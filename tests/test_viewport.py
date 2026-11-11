import unittest
from unittest.mock import MagicMock, patch
from remote_checkout import CheckoutSession

class ViewportTests(unittest.TestCase):
    def test_phone_fit_crops_stream_and_resizes_browser(self):
        s=CheckoutSession(chat_id=1,interactive_enabled=True,display=':90')
        s.driver=MagicMock()
        s.driver.execute_script.side_effect=[85,[500,900,815]]
        with patch('remote_checkout.subprocess.run') as run:
            result=s.fit_viewport(390,700)
        self.assertEqual(result,{'width':500,'height':767,'crop':48})
        rect=s.driver.set_window_rect.call_args.kwargs
        self.assertLessEqual(rect['width'],1280)
        self.assertLessEqual(rect['height'],1600)
        self.assertIn('clip:500x767+0+85',run.call_args.args[0])
    def test_closed_session_cannot_resize(self):
        s=CheckoutSession(chat_id=1,closed=True)
        with self.assertRaises(ValueError):s.fit_viewport(390,700)
    def test_desktop_fit(self):
        s=CheckoutSession(chat_id=1,interactive_enabled=True,display=':90')
        s.driver=MagicMock()
        s.driver.execute_script.side_effect=[85,[500,414,329]]
        with patch('remote_checkout.subprocess.run'):
            s.fit_viewport(1200,675)
        rect=s.driver.set_window_rect.call_args.kwargs
        # Landscape layout should not be turned into a tall mobile window.
        self.assertGreater(rect['width'],rect['height']-85-48)
