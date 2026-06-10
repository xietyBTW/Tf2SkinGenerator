import unittest

from src.shared.error_classifier import classify


class ErrorClassifierTests(unittest.TestCase):
    def test_tf2_path_not_specified_ru(self):
        title, desc = classify("Не указана папка TF2", language="ru")
        self.assertIn("TF2", title)
        self.assertIn("настройк", desc.lower())

    def test_tf2_path_not_specified_en(self):
        title, desc = classify("TF2 folder not specified", language="en")
        self.assertIn("TF2", title)
        self.assertIn("settings", desc.lower())

    def test_crowbar_missing(self):
        title, _ = classify("Crowbar CLI missing: tools/crowbar/x.exe", language="en")
        self.assertIn("Crowbar", title)

    def test_unknown_message_falls_back_ru(self):
        title, desc = classify("какая-то совершенно неизвестная ошибка xyz", language="ru")
        self.assertIn("непредвиденная", title.lower())
        self.assertTrue(desc)

    def test_unknown_message_falls_back_en(self):
        title, desc = classify("totally unknown error xyz", language="en")
        self.assertIn("unexpected", title.lower())
        self.assertTrue(desc)

    def test_model_work_error(self):
        title_ru, _ = classify("Ошибка при работе с моделью: details", language="ru")
        title_en, _ = classify("Error while working with model: details", language="en")
        self.assertIn("модели", title_ru.lower())
        self.assertIn("model", title_en.lower())

    def test_case_insensitive(self):
        a = classify("TF2 FOLDER NOT SPECIFIED", language="en")
        b = classify("tf2 folder not specified", language="en")
        self.assertEqual(a, b)

    def test_classify_returns_pair_of_strings(self):
        for msg in ["", "x", "Не указана папка TF2"]:
            result = classify(msg, language="ru")
            self.assertEqual(len(result), 2)
            self.assertTrue(all(isinstance(s, str) and s for s in result))


if __name__ == "__main__":
    unittest.main()
