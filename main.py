"""
Telegram Bot entry point for the Pixel 10 Pro Google One Gemini Bot.

Commands:
  /start        – Show welcome message and available commands
  /doctor       – Run a first-time setup self-check
  /login        – Begin credential capture flow (email → password)
  /witai        – Save or clear the Wit.ai token used for audio captcha solving
  /logout       – Clear stored credentials and session data
  /check_offer  – Run Google One automation and look for Gemini Pro offer
  /get_link     – Show the last captured offer link
  /status       – Show current session status and device profile
  /disable_proxy – Force the current session to use direct/local IP
  /lang_id      – Switch chat language to Indonesian
  /langid       – Alias for /lang_id

Supports both Gmail (user@gmail.com) and Google Workspace (user@company.com)
accounts.
"""

import logging
import os
import sys

# Clean up NO_PROXY / no_proxy to prevent httpx from crashing on IPv6 loopback addresses like ::1 on Windows
for _var_name in ("no_proxy", "NO_PROXY"):
    if _var_name in os.environ:
        _parts = [p.strip() for p in os.environ[_var_name].split(",")]
        _cleaned = [p for p in _parts if p not in ("::1", "::1/128")]
        os.environ[_var_name] = ",".join(_cleaned)

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

import config
from handlers import (
    AWAIT_2FA_CODE,
    AWAIT_EMAIL,
    AWAIT_MANUAL_VERIFICATION,
    AWAIT_PASSWORD,
    AWAIT_WIT_AI_TOKEN,
    DEVICE_CALLBACK_PREFIX,
    cancel_2fa,
    check_offer,
    device_menu,
    device_select,
    doctor,
    disable_proxy,
    get_link,
    handle_2fa_code,
    handle_manual_verification,
    ip_status,
    lang_en,
    lang_id,
    login_cancel,
    login_email,
    login_password,
    login_start,
    logout,
    offer_timeout,
    proxy_status,
    rotate_proxy,
    session_cleanup_job,
    start,
    status,
    wit_ai_cancel,
    wit_ai_start,
    wit_ai_token,
)
from handlers.ui import button_regex
from services.setup_diagnostics import collect_setup_diagnostics

# ── Logging ───────────────────────────────────────────────────────────────────
from datetime import datetime as _dt

_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)

_formatter = logging.Formatter(config.LOG_FORMAT)

# Console handler
_console_handler = logging.StreamHandler()
_console_handler.setFormatter(_formatter)

# File handler – new file per startup: bot_YYYYMMDD_HHMMSS.log
_log_filename = f"bot_{_dt.now().strftime('%Y%m%d_%H%M%S')}.log"
_file_handler = logging.FileHandler(
    os.path.join(_LOG_DIR, _log_filename),
    encoding="utf-8",
)
_file_handler.setFormatter(_formatter)

logging.basicConfig(
    level=config.LOG_LEVEL,
    handlers=[_console_handler, _file_handler],
)
logger = logging.getLogger(__name__)


# ── Application setup ─────────────────────────────────────────────────────────

def _log_startup_diagnostics() -> None:
    """Emit a concise startup checklist to the application log."""
    report = collect_setup_diagnostics()
    logger.info(
        "Startup self-check summary: %s",
        report["summary"].upper(),
    )
    for item in report["checks"]:
        logger.info("Startup check %-18s %s", item["name"], item["status"].upper())

