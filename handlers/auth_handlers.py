"""Authentication-related Telegram handlers."""

import asyncio
import html
import logging
import re
import time

from telegram import Update, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler

import config
from core.proxy_manager import PROXY_MANAGER, mask_proxy_url
from core.session_manager import (
    SESSION_STORE,
    clear_session,
    ensure_proxy_session_token,
    get_session,
)
from handlers.device_handlers import sync_device_profile_to_session
from services.device_simulator import create_device_profile
from services.network_diagnostics import inspect_connection
from services.runtime_settings import clear_wit_ai_token, store_wit_ai_token
from handlers.ui import (
    build_welcome_message,
    main_menu_keyboard,
    prepare_action_message,
    quick_actions_inline_keyboard,
    send_header_media_async,
    set_user_lang,
    tr,
)

logger = logging.getLogger(__name__)

AWAIT_EMAIL, AWAIT_PASSWORD, AWAIT_WIT_AI_TOKEN = range(3)


def _mask_secret(value: str, prefix: int = 6, suffix: int = 4) -> str:
    """Return a masked preview of a secret string."""
    normalized = str(value or "").strip()
    if not normalized:
        return "-"
    if len(normalized) <= prefix + suffix:
        return "*" * len(normalized)
    return f"{normalized[:prefix]}...{normalized[-suffix:]}"


