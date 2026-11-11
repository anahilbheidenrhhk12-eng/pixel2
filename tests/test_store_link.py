import os
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import web
from aiohttp.test_utils import TestServer

import admin_store
import native_admin
import store_link

SECRET = 'unit-test-secret'


class FakeStore:
    """The store's side of the protocol: same signature, integer cents, idempotent refs."""
    def __init__(self):
        self.balances = {111: 1000, 222: 100}
        self.charges, self.refunds = {}, {}
        self.fail = False          # answer 503 (outcome unknown to the caller)
        self.calls = 0

    async def handle(self, request):
        self.calls += 1
        action = request.match_info['action']
        body = await request.json()
        uid, cents, ref = int(body['user_id']), int(body.get('amount_cents', 0)), body.get('ref', '')
        ts = request.headers.get('X-Digipro-Ts', '')
        want = store_link.sign(SECRET, ts, action, uid, cents if action != 'balance' else 0, ref if action != 'balance' else '')
        if request.headers.get('X-Digipro-Sign') != want or abs(time.time() - int(ts)) > 300:
            return web.json_response({'ok': False, 'reason': 'bad_signature'}, status=401)
        if self.fail:
            return web.json_response({'ok': False}, status=503)
        if action == 'balance':
            return web.json_response({'ok': True, 'exists': uid in self.balances, 'balance_cents': self.balances.get(uid, 0)})
        if uid not in self.balances:
            return web.json_response({'ok': False, 'reason': 'no_account'})
        if action == 'charge':
            if ref in self.charges:
                return web.json_response({'ok': True, 'duplicate': True, 'balance_cents': self.balances[uid]})
            if self.balances[uid] < cents:
                return web.json_response({'ok': False, 'reason': 'insufficient', 'balance_cents': self.balances[uid]})
            self.balances[uid] -= cents
            self.charges[ref] = (uid, cents)
            return web.json_response({'ok': True, 'balance_cents': self.balances[uid]})
        if action == 'refund':
            if ref not in self.charges:
                return web.json_response({'ok': False, 'reason': 'no_matching_charge'}, status=404)
            if ref not in self.refunds:
                self.refunds[ref] = True
                self.balances[uid] += cents
            return web.json_response({'ok': True, 'balance_cents': self.balances[uid]})
        return web.json_response({'ok': False}, status=404)


