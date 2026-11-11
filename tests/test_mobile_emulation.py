"""_build_driver used to build a bare desktop Chrome and ignore the
DeviceProfile it was handed entirely (the comment literally said "Do not
inject a Pixel or Android device fingerprint"). The user asked to bring back
mobile emulation — real Android Chrome UA/client-hints and the Pixel 11 Pro
navigator/WebGL/battery fingerprint from device_simulator.py — because the
desktop automation felt heavier and less reliable. These tests drive the
real _build_driver() with the real selenium Options object, but fake out the
actual Chrome process (no real browser launch needed to prove the wiring)."""
import json
import shutil
import subprocess
import unittest
from unittest.mock import MagicMock, patch

import config
import device_simulator as ds
import google_automation as ga


def build_with_fake_chrome(profile):
    fake_driver = MagicMock()
    with patch.object(ga, '_find_executable', return_value='/usr/bin/fake-binary'), \
         patch.object(ga.webdriver, 'Chrome', return_value=fake_driver) as fake_chrome_cls, \
         patch.object(ga, 'Service', return_value=MagicMock()):
        driver = ga._build_driver(profile)
    return driver, fake_chrome_cls


class MobileEmulationWiringTests(unittest.TestCase):
    def setUp(self):
        self.profile = ds.create_device_profile()

    def test_window_size_matches_the_profiles_css_viewport_not_desktop(self):
        driver, fake_chrome_cls = build_with_fake_chrome(self.profile)
        options = fake_chrome_cls.call_args.kwargs['options']
        self.assertIn(
            f'--window-size={config.SCREEN_CSS_WIDTH},{config.SCREEN_CSS_HEIGHT}',
            options.arguments,
        )
        self.assertNotIn('--window-size=1280,900', options.arguments)

    def test_device_metrics_override_reports_a_mobile_viewport(self):
        driver, _ = build_with_fake_chrome(self.profile)
        calls = {c.args[0]: c.args[1] for c in driver.execute_cdp_cmd.call_args_list}
        self.assertIn('Emulation.setDeviceMetricsOverride', calls)
        metrics = calls['Emulation.setDeviceMetricsOverride']
        self.assertEqual(metrics['width'], config.SCREEN_CSS_WIDTH)
        self.assertEqual(metrics['height'], config.SCREEN_CSS_HEIGHT)
        self.assertEqual(metrics['deviceScaleFactor'], config.SCREEN_PIXEL_RATIO)
        self.assertTrue(metrics['mobile'])

    def test_touch_emulation_is_enabled(self):
        driver, _ = build_with_fake_chrome(self.profile)
        calls = {c.args[0]: c.args[1] for c in driver.execute_cdp_cmd.call_args_list}
        self.assertTrue(calls['Emulation.setTouchEmulationEnabled']['enabled'])
        self.assertEqual(calls['Emulation.setTouchEmulationEnabled']['maxTouchPoints'], config.DEVICE_MAX_TOUCH)

    def test_locale_timezone_and_geolocation_are_overridden(self):
        """A reference implementation that DOES get its exact model
        recognized by Google also sets these alongside UA/client-hints
        spoofing — an Android session with no locale/timezone/geo signal at
        all is itself an inconsistency."""
        driver, _ = build_with_fake_chrome(self.profile)
        calls = {c.args[0]: c.args[1] for c in driver.execute_cdp_cmd.call_args_list}
        self.assertEqual(calls['Emulation.setLocaleOverride']['locale'], config.DEVICE_LOCALE)
        self.assertEqual(calls['Emulation.setTimezoneOverride']['timezoneId'], config.EMULATION_TIMEZONE_ID)
        geo = calls['Emulation.setGeolocationOverride']
        self.assertEqual(geo['latitude'], config.EMULATION_GEO_LATITUDE)
        self.assertEqual(geo['longitude'], config.EMULATION_GEO_LONGITUDE)
        self.assertEqual(geo['accuracy'], config.EMULATION_GEO_ACCURACY)

    def test_a_broken_locale_override_does_not_block_timezone_and_geo(self):
        """Some Chrome/Chromium builds reject Emulation.setLocaleOverride —
        that alone must not skip the timezone/geolocation calls after it."""
        fake_driver = MagicMock()

        def cdp_side_effect(cmd, params):
            if cmd == 'Emulation.setLocaleOverride':
                raise Exception('not supported on this build')
            return MagicMock()

        fake_driver.execute_cdp_cmd.side_effect = cdp_side_effect
        with patch.object(ga, '_find_executable', return_value='/usr/bin/fake-binary'), \
             patch.object(ga.webdriver, 'Chrome', return_value=fake_driver), \
             patch.object(ga, 'Service', return_value=MagicMock()):
            ga._build_driver(self.profile)
        calls = [c.args[0] for c in fake_driver.execute_cdp_cmd.call_args_list]
        self.assertIn('Emulation.setTimezoneOverride', calls)
        self.assertIn('Emulation.setGeolocationOverride', calls)
        self.assertIn('Page.addScriptToEvaluateOnNewDocument', calls)

    def test_webrtc_and_geolocation_prefs_avoid_ip_leaks_and_permission_prompts(self):
        driver, fake_chrome_cls = build_with_fake_chrome(self.profile)
        options = fake_chrome_cls.call_args.kwargs['options']
        prefs = options.experimental_options['prefs']
        self.assertEqual(prefs['webrtc.ip_handling_policy'], 'disable_non_proxied_udp')
        self.assertEqual(prefs['profile.default_content_setting_values.geolocation'], 2)

    def test_user_agent_and_client_hints_report_pixel_11_pro(self):
        driver, _ = build_with_fake_chrome(self.profile)
        calls = {c.args[0]: c.args[1] for c in driver.execute_cdp_cmd.call_args_list}
        ua_call = calls['Network.setUserAgentOverride']
        self.assertEqual(ua_call['userAgent'], self.profile.user_agent)
        self.assertEqual(ua_call['userAgentMetadata']['model'], 'Pixel 11 Pro')
        self.assertTrue(ua_call['userAgentMetadata']['mobile'])

    def test_user_agent_is_also_set_as_a_launch_flag(self):
        """Matches a working reference implementation: the UA is set as a
        Chrome launch flag, not only via CDP after the browser has already
        started — this is one of the two concrete differences found (the
        other being the explicit Sec-CH-UA-* headers below) between our
        setup and one a real screenshot showed Google recognizing as the
        exact model."""
        driver, fake_chrome_cls = build_with_fake_chrome(self.profile)
        options = fake_chrome_cls.call_args.kwargs['options']
        self.assertIn(f'--user-agent={self.profile.user_agent}', options.arguments)

    def test_extra_http_headers_carry_sec_ch_ua_model_on_every_request(self):
        """Network.setUserAgentOverride's userAgentMetadata alone only makes
        Chrome send Sec-CH-UA-* headers once the server opts in via
        Accept-CH — the first request to a new origin can go out without
        them. Setting Network.setExtraHTTPHeaders explicitly guarantees
        Google's server sees the real model from the very first request."""
        driver, _ = build_with_fake_chrome(self.profile)
        calls = {c.args[0]: c.args[1] for c in driver.execute_cdp_cmd.call_args_list}
        headers = calls['Network.setExtraHTTPHeaders']['headers']
        self.assertEqual(headers['Sec-CH-UA-Model'], '"Pixel 11 Pro"')
        self.assertEqual(headers['Sec-CH-UA-Mobile'], '?1')
        self.assertEqual(headers['Sec-CH-UA-Platform'], '"Android"')

    def test_fingerprint_script_is_injected_for_every_document(self):
        driver, _ = build_with_fake_chrome(self.profile)
        calls = {c.args[0]: c.args[1] for c in driver.execute_cdp_cmd.call_args_list}
        injected = calls['Page.addScriptToEvaluateOnNewDocument']['source']
        self.assertIn('navigator', injected)
        self.assertIn(str(config.DEVICE_MAX_TOUCH), injected)

    def test_a_cdp_failure_does_not_abort_the_whole_launch(self):
        """Fingerprint spoofing is a nice-to-have, not a requirement — a
        broken CDP call must never prevent an activation from proceeding."""
        fake_driver = MagicMock()
        fake_driver.execute_cdp_cmd.side_effect = Exception('devtools not ready')
        with patch.object(ga, '_find_executable', return_value='/usr/bin/fake-binary'), \
             patch.object(ga.webdriver, 'Chrome', return_value=fake_driver), \
             patch.object(ga, 'Service', return_value=MagicMock()):
            driver = ga._build_driver(self.profile)  # must not raise
        self.assertIs(driver, fake_driver)

    def test_build_driver_no_longer_checks_navigator_on_the_blank_startup_page(self):
        """navigator.userAgentData is only ever populated on a real https://
        document, never on the blank page Chrome starts on before any
        navigation — checking it here used to always report
        "no-high-entropy-api" regardless of whether the CDP spoofing above
        actually works, which is misleading. The real check now runs via
        _log_device_spoofing_self_check(), called from _gmail_login() right
        after the first real navigation (see DeviceSpoofingSelfCheckTests)."""
        driver, _ = build_with_fake_chrome(self.profile)
        driver.execute_script.assert_not_called()
        driver.execute_async_script.assert_not_called()


