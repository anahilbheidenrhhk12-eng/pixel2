"""Owner-only Telegram administration with native buttons and document uploads."""
import asyncio
import csv
import io
import json
from pathlib import Path
import secrets
import re
from telegram import InlineKeyboardButton as B, InlineKeyboardMarkup as K, ReplyKeyboardMarkup
from telegram.ext import ConversationHandler, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from admin_store import STORE, is_admin, DEFAULTS

INPUT, FILE = 90, 91
LABELS = dict(mode='Display Quality',max_sessions='Browser Capacity',maintenance='Maintenance',maintenance_message='Maintenance Message',final_url='Final Stage URL',second_url='Second URL',second_delay='Second URL Delay',close_on_activation='Close on Completion',completion_url='Completion URL',close_delay='Close Delay',notes='Customer Notes',tutorial_url='Tutorial URL',price='Code Price (USD)',instructions='Customer Instructions',channel='Required Channel',channel_link='Channel Join Link',topup_instructions='Top-up Instructions',pinch_zoom='Finger Zoom (Live Browser)')

MENU = {'Generate Codes':'generate','Access Codes':'codes:0','Extensions':'extensions','Settings':'settings','Live Sessions':'sessions','Reports':'reports:0','Export CSV':'export','Upload Tutorial':'video','Delete Tutorial':'removevideo','Support Tickets':'tickets'}
ICONS = {'Generate Codes':'🎟️','Access Codes':'🔑','Extensions':'🧩','Settings':'⚙️',
         'Live Sessions':'🖥️','Reports':'📊','Export CSV':'📤','Upload Tutorial':'🎬',
         'Delete Tutorial':'🗑️','Support Tickets':'💬','HOME':'🏠','CANCEL':'❌'}
DISPLAY_MENU={ICONS[k]+' '+k:v for k,v in MENU.items()}
MENU.update(DISPLAY_MENU)
def decorate(label):
    if label and not label[0].isascii():
        return label
    icon=ICONS.get(label)
    if not icon:
        icon=next((v for k,v in [('Back','↩️'),('Enable','▶️'),('Disable','⏹️'),('Delete','🗑️'),('Close','⏹️'),('Upload','📤'),('Next','➡️'),('Previous','⬅️'),('Search','🔎'),('Reply','💬'),('Completed','✅'),('Incomplete','⚠️')] if k.lower() in label.lower()),'⚙️')
    return icon+' '+label

def admin_keyboard():
    return ReplyKeyboardMarkup([[decorate(x) for x in row] for row in [['Generate Codes','Access Codes'],['Extensions','Settings'],['Live Sessions','Reports'],['Export CSV','Upload Tutorial'],['Delete Tutorial','Support Tickets'],['HOME','CANCEL']]],resize_keyboard=True,is_persistent=True)

async def menu_choice(update,context):
    return await callback(update,context,MENU[update.message.text])

def keyboard(rows):
    return K([[B(decorate(label),callback_data='a:'+data) for label,data in row] for row in rows])

async def allowed(update):
    ok = update.effective_chat.type == 'private' and is_admin(update.effective_user.id)
    if update.callback_query:
        await update.callback_query.answer(None if ok else 'Administrator access only',show_alert=not ok)
    elif not ok:
        await update.effective_message.reply_text('This interface is available to administrators only.')
    return ok

async def show(update,text,rows):
    markup=keyboard(rows)
    if update.callback_query:
        # A new message avoids Telegram's "message is not modified" failures.
        await update.effective_message.reply_text(text,reply_markup=markup)
    else:
        await update.message.reply_text(text,reply_markup=markup)

async def open_admin(update,context):
    if not await allowed(update):return ConversationHandler.END
    context.user_data.pop('admin_action',None)
    from remote_checkout import REGISTRY
    with STORE.db() as db:
        total=db.execute('SELECT count(*) FROM codes').fetchone()[0]
        used=db.execute("SELECT count(*) FROM codes WHERE state='used'").fetchone()[0]
    text=f'🛠️ ADMIN CONTROL CENTER\n\nAccess codes: {total}\nUsed codes: {used}\nLive sessions: {len(REGISTRY.by_chat)}\n\nSelect a section below. Use HOME for the customer menu and CANCEL to stop an input.'
    await update.effective_message.reply_text(text,reply_markup=admin_keyboard())
    return ConversationHandler.END

