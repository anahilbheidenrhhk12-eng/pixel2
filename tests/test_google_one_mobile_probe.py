import unittest
from unittest.mock import patch

from google_one_mobile_probe import inspect_google_one_mobile


class FakeDriver:
    def __init__(self, url="https://one.google.com/", text="Google One"):
        self.current_url = url
        self.text = text
        self.visits = []
    def get(self, url):
        self.visits.append(url)
    def execute_script(self, source):
        return self.text


class GoogleOneMobileTests(unittest.TestCase):
    @patch("google_one_mobile_probe.time.sleep")
    def test_google_one_loads_using_same_browser(self, _sleep):
        driver = FakeDriver(text="Google One Check for offers")
        messages = []
        result = inspect_google_one_mobile(driver, messages.append)
        self.assertEqual(driver.visits, ["https://one.google.com/"])
        self.assertFalse(result["native_application"])
        self.assertTrue(result["check_for_offers_visible"])
        self.assertTrue(any("mobile website loaded" in x for x in messages))

    @patch("google_one_mobile_probe.time.sleep")
    def test_signin_redirect_is_reported(self, _sleep):
        driver = FakeDriver("https://accounts.google.com/signin/v2/identifier", "Sign in")
        messages = []
        result = inspect_google_one_mobile(driver, messages.append)
        self.assertTrue(result["sign_in_required"])
        self.assertFalse(result["native_application"])
        self.assertTrue(any("sign-in" in x for x in messages))


if __name__ == "__main__":
    unittest.main()
