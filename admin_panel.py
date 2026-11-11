"""Telegram-authenticated admin dashboard, served by the existing aiohttp app."""
import asyncio
import io
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import stat
import time
import zipfile
from aiohttp import web
from admin_store import STORE, is_admin

AUTH = {}
COOKIE = 'digipro_admin'

@web.middleware
async def errors(request, handler):
    try:
        return await handler(request)
    except (ValueError, zipfile.BadZipFile) as exc:
        raise web.HTTPBadRequest(text=str(exc))

async def page(request):
    from remote_checkout import _secure_headers
    res = _secure_headers(web.FileResponse(Path(__file__).with_name('admin.html')))
    res.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline' https://telegram.org; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"
    return res

async def authenticate(request):
    from telegram_miniapp import verify_init_data
    user = verify_init_data((await request.json()).get('initData',''), os.getenv('TELEGRAM_BOT_TOKEN',''))
    if not user or not is_admin(user):
        raise web.HTTPForbidden(text='Admin access denied. Configure ADMIN_TELEGRAM_IDS.')
    for key, entry in list(AUTH.items()):
        if entry[1] < time.time() or entry[0] == user:
            AUTH.pop(key, None)
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    AUTH[token] = (user, time.time()+86400, csrf)
    res = web.json_response({'csrf': csrf})
    res.set_cookie(COOKIE, token, httponly=True, secure=True, samesite='Strict', max_age=86400)
    res.headers['Cache-Control'] = 'no-store'
    return res

def require(request):
    entry = AUTH.get(request.cookies.get(COOKIE,''))
    if not entry or entry[1] < time.time() or not is_admin(entry[0]):
        raise web.HTTPUnauthorized(text='Reopen dashboard from /admin')
    if request.method != 'GET' and not secrets.compare_digest(request.headers.get('X-CSRF',''), entry[2]):
        raise web.HTTPForbidden(text='Invalid request token')
    return entry[0]

async def snapshot(request):
    require(request)
    from remote_checkout import REGISTRY
    data = STORE.snapshot()
    # Extension filesystem paths are internal details.
    for item in data['extensions']:
        item.pop('path', None)
    data['settings'] = STORE.settings()
    with REGISTRY.lock:
        data['sessions'] = [dict(id=s.token, owner=s.chat_id, phase=s.phase, interactive=s.interactive_enabled, age=int(time.monotonic()-s.created)) for s in REGISTRY.by_chat.values() if not s.closed]
    return web.json_response(data, headers={'Cache-Control':'no-store'})

async def action(request):
    require(request)
    body = await request.json()
    kind = request.match_info['action']
    from remote_checkout import REGISTRY
    if kind == 'settings':
        return web.json_response(STORE.save_settings(body))
    if kind == 'generate':
        return web.json_response({'codes': STORE.generate(body.get('count'))})
    if kind == 'delete-video':
        with STORE.db() as db:
            row = db.execute('SELECT path FROM media WHERE id=1').fetchone()
            db.execute('DELETE FROM media WHERE id=1')
        if row:
            Path(row[0]).unlink(missing_ok=True)
        return web.json_response({'ok':True})
    if kind == 'revoke':
        STORE.revoke(body['code'])
        with STORE.db() as db:
            ids = [r[0] for r in db.execute('SELECT id FROM operations WHERE code=? AND ended IS NULL', (body['code'],))]
        for ident in ids:
            s = REGISTRY.find(ident)
            if s:
                await asyncio.to_thread(REGISTRY.discard, s)
    elif kind == 'stop':
        s = REGISTRY.find(body['id'])
        if s:
            await asyncio.to_thread(REGISTRY.discard, s)
    elif kind == 'review':
        if body.get('review') not in ('completed','incomplete',''):
            raise ValueError('Invalid review')
        with STORE.db() as db:
            db.execute('UPDATE operations SET review=? WHERE id=?', (body['review'],body['id']))
    elif kind == 'extension':
        if type(body.get('enabled')) is not bool:
            raise ValueError('Invalid extension state')
        with STORE.db() as db:
            db.execute('UPDATE extensions SET enabled=? WHERE id=?', (int(body['enabled']),body['id']))
    else:
        raise web.HTTPNotFound()
    return web.json_response({'ok':True})