async def callback(update,context,action=None):
    action=action or update.callback_query.data[2:]
    if action=='home':return await open_admin(update,context)
    if not await allowed(update):return ConversationHandler.END
    back=[[('Back to Admin','home')]]
    if action=='cancel':
        context.user_data.pop('admin_action',None)
        await show(update,'Menu closed.',[[('ADMIN','home')]])
        return ConversationHandler.END
    if action in ('generate','revoke','find'):
        context.user_data['admin_action']=action
        await show(update,{'generate':'How many codes? Send a number from 1 to 500.','revoke':'Send the code to revoke. Its active session will be closed.','find':'Send an email, code or Telegram user ID to search reports.'}[action],back)
        return INPUT
    if action=='settings':
        cfg=STORE.settings()
        rows=[[(LABELS[k]+' : '+str(cfg[k])[:28], 'set:'+k)] for k in LABELS]
        await show(update,'⚙️ Settings. Select a field to edit. Browser sessions have no time limit.',rows+back)
    elif action.startswith('set:'):
        key=action[4:]
        if key not in LABELS:return ConversationHandler.END
        if isinstance(DEFAULTS[key],bool):
            await show(update,LABELS[key],[[('Enable','bool:'+key+':1'),('Disable','bool:'+key+':0')]]+back)
        elif key=='mode':
            await show(update,'Display Quality',[[('Fast','mode:fast'),('Balanced','mode:balanced'),('High Quality','mode:quality')]]+back)
        else:
            context.user_data['admin_action']='set:'+key
            await show(update,'Send a value for '+LABELS[key]+'\nSend - to clear text or URL.\nCurrent value: '+str(STORE.settings()[key]),back)
            return INPUT
    elif action.startswith(('bool:','mode:')):
        try:
            if action.startswith('bool:'):
                _,key,value=action.split(':')
                if key not in ('maintenance','close_on_activation','pinch_zoom'):raise ValueError('Invalid setting')
                STORE.save_settings({key:value=='1'})
            else:STORE.save_settings({'mode':action.split(':')[1]})
            await show(update,'Saved successfully.',[[('Settings','settings')]]+back)
        except ValueError as e:await show(update,str(e),back)
    elif action.startswith('codes:'):
        offset=max(0,int(action.split(':')[1]));codes=STORE.snapshot()['codes'];page=codes[offset:offset+10]
        text='🔑 ACCESS CODES\n\n'+'\n'.join(f"{c['code']}\n{c['state']} • Telegram: {c['owner'] or '—'}" for c in page)
        rows=[[('Generate Codes','generate'),('Revoke Code','revoke')]]
        if offset:rows.append([('Previous',f'codes:{max(0,offset-10)}')])
        if offset+10<len(codes):rows.append([('Next',f'codes:{offset+10}')])
        await show(update,text,rows+back)
    elif action=='extensions':
        await extension_panel(update)
    elif action.startswith('extset:'):
        try:
            _, ident, enabled = action.split(':')
            if enabled not in ('0','1'):
                raise ValueError('Invalid extension state.')
            with STORE.db() as db:
                row=db.execute('SELECT path FROM extensions WHERE id=?',(ident,)).fetchone()
                if not row:
                    raise ValueError('Extension not found. Reopen Extensions.')
                if enabled=='1' and not (Path(row['path'])/'manifest.json').is_file():
                    raise ValueError('Extension files are missing. Upload the ZIP again.')
                db.execute('UPDATE extensions SET enabled=? WHERE id=?',(int(enabled),ident))
            await extension_panel(update)
        except ValueError as exc:
            await show(update,'⚠️ '+str(exc),[[('🧩 Extensions','extensions')]]+back)
    elif action.startswith('ext:'):
        # Old messages must not toggle the saved state unpredictably.
        await extension_panel(update)
    elif action in ('upload','video'):
        context.user_data['admin_action']=action
        await show(update,'Send '+('the extension ZIP file' if action=='upload' else 'an MP4 or WebM video as a Document')+' here, up to 20 MB.\nUse Attach → File.',back)
        return FILE
    elif action=='removevideo':
        await show(update,'Delete the tutorial video?',[[('Confirm Delete','confirmvideo')]]+back)
    elif action=='confirmvideo':
        with STORE.db() as db:
            row=db.execute('SELECT path FROM media WHERE id=1').fetchone();db.execute('DELETE FROM media WHERE id=1')
        if row:Path(row[0]).unlink(missing_ok=True)
        await show(update,'Tutorial deleted.',back)
    elif action=='sessions':
        from remote_checkout import REGISTRY
        with REGISTRY.lock:sessions=list(REGISTRY.by_chat.values())
        await show(update,'Live Sessions: '+str(len(sessions)),[[(str(s.chat_id)+' • '+s.phase[:25],'stop:'+s.token)] for s in sessions]+back)
    elif action.startswith('stop:'):
        await show(update,'Close this browser session?',[[('Close Session','end:'+action[5:])]]+back)
    elif action.startswith('end:'):
        from remote_checkout import REGISTRY
        s=REGISTRY.find(action[4:])
        if s:await asyncio.to_thread(REGISTRY.discard,s)
        await show(update,'Session closed.',[[('Sessions','sessions')]]+back)
    elif action.startswith('reports:'):
        offset=max(0,int(action.split(':')[1]));items=STORE.snapshot()['operations'];await report_page(update,items,offset)
    elif action.startswith('review:'):
        _,ident,value=action.split(':')
        if value not in ('completed','incomplete'):return ConversationHandler.END
        with STORE.db() as db:db.execute('UPDATE operations SET review=? WHERE id=?',(value,ident))
        await show(update,'Report review updated.',back)
    elif action=='tickets':
        from customer_portal import init
        init()
        with STORE.db() as db:items=[dict(r) for r in db.execute("SELECT * FROM tickets WHERE status='open' ORDER BY id DESC LIMIT 10")]
        await show(update,'💬 SUPPORT TICKETS\n\n'+('\n\n'.join('#'+str(t['id'])+' • '+str(t['owner'])+'\n'+t['message'][:200] for t in items) or 'No open tickets.'), [[('Reply #'+str(t['id']),'reply:'+str(t['id']))] for t in items]+back)
    elif action.startswith('reply:'):
        context.user_data['admin_action']=action
        await show(update,'Send your reply to this support ticket. The reply will be delivered to the customer.',back)
        return INPUT
    elif action=='export':
        data=STORE.snapshot();out=io.StringIO();writer=csv.writer(out);fields=['code','owner','email','started','ended','status','review'];writer.writerow(fields)
        for row in data['operations']:
            vals=[str(row[k] or '') for k in fields];writer.writerow(["'"+v if v.startswith(('=','+','-','@')) else v for v in vals])
        doc=io.BytesIO(('\ufeff'+out.getvalue()).encode());doc.name='reports.csv'
        await update.effective_message.reply_document(doc,caption='Session reports')
    return ConversationHandler.END

