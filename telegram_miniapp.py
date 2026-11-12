"""Telegram Mini App for the existing temporary Chrome/noVNC session.

Telegram initData is validated server-side. No card fields, credential text,
keystrokes, or screenshots are stored by this module.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from urllib.parse import parse_qsl

from aiohttp import web
from remote_checkout import REGISTRY, _secure_headers

logger = logging.getLogger(__name__)
COOKIE_NAME = 'digipro_mini_auth'
INIT_MAX_AGE = 3600


def verify_init_data(raw: str, bot_token: str, now: float | None = None) -> int | None:
    """Validate Telegram's HMAC-authenticated WebApp initData; return user ID."""
    if not raw or not bot_token or len(raw) > 16000:
        return None
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
        data = dict(pairs)
        if len(data) != len(pairs):
            return None
        supplied_hash = data.pop('hash', '')
        if len(supplied_hash) != 64:
            return None
        ts = int(data['auth_date'])
        instant = time.time() if now is None else now
        if ts > instant + 60 or instant - ts > INIT_MAX_AGE:
            return None
        check_string = '\n'.join(f'{k}={v}' for k, v in sorted(data.items()))
        secret = hmac.new(b'WebAppData', bot_token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(supplied_hash.lower(), expected):
            return None
        user = json.loads(data['user'])
        user_id = user.get('id')
        return user_id if type(user_id) is int and user_id > 0 else None
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def authorized(request, session) -> bool:
    token = request.cookies.get(COOKIE_NAME, '')
    return bool(token and session.auth_cookie and secrets.compare_digest(token, session.auth_cookie))


def _require_session(request):
    session = REGISTRY.find(request.match_info['token'])
    if session is None:
        raise web.HTTPNotFound(text='Browser session expired')
    if not session.interactive_enabled:
        raise web.HTTPForbidden(text='Final browser stage is not ready')
    if not authorized(request, session):
        raise web.HTTPForbidden(text='Open this Mini App from your own Telegram bot chat')
    return session


def _state(session):
    from admin_store import STORE
    settings = STORE.settings()
    with STORE.db() as db:
        has_video = db.execute('SELECT 1 FROM media WHERE id=1').fetchone() is not None
    return {
        'ready': bool(session.ready),
        'interactive': bool(session.interactive_enabled),
        'phase': session.phase,
        'mode': session.mode,
        'notes': settings['notes'],
        'tutorial_url': settings['tutorial_url'] or ('/tutorial' if has_video else ''),
        'closed': session.closed,
        'pinch_zoom': bool(settings.get('pinch_zoom', True)),
    }


def _miniapp_html(lang):
    import i18n
    lang = lang if lang in i18n.LANGS else i18n.DEFAULT_LANG
    html = MINIAPP_HTML.replace('__LANG__', lang).replace('__DIR__', 'rtl' if i18n.is_rtl(lang) else 'ltr')
    return html


async def miniapp_page(request):
    # No token, email, card data, or Google page data is served before auth.
    lang = request.query.get('lang', '')
    resp = web.Response(text=_miniapp_html(lang), content_type='text/html')
    _secure_headers(resp)
    resp.headers['Content-Security-Policy'] = (
        "default-src 'none'; script-src 'self' 'unsafe-inline' https://telegram.org; "
        "style-src 'unsafe-inline'; connect-src 'self' wss:; "
        "img-src 'self' data:; font-src 'self'; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'none'"
    )
    return resp


async def miniapp_auth(request):
    try:
        body = await request.json()
        raw = body.get('initData', '')
    except (ValueError, TypeError):
        raise web.HTTPBadRequest(text='Missing initData')
    user_id = verify_init_data(raw, os.environ.get('TELEGRAM_BOT_TOKEN', ''))
    if user_id is None:
        raise web.HTTPUnauthorized(text='Telegram authentication failed; open from Telegram')
    # Sessions are only paired with the owner in a one-to-one bot chat.
    session = REGISTRY.for_chat(user_id)
    if session is None:
        raise web.HTTPNotFound(text='No active browser. Start Check Offer in this bot chat.')
    if not session.ready or not session.interactive_enabled:
        raise web.HTTPForbidden(text='Complete the sign-in steps first; the browser opens when it is ready.')
    session.auth_cookie = secrets.token_urlsafe(32)
    response = web.json_response({'token': session.token, **_state(session)})
    _secure_headers(response)
    response.set_cookie(
        COOKIE_NAME, session.auth_cookie,
        httponly=True, secure=True, samesite='Lax', path='/',
        max_age=86400,
    )
    return response


async def miniapp_status(request):
    session = _require_session(request)
    return _secure_headers(web.json_response(_state(session)))


async def miniapp_connected(request):
    session = _require_session(request)
    if not session.in_use or not session.ready:
        raise web.HTTPConflict(text='Connect the browser viewer first')
    session.viewer_connected = True
    if session.interactive_enabled and not getattr(session, "google_one_mobile_probe", False):
        from admin_store import STORE
        if not STORE.consume(session.token):
            raise web.HTTPForbidden(text='Access code revoked')
    return _secure_headers(web.json_response({'ok': True}))


async def miniapp_viewport(request):
    session = _require_session(request)
    try:
        body = await request.json()
        width, height = body['width'], body['height']
        if type(width) is not int or type(height) is not int or not 200 <= width <= 4000 or not 200 <= height <= 4000:
            raise ValueError('Invalid viewport')
    except (ValueError, KeyError, TypeError):
        raise web.HTTPBadRequest(text='Invalid viewport')
    import asyncio
    try:
        geometry = await asyncio.to_thread(session.fit_viewport, width, height)
    except Exception:
        logger.exception('Could not fit browser viewport')
        raise web.HTTPServiceUnavailable(text='Could not fit browser. Tap Reconnect to retry.')
    return _secure_headers(web.json_response(geometry))


async def miniapp_end(request):
    session = _require_session(request)
    import asyncio
    await asyncio.to_thread(REGISTRY.discard, session)
    response = _secure_headers(web.json_response({'closed': True}))
    response.del_cookie(COOKIE_NAME, path='/')
    return response


MINIAPP_HTML = r'''<!doctype html>
<html lang="__LANG__" dir="__DIR__"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<meta name="color-scheme" content="dark light">
<title>DigiPro Live Browser</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{color-scheme:dark;--bg:#0b1220;--fg:#f8fafc;--muted:#9caec2;--line:#29405c;--accent:#2481ef}
*{box-sizing:border-box}html,body{margin:0;width:100%;height:100%;background:var(--bg);color:var(--fg);font-family:system-ui,-apple-system,sans-serif;overflow:hidden}
main{height:var(--tg-viewport-stable-height,100dvh);display:flex;flex-direction:column;padding-top:env(safe-area-inset-top);padding-bottom:env(safe-area-inset-bottom)}
header{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:11px 13px;background:#111d32;border-bottom:1px solid var(--line)}
h1{font-size:15px;margin:0;line-height:1.3}.detail{font-size:12px;color:var(--muted);margin-top:4px;max-width:75vw;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.actions{display:flex;align-items:center;gap:7px}button{border:1px solid var(--line);background:#183353;color:white;padding:9px 10px;border-radius:10px;font-size:12px;cursor:pointer;white-space:nowrap}button.danger{background:#562a36;border-color:#804252}
#screen{position:relative;flex:1;min-height:0;overflow:hidden;display:flex;align-items:center;justify-content:center;background:#202020;touch-action:none}#screen canvas{touch-action:none;transform-origin:0 0;will-change:transform}
#zoom-reset{position:absolute;top:8px;right:8px;z-index:3;padding:7px 11px;border-radius:20px;background:rgba(17,29,50,.9)}#zoom-reset[hidden]{display:none}
#overlay{position:absolute;inset:60px 0 0;display:flex;align-items:center;justify-content:center;padding:25px;text-align:center;background:#0b1220;z-index:2}
#overlay.hidden{display:none}#overlay h2{font-size:18px;font-weight:600;margin:0 0 10px}#overlay p{font-size:14px;line-height:1.5;color:var(--muted);max-width:400px}
#foot{font-size:11px;color:var(--muted);padding:6px 13px;background:#111d32;border-top:1px solid var(--line)}
[hidden]{display:none!important}
#typing-bar{display:flex;gap:5px;flex-wrap:wrap;padding:7px;background:#111d32;flex-shrink:0}
#input-tools{padding:6px;background:#111d32;flex-shrink:0}#phone-input{font-size:16px;width:100%;height:38px;resize:none;color:white;background:#183353;border:1px solid #426289;border-radius:8px;padding:6px;touch-action:auto}
#input-tools small{display:block;color:#9caec2;margin-bottom:4px}
#clipboard-panel{position:fixed;inset:20% 12px auto;z-index:5;background:#14243b;padding:16px;border:1px solid #426289;border-radius:12px}
#copy-text{width:100%;height:100px;font-size:16px}header .actions{flex-wrap:wrap}
</style></head><body><main>
<header><div><h1 id="apptitle">🖥️ DigiPro Live Browser</h1><div class="detail" id="status"></div></div>
<div class="actions"><button id="reconnect"></button><button class="danger" id="end"></button></div></header>
<div id="screen"><button id="zoom-reset" hidden>🔍 100%</button></div><div id="overlay"><div><h2 id="headline"></h2><p id="description"></p></div></div>
<div id="typing-bar"><button id="keyboard"></button><button id="numbers">123</button><button id="paste"></button><button id="copy"></button><button id="backspace">⌫</button><button id="next-field"></button><button id="enter-key"></button></div>
<div id="input-tools" hidden><small id="phonehint"></small><textarea id="phone-input" aria-label="Phone keyboard input" inputmode="text" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false"></textarea><button id="hide-keyboard"></button></div>
<div id="clipboard-panel" hidden><p id="copyhint"></p><textarea id="copy-text" readonly aria-label="Selected remote text"></textarea><button id="copy-confirm"></button><button id="copy-close"></button></div>
<div id="foot"></div>
</main>
<script type="module">
import RFB from '/novnc/core/rfb.js';
import {attachKeyboard} from '/mobile-keyboard.js';
const I18N={
 en:{title:'🖥️ DigiPro Live Browser',authenticating:'Authenticating with Telegram…',connecting:'Connecting securely…',connectingDesc:'Only the Telegram account that started this session can view it.',reconnect:'🔄 Reconnect',end:'⏹ End',keyboard:'⌨ Keyboard',paste:'Paste',copy:'Copy',next:'Next ⇥',enter:'Enter',phoneHint:'Tap a field in the browser, then type here or long-press to paste.',hideKeyboard:'Hide keyboard',copyHint:'Copy selected browser text',copyToPhone:'Copy to phone',close:'Close',footer:'Private browser • Complete your operation, then select End',browserStarting:'Browser starting…',sessionUnavailableTitle:'Session unavailable',sessionUnavailableDesc:'The browser was closed. Return to the bot.',startingBrowserTitle:'Starting your browser…',startingBrowserDesc:'The bot is signing in and preparing Google One. The live view will appear automatically.',reconnectingStatus:'Reconnecting…',interactiveConnected:'Interactive browser connected',liveViewConnected:'Live view connected · automation running',disconnectedTitle:'Browser disconnected',disconnectedDesc:'Tap Reconnect. Your Google session remains on the server.',viewerUnavailableTitle:'Viewer unavailable',viewerUnavailableDesc:'Could not load the remote Chrome screen.',screenFitUnavailable:'⚠️ Screen fit unavailable · tap Reconnect',openTelegramTitle:'Open inside Telegram',openTelegramDesc:'Launch this Mini App using the button in your bot chat. Ordinary browser links cannot sign in.',unableOpenTitle:'Unable to open browser',connectionProblemTitle:'Connection problem',connectionProblemDesc:'Please reopen this Mini App from the bot.',reconnectingTitle:'Reconnecting…',reconnectingDesc:'Attempting to restore the live browser.',confirmClose:'Close the remote browser session?',sessionClosedTitle:'Session closed',sessionClosedDesc:'Return to the bot to start another session.',instructions:' • Instructions'},
 ar:{title:'🖥️ المتصفح المباشر — ديجي برو',authenticating:'جارٍ التحقق مع تيليجرام…',connecting:'جارٍ الاتصال بأمان…',connectingDesc:'فقط حساب تيليجرام الذي بدأ هذه الجلسة يمكنه رؤيتها.',reconnect:'🔄 إعادة الاتصال',end:'⏹ إنهاء',keyboard:'⌨ لوحة المفاتيح',paste:'لصق',copy:'نسخ',next:'التالي ⇥',enter:'إدخال',phoneHint:'اضغط على حقل في المتصفح، ثم اكتب هنا أو اضغط مطولًا للصق.',hideKeyboard:'إخفاء لوحة المفاتيح',copyHint:'نسخ النص المحدد من المتصفح',copyToPhone:'نسخ إلى الهاتف',close:'إغلاق',footer:'متصفح خاص • أنهِ عمليتك، ثم اختر إنهاء',browserStarting:'المتصفح قيد التشغيل…',sessionUnavailableTitle:'الجلسة غير متوفرة',sessionUnavailableDesc:'تم إغلاق المتصفح. رجع إلى البوت.',startingBrowserTitle:'جارٍ تشغيل متصفحك…',startingBrowserDesc:'البوت يقوم بتسجيل الدخول وتجهيز Google One. ستظهر العرض المباشر تلقائيًا.',reconnectingStatus:'إعادة الاتصال…',interactiveConnected:'المتصفح التفاعلي متصل',liveViewConnected:'العرض المباشر متصل · الأتمتة قيد التشغيل',disconnectedTitle:'انقطع اتصال المتصفح',disconnectedDesc:'اضغط على إعادة الاتصال. تبقى جلسة Google على الخادم.',viewerUnavailableTitle:'العارض غير متوفر',viewerUnavailableDesc:'تعذر تحميل شاشة Chrome البعيدة.',screenFitUnavailable:'⚠️ تعذر ضبط الشاشة · اضغط إعادة الاتصال',openTelegramTitle:'افتح من داخل تيليجرام',openTelegramDesc:'شغّل هذا التطبيق المصغر من الزر في محادثة البوت. روابط المتصفح العادية لا يمكنها تسجيل الدخول.',unableOpenTitle:'تعذر فتح المتصفح',connectionProblemTitle:'مشكلة في الاتصال',connectionProblemDesc:'يرجى إعادة فتح هذا التطبيق المصغر من البوت.',reconnectingTitle:'إعادة الاتصال…',reconnectingDesc:'جارٍ استعادة المتصفح المباشر.',confirmClose:'إغلاق جلسة المتصفح البعيد؟',sessionClosedTitle:'تم إغلاق الجلسة',sessionClosedDesc:'رجع إلى البوت لبدء جلسة أخرى.',instructions:' • التعليمات'},
 vi:{title:'🖥️ Trình duyệt trực tiếp DigiPro',authenticating:'Đang xác thực với Telegram…',connecting:'Đang kết nối an toàn…',connectingDesc:'Chỉ tài khoản Telegram đã bắt đầu phiên này có thể xem.',reconnect:'🔄 Kết nối lại',end:'⏹ Kết thúc',keyboard:'⌨ Bàn phím',paste:'Dán',copy:'Sao chép',next:'Tiếp ⇥',enter:'Enter',phoneHint:'Chạm vào một trường trong trình duyệt, rồi gõ ở đây hoặc nhấn giữ để dán.',hideKeyboard:'Ẩn bàn phím',copyHint:'Sao chép văn bản đã chọn từ trình duyệt',copyToPhone:'Sao chép vào điện thoại',close:'Đóng',footer:'Trình duyệt riêng tư • Hoàn tất thao tác, rồi chọn Kết thúc',browserStarting:'Trình duyệt đang khởi động…',sessionUnavailableTitle:'Phiên không khả dụng',sessionUnavailableDesc:'Trình duyệt đã đóng. Quay lại bot.',startingBrowserTitle:'Đang khởi động trình duyệt…',startingBrowserDesc:'Bot đang đăng nhập và chuẩn bị Google One. Chế độ xem trực tiếp sẽ tự xuất hiện.',reconnectingStatus:'Đang kết nối lại…',interactiveConnected:'Trình duyệt tương tác đã kết nối',liveViewConnected:'Đã kết nối xem trực tiếp · đang tự động hóa',disconnectedTitle:'Trình duyệt đã ngắt kết nối',disconnectedDesc:'Nhấn Kết nối lại. Phiên Google của bạn vẫn còn trên máy chủ.',viewerUnavailableTitle:'Trình xem không khả dụng',viewerUnavailableDesc:'Không thể tải màn hình Chrome từ xa.',screenFitUnavailable:'⚠️ Không thể vừa màn hình · nhấn Kết nối lại',openTelegramTitle:'Mở trong Telegram',openTelegramDesc:'Hãy mở Mini App này bằng nút trong trò chuyện bot. Liên kết trình duyệt thông thường không thể đăng nhập.',unableOpenTitle:'Không thể mở trình duyệt',connectionProblemTitle:'Lỗi kết nối',connectionProblemDesc:'Vui lòng mở lại Mini App này từ bot.',reconnectingTitle:'Đang kết nối lại…',reconnectingDesc:'Đang khôi phục trình duyệt trực tiếp.',confirmClose:'Đóng phiên trình duyệt từ xa?',sessionClosedTitle:'Đã đóng phiên',sessionClosedDesc:'Quay lại bot để bắt đầu phiên khác.',instructions:' • Hướng dẫn'},
 es:{title:'🖥️ Navegador en vivo de DigiPro',authenticating:'Autenticando con Telegram…',connecting:'Conectando de forma segura…',connectingDesc:'Solo la cuenta de Telegram que inició esta sesión puede verla.',reconnect:'🔄 Reconectar',end:'⏹ Finalizar',keyboard:'⌨ Teclado',paste:'Pegar',copy:'Copiar',next:'Siguiente ⇥',enter:'Entrar',phoneHint:'Toca un campo en el navegador, luego escribe aquí o mantén pulsado para pegar.',hideKeyboard:'Ocultar teclado',copyHint:'Copiar texto seleccionado del navegador',copyToPhone:'Copiar al teléfono',close:'Cerrar',footer:'Navegador privado • Completa tu operación y luego selecciona Finalizar',browserStarting:'El navegador está iniciando…',sessionUnavailableTitle:'Sesión no disponible',sessionUnavailableDesc:'El navegador se cerró. Vuelve al bot.',startingBrowserTitle:'Iniciando tu navegador…',startingBrowserDesc:'El bot está iniciando sesión y preparando Google One. La vista en vivo aparecerá automáticamente.',reconnectingStatus:'Reconectando…',interactiveConnected:'Navegador interactivo conectado',liveViewConnected:'Vista en vivo conectada · automatización en curso',disconnectedTitle:'Navegador desconectado',disconnectedDesc:'Toca Reconectar. Tu sesión de Google permanece en el servidor.',viewerUnavailableTitle:'Visor no disponible',viewerUnavailableDesc:'No se pudo cargar la pantalla remota de Chrome.',screenFitUnavailable:'⚠️ No se pudo ajustar la pantalla · toca Reconectar',openTelegramTitle:'Abrir dentro de Telegram',openTelegramDesc:'Abre esta Mini App usando el botón en el chat del bot. Los enlaces de navegador comunes no pueden iniciar sesión.',unableOpenTitle:'No se pudo abrir el navegador',connectionProblemTitle:'Problema de conexión',connectionProblemDesc:'Vuelve a abrir esta Mini App desde el bot.',reconnectingTitle:'Reconectando…',reconnectingDesc:'Restaurando el navegador en vivo.',confirmClose:'¿Cerrar la sesión del navegador remoto?',sessionClosedTitle:'Sesión cerrada',sessionClosedDesc:'Vuelve al bot para iniciar otra sesión.',instructions:' • Instrucciones'},
};
const LANG=(document.documentElement.getAttribute('lang')||'en');
const L=I18N[LANG]||I18N.en;
const tg=window.Telegram?.WebApp;
const status=document.querySelector('#status');
const overlay=document.querySelector('#overlay');
const headline=document.querySelector('#headline');
const description=document.querySelector('#description');
const screen=document.querySelector('#screen');
document.querySelector('#apptitle').textContent=L.title;
status.textContent=L.authenticating;
document.querySelector('#reconnect').textContent=L.reconnect;
document.querySelector('#end').textContent=L.end;
document.querySelector('#keyboard').textContent=L.keyboard;
document.querySelector('#paste').textContent=L.paste;
document.querySelector('#copy').textContent=L.copy;
document.querySelector('#next-field').textContent=L.next;
document.querySelector('#enter-key').textContent=L.enter;
document.querySelector('#phonehint').textContent=L.phoneHint;
document.querySelector('#hide-keyboard').textContent=L.hideKeyboard;
document.querySelector('#copyhint').textContent=L.copyHint;
document.querySelector('#copy-confirm').textContent=L.copyToPhone;
document.querySelector('#copy-close').textContent=L.close;
document.querySelector('#foot').textContent=L.footer;
headline.textContent=L.connecting;description.textContent=L.connectingDesc;
let token=null,rfb=null,interactivity=false,closed=false,connected=false,lastAttempt=0,mode='balanced';
const keyboard=attachKeyboard({screen,getViewer:()=>rfb,isReady:()=>connected&&interactivity&&!closed,status});
function show(message,details){headline.textContent=message;description.textContent=details||'';overlay.classList.remove('hidden')}
function hide(){overlay.classList.add('hidden')}
function stateText(data){status.textContent=data.phase||L.browserStarting;mode=data.mode||'balanced';
 pinchEnabled=data.pinch_zoom!==false;zoomBtn.hidden=!pinchEnabled||zoomScale===1;
 const foot=document.querySelector('#foot');foot.textContent=data.notes||L.footer;foot.hidden=!data.notes&&!data.tutorial_url&&!data.notes;
 if(data.tutorial_url){const a=document.createElement('a');a.textContent=L.instructions;a.href=data.tutorial_url;a.target='_blank';a.rel='noopener noreferrer';foot.append(a)}
}

// ── Finger zoom (pinch to magnify the remote screen; admin can disable it) ──
const zoomBtn=document.querySelector('#zoom-reset');
let pinchEnabled=true,zoomScale=1,zoomTx=0,zoomTy=0,pinchActive=false,pinchStartDist=0,pinchStartScale=1,pinchStartMid=null,pinchStartTx=0,pinchStartTy=0;
function zoomTarget(){return screen.querySelector('canvas')}
function applyZoom(){
 const el=zoomTarget();if(!el)return;
 el.style.transform=zoomScale===1?'':`translate(${zoomTx}px,${zoomTy}px) scale(${zoomScale})`;
 zoomBtn.hidden=!pinchEnabled||zoomScale===1;zoomBtn.textContent='🔍 '+Math.round(zoomScale*100)+'%';
}
function resetZoom(){zoomScale=1;zoomTx=0;zoomTy=0;applyZoom()}
function touchDist(a,b){return Math.hypot(a.clientX-b.clientX,a.clientY-b.clientY)}
function touchMid(a,b){return{x:(a.clientX+b.clientX)/2,y:(a.clientY+b.clientY)/2}}
screen.addEventListener('touchstart',e=>{
 if(!pinchEnabled||e.touches.length!==2)return;
 pinchActive=true;e.preventDefault();e.stopPropagation();
 pinchStartDist=touchDist(e.touches[0],e.touches[1]);pinchStartScale=zoomScale;
 pinchStartMid=touchMid(e.touches[0],e.touches[1]);pinchStartTx=zoomTx;pinchStartTy=zoomTy;
},{capture:true,passive:false});
screen.addEventListener('touchmove',e=>{
 if(!pinchEnabled||!pinchActive||e.touches.length!==2)return;
 e.preventDefault();e.stopPropagation();
 const d=touchDist(e.touches[0],e.touches[1]);
 zoomScale=Math.min(3,Math.max(1,pinchStartScale*d/pinchStartDist));
 const m=touchMid(e.touches[0],e.touches[1]);
 zoomTx=pinchStartTx+(m.x-pinchStartMid.x);zoomTy=pinchStartTy+(m.y-pinchStartMid.y);
 if(zoomScale<=1.02){zoomScale=1;zoomTx=0;zoomTy=0}
 applyZoom();
},{capture:true,passive:false});
screen.addEventListener('touchend',e=>{if(e.touches.length<2)pinchActive=false},{capture:true,passive:true});
zoomBtn.onclick=resetZoom;
async function state(){
 if(closed||!token)return;
 try{
  const res=await fetch('/miniapp-status/'+encodeURIComponent(token),{cache:'no-store'});
  if(!res.ok){closed=true;show(L.sessionUnavailableTitle,L.sessionUnavailableDesc);rfb?.disconnect();return}
  const data=await res.json();stateText(data);
  interactivity=!!data.interactive;
  if(rfb)rfb.viewOnly=!interactivity;
  if(data.ready){
   if(!rfb && Date.now()-lastAttempt>2500)connect();
   else if(connected)hide();
  }else{show(L.startingBrowserTitle,L.startingBrowserDesc);}
 }catch(e){status.textContent=L.reconnectingStatus}
}
function connect(){
 if(!token||closed)return;
 rfb?.disconnect();rfb=null;connected=false;lastAttempt=Date.now();
 const scheme=location.protocol==='https:'?'wss:':'ws:';
 const endpoint=scheme+'//'+location.host+'/miniapp-ws/'+encodeURIComponent(token);
 try{
  const viewer=new RFB(screen,endpoint);rfb=viewer;keyboard.bind(viewer);
  viewer.qualityLevel=mode==='fast'?3:mode==='quality'?8:6;viewer.compressionLevel=mode==='fast'?5:3;
  viewer.scaleViewport=true;viewer.clipViewport=false;viewer.resizeSession=false;viewer.viewOnly=!interactivity;
  viewer.addEventListener('connect',()=>{if(rfb!==viewer)return;fetch('/miniapp-connected/'+encodeURIComponent(token),{method:'POST'}).catch(()=>{});connected=true;hide();resetZoom();status.textContent=interactivity?L.interactiveConnected:L.liveViewConnected});
  viewer.addEventListener('disconnect',()=>{if(rfb!==viewer)return;connected=false;if(!closed){rfb=null;show(L.disconnectedTitle,L.disconnectedDesc)}});
 }catch(e){show(L.viewerUnavailableTitle,L.viewerUnavailableDesc)}
}
let fitting=false,lastWidth=0,fitTimer;
async function fitBrowser(){
 if(!token||closed||fitting)return;
 fitting=true;
 try{
  const width=Math.max(200,Math.round(screen.clientWidth));
  const height=Math.max(200,Math.round(screen.clientHeight));
  const res=await fetch('/miniapp-viewport/'+encodeURIComponent(token),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({width,height})});
  if(!res.ok){status.textContent=L.screenFitUnavailable;return}
  lastWidth=width;
 }finally{fitting=false}
}
new ResizeObserver(()=>{
 if(!token||Math.abs(screen.clientWidth-lastWidth)<30)return;
 clearTimeout(fitTimer);fitTimer=setTimeout(()=>fitBrowser().catch(()=>{}),350);
}).observe(screen);
async function init(){
 try{
  if(!tg?.initData){show(L.openTelegramTitle,L.openTelegramDesc);return}
  tg.ready();tg.expand();
  const res=await fetch('/miniapp-auth',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({initData:tg.initData}),cache:'no-store'});
  if(!res.ok){show(L.unableOpenTitle,await res.text());return}
  const data=await res.json();token=data.token;stateText(data);
  await fitBrowser();await state();setInterval(state,2000);
 }catch(e){show(L.connectionProblemTitle,L.connectionProblemDesc)}
}
document.querySelector('#reconnect').onclick=async()=>{if(!token){init();return}if(rfb)rfb.disconnect();rfb=null;connected=false;lastAttempt=0;resetZoom();show(L.reconnectingTitle,L.reconnectingDesc);await fitBrowser();state()};
document.querySelector('#end').onclick=async()=>{
 if(!token)return;
 if(!confirm(L.confirmClose))return;
 await fetch('/miniapp-end/'+encodeURIComponent(token),{method:'POST',cache:'no-store'});
 closed=true;keyboard.cleanup();rfb?.disconnect();show(L.sessionClosedTitle,L.sessionClosedDesc);
};
init();
</script></body></html>'''
