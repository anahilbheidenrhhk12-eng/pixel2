"""Provision and launch a persistent Google Play Android Emulator on Windows.

Installs official Android SDK command line tools and Google Play system image
into user-writable folders when Android Studio is not already available.
Never exposes ADB over the network.
"""
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

AVD_NAME = "Digi_Pixel_11_Pro_XL"
ONE_APP = "com.google.android.apps.subscriptions.red"
CMDLINE_TOOLS = "https://dl.google.com/android/repository/commandlinetools-win-15859902_latest.zip"
CMDLINE_SHA256 = "90ae805d20434428bffcb699c290860f19bb5f66a67e6b330067e3de801fb04a"


def home():
    return Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "DigiPixelServer"


def fetch(url, destination, expected_sha=None, progress=None):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if progress:
        progress("Downloading " + destination.name)
    req = urllib.request.Request(url, headers={"User-Agent": "DigiPixelServer/1.0"})
    h = hashlib.sha256()
    with urllib.request.urlopen(req, timeout=90) as response, destination.open("wb") as out:
        while True:
            data = response.read(1024 * 1024)
            if not data:
                break
            h.update(data)
            out.write(data)
    if expected_sha and h.hexdigest().lower() != expected_sha.lower():
        destination.unlink(missing_ok=True)
        raise RuntimeError("Downloaded Android command-line tools checksum did not match official SHA256")
    return destination


def unzip_safe(archive, destination):
    destination.mkdir(parents=True, exist_ok=True)
    base = destination.resolve()
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            target = (destination / name).resolve()
            if target != base and base not in target.parents:
                raise RuntimeError("Unsafe ZIP path")
        z.extractall(destination)


def sdk_env(sdk_root):
    env = dict(os.environ)
    env["ANDROID_HOME"] = str(sdk_root)
    env["ANDROID_SDK_ROOT"] = str(sdk_root)
    env["PATH"] = (str(sdk_root / "platform-tools") + os.pathsep
                   + str(sdk_root / "emulator") + os.pathsep
                   + env.get("PATH", ""))
    return env


def ensure_java(env, progress):
    if os.getenv("JAVA_HOME") and (Path(os.getenv("JAVA_HOME")) / "bin" / "java.exe").exists():
        env["JAVA_HOME"] = os.getenv("JAVA_HOME")
        env["PATH"] = str(Path(env["JAVA_HOME"]) / "bin") + os.pathsep + env["PATH"]
        return env
    if shutil.which("java"):
        return env
    dest = home() / "java"
    existing = next(dest.glob("*/bin/java.exe"), None) if dest.is_dir() else None
    if not existing:
        progress("Installing Java runtime for Android SDK...")
        # Adoptium distributes official Eclipse Temurin OpenJDK binaries.
        archive = fetch(
            "https://api.adoptium.net/v3/binary/latest/21/ga/windows/x64/jre/hotspot/normal/eclipse",
            home() / "downloads" / "java21.zip", progress=progress
        )
        unzip_safe(archive, dest)
        archive.unlink(missing_ok=True)
        existing = next(dest.glob("*/bin/java.exe"), None)
    if not existing:
        raise RuntimeError("Java runtime was not installed")
    env["JAVA_HOME"] = str(existing.parent.parent)
    env["PATH"] = str(existing.parent) + os.pathsep + env["PATH"]
    return env


def find_sdk():
    possible = [
        os.getenv("ANDROID_HOME", ""),
        os.getenv("ANDROID_SDK_ROOT", ""),
        str(Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "Android" / "Sdk"),
        str(home() / "android-sdk"),
    ]
    for path in possible:
        if path and (Path(path) / "emulator" / "emulator.exe").is_file() and (
            Path(path) / "platform-tools" / "adb.exe").is_file():
            return Path(path)
    return home() / "android-sdk"


