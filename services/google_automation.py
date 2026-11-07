"""Google One automation service."""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import platform
import random
import time
import zipfile
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import undetected_chromedriver as uc
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

import config
from core.proxy_manager import (
    mask_proxy_url,
    parse_proxy_parts,
    resolve_runtime_proxy_url,
)
from services.device_simulator import DEVICE_SPECS as SPECS, DeviceProfile
from services.proxy_forwarder import AuthenticatedProxyForwarder
from services.wit_ai_solver import (
    AudioCaptchaSolveError,
    has_audio_captcha_challenge,
    solve_audio_captcha_with_wit_ai,
    wit_ai_is_available,
)

logger = logging.getLogger(__name__)


class GoogleAutomationError(Exception):
    """Raised when automation encounters an unrecoverable error."""


# Proxy helpers


def proxy_server_argument(proxy_url: str) -> str:
    """Return a Chrome --proxy-server value without credentials."""
    proxy = parse_proxy_parts(proxy_url)
    return f"{proxy['scheme']}://{proxy['host']}:{proxy['port']}"


def _proxy_requires_auth(proxy_url: str | None) -> bool:
    """Return True when the proxy URL contains username credentials."""
    if not proxy_url:
        return False
    try:
        proxy = parse_proxy_parts(proxy_url)
    except Exception:
        return False
    return bool(proxy.get("username"))


def build_proxy_auth_extension(proxy_url: str) -> str | None:
    """Return a base64-encoded Chrome extension strictly for proxy authentication."""
    proxy = parse_proxy_parts(proxy_url)
    username = proxy["username"]
    password = proxy["password"]

    if not username:
        return None

    manifest = {
        "version": "1.0.0",
        "manifest_version": 3,
        "name": "AutoPixel Proxy Auth",
        "permissions": [
            "webRequest",
            "webRequestAuthProvider",
        ],
        "host_permissions": [
            "<all_urls>",
        ],
        "background": {
            "service_worker": "background.js",
        },
        "minimum_chrome_version": "120.0.0.0",
    }

    background = f"""
chrome.webRequest.onAuthRequired.addListener(
  (details, callback) => {{
    if (!details.isProxy) {{
      callback({{}});
      return;
    }}

    callback({{
      authCredentials: {{
        username: {json.dumps(username)},
        password: {json.dumps(password or "")}
      }}
    }});
  }},
  {{ urls: ["<all_urls>"] }},
  ["asyncBlocking"]
);
""".strip()

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("background.js", background)

    return base64.b64encode(buffer.getvalue()).decode("ascii")


# Driver factory


