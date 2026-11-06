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

logger = logging.getLogger(__name__)

ProgressCB = Optional[Callable[[str, Optional[bytes]], None]]


# ── Screenshot helper ─────────────────────────────────────────────────────────

def _shot(driver: webdriver.Chrome) -> Optional[bytes]:
    """Return a PNG screenshot as bytes, or None on failure."""
    try:
        return driver.get_screenshot_as_png()
    except Exception:
        return None


def _report(cb: ProgressCB, msg: str, driver: Optional[webdriver.Chrome] = None) -> None:
    """Send a progress message (and optional screenshot) via the callback."""
    logger.info(msg)
    if cb:
        screenshot = _shot(driver) if driver else None
        try:
            cb(msg, screenshot)
        except Exception as e:
            logger.warning("progress_callback error: %s", e)


# ── Driver factory ────────────────────────────────────────────────────────────

def _build_driver(profile: DeviceProfile) -> webdriver.Chrome:
    """
    Return a headless Chrome WebDriver fully configured to impersonate a
    real Google Pixel 10 Pro running Android 16 / Chrome 149.

    Spoofing layers (applied in order):
      1. Chrome launch flags   – mobile emulation, reduced UA, anti-detection
      2. CDP commands          – authoritative screen metrics, UA client hints,
                                 touch emulation
      3. JS injection          – navigator props, WebGL GPU, battery, network,
                                 chrome runtime object, plugins
    """
    options = Options()

    if config.HEADLESS:
        options.add_argument("--headless=new")

    if getattr(config, "PROXY", None):
        options.add_argument(f"--proxy-server={config.PROXY}")

    # ── Core stability flags ──────────────────────────────────────────────────
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
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

    # ── Window size = Pixel 10 Pro CSS viewport ───────────────────────────────
    w, h = profile.screen_width, profile.screen_height
    options.add_argument(f"--window-size={w},{h}")
    options.add_argument(f"--user-agent={profile.user_agent}")

    # ── Anti-detection ────────────────────────────────────────────────────────
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    # ── Chrome-level mobile emulation ─────────────────────────────────────────
    # Reduced UA: "Android 10; K" — device model intentionally absent (Chrome 110+)
    mobile_emulation = {
        "deviceMetrics": {
            "width":      w,
            "height":     h,
            "pixelRatio": profile.pixel_ratio,
            "touch":      True,
        },
        "userAgent": profile.user_agent,
    }
    options.add_experimental_option("mobileEmulation", mobile_emulation)

    # ── Launch browser ────────────────────────────────────────────────────────
    chromium_binary = shutil.which("chromium") or shutil.which("chromium-browser")
    if chromium_binary:
        options.binary_location = chromium_binary
    try:
        chromedriver_path = shutil.which("chromedriver") or ChromeDriverManager().install()
        # 修复 webdriver-manager 在 Windows 上误匹配到非 .exe 文件的问题（例如 THIRD_PARTY_NOTICES.chromedriver）
        if not chromedriver_path.lower().endswith(".exe"):
            dir_name = os.path.dirname(chromedriver_path)
            candidate = os.path.join(dir_name, "chromedriver.exe")
            if os.path.exists(candidate):
                chromedriver_path = candidate
            else:
                # 向下遍历搜索 chromedriver.exe
                found = False
                for root, dirs, files in os.walk(dir_name):
                    if "chromedriver.exe" in files:
                        chromedriver_path = os.path.join(root, "chromedriver.exe")
                        found = True
                        break
                # 如果没找到，尝试在父目录遍历搜索
                if not found:
                    parent_dir = os.path.dirname(dir_name)
                    for root, dirs, files in os.walk(parent_dir):
                        if "chromedriver.exe" in files:
                            chromedriver_path = os.path.join(root, "chromedriver.exe")
                            break
        service = Service(executable_path=chromedriver_path)
    except Exception as e:
        logger.warning("webdriver_manager failed, falling back to local: %s", e)
        chromedriver_binary = shutil.which("chromedriver") or "chromedriver"
        service = Service(executable_path=chromedriver_binary)
    driver = webdriver.Chrome(service=service, options=options)

    # ── CDP layer 1: authoritative screen metrics + touch ─────────────────────
    driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
        "width":             w,
        "height":            h,
        "deviceScaleFactor": profile.pixel_ratio,
        "mobile":            True,
        "screenWidth":       w,
        "screenHeight":      h,
        "positionX":         0,
        "positionY":         0,
    })

    # ── CDP layer 2: User-Agent + full Sec-CH-UA-* client hints ──────────────
    # This is what Google reads to know the real device behind the reduced UA.
    driver.execute_cdp_cmd("Emulation.setUserAgentOverride", {
        "userAgent":         profile.user_agent,
        "acceptLanguage":    "en-US,en;q=0.9",
        "platform":          "Linux armv8l",
        "userAgentMetadata": profile.client_hints_metadata(),
    })

    # ── CDP layer 3: multitouch emulation ────────────────────────────────────
    driver.execute_cdp_cmd("Emulation.setTouchEmulationEnabled", {
        "enabled":       True,
        "maxTouchPoints": profile.max_touch_points,
    })

    # ── CDP layer 4: JS navigator/WebGL/battery/network spoofing ─────────────
    # Injected before every page's own JS runs.
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": profile.navigator_js()
    })

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
    _report(cb, f"🔢 正在输入身份验证器验证码: `{code}` (该验证码还剩 {secs_left}秒 有效)", driver)

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
        _report(cb, "⚠️ 当前页面未找到二步验证（TOTP）输入框", driver)
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
        _report(cb, "ℹ️ 步骤 4/6 — 未检测到二步验证挑战，已成功登录", driver)
        return

    src = driver.page_source.lower()
    path = urlparse(driver.current_url).path
    _report(cb, f"🔐 步骤 4/6 — 二步验证挑战页面\n📍 路径: {path}", driver)

    # ── Stage 1: g.co/sc device-code page → click "Try another way" ──────────
    if "g.co/sc" in src:
        _report(cb,
                "🔄 步骤 4a — 检测到 g.co/sc 页面 (设备浏览器验证码)。\n"
                "正在点击 '尝试其他方式' 以切换到身份验证器应用…",
                driver)
        clicked = _click_try_another_way(driver)
        time.sleep(2)
        src = driver.page_source.lower()
        path = urlparse(driver.current_url).path
        _report(cb,
                f"{'✅' if clicked else '⚠️'} 步骤 4a — "
                f"{'已成功离开 g.co/sc 页面' if clicked else '未找到“尝试其他方式”选项'}\n"
                f"📍 当前路径: {path}",
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
                "🔍 步骤 4b — 二步验证方式选择页面。\n"
                "正在选择 '谷歌身份验证器' 选项…",
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
            _report(cb, f"📋 页面选项:\n{items_info or '(无)'}", driver)
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
                        f"✅ 步骤 4b — 二步验证码输入框已加载\n"
                        f"📍 当前路径: {urlparse(driver.current_url).path}",
                        driver)
            except Exception:
                _report(cb,
                        f"⚠️ 步骤 4b — 等待超时，未找到二步验证码输入框\n"
                        f"📍 当前路径: {urlparse(driver.current_url).path}",
                        driver)
        else:
            _report(cb, "⚠️ 步骤 4b — 无法点击身份验证器选项", driver)
            time.sleep(2)

    # ── Stage 3: TOTP input page → enter the code ────────────────────────────
    time.sleep(0.5)
    _report(cb, "🔑 步骤 4c — 正在输入身份验证器二步验证码…", driver)
    submitted = _enter_totp(driver, totp_secret, cb)
    if submitted:
        time.sleep(3)
        _report(cb,
                f"✅ 步骤 4 — 二步验证码已提交\n📍 URL: {driver.current_url[:80]}",
                driver)
    else:
        _report(cb,
                "⚠️ 步骤 4 — 未能找到二步验证输入框。\n"
                f"📍 当前页面: {urlparse(driver.current_url).path}",
                driver)


