"""Google One UI navigation after sign-in.

Select the Annual billing tab, verify that the Google AI Pro card uses annual
billing, and open the plan's checkout. Never confirms a purchase or payment.

This module deliberately does not touch authentication or device emulation.
It depends on a Selenium-like driver's ordinary browser interaction methods.
"""

import logging
import time
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

ANNUAL_CONTROL_XPATHS = (
    "//*[self::button or self::a or self::label or @role='button' "
    "or @role='tab' or @role='radio'][normalize-space(.)='Annual']",
    "//*[normalize-space(text())='Annual']/ancestor-or-self::*"
    "[self::button or self::a or self::label or @role='button' "
    "or @role='tab' or @role='radio'][1]",
    "//*[@aria-label='Annual']",
    # Google has also shown the control with its price folded into the same
    # label, e.g. "Annual ($199.99)" — match that too, not only the bare word.
    "//*[self::button or self::a or self::label or @role='button' "
    "or @role='tab' or @role='radio'][starts-with(normalize-space(.),'Annual')]",
    "//*[starts-with(normalize-space(text()),'Annual')]/ancestor-or-self::*"
    "[self::button or self::a or self::label or @role='button' "
    "or @role='tab' or @role='radio'][1]",
    "//*[starts-with(@aria-label,'Annual')]",
)
PRO_BUTTON_XPATHS = (
    "//*[self::button or self::a or @role='button']"
    "[normalize-space(.)='Get Google AI Pro']",
    "//*[normalize-space(text())='Get Google AI Pro']/ancestor-or-self::*"
    "[self::button or self::a or @role='button'][1]",
    "//*[@aria-label='Get Google AI Pro']",
    # Google has also shortened this button to just "Get Pro" on some plan
    # cards/layouts.
    "//*[self::button or self::a or @role='button']"
    "[normalize-space(.)='Get Pro']",
    "//*[@aria-label='Get Pro']",
)


def _report(cb, message, driver):
    logger.info(message)
    if cb:
        cb(message, driver)


def _find_visible(driver, xpaths, timeout=20):
    deadline = time.monotonic() + timeout
    while True:
        for expression in xpaths:
            try:
                for element in driver.find_elements('xpath', expression):
                    if element.is_displayed() and element.is_enabled():
                        return element
            except Exception as exc:
                logger.debug('Selector not ready: %s', exc)
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.35)


def _click(driver, element):
    """Scroll to the actual control and click; JS fallback for overlay issues."""
    try:
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center',inline:'nearest'});",
            element,
        )
    except Exception:
        pass
    try:
        element.click()
    except Exception:
        driver.execute_script('arguments[0].click();', element)


def _annual_selection_visible(annual_control, pro_button):
    """Confirm annual via accessible state OR the Pro card's yearly pricing."""
    for attr in ('aria-pressed', 'aria-selected', 'aria-checked'):
        try:
            if (annual_control.get_attribute(attr) or '').lower() == 'true':
                return True
        except Exception:
            pass
    try:
        if (annual_control.get_attribute('data-state') or '').lower() in ('active', 'checked', 'selected'):
            return True
    except Exception:
        pass

    # Inspect the closest product card, not the whole page (where AI Plus also
    # has an annual price). This avoids mistaking monthly Pro for annual Pro.
    for depth in (2, 3, 4, 5):
        try:
            ancestor = pro_button.find_element('xpath', '/'.join('..' for _ in range(depth)))
            text = ' '.join(ancestor.text.lower().split())
            if (len(text) < 1800 and 'google ai pro' in text
                    and 'google ai plus' not in text
                    and 'google ai ultra' not in text
                    and any(year in text for year in ('/yr', '/year', 'per year', 'for 1 year', 'annually', 'a year'))):
                return True
        except Exception:
            pass
    return False


def _checkout_url_usable(url, landing_url):
    if not url or url == landing_url:
        return False
    parsed = urlparse(url)
    host = (parsed.hostname or '').lower()
    if parsed.scheme != 'https':
        return False
    if host not in ('one.google.com', 'payments.google.com', 'pay.google.com', 'play.google.com'):
        return False
    # Landing and general plan pages are not checkout links.
    if (host == 'one.google.com' and parsed.path.rstrip('/') in
            ('', '/ai', '/about/plans')):
        return False
    return True



def _checkout_modal_visible(driver):
    """Detect an already-open Google payment dialog on the current page.

    A modal is not a new URL; don't waste the full URL polling window once
    the checkout overlay is visibly available. Never inspect payment inputs.
    """
    try:
        return bool(driver.execute_script("""
            const dialogs = document.querySelectorAll('[role="dialog"], dialog, [aria-modal="true"]');
            for (const element of dialogs) {
                const rect = element.getBoundingClientRect();
                if (rect.width < 180 || rect.height < 160) continue;
                const style = window.getComputedStyle(element);
                if (style.display === 'none' || style.visibility === 'hidden') continue;
                const text = (element.innerText || '').toLowerCase();
                if (text.includes('payment method') || text.includes('add card') ||
                    text.includes('google play') || text.includes('pay on your phone') ||
                    text.includes('credit or debit card') || element.querySelector('iframe')) {
                    return true;
                }
            }
            return false;
        """))
    except Exception as exc:
        logger.debug('Checkout modal probe unavailable: %s', exc)
        return False


