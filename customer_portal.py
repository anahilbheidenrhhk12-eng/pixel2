"""Customer navigation: wallet credits, orders, support tickets and read-only API."""
import hashlib
import secrets
import time
from aiohttp import web
from telegram import ReplyKeyboardMarkup
from admin_store import STORE
import i18n


def init():
    with STORE.db() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY AUTOINCREMENT,owner INTEGER,message TEXT,status TEXT DEFAULT 'open',created REAL);
        CREATE TABLE IF NOT EXISTS api_keys(owner INTEGER PRIMARY KEY,hash TEXT UNIQUE);''')


BUTTONS={'BUY':'🛒 BUY','LOGIN':'🔐 LOGIN','WALLET':'👛 WALLET','ORDER':'🛍️ ORDER','SUPPORT':'💬 SUPPORT','API':'🔌 API','LANG':'🌐 LANGUAGE','ADMIN':'🛠️ ADMIN','CANCEL':'❌ CANCEL'}
_ACTION_KEY={'BUY':'btn_buy','LOGIN':'btn_login','WALLET':'btn_wallet','ORDER':'btn_order','SUPPORT':'btn_support','API':'btn_api','LANG':'btn_lang','ADMIN':'btn_admin','CANCEL':'btn_cancel'}


def label(action, lang='en'):
    return i18n.t(_ACTION_KEY[action], lang)


def reverse_map():
    """Every button label, in every language, mapped (uppercased) back to its action."""
    out={}
    for action, key in _ACTION_KEY.items():
        for lang in i18n.LANGS:
            out[i18n.t(key, lang).upper()] = action
    return out


def keyboard(admin=False,cancel=False,lang='en'):
    rows=[['LOGIN','BUY'],['WALLET','ORDER'],['SUPPORT','API'],['LANG']]
    if admin:rows.append(['ADMIN'])
    if cancel:rows.append(['CANCEL'])
    return ReplyKeyboardMarkup([[label(x,lang) for x in row] for row in rows],resize_keyboard=True,is_persistent=True,one_time_keyboard=False,input_field_placeholder=i18n.t('placeholder_menu',lang))


def orders(owner):
    with STORE.db() as db:
        return [dict(r) for r in db.execute('SELECT code,started,ended,status,review FROM operations WHERE owner=? ORDER BY started DESC LIMIT 50',(owner,))]

def balance(owner):
    with STORE.db() as db:
        return db.execute("SELECT count(*) FROM codes WHERE owner=? AND state='bound'",(owner,)).fetchone()[0]

async def handle(update,context,choice):
    init();uid=update.effective_user.id;lang=i18n.resolve(uid)
    if choice=='WALLET':
        import store_link
        extra=await store_link.wallet_lines(uid,lang)
        text=i18n.t('wallet_title',lang)+'\n\n'+i18n.t('wallet_body',lang,n=balance(uid))
        if extra:text+='\n\n'+'\n'.join(extra)
        url=store_link.topup_url()
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        kb=[[InlineKeyboardButton(i18n.t('wallet_topup_btn',lang),url=url)]] if url and store_link.configured() else []
        if store_link.configured():kb.append([InlineKeyboardButton(i18n.t('wallet_howto_btn',lang),callback_data='b:h')])
        await update.message.reply_text(text,reply_markup=InlineKeyboardMarkup(kb) if kb else None)
    elif choice=='ORDER':
        rows=orders(uid)
        body=('\n\n'.join(f"{i+1}. {r['code']}\n{i18n.t('order_status',lang)}: {r['status']}\n{i18n.t('order_review',lang)}: {r['review'] or i18n.t('order_pending',lang)}" for i,r in enumerate(rows[:10]))
              if rows else i18n.t('order_empty',lang))
        text=i18n.t('order_title',lang)+'\n\n'+body
        from remote_checkout import REGISTRY
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
        remote=REGISTRY.for_chat(uid)
        if remote and remote.ready and remote.interactive_enabled:
            await update.message.reply_text(text,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(i18n.t('live_browser_btn',lang),web_app=WebAppInfo(url=remote.url+'?lang='+lang))]]))
        else:
            await update.message.reply_text(text)
    elif choice=='SUPPORT':
        context.user_data['support_pending']=True
        await update.message.reply_text(i18n.t('support_title',lang)+'\n\n'+i18n.t('support_prompt',lang),reply_markup=keyboard(cancel=True,lang=lang))
    elif choice=='API':
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        await update.message.reply_text(i18n.t('api_title',lang),reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(i18n.t('api_generate_btn',lang),callback_data='customer:api')]]))
    elif choice=='LANG':
        await update.message.reply_text(i18n.t('choose_language',lang),reply_markup=i18n.picker_markup())

async def api_key(update,context):
    lang=i18n.resolve(update.effective_user.id)
    if update.effective_chat.type!='private':
        await update.callback_query.answer(i18n.t('api_private_only',lang),show_alert=True);return
    init();await update.callback_query.answer();token=secrets.token_urlsafe(32)
    with STORE.db() as db:db.execute('INSERT OR REPLACE INTO api_keys VALUES (?,?)',(update.effective_user.id,hashlib.sha256(token.encode()).hexdigest()))
    from remote_checkout import CHECKOUT_PUBLIC_URL
    await update.effective_message.reply_text(i18n.t('api_key_message',lang,token=token,url=CHECKOUT_PUBLIC_URL))

async def ticket(update,context):
    init();body=update.message.text.strip();lang=i18n.resolve(update.effective_user.id)
    if len(body)>3000:
        await update.message.reply_text(i18n.t('support_too_long',lang));return
    with STORE.db() as db:
        cur=db.execute('INSERT INTO tickets(owner,message,created) VALUES (?,?,?)',(update.effective_user.id,body,time.time()));ident=cur.lastrowid
    context.user_data.pop('support_pending',None)
    from admin_store import is_admin
    await update.message.reply_text(i18n.t('support_created',lang,id=ident),reply_markup=keyboard(is_admin(update.effective_user.id),lang=lang))

async def api_read(request):
    auth=request.headers.get('Authorization','')
    if not auth.startswith('Bearer ') or len(auth)>200:raise web.HTTPUnauthorized()
    with STORE.db() as db:
        row=db.execute('SELECT owner FROM api_keys WHERE hash=?',(hashlib.sha256(auth[7:].encode()).hexdigest(),)).fetchone()
    if not row:raise web.HTTPUnauthorized()
    return web.json_response({'login_credits':balance(row[0])} if request.match_info['kind']=='wallet' else {'orders':orders(row[0])},headers={'Cache-Control':'no-store'})

def register(app):
    init();app.router.add_get('/api/v1/{kind:wallet|orders}',api_read)
