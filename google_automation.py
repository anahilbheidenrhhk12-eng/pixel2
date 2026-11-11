"""
Google One automation using Selenium.

Logs into a Gmail account, navigates to Google One, detects the
12-month free Gemini Pro offer, and returns the activation / payment link.

progress_callback(msg, screenshot_bytes=None) is called at every key step
so callers can relay updates to Telegram in real time.
"""

import io
import logging
import os
import re
import shutil
import time
from typing import Callable, Optional
from urllib.parse import urlparse

import pyotp
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

import config
from device_simulator import DeviceProfile
from google_one_plan import open_annual_ai_pro_checkout, open_add_card_dialog

logger = logging.getLogger(__name__)

ProgressCB = Optional[Callable[[str, Optional[bytes]], None]]


# ── Screenshot helper ─────────────────────────────────────────────────────────

def _shot(driver: webdriver.Chrome, crop_bottom: bool = False) -> Optional[bytes]:
    """Return a PNG screenshot as bytes, or None on failure."""
    try:
        payload = driver.get_screenshot_as_png()
        if crop_bottom:
            from screenshot_crop import crop_stage_six
            return crop_stage_six(payload)
        return payload
    except Exception:
        return None


def _report(cb: ProgressCB, msg: str, driver: Optional[webdriver.Chrome] = None, *, crop_bottom: bool = False) -> None:
    """Send a progress message (and optional screenshot) via the callback."""
    logger.info(msg)
    if cb:
        screenshot = _shot(driver, crop_bottom=crop_bottom) if driver and getattr(cb, "capture_screenshots", True) else None
        try:
            cb(msg, screenshot)
        except Exception as e:
            logger.warning("progress_callback error: %s", e)


def _find_executable(env_name: str, names: tuple[str, ...]) -> Optional[str]:
    """Resolve a configured binary or installed command to an absolute path."""
    env_value = os.environ.get(env_name, "").strip()
    if env_value:
        candidate = os.path.expanduser(env_value)
        candidate = shutil.which(candidate) or candidate
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return os.path.abspath(candidate)
        raise RuntimeError(f"{env_name} points to a missing or non-executable file: {env_value}")
    for name in names:
        path = shutil.which(name)
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return os.path.abspath(path)
    return None


# ── Driver factory ────────────────────────────────────────────────────────────