def _generate_totp(secret: str) -> str:
    """Generate the current TOTP code from a base32 secret."""
    clean_secret = secret.upper().replace(" ", "")
    totp = pyotp.TOTP(clean_secret)
    code = totp.now()
    secs_left = 30 - (int(time.time()) % 30)
    logger.info("Generated TOTP: %s (%ds left)", code, secs_left)
    return code


# ── Login ─────────────────────────────────────────────────────────────────────

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
        _report(cb, "🌐 步骤 1/6 — 正在加载 Google 登录页面…", driver)
        driver.get(config.GMAIL_LOGIN_URL)
        time.sleep(2)

        # ── 步骤 2: 输入邮箱 ───────────────────────────────────────────────
        _report(cb, f"📧 步骤 2/6 — 正在输入邮箱: {email}", driver)
        email_field = _wait_for(driver, By.CSS_SELECTOR,
                                'input[name="identifier"], input[type="email"]')
        email_field.clear()
        email_field.send_keys(email)
        _wait_for(driver, By.ID, "identifierNext").click()
        time.sleep(2)

        # ── 步骤 3: 输入密码 ────────────────────────────────────────────
        _report(cb, "🔒 步骤 3/6 — 正在输入密码…", driver)
        password_field = _wait_for(driver, By.CSS_SELECTOR,
                                   'input[type="password"]')
        password_field.clear()
        password_field.send_keys(password)
        _wait_for(driver, By.ID, "passwordNext").click()
        time.sleep(3)

        # ── 步骤 4: 二步验证 / TOTP ────────────────────────────────────────────────
        if totp_secret:
            _report(cb, "🔐 步骤 4/6 — 正在检查二步验证挑战…", driver)
            _handle_2fa(driver, totp_secret, cb)

        # ── Step 5: Verify login ──────────────────────────────────────────────
        current_url = driver.current_url
        parsed = urlparse(current_url)
        hostname = parsed.hostname or ""
        path = parsed.path or ""

        # Check for visible error text
        try:
            error_el = driver.find_element(
                By.CSS_SELECTOR, '[jsname="B34EJ"], [aria-live="assertive"]'
            )
            if error_el.text.strip():
                _report(cb,
                        f"❌ 步骤 5/6 — 登录出错: {error_el.text.strip()}",
                        driver)
                return False
        except NoSuchElementException:
            pass

        if (hostname == "myaccount.google.com"
                or (hostname.endswith(".google.com") and "/u/" in path)):
            _report(cb, "✅ 步骤 5/6 — 登录成功！", driver)
            return True

        if not (hostname == "accounts.google.com"
                and path.startswith("/signin")):
            _report(cb,
                    f"✅ 步骤 5/6 — 登录似乎成功\n"
                    f"📍 链接: {current_url[:80]}",
                    driver)
            return True

        _report(cb,
                f"❌ 步骤 5/6 — 登录后仍停留在登录页面\n"
                f"📍 链接: {current_url[:80]}",
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


def _navigate_google_one(driver: webdriver.Chrome,
                         cb: ProgressCB = None) -> Optional[str]:
    """Navigate Google One pages and return the Gemini offer link."""
    for url in (config.GOOGLE_ONE_URL, config.GOOGLE_ONE_OFFERS_URL):
        try:
            _report(cb, f"🔍 步骤 6/6 — 正在扫描页面: {url}", driver)
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
                    pass

            _report(cb, f"🔎 正在页面中搜索 Gemini 优惠链接…", driver)
            link = _extract_payment_link(driver)
            if link:
                _report(cb,
                        f"🎯 成功找到优惠链接！\n🔗 {link}",
                        driver)
                return link
            else:
                _report(cb, f"😔 在 {url} 页面未检测到优惠链接，尝试下一个页面…", driver)

        except (TimeoutException, WebDriverException) as exc:
            _report(cb, f"⚠️ 加载 {url} 出错: {exc}", driver)

    return None


# ── Public API ────────────────────────────────────────────────────────────────

class GoogleAutomationError(Exception):
    """Raised when automation encounters an unrecoverable error."""


def check_gemini_offer(email: str, password: str,
                       device: DeviceProfile,
                       totp_secret: Optional[str] = None,
                       progress_callback: ProgressCB = None,
                       manual_login: bool = False) -> Optional[str]:
    """
    Main entry point.

    Logs into email/password with optional TOTP, navigates to Google One,
    and returns the Gemini Pro offer link (or None).

    progress_callback(msg: str, screenshot_bytes: Optional[bytes]) is called
    at every key step so the caller can relay live updates to Telegram.
    """
    driver: Optional[webdriver.Chrome] = None
    try:
        _report(progress_callback,
                f"🤖 正在启动 Pixel 10 Pro 模拟器\n"
                f"📱 会话: {device.session_id[:8]}…\n"
                f"🌐 User-Agent: {device.user_agent[:60]}…")

        driver = _build_driver(device)
        _report(progress_callback, "✅ 浏览器启动成功", driver)

        if manual_login:
            # 开启手动登录页面
            _report(progress_callback, "🌐 正在加载谷歌登录页面...", driver)
            driver.get(config.GMAIL_LOGIN_URL)
            print("\n" + "="*60)
            print("👉 请在弹出的浏览器窗口中完成 Google 账号登录（手动输入账号、密码并完成两步验证）。")
            print("👉 登录成功并看到您的谷歌账号主页后，请返回此终端窗口，按【回车键】继续自动化检测优惠...")
            print("="*60 + "\n")
            input("按【回车键】继续...")
            _report(progress_callback, "✅ 手动登录确认完成，开始检测 Google One 优惠...", driver)
        else:
            logged_in = _gmail_login(
                driver, email, password,
                totp_secret=totp_secret,
                cb=progress_callback,
            )
            if not logged_in:
                raise GoogleAutomationError(
                    "登录失败 — 请检查您的账号和密码。"
                )

        offer_link = _navigate_google_one(driver, cb=progress_callback)
        return offer_link

    finally:
        if driver:
            try:
                # 如果是有头模式（显示界面），提示用户确认后再关闭浏览器，防止窗口瞬间关闭
                if not config.HEADLESS:
                    print("\n" + "="*60)
                    print("💡 流程已结束。为方便您查看/操作页面，浏览器窗口已保留。")
                    print("👉 请在终端中按【回车键】关闭浏览器并退出程序...")
                    print("="*60 + "\n")
                    input("按【回车键】关闭浏览器并退出...")
                _report(progress_callback, "🧹 正在关闭浏览器会话…")
                driver.quit()
            except Exception:
                pass
