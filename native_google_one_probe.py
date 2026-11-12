#!/usr/bin/env python3
"""Open the official Google One Android app after an Android-level Google login.

On an interactive emulator/phone, sign in using Google's own account screen;
then the Google One app can see the *same Android account*. A Chrome CDP login
is a different browser session and cannot be transferred to an Android app.

No account passwords, cookies, 2FA secrets, or purchase actions are captured.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

GOOGLE_ONE = "com.google.android.apps.subscriptions.red"
GOOGLE_PLAY = "com.android.vending"


def adb(*args, timeout=40, binary=False):
    cmd = ["adb"]
    if os.environ.get("ANDROID_SERIAL"):
        cmd.extend(["-s", os.environ["ANDROID_SERIAL"]])
    cmd.extend(str(arg) for arg in args)
    result = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if binary:
        return result.returncode, result.stdout, result.stderr
    return (result.returncode, result.stdout.decode("utf-8", "replace").strip(),
            result.stderr.decode("utf-8", "replace").strip())


def getprop(name):
    return adb("shell", "getprop", name)[1]


def package_installed(package):
    code, out, _ = adb("shell", "pm", "path", package)
    return code == 0 and "package:" in out


def android_google_account_present():
    """Only return presence; never expose account names from dumpsys."""
    code, out, _ = adb("shell", "dumpsys", "account")
    if code:
        return None
    return bool(re.search(r"\btype=com\.google\b", out))


def screenshot(outdir, filename, enabled):
    if not enabled:
        return
    code, content, _ = adb("exec-out", "screencap", "-p", binary=True)
    if code == 0 and content.startswith(b"\x89PNG"):
        (outdir / filename).write_bytes(content)


def dump_ui():
    code, _, error = adb("shell", "uiautomator", "dump", "/sdcard/google_one_ui.xml", timeout=40)
    if code:
        return [], "uiautomator: " + error[:200]
    code, out, error = adb("exec-out", "cat", "/sdcard/google_one_ui.xml")
    if code:
        return [], "UI pull: " + error[:200]
    try:
        root = ET.fromstring(out)
    except ET.ParseError:
        return [], "invalid UI XML"
    return [node.attrib for node in root.iter("node")], None


def tap_text(text_options):
    items, error = dump_ui()
    if error:
        return False, error
    for search in text_options:
        for item in items:
            labels = item.get("text", "") + " " + item.get("content-desc", "")
            if search.casefold() not in labels.casefold():
                continue
            coords = re.findall(r"\d+", item.get("bounds", ""))
            if len(coords) != 4:
                continue
            x1, y1, x2, y2 = map(int, coords)
            code, _, _ = adb("shell", "input", "tap", str((x1+x2)//2), str((y1+y2)//2))
            return code == 0, search
    return False, "not visible"


def open_account_login():
    """Start official Android account settings; Google manages credential entry."""
    code, _, error = adb("shell", "am", "start", "-a", "android.settings.ADD_ACCOUNT_SETTINGS")
    if code:
        return False, error[:180]
    return True, "opened Android add-account settings"


def wait_for_account(seconds):
    deadline = time.monotonic() + max(0, seconds)
    while time.monotonic() < deadline:
        if android_google_account_present() is True:
            return True
        time.sleep(min(5, max(0, deadline - time.monotonic())))
    return False


def open_play_store_listing():
    return adb("shell", "am", "start", "-a", "android.intent.action.VIEW", "-d",
               "market://details?id=" + GOOGLE_ONE, "-p", GOOGLE_PLAY)


def wait_for_package(seconds):
    deadline = time.monotonic() + max(0, seconds)
    while time.monotonic() < deadline:
        if package_installed(GOOGLE_ONE):
            return True
        time.sleep(min(5, max(0, deadline - time.monotonic())))
    return package_installed(GOOGLE_ONE)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Google One native Android sign-in and offer UI probe")
    parser.add_argument("--interactive", action="store_true",
                        help="Wait for Android Google login and official Google One Play Store install")
    parser.add_argument("--wait-seconds", type=int, default=240)
    parser.add_argument("--apk", type=Path, help="Optional local Google One APK")
    parser.add_argument("--screenshots", action="store_true", help="Save screenshots locally")
    parser.add_argument("--result-dir", type=Path, default=Path("native_test_results"))
    args = parser.parse_args(argv)
    outdir = args.result_dir
    outdir.mkdir(parents=True, exist_ok=True)
    report = {"at": datetime.now(timezone.utc).isoformat(), "outcome": "starting"}
    try:
        code, devices, error = adb("devices")
        online = [line.split()[0] for line in devices.splitlines()[1:]
                  if line.split()[1:] == ["device"]]
        if code or not online:
            raise RuntimeError("ADB Android device unavailable: " + error[:100])
        report["adb_online"] = True
        report["model"] = getprop("ro.product.model")
        report["android"] = getprop("ro.build.version.release")
        report["api"] = getprop("ro.build.version.sdk")
        report["google_play"] = package_installed(GOOGLE_PLAY)
        report["google_play_services"] = package_installed("com.google.android.gms")
        report["android_account_present"] = android_google_account_present()
        report["google_one_installed"] = package_installed(GOOGLE_ONE)
        print("Android", report["android"], "model", report["model"],
              "Play Store", report["google_play"], flush=True)

        # Browser/CDP Pixel identity is not an Android device identity.
        if report["android_account_present"] is not True:
            if not args.interactive:
                report["outcome"] = "requires_android_google_login"
                print("Android Google account is missing; interactive OS login is required.", flush=True)
                return report
            ok, reason = open_account_login()
            if not ok:
                report["outcome"] = "account_settings_failed"
                report["reason"] = reason
                return report
            print("Sign in on Android using Google's own sign-in screen.", flush=True)
            if not wait_for_account(args.wait_seconds):
                report["outcome"] = "android_login_not_completed"
                return report
            report["android_account_present"] = True
            print("Android Google account login detected.", flush=True)

        if not report["google_one_installed"] and args.apk:
            if not args.apk.is_file():
                report["outcome"] = "apk_file_missing"
                return report
            code, output, error = adb("install", "-r", str(args.apk), timeout=100)
            report["apk_install_ok"] = code == 0 and "Success" in output
            if not report["apk_install_ok"]:
                report["apk_install_error"] = (error or output)[:250]
            report["google_one_installed"] = package_installed(GOOGLE_ONE)

        if not report["google_one_installed"]:
            if not report["google_play"]:
                report["outcome"] = "google_play_unavailable"
                return report
            code, _, err = open_play_store_listing()
            if code:
                report["outcome"] = "google_one_play_listing_failed"
                report["reason"] = err[:200]
                return report
            screenshot(outdir, "google_one_play_store.png", args.screenshots)
            if not args.interactive:
                report["outcome"] = "google_one_install_required"
                return report
            print("Install official Google One from Play Store on the Android screen.", flush=True)
            if not wait_for_package(args.wait_seconds):
                report["outcome"] = "google_one_install_not_completed"
                return report
            report["google_one_installed"] = True

        code, output, err = adb("shell", "monkey", "-p", GOOGLE_ONE,
                                "-c", "android.intent.category.LAUNCHER", "1")
        report["launch_ok"] = code == 0 and "Events injected: 1" in output
        if not report["launch_ok"]:
            report["outcome"] = "google_one_launch_failed"
            report["reason"] = err[:170]
            return report
        time.sleep(3)
        screenshot(outdir, "google_one_open.png", args.screenshots)
        report["outcome"] = "google_one_opened_with_android_account"
        ok, _ = tap_text(["Settings", "الإعدادات", "Paramètres"])
        report["settings_found"] = ok
        if ok:
            time.sleep(2)
            screenshot(outdir, "google_one_settings.png", args.screenshots)
            ok, _ = tap_text(["Check for offers", "البحث عن عروض", "Vérifier les offres"])
            report["check_for_offers_found"] = ok
            if ok:
                time.sleep(3)
                screenshot(outdir, "google_one_offers.png", args.screenshots)
                report["outcome"] = "offer_check_screen_opened"
        return report
    except Exception as exc:
        report["outcome"] = "error"
        report["error"] = repr(exc)[:250]
        print("Error:", str(exc), file=sys.stderr)
        return report
    finally:
        (outdir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("RESULT:", json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