def _detect_chrome_binary() -> Optional[str]:
    """Detect a Chrome/Chromium binary across Linux/macOS/Windows."""
    import shutil

    chrome_bin = (
        os.environ.get("CHROME_BIN")
        or shutil.which("chromium")
        or shutil.which("chromium-browser")
        or shutil.which("google-chrome")
        or shutil.which("chrome")
        or shutil.which("chrome.exe")
    )

    if chrome_bin:
        return chrome_bin

    if platform.system() == "Windows":
        win_candidates = [
            os.path.join(os.environ.get("PROGRAMFILES", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
        ]
        for candidate in win_candidates:
            if candidate and os.path.exists(candidate):
                return candidate

    return None


def resolve_browser_binaries() -> tuple[Optional[str], Optional[str]]:
    """Resolve Chrome binary and chromedriver path."""
    import shutil

    chrome_bin = _detect_chrome_binary()
    chromedriver_path = os.environ.get("CHROMEDRIVER_PATH") or shutil.which("chromedriver")
    return chrome_bin, chromedriver_path


def _detect_driver_major_version(chromedriver_path: str | None) -> Optional[int]:
    """Return the detected chromedriver major version, if available."""
    import subprocess

    if not chromedriver_path:
        return None

    try:
        out = subprocess.check_output(
            [chromedriver_path, "--version"],
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).decode("utf-8", errors="replace").strip()
    except Exception:
        return None

    for part in out.split():
        if "." in part and part[0].isdigit():
            try:
                return int(part.split(".")[0])
            except (TypeError, ValueError):
                return None
    return None


def build_driver(
    profile: DeviceProfile,
    headless: Optional[bool] = None,
    proxy_url: str | None = None,
    proxy_session_token: str | None = None,
) -> webdriver.Chrome:
    """Return a Chrome WebDriver configured for the device profile."""
    runtime_proxy_url = resolve_runtime_proxy_url(proxy_url, proxy_session_token)
    options = uc.ChromeOptions()
    options.page_load_strategy = "eager"
    headless_enabled = config.HEADLESS if headless is None else headless

    if headless_enabled:
        options.add_argument("--headless=new")

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-notifications")
    options.add_argument(f"--window-size={SPECS['width']},{SPECS['height']}")
    options.add_argument(f"--user-agent={profile.user_agent}")

    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-features=VizDisplayCompositor")
    options.add_argument("--disable-crash-reporter")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-default-apps")
    options.add_argument("--disable-translate")
    options.add_argument("--no-first-run")
    options.add_argument("--renderer-process-limit=2")
    options.add_argument("--js-flags=--max-old-space-size=512")
    options.add_argument("--disable-ipc-flooding-protection")
    if config.BROWSER_IGNORE_CERT_ERRORS:
        options.add_argument("--ignore-certificate-errors")
        options.add_argument("--ignore-ssl-errors=yes")
        options.set_capability("acceptInsecureCerts", True)
        logger.warning(
            "Browser certificate errors will be ignored for this session because BROWSER_IGNORE_CERT_ERRORS=1."
        )

    chrome_bin, chromedriver_path = resolve_browser_binaries()
    browser_major = config.CHROME_MAJOR_VERSION
    driver_major = _detect_driver_major_version(chromedriver_path)

    if chrome_bin:
        options.binary_location = chrome_bin
        logger.info("Using Chrome binary: %s", chrome_bin)
    else:
        logger.warning(
            "CHROME_BIN not found; relying on Selenium Manager/browser defaults."
        )

    prefs = {
        "webrtc.ip_handling_policy": "disable_non_proxied_udp",
        "webrtc.multiple_routes_enabled": False,
        "webrtc.nonproxied_udp_enabled": False,
        "profile.default_content_setting_values.geolocation": 2,  # Block native geo popup
    }
    options.add_experimental_option("prefs", prefs)
    options.add_argument("--disable-blink-features=AutomationControlled")

    encoded_extension = None
    proxy_forwarder = None
    if runtime_proxy_url:
        if _proxy_requires_auth(runtime_proxy_url):
            proxy_forwarder = AuthenticatedProxyForwarder(runtime_proxy_url).start()
            options.add_argument(f"--proxy-server={proxy_forwarder.local_proxy_url}")
        else:
            options.add_argument(f"--proxy-server={proxy_server_argument(runtime_proxy_url)}")
        logger.info("Using proxy: %s", mask_proxy_url(proxy_url or runtime_proxy_url))

    if not encoded_extension:
        options.add_argument("--disable-extensions")

    driver_kwargs = {
        "options": options,
        "use_subprocess": False,
        "version_main": browser_major,
    }
    if chromedriver_path and driver_major == browser_major:
        logger.info("Using chromedriver: %s", chromedriver_path)
        driver_kwargs["driver_executable_path"] = chromedriver_path
    elif chromedriver_path:
        logger.warning(
            "Ignoring chromedriver %s because major version %s does not match browser major %s.",
            chromedriver_path,
            driver_major if driver_major is not None else "unknown",
            browser_major,
        )
    else:
        logger.warning(
            "CHROMEDRIVER_PATH not found; using undetected-chromedriver fallback."
        )

    if chrome_bin:
        driver_kwargs["browser_executable_path"] = chrome_bin

    try:
        driver = uc.Chrome(**driver_kwargs)
    except Exception:
        if proxy_forwarder:
            proxy_forwarder.stop()
        raise

    setattr(driver, "_autopixel_headless", headless_enabled)
    setattr(driver, "_autopixel_proxy_requires_auth", _proxy_requires_auth(runtime_proxy_url))
    setattr(driver, "_autopixel_proxy_forwarder", proxy_forwarder)

    driver.implicitly_wait(config.IMPLICIT_WAIT)
    driver.set_page_load_timeout(config.PAGE_LOAD_TIMEOUT)

    try:
        driver.execute_cdp_cmd("Network.enable", {})
        driver.execute_cdp_cmd(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": SPECS["width"],
                "height": SPECS["height"],
                "deviceScaleFactor": SPECS["pixel_ratio"],
                "mobile": True,
                "screenWidth": SPECS["device_width"],
                "screenHeight": SPECS["device_height"],
            },
        )
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": profile.navigator_overrides_js()},
        )
        driver.execute_cdp_cmd(
            "Network.setUserAgentOverride",
            {
                "userAgent": profile.user_agent,
                "acceptLanguage": profile.accept_language,
                "platform": "Android",
                "userAgentMetadata": profile.user_agent_metadata(),
            },
        )
        driver.execute_cdp_cmd(
            "Network.setExtraHTTPHeaders",
            {"headers": profile.as_headers()},
        )
        driver.execute_cdp_cmd(
            "Emulation.setTouchEmulationEnabled",
            {"enabled": True, "maxTouchPoints": SPECS["max_touch_points"]},
        )
        try:
            driver.execute_cdp_cmd(
                "Emulation.setLocaleOverride",
                {"locale": profile.locale},
            )
        except Exception as exc:
            logger.debug("Locale override unavailable for this Chrome build: %s", exc)
        driver.execute_cdp_cmd(
            "Emulation.setTimezoneOverride",
            {"timezoneId": profile.timezone_id},
        )
        driver.execute_cdp_cmd(
            "Emulation.setGeolocationOverride",
            {
                "latitude": profile.geolocation_latitude,
                "longitude": profile.geolocation_longitude,
                "accuracy": profile.geolocation_accuracy,
            },
        )
        logger.info(
            "Device emulation configured: %s (Build %s, Chrome %s)",
            profile.model,
            profile.build_id,
            profile.chrome_version,
        )
    except Exception as exc:
        logger.warning("CDP override injection failed (non-fatal): %s", exc)

    return driver


# Login flow


def _driver_is_headless(driver: webdriver.Chrome) -> bool:
    """Return whether this driver instance is running headless."""
    return bool(getattr(driver, "_autopixel_headless", config.HEADLESS))


def _is_google_challenge_url(url: str) -> bool:
    """Return True when Google is still showing a sign-in challenge page."""
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    path = parsed.path or ""
    return hostname == "accounts.google.com" and "challenge" in path


def get_signin_error_text(driver: webdriver.Chrome) -> str | None:
    """Return visible Google sign-in error text when present."""
    selectors = (
        '[jsname="B34EJ"]',
        '[aria-live="assertive"]',
        '[role="alert"]',
    )
    for selector in selectors:
        try:
            element = driver.find_element(By.CSS_SELECTOR, selector)
        except NoSuchElementException:
            continue

        text = " ".join((element.text or "").split())
        if text:
            return text

    return None


def _looks_like_captcha_error_text(text: str | None) -> bool:
    """Return True when Google is asking for an image/text captcha."""
    normalized = " ".join((text or "").lower().split())
    if not normalized:
        return False
    markers = (
        "characters you see in the image above",
        "text you hear or see",
        "enter the characters",
        "captcha",
    )
    return any(marker in normalized for marker in markers)


