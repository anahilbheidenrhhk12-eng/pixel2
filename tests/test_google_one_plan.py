"""Offline tests for the Google One Annual -> Google AI Pro navigation.
Run: python -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import google_one_plan as plan

LANDING = 'https://one.google.com/ai?hl=en-TN&g1_landing_page=75'
CHECKOUT = 'https://one.google.com/checkout/ai-pro-annual'


class Element:
    def __init__(self, owner, label, yearly=True):
        self.owner = owner
        self.label = label
        self.yearly = yearly

    def is_displayed(self): return True
    def is_enabled(self): return True
    def get_attribute(self, name):
        if name in ('aria-pressed', 'aria-selected', 'aria-checked') and self.label == 'Annual':
            return 'true' if self.owner.annual_selected else 'false'
        if name == 'href': return None
        return None

    def click(self):
        self.owner.clicked.append(self.label)
        if self.label == 'Annual':
            self.owner.annual_selected = self.yearly
        elif self.label == 'Get Google AI Pro' and self.owner.navigate_checkout:
            self.owner.current_url = CHECKOUT

    def find_element(self, by, xpath):
        if self.label != 'Get Google AI Pro':
            raise ValueError('Not a plan')
        price = 'US$149.99/yr for 1 year' if self.yearly else 'US$19.99/mo'
        return type('Card', (), {'text': 'Google AI Pro 5 TB ' + price + ' Get Google AI Pro'})()


class FakeDriver:
    def __init__(self, annual=True, pro=True, yearly=True, navigate_checkout=True):
        self.current_url = 'about:blank'
        self.window_handles = ['tab']
        self.switch_to = type('Tabs', (), {'window': lambda _, name: None})()
        self.clicked = []
        self.annual_selected = False
        self.annual = Element(self, 'Annual', yearly=yearly) if annual else None
        self.pro = Element(self, 'Get Google AI Pro', yearly=yearly) if pro else None
        self.navigate_checkout = navigate_checkout

    def get(self, url):
        self.current_url = url

    def find_elements(self, by, xpath):
        if 'Get Google AI Pro' in xpath:
            return [self.pro] if self.pro else []
        if 'Annual' in xpath:
            return [self.annual] if self.annual else []
        return []

    def execute_script(self, script, *args):
        if 'arguments[0].click();' in script:
            args[0].click()


class TestAnnualPlan(unittest.TestCase):
    def test_exact_annual_then_pro_click(self):
        driver = FakeDriver()
        events = []
        result = plan.open_annual_ai_pro_checkout(driver, LANDING, lambda msg, d: events.append(msg))
        self.assertEqual(result, CHECKOUT)
        self.assertEqual(driver.clicked, ['Annual', 'Get Google AI Pro'])
        self.assertTrue(any('Payment NOT confirmed' in msg for msg in events))

    def test_missing_annual_stops_before_checkout(self):
        driver = FakeDriver(annual=False)
        with patch.object(plan, '_find_visible', side_effect=[None]):
            result = plan.open_annual_ai_pro_checkout(driver, LANDING)
        self.assertIsNone(result)
        self.assertEqual(driver.clicked, [])

    def test_missing_pro_never_clicks_other_plan(self):
        driver = FakeDriver(pro=False)
        with patch.object(plan, '_find_visible', side_effect=[driver.annual, None]):
            result = plan.open_annual_ai_pro_checkout(driver, LANDING)
        self.assertIsNone(result)
        self.assertEqual(driver.clicked, ['Annual'])

    def test_monthly_pro_is_not_clicked(self):
        driver = FakeDriver(yearly=False)
        result = plan.open_annual_ai_pro_checkout(driver, LANDING)
        self.assertIsNone(result)
        self.assertEqual(driver.clicked, ['Annual'])

    def test_modal_checkout_has_no_invented_link(self):
        driver = FakeDriver(navigate_checkout=False)
        with patch.object(plan.time, 'monotonic', side_effect=[0, 0, 0, 1, 11, 11]):
            with patch.object(plan.time, 'sleep'):
                result = plan.open_annual_ai_pro_checkout(driver, LANDING)
        self.assertIsNone(result)
        self.assertEqual(driver.clicked, ['Annual', 'Get Google AI Pro'])

    def test_final_photo_only_after_pro_click(self):
        driver = FakeDriver()
        final_captures = []
        link = plan.open_annual_ai_pro_checkout(
            driver,
            LANDING,
            final_photo=lambda page: final_captures.append(tuple(page.clicked)),
        )
        self.assertEqual(link, CHECKOUT)
        self.assertEqual(final_captures, [('Annual', 'Get Google AI Pro')])
        self.assertEqual(driver.current_url, CHECKOUT)

    def test_no_final_photo_if_annual_plan_not_confirmed(self):
        driver = FakeDriver(yearly=False)
        final_captures = []
        link = plan.open_annual_ai_pro_checkout(
            driver, LANDING,
            final_photo=lambda page: final_captures.append(page.current_url),
        )
        self.assertIsNone(link)
        self.assertEqual(final_captures, [])
        self.assertEqual(driver.clicked, ['Annual'])

    def test_checkout_url_rejects_landing_and_non_google_sites(self):
        self.assertFalse(plan._checkout_url_usable(LANDING, LANDING))
        self.assertFalse(plan._checkout_url_usable('https://example.com/checkout', LANDING))
        self.assertTrue(plan._checkout_url_usable(CHECKOUT, LANDING))


if __name__ == '__main__':
    unittest.main()