def _build_driver(profile: DeviceProfile, display_override: Optional[str] = None) -> webdriver.Chrome:
    """Launch Chrome emulating the given mobile device (Pixel 11 Pro by
    default) — real Android Chrome UA/client-hints via CDP, matching screen
    geometry, and the navigator/WebGL/battery fingerprint from device_simulator.py."""
    options = Options()
    options.page_load_strategy = "normal"  # Restore the original complete-page loading behavior.

    if config.HEADLESS and not display_override:
        options.add_argument("--headless=new")

    if getattr(config, "PROXY", None):
        options.add_argument(f"--proxy-server={config.PROXY}")

    # ── Core stability flags ──────────────────────────────────────────────────
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    from admin_store import STORE
    extension_paths = STORE.extensions()
    if extension_paths:
        options.add_argument('--load-extension=' + ','.join(extension_paths))
        options.add_argument('--disable-extensions-except=' + ','.join(extension_paths))
    else:
        options.add_argument('--disable-extensions')
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-notifications")
    options.add_argument("--mute-audio")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-sync")
    options.add_argument("--metrics-recording-only")
    options.add_argument("--js-flags=--max-old-space-size=512")
    options.add_argument("--renderer-process-limit=1")

    # ── Realism flags (match a real Chrome on Android) ────────────────────────
    options.add_argument("--enable-features=NetworkService,NetworkServiceInProcess")
    options.add_argument("--lang=en-US")

    # ── Mobile viewport (CSS pixels; CDP sets the real device scale factor) ──
    options.add_argument(f"--window-size={profile.screen_width},{profile.screen_height}")

    # ── User-Agent at launch, not just via CDP after launch ───────────────────
    # A reference implementation that DOES get recognized as the exact model
    # on Google's own device-security page sets this as a Chrome launch flag
    # in addition to the post-launch Network.setUserAgentOverride CDP call
    # below — this bakes the UA identity in from process start instead of
    # switching it after Chrome already initialized with the default one.
    options.add_argument(f"--user-agent={profile.user_agent}")

    # ── Anti-detection ────────────────────────────────────────────────────────
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    # ── Launch browser ────────────────────────────────────────────────────────
    # On Railway/Docker always use the system-provided Chromium and matching
    # chromedriver. Downloading a random latest driver causes version mismatch
    # and unreliable launches, and also breaks in offline/restricted builds.
    browser_binary = _find_executable(
        "CHROME_BIN", ("chromium", "chromium-browser", "google-chrome-stable", "google-chrome", "chrome")
    )
    if not browser_binary:
        raise RuntimeError(
            "Chrome/Chromium not installed. Use the supplied Dockerfile on Railway "
            "(it installs chromium and chromium-driver)."
        )
    options.binary_location = browser_binary

    driver_binary = _find_executable("CHROMEDRIVER_PATH", ("chromedriver",))
    if not driver_binary:
        # Convenience fallback for local development, particularly Windows.
        # Railway should NEVER use webdriver-manager: use Dockerfile binaries.
        if os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RAILWAY_PROJECT_ID"):
            raise RuntimeError(
                "ChromeDriver is missing on Railway. Check that Railway is building "
                "with Dockerfile and CHROMEDRIVER_PATH=/usr/bin/chromedriver."
            )
        try:
            candidate = ChromeDriverManager().install()
            if not os.path.isfile(candidate) or not os.access(candidate, os.X_OK):
                folder = os.path.dirname(candidate)
                matches = [os.path.join(folder, fname)
                           for fname in ("chromedriver", "chromedriver.exe")]
                candidate = next((p for p in matches
                                  if os.path.isfile(p) and os.access(p, os.X_OK)), "")
            driver_binary = candidate
        except Exception as exc:
            logger.warning("Driver download failed: %s", exc)
    if not driver_binary:
        raise RuntimeError(
            "Could not find ChromeDriver. On Railway use Dockerfile; locally "
            "install a matching ChromeDriver or set CHROMEDRIVER_PATH."
        )

    logger.info("Using Chrome/Chromium: %s", browser_binary)
    logger.info("Using ChromeDriver: %s", driver_binary)
    # When the user needs an interactive payment form, Chrome is visible on a
    # private virtual display. Leave the existing sign-in routine untouched.
    driver_env = dict(os.environ)
    if display_override:
        driver_env['DISPLAY'] = display_override
    driver = webdriver.Chrome(service=Service(executable_path=driver_binary, env=driver_env), options=options)

    # ── Mobile emulation (CDP) ─────────────────────────────────────────────────
    # Real Android Chrome UA reduction means the UA string alone never reveals
    # the device; Google reads the actual model from the Sec-CH-UA-* client
    # hints, so both must be set together via Network.setUserAgentOverride.
    try:
        driver.execute_cdp_cmd('Network.enable', {})
        driver.execute_cdp_cmd('Network.setUserAgentOverride', {
            'userAgent': profile.user_agent,
            'acceptLanguage': 'en-US,en;q=0.9',
            'platform': 'Android',
            'userAgentMetadata': profile.client_hints_metadata(),
        })
        # Network.setUserAgentOverride's userAgentMetadata alone only makes
        # Chrome send the Sec-CH-UA-* headers once the SERVER has first
        # opted in via Accept-CH — the very first request to a new origin
        # can go out without them. Setting them explicitly here guarantees
        # Google's server sees the real model on every request, including
        # the first one (this is what a working reference implementation
        # does, confirmed via a real screenshot where it worked).
        driver.execute_cdp_cmd('Network.setExtraHTTPHeaders', {
            'headers': profile.client_hints_headers(),
        })
        driver.execute_cdp_cmd('Emulation.setDeviceMetricsOverride', {
            'width': profile.screen_width,
            'height': profile.screen_height,
            'deviceScaleFactor': profile.pixel_ratio,
            'mobile': True,
        })
        driver.execute_cdp_cmd('Emulation.setTouchEmulationEnabled', {
            'enabled': True,
            'maxTouchPoints': profile.max_touch_points,
        })
        # Applies to every document loaded from here on (sign-in, Google One,
        # checkout) — not just the current page.
        driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': profile.navigator_js(),
        })
    except Exception as exc:
        # Never let a fingerprint-spoofing step abort a real activation —
        # Chrome still works as a (less convincing) desktop browser without it.
        logger.warning("Mobile emulation setup failed; continuing without full device spoofing: %s", exc)

    # NOTE: we deliberately do NOT run the spoofing self-check here. At this
    # point the browser is still on its initial blank startup page (not a
    # real https:// document yet), and navigator.userAgentData is only ever
    # populated on a real secure-origin page — on the blank page it is always
    # undefined, which made this check always report "no-high-entropy-api"
    # regardless of whether the spoofing actually works. See
    # _log_device_spoofing_self_check(), called instead right after the first
    # real navigation (the Google sign-in page) in _gmail_login().

    driver.implicitly_wait(config.IMPLICIT_WAIT)
    driver.set_page_load_timeout(config.PAGE_LOAD_TIMEOUT)
    return driver