def open_annual_ai_pro_checkout(driver, landing_url, progress=None, final_photo=None):
    """Select Annual, press ONLY 'Get Google AI Pro', and capture checkout URL.

    progress(message, driver) may send screenshots to Telegram. Returns a real
    checkout URL only if navigation provides one, otherwise None. A modal can
    open without a distinct URL; the progress log still reports the click.
    """
    _report(progress, '🌐 Step 6/6 — Opening the Google AI Pro offer page…', driver)
    driver.get(landing_url)

    annual = _find_visible(driver, ANNUAL_CONTROL_XPATHS)
    if annual is None:
        _report(progress,
                '❌ Annual billing button not found. Sign-in or page layout may have changed.',
                driver)
        return None

    _click(driver, annual)
    _report(progress, '✅ Step 6/6 — Annual billing selected.', driver)

    pro_button = _find_visible(driver, PRO_BUTTON_XPATHS, timeout=15)
    if pro_button is None:
        _report(progress, '❌ Get Google AI Pro button not found; no other plan selected.', driver)
        return None

    if not _annual_selection_visible(annual, pro_button):
        _report(progress,
                '⚠️ Unable to confirm annual pricing for Google AI Pro; stopped before checkout.',
                driver)
        return None

    before_url = driver.current_url
    before_tabs = set(driver.window_handles)
    try:
        direct_link = pro_button.get_attribute('href')
    except Exception:
        direct_link = None

    _click(driver, pro_button)
    _report(progress, '✅ Step 6/6 — Clicked Get Google AI Pro (Annual).', driver)

    # New tab, same-tab navigation, or in-page checkout dialog are all possible.
    # Always capture the final visible state after the click, even if there is no URL.
    end = time.monotonic() + 10
    after_url = before_url
    while time.monotonic() < end:
        try:
            new_tabs = set(driver.window_handles) - before_tabs
            if new_tabs:
                driver.switch_to.window(next(iter(new_tabs)))
            after_url = driver.current_url
            if _checkout_url_usable(after_url, landing_url):
                # Wait briefly for the checkout content before capturing the photo.
                try:
                    driver.execute_script("return document.readyState")
                    time.sleep(0.6)
                except Exception:
                    pass
                _report(progress, '🔗 Google AI Pro checkout page opened. Payment NOT confirmed.', driver)
                if final_photo:
                    final_photo(driver)
                return after_url
            # Google Play commonly opens checkout inside an overlay without
            # changing one.google.com/ai. Continue immediately in that case.
            if _checkout_modal_visible(driver):
                _report(progress,
                        '✅ Google payment dialog opened in the same Chrome tab.', driver)
                if final_photo:
                    final_photo(driver)
                return None
        except Exception as exc:
            logger.debug('Checkout URL not ready: %s', exc)
        time.sleep(0.4)

    if _checkout_url_usable(direct_link, landing_url):
        _report(progress, '🔗 Google AI Pro checkout button has a direct link. Payment NOT confirmed.', driver)
        if final_photo:
            final_photo(driver)
        return direct_link

    _report(progress,
            '✅ Annual Pro was selected and its button clicked. Checkout may be a modal; '
            'no distinct link was captured. No purchase was confirmed.',
            driver)
    if final_photo:
        final_photo(driver)
    return None


# Step after the Google AI Pro checkout button: open Google's own card UI.
# No card information is collected by Selenium or Telegram.
ADD_CARD_XPATHS = (
    "//*[self::button or self::a or @role='button' or @role='option'][normalize-space(.)='Add card']",
    "//*[normalize-space(text())='Add card']/ancestor-or-self::*"
    "[self::button or self::a or @role='button' or @role='option'][1]",
    "//*[normalize-space(text())='Add card']",
)


def _frame_paths(driver, max_depth=2):
    """Yield current-page and nested frame paths without assuming Google UI layout."""
    queue = [()]
    while queue:
        path = queue.pop(0)
        try:
            driver.switch_to.default_content()
            for n in path:
                driver.switch_to.frame(n)
            yield path
            if len(path) < max_depth:
                frames = driver.find_elements('css selector', 'iframe, frame')
                queue.extend(path + (i,) for i in range(min(len(frames), 16)))
        except Exception:
            continue
    try:
        driver.switch_to.default_content()
    except Exception:
        pass


def _goto_frame(driver, path):
    driver.switch_to.default_content()
    for n in path:
        driver.switch_to.frame(n)


def _card_form_visible(driver):
    """Detect Google's card dialog from public labels; never read input values."""
    try:
        text = driver.page_source.lower()
        if ('add credit or debit card' in text or 'add debit or credit card' in text):
            return True
        # Input metadata only; never call get_attribute('value') on card fields.
        if driver.find_elements('css selector', "input[autocomplete='cc-number']"):
            return True
    except Exception:
        pass
    return False


def open_add_card_dialog(driver, progress=None, timeout=20):
    """Click 'Add card' in the Google Play modal, including nested frames.

    Returns True only when the card form is visible. The user must manually
    enter all payment details through the interactive browser.
    """
    deadline = time.monotonic() + timeout
    clicked = False
    while time.monotonic() < deadline:
        try:
            for path in _frame_paths(driver):
                _goto_frame(driver, path)
                if _card_form_visible(driver):
                    driver.switch_to.default_content()
                    _report(progress, '✅ Google card entry form is open for manual input.', driver)
                    return True
                if not clicked:
                    add_card = _find_visible(driver, ADD_CARD_XPATHS, timeout=0)
                    if add_card is not None:
                        _click(driver, add_card)
                        clicked = True
                        _report(progress, '✅ Clicked Add card in the Google payment selector.', driver)
                        break
        except Exception as exc:
            logger.debug('Google card dialog not ready: %s', exc)
        finally:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass
        time.sleep(.5)
    _report(progress, '⚠️ Add card form not confirmed; you may open it manually in the live browser.', driver)
    return False
