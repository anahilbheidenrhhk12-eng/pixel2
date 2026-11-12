"""Private, temporary interactive Chrome window for a Telegram user.

The card is entered into the *actual* Google Payments browser dialog using
noVNC in an HTTPS page. The Telegram bot and this service never ask for or
store PAN, expiration date, or CVC. Keyboard/mouse bytes pass to a loopback
VNC socket and are not decoded or logged here.
"""
from __future__ import annotations

import asyncio
import contextlib
import html
import logging
import os
import secrets
import shutil
import socket
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from aiohttp import WSMsgType, web
from admin_store import STORE

log = logging.getLogger(__name__)
NOVNC_PATH = Path('/usr/share/novnc')
DISPLAY_LOCK = threading.RLock()
DISPLAY_SLOTS = set()
MAX_SESSION_AGE = float('inf')  # Legacy compatibility; browser sessions have no TTL.
CHECKOUT_PUBLIC_URL = (
    os.environ.get('PUBLIC_BASE_URL', '').strip()
    or ('https://' + os.environ['RAILWAY_PUBLIC_DOMAIN'].strip()
        if os.environ.get('RAILWAY_PUBLIC_DOMAIN') else '')
).rstrip('/')


def enabled() -> bool:
    return CHECKOUT_PUBLIC_URL.startswith('https://')


def _free_tcp_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def _display_slot() -> int:
    for display in range(140, 200):
        if display not in DISPLAY_SLOTS and not Path(f'/tmp/.X11-unix/X{display}').exists():
            DISPLAY_SLOTS.add(display)
            return display
    raise RuntimeError('No available virtual display slots')


def synchronized(fn):
    def wrapped(self, *args, **kwargs):
        with self.resource_lock:
            return fn(self, *args, **kwargs)
    return wrapped


