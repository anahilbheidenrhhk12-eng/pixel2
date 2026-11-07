"""Session and status handlers."""

import asyncio
import html
import logging
import os

from telegram import Update
from telegram.ext import ContextTypes

import config
from core.proxy_manager import PROXY_MANAGER, mask_proxy_url
from core.session_manager import (
    SESSION_STORE,
    ensure_proxy_session_token,
    get_session,
    purge_expired_sessions,
)
from handlers.ui import (
    build_session_overview,
    main_menu_keyboard,
    prepare_action_message,
    quick_actions_inline_keyboard,
    tr,
)
from services.device_simulator import create_device_profile, resolve_emulation_settings
from services.network_diagnostics import format_connection_identity, inspect_connection
from services.setup_diagnostics import collect_setup_diagnostics

logger = logging.getLogger(__name__)


async def _refresh_device_for_route(session: dict, proxy_url: str | None) -> None:
    """Rebuild the device profile so its timezone/GPS match the active route."""
    network_identity = None
    proxy_session_token = ensure_proxy_session_token(session)
    try:
        network_identity = await asyncio.to_thread(
            inspect_connection,
            proxy_url,
            proxy_session_token,
        )
    except Exception as exc:
        logger.warning("Falling back to static emulation settings while refreshing device: %s", exc)

    if network_identity:
        session["network_identity"] = network_identity
    else:
        session.pop("network_identity", None)

    session["device"] = create_device_profile(
        network_identity=network_identity,
        profile_name=session.get("device_profile"),
    )
    session["_device_route_tag"] = proxy_url or "__direct__"


def _build_proxy_summary(context, proxy_url: str | None, direct_mode: bool = False) -> str:
    """Return a compact proxy summary for status views."""
    stats = PROXY_MANAGER.stats()
    if direct_mode:
        mode = tr(context, "proxy_summary_direct_locked")
    elif proxy_url:
        mode = mask_proxy_url(proxy_url)
    else:
        mode = tr(context, "proxy_summary_direct")
    return (
        f"🌐 {html.escape(mode)}\n"
        f"{html.escape(tr(context, 'proxy_summary_pool', available=stats['available'], total=stats['total']))}"
    )


def _format_env_ready_emulation(context, network_identity: dict[str, str] | None) -> str:
    """Return exact emulation values that the runtime would use for this route."""
    emulation = resolve_emulation_settings(network_identity)
    source_key = (
        "ip_emulation_source_route"
        if network_identity
        else "ip_emulation_source_fallback"
    )
    return "\n".join(
        [
            tr(context, "ip_emulation_title"),
            tr(context, source_key),
            tr(context, "ip_emulation_copy_note"),
            f"EMULATION_TIMEZONE_ID={emulation['timezone_id']}",
            f"EMULATION_GEO_LATITUDE={emulation['geolocation_latitude']}",
            f"EMULATION_GEO_LONGITUDE={emulation['geolocation_longitude']}",
            f"EMULATION_GEO_ACCURACY={emulation['geolocation_accuracy']}",
        ]
    )


def _format_doctor_report(context, report: dict[str, object]) -> str:
    """Return a readable first-run diagnostics report."""
    summary_key = f"doctor_summary_{report['summary']}"
    lines = [
        tr(context, "doctor_title"),
        tr(context, summary_key),
        "",
    ]

    token_status = next(item["status"] for item in report["checks"] if item["name"] == "telegram_token")
    lines.append(tr(context, "doctor_token_ok" if token_status == "ok" else "doctor_token_fail"))

    chrome_status = next(item["status"] for item in report["checks"] if item["name"] == "chrome_binary")
    if chrome_status == "ok":
        lines.append(
            tr(
                context,
                "doctor_chrome_ok",
                version=report["chrome_version"],
                major=report["chrome_major_version"],
            )
        )
    else:
        lines.append(tr(context, "doctor_chrome_fail"))

    env_file = report["env_file"]
    lines.append(
        tr(
            context,
            "doctor_env_ok" if env_file["exists"] else "doctor_env_warn",
            path=html.escape(str(env_file["path"])),
        )
    )

    header_media = report["header_media"]
    header_mode = str(header_media["mode"])
    if header_mode == "local":
        lines.append(tr(context, "doctor_header_local_ok", value=html.escape(str(header_media["value"]))))
    elif header_mode == "remote":
        lines.append(tr(context, "doctor_header_remote_ok", value=html.escape(str(header_media["value"]))))
    elif header_mode == "disabled":
        lines.append(tr(context, "doctor_header_disabled"))
    else:
        lines.append(tr(context, "doctor_header_warn", value=html.escape(str(header_media["value"]))))

    proxy_pool = report["proxy_pool"]
    if not proxy_pool["enabled"]:
        lines.append(tr(context, "doctor_proxy_disabled"))
    elif not proxy_pool["exists"]:
        lines.append(tr(context, "doctor_proxy_missing", path=html.escape(str(proxy_pool["path"]))))
    elif not bool(proxy_pool.get("readable", False)):
        lines.append(tr(context, "doctor_proxy_unreadable", path=html.escape(str(proxy_pool["path"]))))
    elif int(proxy_pool["valid_entries"]) <= 0:
        lines.append(tr(context, "doctor_proxy_empty", path=html.escape(str(proxy_pool["path"]))))
    elif int(proxy_pool["invalid_entries"]) > 0:
        lines.append(
            tr(
                context,
                "doctor_proxy_warn_invalid",
                valid=proxy_pool["valid_entries"],
                invalid=proxy_pool["invalid_entries"],
            )
        )
    else:
        lines.append(
            tr(
                context,
                "doctor_proxy_ok",
                count=proxy_pool["valid_entries"],
                path=html.escape(str(proxy_pool["path"])),
            )
        )

    chromedriver_path = str(report["chromedriver_path"] or "")
    if not chromedriver_path:
        lines.append(tr(context, "doctor_driver_auto"))
    elif os.path.exists(chromedriver_path):
        lines.append(tr(context, "doctor_driver_ok", path=html.escape(chromedriver_path)))
    else:
        lines.append(tr(context, "doctor_driver_warn", path=html.escape(chromedriver_path)))

    lines.extend(
        [
            "",
            tr(context, "doctor_next_steps"),
        ]
    )
    return "\n".join(lines)