class DeviceSpoofingSelfCheckTests(unittest.TestCase):
    """_log_device_spoofing_self_check() is the real test — it must be called
    on an actual page (e.g. right after driver.get() to the Google sign-in
    URL), never on the blank pre-navigation page (see the test above)."""

    def test_logs_a_self_check_of_the_live_navigator_overrides(self):
        fake_driver = MagicMock()
        fake_driver.execute_script.return_value = '{"mobile":true,"platform":"Linux armv8l"}'
        with self.assertLogs(ga.logger, level='INFO') as logs:
            ga._log_device_spoofing_self_check(fake_driver)
        self.assertTrue(any('Device spoofing check' in m for m in logs.output))
        self.assertTrue(any('Linux armv8l' in m for m in logs.output))

    def test_logs_the_actual_high_entropy_model_value(self):
        """The device model is a high-entropy client hint a page only gets by
        calling getHighEntropyValues(['model']) — this is what that call
        would actually resolve to, i.e. the real test of whether "Pixel 11
        Pro" is reported correctly, versus what any particular Google screen
        happens to display."""
        fake_driver = MagicMock()
        fake_driver.execute_async_script.return_value = '{"model":"Pixel 11 Pro"}'
        with self.assertLogs(ga.logger, level='INFO') as logs:
            ga._log_device_spoofing_self_check(fake_driver)
        self.assertTrue(any('Pixel 11 Pro' in m for m in logs.output))

    def test_a_broken_diagnostic_check_does_not_raise(self):
        fake_driver = MagicMock()
        fake_driver.execute_script.side_effect = Exception('page not ready')
        fake_driver.execute_async_script.side_effect = Exception('page not ready')
        ga._log_device_spoofing_self_check(fake_driver)  # must not raise


