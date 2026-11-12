import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import native_google_one_probe as native


def fake_adb(*args, **kwargs):
    if args == ('devices',):
        return 0, 'List of devices attached\nemulator-5554\tdevice\n', ''
    if args[:3] == ('shell', 'monkey', '-p'):
        return 0, 'Events injected: 1', ''
    return 0, '', ''


class NativeGoogleOneTest(unittest.TestCase):
    def common(self, has_account=True, has_app=True):
        def is_installed(package):
            if package == native.GOOGLE_ONE:
                return has_app
            return True
        return (
            patch.object(native, 'adb', side_effect=fake_adb),
            patch.object(native, 'getprop', side_effect=lambda name: '17' if 'release' in name else 'sdk_gphone'),
            patch.object(native, 'package_installed', side_effect=is_installed),
            patch.object(native, 'android_google_account_present', return_value=has_account),
            patch.object(native.time, 'sleep', return_value=None),
        )

    def test_not_logged_in_reports_required(self):
        with tempfile.TemporaryDirectory() as folder:
            p = self.common(has_account=False)
            with p[0], p[1], p[2], p[3], p[4]:
                result = native.main(['--result-dir', folder])
            self.assertEqual(result['outcome'], 'requires_android_google_login')
            self.assertFalse(result['android_account_present'])
            self.assertTrue((Path(folder) / 'report.json').exists())

    def test_logged_in_android_account_opens_google_one(self):
        with tempfile.TemporaryDirectory() as folder:
            p = self.common(has_account=True)
            with p[0], p[1], p[2], p[3], p[4], patch.object(native, 'tap_text', return_value=(True, 'ok')):
                result = native.main(['--result-dir', folder])
            self.assertTrue(result['launch_ok'])
            self.assertTrue(result['settings_found'])
            self.assertTrue(result['check_for_offers_found'])
            self.assertEqual(result['outcome'], 'offer_check_screen_opened')

    def test_interactive_account_login_proceeds_to_native_app(self):
        with tempfile.TemporaryDirectory() as folder:
            p = self.common(has_account=False)
            with p[0], p[1], p[2], p[3], p[4], \
                 patch.object(native, 'open_account_login', return_value=(True, 'opened')), \
                 patch.object(native, 'wait_for_account', return_value=True), \
                 patch.object(native, 'tap_text', return_value=(False, 'not visible')):
                result = native.main(['--interactive', '--wait-seconds', '10', '--result-dir', folder])
            self.assertTrue(result['android_account_present'])
            self.assertEqual(result['outcome'], 'google_one_opened_with_android_account')


if __name__ == '__main__':
    unittest.main()
