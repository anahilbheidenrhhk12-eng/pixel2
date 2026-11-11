"""Mini App authentication and session isolation checks (no Google login)."""
import asyncio
import hashlib
import hmac
import json
import pathlib
import sys
import time
import unittest
from urllib.parse import urlencode

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from remote_checkout import REGISTRY, CheckoutSession, checkout_ws
from telegram_miniapp import (
    verify_init_data, miniapp_page, miniapp_auth, miniapp_status, miniapp_end,
)

TOKEN = '12345:example_telegram_token_test'


def sign(user_id, timestamp=None, token=TOKEN):
    values = {
        'auth_date': str(int(time.time() if timestamp is None else timestamp)),
        'user': json.dumps({'id': user_id, 'first_name': 'Tester'}, separators=(',', ':')),
    }
    data = '\n'.join(f'{k}={v}' for k, v in sorted(values.items()))
    secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    values['hash'] = hmac.new(secret, data.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


class MiniAppTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import os
        self.old_token = os.environ.get('TELEGRAM_BOT_TOKEN')
        os.environ['TELEGRAM_BOT_TOKEN'] = TOKEN
        self.session = REGISTRY.create(99112)
        app = web.Application()
        app.router.add_get('/miniapp', miniapp_page)
        app.router.add_post('/miniapp-auth', miniapp_auth)
        app.router.add_get('/miniapp-status/{token}', miniapp_status)
        app.router.add_get('/checkout-ws/{token}', checkout_ws)
        app.router.add_post('/miniapp-end/{token}', miniapp_end)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        import os
        REGISTRY.discard(self.session)
        await self.client.close()
        if self.old_token is None:
            os.environ.pop('TELEGRAM_BOT_TOKEN', None)
        else:
            os.environ['TELEGRAM_BOT_TOKEN'] = self.old_token

    async def test_server_hmac(self):
        raw = sign(99112)
        self.assertEqual(verify_init_data(raw, TOKEN), 99112)
        self.assertIsNone(verify_init_data(raw.replace('99112', '99113'), TOKEN))
        self.assertIsNone(verify_init_data(sign(99112, time.time()-4000), TOKEN))
        self.assertIsNone(verify_init_data(sign(99112, time.time()+300), TOKEN))
        self.assertIsNone(verify_init_data(raw, 'different-token'))

    async def test_owner_only_and_cookie(self):
        bad = await self.client.post('/miniapp-auth', json={'initData': sign(99113)})
        self.assertEqual(bad.status, 404)
        anon = await self.client.get('/miniapp-status/' + self.session.token)
        self.assertEqual(anon.status, 403)
        early = await self.client.post('/miniapp-auth', json={'initData': sign(99112)})
        self.assertEqual(early.status, 403)
        self.session.ready = True
        self.session.interactive_enabled = True
        good = await self.client.post('/miniapp-auth', json={'initData': sign(99112)})
        self.assertEqual(good.status, 200)
        body = await good.json()
        self.assertEqual(body['token'], self.session.token)
        self.assertTrue(body['ready'])
        cookie = good.cookies['digipro_mini_auth']
        self.assertTrue(cookie['secure'])
        self.assertTrue(cookie['httponly'])
        header = {'Cookie': 'digipro_mini_auth=' + cookie.value}
        status = await self.client.get('/miniapp-status/' + self.session.token, headers=header)
        self.assertEqual(status.status, 200)
        self.assertTrue((await status.json())['interactive'])
        self.session.ready = True
        self.session.interactive_enabled = True
        status = await self.client.get('/miniapp-status/' + self.session.token, headers=header)
        self.assertTrue((await status.json())['interactive'])
        ws = await self.client.get('/checkout-ws/' + self.session.token)
        self.assertEqual(ws.status, 403)
        ended = await self.client.post('/miniapp-end/' + self.session.token, headers=header)
        self.assertEqual(ended.status, 200)
        self.assertIsNone(REGISTRY.for_chat(99112))

    async def test_final_browser_handshake_works(self):
        # RFB/noVNC requires client binary handshake frames even when
        # interactive controls are disabled by the Mini App.
        async def fake_vnc(reader, writer):
            try:
                payload = await asyncio.wait_for(reader.read(64), 2)
                writer.write(b'ACK:' + payload)
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(fake_vnc, '127.0.0.1', 0)
        self.session.vnc_port = server.sockets[0].getsockname()[1]
        self.session.ready = True
        self.session.interactive_enabled = True
        try:
            good = await self.client.post('/miniapp-auth', json={'initData': sign(99112)})
            cookie = good.cookies['digipro_mini_auth'].value
            async with self.client.ws_connect(
                '/checkout-ws/' + self.session.token,
                headers={'Cookie': 'digipro_mini_auth=' + cookie},
            ) as ws:
                await ws.send_bytes(b'RFB 003.008\n')
                received = await ws.receive(timeout=2)
                self.assertEqual(received.data, b'ACK:RFB 003.008\n')
        finally:
            server.close()
            await server.wait_closed()

    async def test_miniapp_page(self):
        response = await self.client.get('/miniapp')
        self.assertEqual(response.status, 200)
        html = await response.text()
        self.assertIn('telegram-web-app.js', html)
        self.assertIn('/novnc/core/rfb.js', html)
        self.assertIn('viewOnly', html)
        self.assertIn('miniapp-auth', html)
        self.assertEqual(response.headers['Cache-Control'], 'no-store, max-age=0')

    async def test_miniapp_page_respects_lang_query(self):
        html = await (await self.client.get('/miniapp')).text()
        self.assertIn('lang="en"', html)
        html_ar = await (await self.client.get('/miniapp?lang=ar')).text()
        self.assertIn('lang="ar"', html_ar)
        self.assertIn('dir="rtl"', html_ar)
        html_bad = await (await self.client.get('/miniapp?lang=zz')).text()
        self.assertIn('lang="en"', html_bad)       # unknown language falls back safely

    async def test_auth_state_exposes_pinch_zoom_default(self):
        self.session.ready = True
        self.session.interactive_enabled = True
        res = await self.client.post('/miniapp-auth', json={'initData': sign(99112)})
        data = await res.json()
        self.assertIn('pinch_zoom', data)
        self.assertTrue(data['pinch_zoom'])        # admin default is ON


if __name__ == '__main__':
    unittest.main()