async def get_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return the last captured offer link for this session."""
    message = await prepare_action_message(update)
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    link = session.get("offer_link")

    if link:
        await message.reply_text(
            f"🔗 <b>Latest captured offer link</b>\n\n{link}",
            parse_mode="HTML",
            reply_markup=quick_actions_inline_keyboard(context),
        )
    else:
        await message.reply_text(
            "ℹ️ No offer link has been captured yet. "
            "Use /check\\_offer to search for the Gemini Pro offer.",
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(context),
        )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show current session and device profile summary."""
    message = await prepare_action_message(update)
    chat_id = update.effective_chat.id

    if chat_id not in SESSION_STORE or not SESSION_STORE[chat_id]:
        await message.reply_text(
            tr(context, "status_no_session"),
            reply_markup=main_menu_keyboard(context),
        )
        return

    session = SESSION_STORE[chat_id]
    email_raw = session.get("email", "-")
    if isinstance(email_raw, bytearray):
        email = bytes(email_raw).decode("utf-8")
    else:
        email = str(email_raw) if email_raw else "-"

    has_creds = bool(session.get("email") and session.get("password"))
    offer_link = session.get("offer_link")
    device = session.get("device")
    proxy_url = session.get("proxy")
    direct_mode = bool(session.get("proxy_disabled"))

    await message.reply_text(
        build_session_overview(
            context,
            email=email,
            has_creds=has_creds,
            has_offer_link=bool(offer_link),
            device_summary=device.summary() if device else None,
            proxy_summary=_build_proxy_summary(context, proxy_url, direct_mode=direct_mode),
        ),
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(context),
    )


async def proxy_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the current session proxy and global pool counters."""
    message = await prepare_action_message(update)
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    if not session.get("proxy_disabled") and not session.get("proxy") and config.PROXY_ENABLED:
        selected_proxy = PROXY_MANAGER.get_proxy()
        if selected_proxy:
            session["proxy"] = selected_proxy
    await message.reply_text(
        _build_proxy_summary(
            context,
            session.get("proxy"),
            direct_mode=bool(session.get("proxy_disabled")),
        ),
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(context),
    )


async def rotate_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Rotate the current session proxy to another healthy entry."""
    message = await prepare_action_message(update)
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    session["proxy_disabled"] = False
    current_proxy = session.get("proxy")
    next_proxy = PROXY_MANAGER.get_proxy(excluded={current_proxy} if current_proxy else None)

    if next_proxy:
        session["proxy"] = next_proxy
        await _refresh_device_for_route(session, next_proxy)
        await message.reply_text(
            tr(context, "proxy_rotated", proxy=html.escape(mask_proxy_url(next_proxy))),
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(context),
        )
        return

    session.pop("proxy", None)
    stats = PROXY_MANAGER.stats()
    if stats["total"] == 0:
        text = tr(context, "proxy_no_pool")
    else:
        text = tr(context, "proxy_no_healthy")

    await message.reply_text(
        text,
        reply_markup=main_menu_keyboard(context),
    )


async def disable_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Force the current session to use direct/local IP instead of the proxy pool."""
    message = await prepare_action_message(update)
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    already_disabled = bool(session.get("proxy_disabled"))
    session["proxy_disabled"] = True
    session.pop("proxy", None)
    await _refresh_device_for_route(session, None)

    await message.reply_text(
        tr(context, "proxy_disabled_already" if already_disabled else "proxy_disabled_set"),
        reply_markup=main_menu_keyboard(context),
    )


async def ip_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Probe the current public IP through the active session proxy."""
    message = await prepare_action_message(update)
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    proxy_session_token = ensure_proxy_session_token(session, seed=str(chat_id))
    proxy_url = session.get("proxy")
    if not session.get("proxy_disabled") and not proxy_url and config.PROXY_ENABLED:
        proxy_url = PROXY_MANAGER.get_proxy()
        if proxy_url:
            session["proxy"] = proxy_url

    await message.reply_text(tr(context, "ip_checking"))

    try:
        result = await asyncio.to_thread(
            inspect_connection,
            proxy_url,
            proxy_session_token,
        )
    except Exception as exc:
        await message.reply_text(
            tr(context, "ip_check_failed", reason=exc),
            reply_markup=main_menu_keyboard(context),
        )
        return

    await message.reply_text(
        (
            f"{format_connection_identity(result, title=tr(context, 'network_title'))}\n\n"
            f"{_format_env_ready_emulation(context, result)}"
        ),
        reply_markup=main_menu_keyboard(context),
    )


async def doctor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show a first-run setup checklist for new users."""
    message = await prepare_action_message(update)
    await message.reply_text(
        tr(context, "doctor_running"),
        reply_markup=main_menu_keyboard(context),
    )
    report = collect_setup_diagnostics()
    await message.reply_text(
        _format_doctor_report(context, report),
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(context),
    )


async def session_cleanup_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Periodic callback to purge expired sessions."""
    purge_expired_sessions()
