"""Small health check; opens a blank page only, never logs into Google.

Run inside the deployed Docker image: python smoke_browser.py
"""
import os
import sys
from shutil import which
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service


def main() -> int:
    browser = os.environ.get("CHROME_BIN") or which("chromium") or which("google-chrome")
    driver_path = os.environ.get("CHROMEDRIVER_PATH") or which("chromedriver")
    if not browser or not os.path.isfile(browser):
        print("FAIL: Chromium executable not found")
        return 1
    if not driver_path or not os.path.isfile(driver_path):
        print("FAIL: ChromeDriver executable not found")
        return 1
    options = Options()
    options.binary_location = browser
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    try:
        with webdriver.Chrome(service=Service(executable_path=driver_path), options=options) as drv:
            drv.get("about:blank")
            print("PASS: Chromium and ChromeDriver launched; blank page opened")
            return 0
    except Exception as exc:
        print(f"FAIL: Browser launch error: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
