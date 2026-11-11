import asyncio
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import admin_store
import admin_panel
import remote_checkout
import telegram_miniapp
from test_telegram_miniapp import sign, TOKEN

class Keys(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = admin_store.Store(self.tmp.name)
    def tearDown(self):
        self.tmp.cleanup()
    def test_racing_claim_has_one_owner(self):
        key = self.store.generate(1)[0]
        def claim(owner):
            try:
                self.store.claim(key, owner)
                return owner
            except ValueError:
                return None
        with ThreadPoolExecutor(8) as pool:
            winners = [v for v in pool.map(claim, range(1,9)) if v]
        self.assertEqual(len(winners), 1)
    def test_retry_consumption_revoke_and_restart(self):
        key = self.store.generate(1)[0]
        self.store.claim(key, 7)
        self.store.begin(key,7,'fail','test@example.com')
        self.store.finish('fail','incomplete')
        self.store.claim(key,7)  # no screen: key remains available to owner
        with self.assertRaises(ValueError):
            self.store.claim(key,8)
        self.store.begin(key,7,'retry','test@example.com')
        with self.assertRaises(ValueError):
            self.store.begin(key,7,'duplicate','')
        self.store.consume('retry')
        with self.assertRaises(ValueError):
            self.store.claim(key,7)
        self.store.recover()
        self.assertEqual(self.store.snapshot()['operations'][0]['status'],'interrupted')
        other = self.store.generate(1)[0]
        self.store.claim(other,8)
        self.store.begin(other,8,'revoked','')
        self.store.revoke(other)
        self.assertFalse(self.store.consume('revoked'))
    def test_settings_validation_and_persistence(self):
        self.store.save_settings({'max_sessions':3,'notes':'مرحبا','mode':'fast'})
        self.assertEqual(admin_store.Store(self.tmp.name).settings()['max_sessions'],3)
        for value in [{'max_sessions':0}, {'mode':'invalid'}, {'final_url':'javascript:alert(1)'}, {'close_on_activation':True}]:
            with self.assertRaises(ValueError):
                self.store.save_settings(value)
    def test_extension_traversal_and_enable(self):
        def archive(name):
            b=io.BytesIO()
            with zipfile.ZipFile(b,'w') as z:
                z.writestr('extension/manifest.json',json.dumps({'manifest_version':3,'name':'Test','version':'1'}))
                z.writestr(name,'test')
            return b.getvalue()
        with patch.object(admin_panel,'STORE',self.store):
            for name in ('../escape','/tmp/escape','extension/../../escape','..\\escape'):
                with self.assertRaises(ValueError):
                    admin_panel.install_extension(archive(name))
            admin_panel.install_extension(archive('extension/test.txt'))
        self.assertEqual(len(self.store.extensions()),1)
        self.assertTrue(Path(self.store.extensions()[0],'manifest.json').exists())
    def test_no_browser_expiry_and_capacity(self):
        registry=remote_checkout.CheckoutRegistry()
        self.store.save_settings({'max_sessions':1})
        with patch.object(remote_checkout,'STORE',self.store):
            s=registry.create(1)
            s.expires_at=0
            self.assertIs(registry.find(s.token),s)
            with self.assertRaises(RuntimeError):registry.create(2)
            registry.discard(s)
    def test_final_stage_does_not_consume_without_viewer(self):
        registry=remote_checkout.CheckoutRegistry()
        key=self.store.generate(1)[0];self.store.claim(key,7)
        s=remote_checkout.CheckoutSession(7,ready=True,interactive_enabled=True)
        s.driver=MagicMock();s.driver.current_url='https://example.com/done'
        self.store.begin(key,7,s.token,'')
        with patch.object(remote_checkout,'STORE',self.store):
            registry._final_stage(s)
            self.assertEqual(self.store.snapshot()['codes'][0]['state'],'bound')
            s.viewer_connected=True
            registry._final_stage(s)
            self.assertEqual(self.store.snapshot()['codes'][0]['state'],'used')
            self.store.save_settings({'close_on_activation':True,'completion_url':'https://example.com/done'})
            registry._final_stage(s)
            self.assertTrue(s.closed)
            self.assertEqual(self.store.snapshot()['operations'][0]['status'],'activation_detected')

class AdminAPI(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=admin_store.Store(self.tmp.name)
        self.patch=patch.object(admin_panel,'STORE',self.store);self.patch.start()
        self.env=patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':TOKEN,'ADMIN_TELEGRAM_IDS':'123'})
        self.env.start()
        app=web.Application();admin_panel.register(app)
        self.client=TestClient(TestServer(app));await self.client.start_server()
    async def asyncTearDown(self):
        await self.client.close();self.env.stop();self.patch.stop();self.tmp.cleanup()
    async def test_admin_auth_csrf_and_regular_user_denied(self):
        r=await self.client.get('/admin-api/state');self.assertEqual(r.status,401)
        r=await self.client.post('/admin-auth',json={'initData':sign(456)});self.assertEqual(r.status,403)
        r=await self.client.post('/admin-auth',json={'initData':sign(123)})
        self.assertEqual(r.status,200)
        csrf=(await r.json())['csrf'];cookie=r.cookies[admin_panel.COOKIE].value
        headers={'Cookie':admin_panel.COOKIE+'='+cookie}
        r=await self.client.post('/admin-api/generate',json={'count':1},headers=headers)
        self.assertEqual(r.status,403)
        headers['X-CSRF']=csrf
        r=await self.client.post('/admin-api/generate',json={'count':2},headers=headers)
        self.assertEqual(r.status,200);self.assertEqual(len((await r.json())['codes']),2)
        r=await self.client.get('/admin-api/state',headers=headers);self.assertEqual(r.status,200)
        r=await self.client.post('/admin-api/settings',json={'max_sessions':0},headers=headers);self.assertEqual(r.status,400)

class LoginGate(unittest.IsolatedAsyncioTestCase):
    async def test_plain_login_and_invalid_key_never_ask_password(self):
        import main
        with tempfile.TemporaryDirectory() as root:
            store=admin_store.Store(root)
            key=store.generate(1)[0]
            update=MagicMock();update.effective_chat.type='private';update.effective_chat.id=991
            update.effective_user.id=991;update.message.reply_text=AsyncMock()
            context=MagicMock()
            with patch.object(main,'STORE',store):
                update.message.text='LOGIN T=bad'
                self.assertEqual(await main.login_start(update,context),main.AWAIT_KEY)
                update.message.text='LOGIN T='+key
                self.assertEqual(await main.login_start(update,context),main.AWAIT_EMAIL)
                update.message.text='/login T='+key
                self.assertEqual(await main.login_start(update,context),main.AWAIT_EMAIL)
                update.effective_chat.type='group'
                self.assertEqual(await main.login_start(update,context),main.ConversationHandler.END)

if __name__=='__main__':unittest.main()