# ── Helpers ───────────────────────────────────────────────────────────────────

def _wait_for(driver: webdriver.Chrome, by: str, value: str,
              timeout: int = config.WEBDRIVER_TIMEOUT):
    """Return element after waiting for it to be clickable."""
    return WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((by, value))
    )


def _click_element_by_inner_text(driver: webdriver.Chrome,
                                 keyword: str, tag: str = "*") -> bool:
    """Click the first visible element whose full inner text contains keyword."""
    try:
        el = driver.find_element(
            By.XPATH,
            f"//{tag}[contains(translate(., "
            f"'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')"
            f", '{keyword.lower()}')]"
        )
        if el.is_displayed():
            el.click()
            return True
    except Exception:
        pass
    # JS fallback — walks every element and checks innerText
    try:
        driver.execute_script(
            """
            var kw = arguments[0].toLowerCase();
            var els = document.querySelectorAll(arguments[1]);
            for (var i = 0; i < els.length; i++) {
                if (els[i].innerText && els[i].innerText.toLowerCase().includes(kw)
                        && els[i].offsetParent !== null) {
                    els[i].click();
                    return true;
                }
            }
            return false;
            """,
            keyword.lower(), tag
        )
        return True
    except Exception:
        pass
    return False


def _enter_totp(driver: webdriver.Chrome, totp_secret: str,
                cb: ProgressCB = None) -> bool:
    """Generate a fresh TOTP code and fill it into the visible input. Returns True on submit."""
    code = _generate_totp(totp_secret)
    secs_left = 30 - (int(time.time()) % 30)
    _report(cb, f"🔢 Entering the authenticator code (valid for {secs_left}s)", driver)

    # Find the visible TOTP input field
    totp_field = None
    for inp in driver.find_elements(By.CSS_SELECTOR, "input"):
        try:
            if (inp.get_attribute("aria-hidden") or "").lower() == "true":
                continue
            itype = (inp.get_attribute("type") or "").lower()
            iname = (inp.get_attribute("name") or "").lower()
            iac = (inp.get_attribute("autocomplete") or "").lower()
            if (itype in ("tel", "number") or "pin" in iname
                    or "totp" in iname or "one-time" in iac
                    or "security" in iname):
                totp_field = inp
                break
            # fallback: any visible non-hidden text input
            if itype == "text" and inp.is_displayed():
                totp_field = inp
        except Exception:
            continue

    if not totp_field:
        _report(cb, "⚠️ The 2FA authenticator input was not found on this page.", driver)
        return False

    totp_field.clear()
    totp_field.send_keys(code)
    time.sleep(0.5)

    # Submit
    for sid in ["totpNext", "passwordNext"]:
        try:
            driver.find_element(By.ID, sid).click()
            return True
        except NoSuchElementException:
            continue
    try:
        driver.find_element(
            By.CSS_SELECTOR, 'button[type="submit"], [jsname="LgbsSe"]'
        ).click()
        return True
    except NoSuchElementException:
        pass
    return False