def get_login_debug_snapshot(driver: webdriver.Chrome) -> dict[str, str]:
    """Return a small snapshot of the current login page for diagnostics."""
    current_url = ""
    title = ""
    excerpt = ""

    try:
        current_url = driver.current_url or ""
    except Exception:
        current_url = ""

    try:
        title = " ".join((driver.title or "").split())
    except Exception:
        title = ""

    selectors = ("body", "main", '[role="main"]')
    for selector in selectors:
        try:
            element = driver.find_element(By.CSS_SELECTOR, selector)
        except NoSuchElementException:
            continue

        text = " ".join((element.text or "").split())
        if text:
            excerpt = text[:240]
            break

    return {
        "url": current_url,
        "title": title,
        "excerpt": excerpt,
    }


def _looks_like_privacy_error_snapshot(snapshot: dict[str, str]) -> bool:
    """Return True when Chrome is showing its certificate/privacy interstitial."""
    title = (snapshot.get("title") or "").lower()
    excerpt = (snapshot.get("excerpt") or "").lower()
    url = (snapshot.get("url") or "").lower()
    return any(
        marker in f"{title} {excerpt} {url}"
        for marker in (
            "privacy error",
            "your connection is not private",
            "net::err_cert_authority_invalid",
        )
    )


def _looks_like_proxy_policy_block_snapshot(snapshot: dict[str, str]) -> bool:
    """Return True when the page body looks like a generic proxy access-policy block."""
    title = (snapshot.get("title") or "").lower()
    excerpt = (snapshot.get("excerpt") or "").lower()
    url = (snapshot.get("url") or "").lower()
    combined = f"{title} {excerpt} {url}"
    return any(
        marker in combined
        for marker in (
            "bad_endpoint",
            "policy_20130",
            "policy_20140",
            "access mode",
            "blocked by proxy",
        )
    )


def _summarize_snapshot_excerpt(snapshot: dict[str, str], limit: int = 180) -> str:
    """Return a short single-line excerpt for user-facing error messages."""
    excerpt = " ".join((snapshot.get("excerpt") or "").split())
    if not excerpt:
        return ""
    if len(excerpt) <= limit:
        return excerpt
    return excerpt[: limit - 3].rstrip() + "..."


def get_google_login_state(driver: webdriver.Chrome) -> str:
    """Return a coarse login state for the current Google page."""
    parsed = urlparse(driver.current_url)
    hostname = parsed.hostname or ""
    path = parsed.path or ""

    if _is_google_challenge_url(driver.current_url):
        if _is_totp_challenge(driver):
            return "needs_totp"
        return "challenge"

    if hostname == "accounts.google.com" and path.startswith("/signin"):
        return "signin"

    if hostname == "myaccount.google.com":
        return "success"

    if hostname.endswith(".google.com") and "/u/" in path:
        return "success"

    if hostname.endswith(".google.com") and "signin" not in path:
        return "success"

    return "unknown"


def wait_for_login_resolution(driver: webdriver.Chrome, timeout: int = 10) -> str:
    """Wait briefly for Google to leave the sign-in/challenge flow."""
    deadline = time.time() + timeout
    state = get_google_login_state(driver)

    while time.time() < deadline and state in {"challenge", "signin"}:
        time.sleep(0.5)
        state = get_google_login_state(driver)

    return state


def _has_totp_error(driver: webdriver.Chrome) -> bool:
    """Best-effort detection of inline TOTP errors on the Google challenge page."""
    try:
        page_text = driver.page_source.lower()
    except Exception:
        return False

    error_indicators = (
        "wrong code",
        "incorrect code",
        "invalid code",
        "enter a valid code",
        "couldn't verify",
        "could not verify",
        "try again",
        "expired code",
    )
    return any(indicator in page_text for indicator in error_indicators)


def _is_totp_challenge(driver: webdriver.Chrome) -> bool:
    """Return True only when the challenge page really looks like TOTP input."""
    specific_selectors = ('input[name="totpPin"]', "#totpPin")
    for selector in specific_selectors:
        try:
            driver.find_element(By.CSS_SELECTOR, selector)
            return True
        except NoSuchElementException:
            continue

    try:
        driver.find_element(By.CSS_SELECTOR, 'input[type="tel"]')
    except NoSuchElementException:
        return False

    page_text = driver.page_source.lower()
    positive_indicators = (
        "authenticator",
        "google authenticator",
        "verification code",
        "6-digit",
        "6 digit",
        "enter the code",
        "totp",
    )
    negative_indicators = (
        "security key",
        "usb",
        "phone",
        "sms",
        "tap yes",
        "google prompt",
    )

    return (
        any(indicator in page_text for indicator in positive_indicators)
        and not any(indicator in page_text for indicator in negative_indicators)
    )


def _try_wit_ai_audio_captcha(driver: webdriver.Chrome, stage_label: str) -> bool:
    """Best-effort solve for visible audio captcha challenges."""
    if not wit_ai_is_available():
        return False

    try:
        solved = solve_audio_captcha_with_wit_ai(driver)
    except AudioCaptchaSolveError as exc:
        logger.warning("Wit.ai audio captcha solver failed during %s: %s", stage_label, exc)
        return False
    except Exception as exc:
        logger.warning(
            "Unexpected Wit.ai audio captcha error during %s: %s",
            stage_label,
            exc,
        )
        return False

    if solved:
        logger.info("Wit.ai audio captcha submitted during %s.", stage_label)
    return solved


