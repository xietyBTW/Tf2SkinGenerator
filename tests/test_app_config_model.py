import unittest
from unittest.mock import patch

from src.domain.models.app_config import AppConfig


class AppConfigModelTests(unittest.TestCase):
    def test_load_from_file(self):
        with patch("src.domain.models.app_config.AppConfigService.load_config", return_value={"language": "ru"}):
            config = AppConfig.load_from_file()
        self.assertEqual(config.language, "ru")

    def test_save_to_file(self):
        config = AppConfig(language="ru")
        with patch("src.domain.models.app_config.AppConfigService.save_config", return_value=True) as mock_save:
            result = config.save_to_file()
        self.assertTrue(result)
        mock_save.assert_called()

    def test_get_set(self):
        config = AppConfig(language="en")
        self.assertEqual(config.get("language"), "en")
        config.set("language", "ru")
        self.assertEqual(config.language, "ru")
        with self.assertRaises(AttributeError):
            config.set("missing", "x")


if __name__ == "__main__":
    unittest.main()