def _click_authenticator_option(driver: webdriver.Chrome,
                                cb: ProgressCB = None) -> bool:
    """
    Click the Authenticator app option on Google's method-selection page.

    The <li> elements have no jsaction. The real click handler is on a child
    <div> or <a> INSIDE the authenticator <li>. Strategy:
      1. Find the <li> whose innerText contains "authenticator"
      2. Look INSIDE it for any jsaction child, <a>, or <button>
      3. If none, click the first <div> child (Google wraps options in divs)
      4. Last resort: plain .click() + dispatchEvent on the <li> itself
    """
    result = driver.execute_script(
        """
        // Strategy A: data-challengetype="6" = TOTP (Google Authenticator).
        // Do NOT use data-challengeid — it is not unique and matches other options.
        var directEl = document.querySelector('[data-action="selectchallenge"][data-challengetype="6"]');
        if (directEl && directEl.offsetParent !== null) {
            directEl.click();
            return 'direct_challengetype6';
        }

        // Strategy B: find <li> whose innerText contains "authenticator",
        // then click its first child with role=link/button or any jsaction,
        // or fall back to the first <div> child (which is Google's click wrapper).
        var kw = 'authenticator';
        var targetLi = null;
        var lis = document.querySelectorAll('li');
        for (var i = 0; i < lis.length; i++) {
            var t = (lis[i].innerText || '').toLowerCase();
            if (t.includes(kw) && lis[i].offsetParent !== null) {
                targetLi = lis[i];
                break;
            }
        }
        if (!targetLi) return 'li_not_found';

        // Prefer role=link/button or any jsaction child inside the li
        var jaEl = targetLi.querySelector('[role="link"], [role="button"], [jsaction], a, button');
        if (jaEl) {
            jaEl.click();
            return 'inner_role:' + jaEl.tagName + '/' + (jaEl.getAttribute('role') || '');
        }

        // First <div> child is Google's click container
        var divEl = targetLi.querySelector('div');
        if (divEl) {
            divEl.click();
            return 'inner_div';
        }

        // Last resort: click the LI itself
        targetLi.click();
        targetLi.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
        return 'li_click_dispatch';
        """
    )
    _report(cb, f"🔍 Authenticator click: {result}", driver)
    if result and result not in ("li_not_found",):
        return True

    # DOM fallback via Selenium ActionChains
    try:
        from selenium.webdriver.common.action_chains import ActionChains
        el = driver.find_element(
            By.XPATH,
            "//li[.//*[contains(translate(.,"
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'authenticator')]]"
        )
        ActionChains(driver).move_to_element(el).click(el).perform()
        _report(cb, "✅ Clicked Authenticator via ActionChains", driver)
        return True
    except Exception as e:
        _report(cb, f"⚠️ ActionChains fallback failed: {e}", driver)

    return False


def _click_try_another_way(driver: webdriver.Chrome) -> bool:
    """Click the 'Try another way' link/button. Returns True on success."""
    # JS innerText scan — most reliable across Google UI variants
    try:
        driver.execute_script(
            """
            var els = document.querySelectorAll('a, button, [role="button"]');
            for (var i = 0; i < els.length; i++) {
                if ((els[i].innerText || '').toLowerCase().includes('try another way')
                        && els[i].offsetParent !== null) {
                    els[i].click(); return;
                }
            }
            """
        )
        return True
    except Exception:
        pass
    # DOM fallback
    for el in driver.find_elements(By.CSS_SELECTOR, "a, button, [role='button']"):
        try:
            if "try another way" in (el.get_attribute("innerText") or el.text or "").lower() \
                    and el.is_displayed():
                el.click()
                return True
        except Exception:
            continue
    return False


