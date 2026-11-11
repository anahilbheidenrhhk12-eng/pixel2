import hashlib
import io
import tempfile
import unittest
from unittest.mock import MagicMock,AsyncMock,patch
import main
import customer_portal as portal
import admin_store
import google_automation as ga
from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer

class CustomerFlow(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=admin_store.Store(self.tmp.name)
        self.patches=[patch.object(main,'STORE',self.store),patch.object(portal,'STORE',self.store),patch.object(admin_store,'STORE',self.store)]
        for p in self.patches:p.start()
        portal.init()
        self.u=MagicMock();self.u.effective_user.id=123;self.u.effective_chat.id=123;self.u.effective_chat.type='private';self.u.message.reply_text=AsyncMock();self.u.message.delete=AsyncMock();self.u.effective_message=self.u.message
        self.c=MagicMock();self.c.user_data={};self.c.bot.set_chat_menu_button=AsyncMock();self.c.bot.send_message=AsyncMock()
    async def asyncTearDown(self):
        for p in self.patches:p.stop()
        self.tmp.cleanup()
    async def test_start_shows_language_picker_first_time(self):
        self.c.user_data={'phase':main.AWAIT_PASSWORD,'pending_email':'x','pending_password':'secret'}
        self.c.bot.set_chat_menu_button.side_effect=RuntimeError('temporary network failure')
        await main.start(self.u,self.c)
        kwargs=self.u.message.reply_text.call_args.kwargs
        self.assertIn('reply_markup',kwargs)      # the language picker, an inline keyboard
        self.assertNotIn('pending_password',self.c.user_data)

    async def test_start_plain_text_and_persistent_clean_menu(self):
        import i18n
        i18n.set_lang(123,'en')
        self.c.user_data={'phase':main.AWAIT_PASSWORD,'pending_email':'x','pending_password':'secret'}
        self.c.bot.set_chat_menu_button.side_effect=RuntimeError('temporary network failure')
        await main.start(self.u,self.c)
        kwargs=self.u.message.reply_text.call_args.kwargs
        self.assertNotIn('parse_mode',kwargs)
        menu=kwargs['reply_markup'];self.assertTrue(menu.is_persistent)
        self.assertEqual([b.text for row in menu.keyboard for b in row],[portal.BUTTONS[k] for k in ['LOGIN','BUY','WALLET','ORDER','SUPPORT','API','LANG']])
        self.assertNotIn('pending_password',self.c.user_data)
    async def test_code_only_routing_and_cancel(self):
        self.u.message.text='LOGIN';await main.text_router(self.u,self.c)
        self.assertEqual(self.c.user_data['phase'],main.AWAIT_KEY)
        key=self.store.generate(1)[0];self.assertEqual(len(key),12);self.assertNotIn('-',key)
        self.u.message.text=key;await main.text_router(self.u,self.c)
        self.assertEqual(self.c.user_data['phase'],main.AWAIT_EMAIL)
        self.u.message.text='not_an_email';await main.text_router(self.u,self.c)
        self.assertEqual(self.c.user_data['phase'],main.AWAIT_EMAIL)
        self.u.message.text='CANCEL';await main.text_router(self.u,self.c)
        self.assertNotIn('phase',self.c.user_data)
        self.assertEqual(self.store.claim(key,123),key)
    async def test_login_success_consumes_code_before_final_failure(self):
        key=self.store.generate(1)[0];self.store.claim(key,123);self.store.begin(key,123,'operation','x@example.com')
        remote=MagicMock(token='operation',closed=False,display=':1')
        with patch.object(ga,'_build_driver',return_value=MagicMock()),patch.object(ga,'_gmail_login',return_value=True),patch.object(ga,'_navigate_google_one',side_effect=RuntimeError('final stage failed')),patch.object(ga,'_report'):
            with self.assertRaises(RuntimeError):ga.check_gemini_offer('x@example.com','p',MagicMock(),remote_session=remote)
        with self.assertRaises(ValueError):self.store.claim(key,123)
    async def test_support_and_order_isolation(self):
        self.u.message.text='My session stopped';await portal.ticket(self.u,self.c)
        with self.store.db() as db:self.assertEqual(db.execute('SELECT owner FROM tickets').fetchone()[0],123)
        for owner in (123,456):
            key=self.store.generate(1)[0];self.store.claim(key,owner);self.store.begin(key,owner,str(owner),'')
        self.assertEqual(len(portal.orders(123)),1)
        self.assertEqual(portal.balance(123),1)
    async def test_api_is_owner_scoped_and_requires_key(self):
        app=web.Application();portal.register(app)
        with self.store.db() as db:db.execute('INSERT INTO api_keys VALUES (?,?)',(123,hashlib.sha256(b'secret').hexdigest()))
        key=self.store.generate(1)[0];self.store.claim(key,456);self.store.begin(key,456,'other','')
        client=TestClient(TestServer(app));await client.start_server()
        try:
            r=await client.get('/api/v1/orders');self.assertEqual(r.status,401)
            r=await client.get('/api/v1/orders',headers={'Authorization':'Bearer secret'});self.assertEqual((await r.json())['orders'],[])
        finally:await client.close()

    async def test_icon_login_and_cancel_routes(self):
        self.u.message.text='🔐 LOGIN'
        await main.text_router(self.u,self.c)
        self.assertEqual(self.c.user_data['phase'],main.AWAIT_KEY)
        self.u.message.text='❌ CANCEL'
        await main.text_router(self.u,self.c)
        self.assertNotIn('phase',self.c.user_data)

    async def test_admin_gets_a_screenshot_of_the_exact_failure(self):
        """A failed activation must notify the admin with the browser exactly
        as it stood at the moment of failure, not just the text of the error
        (requested after a real customer failure only showed a raw Selenium
        message with no visual to go with it).

        google_automation.py's real check_gemini_offer() ALWAYS quits the
        Chrome driver and clears remote_session.driver in its own `finally:`
        block before returning or re-raising — even on the exception path,
        where it reports one last screenshot via progress_callback just
        before that teardown. A fake here that raises without reproducing
        that teardown would hide the exact bug this test is guarding against:
        an earlier version of this admin-screenshot feature tried to grab a
        *fresh* screenshot straight from remote_session.driver after the
        fact, which is always too late by then and silently produced
        nothing. The fix is to reuse the screenshot the automation already
        took and relayed through progress_callback — so this fake must relay
        one and THEN tear the driver down, exactly like the real thing."""
        import os
        import remote_checkout as rc
        key=self.store.generate(1)[0];self.store.claim(key,123)
        session=main._get_session(123)
        session['access_key']=key;session['email']='x@example.com';session['password']='p';session['totp_secret']='JBSWY3DPEHPK3PXP'
        self.c.bot.send_message=AsyncMock(return_value=MagicMock(edit_text=AsyncMock()))
        self.c.bot.send_photo=AsyncMock()

        class FakeDriver:
            def get_screenshot_as_png(self):
                return b'FAKE-PNG-BYTES'

        def fake_check_gemini_offer(email,password,device,totp_secret=None,progress_callback=None,remote_session=None):
            remote_session.attach_driver(FakeDriver())
            exc=ga.GoogleAutomationError('Message: stale element reference: stale element not found')
            if progress_callback:
                progress_callback('⚠️ Last browser screen before stopping (GoogleAutomationError)',
                                   remote_session.driver.get_screenshot_as_png())
            # Reproduce check_gemini_offer's own `finally:` teardown, which
            # always runs — on every path, success or failure — before
            # control returns to main.check_offer.
            remote_session.driver=None
            remote_session.stop()
            raise exc

        with patch.object(rc,'STORE',self.store), \
             patch.object(main,'checkout_enabled',return_value=True), \
             patch.object(main,'check_gemini_offer',fake_check_gemini_offer), \
             patch.dict(os.environ,{'ADMIN_TELEGRAM_IDS':'999'}):
            await main.check_offer(self.u,self.c)

        # send_photo is also called once for the customer's own live progress
        # feed (chat_id=123, via photo_progress) — find the admin's call.
        admin_calls=[c for c in self.c.bot.send_photo.call_args_list if c.kwargs.get('chat_id')==999]
        self.assertEqual(len(admin_calls),1)
        kwargs=admin_calls[0].kwargs
        self.assertEqual(kwargs['photo'].getvalue(),b'FAKE-PNG-BYTES')
        self.assertIn('stale element',kwargs['caption'])

    async def test_soft_failure_also_gets_the_last_reported_screenshot(self):
        """Same guarantee for the "no exception, just never finished" path
        (e.g. 'Annual billing button not found' — open_annual_ai_pro_checkout
        returns None rather than raising). The automation's own finally:
        block tears the driver down here too, before main.check_offer ever
        sees it, so this must also come from the relayed screenshot, not a
        live grab."""
        import os
        import remote_checkout as rc
        key=self.store.generate(1)[0];self.store.claim(key,123)
        session=main._get_session(123)
        session['access_key']=key;session['email']='x@example.com';session['password']='p';session['totp_secret']='JBSWY3DPEHPK3PXP'
        self.c.bot.send_message=AsyncMock(return_value=MagicMock(edit_text=AsyncMock()))
        self.c.bot.send_photo=AsyncMock()

        class FakeDriver:
            def get_screenshot_as_png(self):
                return b'ANNUAL-BUTTON-MISSING-PNG'

        def fake_check_gemini_offer(email,password,device,totp_secret=None,progress_callback=None,remote_session=None):
            remote_session.attach_driver(FakeDriver())
            if progress_callback:
                progress_callback('❌ Annual billing button not found. Sign-in or page layout may have changed.',
                                   remote_session.driver.get_screenshot_as_png())
            remote_session.driver=None
            remote_session.stop()
            return None  # no exception — just never reached a usable offer link

        with patch.object(rc,'STORE',self.store), \
             patch.object(main,'checkout_enabled',return_value=True), \
             patch.object(main,'check_gemini_offer',fake_check_gemini_offer), \
             patch.dict(os.environ,{'ADMIN_TELEGRAM_IDS':'999'}):
            await main.check_offer(self.u,self.c)

        admin_calls=[c for c in self.c.bot.send_photo.call_args_list if c.kwargs.get('chat_id')==999]
        self.assertEqual(len(admin_calls),1)
        kwargs=admin_calls[0].kwargs
        self.assertEqual(kwargs['photo'].getvalue(),b'ANNUAL-BUTTON-MISSING-PNG')
        self.assertIn('Annual billing button not found',kwargs['caption'])
