"""Digi Pixel Server - Windows GUI and outbound Railway agent.

Runs a Google Play Android Emulator locally, opens the native Google One app,
and can apply the existing pixel2 CDP profile to Android Chrome in that emulator.
Account sign-in stays on the official Android/Google screen, not in Telegram.
"""
import base64
import json
import os
import queue
import re
import secrets
import subprocess
import threading
import time
import tkinter as tk
import urllib.request
import zipfile
from pathlib import Path
from tkinter import messagebox, scrolledtext

from winpixel_sdk import AVD_NAME, ONE_APP, adb_command, home, start_emulator, fetch, unzip_safe

try:
    import native_google_one_probe
except ImportError:
    native_google_one_probe = None

APP_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
if getattr(__import__("sys"), "frozen", False):
    APP_DIR = Path(__import__("sys").executable).parent
CONNECTION = APP_DIR / "connection.json"
GOOGLE_URL = "https://one.google.com/"
ACTIONS = {"start", "account", "one", "offers", "screenshot", "pixel"}


class PixelServer:
    def __init__(self):
        self.sdk = None
        self.serial = None
        self.driver = None
        self.ready = False
        self.busy = False
        self.shutdown = threading.Event()
        self.work = queue.Queue()
        self.notifications = queue.Queue()
        self.pairing = "".join(str(secrets.randbelow(10)) for _ in range(8))
        self.status = "Windows server started"
        self.config = {}
        if CONNECTION.is_file():
            try:
                conf = json.loads(CONNECTION.read_text(encoding="utf-8"))
                if (str(conf.get("railway_url", "")).startswith("https://")
                        and len(str(conf.get("bridge_token", ""))) >= 32):
                    self.config = conf
            except Exception:
                pass
        self.root = tk.Tk()
        self.root.title("Digi Pixel Server • Pixel 11 Pro XL")
        self.root.geometry("580x610")
        self.root.minsize(500, 540)
        self.root.configure(bg="#0a1423")
        self.build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(200, self.refresh)
        threading.Thread(target=self.worker, daemon=True).start()
        threading.Thread(target=self.relay_loop, daemon=True).start()
        self.schedule("start", None, remote=False)

    def line(self, parent, text, size=12, color="#dbeafe", bold=False, pady=4):
        widget = tk.Label(parent, text=text, anchor="w", justify="left",
                          font=("Segoe UI", size, "bold" if bold else "normal"),
                          fg=color, bg="#0a1423")
        widget.pack(fill="x", pady=pady)
        return widget

    def build_ui(self):
        root = tk.Frame(self.root, bg="#0a1423", padx=24, pady=20)
        root.pack(fill="both", expand=True)
        self.line(root, "DIGI PRO  /  WINDOWS PIXEL SERVER", 11, "#2ae6b8", True)
        self.line(root, "Pixel 11 Pro XL  +  Google One", 22, "#ffffff", True, 10)
        self.line(root, "Official Google One app inside a persistent Android Emulator.", 11, "#a5b4ca")
        self.status_label = self.line(root, "Starting…", 12, "#fbbf24", True, 9)
        if self.config:
            self.line(root, "Railway bridge: connected after pairing", 11, "#93c5fd")
            self.line(root, "ONE-TIME TELEGRAM PAIRING NUMBER:", 11, "#a5b4ca", True, 7)
            self.line(root, self.pairing, 23, "#2ae6b8", True)
            self.line(root, "Send  /winpixel pair " + self.pairing + "  to your Telegram bot.", 10, "#a5b4ca")
        else:
            self.line(root, "Local mode (no Railway connection.json found).", 11, "#fbbf24")
        grid = tk.Frame(root, bg="#0a1423")
        grid.pack(fill="x", pady=15)
        buttons = [
            ("▶ START EMULATOR", "start"),
            ("🔐 ADD GOOGLE ACCOUNT", "account"),
            ("📲 OPEN GOOGLE ONE APP", "one"),
            ("🔎 CHECK FOR OFFERS", "offers"),
            ("🌐 PIXEL CHROME (CDP)", "pixel"),
            ("📸 SCREENSHOT", "screenshot"),
        ]
        for i, (name, action) in enumerate(buttons):
            b = tk.Button(grid, text=name, command=lambda a=action: self.schedule(a, None),
                          bg="#19bf9d" if i == 0 else "#182d46", fg="#071522" if i == 0 else "#f4fbff",
                          activebackground="#2ae6b8", activeforeground="#071522",
                          relief="flat", font=("Segoe UI", 10, "bold"),
                          pady=9, cursor="hand2")
            b.grid(row=i // 2, column=i % 2, sticky="ew", padx=5, pady=5)
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)
        self.log = scrolledtext.ScrolledText(root, height=9, bg="#0d1d32",
                                            fg="#cedcef", insertbackground="#cedcef",
                                            relief="flat", font=("Consolas", 9))
        self.log.pack(fill="both", expand=True)
        self.log.insert("end", "Server ready. Initial emulator setup downloads official Android components.\n")

    def set_status(self, message):
        self.status = message[:240]
        self.notifications.put(message[:500])

    def refresh(self):
        while True:
            try:
                msg = self.notifications.get_nowait()
            except queue.Empty:
                break
            self.status_label.configure(text=msg[:75], fg="#2ae6b8" if "ready" in msg.lower() else "#fbbf24")
            self.log.insert("end", time.strftime("%H:%M:%S") + "  " + msg + "\n")
            self.log.see("end")
        if not self.shutdown.is_set():
            self.root.after(250, self.refresh)

    def schedule(self, action, job_id, remote=False):
        if action not in ACTIONS:
            return
        self.work.put((action, job_id))
        if not remote:
            self.set_status("Queued " + action + " on Windows")

    def adb(self, *args, binary=False):
        if not self.sdk or not self.serial:
            raise RuntimeError("Start the emulator first")
        return adb_command(self.sdk, *args, serial=self.serial, binary=binary)

    def ensure(self):
        if not self.sdk or not self.serial:
            self.sdk, self.serial = start_emulator(self.set_status)
            self.ready = True
        return self.sdk, self.serial

    def installed(self, package):
        return "package:" in self.adb("shell", "pm", "path", package)

    def shot(self):
        if not self.sdk or not self.serial:
            return None
        image = self.adb("exec-out", "screencap", "-p", binary=True)
        return image if image.startswith(b"\x89PNG") else None

    def open_account(self):
        self.ensure()
        self.adb("shell", "am", "start", "-a", "android.settings.ADD_ACCOUNT_SETTINGS")
        return "🔐 Google account settings opened IN YOUR WINDOWS EMULATOR. Sign in there; the account remains on this emulator."

    def open_one(self):
        self.ensure()
        if not self.installed(ONE_APP):
            self.adb("shell", "am", "start", "-a", "android.intent.action.VIEW", "-d",
                     "market://details?id=" + ONE_APP, "-p", "com.android.vending")
            return "📲 Google One Play Store page opened INSIDE Android. Tap Install once. Future starts will open the installed app."
        self.adb("shell", "monkey", "-p", ONE_APP, "-c", "android.intent.category.LAUNCHER", "1")
        return "✅ Google One native Android app opened inside the Windows emulator."

    def offers(self):
        reply = self.open_one()
        if not self.installed(ONE_APP):
            return reply
        time.sleep(3)
        if native_google_one_probe is None:
            return reply + "\nOpen Settings > Check for offers on the Android screen."
        try:
            ok, _ = native_google_one_probe.tap_text(["Settings", "الإعدادات", "Paramètres"])
            if not ok:
                return reply + "\nSettings button not detected; tap it manually."
            time.sleep(2)
            checked, _ = native_google_one_probe.tap_text(
                ["Check for offers", "البحث عن عروض", "Vérifier les offres"])
            return reply + ("\n🔎 Check for offers screen opened." if checked
                            else "\nSettings opened. Check for offers was not detected.")
        except Exception as exc:
            return reply + "\nOffer navigation: " + str(exc)[:150]

    def chromedriver(self, major):
        root = home() / "chromedriver" / major
        executable = root / "chromedriver-win64" / "chromedriver.exe"
        if executable.is_file():
            return executable
        self.set_status("Downloading matching Android ChromeDriver " + major)
        version = urllib.request.urlopen(
            "https://googlechromelabs.github.io/chrome-for-testing/LATEST_RELEASE_" + major,
            timeout=30).read().decode("ascii").strip()
        if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", version):
            raise RuntimeError("Invalid ChromeDriver release string")
        archive = fetch("https://storage.googleapis.com/chrome-for-testing-public/"
                        + version + "/win64/chromedriver-win64.zip",
                        home() / "downloads" / ("driver-" + major + ".zip"),
                        progress=self.set_status)
        unzip_safe(archive, root)
        archive.unlink(missing_ok=True)
        return executable

    def pixel_chrome(self):
        self.ensure()
        if not self.installed("com.android.chrome"):
            return "Chrome Android is missing. Install Chrome from Play Store."
        self.set_status("Opening Android Chrome with original Pixel 11 CDP profile")
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from device_simulator import create_device_profile
        import config as pixel_config
        # The same profile generator / client hints / document-level JS
        # used in the original Railway Pixel Chrome implementation.
        profile = create_device_profile()
        chrome_package = self.adb("shell", "dumpsys", "package", "com.android.chrome")
        match = re.search(r"versionName=(\d+)\.", chrome_package)
        major = match.group(1) if match else str(pixel_config.CHROME_MAJOR_VERSION)
        driver_file = self.chromedriver(major)
        # Start Android Chrome in this AVD before attaching ChromeDriver.
        # The browser runs on the emulated Android device, not Windows.
        self.adb("shell", "am", "start", "-a", "android.intent.action.VIEW",
                 "-d", GOOGLE_URL, "-p", "com.android.chrome")
        time.sleep(2)
        opts = webdriver.ChromeOptions()
        opts.add_experimental_option("androidPackage", "com.android.chrome")
        opts.add_experimental_option("androidDeviceSerial", self.serial)
        opts.add_experimental_option("androidUseRunningApp", True)
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
        driver = webdriver.Chrome(service=Service(str(driver_file)), options=opts)
        try:
            driver.execute_cdp_cmd("Network.enable", {})
            driver.execute_cdp_cmd("Network.setUserAgentOverride", {
                "userAgent": profile.user_agent,
                "platform": "Android",
                "acceptLanguage": "en-US,en;q=0.9",
                "userAgentMetadata": profile.client_hints_metadata(),
            })
            driver.execute_cdp_cmd("Network.setExtraHTTPHeaders", {
                "headers": profile.client_hints_headers(),
            })
            driver.execute_cdp_cmd("Emulation.setDeviceMetricsOverride", {
                "width": profile.screen_width,
                "height": profile.screen_height,
                "deviceScaleFactor": profile.pixel_ratio,
                "mobile": True,
            })
            driver.execute_cdp_cmd("Emulation.setTouchEmulationEnabled", {
                "enabled": True, "maxTouchPoints": profile.max_touch_points,
            })
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": profile.navigator_js(),
            })
            driver.get(GOOGLE_URL)
        except Exception:
            driver.quit()
            raise
        self.driver = driver
        return "🌐 Original Pixel 11 Pro XL CDP browser profile launched INSIDE Android Chrome. The Google One app is available separately in the same emulator."

    def execute(self, action):
        if action == "start":
            self.ensure()
            first_screen = self.open_one()
            return "✅ Persistent Android Emulator ready: " + AVD_NAME + "\n" + self.serial + "\n" + first_screen
        if action == "account":
            return self.open_account()
        if action == "one":
            return self.open_one()
        if action == "offers":
            return self.offers()
        if action == "pixel":
            return self.pixel_chrome()
        if action == "screenshot":
            self.ensure()
            return "📸 Screenshot captured from Windows Android Emulator."
        return "Unknown command"

    def worker(self):
        while not self.shutdown.is_set():
            try:
                action, job_id = self.work.get(timeout=1)
            except queue.Empty:
                continue
            self.busy = True
            self.set_status("Processing " + action)
            screenshot = None
            try:
                message = self.execute(action)
                if action in ("one", "offers", "screenshot", "pixel"):
                    screenshot = self.shot()
                self.set_status("Ready • " + action)
            except Exception as exc:
                message = "❌ Windows Android: " + str(exc)[:700]
                self.set_status("Error • " + str(exc)[:140])
            finally:
                self.busy = False
            if job_id:
                self.post_result(job_id, message, screenshot)
            self.work.task_done()

    def request(self, endpoint, data, timeout=30):
        cfg = self.config
        url = cfg["railway_url"].rstrip("/") + "/winpixel/agent/" + endpoint
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url, payload,
            headers={"Authorization": "Bearer " + cfg["bridge_token"],
                     "Content-Type": "application/json", "User-Agent": "DigiPixelServer/1.0"},
            method="POST")
        with urllib.request.urlopen(request, timeout=timeout) as res:
            return json.loads(res.read().decode("utf-8"))

    def relay_loop(self):
        if not self.config:
            self.set_status("Local only. connection.json not installed.")
            return
        while not self.shutdown.is_set():
            try:
                result = self.request("poll", {
                    "pair_code": self.pairing,
                    "status": ("Busy • " if self.busy else "Idle • ") + self.status[:140],
                })
                action = result.get("action", "")
                job = result.get("job_id", "")
                if action in ACTIONS and job:
                    self.schedule(action, job, remote=True)
            except Exception as exc:
                self.set_status("Railway reconnect: " + str(exc)[:90])
            self.shutdown.wait(4)

    def post_result(self, job_id, message, screenshot):
        if not self.config:
            return
        payload = {"job_id": job_id, "message": message[:1400], "screenshot": ""}
        if screenshot and len(screenshot) <= 4_000_000:
            payload["screenshot"] = base64.b64encode(screenshot).decode("ascii")
        for attempt in range(3):
            try:
                self.request("result", payload, timeout=50)
                return
            except Exception as exc:
                self.set_status("Result delivery retry: " + str(exc)[:80])
                time.sleep(3)

    def close(self):
        self.shutdown.set()
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    PixelServer().run()
