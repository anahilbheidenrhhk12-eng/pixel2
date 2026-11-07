"""Per-user device profile selection handlers."""

import asyncio
import html
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import config
from core.session_manager import SESSION_STORE, ensure_proxy_session_token
from handlers.ui import (
    main_menu_keyboard,
    prepare_action_message,
    quick_actions_inline_keyboard,
    tr,
)
from services.device_simulator import create_device_profile
from services.network_diagnostics import inspect_connection

logger = logging.getLogger(__name__)

DEVICE_CALLBACK_PREFIX = "device:"


def get_user_device_profile(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Return the user's stored device profile choice (falls back to default)."""
    stored = (context.user_data or {}).get("device_profile")
    if stored and stored in config.DEVICE_PRESETS:
        return stored
    return config.DEVICE_PROFILE_NAME


def set_user_device_profile(context: ContextTypes.DEFAULT_TYPE, profile_name: str) -> str:
    """Persist the user's device profile choice and return the active profile."""
    active = profile_name if profile_name in config.DEVICE_PRESETS else config.DEVICE_PROFILE_NAME
    if context.user_data is not None:
        context.user_data["device_profile"] = active
    return active


def sync_device_profile_to_session(
    context: ContextTypes.DEFAULT_TYPE,
    session: dict,
) -> str:
    """Mirror the user's chosen device profile into the session dict."""
    active = get_user_device_profile(context)
    session["device_profile"] = active
    return active


def device_select_keyboard(context: ContextTypes.DEFAULT_TYPE) -> InlineKeyboardMarkup:
    """Return an inline keyboard listing every available device preset."""
    active = get_user_device_profile(context)
    rows: list[list[InlineKeyboardButton]] = []
    for key, preset in config.DEVICE_PRESETS.items():
        marker = "✅ " if key == active else ""
        label = f"{marker}{preset['model']} (Android {preset['android_version']})"
        rows.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"{DEVICE_CALLBACK_PREFIX}{key}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                tr(context, "menu_home"),
                callback_data="menu:home",
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def _format_device_prompt(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Return the prompt body shown when /device is invoked."""
    active = get_user_device_profile(context)
    active_preset = config.DEVICE_PRESETS.get(active, {})
    active_label = active_preset.get("model", active)
    return tr(
        context,
        "device_prompt",
        active=html.escape(active_label),
    )


async def device_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the inline list of available device presets."""
    message = await prepare_action_message(update)
    await message.reply_text(
        _format_device_prompt(context),
        parse_mode="HTML",
        reply_markup=device_select_keyboard(context),
    )


async def _refresh_session_device(session: dict, profile_name: str) -> None:
    """Rebuild the active session's device profile using *profile_name*."""
    proxy_url = None if session.get("proxy_disabled") else session.get("proxy")
    network_identity = session.get("network_identity")

    if proxy_url and not network_identity:
        proxy_session_token = ensure_proxy_session_token(session)
        try:
            network_identity = await asyncio.to_thread(
                inspect_connection,
                proxy_url,
                proxy_session_token,
            )
        except Exception as exc:
            logger.warning(
                "Falling back to static emulation while refreshing device for new preset: %s",
                exc,
            )
            network_identity = None

    session["device"] = create_device_profile(
        network_identity=network_identity,
        profile_name=profile_name,
    )
    session["_device_route_tag"] = proxy_url or "__direct__"


async def device_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle a tap on one of the device buttons."""
    query = update.callback_query
    if query is None:
        return

    raw_data = query.data or ""
    requested = raw_data.removeprefix(DEVICE_CALLBACK_PREFIX).strip()

    if not requested or requested not in config.DEVICE_PRESETS:
        try:
            await query.answer(tr(context, "device_unknown"), show_alert=True)
        except Exception:
            pass
        return

    active = set_user_device_profile(context, requested)
    preset = config.DEVICE_PRESETS[active]

    chat_id = update.effective_chat.id
    refreshed_summary: str | None = None
    if chat_id in SESSION_STORE and SESSION_STORE[chat_id]:
        session = SESSION_STORE[chat_id]
        session["device_profile"] = active
        if session.get("device") is not None:
            await _refresh_session_device(session, active)
            refreshed_summary = session["device"].summary()

    try:
        await query.answer(tr(context, "device_set_toast", model=preset["model"]))
    except Exception:
        pass

    body_lines = [
        tr(context, "device_set_title"),
        tr(
            context,
            "device_set_body",
            model=html.escape(preset["model"]),
            android=html.escape(preset["android_version"]),
        ),
    ]
    if refreshed_summary:
        body_lines.append("")
        body_lines.append(refreshed_summary)
    body_lines.append("")
    body_lines.append(tr(context, "device_set_next"))

    message = await prepare_action_message(update)
    await message.reply_text(
        "\n".join(body_lines),
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(context),
    )
    await message.reply_text(
        tr(context, "quick_actions_title"),
        parse_mode="HTML",
        reply_markup=quick_actions_inline_keyboard(context),
    )


__all__ = [
    "DEVICE_CALLBACK_PREFIX",
    "device_menu",
    "device_select",
    "device_select_keyboard",
    "get_user_device_profile",
    "set_user_device_profile",
    "sync_device_profile_to_session",
]
