"""Telegram + Railway broker for the local Windows Pixel emulator (outbound polling).
No local ADB ports are exposed. The first user pairs by reading digits on the PC.
"""
import base64
import io
import os
import re
import secrets
import threading
import time
from collections import deque

from aiohttp import web
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from admin_store import STORE, is_admin

lock = threading.RLock()
queue = deque()
pending = {}
pair_code = ""
pair_expires = 0
last_seen = 0
pc_state = "offline"
bot_ref = None
ACTIONS = {"start", "account", "one", "offers", "screenshot", "pixel"}


def set_bot(bot):
    global bot_ref
    bot_ref = bot


def authenticate(request):
    token = os.environ.get("PIXEL_EMULATOR_BRIDGE_TOKEN", "")
    supplied = request.headers.get("Authorization", "")
    if len(token) < 32 or not secrets.compare_digest(supplied, "Bearer " + token):
        raise web.HTTPUnauthorized(text="Invalid Windows server credentials")


def paired(uid):
    if is_admin(uid):
        return True
    with STORE.db() as db:
        db.execute("CREATE TABLE IF NOT EXISTS winpixel_owners (id INTEGER PRIMARY KEY, added REAL NOT NULL)")
        return db.execute("SELECT 1 FROM winpixel_owners WHERE id=?", (uid,)).fetchone() is not None


def pair(uid, value):
    global pair_code, pair_expires
    if not re.fullmatch(r"\d{8}", value):
        return False
    with lock:
        with STORE.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS winpixel_owners (id INTEGER PRIMARY KEY, added REAL NOT NULL)")
            if db.execute("SELECT 1 FROM winpixel_owners LIMIT 1").fetchone():
                return False
            if not pair_code or time.monotonic() > pair_expires or not secrets.compare_digest(pair_code, value):
                return False
            db.execute("INSERT INTO winpixel_owners VALUES (?,?)", (uid, time.time()))
        pair_code = ""
        pair_expires = 0
    return True


def status():
    with lock:
        online = bool(last_seen and time.monotonic() - last_seen < 25)
        state, n = pc_state[:180], len(queue)
    return ("🟢 Windows Pixel Server connected" if online else "🔴 Windows Pixel Server offline") + "\n💻 " + state + "\n📋 Jobs waiting: " + str(n)


def keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ START EMULATOR", callback_data="wp:start")],
        [InlineKeyboardButton("🔐 ADD GOOGLE ACCOUNT", callback_data="wp:account"),
         InlineKeyboardButton("📲 GOOGLE ONE APP", callback_data="wp:one")],
        [InlineKeyboardButton("🔎 CHECK OFFERS", callback_data="wp:offers"),
         InlineKeyboardButton("📸 SCREENSHOT", callback_data="wp:screenshot")],
        [InlineKeyboardButton("🌐 PIXEL CHROME", callback_data="wp:pixel"),
         InlineKeyboardButton("📊 STATUS", callback_data="wp:status")]
    ])


def enqueue(action, chat_id):
    with lock:
        if not last_seen or time.monotonic() - last_seen > 25:
            return False
        ident = secrets.token_urlsafe(12)
        queue.append((ident, action))
        pending[ident] = (chat_id, time.monotonic())
    return True


async def command(update, context):
    if update.effective_chat.type != "private":
        await update.effective_message.reply_text("Use the private bot chat.")
        return
    uid = update.effective_user.id
    args = context.args or []
    if args and args[0].lower() == "pair":
        if len(args) > 1 and pair(uid, args[1]):
            await update.effective_message.reply_text("✅ Windows Pixel Server paired.\n" + status(), reply_markup=keyboard())
        else:
            await update.effective_message.reply_text("❌ Pairing number invalid or expired. Read the digits from your Windows Pixel Server window.")
        return
    if not paired(uid):
        await update.effective_message.reply_text("Open the Windows Pixel Server, then send /winpixel pair 12345678 using its displayed 8-digit number. This is only needed once.")
        return
    action = args[0].lower() if args else "status"
    if action in ("status", "menu"):
        await update.effective_message.reply_text(status(), reply_markup=keyboard())
    elif action in ACTIONS:
        await update.effective_message.reply_text("📤 Sent to Windows emulator." if enqueue(action, update.effective_chat.id) else "🔴 Start the Windows Pixel Server first.")
    else:
        await update.effective_message.reply_text("Use /winpixel or /winpixel start.")


async def callback(update, context):
    q = update.callback_query
    await q.answer()
    if not paired(update.effective_user.id):
        await q.message.reply_text("Pair the Windows Pixel Server first with /winpixel.")
        return
    action = q.data.split(":", 1)[1]
    if action == "status":
        await q.message.reply_text(status(), reply_markup=keyboard())
    elif action in ACTIONS:
        await q.message.reply_text("📤 Command sent to Windows." if enqueue(action, q.message.chat_id) else "🔴 Windows Pixel Server offline.")


async def agent_poll(request):
    global last_seen, pc_state, pair_code, pair_expires
    authenticate(request)
    try:
        body = await request.json()
        state, digits = body.get("status", ""), body.get("pair_code", "")
        if not isinstance(state, str) or len(state) > 500 or not isinstance(digits, str):
            raise ValueError()
    except (ValueError, TypeError):
        raise web.HTTPBadRequest(text="Bad status")
    with lock:
        last_seen = time.monotonic()
        pc_state = state
        if re.fullmatch(r"\d{8}", digits):
            with STORE.db() as db:
                db.execute("CREATE TABLE IF NOT EXISTS winpixel_owners (id INTEGER PRIMARY KEY, added REAL NOT NULL)")
                exists = db.execute("SELECT 1 FROM winpixel_owners LIMIT 1").fetchone()
            if not exists:
                if digits != pair_code:
                    pair_expires = time.monotonic() + 900
                pair_code = digits
        while queue and pending.get(queue[0][0], (None, 0))[1] + 1800 < time.monotonic():
            ident, _ = queue.popleft()
            pending.pop(ident, None)
        ident, action = queue.popleft() if queue else ("", "")
    return web.json_response({"job_id": ident, "action": action}, headers={"Cache-Control": "no-store"})


async def agent_result(request):
    authenticate(request)
    try:
        body = await request.json()
        ident, message, screenshot = body.get("job_id", ""), body.get("message", ""), body.get("screenshot", "")
        if not isinstance(ident, str) or not isinstance(message, str) or not isinstance(screenshot, str):
            raise ValueError()
        if len(message) > 1500 or len(screenshot) > 6_000_000:
            raise ValueError()
    except (ValueError, TypeError):
        raise web.HTTPBadRequest(text="Bad report")
    with lock:
        item = pending.pop(ident, None)
    if not item:
        raise web.HTTPNotFound(text="Unknown or expired job")
    if bot_ref is not None:
        chat_id, _ = item
        if screenshot:
            try:
                png = base64.b64decode(screenshot, validate=True)
                if png.startswith(b"\x89PNG") and len(png) <= 4_000_000:
                    await bot_ref.send_photo(chat_id, io.BytesIO(png), caption=message[:1000])
                else:
                    await bot_ref.send_message(chat_id, message[:1000])
            except Exception:
                await bot_ref.send_message(chat_id, message[:1000])
        else:
            await bot_ref.send_message(chat_id, message[:1000])
    return web.json_response({"ok": True})


def register_routes(app):
    app.router.add_post("/winpixel/agent/poll", agent_poll)
    app.router.add_post("/winpixel/agent/result", agent_result)