class GmailLoginRunsTheSelfCheckOnTheRealPageTests(unittest.TestCase):
    """The whole point of moving the check out of _build_driver() is that it
    now runs against the real Google sign-in page, not the blank startup
    page. This drives _gmail_login() far enough (through the first
    driver.get()) to prove that wiring, using a fake driver with no email
    field so it fails fast right after — we only care that the self-check
    fired before that failure."""

    def test_gmail_login_checks_the_real_sign_in_page_after_navigating(self):
        fake_driver = MagicMock()
        fake_driver.find_element.side_effect = ga.NoSuchElementException('no field')
        with patch.object(ga, '_wait_for', side_effect=Exception('no email field in this fake')), \
             patch.object(ga, '_log_device_spoofing_self_check') as fake_check, \
             patch.object(ga.time, 'sleep'):
            try:
                ga._gmail_login(fake_driver, 'a@example.com', 'pw')
            except Exception:
                pass
        fake_driver.get.assert_called_once_with(config.GMAIL_LOGIN_URL)
        fake_check.assert_called_once_with(fake_driver)


class NavigatorJsHighEntropyModelHintTests(unittest.TestCase):
    """The real bug: a Railway log showed getHighEntropyValues(['model'])
    resolving to "no-high-entropy-api" because CDP's
    Network.setUserAgentOverride only asks Chrome to construct
    navigator.userAgentData itself, and that object simply wasn't there yet
    on the page checked. The fix (borrowed from a working reference
    implementation) is to define navigator.userAgentData directly in the
    injected script instead of depending on Chrome's own Client Hints
    plumbing. This test executes the ACTUAL injected JS in Node (same V8
    engine/Promise semantics as Chrome) against a bare fake
    navigator/screen/window, so it proves the real behaviour — not just that
    the string "Pixel 11 Pro" happens to appear somewhere in the source."""

    def test_get_high_entropy_values_resolves_the_real_model(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node is not installed in this environment')
        profile = ds.create_device_profile()
        harness = (
            "global.navigator = {}; global.screen = {}; global.window = global;\n"
            + profile.navigator_js()
            + "\nnavigator.userAgentData.getHighEntropyValues("
              "['model','platformVersion','architecture'])"
              ".then(v => console.log(JSON.stringify(v)))"
              ".catch(e => { console.error(e); process.exit(1); });"
        )
        result = subprocess.run(
            [node, '-e', harness], capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout.strip())
        self.assertEqual(value['model'], 'Pixel 11 Pro')
        self.assertEqual(value['platformVersion'], f'{config.ANDROID_VERSION}.0.0')


class DeviceProfileIdentityTests(unittest.TestCase):
    """The profile itself now reports Pixel 11 Pro / Tensor G6 / Chrome 157,
    with the same screen geometry as the Pixel 10 Pro (identical real panel:
    6.3", 1280x2856, ~495ppi — the CSS viewport doesn't need to change)."""

    def test_model_and_platform_fields(self):
        profile = ds.create_device_profile()
        self.assertEqual(profile.model, 'Pixel 11 Pro')
        self.assertEqual(profile.android_version, '17')
        self.assertEqual(profile.gpu_renderer, 'PowerVR CXTP-48-1536')
        self.assertEqual(profile.hardware_concurrency, 7)

    def test_screen_geometry_unchanged_from_pixel_10_pro(self):
        profile = ds.create_device_profile()
        self.assertEqual((profile.screen_width, profile.screen_height, profile.pixel_ratio),
                          (412, 915, 3.5))

    def test_chrome_version_is_157_with_a_randomized_patch(self):
        profile = ds.create_device_profile()
        self.assertTrue(profile.chrome_version.startswith('157.0.'))

    def test_imei_still_luhn_valid_with_a_real_known_pixel_tac(self):
        profile = ds.create_device_profile()
        self.assertEqual(len(profile.imei), 15)
        tac = profile.imei[:8]
        self.assertIn(tac, ds.PIXEL_TAC_PREFIXES)


class ClientHintsHeadersTests(unittest.TestCase):
    """client_hints_headers() formats the literal Sec-CH-UA-* request header
    values (quoted strings, comma-joined brand lists) that
    Network.setExtraHTTPHeaders sends on every request."""

    def test_model_header_is_quoted(self):
        profile = ds.create_device_profile()
        headers = profile.client_hints_headers()
        self.assertEqual(headers['Sec-CH-UA-Model'], '"Pixel 11 Pro"')

    def test_mobile_and_platform_headers(self):
        profile = ds.create_device_profile()
        headers = profile.client_hints_headers()
        self.assertEqual(headers['Sec-CH-UA-Mobile'], '?1')
        self.assertEqual(headers['Sec-CH-UA-Platform'], '"Android"')
        self.assertEqual(headers['Sec-CH-UA-Platform-Version'], '"17.0.0"')

    def test_brands_list_is_comma_joined_and_quoted(self):
        profile = ds.create_device_profile()
        headers = profile.client_hints_headers()
        self.assertIn('"Google Chrome";v="157"', headers['Sec-CH-UA'])
        self.assertIn('"Chromium";v="157"', headers['Sec-CH-UA'])

    def test_full_version_uses_the_actual_patch_version(self):
        profile = ds.create_device_profile()
        headers = profile.client_hints_headers()
        self.assertEqual(headers['Sec-CH-UA-Full-Version'], f'"{profile.chrome_version}"')
        self.assertIn(profile.chrome_version, headers['Sec-CH-UA-Full-Version-List'])


if __name__ == '__main__':
    unittest.main()