def _resolve_post_password_state(driver: webdriver.Chrome, email: str) -> str:
    """Resolve the Google login state after password submission with retries."""
    deadline = time.time() + 15
    last_exc: Exception | None = None
    captcha_solver_attempted = False

    while time.time() < deadline:
        try:
            current_url = driver.current_url
            parsed = urlparse(current_url)
            hostname = parsed.hostname or ""
            path = parsed.path or ""

            challenge_paths = ("/signin/v2/challenge", "/signin/challenge", "/v2/challenge")
            if hostname == "accounts.google.com" and any(p in path for p in challenge_paths):
                if _is_totp_challenge(driver):
                    logger.info("TOTP 2FA challenge confirmed for %s - awaiting code", email)
                    return "needs_totp"

                if (
                    not captcha_solver_attempted
                    and wit_ai_is_available()
                    and has_audio_captcha_challenge(driver)
                ):
                    captcha_solver_attempted = True
                    if _try_wit_ai_audio_captcha(driver, "post-password challenge"):
                        time.sleep(2)
                        continue

                switched_to_totp = False
                try:
                    for opt_xpath in (
                        '//*[@data-challengetype="6"]',
                        '//div[@data-challengetype="6"]',
                        '//div[contains(text(), "Authenticator")]',
                        '//div[contains(text(), "authenticator")]',
                        '//div[contains(text(), "Google Authenticator")]',
                        '//div[contains(text(), "verification code")]',
                        '//li[contains(., "Authenticator")]',
                        '//li[contains(., "authenticator")]',
                    ):
                        try:
                            driver.find_element(By.XPATH, opt_xpath).click()
                            time.sleep(2)
                            switched_to_totp = True
                            break
                        except NoSuchElementException:
                            continue

                    if not switched_to_totp:
                        for selector in (
                            '//a[contains(text(), "another way")]',
                            '//button[contains(text(), "another way")]',
                            '//a[contains(text(), "other way")]',
                            '//a[contains(text(), "Try another")]',
                            '//span[contains(text(), "another way")]/ancestor::a',
                            '//span[contains(text(), "another way")]/ancestor::button',
                        ):
                            try:
                                try_another = driver.find_element(By.XPATH, selector)
                                try_another.click()
                                time.sleep(2)
                                break
                            except NoSuchElementException:
                                continue

                        for opt_xpath in (
                            '//*[@data-challengetype="6"]',
                            '//div[@data-challengetype="6"]',
                            '//div[contains(text(), "Authenticator")]',
                            '//div[contains(text(), "authenticator")]',
                            '//div[contains(text(), "Google Authenticator")]',
                            '//div[contains(text(), "verification code")]',
                            '//li[contains(., "Authenticator")]',
                        ):
                            try:
                                driver.find_element(By.XPATH, opt_xpath).click()
                                time.sleep(1)
                                switched_to_totp = True
                                break
                            except NoSuchElementException:
                                continue

                    if switched_to_totp and _is_totp_challenge(driver):
                        return "needs_totp"
                except Exception as exc:
                    logger.warning("Error trying alternative 2FA: %s", exc)

                page_text = driver.page_source.lower()
                if (
                    "text you hear or see" in page_text
                    or "characters you see in the image above" in page_text
                    or "enter the characters" in page_text
                    or "captcha" in page_text
                ):
                    challenge_type = "captcha / audio verification"
                elif "security key" in page_text or "usb" in page_text:
                    challenge_type = "security key"
                elif "phone" in page_text or "sms" in page_text:
                    challenge_type = "SMS / phone verification"
                elif "tap yes" in page_text or "google prompt" in page_text:
                    challenge_type = "Google prompt (tap Yes on your phone)"
                else:
                    challenge_type = "two-step verification"

                if not _driver_is_headless(driver):
                    setattr(driver, "_autopixel_challenge_type", challenge_type)
                    logger.info(
                        "Manual verification required for %s: %s",
                        email,
                        challenge_type,
                    )
                    return "needs_manual_verification"

                raise GoogleAutomationError(
                    f"Your account requires {challenge_type}. "
                    f"No authenticator option found. "
                    f"Please use an App Password instead."
                )

            if hostname == "myaccount.google.com" or (hostname.endswith(".google.com") and "/u/" in path):
                return "success"

            if get_signin_error_text(driver):
                return "failed"

            if not (hostname == "accounts.google.com" and path.startswith("/signin")):
                return "success"

            time.sleep(0.5)
        except StaleElementReferenceException as exc:
            last_exc = exc
            time.sleep(0.5)
        except WebDriverException as exc:
            last_exc = exc
            time.sleep(0.5)

    if last_exc:
        logger.warning("Transient WebDriver issue while resolving login state: %s", last_exc)
    raise GoogleAutomationError(
        "Timed out while waiting for Google sign-in to continue. "
        "This usually points to a proxy/network issue or an unsupported challenge."
    )


def wait_for(
    driver: webdriver.Chrome,
    by: str,
    value: str,
    timeout: int = config.WEBDRIVER_TIMEOUT,
) -> WebElement:
    """Return element after waiting for it to be clickable."""
    return WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((by, value)))


def wait_for_any(
    driver: webdriver.Chrome,
    selectors: tuple[tuple[str, str], ...],
    timeout: int = config.WEBDRIVER_TIMEOUT,
) -> WebElement:
    """Return the first visible element that matches any selector."""
    deadline = time.time() + timeout
    last_error: Exception | None = None

    while time.time() < deadline:
        for by, value in selectors:
            try:
                element = driver.find_element(by, value)
            except NoSuchElementException as exc:
                last_error = exc
                continue

            try:
                if element.is_displayed():
                    return element
            except StaleElementReferenceException as exc:
                last_error = exc
                continue
        time.sleep(0.5)

    raise TimeoutException(str(last_error) if last_error else "No matching visible element found.")


def _send_keys_human_like(
    element: WebElement,
    value: str,
    delay_min: float = 0.05,
    delay_max: float = 0.2,
) -> None:
    """Type text one character at a time with small randomized delays."""
    for char in value:
        element.send_keys(char)
        time.sleep(random.uniform(delay_min, delay_max))