def _handle_2fa(driver: webdriver.Chrome, totp_secret: str,
                cb: ProgressCB = None) -> None:
    """
    Handle any Google 2FA challenge after password submission.

    Detection is CONTENT-based, not URL-based, because Google reuses the
    /skotp URL for both the g.co/sc device code page AND the TOTP page.

    Flow:
      1. If page shows "g.co/sc"  →  click "Try another way"
      2. If page shows method list →  click "Authenticator app" option
      3. Enter the TOTP code from the authenticator key
    """
    hostname = urlparse(driver.current_url).hostname or ""
    if "accounts.google.com" not in hostname:
        _report(cb, "ℹ️ Step 4/6 — No 2FA challenge detected; signed in.", driver)
        return

    src = driver.page_source.lower()
    path = urlparse(driver.current_url).path
    _report(cb, f"🔐 Step 4/6 — Two-step verification required\n📍 Path: {path}", driver)

    # ── Stage 1: g.co/sc device-code page → click "Try another way" ──────────
    if "g.co/sc" in src:
        _report(cb,
                "🔄 Step 4a — g.co/sc device verification detected.\n"
                "Selecting 'Try another way' to use the authenticator app…",
                driver)
        clicked = _click_try_another_way(driver)
        time.sleep(2)
        src = driver.page_source.lower()
        path = urlparse(driver.current_url).path
        _report(cb,
                f"{'✅' if clicked else '⚠️'} Step 4a — "
                f"{'Left the g.co/sc page' if clicked else 'Try another way was not found'}\n"
                f"📍 Current path: {path}",
                driver)

    # ── Stage 2: Method selection page → pick Authenticator app ──────────────
    src = driver.page_source.lower()
    # Selection page = has "authenticator" in content but no TOTP code input yet
    has_authenticator_option = "authenticator" in src
    has_totp_input = any(
        kw in src for kw in ['name="pin"', 'type="tel"', 'type="number"']
    )

    if has_authenticator_option and not has_totp_input:
        _report(cb,
                "🔍 Step 4b — Verification method selection.\n"
                "Selecting the authenticator app…",
                driver)

        # Log the clickable items on the page to aid debugging
        try:
            items_info = driver.execute_script(
                """
                var out = [];
                var items = document.querySelectorAll('li, [role="option"], [role="listitem"]');
                for (var i = 0; i < items.length; i++) {
                    var t = (items[i].innerText || '').trim().substring(0, 80);
                    var ja = items[i].getAttribute('jsaction') || '';
                    if (t) out.push(items[i].tagName + ' ja=' + ja.substring(0,30) + ' | ' + t);
                }
                return out.join('\\n');
                """
            )
            _report(cb, f"📋 Available options:\n{items_info or '(none)'}", driver)
        except Exception:
            pass

        picked = _click_authenticator_option(driver, cb)

        if picked:
            # Wait up to 8s for the TOTP input to appear (actual page navigation)
            try:
                WebDriverWait(driver, 8).until(
                    lambda d: any(
                        (inp.get_attribute("type") or "") in ("tel", "number", "text")
                        and inp.is_displayed()
                        for inp in d.find_elements(By.CSS_SELECTOR, "input")
                        if (inp.get_attribute("aria-hidden") or "").lower() != "true"
                    )
                )
                _report(cb,
                        f"✅ Step 4b — Authenticator code field is ready\n"
                        f"📍 Current path: {urlparse(driver.current_url).path}",
                        driver)
            except Exception:
                _report(cb,
                        f"⚠️ Step 4b — Timed out waiting for the authenticator field\n"
                        f"📍 Current path: {urlparse(driver.current_url).path}",
                        driver)
        else:
            _report(cb, "⚠️ Step 4b — Could not choose the authenticator option.", driver)
            time.sleep(2)

    # ── Stage 3: TOTP input page → enter the code ────────────────────────────
    time.sleep(0.5)
    _report(cb, "🔑 Step 4c — Entering authenticator code…", driver)
    submitted = _enter_totp(driver, totp_secret, cb)
    if submitted:
        time.sleep(3)
        _report(cb,
                f"✅ Step 4 — Verification code submitted\n📍 URL: {driver.current_url[:80]}",
                driver)
    else:
        _report(cb,
                "⚠️ Step 4 — Could not locate the 2FA input.\n"
                f"📍 Current page: {urlparse(driver.current_url).path}",
                driver)


def _generate_totp(secret: str) -> str:
    """Generate the current TOTP code from a base32 secret."""
    clean_secret = secret.upper().replace(" ", "")
    totp = pyotp.TOTP(clean_secret)
    code = totp.now()
    secs_left = 30 - (int(time.time()) % 30)
    logger.info("Generated a TOTP code (%ds left)", secs_left)
    return code


# ── Login ─────────────────────────────────────────────────────────────────────

def _log_device_spoofing_self_check(driver: webdriver.Chrome) -> None:
    """Log what the CURRENT page's navigator actually reports. Must be called
    after a real https:// navigation — navigator.userAgentData only exists on
    a real secure-origin document (never on the blank page Chrome starts on),
    so calling this before any navigation always reports "no-high-entropy-api"
    even when the CDP spoofing in _build_driver() is working correctly. A
    Google page choosing to display just "Android" (not "Pixel 11 Pro") in
    its own UI proves nothing either way: the device model is a
    "high-entropy" client hint Chrome only ever sends when the page itself
    explicitly asks for it via JS, and most Google account-security screens
    may never do — so even a REAL physical Pixel 11 Pro signing in through a
    browser (not the Google app) could show the same generic "Android"
    there. This checks the one thing we actually control and can verify:
    that our own override is live in the browser itself, independent of
    what any given Google page chooses to display."""
    try:
        check = driver.execute_script(
            "return JSON.stringify({"
            "mobile: !!(navigator.userAgentData && navigator.userAgentData.mobile),"
            "platform: navigator.platform,"
            "touchPoints: navigator.maxTouchPoints,"
            "ua: navigator.userAgent"
            "});"
        )
        logger.info("Device spoofing check (Pixel 11 Pro) — %s", check)
    except Exception as exc:
        logger.debug("Device spoofing check unavailable: %s", exc)

    # The model itself is a high-entropy hint, only obtainable via this async
    # API (never from a plain header or navigator.platform) — this is what a
    # page would see if it actually asked, which is the real test of whether
    # "Pixel 11 Pro" is being reported correctly.
    try:
        model_check = driver.execute_async_script(
            "var cb = arguments[arguments.length - 1];"
            "if (navigator.userAgentData && navigator.userAgentData.getHighEntropyValues) {"
            "  navigator.userAgentData.getHighEntropyValues(['model','platformVersion','architecture'])"
            "    .then(function(v){ cb(JSON.stringify(v)); })"
            "    .catch(function(e){ cb('error: ' + e); });"
            "} else { cb('no-high-entropy-api'); }"
        )
        logger.info("Device spoofing check (high-entropy model hint) — %s", model_check)
    except Exception as exc:
        logger.debug("High-entropy device check unavailable: %s", exc)


