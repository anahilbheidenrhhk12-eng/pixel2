"""Two-factor authentication is now mandatory for login: no "NONE" bypass.
Covers the validation helper and the login_totp step of the flow."""
import tempfile
import unittest
from unittest.mock import MagicMock, AsyncMock

import admin_store
import main


class TotpSecretValidationTests(unittest.TestCase):
    def test_rejects_none(self):
        self.assertFalse(main._looks_like_totp_secret('NONE'))
        self.assertFalse(main._looks_like_totp_secret('none'))

    def test_rejects_empty_and_garbage(self):
        self.assertFalse(main._looks_like_totp_secret(''))
        self.assertFalse(main._looks_like_totp_secret('short'))
        self.assertFalse(main._looks_like_totp_secret('123456'))  # a 6-digit code, not a secret

    def test_accepts_a_plausible_base32_secret(self):
        self.assertTrue(main._looks_like_totp_secret('JBSWY3DPEHPK3PXP'))  # 16 chars
        self.assertTrue(main._looks_like_totp_secret('jbsw y3dp ehpk 3pxp'))  # lowercase + spaces
        self.assertTrue(main._looks_like_totp_secret('JBSW-Y3DP-EHPK-3PXP-ABCD'))  # dashes, longer
        self.assertTrue(main._looks_like_totp_secret('JBSWY3DPEHPK3PXP===='))  # padding


class LoginTotpStepTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = admin_store.Store(self.tmp.name)
        import unittest.mock as mock
        self.patches = [mock.patch.object(main, 'STORE', self.store)]
        for p in self.patches:
            p.start()
        self.u = MagicMock()
        self.u.effective_user.id = 321
        self.u.effective_chat.id = 321
        self.u.effective_chat.type = 'private'
        self.u.message.reply_text = AsyncMock()
        self.u.message.delete = AsyncMock()
        self.u.effective_message = self.u.message
        self.u.effective_chat.send_message = AsyncMock()
        self.c = MagicMock()
        self.c.user_data = {'pending_email': 'x@example.com', 'pending_password': 'secret'}
        # Dispose of the check_offer(...) coroutine rather than letting it dangle unawaited.
        self.c.application.create_task = MagicMock(side_effect=lambda coro, **kw: coro.close())

    async def asyncTearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    async def test_none_is_rejected_and_stays_on_totp_step(self):
        self.u.message.text = 'NONE'
        result = await main.login_totp(self.u, self.c)
        self.assertEqual(result, main.AWAIT_TOTP)
        self.u.effective_chat.send_message.assert_called_once()
        self.assertIn('pending_email', self.c.user_data)  # not consumed — the attempt never started

    async def test_garbage_is_rejected_and_stays_on_totp_step(self):
        self.u.message.text = '123456'
        result = await main.login_totp(self.u, self.c)
        self.assertEqual(result, main.AWAIT_TOTP)

    async def test_valid_secret_is_accepted_and_starts_the_check(self):
        self.u.message.text = 'JBSWY3DPEHPK3PXP'
        result = await main.login_totp(self.u, self.c)
        self.assertEqual(result, main.ConversationHandler.END)
        self.c.application.create_task.assert_called_once()
        session = main._get_session(321)
        self.assertEqual(session['totp_secret'], 'JBSWY3DPEHPK3PXP')
        self.assertNotIn('pending_email', self.c.user_data)  # consumed into the session