def _type_into_any(
    driver: webdriver.Chrome,
    selectors: tuple[tuple[str, str], ...],
    value: str,
    description: str,
    attempts: int = 4,
    timeout: int = config.WEBDRIVER_TIMEOUT,
    delay_min: float = 0.05,
    delay_max: float = 0.2,
) -> None:
    """Find an input field and type into it, retrying when Google rerenders."""
    last_exc: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            field = wait_for_any(driver, selectors, timeout=timeout)
            field.clear()
            _send_keys_human_like(field, value, delay_min=delay_min, delay_max=delay_max)
            return
        except StaleElementReferenceException as exc:
            last_exc = exc
            logger.warning(
                "Stale element while typing into %s, retrying (%d/%d)",
                description,
                attempt,
                attempts,
            )
            time.sleep(0.6)

    raise GoogleAutomationError(
        f"{description.capitalize()} became unstable while typing. Please retry the session."
    ) from last_exc


def _click_element(
    driver: webdriver.Chrome,
    by: str,
    value: str,
    description: str,
    attempts: int = 4,
    timeout: int = config.WEBDRIVER_TIMEOUT,
) -> None:
    """Click an element with stale-element retries and a JS fallback."""
    last_exc: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            element = wait_for(driver, by, value, timeout=timeout)
            try:
                element.click()
            except WebDriverException:
                driver.execute_script("arguments[0].click();", element)
            return
        except StaleElementReferenceException as exc:
            last_exc = exc
            logger.warning(
                "Stale element while clicking %s, retrying (%d/%d)",
                description,
                attempt,
                attempts,
            )
            time.sleep(0.6)

    raise GoogleAutomationError(
        f"{description.capitalize()} became unstable while clicking. Please retry the session."
    ) from last_exc


def _stop_page_load(driver: webdriver.Chrome) -> None:
    """Best-effort stop for a page that is still loading after a timeout."""
    try:
        driver.execute_script("window.stop();")
    except Exception:
        pass


def _wait_for_password_stage(driver: webdriver.Chrome) -> WebElement | None:
    """Wait for Google's password step, failing faster when sign-in never advances."""
    selectors = (
        (By.CSS_SELECTOR, 'input[type="password"]'),
        (By.CSS_SELECTOR, 'input[name="Passwd"]'),
        (By.CSS_SELECTOR, 'input[autocomplete="current-password"]'),
    )
    deadline = time.time() + config.GOOGLE_PASSWORD_STAGE_TIMEOUT_SECONDS
    re_clicked_identifier_next = False
    captcha_solver_attempted = False

    while time.time() < deadline:
        for by, value in selectors:
            try:
                element = driver.find_element(by, value)
            except NoSuchElementException:
                continue
            if element.is_displayed():
                return element

        detail = get_signin_error_text(driver)
        captcha_detected = bool(detail and _looks_like_captcha_error_text(detail))
        audio_captcha_detected = False
        if not captcha_detected and not captcha_solver_attempted and wit_ai_is_available():
            audio_captcha_detected = has_audio_captcha_challenge(driver)
            captcha_detected = audio_captcha_detected

        if captcha_detected:
            challenge_type = (
                "captcha / audio verification"
                if audio_captcha_detected
                else "captcha / image verification"
            )
            if not captcha_solver_attempted:
                captcha_solver_attempted = True
                if _try_wit_ai_audio_captcha(driver, "pre-password challenge"):
                    time.sleep(2)
                    continue

            if not _driver_is_headless(driver):
                setattr(driver, "_autopixel_challenge_type", challenge_type)
                logger.info(
                    "Manual verification required before password step: %s",
                    challenge_type,
                )
                return None
            raise GoogleAutomationError(
                "Google requested captcha / image verification before the password step."
            )

        if detail:
            raise GoogleAutomationError(f"Google sign-in rejected the login: {detail}")

        # Google sometimes stays on the identifier step even after the first click.
        try:
            identifier = driver.find_element(By.CSS_SELECTOR, 'input[name="identifier"]')
            if identifier.is_displayed() and not re_clicked_identifier_next:
                try:
                    driver.find_element(By.ID, "identifierNext").click()
                    re_clicked_identifier_next = True
                except Exception:
                    pass
        except NoSuchElementException:
            pass

        time.sleep(0.5)

    snapshot = get_login_debug_snapshot(driver)
    if "/signin/" in (snapshot.get("url") or "") and "email or phone" in (
        (snapshot.get("excerpt") or "").lower()
    ):
        raise GoogleAutomationError(
            "Google sign-in did not advance from the email step to the password step. "
            "This can happen when Google is still evaluating the session, the page is loading slowly, "
            "or an intermediate prompt/captcha is blocking progress."
        )

    raise TimeoutException("Password field did not appear in time.")


