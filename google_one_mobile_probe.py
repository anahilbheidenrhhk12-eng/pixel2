"""Google One mobile-web experiment using the same already-authenticated Chrome session.

This is a mobile web experience, not the signed Android Google One application.
No forged app tokens, app signatures, or entitlement claims.
"""
import time
from urllib.parse import urlsplit

import config


def inspect_google_one_mobile(driver, progress=None):
    """Open the official Google One site, preserving the Pixel Chrome session."""
    send = progress or (lambda message: None)
    driver.get(config.GOOGLE_ONE_URL)
    time.sleep(3)
    host = (urlsplit(driver.current_url).hostname or "").lower()
    try:
        body = driver.execute_script(
            "return (document.body ? document.body.innerText : '').slice(0,8000)"
        ) or ""
    except Exception:
        body = ""

    result = {
        "native_application": False,
        "host": host,
        "sign_in_required": host == "accounts.google.com",
        "check_for_offers_visible": "check for offers" in body.casefold(),
        "six_months_text": "6 months" in body.casefold(),
    }
    if result["sign_in_required"]:
        send("Google One requested another sign-in in this browser.")
    elif host != "one.google.com":
        send("Google One redirected elsewhere; inspect the browser.")
    else:
        send("Google One mobile website loaded in the same Pixel Chrome session.")
        if result["check_for_offers_visible"]:
            send("Check for offers is visible in the web interface.")
        else:
            send("Native Google One app's Check for offers control was not found on the website.")
    send("Web simulation only: device-based six-month eligibility cannot be verified here.")
    return result