def main() -> None:
    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        logger.error(
            "TELEGRAM_BOT_TOKEN environment variable is not set. "
            "Set it as an environment variable (e.g. via .env file or "
            "system environment) and restart."
        )
        sys.exit(1)

    _log_startup_diagnostics()

    app = Application.builder().token(token).build()

    # /login conversation
    login_conv = ConversationHandler(
        entry_points=[
            CommandHandler("login", login_start),
            CallbackQueryHandler(login_start, pattern=r"^menu:login$"),
            MessageHandler(filters.Regex(button_regex("menu_login")), login_start),
        ],
        states={
            AWAIT_EMAIL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, login_email)
            ],
            AWAIT_PASSWORD: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, login_password)
            ],
        },
        fallbacks=[CommandHandler("cancel", login_cancel)],
        allow_reentry=True,
    )

    wit_ai_conv = ConversationHandler(
        entry_points=[
            CommandHandler("witai", wit_ai_start),
        ],
        states={
            AWAIT_WIT_AI_TOKEN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, wit_ai_token)
            ],
        },
        fallbacks=[CommandHandler("cancel", wit_ai_cancel)],
        allow_reentry=True,
    )

    offer_conv = ConversationHandler(
        entry_points=[
            CommandHandler("check_offer", check_offer),
            CallbackQueryHandler(check_offer, pattern=r"^menu:check_offer$"),
            MessageHandler(filters.Regex(button_regex("menu_check_offer")), check_offer),
        ],
        states={
            AWAIT_2FA_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_2fa_code)
            ],
            AWAIT_MANUAL_VERIFICATION: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    handle_manual_verification,
                )
            ],
            ConversationHandler.TIMEOUT: [
                MessageHandler(filters.ALL, offer_timeout)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_2fa)],
        allow_reentry=True,
        conversation_timeout=300,  # 5 minutes for TOTP or manual verification
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("doctor", doctor))
    app.add_handler(CallbackQueryHandler(start, pattern=r"^menu:home$"))
    app.add_handler(MessageHandler(filters.Regex(button_regex("menu_home")), start))
    app.add_handler(CommandHandler("lang_en", lang_en))
    app.add_handler(CallbackQueryHandler(lang_en, pattern=r"^menu:lang_en$"))
    app.add_handler(MessageHandler(filters.Regex(button_regex("menu_lang_en")), lang_en))
    app.add_handler(CommandHandler("lang_id", lang_id))
    app.add_handler(CommandHandler("langid", lang_id))
    app.add_handler(CallbackQueryHandler(lang_id, pattern=r"^menu:lang_id$"))
    app.add_handler(MessageHandler(filters.Regex(button_regex("menu_lang_id")), lang_id))
    app.add_handler(login_conv)
    app.add_handler(wit_ai_conv)
    app.add_handler(CommandHandler("logout", logout))
    app.add_handler(CallbackQueryHandler(logout, pattern=r"^menu:logout$"))
    app.add_handler(MessageHandler(filters.Regex(button_regex("menu_logout")), logout))
    app.add_handler(offer_conv)
    app.add_handler(CommandHandler("get_link", get_link))
    app.add_handler(CallbackQueryHandler(get_link, pattern=r"^menu:get_link$"))
    app.add_handler(MessageHandler(filters.Regex(button_regex("menu_get_link")), get_link))
    app.add_handler(CommandHandler("ip", ip_status))
    app.add_handler(CallbackQueryHandler(ip_status, pattern=r"^menu:ip$"))
    app.add_handler(MessageHandler(filters.Regex(button_regex("menu_ip")), ip_status))
    app.add_handler(CommandHandler("proxy", proxy_status))
    app.add_handler(CallbackQueryHandler(proxy_status, pattern=r"^menu:proxy$"))
    app.add_handler(MessageHandler(filters.Regex(button_regex("menu_proxy")), proxy_status))
    app.add_handler(CommandHandler("rotate_proxy", rotate_proxy))
    app.add_handler(CallbackQueryHandler(rotate_proxy, pattern=r"^menu:rotate_proxy$"))
    app.add_handler(MessageHandler(filters.Regex(button_regex("menu_rotate_proxy")), rotate_proxy))
    app.add_handler(CommandHandler("disable_proxy", disable_proxy))
    app.add_handler(CallbackQueryHandler(disable_proxy, pattern=r"^menu:disable_proxy$"))
    app.add_handler(MessageHandler(filters.Regex(button_regex("menu_disable_proxy")), disable_proxy))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CallbackQueryHandler(status, pattern=r"^menu:status$"))
    app.add_handler(MessageHandler(filters.Regex(button_regex("menu_status")), status))
    app.add_handler(CommandHandler("device", device_menu))
    app.add_handler(CallbackQueryHandler(device_menu, pattern=r"^menu:device$"))
    app.add_handler(MessageHandler(filters.Regex(button_regex("menu_device")), device_menu))
    app.add_handler(
        CallbackQueryHandler(device_select, pattern=rf"^{DEVICE_CALLBACK_PREFIX}")
    )

    # Periodic job: purge expired sessions every 5 minutes
    app.job_queue.run_repeating(
        session_cleanup_job, interval=300, first=300,
    )

    logger.info("Bot is running. Press Ctrl-C to stop.")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        bootstrap_retries=5,
    )


if __name__ == "__main__":
    main()