class StoreSetup(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = admin_store.Store(self.tmp.name)
        self.patches = [patch.object(store_link, 'STORE', self.store), patch.object(admin_store, 'STORE', self.store)]
        for p in self.patches:
            p.start()
        self.fake = FakeStore()
        app = web.Application()
        app.router.add_post('/internal/digipro/{action}', self.fake.handle)
        self.server = TestServer(app)
        await self.server.start_server()
        self.env = patch.dict(os.environ, {'STORE_API_URL': str(self.server.make_url('')).rstrip('/'),
                                           'STORE_API_SECRET': SECRET, 'STORE_BOT_USERNAME': 'storebot'})
        self.env.start()
        store_link.init()
        self.store.save_settings({'price': '3.5'})
        patch.object(store_link.asyncio, 'sleep', AsyncMock()).start()

    async def asyncTearDown(self):
        patch.stopall()
        await self.server.close()
        self.tmp.cleanup()

    def codes(self):
        with self.store.db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM codes')]

    def update(self, uid=111, text='x', data=None):
        u = MagicMock()
        u.effective_user.id = uid
        u.effective_chat.type = 'private'
        u.effective_message.reply_text = AsyncMock()
        u.message = u.effective_message
        if data:
            u.callback_query.data = data
            u.callback_query.answer = AsyncMock()
        return u


class StoreLinkTests(StoreSetup):

    # ── price parsing / settings ─────────────────────────────────────────
    def test_price_is_validated_and_normalised_in_settings(self):
        self.assertEqual(self.store.settings()['price'], '3.50')
        for bad in ('abc', '0', '1.234', '501'):
            with self.assertRaises(ValueError):
                self.store.save_settings({'price': bad})
        self.assertEqual(self.store.settings()['price'], '3.50')       # a bad value changes nothing
        self.store.save_settings({'price': ''})
        self.assertIsNone(store_link.price_cents())

    def test_price_parsing(self):
        self.assertEqual(store_link.parse_price('12.5'), 1250)
        self.assertEqual(store_link.parse_price('$3,50'), 350)
        for bad in ('abc', '0', '-2', '1.234', '501', ''):
            with self.assertRaises(ValueError):
                store_link.parse_price(bad)

    # ── purchase ─────────────────────────────────────────────────────────
    async def test_purchase_charges_once_and_binds_codes_to_buyer(self):
        res = await store_link.purchase(111, 2)
        self.assertEqual(res['status'], 'issued')
        self.assertEqual(len(res['codes']), 2)
        self.assertEqual(self.fake.balances[111], 1000 - 700)
        rows = self.codes()
        self.assertEqual({r['owner'] for r in rows}, {111})
        self.assertEqual({r['state'] for r in rows}, {'bound'})
        self.assertTrue(all(len(r['code']) == 12 for r in rows))
        # the buyer can use it straight away, nobody else can
        self.assertEqual(self.store.claim(rows[0]['code'], 111), rows[0]['code'])
        with self.assertRaises(ValueError):
            self.store.claim(rows[1]['code'], 999)

    async def test_insufficient_balance_charges_and_issues_nothing(self):
        res = await store_link.purchase(222, 1)
        self.assertEqual((res['status'], res['balance_cents'], res['need_cents']), ('insufficient', 100, 350))
        self.assertEqual(self.fake.balances[222], 100)
        self.assertEqual(self.codes(), [])

    async def test_no_account(self):
        self.assertEqual((await store_link.purchase(999, 1))['status'], 'no_account')

    async def test_wrong_secret_is_rejected_and_nothing_is_issued(self):
        with patch.dict(os.environ, {'STORE_API_SECRET': 'other'}):
            res = await store_link.purchase(111, 1)
        self.assertEqual(res['status'], 'error')
        self.assertEqual(self.fake.balances[111], 1000)
        self.assertEqual(self.codes(), [])

    async def test_unconfigured_store_link(self):
        with patch.dict(os.environ, {'STORE_API_SECRET': ''}):
            self.assertFalse(store_link.configured())
            self.assertEqual((await store_link.purchase(111, 1))['status'], 'unavailable')

    async def test_issue_failure_refunds_the_wallet(self):
        with patch.object(store_link, '_issue', side_effect=RuntimeError('disk full')):
            res = await store_link.purchase(111, 1)
        self.assertEqual(res['status'], 'error')
        self.assertEqual(self.fake.balances[111], 1000)           # money is back
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT status FROM purchases').fetchone()[0], 'refunded')

    # ── network failure: never lose money, never charge twice ────────────
    async def test_unreachable_store_leaves_pending_then_reconcile_delivers_once(self):
        self.fake.fail = True
        res = await store_link.purchase(111, 1)
        self.assertEqual(res['status'], 'pending')
        self.assertEqual(self.codes(), [])
        self.fake.fail = False
        bot = MagicMock(); bot.send_message = AsyncMock()
        with self.store.db() as db:
            db.execute('UPDATE purchases SET created=?', (time.time() - 200,))
        await store_link.reconcile_once(bot)
        await store_link.reconcile_once(bot)                       # a second pass must not do anything
        self.assertEqual(len(self.codes()), 1)
        self.assertEqual(self.fake.balances[111], 1000 - 350)      # charged exactly once
        bot.send_message.assert_awaited_once()
        self.assertIn(self.codes()[0]['code'], bot.send_message.call_args.kwargs['text'])

    async def test_charge_that_succeeded_but_reply_was_lost_is_not_charged_again(self):
        ref = 'dp_lostreply_0001'
        await store_link._call('charge', 111, 350, ref, 'x')      # store charged, we "never saw" the answer
        with self.store.db() as db:
            db.execute("INSERT INTO purchases(ref,owner,plan_id,title,qty,cents,status,created,updated) VALUES (?,?,?,?,?,?,'pending',?,?)",
                       (ref, 111, 1, 'x', 1, 350, time.time() - 200, time.time() - 200))
        await store_link.reconcile_once(None)
        self.assertEqual(self.fake.balances[111], 650)             # still only one charge
        self.assertEqual(len(self.codes()), 1)

    async def test_old_pending_purchase_is_refunded_not_charged_late(self):
        ref = 'dp_oldpending_0001'
        await store_link._call('charge', 111, 350, ref, 'x')
        with self.store.db() as db:
            db.execute("INSERT INTO purchases(ref,owner,plan_id,title,qty,cents,status,created,updated) VALUES (?,?,?,?,?,?,'pending',?,?)",
                       (ref, 111, 1, 'x', 1, 350, time.time() - 5000, time.time() - 5000))
        await store_link.reconcile_once(None)
        self.assertEqual(self.fake.balances[111], 1000)            # handed back
        self.assertEqual(self.codes(), [])

    async def test_no_price_means_not_on_sale_and_bad_quantity_is_refused(self):
        self.assertEqual((await store_link.purchase(111, 99))['status'], 'error')
        self.assertEqual(self.fake.calls, 0)
        self.store.save_settings({'price': ''})
        self.assertEqual((await store_link.purchase(111, 1))['status'], 'disabled')
        self.assertEqual(self.fake.calls, 0)

    # ── screens ──────────────────────────────────────────────────────────
    async def test_buy_menu_shows_the_fixed_price_and_quantities(self):
        u = self.update()
        await store_link.buy_menu(u, MagicMock())
        call = u.effective_message.reply_text.call_args
        self.assertIn('$3.50 per code', call.args[0])
        self.assertIn('$10.00', call.args[0])                        # wallet balance of user 111
        labels = [b.text for row in call.kwargs['reply_markup'].inline_keyboard for b in row]
        self.assertEqual(labels[:4], ['Buy 1 — $3.50', 'Buy 2 — $7.00', 'Buy 3 — $10.50', 'Buy 5 — $17.50'])
        self.assertTrue(any('Top up' in l for l in labels))

    async def test_buy_callback_full_flow_and_double_tap_guard(self):
        u = self.update(data='b:y:1')
        await store_link.buy_callback(u, MagicMock())
        self.assertIn('PURCHASE COMPLETE', u.effective_message.reply_text.call_args.args[0])
        self.assertEqual(len(self.codes()), 1)
        store_link._BUYING.add(111)
        u2 = self.update(data='b:y:1')
        await store_link.buy_callback(u2, MagicMock())
        store_link._BUYING.discard(111)
        self.assertEqual(len(self.codes()), 1)                       # second tap did nothing

    async def test_insufficient_shows_topup_button(self):
        u = self.update(uid=222, data='b:y:1')
        await store_link.buy_callback(u, MagicMock())
        msg = u.effective_message.reply_text.call_args
        self.assertIn('Not enough balance', msg.args[0])
        urls = [b.url for row in msg.kwargs['reply_markup'].inline_keyboard for b in row if getattr(b, 'url', None)]
        self.assertEqual(urls, ['https://t.me/storebot?start=wallet'])

    async def test_wallet_lines_show_store_balance_and_history(self):
        await store_link.purchase(111, 1)
        lines = '\n'.join(await store_link.wallet_lines(111))
        self.assertIn('$6.50', lines)
        self.assertIn('issued', lines)

    # ── admin ────────────────────────────────────────────────────────────
class InstructionsTests(unittest.IsolatedAsyncioTestCase):
    """The instructions are shown BEFORE the code step, on every LOGIN."""
    async def asyncSetUp(self):
        import main
        self.main = main
        self.tmp = tempfile.TemporaryDirectory()
        self.store = admin_store.Store(self.tmp.name)
        self.patches = [patch.object(main, 'STORE', self.store), patch.object(admin_store, 'STORE', self.store)]
        for p in self.patches:
            p.start()
        self.u = MagicMock()
        self.u.effective_user.id = 123
        self.u.effective_chat.id = 123
        self.u.effective_chat.type = 'private'
        self.u.message.text = 'LOGIN'
        self.u.message.reply_text = AsyncMock()
        self.c = MagicMock()
        self.c.user_data = {}

    async def asyncTearDown(self):
        patch.stopall()
        self.tmp.cleanup()

    async def test_without_instructions_login_goes_straight_to_the_code(self):
        await self.main.begin_login(self.u, self.c)
        self.assertEqual(self.c.user_data['phase'], self.main.AWAIT_KEY)
        self.assertIn('STEP 1 OF 5', self.u.message.reply_text.call_args.args[0])

    async def test_instructions_come_first_then_the_button_continues(self):
        self.store.save_settings({'instructions': 'Read this.\n1. Have your phone ready.'})
        await self.main.begin_login(self.u, self.c)
        call = self.u.message.reply_text.call_args
        self.assertIn('📘 INSTRUCTIONS', call.args[0])
        self.assertIn('Have your phone ready', call.args[0])
        self.assertNotIn('parse_mode', call.kwargs)                       # plain text: nothing can break
        self.assertIsNone(self.c.user_data.get('phase'))                   # not asking for the code yet
        self.assertEqual(call.kwargs['reply_markup'].inline_keyboard[0][0].callback_data, 'i:go')
        # typing a code now must NOT skip the instructions
        self.u.message.text = 'ABCDEFGHJKLM'
        await self.main.text_router(self.u, self.c)
        self.assertNotIn('STEP 2', self.u.message.reply_text.call_args.args[0])
        # tapping Continue moves to step 1
        q = MagicMock(); q.answer = AsyncMock(); q.edit_message_reply_markup = AsyncMock(); q.message.reply_text = AsyncMock()
        upd = MagicMock(); upd.callback_query = q; upd.effective_user.id = 123; upd.effective_chat.type = 'private'
        await self.main.instructions_continue(upd, self.c)
        self.assertEqual(self.c.user_data['phase'], self.main.AWAIT_KEY)
        self.assertIn('STEP 1 OF 5', q.message.reply_text.call_args.args[0])

    async def test_maintenance_still_wins_over_instructions(self):
        self.store.save_settings({'instructions': 'x', 'maintenance': True})
        await self.main.begin_login(self.u, self.c)
        self.assertIn('Maintenance', self.u.message.reply_text.call_args.args[0])

    async def test_admin_can_edit_and_clear_instructions_in_settings(self):
        import native_admin
        self.assertIn('instructions', native_admin.LABELS)
        self.assertIn('price', native_admin.LABELS)
        self.store.save_settings({'instructions': 'abc'})
        self.assertEqual(self.store.settings()['instructions'], 'abc')
        with self.assertRaises(ValueError):
            self.store.save_settings({'instructions': 'x' * 3501})
        self.store.save_settings({'instructions': ''})
        self.assertEqual(self.store.settings()['instructions'], '')


class ChannelGateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import join_gate
        self.gate = join_gate
        self.gate._MEMBER_UNTIL.clear()
        self.gate._WARNED.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.store = admin_store.Store(self.tmp.name)
        self.patches = [patch.object(join_gate, 'STORE', self.store), patch.object(admin_store, 'STORE', self.store)]
        for p in self.patches:
            p.start()
        self.store.save_settings({'channel': '@mychannel'})
        self.ctx = MagicMock()
        self.ctx.bot.send_message = AsyncMock()

    async def asyncTearDown(self):
        patch.stopall()
        self.tmp.cleanup()

    def upd(self, uid=5, data=None, chat='private'):
        u = MagicMock()
        u.effective_user.id = uid
        u.effective_chat.type = chat
        u.effective_chat.id = uid
        if data:
            u.callback_query.data = data
            u.callback_query.answer = AsyncMock()
            u.callback_query.edit_message_reply_markup = AsyncMock()
        else:
            u.callback_query = None
        return u

    def status(self, st, is_member=True):
        m = MagicMock(); m.status = st; m.is_member = is_member
        self.ctx.bot.get_chat_member = AsyncMock(return_value=m)

    async def test_non_member_is_blocked_with_join_and_continue_buttons(self):
        from telegram.ext import ApplicationHandlerStop
        self.status('left')
        with self.assertRaises(ApplicationHandlerStop):
            await self.gate.gate(self.upd(), self.ctx)
        kw = self.ctx.bot.send_message.call_args.kwargs
        self.assertIn('JOIN OUR CHANNEL', kw['text'])
        buttons = [b for row in kw['reply_markup'].inline_keyboard for b in row]
        self.assertEqual(buttons[0].url, 'https://t.me/mychannel')
        self.assertEqual(buttons[1].callback_data, 'j:ok')

    async def test_kicked_is_blocked_member_admin_and_restricted_member_pass(self):
        from telegram.ext import ApplicationHandlerStop
        self.status('kicked')
        with self.assertRaises(ApplicationHandlerStop):
            await self.gate.gate(self.upd(), self.ctx)
        for st, flag in (('member', True), ('administrator', True), ('creator', True), ('restricted', True)):
            self.gate._MEMBER_UNTIL.clear()
            self.status(st, flag)
            await self.gate.gate(self.upd(), self.ctx)               # no exception = allowed
        self.gate._MEMBER_UNTIL.clear()
        self.status('restricted', False)
        with self.assertRaises(ApplicationHandlerStop):
            await self.gate.gate(self.upd(), self.ctx)

    async def test_gate_off_admin_group_chat_and_unknown_answer_all_let_through(self):
        self.status('left')
        self.store.save_settings({'channel': ''})
        await self.gate.gate(self.upd(), self.ctx)                    # gate off
        self.store.save_settings({'channel': '@mychannel'})
        with patch.dict(os.environ, {'ADMIN_TELEGRAM_IDS': '5'}):
            await self.gate.gate(self.upd(5), self.ctx)               # admin
        await self.gate.gate(self.upd(chat='group'), self.ctx)        # not a private chat
        self.ctx.bot.get_chat_member = AsyncMock(side_effect=RuntimeError('Chat not found'))
        await self.gate.gate(self.upd(), self.ctx)                    # cannot check → fail open
        self.ctx.bot.send_message.assert_not_awaited()

    async def test_membership_is_cached(self):
        self.status('member')
        await self.gate.gate(self.upd(), self.ctx)
        await self.gate.gate(self.upd(), self.ctx)
        self.assertEqual(self.ctx.bot.get_chat_member.await_count, 1)

    async def test_continue_button_waits_until_really_joined(self):
        self.status('left')
        after = AsyncMock()
        u = self.upd(data='j:ok')
        await self.gate.continue_button(u, self.ctx, after)
        after.assert_not_awaited()
        self.assertTrue(u.callback_query.answer.call_args.kwargs.get('show_alert'))
        self.status('member')
        u2 = self.upd(data='j:ok')
        await self.gate.continue_button(u2, self.ctx, after)
        after.assert_awaited_once()

    async def test_join_button_button_press_is_not_blocked_by_the_gate_itself(self):
        self.status('left')
        await self.gate.gate(self.upd(data='j:ok'), self.ctx)         # must not raise

    def test_channel_settings_are_validated(self):
        for bad in ('mychannel', '@ab', 'https://t.me/x', '-100'):
            with self.assertRaises(ValueError):
                self.store.save_settings({'channel': bad})
        self.store.save_settings({'channel': '-1001234567890'})
        with self.assertRaises(ValueError):
            self.store.save_settings({'channel_link': 'http://evil.example/x'})
        self.store.save_settings({'channel_link': 'https://t.me/+AbCdEf123'})
        self.assertEqual(self.gate.join_url(self.store.settings()), 'https://t.me/+AbCdEf123')

    async def test_private_channel_without_link_shows_no_join_url_but_still_continue(self):
        self.store.save_settings({'channel': '-1001234567890'})
        markup = self.gate.prompt_markup(self.store.settings())
        self.assertEqual([b.callback_data for row in markup.inline_keyboard for b in row], ['j:ok'])


class TopupGuideTests(StoreSetup):
    """Smooth top-up: instructions + one tap to finish the same purchase afterwards."""
    async def test_insufficient_gives_guide_missing_amount_and_resume_button(self):
        u = self.update(uid=222, data='b:y:2')
        await store_link.buy_callback(u, MagicMock())
        msg = u.effective_message.reply_text.call_args
        self.assertIn('you are $6.00 short', msg.args[0])
        self.assertIn('HOW TO ADD BALANCE', msg.args[0])
        self.assertIn('Top up wallet', msg.args[0])                   # default guide text
        buttons = [b for row in msg.kwargs['reply_markup'].inline_keyboard for b in row]
        self.assertEqual(buttons[0].url, 'https://t.me/storebot?start=wallet')
        self.assertEqual(buttons[1].callback_data, 'b:y:2')           # same quantity resumes the purchase
        # the customer tops up, taps the button, and the SAME purchase goes through
        self.fake.balances[222] = 1000
        u2 = self.update(uid=222, data=buttons[1].callback_data)
        await store_link.buy_callback(u2, MagicMock())
        self.assertIn('PURCHASE COMPLETE', u2.effective_message.reply_text.call_args.args[0])
        self.assertEqual(self.fake.balances[222], 1000 - 700)

    async def test_admin_wording_replaces_the_default_guide(self):
        self.store.save_settings({'topup_instructions': 'Send USDT to the store bot, then come back.'})
        u = self.update(uid=222, data='b:y:1')
        await store_link.buy_callback(u, MagicMock())
        text = u.effective_message.reply_text.call_args.args[0]
        self.assertIn('Send USDT to the store bot', text)
        self.assertNotIn('Tap "Top up wallet" below', text)
        with self.assertRaises(ValueError):
            self.store.save_settings({'topup_instructions': 'x' * 1501})

    async def test_how_to_add_balance_screen_from_buy_and_wallet(self):
        u = self.update(data='b:h')
        await store_link.buy_callback(u, MagicMock())
        call = u.effective_message.reply_text.call_args
        self.assertIn('HOW TO ADD BALANCE', call.args[0])
        labels = [b.text for row in call.kwargs['reply_markup'].inline_keyboard for b in row]
        self.assertIn('💰 Top up wallet', labels)
        self.assertIn('🛒 Back to BUY', labels)
        m = self.update()
        await store_link.buy_menu(m, MagicMock())
        menu_buttons = [b.callback_data for row in m.effective_message.reply_text.call_args.kwargs['reply_markup'].inline_keyboard for b in row]
        self.assertIn('b:h', menu_buttons)


if __name__ == '__main__':
    unittest.main()