def _gmail_login(driver: webdriver.Chrome, email: str, password: str,
                 totp_secret: Optional[str] = None,
                 cb: ProgressCB = None) -> bool:
    """
    Perform Gmail login with optional TOTP 2FA.
    Calls cb() with a message + screenshot at every key step.
    Returns True on success, False on detectable failure.
    """
    try:
        # ── 步骤 1: 加载登录页面 ───────────────────────────────────────────
        _report(cb, "🌐 Step 1/6 — Opening Google sign-in…", driver)
        driver.get(config.GMAIL_LOGIN_URL)
        time.sleep(2)
        _log_device_spoofing_self_check(driver)

        # ── 步骤 2: 输入邮箱 ───────────────────────────────────────────────
        _report(cb, f"📧 Step 2/6 — Entering email: {email}", driver)
        email_field = _wait_for(driver, By.CSS_SELECTOR,
                                'input[name="identifier"], input[type="email"]')
        email_field.clear()
        email_field.send_keys(email)
        _wait_for(driver, By.ID, "identifierNext").click()
        time.sleep(2)

        # ── 步骤 3: 输入密码 ────────────────────────────────────────────
        _report(cb, "🔒 Step 3/6 — Entering password…", driver)
        password_field = _wait_for(driver, By.CSS_SELECTOR,
                                   'input[type="password"]')
        password_field.clear()
        password_field.send_keys(password)
        _wait_for(driver, By.ID, "passwordNext").click()
        time.sleep(3)

        # ── 步骤 4: 二步验证 / TOTP ────────────────────────────────────────────────
        if totp_secret:
            _report(cb, "🔐 Step 4/6 — Checking two-step verification…", driver)
            _handle_2fa(driver, totp_secret, cb)

        # ── Step 5: Verify login ──────────────────────────────────────────────
        current_url = driver.current_url
        parsed = urlparse(current_url)
        hostname = parsed.hostname or ""
        path = parsed.path or ""

        # Check for visible error text
        driver.implicitly_wait(0)
        try:
            error_el = driver.find_element(
                By.CSS_SELECTOR, '[jsname="B34EJ"], [aria-live="assertive"]'
            )
            if error_el.text.strip():
                _report(cb,
                        f"❌ Step 5/6 — Sign-in error: {error_el.text.strip()}",
                        driver)
                return False
        except NoSuchElementException:
            pass

        finally:
            driver.implicitly_wait(config.IMPLICIT_WAIT)

        if (hostname == "myaccount.google.com"
                or (hostname.endswith(".google.com") and "/u/" in path)):
            _report(cb, "✅ Step 5/6 — Signed in successfully!", driver)
            return True

        if not (hostname == "accounts.google.com"
                and path.startswith("/signin")):
            _report(cb,
                    f"✅ Step 5/6 — Sign-in appears successful\n"
                    f"📍 URL: {current_url[:80]}",
                    driver)
            return True

        _report(cb,
                f"❌ Step 5/6 — Still on the sign-in page\n"
                f"📍 URL: {current_url[:80]}",
                driver)
        return False

    except TimeoutException as exc:
        _report(cb, f"⏱️ Timeout during login: {exc}", driver)
        return False
    except WebDriverException as exc:
        _report(cb, f"❌ WebDriver error during login: {exc}", driver)
        return False


# ── Offer detection ───────────────────────────────────────────────────────────