def gmail_login(driver: webdriver.Chrome, email: str, password: str) -> str:
    """Perform Google login and return status: success, failed, or needs_totp."""
    try:
        driver.implicitly_wait(0)
        proxy_requires_auth = bool(
            getattr(driver, "_autopixel_proxy_requires_auth", False)
        )
        email_selectors = (
            (By.CSS_SELECTOR, 'input[type="email"]'),
            (By.CSS_SELECTOR, 'input[name="identifier"]'),
            (By.CSS_SELECTOR, 'input[autocomplete="username"]'),
        )

        if proxy_requires_auth:
            logger.info(
                "Authenticated proxy detected; waiting on a local init page so the auth extension can settle before the first external request."
            )
            driver.get("data:text/html,<title>AutoPixel Init</title><body>proxy-init</body>")
            time.sleep(3.5)
        else:
            # --- MULAI INJEKSI WARM-UP ---
            logger.info("Melakukan pemanasan profil (warm-up) sebelum login...")
            try:
                driver.set_page_load_timeout(10)
                driver.get("https://www.google.com/")
                time.sleep(random.uniform(2.0, 3.0))
            except Exception as exc:
                logger.warning("Pemanasan profil terhenti atau timeout; melanjutkan: %s", exc)
                _stop_page_load(driver)
            finally:
                driver.set_page_load_timeout(config.PAGE_LOAD_TIMEOUT)
            # --- AKHIR INJEKSI WARM-UP ---

        try:
            driver.get(config.GMAIL_LOGIN_URL)
        except TimeoutException as exc:
            logger.warning(
                "Google sign-in page load timed out before full completion; attempting to continue: %s",
                exc,
            )
            _stop_page_load(driver)
        time.sleep(3)

        for retry in range(3):
            try:
                _type_into_any(
                    driver,
                    email_selectors,
                    email,
                    "email field",
                    attempts=3,
                )
                break
            except StaleElementReferenceException:
                logger.warning("Stale element on email field, retrying (%d/3)", retry + 1)
                time.sleep(1)
        else:
            raise GoogleAutomationError("Email field stale after 3 retries")

        _click_element(driver, By.ID, "identifierNext", "email next button")
        time.sleep(1)

        password_field = _wait_for_password_stage(driver)
        if password_field is None:
            return "needs_manual_verification"
        _type_into_any(
            driver,
            (
                (By.CSS_SELECTOR, 'input[type="password"]'),
                (By.CSS_SELECTOR, 'input[name="Passwd"]'),
                (By.CSS_SELECTOR, 'input[autocomplete="current-password"]'),
            ),
            password,
            "password field",
        )
        _click_element(driver, By.ID, "passwordNext", "password next button")
        time.sleep(2)
        return _resolve_post_password_state(driver, email)

    except TimeoutException as exc:
        snapshot = get_login_debug_snapshot(driver)
        logger.error(
            "Timeout during login: %s | url=%s | title=%s | excerpt=%s",
            exc,
            snapshot["url"] or "-",
            snapshot["title"] or "-",
            snapshot["excerpt"] or "-",
        )
        if _looks_like_proxy_policy_block_snapshot(snapshot):
            summary = _summarize_snapshot_excerpt(snapshot)
            raise GoogleAutomationError(
                "The proxy provider blocked this Google target by policy. This page is coming "
                "from the proxy, not from Google. Try rotating to a different proxy from the "
                "pool or switching to direct mode."
                + (f" Detail: {summary}" if summary else "")
            ) from exc
        if _looks_like_privacy_error_snapshot(snapshot):
            raise GoogleAutomationError(
                "Chrome stopped at a privacy/certificate error before the Google sign-in page loaded. "
                "Check the proxy certificate chain or, for temporary testing only, set "
                "BROWSER_IGNORE_CERT_ERRORS=1."
            ) from exc
        detail = ""
        if snapshot["title"] or snapshot["excerpt"]:
            detail = (
                f" Current page: {snapshot['title'] or '(untitled)'}"
                f" | URL: {snapshot['url'] or '-'}"
            )
        raise GoogleAutomationError(
            "Timed out while loading the Google sign-in page. "
            "This usually points to a proxy/network issue or an unexpected Google page."
            f"{detail}"
        ) from exc
    except WebDriverException as exc:
        logger.error("WebDriver error during login: %s", exc)
        raise GoogleAutomationError(
            f"Browser/network error during login: {exc.__class__.__name__}"
        ) from exc


def submit_totp_code(driver: webdriver.Chrome, code: str) -> bool:
    """Enter TOTP/authenticator code and return True when accepted."""
    try:
        totp_field = None
        for selector in (
            'input[type="tel"]',
            'input[name="totpPin"]',
            '#totpPin',
            'input[type="text"]',
        ):
            try:
                totp_field = WebDriverWait(driver, 2).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                )
                if totp_field:
                    break
            except TimeoutException:
                continue

        if not totp_field:
            return False

        totp_field.clear()
        for char in code:
            totp_field.send_keys(char)
            time.sleep(random.uniform(0.1, 0.3))
        time.sleep(0.5)

        for btn_selector in (
            "#totpNext",
            'button[jsname="LgbsSe"]',
            '[data-action="verify"]',
            'button[type="submit"]',
        ):
            try:
                driver.find_element(By.CSS_SELECTOR, btn_selector).click()
                break
            except NoSuchElementException:
                continue

        deadline = time.time() + 15
        while time.time() < deadline:
            current_url = driver.current_url
            if not _is_google_challenge_url(current_url):
                return True
            if _has_totp_error(driver):
                return False
            time.sleep(0.5)

        return not _is_google_challenge_url(driver.current_url)
    except Exception as exc:
        logger.error("Error submitting TOTP code: %s", exc)
        return False


# Offer scanning


def diagnose_google_one_page(driver: webdriver.Chrome) -> str | None:
    """Return a short diagnosis string for the current Google One page."""
    try:
        page_source = driver.page_source.lower()
    except Exception:
        return None

    paid_ai_markers = (
        "google ai pro",
        "ai premium",
        "g1.2tb.ai",
        "g1.2tb.ai.annual",
    )
    free_offer_markers = (
        "partner-eft-onboard",
        "bard_advanced",
        "claim offer",
        "redeem",
        "free trial",
        "12-month",
        "12 month",
        "freetrial",
        "freetrialperiod",
        "start trial",
        "mulai uji coba",
        "$0/bln",
        "selama 1 bulan",
        "data-sku-id=\"g1.2tb.ai.1month_eft\"",
        "data-sku-id=\"g1.2tb.1month_eft\"",
    )

    if any(marker in page_source for marker in free_offer_markers):
        if any(marker in page_source for marker in paid_ai_markers):
            return (
                "Google One shows an embedded Google AI trial offer on the plans page, "
                "but AutoPixel did not capture the checkout link automatically."
            )
        return (
            "Google One shows an embedded free-trial offer on the plans page, "
            "but AutoPixel did not capture the checkout link automatically."
        )

    if any(marker in page_source for marker in paid_ai_markers):
        return (
            "Google One shows regular paid Google AI Pro plans for this account, "
            "but no free promo claim link was present."
        )

    if "paket anda saat ini" in page_source or "your current plan" in page_source:
        return "Google One loaded your normal account plan page, but no promo card was present."

    return None


