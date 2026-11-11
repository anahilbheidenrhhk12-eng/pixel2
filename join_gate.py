"""Required-channel gate: nobody uses the bot until they have joined the channel.

Settings (ADMIN → Settings):
  Required Channel   @channelname (or a numeric id like -1001234567890). Empty = gate off.
  Channel Join Link  optional https://t.me/... link (needed for a private channel).

The bot must be an ADMINISTRATOR of the channel, otherwise Telegram does not let it
see members. If Telegram cannot answer (bot not admin, wrong name, network) the gate
lets the customer through and logs a warning — a mistake in the settings must never
lock every customer out.
"""
import logging
import time

from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as K
from telegram.ext import ApplicationHandlerStop

from admin_store import STORE, is_admin
import i18n

log = logging.getLogger(__name__)

CACHE_SECONDS = 600
_MEMBER_UNTIL = {}            # (channel, user) → time until which "is a member" is trusted
_WARNED = {}                  # channel → last time a configuration warning was logged


async def is_member(bot, channel, user_id):
    """True/False, or None when Telegram could not tell."""
    key = (channel, user_id)
    if _MEMBER_UNTIL.get(key, 0) > time.monotonic():
        return True
    try:
        member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
    except Exception as exc:
        if time.monotonic() - _WARNED.get(channel, 0) > 3600:
            _WARNED[channel] = time.monotonic()
            log.warning('Channel gate cannot check %s (is the bot an admin there?): %s', channel, type(exc).__name__)
        return None
    status = getattr(member, 'status', '')
    joined = status in ('creator', 'administrator', 'member') or (status == 'restricted' and bool(getattr(member, 'is_member', False)))
    if joined:
        _MEMBER_UNTIL[key] = time.monotonic() + CACHE_SECONDS
    return joined


def join_url(settings):
    link = str(settings.get('channel_link') or '').strip()
    if link:
        return link
    channel = str(settings.get('channel') or '').strip()
    return f'https://t.me/{channel[1:]}' if channel.startswith('@') else None


def prompt_text(lang='en'):
    return i18n.t('join_prompt_title', lang)


def prompt_markup(settings, lang='en'):
    rows = []
    url = join_url(settings)
    if url:
        rows.append([B(i18n.t('join_channel_btn', lang), url=url)])
    rows.append([B(i18n.t('join_continue_btn', lang), callback_data='j:ok')])
    return K(rows)


async def gate(update, context):
    """Runs before every other handler. Raises ApplicationHandlerStop to block a non-member."""
    user, chat = update.effective_user, update.effective_chat
    if not user or not chat or chat.type != 'private' or is_admin(user.id):
        return
    settings = STORE.settings()
    channel = str(settings.get('channel') or '').strip()
    if not channel:
        return
    if update.callback_query and update.callback_query.data == 'j:ok':
        return                                                    # its own handler re-checks
    if await is_member(context.bot, channel, user.id) is not False:
        return                                                    # member, or unknown → fail open
    lang = i18n.resolve(user.id)
    try:
        if update.callback_query:
            await update.callback_query.answer(i18n.t('join_please_first', lang), show_alert=False)
        await context.bot.send_message(chat_id=chat.id, text=prompt_text(lang), reply_markup=prompt_markup(settings, lang))
    except Exception:
        log.warning('Could not send the join prompt')
    raise ApplicationHandlerStop


async def continue_button(update, context, after):
    """“I joined — Continue”: re-check, then hand over to `after(update, context)`."""
    q = update.callback_query
    user = update.effective_user
    lang = i18n.resolve(user.id)
    settings = STORE.settings()
    channel = str(settings.get('channel') or '').strip()
    if channel and not is_admin(user.id) and await is_member(context.bot, channel, user.id) is False:
        await q.answer(i18n.t('join_not_yet', lang), show_alert=True)
        return
    await q.answer()
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    await after(update, context)
