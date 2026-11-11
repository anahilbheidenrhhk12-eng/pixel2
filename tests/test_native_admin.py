import io
import json
import os
import tempfile
import unittest
import zipfile
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import native_admin as a
import admin_panel
from admin_store import Store

class NativeAdmin(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(self.tmp.name)
        self.env=patch.dict(os.environ,{'ADMIN_TELEGRAM_IDS':'777'});self.env.start()
        self.patches=[patch.object(a,'STORE',self.store),patch.object(admin_panel,'STORE',self.store)]
        for p in self.patches:p.start()
        self.u=MagicMock();self.u.effective_user.id=777;self.u.effective_chat.type='private';self.u.callback_query=None
        self.u.message.reply_text=AsyncMock();self.u.message.reply_document=AsyncMock();self.u.effective_message=self.u.message
        self.c=MagicMock();self.c.user_data={}
    async def asyncTearDown(self):
        for p in self.patches:p.stop()
        self.env.stop();self.tmp.cleanup()
    async def test_only_admin_gets_buttons(self):
        await a.open_admin(self.u,self.c)
        markup=self.u.message.reply_text.call_args.kwargs['reply_markup']
        self.assertTrue(markup.is_persistent)
        self.assertIn('🎟️ Generate Codes',[b.text for row in markup.keyboard for b in row])
        self.u.effective_user.id=123
        self.assertFalse(await a.allowed(self.u))
    async def test_codes_and_settings(self):
        self.c.user_data['admin_action']='generate';self.u.message.text='2'
        await a.text_input(self.u,self.c)
        self.assertEqual(len(self.store.snapshot()['codes']),2)
        self.u.message.reply_document.assert_awaited_once()
        self.c.user_data['admin_action']='set:max_sessions';self.u.message.text='4'
        await a.text_input(self.u,self.c);self.assertEqual(self.store.settings()['max_sessions'],4)
    async def test_zip_upload_in_chat(self):
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:z.writestr('manifest.json',json.dumps({'manifest_version':3,'name':'Test','version':'1.0'}))
        payload=out.getvalue();self.u.message.document=MagicMock(file_size=len(payload),file_name='test.zip',file_id='test')
        file=MagicMock();file.download_as_bytearray=AsyncMock(return_value=bytearray(payload));self.c.bot.get_file=AsyncMock(return_value=file)
        self.c.user_data['admin_action']='upload';await a.file_input(self.u,self.c)
        self.assertEqual(len(self.store.extensions()),1)
    async def test_nonadmin_cannot_upload(self):
        self.u.effective_user.id=123;self.c.bot.get_file=AsyncMock();self.c.user_data['admin_action']='upload'
        await a.file_input(self.u,self.c);self.c.bot.get_file.assert_not_awaited()
    async def test_oversize_rejected_before_download(self):
        self.u.message.document=MagicMock(file_size=21*1024*1024);self.c.bot.get_file=AsyncMock()
        self.assertEqual(await a.file_input(self.u,self.c),a.FILE);self.c.bot.get_file.assert_not_awaited()
    async def test_payment_not_available_before_final(self):
        import main
        self.u.effective_chat.id=777
        s=MagicMock(ready=True,interactive_enabled=False)
        with patch.object(main.REGISTRY,'for_chat',return_value=s):
            await main.payment_window(self.u,self.c)
            self.assertNotIn('reply_markup',self.u.message.reply_text.call_args.kwargs)
            rows=main._menu_keyboard(777).keyboard
            self.assertNotIn(main.MENU_PAYMENT,[b.text for row in rows for b in row])
    async def test_dashboard_no_longer_served(self):
        import aiohttp
        from remote_checkout import start_http
        with patch.dict(os.environ,{'PORT':'0'}):runner=await start_http()
        try:
            host,port=runner.addresses[0][:2]
            async with aiohttp.ClientSession() as client:
                for path in ('/admin','/admin-api/state','/admin-auth'):
                    async with client.get(f'http://127.0.0.1:{port}'+path) as r:self.assertEqual(r.status,404)
        finally:await runner.cleanup()
    async def test_explicit_extension_controls_are_idempotent(self):
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:
            z.writestr('manifest.json',json.dumps({'manifest_version':3,'name':'Test','version':'1.0'}))
        ident=admin_panel.install_extension(out.getvalue())
        await a.callback(self.u,self.c,'extset:'+ident+':0')
        await a.callback(self.u,self.c,'extset:'+ident+':0')
        self.assertEqual(self.store.extensions(),[])
        self.assertEqual(Store(self.tmp.name).extensions(),[])
        await a.callback(self.u,self.c,'extset:'+ident+':1')
        await a.callback(self.u,self.c,'extset:'+ident+':1')
        self.assertEqual(len(self.store.extensions()),1)
        self.assertEqual(len(Store(self.tmp.name).extensions()),1)
        markup=self.u.message.reply_text.call_args.kwargs['reply_markup']
        callbacks=[b.callback_data for row in markup.inline_keyboard for b in row]
        self.assertIn('a:extset:'+ident+':0',callbacks)
        self.assertIn('a:extset:'+ident+':1',callbacks)
        self.assertTrue(all(len(c.encode())<=64 for c in callbacks))
        # A button from an older Telegram message only opens the current panel.
        await a.callback(self.u,self.c,'ext:'+ident)
        self.assertEqual(len(self.store.extensions()),1)
    async def test_customer_cannot_change_extension_state(self):
        with self.store.db() as db:
            db.execute("INSERT INTO extensions VALUES ('test','Test','/missing',1)")
        self.u.effective_user.id=123
        await a.callback(self.u,self.c,'extset:test:0')
        self.assertEqual(self.store.extensions(),['/missing'])
    async def test_enable_missing_extension_is_rejected(self):
        with self.store.db() as db:
            db.execute("INSERT INTO extensions VALUES ('test','Test','/missing',0)")
        await a.callback(self.u,self.c,'extset:test:1')
        self.assertEqual(self.store.extensions(),[])
        self.assertIn('missing',self.u.message.reply_text.call_args.args[0])

    async def test_icon_admin_menu_routes(self):
        self.u.message.text='🧩 Extensions'
        await a.menu_choice(self.u,self.c)
        self.assertIn('CHROME EXTENSIONS',self.u.message.reply_text.call_args.args[0])

    async def test_pinch_zoom_setting_is_a_toggle_and_defaults_on(self):
        self.assertTrue(self.store.settings()['pinch_zoom'])
        self.assertIn('pinch_zoom',a.LABELS)
        await a.callback(self.u,self.c,'bool:pinch_zoom:0')
        self.assertFalse(self.store.settings()['pinch_zoom'])
        await a.callback(self.u,self.c,'bool:pinch_zoom:1')
        self.assertTrue(self.store.settings()['pinch_zoom'])