def _read_wit_ai_argument(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Return the optional inline /witai argument text."""
    raw_args = getattr(context, "args", None) or []
    return " ".join(part for part in raw_args if part).strip()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send welcome message with command menu."""
    message = await prepare_action_message(update)
    await send_header_media_async(
        context,
        update.effective_chat.id,
        caption=html.escape(tr(context, "start_header_caption")),
    )
    await message.reply_text(
        build_welcome_message(context),
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(context),
    )
    await message.reply_text(
        tr(context, "quick_actions_title"),
        parse_mode="HTML",
        reply_markup=quick_actions_inline_keyboard(context),
    )


async def lang_en(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Switch chat language to English."""
    message = await prepare_action_message(update)
    set_user_lang(context, "en")
    await message.reply_text(
        tr(context, "lang_set"),
        reply_markup=main_menu_keyboard(context),
    )
    await message.reply_text(
        tr(context, "quick_actions_title"),
        parse_mode="HTML",
        reply_markup=quick_actions_inline_keyboard(context),
    )


async def lang_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Switch chat language to Indonesian."""
    message = await prepare_action_message(update)
    set_user_lang(context, "id")
    await message.reply_text(
        tr(context, "lang_set"),
        reply_markup=main_menu_keyboard(context),
    )
    await message.reply_text(
        tr(context, "quick_actions_title"),
        parse_mode="HTML",
        reply_markup=quick_actions_inline_keyboard(context),
    )


async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Begin the login conversation - ask for email."""
    message = await prepare_action_message(update)
    await message.reply_text(
        tr(context, "login_prompt_email"),
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )
    return AWAIT_EMAIL


async def wit_ai_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Begin the Wit.ai token capture conversation."""
    message = await prepare_action_message(update)
    inline_value = _read_wit_ai_argument(context)
    if inline_value:
        context.user_data["pending_wit_ai_token"] = inline_value
        return await wit_ai_token(update, context)

    await message.reply_text(
        tr(context, "wit_ai_prompt"),
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return AWAIT_WIT_AI_TOKEN


async def login_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store the email and ask for password."""
    email = update.message.text.strip()

    if not re.match(r"^[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}$", email, re.IGNORECASE):
        await update.message.reply_text(
            tr(context, "login_invalid_email"),
            parse_mode="HTML",
        )
        return AWAIT_EMAIL

    allowed = config.ALLOWED_EMAIL_DOMAINS
    if allowed:
        domain = email.rsplit("@", 1)[1].lower()
        if domain not in [d.lower() for d in allowed]:
            domains_str = ", ".join(f"@{d}" for d in allowed)
            await update.message.reply_text(
                f"⚠️ Only the following email domains are accepted: "
                f"{domains_str}\n\nPlease try again."
            )
            return AWAIT_EMAIL

    context.user_data["pending_email"] = email
    await update.message.reply_text(
        tr(context, "login_password_prompt", email=html.escape(email)),
        parse_mode="HTML",
    )
    return AWAIT_PASSWORD


async def login_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store credentials, generate a new device profile, and finish."""
    chat_id = update.effective_chat.id
    raw_input = update.message.text.strip()
    email = context.user_data.pop("pending_email", "")

    if "|" in raw_input:
        password, totp_secret = raw_input.split("|", 1)
        password = password.strip()
        totp_secret = totp_secret.strip()
    else:
        password = raw_input
        totp_secret = None

    session = get_session(chat_id)
    session["email"] = bytearray(email.encode("utf-8"))
    session["password"] = bytearray(password.encode("utf-8"))
    if totp_secret:
        session["totp_secret"] = totp_secret
    else:
        session.pop("totp_secret", None)
    proxy_note = tr(context, "proxy_summary_direct")
    selected_proxy = None
    proxy_session_token = ensure_proxy_session_token(
        session,
        seed=f"{chat_id}{int(time.time())}",
    )
    if session.get("proxy_disabled"):
        session.pop("proxy", None)
        proxy_note = tr(context, "proxy_summary_direct_locked")
    elif config.PROXY_ENABLED:
        selected_proxy = PROXY_MANAGER.get_proxy(preferred=session.get("proxy"))
        if selected_proxy:
            session["proxy"] = selected_proxy
            proxy_note = f"<code>{html.escape(mask_proxy_url(selected_proxy))}</code>"
        else:
            session.pop("proxy", None)
    else:
        session.pop("proxy", None)

    network_identity = None
    try:
        network_identity = await asyncio.to_thread(
            inspect_connection,
            None if session.get("proxy_disabled") else selected_proxy,
            proxy_session_token,
        )
    except Exception as exc:
        logger.warning("Falling back to static emulation settings for chat %s: %s", chat_id, exc)

    if network_identity:
        session["network_identity"] = network_identity
    else:
        session.pop("network_identity", None)

    profile_name = sync_device_profile_to_session(context, session)
    session["device"] = create_device_profile(
        network_identity=network_identity,
        profile_name=profile_name,
    )
    session["_device_route_tag"] = selected_proxy or "__direct__"
    session["offer_link"] = None
    session["created_at"] = time.time()

    try:
        await update.message.delete()
    except Exception:
        pass

    await context.bot.send_message(
        chat_id=chat_id,
        text=(
            f"<b>{html.escape(tr(context, 'login_saved_title'))}</b>\n\n"
            f"{html.escape(tr(context, 'login_saved_body'))}\n\n"
            f"{session['device'].summary()}\n\n"
            f"[·] <b>{html.escape(tr(context, 'section_proxy'))}</b>\n"
            f"🌐 {proxy_note}"
            + (
                f"\n\n{html.escape(tr(context, 'login_saved_totp'))}"
                if totp_secret
                else ""
            )
            + f"\n\n{tr(context, 'login_saved_next')}"
        ),
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(context),
    )
    return ConversationHandler.END


async def login_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the login conversation."""
    message = await prepare_action_message(update)
    context.user_data.pop("pending_email", None)
    await message.reply_text(
        tr(context, "login_cancelled"),
        reply_markup=main_menu_keyboard(context),
    )
    return ConversationHandler.END


async def wit_ai_token(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store or clear the Wit.ai token from a bot message."""
    message = await prepare_action_message(update)
    raw_input = context.user_data.pop("pending_wit_ai_token", None)
    if raw_input is None:
        raw_input = (update.effective_message.text or "").strip()
    normalized = str(raw_input or "").strip()
    lowered = normalized.lower()

    if not normalized:
        await message.reply_text(
            tr(context, "wit_ai_invalid"),
            reply_markup=ReplyKeyboardRemove(),
        )
        return AWAIT_WIT_AI_TOKEN

    if lowered in {"clear", "hapus", "remove", "delete", "off"}:
        env_path = clear_wit_ai_token()
        await message.reply_text(
            tr(context, "wit_ai_cleared", path=html.escape(str(env_path))),
            parse_mode="HTML",
            reply_markup=main_menu_keyboard(context),
        )
        return ConversationHandler.END

    if len(normalized) < 10:
        await message.reply_text(
            tr(context, "wit_ai_invalid"),
            reply_markup=ReplyKeyboardRemove(),
        )
        return AWAIT_WIT_AI_TOKEN

    env_path = store_wit_ai_token(normalized)
    await message.reply_text(
        tr(
            context,
            "wit_ai_saved",
            token=html.escape(_mask_secret(normalized)),
            path=html.escape(str(env_path)),
        ),
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(context),
    )
    return ConversationHandler.END


async def wit_ai_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the Wit.ai token conversation."""
    message = await prepare_action_message(update)
    context.user_data.pop("pending_wit_ai_token", None)
    await message.reply_text(
        tr(context, "wit_ai_cancelled"),
        reply_markup=main_menu_keyboard(context),
    )
    return ConversationHandler.END


async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear stored credentials and destroy the session."""
    message = await prepare_action_message(update)
    chat_id = update.effective_chat.id
    if chat_id in SESSION_STORE:
        clear_session(chat_id)
        await message.reply_text(
            tr(context, "logout_success"),
            reply_markup=main_menu_keyboard(context),
        )
    else:
        await message.reply_text(
            tr(context, "logout_none"),
            reply_markup=main_menu_keyboard(context),
        )
