"""Link between DigiPro and the DIGITRUST store (V167.7).

The STORE owns the wallet. DigiPro only sells activation codes and asks the
store to charge / refund a customer's wallet:

  customer taps BUY → chooses how many codes → DigiPro asks the store to charge
  the wallet → the store answers → DigiPro issues the code(s), bound to that buyer.

ONE product, ONE fixed price: the admin sets it in ADMIN → Settings → Code Price.

Environment (all three are needed for BUY to work):
  STORE_API_URL       e.g. https://digitrust-bot-production.up.railway.app   (no trailing /)
  STORE_API_SECRET    the same value as DIGIPRO_SECRET on the store
  STORE_BOT_USERNAME  the store bot, without @ — used for the "top up" button

Money moves in integer cents only. Every purchase has a unique `ref`, so a
retried request can never charge twice; a charge that cannot be turned into a
code is refunded.
"""
import asyncio
import hashlib
import hmac
import logging
import os
import re
import secrets
import time
from decimal import Decimal, InvalidOperation

import aiohttp
from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as K

from admin_store import STORE
import i18n

log = logging.getLogger(__name__)

CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'   # same alphabet as STORE.generate
MAX_QTY = 10
PENDING_RETRY_AFTER = 90        # seconds before a pending purchase is re-checked
PENDING_GIVE_UP = 600           # after this a pending purchase is refunded and closed
_BUYING = set()                 # owners with a purchase in flight (double-tap guard)


# ── Configuration ─────────────────────────────────────────────────────────────

def cfg():
    return dict(
        url=os.getenv('STORE_API_URL', '').strip().rstrip('/'),
        secret=os.getenv('STORE_API_SECRET', '').strip(),
        bot=os.getenv('STORE_BOT_USERNAME', '').strip().lstrip('@'),
    )


def configured():
    c = cfg()
    local = c['url'].startswith(('http://127.0.0.1', 'http://localhost'))   # tests only; real traffic must be https
    return bool((c['url'].startswith('https://') or local) and c['secret'])


def topup_url():
    bot = cfg()['bot']
    return f'https://t.me/{bot}?start=wallet' if bot else None


def money(cents):
    return f'${int(cents) / 100:,.2f}'


# ── Database ──────────────────────────────────────────────────────────────────