async def extension_panel(update):
    entries=STORE.snapshot()['extensions']
    rows=[[('📦 Upload ZIP Extension','upload')]]
    for entry in entries:
        status='🟢 ON' if entry['enabled'] else '🔴 OFF'
        rows.append([(status+' • '+entry['name'][:35], 'extensions')])
        rows.append([('▶️ Enable','extset:'+entry['id']+':1'),
                     ('⏹️ Disable','extset:'+entry['id']+':0')])
    rows.append([('↩️ Back to Admin','home')])
    text='🧩 CHROME EXTENSIONS\n\nChanges apply to new browser sessions.\nClose and reopen the browser to apply a change.'
    if not entries:
        text+='\n\n📭 No extensions uploaded yet.'
    await show(update,text,rows)

async def report_page(update,items,offset=0):
    rows=[];text='📊 Reports\n'
    for i,o in enumerate(items[offset:offset+5],start=offset+1):
        text+=f"\n{i}. {o['code']}\n{o['email']} • {o['owner']}\n{o['status']} • {o['review'] or 'Not reviewed'}\n"
        reason=(o.get('fail_reason') or '').strip() if hasattr(o,'get') else ''
        if reason and o['status'] not in ('closed','activation_detected'):
            text+=f"⚠️ Reason: {reason}\n"
        # Operation tokens are 43 chars; callback stays below Telegram's 64-byte limit.
        rows.append([(f'{i} Completed','review:'+o['id']+':completed'),(f'{i} Incomplete','review:'+o['id']+':incomplete')])
    if offset:rows.append([('Previous',f'reports:{max(0,offset-5)}')])
    if offset+5<len(items):rows.append([('Next',f'reports:{offset+5}')])
    await show(update,text or 'No reports yet.',rows+[[('Search','find'),('Back to Admin','home')]])

