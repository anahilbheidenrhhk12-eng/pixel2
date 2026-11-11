"""Failure-reason reporting: STORE persistence, admin notification, and the
Reports screen showing WHY an activation attempt failed."""
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import admin_store
import main
import native_admin as a
from google_automation import GoogleAutomationError
from remote_checkout import CheckoutRegistry, CheckoutSession


class AdminIdsTests(unittest.TestCase):
    def test_parses_comma_separated_ids(self):
        with patch.dict(os.environ, {'ADMIN_TELEGRAM_IDS': '111, -100222, abc, '}):
            self.assertEqual(admin_store.admin_ids(), [111, -100222])

    def test_empty_when_unset(self):
        with patch.dict(os.environ, {'ADMIN_TELEGRAM_IDS': ''}):
            self.assertEqual(admin_store.admin_ids(), [])


class FailureReasonTests(unittest.TestCase):
    def test_uses_the_errors_own_message_when_specific(self):
        exc = GoogleAutomationError('Session cancelled or code revoked')
        self.assertEqual(main.failure_reason(exc, []), 'Session cancelled or code revoked')

    def test_falls_back_to_last_concrete_step_for_the_generic_message(self):
        exc = GoogleAutomationError('Google sign-in did not complete. Check the last screenshot; a timeout does not prove incorrect credentials.')
        recent = [
            '🔒 Step 3/6 — Entering password…',
            '❌ Step 5/6 — Sign-in error: Wrong password. Try again.',
            '⚠️ Last browser screen before stopping (GoogleAutomationError)',
        ]
        self.assertEqual(main.failure_reason(exc, recent), '❌ Step 5/6 — Sign-in error: Wrong password. Try again.')

    def test_falls_back_to_exception_type_when_nothing_else_available(self):
        self.assertEqual(main.failure_reason(RuntimeError('boom'), []), 'boom')
        self.assertEqual(main.failure_reason(RuntimeError(), []), 'RuntimeError')

    def test_truncated_to_250_chars(self):
        exc = GoogleAutomationError('x' * 400)
        self.assertEqual(len(main.failure_reason(exc, [])), 250)


class StoreFailReasonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = admin_store.Store(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_finish_persists_the_reason(self):
        key = self.store.generate(1)[0]
        self.store.claim(key, 1)
        self.store.begin(key, 1, 'op1', 'x@example.com')
        self.store.finish('op1', 'failed', 'Sign-in error: Wrong password')
        row = self.store.snapshot()['operations'][0]
        self.assertEqual(row['status'], 'failed')
        self.assertEqual(row['fail_reason'], 'Sign-in error: Wrong password')

    def test_recover_records_a_reason_too(self):
        key = self.store.generate(1)[0]
        self.store.claim(key, 1)
        self.store.begin(key, 1, 'op2', 'x@example.com')
        self.store.recover()
        row = self.store.snapshot()['operations'][0]
        self.assertEqual(row['status'], 'interrupted')
        self.assertIn('restarted', row['fail_reason'])


class DiscardWithReasonTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = admin_store.Store(self.tmp.name)
        self.patches = [patch('remote_checkout.STORE', self.store)]
        for p in self.patches:
            p.start()
        key = self.store.generate(1)[0]
        self.store.claim(key, 1)
        self.store.begin(key, 1, 'tok1', 'x@example.com')

    async def asyncTearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    async def test_explicit_status_and_reason_override_the_default(self):
        registry = CheckoutRegistry()
        session = CheckoutSession(chat_id=1, token='tok1')
        registry.by_chat[1] = session
        registry.by_token['tok1'] = session
        registry.discard(session, 'failed', 'Timeout during login')
        row = self.store.snapshot()['operations'][0]
        self.assertEqual(row['status'], 'failed')
        self.assertEqual(row['fail_reason'], 'Timeout during login')


class ReportsShowReasonTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = admin_store.Store(self.tmp.name)
        self.patches = [patch.object(a, 'STORE', self.store)]
        for p in self.patches:
            p.start()
        self.u = MagicMock()
        self.u.callback_query = None
        self.u.message.reply_text = AsyncMock()
        self.u.effective_message = self.u.message

    async def asyncTearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    async def test_failed_operation_shows_its_reason(self):
        key = self.store.generate(1)[0]
        self.store.claim(key, 1)
        self.store.begin(key, 1, 'tok1', 'x@example.com')
        self.store.finish('tok1', 'failed', '❌ Step 5/6 — Sign-in error: Wrong password.')
        items = self.store.snapshot()['operations']
        await a.report_page(self.u, items)
        text = self.u.message.reply_text.call_args.args[0]
        self.assertIn('Wrong password', text)

    async def test_successful_operation_does_not_show_a_reason_line(self):
        key = self.store.generate(1)[0]
        self.store.claim(key, 1)
        self.store.begin(key, 1, 'tok1', 'x@example.com')
        self.store.finish('tok1', 'closed')
        items = self.store.snapshot()['operations']
        await a.report_page(self.u, items)
        text = self.u.message.reply_text.call_args.args[0]
        self.assertNotIn('⚠️ Reason', text)