def init():
    with STORE.db() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS purchases(
            ref TEXT PRIMARY KEY, owner INTEGER NOT NULL, plan_id INTEGER, title TEXT NOT NULL,
            qty INTEGER NOT NULL, cents INTEGER NOT NULL, status TEXT NOT NULL,
            codes TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '', created REAL NOT NULL, updated REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS purchases_owner ON purchases(owner, created);
        ''')


PRODUCT_TITLE = 'Activation code'


def parse_price(raw):
    """'12.5' / '$12.50' / '12,5' → cents. Raises ValueError for anything else."""
    text = str(raw).strip().replace('$', '').replace(',', '.')
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ValueError('Send the price as a number, e.g. 12.50')
    if value != value.quantize(Decimal('0.01')):
        raise ValueError('Use at most two decimals, e.g. 12.50')
    cents = int(value * 100)
    if not 1 <= cents <= 50000:
        raise ValueError('Price must be between $0.01 and $500.00')
    return cents


def price_cents():
    """The fixed price in cents, or None when it has not been set (not on sale)."""
    raw = str(STORE.settings().get('price') or '').strip()
    if not raw:
        return None
    try:
        return parse_price(raw)
    except ValueError:
        return None


def recent_purchases(owner, limit=5):
    init()
    with STORE.db() as db:
        return [dict(r) for r in db.execute(
            'SELECT title,qty,cents,status,created FROM purchases WHERE owner=? ORDER BY created DESC LIMIT ?', (owner, limit))]


# ── Signed client for the store ───────────────────────────────────────────────

class StoreUnreachable(Exception):
    """Network failure or a 5xx: the outcome of the request is UNKNOWN."""


def sign(secret, ts, action, user_id, cents, ref):
    msg = f'{ts}|{action}|{user_id}|{cents}|{ref}'
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()


async def _call(action, user_id, cents=0, ref='', title=None, *, session=None):
    c = cfg()
    if not (c['url'] and c['secret']):
        raise StoreUnreachable('not configured')
    ts = str(int(time.time()))
    body = {'user_id': int(user_id)}
    if action != 'balance':
        body.update(amount_cents=int(cents), ref=ref)
        if title:
            body['title'] = title
    headers = {'X-Digipro-Ts': ts, 'X-Digipro-Sign': sign(c['secret'], ts, action, int(user_id), int(cents) if action != 'balance' else 0, ref if action != 'balance' else '')}
    own = session is None
    session = session or aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12))
    try:
        async with session.post(f"{c['url']}/internal/digipro/{action}", json=body, headers=headers) as resp:
            if resp.status >= 500:
                raise StoreUnreachable(f'store error {resp.status}')
            try:
                data = await resp.json()
            except Exception:
                raise StoreUnreachable('unreadable answer')
            data['_status'] = resp.status
            return data
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        raise StoreUnreachable(type(exc).__name__)
    finally:
        if own:
            await session.close()


async def store_balance(user_id):
    """→ dict(ok, exists, balance_cents) or None when the store cannot be reached."""
    try:
        return await _call('balance', user_id)
    except StoreUnreachable:
        return None


# ── Purchase (charge → issue → or refund) ─────────────────────────────────────

def _new_code():
    return ''.join(secrets.choice(CODE_ALPHABET) for _ in range(12))


def _issue(ref):
    """Create the codes of a charged purchase, once. Returns the code list."""
    with STORE.db() as db:
        row = db.execute('SELECT * FROM purchases WHERE ref=?', (ref,)).fetchone()
        if not row:
            raise ValueError('unknown purchase')
        if row['status'] == 'issued':
            return [c for c in row['codes'].split(',') if c]
        if row['status'] not in ('pending', 'charged'):
            raise ValueError('purchase is ' + row['status'])
        codes = []
        while len(codes) < row['qty']:
            code = _new_code()
            if code in codes or db.execute('SELECT 1 FROM codes WHERE code=?', (code,)).fetchone():
                continue
            codes.append(code)
        now = time.time()
        db.executemany("INSERT INTO codes(code,owner,state,created) VALUES (?,?,'bound',?)", [(c, row['owner'], now) for c in codes])
        db.execute("UPDATE purchases SET status='issued',codes=?,updated=? WHERE ref=?", (','.join(codes), now, ref))
    return codes


def _set_status(ref, status, note=''):
    with STORE.db() as db:
        db.execute('UPDATE purchases SET status=?,note=?,updated=? WHERE ref=?', (status, note[:200], time.time(), ref))


async def _charge(owner, cents, ref, title):
    """Charge with up to 3 tries. The `ref` makes retries safe. None = still unknown."""
    for attempt in range(3):
        try:
            return await _call('charge', owner, cents, ref, title)
        except StoreUnreachable as exc:
            log.warning('charge %s attempt %d failed: %s', ref, attempt + 1, exc)
            await asyncio.sleep(1 + attempt)
    return None


async def _refund(owner, cents, ref):
    try:
        return await _call('refund', owner, cents, ref)
    except StoreUnreachable:
        return None


async def purchase(owner, qty):
    """Buy `qty` codes at the fixed price. Returns dict(status, ...):
         issued   codes, balance_cents
         insufficient  balance_cents, need_cents
         no_account | banned | disabled | unavailable | pending | error
    """
    init()
    if not configured():
        return dict(status='unavailable')
    unit = price_cents()
    if unit is None:
        return dict(status='disabled')
    if not 1 <= qty <= MAX_QTY:
        return dict(status='error', note='bad quantity')
    cents = unit * qty
    ref = 'dp_' + secrets.token_hex(12)
    title = PRODUCT_TITLE + (f' x{qty}' if qty > 1 else '')
    now = time.time()
    with STORE.db() as db:
        db.execute("INSERT INTO purchases(ref,owner,plan_id,title,qty,cents,status,created,updated) VALUES (?,?,?,?,?,?, 'pending',?,?)",
                   (ref, owner, None, title, qty, cents, now, now))
    result = await _charge(owner, cents, ref, title)
    if result is None:
        return dict(status='pending', ref=ref)           # reconcile() will settle it
    if not result.get('ok'):
        reason = result.get('reason') or 'error'
        _set_status(ref, 'failed', reason)
        if reason == 'insufficient':
            return dict(status='insufficient', balance_cents=int(result.get('balance_cents') or 0), need_cents=cents, qty=qty)
        return dict(status=reason if reason in ('no_account', 'banned') else 'error', note=reason)
    return await _finish_charged(owner, cents, ref, result.get('balance_cents'))


async def _finish_charged(owner, cents, ref, balance_cents):
    try:
        _set_status(ref, 'charged')
        codes = _issue(ref)
    except Exception as exc:                                    # never keep money without a code
        log.exception('could not issue codes for %s', ref)
        refunded = await _refund(owner, cents, ref)
        _set_status(ref, 'refunded' if refunded and refunded.get('ok') else 'refund_failed', type(exc).__name__)
        return dict(status='error', note='could not issue the code; your wallet was refunded' if refunded and refunded.get('ok') else 'refund pending')
    return dict(status='issued', codes=codes, balance_cents=balance_cents)


async def reconcile_once(bot=None):
    """Settle purchases left 'pending' by a network failure. Safe to run any time."""
    init()
    now = time.time()
    with STORE.db() as db:
        rows = [dict(r) for r in db.execute("SELECT * FROM purchases WHERE status='pending' AND created<?", (now - PENDING_RETRY_AFTER,))]
    for row in rows:
        ref, owner, cents = row['ref'], row['owner'], row['cents']
        try:
            if now - row['created'] > PENDING_GIVE_UP:
                # Too old to charge now. If the store did charge it, hand the money back.
                res = await _call('refund', owner, cents, ref)
                if res.get('ok'):
                    _set_status(ref, 'refunded', 'expired while pending')
                elif res.get('_status') == 404:
                    _set_status(ref, 'failed', 'never charged')
                continue
            res = await _call('charge', owner, cents, ref, row['title'])
        except StoreUnreachable:
            continue
        if res.get('ok'):
            out = await _finish_charged(owner, cents, ref, res.get('balance_cents'))
            if out['status'] == 'issued' and bot:
                try:
                    await bot.send_message(chat_id=owner, text=issued_text(out['codes'], out.get('balance_cents'), i18n.resolve(owner)))
                except Exception:
                    log.warning('could not deliver late codes to %s', owner)
        else:
            _set_status(ref, 'failed', res.get('reason') or 'error')


async def reconcile_loop(bot):
    while True:
        try:
            await reconcile_once(bot)
        except Exception:
            log.exception('reconcile failed')
        await asyncio.sleep(60)


# ── Customer screens ──────────────────────────────────────────────────────────

def issued_text(codes, balance_cents=None, lang='en'):
    text = i18n.t('buy_issued', lang, plural='s' if len(codes) > 1 else '', codes='\n'.join(codes))
    if balance_cents is not None:
        text += '\n' + i18n.t('buy_issued_balance', lang, money=money(balance_cents))
    return text


DEFAULT_TOPUP_GUIDE = (
    '1. Tap "Top up wallet" below. It opens our store bot.\n'
    '2. Choose a payment method and follow the steps there (your balance is added automatically).\n'
    '3. Come back here and tap the button to finish your purchase.'
)


def topup_guide():
    """The admin's own wording (Settings → Top-up Instructions) or the default."""
    text = str(STORE.settings().get('topup_instructions') or '').strip()
    return text or DEFAULT_TOPUP_GUIDE


def _topup_row(lang='en'):
    url = topup_url()
    return [B(i18n.t('wallet_topup_btn', lang), url=url)] if url else []


async def buy_menu(update, context):
    msg = update.effective_message
    uid = update.effective_user.id
    lang = i18n.resolve(uid)
    if not configured():
        await msg.reply_text(i18n.t('buy_unavailable', lang))
        return
    unit = price_cents()
    if unit is None:
        await msg.reply_text(i18n.t('buy_disabled', lang))
        return
    info = await store_balance(uid)
    bal = '' if info is None or not info.get('exists') else i18n.t('buy_wallet_line', lang, money=money(info.get('balance_cents', 0)))
    rows = [[B(i18n.t('buy_n_btn', lang, n=n, price=money(unit * n)), callback_data=f'b:y:{n}')] for n in (1, 2, 3, 5)]
    if _topup_row(lang):
        rows.append(_topup_row(lang))
    rows.append([B(i18n.t('wallet_howto_btn', lang), callback_data='b:h')])
    await msg.reply_text(i18n.t('buy_header', lang, price=money(unit), bal=bal), reply_markup=K(rows))


async def buy_callback(update, context):
    q = update.callback_query
    uid = update.effective_user.id
    lang = i18n.resolve(uid)
    if update.effective_chat.type != 'private':
        await q.answer(i18n.t('api_private_only', lang), show_alert=True)
        return
    parts = q.data.split(':')
    try:
        if parts[1] == 'l':
            await q.answer()
            return await buy_menu(update, context)
        if parts[1] == 'h':                                    # how to add balance
            await q.answer()
            rows = [r for r in (_topup_row(lang), [B(i18n.t('buy_back_btn', lang), callback_data='b:l')]) if r]
            await update.effective_message.reply_text(i18n.t('buy_howto_title', lang, guide=topup_guide()), reply_markup=K(rows))
            return
        if parts[1] == 'y':
            qty = int(parts[2])
            if uid in _BUYING:
                await q.answer(i18n.t('buy_still_processing', lang), show_alert=True)
                return
            await q.answer(i18n.t('buy_processing', lang))
            _BUYING.add(uid)
            try:
                res = await purchase(uid, qty)
            finally:
                _BUYING.discard(uid)
            await _show_result(update, res, lang)
    except (ValueError, IndexError):
        await q.answer(i18n.t('buy_restart', lang), show_alert=True)


async def _show_result(update, res, lang='en'):
    msg = update.effective_message
    st = res['status']
    if st == 'issued':
        await msg.reply_text(issued_text(res['codes'], res.get('balance_cents'), lang))
    elif st == 'insufficient':
        qty = int(res.get('qty') or 1)
        missing = max(0, res['need_cents'] - res['balance_cents'])
        rows = [_topup_row(lang), [B(i18n.t('buy_added_now_btn', lang, n=qty), callback_data=f'b:y:{qty}')]]
        await msg.reply_text(i18n.t('buy_insufficient', lang, have=money(res['balance_cents']), need=money(res['need_cents']), missing=money(missing), guide=topup_guide()), reply_markup=K([r for r in rows if r]))
    elif st == 'no_account':
        bot = cfg()['bot']
        rows = [[B(i18n.t('buy_open_store_btn', lang), url=f'https://t.me/{bot}?start=1')]] if bot else []
        await msg.reply_text(i18n.t('buy_no_account', lang), reply_markup=K(rows) if rows else None)
    elif st == 'banned':
        await msg.reply_text(i18n.t('buy_banned', lang))
    elif st == 'pending':
        await msg.reply_text(i18n.t('buy_pending', lang))
    elif st == 'disabled':
        await msg.reply_text(i18n.t('buy_disabled', lang))
    elif st == 'unavailable':
        await msg.reply_text(i18n.t('buy_unavailable', lang))
    else:
        await msg.reply_text(i18n.t('buy_error', lang, note=str(res.get('note') or '')))


async def wallet_lines(uid, lang='en'):
    """Extra lines for the WALLET screen (store wallet + purchase history)."""
    lines = []
    if configured():
        info = await store_balance(uid)
        if info is None:
            lines.append(i18n.t('store_wallet_unavailable', lang))
        elif info.get('exists'):
            lines.append(i18n.t('store_wallet_balance', lang, money=money(info.get('balance_cents', 0))))
        else:
            lines.append(i18n.t('store_wallet_open_once', lang))
    hist = recent_purchases(uid)
    if hist:
        lines.append('')
        lines.append(i18n.t('recent_purchases', lang))
        for h in hist:
            lines.append(f"• {h['title']} — {money(h['cents'])} — {h['status']}")
    return lines