def install_extension(payload):
    """Extract a bounded ZIP without traversal, symlinks or duplicate files."""
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        entries = archive.infolist()
        if len(entries) > 3000 or sum(e.file_size for e in entries) > 80*1024*1024:
            raise ValueError('Extension uncompressed limit: 80 MB / 3000 files')
        seen = set()
        for info in entries:
            path = PurePosixPath(info.filename)
            if path.is_absolute() or '..' in path.parts or '\\' in info.filename or ':' in info.filename or info.filename in seen or stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError('Unsafe extension archive')
            seen.add(info.filename)
        manifests = [e for e in entries if PurePosixPath(e.filename).name == 'manifest.json']
        if not manifests:
            raise ValueError('manifest.json is required')
        main = min(manifests, key=lambda e: len(PurePosixPath(e.filename).parts))
        if main.file_size > 1024*1024:
            raise ValueError('Manifest too large')
        manifest = json.loads(archive.read(main))
        if manifest.get('manifest_version') not in (2,3) or not isinstance(manifest.get('name'), str):
            raise ValueError('Invalid Chrome extension manifest')
        ident = secrets.token_hex(12)
        root = STORE.root / 'extensions' / ident
        root.mkdir(parents=True)
        try:
            archive.extractall(root)
            path = root.joinpath(*PurePosixPath(main.filename).parent.parts)
            with STORE.db() as db:
                db.execute('INSERT INTO extensions(id,name,path) VALUES (?,?,?)', (ident,manifest['name'][:200],str(path.resolve())))
        except BaseException:
            import shutil
            shutil.rmtree(root, ignore_errors=True)
            raise
    return ident

async def upload(request):
    require(request)
    payload = await request.read()
    if len(payload) > 20*1024*1024:
        raise web.HTTPRequestEntityTooLarge(max_size=20*1024*1024, actual_size=len(payload))
    ident = await asyncio.to_thread(install_extension, payload)
    return web.json_response({'id':ident})

async def upload_video(request):
    require(request)
    import tempfile
    root = STORE.root / 'tutorial'
    root.mkdir(exist_ok=True)
    fd, filename = tempfile.mkstemp(dir=root, suffix='.video')
    size = 0
    try:
        with os.fdopen(fd, 'wb') as output:
            async for chunk in request.content.iter_chunked(65536):
                size += len(chunk)
                if size > 300*1024*1024:
                    raise ValueError('Video maximum is 300 MB')
                output.write(chunk)
        with open(filename, 'rb') as f:
            header = f.read(16)
        if not (header[4:8] == b'ftyp' or header[:4] == bytes.fromhex('1a45dfa3')):
            raise ValueError('Upload MP4 or WebM video')
        with STORE.db() as db:
            old = db.execute('SELECT path FROM media WHERE id=1').fetchone()
            db.execute('INSERT OR REPLACE INTO media VALUES (1,?,?)', (filename,'Tutorial'))
        if old:
            Path(old[0]).unlink(missing_ok=True)
    except BaseException:
        Path(filename).unlink(missing_ok=True)
        raise
    return web.json_response({'ok':True})

async def tutorial(request):
    from remote_checkout import REGISTRY, _secure_headers
    from telegram_miniapp import authorized
    admin = AUTH.get(request.cookies.get(COOKIE,''))
    permitted = bool(admin and admin[1] > time.time() and is_admin(admin[0]))
    with REGISTRY.lock:
        permitted = permitted or any(authorized(request,s) and not s.closed for s in REGISTRY.by_chat.values())
    if not permitted:
        raise web.HTTPForbidden(text='Open from Telegram first')
    with STORE.db() as db:
        row = db.execute('SELECT path FROM media WHERE id=1').fetchone()
    if not row:
        raise web.HTTPNotFound(text='No tutorial uploaded')
    with open(row[0], 'rb') as f:
        header = f.read(12)
    res = _secure_headers(web.FileResponse(row[0]))
    res.content_type = 'video/mp4' if header[4:8] == b'ftyp' else 'video/webm'
    return res


def register(app):
    app.middlewares.append(errors)
    app.router.add_get('/admin', page)
    app.router.add_post('/admin-auth', authenticate)
    app.router.add_get('/admin-api/state', snapshot)
    app.router.add_post('/admin-api/upload', upload)
    app.router.add_post('/admin-api/video', upload_video)
    app.router.add_get('/tutorial', tutorial)
    app.router.add_post('/admin-api/{action}', action)
