"""
Configuration and constants for the Pixel 11 Pro Google One Gemini Bot.
"""

import os

# ── Telegram ──────────────────────────────────────────────────────────────────
# Never embed bot credentials in source code or GitHub.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()

# ── Proxy (代理设置，国内用户请在此配置本地代理端口以畅通访问谷歌，例如 "http://127.0.0.1:7890") ──
PROXY = ""
# ── Device specs – Google Pixel 11 Pro (Android 17) ──────────────────────────
# Sourced from store.google.com/.../pixel_11_pro_specs, GSMArena and
# AndroidAuthority's Tensor G6 deep-dive / factory-image coverage (Nov 2026).
# Two values are our best inference rather than a value found written down
# verbatim: ANDROID_SDK (Google has incremented it by exactly 1 every year
# since Android 10 → 29, so Android 17 → 37, but no source states "37"
# directly) and the IMEI TAC list below (left as real, older Pixel TACs —
# see the comment there for why a fabricated "Pixel 11 Pro" TAC was not
# invented).
DEVICE_MODEL        = "Pixel 11 Pro"
DEVICE_BRAND        = "google"
DEVICE_MANUFACTURER = "Google"
ANDROID_VERSION     = "17"
ANDROID_SDK         = "37"
BUILD_ID            = "CD1A.260618.001"       # Pixel 11 Pro factory-image build fingerprint

# Hardware profile (used for navigator injection)
DEVICE_RAM_GB           = 16                  # 16 GB RAM variant (also spoofed by the Pixel 10 Pro profile)
DEVICE_CPU_CORES        = 7                   # Tensor G6: 1 Arm C1-Ultra + 4 Arm C1-Pro + 2 Arm C1-Pro = 7 reported cores (down from 8 on G5)
DEVICE_MAX_TOUCH        = 5                   # 5-point multitouch (realistic)
DEVICE_GPU_VENDOR       = "Imagination Technologies"
DEVICE_GPU_RENDERER     = "PowerVR CXTP-48-1536"  # Tensor G6 GPU (successor to the G5's DXT-48-1536)

# Screen – Pixel 11 Pro: same 6.3" / 1280×2856 / ~495 PPI panel as the Pixel
# 10 Pro, so the same CSS viewport (412×915 @3.5× density) still applies.
SCREEN_CSS_WIDTH    = 412
SCREEN_CSS_HEIGHT   = 915
SCREEN_PIXEL_RATIO  = 3.5

# ── Chrome 157 (latest stable for Android, Nov 2026) ─────────────────────────
CHROME_VERSION       = "157.0.8103.50"
CHROME_MAJOR_VERSION = 157

# ── User-Agent – Chrome UA Reduction (Chrome 110+) ───────────────────────────
# Modern Chrome on Android NEVER reveals device model in the UA string.
# The real device identity is sent via Sec-CH-UA-Model client hint.
# Format: "Mozilla/5.0 (Linux; Android 10; K) ... Chrome/<version> Mobile Safari/537.36"
USER_AGENT_TEMPLATES = [
    (
        "Mozilla/5.0 (Linux; Android 10; K) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/{chrome} Mobile Safari/537.36"
    ),
]

# ── Google URLs ───────────────────────────────────────────────────────────────
GMAIL_LOGIN_URL       = "https://accounts.google.com/signin/v2/identifier"
GOOGLE_ONE_URL        = "https://one.google.com/"
GOOGLE_ONE_OFFERS_URL = "https://one.google.com/about/plans"
GOOGLE_ONE_AI_URL     = "https://one.google.com/ai?hl=en-TN&g1_landing_page=75"

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

# ── Selenium / WebDriver ──────────────────────────────────────────────────────
WEBDRIVER_TIMEOUT  = 30   # seconds – explicit wait
IMPLICIT_WAIT      = 10   # seconds
PAGE_LOAD_TIMEOUT  = 60   # seconds
HEADLESS           = True # always headless on Replit

# ── Session storage ───────────────────────────────────────────────────────────
SESSION_STORE: dict = {}

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL  = "INFO"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
