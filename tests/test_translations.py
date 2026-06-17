"""
Тесты целостности словарей переводов.

Цель — не дать языкам разъехаться: если в один язык добавили ключ, а в другой
забыли, UI начнёт показывать английский fallback (или KeyError при self.t[key]).
Тест ловит это до рантайма.
"""

import unittest

from src.data.translations import TRANSLATIONS


class TranslationsParityTests(unittest.TestCase):
    def test_languages_present(self):
        self.assertIn("ru", TRANSLATIONS)
        self.assertIn("en", TRANSLATIONS)

    def test_ru_en_key_parity(self):
        ru = set(TRANSLATIONS["ru"])
        en = set(TRANSLATIONS["en"])
        only_ru = ru - en
        only_en = en - ru
        self.assertEqual(
            only_ru, set(),
            f"Ключи есть только в 'ru', нет в 'en': {sorted(only_ru)}",
        )
        self.assertEqual(
            only_en, set(),
            f"Ключи есть только в 'en', нет в 'ru': {sorted(only_en)}",
        )

    def test_no_empty_values(self):
        for lang, mapping in TRANSLATIONS.items():
            for key, value in mapping.items():
                self.assertIsInstance(value, str, f"{lang}['{key}'] не строка")
                self.assertTrue(value.strip(), f"{lang}['{key}'] пустая строка")

    def test_tab_keys_exist(self):
        # Регрессия: вкладки раньше держались на fallback в .get() — ключей не было,
        # и русская вкладка оружия показывалась как "Weapons".
        for key in ("tab_weapons", "tab_hats"):
            self.assertIn(key, TRANSLATIONS["ru"])
            self.assertIn(key, TRANSLATIONS["en"])


if __name__ == "__main__":
    unittest.main()