@dataclass
class CheckoutSession:
    chat_id: int
    resource_lock: object = field(default_factory=threading.RLock, repr=False)
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    created: float = field(default_factory=time.monotonic)
    expires_at: float = field(default_factory=lambda: time.monotonic() + MAX_SESSION_AGE)
    display: str = ''
    vnc_port: int = 0
    xvfb: Optional[subprocess.Popen] = field(default=None, repr=False)
    vnc: Optional[subprocess.Popen] = field(default=None, repr=False)
    driver: object = field(default=None, repr=False)
    ready: bool = False
    closed: bool = False
    in_use: bool = False
    interactive_enabled: bool = False
    phase: str = 'Starting Chrome…'
    auth_cookie: str = ''
    viewer_connected: bool = False
    final_started: float = 0
    final_opened: bool = False
    second_opened: bool = False
    completion_seen: float = 0
    mode: str = 'balanced'

    @property
    def url(self) -> str:
        return f'{CHECKOUT_PUBLIC_URL}/miniapp'

    @synchronized
    def start_display(self):
        if not shutil.which('Xvfb') or not shutil.which('x11vnc'):
            raise RuntimeError('Xvfb/x11vnc are not installed; build with the included Dockerfile')
        with DISPLAY_LOCK:
            if self.closed:
                raise RuntimeError('Browser was closed')
            slot = _display_slot()
            self.display = ':' + str(slot)
        self.vnc_port = _free_tcp_port()
        self.xvfb = subprocess.Popen(
            ['Xvfb', self.display, '-screen', '0', '1280x1600x24', '-nolisten', 'tcp', '-ac'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if self.xvfb.poll() is not None:
                raise RuntimeError('Xvfb exited before the display was ready')
            if Path(f'/tmp/.X11-unix/X{slot}').exists():
                break
            time.sleep(.1)
        else:
            raise RuntimeError('Virtual display did not become ready')
        self.vnc = subprocess.Popen(
            ['x11vnc', '-display', self.display, '-rfbport', str(self.vnc_port),
             '-localhost', '-nopw', '-forever', '-shared', '-noxdamage', '-quiet',
             '-clip', '1280x852+0+0'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if self.vnc.poll() is not None:
                raise RuntimeError('VNC server failed to start')
            try:
                with socket.create_connection(('127.0.0.1', self.vnc_port), timeout=.2):
                    if self.closed:
                        self.stop()
                        raise RuntimeError('Browser was closed')
                    return
            except (OSError, TimeoutError):
                time.sleep(.15)
        raise RuntimeError('VNC server did not become ready')

    @synchronized
    def fit_viewport(self, width, height):
        """Fit the actual Chrome window, then stream only its visible page area."""
        if self.closed or not self.driver or not self.interactive_enabled:
            raise ValueError('Browser is not ready')
        crop = max(0, min(120, int(os.getenv('BROWSER_BOTTOM_CROP', '48'))))
        ratio = width / height
        toolbar = self.driver.execute_script('return Math.max(0, window.outerHeight-window.innerHeight)')
        toolbar = max(0, min(160, int(toolbar)))
        visible_w = max(500, min(1280, width))
        visible_h = max(200, round(visible_w/ratio))
        if visible_h > 1600-toolbar-crop:
            visible_h = 1600-toolbar-crop
            visible_w = max(500, round(visible_h*ratio))
        self.driver.set_window_rect(x=0, y=0, width=visible_w, height=visible_h+toolbar+crop)
        actual = self.driver.execute_script('return [window.outerWidth,window.outerHeight,window.innerHeight]')
        w, outer_h, inner_h = [int(v) for v in actual]
        top = max(0, outer_h-inner_h)
        h = max(100, inner_h-crop)
        result = subprocess.run(['x11vnc','-display',self.display,'-sync','-remote',
                                 f'clip:{min(w,1280)}x{min(h,1600-top)}+0+{top}'],
                                capture_output=True, timeout=5, check=True)
        return {'width':w,'height':h,'crop':crop}

    @synchronized
    def attach_driver(self, driver):
        if self.closed:
            raise RuntimeError('Browser was closed')
        self.driver = driver
        self.ready = True

    @synchronized
    def stop(self):
        self.closed = True
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                log.debug('Error closing Chrome', exc_info=True)
            self.driver = None
        for proc in (self.vnc, self.xvfb):
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
        with DISPLAY_LOCK:
            if self.display:
                DISPLAY_SLOTS.discard(int(self.display[1:]))
        self.ready = False


class CheckoutRegistry:
    def __init__(self):
        self.by_chat: dict[int, CheckoutSession] = {}
        self.by_token: dict[str, CheckoutSession] = {}
        self.lock = threading.RLock()

    def create(self, chat_id: int) -> CheckoutSession:
        with self.lock:
            old = self.by_chat.get(chat_id)
            if old and not old.closed:
                raise RuntimeError('An existing browser session is active; use /close_checkout first')
            if len(self.by_chat) >= STORE.settings()['max_sessions']:
                raise RuntimeError('All browser slots are occupied; try again after another session closes')
            if STORE.settings()['maintenance']:
                raise RuntimeError(STORE.settings()['maintenance_message'])
            session = CheckoutSession(chat_id=chat_id, mode=STORE.settings()['mode'])
            self.by_chat[chat_id] = session
            self.by_token[session.token] = session
            return session

    def find(self, token: str) -> Optional[CheckoutSession]:
        with self.lock:
            session = self.by_token.get(token)
            if not session or session.closed:
                return None
            return session

    def for_chat(self, chat_id: int) -> Optional[CheckoutSession]:
        with self.lock:
            session = self.by_chat.get(chat_id)
            if not session or session.closed:
                return None
            return session

    def discard(self, session: CheckoutSession, status: str = None, reason: str = ''):
        removed_owner = False
        with self.lock:
            if self.by_chat.get(session.chat_id) is session:
                self.by_chat.pop(session.chat_id, None)
                removed_owner = True
            if self.by_token.get(session.token) is session:
                self.by_token.pop(session.token, None)
        if session.viewer_connected and session.interactive_enabled:
            STORE.consume(session.token)
        if status is None:
            status = 'closed' if session.viewer_connected and session.interactive_enabled else 'incomplete'
        STORE.finish(session.token, status, reason)
        import config
        if removed_owner:
            config.SESSION_STORE.pop(session.chat_id, None)
        session.stop()

    async def monitor_sessions(self):
        while True:
            await asyncio.sleep(2)
            with self.lock:
                sessions = list(self.by_chat.values())
            for session in sessions:
                if session.closed or not session.interactive_enabled:
                    continue
                if getattr(session, "google_one_mobile_probe", False):
                    continue  # Probe is not an activation checkout window.
                try:
                    await asyncio.to_thread(self._final_stage, session)
                except Exception:
                    log.warning('Final browser check failed; session preserved for reconnect')

    def _final_stage(self, session):
        with session.resource_lock:
            return self._final_stage_locked(session)

    def _final_stage_locked(self, session):
        from urllib.parse import urlsplit
        settings = STORE.settings()
        if session.viewer_connected and not STORE.consume(session.token):
            self.discard(session)
            return
        now = time.monotonic()
        if not session.final_started:
            session.final_started = now
        if not session.final_opened:
            if settings['final_url']:
                session.driver.get(settings['final_url'])
            session.final_opened = True
        if not session.second_opened and settings['second_url'] and now-session.final_started >= settings['second_delay']:
            session.driver.get(settings['second_url'])
            session.second_opened = True
        if settings['close_on_activation'] and settings['completion_url']:
            target = urlsplit(settings['completion_url'])
            current = urlsplit(session.driver.current_url)
            matches = (current.scheme, current.netloc, current.path.rstrip('/')) == (target.scheme, target.netloc, target.path.rstrip('/'))
            matches = matches and (not target.query or current.query == target.query)
            if matches:
                session.completion_seen = session.completion_seen or now
                if now-session.completion_seen >= settings['close_delay']:
                    STORE.finish(session.token, 'activation_detected')
                    self.discard(session)
            else:
                session.completion_seen = 0



REGISTRY = CheckoutRegistry()


def _secure_headers(response):
    response.headers.update({
        'Cache-Control': 'no-store, max-age=0',
        'Pragma': 'no-cache',
        'Referrer-Policy': 'no-referrer',
        'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'DENY',
    })
    return response


async def checkout_view(request):
    session = REGISTRY.find(request.match_info['token'])
    if not session:
        raise web.HTTPNotFound(text='This private browser link is invalid or expired.')
    from telegram_miniapp import authorized
    if not session.interactive_enabled:
        raise web.HTTPForbidden(text='The final browser stage is not ready')
    if not authorized(request, session):
        raise web.HTTPForbidden(text='Open the Mini App in your Telegram bot chat')
    if not session.ready:
        raise web.HTTPNotFound(text='The browser has not started yet')
    token = html.escape(session.token, quote=True)
    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>Private Google Checkout Browser</title>
<style>
body{{margin:0;background:#0f172a;color:#f8fafc;font-family:system-ui,sans-serif}}
header{{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 16px}}
header b{{font-size:15px}}.sub{{font-size:12px;color:#94a3b8}}button{{background:#a83232;color:white;border:0;border-radius:8px;padding:10px;cursor:pointer}}
#screen{{height:calc(100dvh - 78px);overflow:hidden;background:#202020;display:flex;align-items:center;justify-content:center}}
#screen canvas{{touch-action:none}}#notice{{position:fixed;bottom:8px;left:10px;color:#fff;background:#333c;padding:8px;border-radius:6px;font-size:12px}}
</style></head><body><header><div><b>🔐 Private Google payment window</b><div class="sub">Enter card details only on Google's page; nothing is sent in Telegram.</div></div><button id="finish">End session</button></header>
<div id="screen"></div><div id="notice">Connecting to your browser…</div>
<script type="module">
import RFB from '/novnc/core/rfb.js';
const token={token!r};
const endpoint=(location.protocol==='https:'?'wss://':'ws://')+location.host+'/checkout-ws/'+token;
const notice=document.querySelector('#notice');
const rfb=new RFB(document.querySelector('#screen'),endpoint);
rfb.scaleViewport=true; rfb.resizeSession=false; rfb.viewOnly=false; rfb.clipViewport=true;
rfb.addEventListener('connect',()=>{{notice.textContent='Connected — click a field to type'; setTimeout(()=>notice.remove(),2500);}});
rfb.addEventListener('disconnect',()=>{{notice.textContent='Browser disconnected or session ended';}});
document.querySelector('#finish').onclick=async()=>{{
  if(!confirm('Close this private browser session?'))return;
  await fetch('/checkout-end/'+token,{{method:'POST',cache:'no-store'}});
  location.replace('about:blank');
}};
</script></body></html>'''
    response = web.Response(text=page, content_type='text/html')
    _secure_headers(response)
    response.headers['Content-Security-Policy'] = (
        "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; "
        "connect-src 'self' wss: ws:; img-src 'self' data:; font-src 'self'; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    )
    return response


async def checkout_ws(request):
    session = REGISTRY.find(request.match_info['token'])
    if not session or not session.ready:
        raise web.HTTPNotFound(text='Session expired')
    from telegram_miniapp import authorized
    if not session.interactive_enabled:
        raise web.HTTPForbidden(text='The final browser stage is not ready')
    if not authorized(request, session):
        raise web.HTTPForbidden(text='Open the Mini App in Telegram first')
    # Only one active viewer for each account's payment page.
    with REGISTRY.lock:
        if session.in_use:
            raise web.HTTPConflict(text='Browser already open on another device')
        session.in_use = True
    ws = web.WebSocketResponse(protocols=('binary',), heartbeat=30, max_msg_size=8 * 1024 * 1024)
    try:
        await ws.prepare(request)
        reader, writer = await asyncio.open_connection('127.0.0.1', session.vnc_port)
        async def browser_to_user():
            while not reader.at_eof():
                chunk = await reader.read(65536)
                if not chunk:
                    break
                await ws.send_bytes(chunk)

        async def user_to_browser():
            async for msg in ws:
                if msg.type == WSMsgType.BINARY:
                    # The noVNC RFB handshake and framebuffer requests use
                    # client-to-server binary frames even in view-only mode.
                    # Blocking them prevents the viewer from connecting at all.
                    # The Mini App's noVNC client disables user inputs until
                    # the checkout is ready; this authenticated relay stays
                    # protocol-transparent so the live picture can render.
                    writer.write(msg.data)
                    await writer.drain()
                elif msg.type == WSMsgType.ERROR:
                    break

        tasks = [asyncio.create_task(browser_to_user()), asyncio.create_task(user_to_browser())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
    except Exception:
        log.warning('Remote viewer disconnected; card content was not logged')
    finally:
        with REGISTRY.lock:
            session.in_use = False
        await ws.close()
    return ws


async def checkout_end(request):
    session = REGISTRY.find(request.match_info['token'])
    if not session:
        raise web.HTTPNotFound()
    from telegram_miniapp import authorized
    if not authorized(request, session):
        raise web.HTTPForbidden(text='Not authorized')
    await asyncio.to_thread(REGISTRY.discard, session)
    return _secure_headers(web.json_response({'closed': True}))


async def home(request):
    return _secure_headers(web.Response(text='Remote Google checkout viewer is running.', content_type='text/plain'))


async def start_http():
    app = web.Application(client_max_size=20 * 1024 * 1024)
    # Administration is native Telegram only. Keep authenticated tutorial playback.
    from admin_panel import tutorial
    app.router.add_get('/tutorial', tutorial)
    from customer_portal import register
    register(app)
    from telegram_miniapp import miniapp_page, miniapp_auth, miniapp_status, miniapp_end, miniapp_connected, miniapp_viewport
    from winpixel_bridge import register_routes as register_windows_pixel_routes
    register_windows_pixel_routes(app)
    app.router.add_get('/', home)
    app.router.add_get('/miniapp', miniapp_page)
    async def keyboard_script(request):
        return _secure_headers(web.FileResponse(Path(__file__).with_name('mobile_keyboard.js')))
    app.router.add_get('/mobile-keyboard.js', keyboard_script)
    app.router.add_post('/miniapp-auth', miniapp_auth)
    app.router.add_get('/miniapp-status/{token}', miniapp_status)
    app.router.add_post('/miniapp-connected/{token}', miniapp_connected)
    app.router.add_post('/miniapp-viewport/{token}', miniapp_viewport)
    app.router.add_get('/miniapp-ws/{token}', checkout_ws)
    app.router.add_post('/miniapp-end/{token}', miniapp_end)
    app.router.add_get('/checkout/{token}', checkout_view)
    app.router.add_get('/checkout-ws/{token}', checkout_ws)
    app.router.add_post('/checkout-end/{token}', checkout_end)
    if NOVNC_PATH.is_dir():
        app.router.add_static('/novnc/', path=str(NOVNC_PATH), show_index=False)
    else:
        log.warning('noVNC static assets are missing; install Debian novnc package')
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get('PORT', '8080')))
    await site.start()
    log.info('Private checkout viewer listening on port %s', os.environ.get('PORT', '8080'))
    return runner