def is_correct_offer_url(url: str) -> bool:
    """Return True for expected Pixel Gemini offer claim URL pattern."""
    return bool(url) and "partner-eft-onboard" in url


def _looks_like_checkout_url(url: str) -> bool:
    """Return True when the URL looks like a Google subscription checkout flow."""
    normalized = (url or "").lower()
    return any(
        marker in normalized
        for marker in (
            "partner-eft-onboard",
            "subscriptions/checkout",
            "store.google.com/subscriptions/checkout",
            "play.google.com",
            "tokenized.play.google.com",
            "purchase",
            "buy",
        )
    )


def _trial_button_priority(button: WebElement) -> tuple[int, str]:
    """Rank trial buttons so AI/Gemini-related monthly trials are preferred."""
    sku_id = (button.get_attribute("data-sku-id") or "").lower()
    label = " ".join(
        part
        for part in (
            button.get_attribute("aria-label") or "",
            button.text or "",
            button.get_attribute("data-formatted-price") or "",
        )
    ).lower()

    score = 0
    if ".ai." in sku_id or "ai pro" in label or "gemini" in label:
        score += 100
    if "2tb" in sku_id or "2 tb" in label:
        score += 30
    if "1month" in sku_id or "trial" in label or "uji coba" in label:
        score += 10
    return (-score, sku_id)


def _capture_checkout_after_trial_click(
    driver: webdriver.Chrome,
    button: WebElement,
) -> Optional[str]:
    """Click a Google One trial button and try to capture the checkout URL."""
    before_url = driver.current_url
    before_handles = list(driver.window_handles)

    try:
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center', inline:'center'});",
            button,
        )
    except Exception:
        pass

    time.sleep(0.6)
    try:
        button.click()
    except Exception:
        try:
            driver.execute_script("arguments[0].click();", button)
        except Exception as exc:
            logger.warning("Failed to click Google One trial button: %s", exc)
            return None

    deadline = time.time() + 12
    while time.time() < deadline:
        try:
            current_handles = list(driver.window_handles)
        except Exception:
            current_handles = before_handles

        if len(current_handles) > len(before_handles):
            try:
                driver.switch_to.window(current_handles[-1])
            except Exception:
                pass

        try:
            current_url = driver.current_url
        except Exception:
            current_url = ""

        if current_url and current_url != before_url and _looks_like_checkout_url(current_url):
            return current_url

        try:
            iframes = driver.find_elements(By.TAG_NAME, "iframe")
            for frame in iframes:
                src = (frame.get_attribute("src") or "").strip()
                if src and _looks_like_checkout_url(src):
                    return src
        except Exception:
            pass

        time.sleep(0.5)

    return None


def extract_trial_button_link(driver: webdriver.Chrome) -> Optional[str]:
    """Try to launch a Google One trial checkout from page buttons."""
    try:
        buttons = driver.find_elements(By.CSS_SELECTOR, "button[data-sku-id]")
    except Exception:
        return None

    candidates: list[WebElement] = []
    for button in buttons:
        try:
            sku_id = (button.get_attribute("data-sku-id") or "").lower()
            label = " ".join(
                part
                for part in (
                    button.get_attribute("aria-label") or "",
                    button.text or "",
                    button.get_attribute("data-formatted-price") or "",
                )
            ).lower()
        except StaleElementReferenceException:
            continue

        if not sku_id:
            continue
        if (
            "1month" in sku_id
            or "trial" in label
            or "uji coba" in label
            or "start trial" in label
        ):
            candidates.append(button)

    for button in sorted(candidates, key=_trial_button_priority):
        link = _capture_checkout_after_trial_click(driver, button)
        if link:
            return link

    return None


def extract_payment_link(driver: webdriver.Chrome) -> Optional[str]:
    """Scan current page for Gemini Pro offer activation link."""
    all_links = driver.find_elements(By.TAG_NAME, "a")

    for link in all_links:
        try:
            href = link.get_attribute("href") or ""
            if is_correct_offer_url(href):
                return href
        except Exception:
            continue

    trial_link = extract_trial_button_link(driver)
    if trial_link:
        return trial_link

    keywords = config.GEMINI_OFFER_KEYWORDS
    for link in all_links:
        try:
            text = (link.text + " " + (link.get_attribute("aria-label") or "")).lower()
            href = link.get_attribute("href") or ""
            if "LOCKED" in href:
                continue
            if any(keyword in text for keyword in keywords) and is_correct_offer_url(href):
                return href
        except Exception:
            continue

    for link in all_links:
        try:
            href = link.get_attribute("href") or ""
            if is_correct_offer_url(href):
                return href
        except Exception:
            continue

    for link in all_links:
        try:
            href = link.get_attribute("href") or ""
            if "LOCKED" not in href or "BARD_ADVANCED" not in href:
                continue

            old_url = driver.current_url
            driver.execute_script("arguments[0].click();", link)
            time.sleep(5)
            current_url = driver.current_url

            if is_correct_offer_url(current_url):
                return current_url
            if current_url != old_url and _looks_like_checkout_url(current_url):
                return current_url
            if "LOCKED" in current_url:
                try:
                    driver.back()
                    time.sleep(1.5)
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("Error clicking LOCKED link: %s", exc)
            continue

    return None


def navigate_google_one(driver: webdriver.Chrome) -> Optional[str]:
    """Navigate Google One pages and attempt to find the offer link."""
    for url in (config.GOOGLE_ONE_OFFERS_URL, config.GOOGLE_ONE_URL):
        try:
            logger.info("Navigating to %s", url)
            driver.get(url)
            time.sleep(3)

            for selector in (
                '[aria-label="Accept all"]',
                'button[jsname="higCR"]',
                '[data-action="accept"]',
            ):
                try:
                    driver.find_element(By.CSS_SELECTOR, selector).click()
                    time.sleep(1)
                    break
                except NoSuchElementException:
                    continue

            link = extract_payment_link(driver)
            if link:
                return link
        except (TimeoutException, WebDriverException) as exc:
            logger.warning("Error accessing %s: %s", url, exc)

    return None