def _extract_payment_link(driver: webdriver.Chrome) -> Optional[str]:
    """Scan current page for a Gemini Pro offer / activation link."""
    keywords = config.GEMINI_OFFER_KEYWORDS
    # 优先匹配包含 gemini 或 ai premium 的高优关键词
    priority_keywords = ["gemini", "ai premium", "ai_premium"]
    # 排除非相关服务的黑名单（防止误把 YouTube Premium 等优惠当作 Gemini 提取）
    blacklist = ["youtube", "fitbit", "nest", "playpass", "play pass"]

    url_pat = re.compile(
        r"(gemini|upgrade|activate|offer|redeem|trial|checkout)",
        re.IGNORECASE,
    )

    all_links = driver.find_elements(By.TAG_NAME, "a")

    # 第一阶段：高优先级搜索（包含 gemini 等特有词，且不包含黑名单）
    for link in all_links:
        try:
            href = (link.get_attribute("href") or "").lower()
            text = (link.text + " " + (link.get_attribute("aria-label") or "")).lower()
            
            if any(bl in text or bl in href for bl in blacklist):
                continue
                
            if any(p_kw in text or p_kw in href for p_kw in priority_keywords) and href:
                return link.get_attribute("href")
        except Exception:
            continue

    # 第二阶段：次优先级搜索（原有的 Gemini 关键词过滤，不包含黑名单）
    for link in all_links:
        try:
            href = (link.get_attribute("href") or "").lower()
            text = (link.text + " " + (link.get_attribute("aria-label") or "")).lower()
            
            if any(bl in text or bl in href for bl in blacklist):
                continue
                
            if any(kw in text for kw in keywords) and href:
                return link.get_attribute("href")
        except Exception:
            continue

    # 第三阶段：正则 fallback（不包含黑名单）
    for link in all_links:
        try:
            href = (link.get_attribute("href") or "").lower()
            text = (link.text + " " + (link.get_attribute("aria-label") or "")).lower()
            
            if any(bl in text or bl in href for bl in blacklist):
                continue
                
            if url_pat.search(href):
                return link.get_attribute("href")
        except Exception:
            continue

    # 第四阶段：按钮搜索（不包含黑名单）
    for btn in driver.find_elements(By.CSS_SELECTOR, "button, [role='button']"):
        try:
            text = btn.text.lower()
            if any(bl in text for bl in blacklist):
                continue
                
            if any(kw in text for kw in keywords):
                try:
                    parent = btn.find_element(By.XPATH, "ancestor::a")
                    href = parent.get_attribute("href") or ""
                    if href:
                        if any(bl in href.lower() for bl in blacklist):
                            continue
                        return href
                except NoSuchElementException:
                    pass
                return driver.current_url
        except Exception:
            continue

    return None


def _navigate_google_one(driver: webdriver.Chrome, cb: ProgressCB = None,
                         interactive: bool = False) -> tuple[Optional[str], bool]:
    """Step 6: select Annual > Google AI Pro > Add card.

    The interactive mode leaves the real Google payment form open for the user.
    The bot does not enter payment details or confirm a purchase.
    Returns (captured_google_checkout_url_or_none, pro_button_was_clicked).
    """
    pro_clicked = False

    def stage_message(message, page):
        nonlocal pro_clicked
        if 'Clicked Get Google AI Pro (Annual)' in message:
            pro_clicked = True
        # Diagnostic photos for each Google One stage, before manual control.
        _report(cb, message, page, crop_bottom=True)

    # Selector fallbacks already have their own polling deadline. An implicit
    # wait per missing XPath multiplies latency across every fallback selector.
    driver.implicitly_wait(0)
    try:
        offer_link = open_annual_ai_pro_checkout(
            driver, config.GOOGLE_ONE_AI_URL, progress=stage_message,
            final_photo=None,
        )
    finally:
        driver.implicitly_wait(config.IMPLICIT_WAIT)
    if not pro_clicked:
        return offer_link, False

    def card_message(message, page):
        _report(cb, message, page, crop_bottom=True)

    # Disable implicit Selenium waits *only* while scanning the already-open
    # Google checkout. Nested-frame probes must not each consume 10 seconds.
    # If Add card is slow to appear, hand the live page to the Mini App user.
    try:
        driver.implicitly_wait(0)
        card_opened = open_add_card_dialog(driver, progress=card_message, timeout=8)
    finally:
        driver.implicitly_wait(config.IMPLICIT_WAIT)
    # This photo is taken before the user has entered their payment data.
    if cb:
        screenshot = _shot(driver, crop_bottom=True) if getattr(cb, "capture_screenshots", True) else None
        if screenshot:
            cb('📸 Step 6/6 — Google AI Pro Annual checkout. '
               + ('Add card form opened.' if card_opened else 'Payment dialog opened.')
               + (' Use the private interactive window to complete checkout.'
                  if interactive else ' Payment has not been confirmed.'), screenshot)
        else:
            cb('✅ Step 6/6 — Google payment page reached. Payment not confirmed.', None)
    return offer_link, True