async def text_input(update,context):
    if not await allowed(update):return ConversationHandler.END
    action=context.user_data.get('admin_action','');raw=update.message.text.strip()
    try:
        if action=='generate':
            keys=STORE.generate(int(raw));doc=io.BytesIO(('\n'.join(k for k in keys)).encode());doc.name='login-codes.txt'
            await update.message.reply_document(doc,caption=f'Generated {len(keys)} codes')
            if len(keys)<=10:await update.message.reply_text('\n'.join(k for k in keys))
        elif action=='revoke':
            key=raw.removeprefix('LOGIN T=').removeprefix('T=').upper();STORE.revoke(key)
            from remote_checkout import REGISTRY
            with STORE.db() as db:ids=[r[0] for r in db.execute('SELECT id FROM operations WHERE code=? AND ended IS NULL',(key,))]
            for ident in ids:
                s=REGISTRY.find(ident)
                if s:await asyncio.to_thread(REGISTRY.discard,s)
            await update.message.reply_text('Code revoked if found.')
        elif action=='find':
            items=[o for o in STORE.snapshot()['operations'] if raw.lower() in (str(o['owner'])+' '+o['email']+' '+o['code']).lower()]
            await report_page(update,items[:5])
        elif action.startswith('reply:'):
            ident=int(action[6:])
            with STORE.db() as db:row=db.execute('SELECT owner FROM tickets WHERE id=?',(ident,)).fetchone()
            if not row:raise ValueError('Ticket not found')
            await context.bot.send_message(chat_id=row[0],text='SUPPORT • Ticket #'+str(ident)+'\n\n'+raw)
            with STORE.db() as db:db.execute("UPDATE tickets SET status='answered' WHERE id=?",(ident,))
            await update.message.reply_text('Reply sent.')
        elif action.startswith('set:'):
            key=action[4:];value=int(raw) if type(DEFAULTS[key]) is int else '' if raw=='-' else raw
            STORE.save_settings({key:value});await update.message.reply_text('Saved successfully.')
    except (ValueError,KeyError) as e:
        await update.message.reply_text('Could not save: '+str(e)+'\nTry again or select CANCEL.')
        return INPUT
    context.user_data.pop('admin_action',None)
    await show(update,'Choose your next action:',[[('ADMIN','home')]])
    return ConversationHandler.END

async def file_input(update,context):
    if not await allowed(update):return ConversationHandler.END
    doc=update.message.document
    if not doc:
        await update.message.reply_text('Send a Document using Attach → File.');return FILE
    if not doc.file_size or doc.file_size>20*1024*1024:
        await update.message.reply_text('Maximum upload size: 20 MB.');return FILE
    try:
        tgfile=await context.bot.get_file(doc.file_id);payload=bytes(await tgfile.download_as_bytearray())
        if len(payload)>20*1024*1024:raise ValueError('File exceeds 20 MB.')
        if context.user_data.get('admin_action')=='upload':
            if not (doc.file_name or '').lower().endswith('.zip'):raise ValueError('Send a ZIP file')
            from admin_panel import install_extension
            await asyncio.to_thread(install_extension,payload)
            msg='✅ Extension uploaded and enabled for new browser sessions.'
        else:
            if not (payload[4:8]==b'ftyp' or payload[:4]==bytes.fromhex('1a45dfa3')):raise ValueError('Send MP4 or WebM')
            root=STORE.root/'tutorial';root.mkdir(exist_ok=True);path=root/(secrets.token_hex(12)+'.video');path.write_bytes(payload)
            with STORE.db() as db:
                old=db.execute('SELECT path FROM media WHERE id=1').fetchone();db.execute('INSERT OR REPLACE INTO media VALUES (1,?,?)',(str(path),'Tutorial'))
            if old:Path(old[0]).unlink(missing_ok=True)
            msg='Tutorial uploaded. Clear Tutorial URL to display this video.'
        await show(update,msg,[[('🧩 Extensions','extensions'),('↩️ Admin','home')]] if context.user_data.get('admin_action')=='upload' else [[('ADMIN','home')]])
        context.user_data.pop('admin_action',None)
        return ConversationHandler.END
    except Exception as exc:
        # Do not expose Bot API URLs or token-bearing exceptions.
        await update.message.reply_text('Upload failed. Check file type and size, then try again. '+(str(exc) if isinstance(exc,ValueError) else ''))
        return FILE

async def cancel(update,context):
    if not await allowed(update):return ConversationHandler.END
    context.user_data.pop('admin_action',None)
    await update.message.reply_text('Cancelled. Select ADMIN to return.')
    return ConversationHandler.END

def handler():
    entry=[MessageHandler(filters.Regex('^(?:'+'|'.join(re.escape(k) for k in MENU)+')$'),menu_choice),CommandHandler('admin',open_admin),MessageHandler(filters.Regex('^ADMIN$'),open_admin),CallbackQueryHandler(callback,pattern=r'^a:')]
    return ConversationHandler(entry_points=entry,states={INPUT:[MessageHandler(filters.TEXT & ~filters.COMMAND,text_input)],FILE:[MessageHandler(~filters.COMMAND,file_input)]},fallbacks=[CommandHandler('cancel',cancel)],allow_reentry=True)
