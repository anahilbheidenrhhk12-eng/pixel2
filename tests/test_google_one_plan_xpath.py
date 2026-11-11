"""The existing test_google_one_plan.py fakes find_elements() by checking
whether a substring appears in the xpath string — it proves the click/URL
control flow but never actually proves the XPath syntax matches real HTML.
That gap is exactly how "Annual billing button not found" started firing for
every customer: Google restyled the control to read "Annual ($199.99)" and
the exact-text-only selector (normalize-space(.)='Annual') stopped matching
anything. These tests run the real XPath expressions (via lxml, which
implements the same XPath 1.0 Selenium/browsers use) against small HTML
fixtures shaped like the old and the new Google layouts."""
import unittest

import pytest

lxml_html = pytest.importorskip('lxml.html', reason='lxml is a test-only dependency (pip install lxml); not required to run the bot')

import google_one_plan as plan


def matches(xpaths, fragment):
    """Elements matched by ANY of the xpaths, deduplicated. Several of the
    alternatives in a tuple are deliberately overlapping fallbacks for the
    same real element (that's the point — _find_visible just needs any one
    of them to hit), so counting raw per-expression hits would be the wrong
    thing to assert on."""
    tree = lxml_html.fromstring(fragment)
    seen, found = set(), []
    for expr in xpaths:
        for el in tree.xpath(expr):
            if id(el) not in seen:
                seen.add(id(el))
                found.append(el)
    return found


class AnnualControlXpathTests(unittest.TestCase):
    def test_matches_the_old_bare_label(self):
        found = matches(plan.ANNUAL_CONTROL_XPATHS, '''
            <div>
              <button role="tab">Monthly</button>
              <button role="tab">Annual</button>
            </div>''')
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].text, 'Annual')

    def test_matches_the_new_price_suffixed_label(self):
        found = matches(plan.ANNUAL_CONTROL_XPATHS, '''
            <div>
              <button role="tab">Monthly ($19.99)</button>
              <button role="tab">Annual ($199.99)</button>
            </div>''')
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].text, 'Annual ($199.99)')

    def test_matches_via_aria_label_with_price_suffix(self):
        found = matches(plan.ANNUAL_CONTROL_XPATHS, '''
            <div>
              <div role="radio" aria-label="Annual ($199.99 per year)">Yearly</div>
            </div>''')
        self.assertEqual(len(found), 1)

    def test_does_not_match_unrelated_prose(self):
        found = matches(plan.ANNUAL_CONTROL_XPATHS, '''
            <div>
              <p>Annual review of your storage usage.</p>
              <span>Annually billed services may vary.</span>
            </div>''')
        self.assertEqual(found, [])  # neither is a button/tab/radio-like control

    def test_does_not_match_monthly(self):
        found = matches(plan.ANNUAL_CONTROL_XPATHS, '<button role="tab">Monthly</button>')
        self.assertEqual(found, [])


class ProButtonXpathTests(unittest.TestCase):
    def test_matches_get_google_ai_pro(self):
        found = matches(plan.PRO_BUTTON_XPATHS, '<button>Get Google AI Pro</button>')
        self.assertEqual(len(found), 1)

    def test_matches_the_shortened_get_pro_label(self):
        found = matches(plan.PRO_BUTTON_XPATHS, '''
            <div class="card">
              <h3>Google AI Pro</h3>
              <button>Get Pro</button>
            </div>''')
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].text, 'Get Pro')

    def test_does_not_match_other_plan_buttons(self):
        found = matches(plan.PRO_BUTTON_XPATHS, '''
            <div>
              <button>Get Plus</button>
              <button>Get Ultra</button>
            </div>''')
        self.assertEqual(found, [])


class AnnualSelectionTextSignalTests(unittest.TestCase):
    """_annual_selection_visible's fallback text scan — now also accepts
    'annually'/'a year' phrasing, not only '/yr'-style suffixes."""

    class FakeElement:
        def __init__(self, text):
            self.text = text

        def find_element(self, by, xpath):
            return self

    def test_accepts_annually_phrasing(self):
        card = self.FakeElement('Google AI Pro 5 TB $199.99 billed annually')
        self.assertTrue(plan._annual_selection_visible(
            annual_control=type('A', (), {'get_attribute': lambda self, name: None})(),
            pro_button=card,
        ))

    def test_still_rejects_plus_or_ultra_cards(self):
        card = self.FakeElement('Google AI Plus 200 GB $7.99/yr')
        self.assertFalse(plan._annual_selection_visible(
            annual_control=type('A', (), {'get_attribute': lambda self, name: None})(),
            pro_button=card,
        ))


if __name__ == '__main__':
    unittest.main()
