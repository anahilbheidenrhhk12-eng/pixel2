"""
Configuration and constants for the Pixel 10 Pro Google One Gemini Bot.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _load_local_env() -> None:
    """Populate os.environ from a local .env file when present."""
    env_path = Path(__file__).resolve().with_name(".env")
    if not env_path.exists():
        return

    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except Exception:
        # Non-fatal: explicit environment variables still take priority.
        pass


_load_local_env()


def _env_flag(name: str, default: str = "0") -> bool:
    """Return True for common truthy environment variable values."""
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    """Return an integer environment variable, falling back safely on bad input."""
    raw_value = os.environ.get(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        logger.warning("Invalid integer for %s=%r; using fallback %s", name, raw_value, default)
        return default


def _env_float(name: str, default: float) -> float:
    """Return a float environment variable, falling back safely on bad input."""
    raw_value = os.environ.get(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        logger.warning("Invalid float for %s=%r; using fallback %s", name, raw_value, default)
        return default


def _env_text(name: str, default: str = "", allow_blank: bool = False) -> str:
    """Return a string environment variable with optional blank fallback handling."""
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    value = raw_value.strip()
    if not allow_blank and value == "":
        return default
    return value

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
BOT_HEADER_MEDIA_URL = _env_text(
    "BOT_HEADER_MEDIA_URL",
    str(Path(__file__).resolve().parent / "assets" / "telegram" / "pixel-header.png"),
)

# ── Device specs – Available device profiles ────────────────────────────────
# Each preset describes a stock Pixel build that the bot can simulate.
# Only Pixel devices that qualify for the Google One AI Premium (2 TB)
# 12-month trial are listed here: the Pixel 9 Pro / 9 Pro XL / 9 Pro Fold and
# the Pixel 10 Pro / 10 Pro XL / 10 Pro Fold.
DEVICE_PRESETS: dict[str, dict[str, str]] = {
    "pixel_10_pro": {
        "model": "Pixel 10 Pro",
        "brand": "google",
        "manufacturer": "Google",
        "android_version": "16",
        "android_sdk": "36",
        "build_id": "AP4A.250405.002",
        "accept_language": "en-US,en;q=0.9",
        "locale": "en-US",
    },
    "pixel_10_pro_xl": {
        "model": "Pixel 10 Pro XL",
        "brand": "google",
        "manufacturer": "Google",
        "android_version": "16",
        "android_sdk": "36",
        "build_id": "AP4A.250405.003",
        "accept_language": "en-US,en;q=0.9",
        "locale": "en-US",
    },
    "pixel_10_pro_fold": {
        "model": "Pixel 10 Pro Fold",
        "brand": "google",
        "manufacturer": "Google",
        "android_version": "16",
        "android_sdk": "36",
        "build_id": "AP4A.250405.004",
        "accept_language": "en-US,en;q=0.9",
        "locale": "en-US",
    },
    "pixel_9_pro": {
        "model": "Pixel 9 Pro",
        "brand": "google",
        "manufacturer": "Google",
        "android_version": "16",
        "android_sdk": "36",
        "build_id": "AP4A.250405.005",
        "accept_language": "en-US,en;q=0.9",
        "locale": "en-US",
    },
    "pixel_9_pro_xl": {
        "model": "Pixel 9 Pro XL",
        "brand": "google",
        "manufacturer": "Google",
        "android_version": "16",
        "android_sdk": "36",
        "build_id": "AP4A.250405.006",
        "accept_language": "en-US,en;q=0.9",
        "locale": "en-US",
    },
    "pixel_9_pro_fold": {
        "model": "Pixel 9 Pro Fold",
        "brand": "google",
        "manufacturer": "Google",
        "android_version": "16",
        "android_sdk": "36",
        "build_id": "AP4A.250405.007",
        "accept_language": "en-US,en;q=0.9",
        "locale": "en-US",
    },
}

DEFAULT_DEVICE_PROFILE = "pixel_10_pro"
DEVICE_PROFILE_NAME = (
    _env_text("DEVICE_PROFILE", DEFAULT_DEVICE_PROFILE).lower().replace("-", "_")
)
if DEVICE_PROFILE_NAME not in DEVICE_PRESETS:
    logger.warning(
        "Unknown DEVICE_PROFILE=%r; falling back to %s",
        DEVICE_PROFILE_NAME,
        DEFAULT_DEVICE_PROFILE,
    )
    DEVICE_PROFILE_NAME = DEFAULT_DEVICE_PROFILE

_active_device_preset = DEVICE_PRESETS[DEVICE_PROFILE_NAME]
DEVICE_MODEL = _active_device_preset["model"]
DEVICE_BRAND = _active_device_preset["brand"]
DEVICE_MANUFACTURER = _active_device_preset["manufacturer"]
ANDROID_VERSION = _active_device_preset["android_version"]
ANDROID_SDK = _active_device_preset["android_sdk"]
BUILD_ID = _active_device_preset["build_id"]
DEVICE_ACCEPT_LANGUAGE = _active_device_preset["accept_language"]
DEVICE_LOCALE = _active_device_preset["locale"]
# Fallback emulation values used only when route-based geo detection is unavailable.
EMULATION_TIMEZONE_ID = _env_text("EMULATION_TIMEZONE_ID", "America/Los_Angeles")
EMULATION_GEO_LATITUDE = _env_float("EMULATION_GEO_LATITUDE", 37.3861)
EMULATION_GEO_LONGITUDE = _env_float("EMULATION_GEO_LONGITUDE", -122.0839)
EMULATION_GEO_ACCURACY = _env_int("EMULATION_GEO_ACCURACY", 100)

# ── Auto-detect installed Chrome version ─────────────────────────────────────
# Avoids UA/Client-Hints mismatch with the actual browser binary.
def _chrome_binary_candidates() -> list[str]:
    """Return candidate Chrome/Chromium binaries in priority order."""
    import shutil

    candidates: list[str] = []

    def _add(candidate: str | None) -> None:
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    _add(os.environ.get("CHROME_BIN"))
    for binary in ("chromium", "chromium-browser", "google-chrome", "chrome", "chrome.exe"):
        _add(shutil.which(binary))

    if os.name == "nt":
        for candidate in (
            os.path.join(os.environ.get("PROGRAMFILES", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome", "Application", "chrome.exe"),
        ):
            if candidate and os.path.exists(candidate):
                _add(candidate)

    return candidates


def _detect_chrome_version() -> tuple[str, int]:
    """Detect installed Chrome/Chromium version. Falls back to defaults."""
    import subprocess

    def _parse_version_token(raw: str) -> tuple[str, int] | None:
        for part in raw.split():
            if "." in part and part[0].isdigit():
                try:
                    return part, int(part.split(".")[0])
                except (TypeError, ValueError):
                    return None
        return None

    env_version = os.environ.get("CHROME_VERSION", "").strip()
    if env_version:
        try:
            return env_version, int(env_version.split(".")[0])
        except (TypeError, ValueError):
            pass

    for path in _chrome_binary_candidates():
        try:
            out = subprocess.check_output(
                [path, "--version"], stderr=subprocess.DEVNULL, timeout=5,
            ).decode().strip()
            parsed = _parse_version_token(out)
            if parsed:
                return parsed
        except Exception:
            pass

        if os.name == "nt" and os.path.exists(path):
            try:
                escaped_path = path.replace("'", "''")
                out = subprocess.check_output(
                    [
                        "powershell.exe",
                        "-NoProfile",
                        "-Command",
                        f"(Get-Item '{escaped_path}').VersionInfo.ProductVersion",
                    ],
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                ).decode().strip()
                parsed = _parse_version_token(out)
                if parsed:
                    return parsed
            except Exception:
                pass
    return "124.0.6367.82", 124

CHROME_VERSION, CHROME_MAJOR_VERSION = _detect_chrome_version()

# Pool of realistic Pixel 10 Pro user-agent strings.
# Keep these browser-consistent; avoid WebView-only markers unless the
# underlying runtime is actually Android WebView.
USER_AGENT_TEMPLATES = [
    (
        "Mozilla/5.0 (Linux; Android {android}; {model}) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/{chrome} Mobile Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Linux; Android {android}; {model} Build/{build}) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/{chrome} Mobile Safari/537.36"
    ),
]

# ── Google URLs ───────────────────────────────────────────────────────────────
GMAIL_LOGIN_URL = "https://accounts.google.com/signin/v2/identifier"
GOOGLE_ONE_URL = "https://one.google.com/"
GOOGLE_ONE_OFFERS_URL = "https://one.google.com/about/plans"

# ── Gemini offer detection keywords ──────────────────────────────────────────
GEMINI_OFFER_KEYWORDS = [
    "gemini pro",
    "gemini advanced",
    "12 month",
    "12-month",
    "free trial",
    "activate",
    "get started",
    "claim offer",
    "redeem",
]

# Only accept offer links whose domain matches one of these.
# This prevents generic keywords ("activate", "get started") from
# matching unrelated links on Google pages.
OFFER_DOMAIN_WHITELIST = [
    "one.google.com",
    "gemini.google.com",
    "play.google.com",
    "accounts.google.com",
    "pay.google.com",
]

# ── Selenium / WebDriver ──────────────────────────────────────────────────────
WEBDRIVER_TIMEOUT = 30          # seconds – explicit wait
IMPLICIT_WAIT = 10              # seconds
PAGE_LOAD_TIMEOUT = 60          # seconds
HEADLESS = True                # set to False for local debugging with visible browser
BROWSER_IGNORE_CERT_ERRORS = _env_flag("BROWSER_IGNORE_CERT_ERRORS", "0")
GOOGLE_PASSWORD_STAGE_TIMEOUT_SECONDS = _env_int("GOOGLE_PASSWORD_STAGE_TIMEOUT_SECONDS", 12)
START_VISIBLE_WITH_AUTH_PROXY = _env_flag("START_VISIBLE_WITH_AUTH_PROXY", "1")
GOOGLE_CAPTCHA_AUTO_SOLVE = _env_flag("GOOGLE_CAPTCHA_AUTO_SOLVE", "1")
GOOGLE_CAPTCHA_MAX_AUDIO_ATTEMPTS = _env_int("GOOGLE_CAPTCHA_MAX_AUDIO_ATTEMPTS", 3)
WIT_AI_TOKEN = _env_text("WIT_AI_TOKEN", "", allow_blank=True)
WIT_AI_SPEECH_API_VERSION = _env_text("WIT_AI_SPEECH_API_VERSION", "20240304")
WIT_AI_TIMEOUT_SECONDS = _env_int("WIT_AI_TIMEOUT_SECONDS", 45)

# ── Proxy / Rotation ──────────────────────────────────────────────────────────
PROXY_ENABLED = _env_flag("PROXY_ENABLED", "1")
PROXY_FILE_PATH = _env_text(
    "PROXY_FILE_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "proxies.txt"),
)
PROXY_FAILURE_COOLDOWN_SECONDS = _env_int("PROXY_FAILURE_COOLDOWN_SECONDS", 90)
PROXY_QUARANTINE_SECONDS = _env_int("PROXY_QUARANTINE_SECONDS", 300)
PROXY_QUARANTINE_THRESHOLD = _env_int("PROXY_QUARANTINE_THRESHOLD", 3)
PROXY_PRECHECK_ENABLED = _env_flag("PROXY_PRECHECK_ENABLED", "1")
PROXY_PRECHECK_TIMEOUT_SECONDS = _env_int("PROXY_PRECHECK_TIMEOUT_SECONDS", 12)
PROXY_DIAGNOSTICS_VERIFY_SSL = _env_flag("PROXY_DIAGNOSTICS_VERIFY_SSL", "0")
REGENERATE_DEVICE_ON_RETRY = _env_flag("REGENERATE_DEVICE_ON_RETRY", "1")

# ── Email validation ──────────────────────────────────────────────────────────
# Leave empty to accept any valid email domain (Gmail + Google Workspace).
# Populate with specific domains to restrict, e.g. ["gmail.com", "mycompany.com"]
ALLOWED_EMAIL_DOMAINS: list[str] = []

# ── Session ───────────────────────────────────────────────────────────────────
# Session time-to-live in seconds.  After this period the session
# (including any stored credentials) is automatically purged.
SESSION_TTL_SECONDS: int = 30 * 60   # 30 minutes

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