# Public API


def dump_offer_debug_artifacts(
    driver,
    chat_id: int,
    attempt: int | None = None,
    session_id: str | None = None,
) -> dict[str, str]:
    """Persist screenshot + page HTML for a no-offer debugging snapshot."""
    project_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    dump_dir = os.path.join(project_root, "logs", "offer_debug", f"chat_{chat_id}")
    os.makedirs(dump_dir, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    token = (session_id or "nosession").replace("-", "")[:8]
    suffix = f"_attempt{attempt}" if attempt is not None else ""
    basename = f"{timestamp}_session_{token}{suffix}"

    screenshot_path = os.path.join(dump_dir, f"{basename}.png")
    html_path = os.path.join(dump_dir, f"{basename}.html")

    artifacts: dict[str, str] = {}
    current_url = ""
    try:
        current_url = driver.current_url or ""
    except Exception:
        current_url = ""

    try:
        driver.save_screenshot(screenshot_path)
        artifacts["screenshot"] = screenshot_path
    except Exception as exc:
        logger.warning("Failed to save no-offer screenshot for chat %s: %s", chat_id, exc)

    try:
        page_source = driver.page_source
        with open(html_path, "w", encoding="utf-8") as handle:
            if current_url:
                handle.write(f"<!-- URL: {current_url} -->\n")
            handle.write(page_source)
        artifacts["html"] = html_path
    except Exception as exc:
        logger.warning("Failed to save no-offer HTML for chat %s: %s", chat_id, exc)

    if artifacts:
        logger.info("Saved no-offer debug artifacts for chat %s", chat_id)

    return artifacts


def start_login(
    email: str,
    password: str,
    device: DeviceProfile,
    headless: bool | None = None,
    proxy_url: str | None = None,
    proxy_session_token: str | None = None,
) -> tuple:
    """Start login process and return (driver, status)."""
    runtime_proxy_url = resolve_runtime_proxy_url(proxy_url, proxy_session_token)
    proxy_requires_auth = _proxy_requires_auth(runtime_proxy_url)
    effective_headless = config.HEADLESS if headless is None else headless
    if (
        effective_headless
        and proxy_requires_auth
        and config.START_VISIBLE_WITH_AUTH_PROXY
    ):
        logger.info(
            "Authenticated proxy detected for session %s; starting directly in visible mode.",
            device.session_id,
        )
        effective_headless = False
    logger.info(
        "Starting WebDriver for session %s (headless=%s)",
        device.session_id,
        effective_headless,
    )
    driver = build_driver(
        device,
        headless=effective_headless,
        proxy_url=proxy_url,
        proxy_session_token=proxy_session_token,
    )

    try:
        status = gmail_login(driver, email, password)
        if status == "failed":
            detail = get_signin_error_text(driver)
            close_driver(driver)
            if detail:
                raise GoogleAutomationError(f"Google sign-in rejected the login: {detail}")
            raise GoogleAutomationError(
                "Google sign-in rejected the login. "
                "This can be caused by invalid credentials, account protection, or proxy issues."
            )
        return driver, status
    except GoogleAutomationError as exc:
        should_retry_visible = (
            effective_headless
            and proxy_requires_auth
            and (
                "Timed out while loading the Google sign-in page" in str(exc)
                or "captcha / image verification" in str(exc).lower()
            )
        )
        if should_retry_visible:
            logger.warning(
                "Headless login hit a retryable Google/proxy barrier for session %s; retrying in visible mode.",
                device.session_id,
            )
            close_driver(driver)
            retry_driver = build_driver(
                device,
                headless=False,
                proxy_url=proxy_url,
                proxy_session_token=proxy_session_token,
            )
            try:
                status = gmail_login(retry_driver, email, password)
                if status == "failed":
                    detail = get_signin_error_text(retry_driver)
                    close_driver(retry_driver)
                    if detail:
                        raise GoogleAutomationError(
                            f"Google sign-in rejected the login: {detail}"
                        )
                    raise GoogleAutomationError(
                        "Google sign-in rejected the login after visible-mode retry. "
                        "This can be caused by invalid credentials, account protection, or proxy issues."
                    )
                return retry_driver, status
            except GoogleAutomationError:
                close_driver(retry_driver)
                raise
            except Exception:
                close_driver(retry_driver)
                raise
        close_driver(driver)
        raise
    except Exception:
        close_driver(driver)
        raise


def submit_2fa_code(driver, code: str) -> bool:
    """Submit TOTP code on a driver that is on the 2FA challenge page."""
    return submit_totp_code(driver, code)


def resolve_manual_login(driver, timeout: int = 10) -> str:
    """Wait briefly for a manual Google verification step to finish."""
    return wait_for_login_resolution(driver, timeout=timeout)


def check_offer_with_driver(driver) -> Optional[str]:
    """Navigate to Google One and find the Gemini Pro offer link."""
    return navigate_google_one(driver)


def diagnose_offer_page(driver) -> str | None:
    """Return a short diagnosis for the currently loaded Google One page."""
    return diagnose_google_one_page(driver)


def close_driver(driver) -> None:
    """Safely close WebDriver instance."""
    if driver:
        try:
            driver.quit()
        except Exception:
            pass
        forwarder = getattr(driver, "_autopixel_proxy_forwarder", None)
        if forwarder:
            try:
                forwarder.stop()
            except Exception:
                pass


__all__ = [
    "GoogleAutomationError",
    "start_login",
    "submit_2fa_code",
    "resolve_manual_login",
    "check_offer_with_driver",
    "diagnose_offer_page",
    "dump_offer_debug_artifacts",
    "close_driver",
]