# ── Public API ────────────────────────────────────────────────────────────────

class GoogleAutomationError(Exception):
    """Raised when automation encounters an unrecoverable error."""


def check_gemini_offer(email: str, password: str,
                       device: DeviceProfile,
                       totp_secret: Optional[str] = None,
                       progress_callback: ProgressCB = None,
                       manual_login: bool = False,
                       remote_session=None) -> Optional[str]:
    """
    Main entry point.

    Logs into email/password with optional TOTP, navigates to Google One,
    and returns the Gemini Pro offer link (or None).

    progress_callback(msg: str, screenshot_bytes: Optional[bytes]) is called
    at every key step so the caller can relay live updates to Telegram.
    """
    driver: Optional[webdriver.Chrome] = None
    keep_browser = False
    in_stage_six = False
    try:
        if remote_session is not None:
            remote_session.start_display()
        _report(progress_callback,
                "📱 Starting Chrome (Pixel 11 Pro) browser session")

        driver = _build_driver(device, display_override=remote_session.display if remote_session else None)
        if remote_session is not None:
            if remote_session.closed:
                raise GoogleAutomationError('Browser was closed')
            # Show the same Chrome window immediately, read-only while the bot
            # performs login and plan selection; never start a second browser.
            remote_session.attach_driver(driver)
            remote_session.phase = '🌐 Chrome started · automatic steps in progress'
        _report(progress_callback, "✅ Browser started successfully", driver)

        if manual_login:
            # 开启手动登录页面
            _report(progress_callback, "🌐 Opening Google sign-in…", driver)
            driver.get(config.GMAIL_LOGIN_URL)
            print("\n" + "="*60)
            print("👉 Complete your Google sign-in in the browser window (email, password, and 2FA).")
            print("👉 Once signed in, return to the terminal and press Enter to open the Google AI Pro offer.")
            print("="*60 + "\n")
            input("Press Enter to continue…")
            _report(progress_callback, "✅ Manual sign-in complete. Opening the Google AI Pro offer…", driver)
        else:
            logged_in = _gmail_login(
                driver, email, password,
                totp_secret=totp_secret,
                cb=progress_callback,
            )
            if not logged_in:
                raise GoogleAutomationError(
                    "Google sign-in did not complete. Check the last screenshot; a timeout does not prove incorrect credentials."
                )

        # A code authorizes exactly one successful Google login, even if a later step fails.
        if remote_session is not None:
            from admin_store import STORE
            if remote_session.closed or not STORE.consume(remote_session.token):
                raise GoogleAutomationError('Session cancelled or code revoked')
        in_stage_six = True
        offer_link, pro_clicked = _navigate_google_one(
            driver, cb=progress_callback, interactive=remote_session is not None,
        )
        if remote_session is not None and remote_session.closed:
            raise GoogleAutomationError('Browser was closed')
        if remote_session is not None and pro_clicked:
            # Chrome stays alive, and no further screenshots or keystrokes are
            # captured by the bot. The user controls Google Payments directly.
            remote_session.attach_driver(driver)
            remote_session.interactive_enabled = True
            remote_session.phase = '💳 Checkout ready · manual control enabled'
            # No time limit; close manually or via the configured completion URL.
            keep_browser = True
        return offer_link

    except Exception as exc:
        # Capture the last visible page before the existing cleanup closes it.
        _report(progress_callback, f"⚠️ Last browser screen before stopping ({type(exc).__name__})", driver, crop_bottom=in_stage_six)
        raise
    finally:
        if remote_session is not None and not keep_browser:
            remote_session.ready = False
            remote_session.driver = None
            remote_session.stop()
        if driver and not keep_browser:
            try:
                # 如果是有头模式（显示界面），提示用户确认后再关闭浏览器，防止窗口瞬间关闭
                if not config.HEADLESS and remote_session is None:
                    print("\n" + "="*60)
                    print("💡 The process is complete. The browser window is still open for review.")
                    print("👉 Press Enter in the terminal to close the browser and exit.")
                    print("="*60 + "\n")
                    input("Press Enter to close the browser…")
                logger.info("Closing browser session")
                driver.quit()
            except Exception:
                pass