def run(command, env=None, input_data=None, timeout=300):
    proc = subprocess.run(
        [str(x) for x in command],
        input=input_data,
        capture_output=True,
        text=True,
        errors="replace",
        env=env,
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if proc.returncode:
        raise RuntimeError((proc.stderr or proc.stdout or "Command failed")[-1400:])
    return proc.stdout


def ensure_cmdline(sdk, progress):
    manager = sdk / "cmdline-tools" / "latest" / "bin" / "sdkmanager.bat"
    if manager.is_file():
        return manager
    progress("Downloading official Android command-line tools...")
    archive = fetch(CMDLINE_TOOLS, home() / "downloads" / "commandlinetools.zip",
                    CMDLINE_SHA256, progress)
    with tempfile.TemporaryDirectory(dir=str(home())) as td:
        unzip_safe(archive, Path(td))
        unpacked = Path(td) / "cmdline-tools"
        if not (unpacked / "bin" / "sdkmanager.bat").is_file():
            raise RuntimeError("Unexpected command-line tools archive format")
        manager.parent.parent.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(unpacked, manager.parent.parent, dirs_exist_ok=True)
    archive.unlink(missing_ok=True)
    return manager


def image_package(sdk, manager, env, progress):
    available = run([manager, "--sdk_root=" + str(sdk), "--list"], env, timeout=600)
    names = [
        "system-images;android-37;google_apis_playstore;x86_64",
        "system-images;android-36;google_apis_playstore;x86_64",
        "system-images;android-35;google_apis_playstore;x86_64",
        "system-images;android-34;google_apis_playstore;x86_64",
    ]
    for item in names:
        if item in available:
            return item
    raise RuntimeError("No compatible Google Play Android system image is currently listed by the SDK")


def ensure_avd(progress):
    if os.name != "nt":
        raise RuntimeError("This package requires Windows 10 or Windows 11")
    sdk = find_sdk()
    env = sdk_env(sdk)
    env = ensure_java(env, progress)
    manager = ensure_cmdline(sdk, progress)
    avdmanager = sdk / "cmdline-tools" / "latest" / "bin" / "avdmanager.bat"
    adb = sdk / "platform-tools" / "adb.exe"
    emulator = sdk / "emulator" / "emulator.exe"
    env["PATH"] = str(manager.parent) + os.pathsep + env["PATH"]
    package = image_package(sdk, manager, env, progress)

    if not adb.is_file() or not emulator.is_file() or not (
        Path.home() / ".android" / "avd" / (AVD_NAME + ".ini")).exists():
        progress("Installing Android Emulator + Google Play image (first run)...")
        run([manager, "--sdk_root=" + str(sdk), "--licenses"],
            env, input_data="y\n" * 150, timeout=300)
        run([manager, "--sdk_root=" + str(sdk), "platform-tools", "emulator", package],
            env, input_data="y\n" * 150, timeout=3600)
    if not adb.is_file() or not emulator.is_file():
        raise RuntimeError("Emulator or ADB could not be installed")
    avd_ini = Path.home() / ".android" / "avd" / (AVD_NAME + ".ini")
    if not avd_ini.exists():
        progress("Creating persistent Google Play Android device: " + AVD_NAME)
        try:
            run([avdmanager, "create", "avd", "-n", AVD_NAME, "-k", package,
                 "--device", "pixel_9_pro_xl", "--force"], env, input_data="no\n", timeout=300)
        except Exception:
            run([avdmanager, "create", "avd", "-n", AVD_NAME, "-k", package,
                 "--device", "pixel", "--force"], env, input_data="no\n", timeout=300)
        ini = Path.home() / ".android" / "avd" / (AVD_NAME + ".avd") / "config.ini"
        if ini.is_file():
            with ini.open("a", encoding="utf-8") as output:
                output.write("\nhw.lcd.width=1344\nhw.lcd.height=2992\nhw.lcd.density=480\nhw.ramSize=4096\n")
    os.environ.update({k: env[k] for k in ("ANDROID_HOME", "ANDROID_SDK_ROOT", "JAVA_HOME") if k in env})
    os.environ["PATH"] = env["PATH"]
    return sdk, env


def adb_command(sdk, *args, serial=None, binary=False, timeout=45):
    cmd = [str(sdk / "platform-tools" / "adb.exe")]
    if serial:
        cmd += ["-s", serial]
    cmd += [str(item) for item in args]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    output = proc.stdout if binary else proc.stdout.decode("utf-8", "replace").strip()
    if proc.returncode:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace")[-300:] or str(output)[:250])
    return output


def ready_emulator(sdk):
    devices = adb_command(sdk, "devices")
    return [row.split()[0] for row in devices.splitlines() if re.fullmatch(r"emulator-\d+\s+device", row.strip())]


def start_emulator(progress):
    sdk, env = ensure_avd(progress)
    existing = ready_emulator(sdk)
    if not existing:
        progress("Starting " + AVD_NAME + " emulator...")
        kwargs = {"env": env, "cwd": str(sdk / "emulator")}
        subprocess.Popen([str(sdk / "emulator" / "emulator.exe"), "-avd", AVD_NAME,
                          "-no-boot-anim"], **kwargs)
    deadline = time.monotonic() + 600
    serial = None
    while time.monotonic() < deadline:
        emulators = ready_emulator(sdk)
        if emulators:
            serial = emulators[0]
            try:
                if adb_command(sdk, "shell", "getprop", "sys.boot_completed", serial=serial, timeout=10) == "1":
                    break
            except Exception:
                pass
        time.sleep(4)
    else:
        raise RuntimeError("Android emulator did not finish booting. Check hardware virtualization support.")
    os.environ["ANDROID_SERIAL"] = serial
    if "package:" not in adb_command(sdk, "shell", "pm", "path", "com.android.vending", serial=serial):
        raise RuntimeError("The running Android image does not include Google Play")
    progress("Android Emulator ready • " + serial)
    return sdk, serial
