import tempfile
import unittest
from unittest.mock import patch

import admin_store
import i18n
import customer_portal as portal


class I18nTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = admin_store.Store(self.tmp.name)
        self.patches = [patch.object(admin_store, 'STORE', self.store), patch.object(i18n, 'STORE', self.store)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_default_is_none_until_chosen(self):
        self.assertIsNone(i18n.get(555))
        self.assertEqual(i18n.resolve(555), 'en')

    def test_set_and_get_roundtrip(self):
        i18n.set_lang(555, 'ar')
        self.assertEqual(i18n.get(555), 'ar')
        self.assertEqual(i18n.resolve(555), 'ar')

    def test_rejects_unknown_language(self):
        with self.assertRaises(ValueError):
            i18n.set_lang(555, 'fr')

    def test_every_language_has_every_key_translated(self):
        for key, variants in i18n.T.items():
            for lang in i18n.LANGS:
                self.assertIn(lang, variants, f'{key} missing {lang}')
                value = variants[lang]
                if isinstance(value, tuple):
                    self.assertTrue(all(v.strip() for v in value), f'{key}/{lang} has an empty stage')
                else:
                    self.assertTrue(value.strip(), f'{key}/{lang} is empty')

    def test_rtl_only_for_arabic(self):
        self.assertTrue(i18n.is_rtl('ar'))
        for lang in ('en', 'vi', 'es'):
            self.assertFalse(i18n.is_rtl(lang))


class KeyboardLocalizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = admin_store.Store(self.tmp.name)
        self.patches = [patch.object(admin_store, 'STORE', self.store), patch.object(portal, 'STORE', self.store)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_keyboard_is_localized(self):
        kb = portal.keyboard(lang='ar')
        texts = [b.text for row in kb.keyboard for b in row]
        self.assertIn(i18n.t('btn_login', 'ar'), texts)
        self.assertIn(i18n.t('btn_lang', 'ar'), texts)

    def test_reverse_map_covers_every_language_label(self):
        rev = portal.reverse_map()
        for action, key in portal._ACTION_KEY.items():
            for lang in i18n.LANGS:
                label = i18n.t(key, lang).upper()
                self.assertEqual(rev[label], action)
