import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from session_progress import SessionProgress
import google_automation as ga

class ProgressTests(unittest.IsolatedAsyncioTestCase):
    async def test_stage_order_and_privacy(self):
        p=SessionProgress(AsyncMock(),None)
        p.report('📧 Step 2/6 — Entering email: private@example.com')
        self.assertEqual(p.stage,1)
        self.assertNotIn('private@example.com',p.render())
        p.report('🔐 Step 4/6 — verification')
        p.report('📧 Step 2/6 — old message')
        self.assertEqual(p.stage,3)
        p.report('✅ Annual billing selected.')
        self.assertEqual(p.stage,5)
        self.assertIn('Stage 6 of 6',p.render())
    async def test_finish_stops_background_edits(self):
        message=AsyncMock();p=SessionProgress(message,None)
        p.start()
        await p.finish('ready')
        self.assertTrue(p.task.done())
        self.assertTrue(p.finished)
        self.assertIn('YOUR BROWSER IS READY',message.edit_text.call_args.args[0])
        self.assertEqual(message.edit_text.call_args.args[0].count('✅'),7)
    async def test_disabled_screenshots_not_captured(self):
        cb=MagicMock();cb.capture_screenshots=False
        with patch.object(ga,'_shot') as shot:
            ga._report(cb,'Status',MagicMock())
        shot.assert_not_called()
        cb.assert_called_once_with('Status',None)
    async def test_navigation_restores_waits_on_error(self):
        driver=MagicMock()
        with patch.object(ga,'open_annual_ai_pro_checkout',side_effect=RuntimeError('test')):
            with self.assertRaises(RuntimeError):ga._navigate_google_one(driver)
        self.assertEqual(driver.implicitly_wait.call_args_list[0].args,(0,))
        self.assertEqual(driver.implicitly_wait.call_args_list[-1].args,(ga.config.IMPLICIT_WAIT,))
