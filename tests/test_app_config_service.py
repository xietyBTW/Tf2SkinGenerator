import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config.app_config import AppConfig


class AppConfigServiceTests(unittest.TestCase):
    def test_load_config_creates_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            config_file = config_dir / "app_config.json"
            with patch.object(AppConfig, "CONFIG_DIR", config_dir):
                with patch.object(AppConfig, "CONFIG_FILE", config_file):
                    config = AppConfig.load_config()
            self.assertTrue(config_file.exists())
            self.assertEqual(config["export_folder"], "export")

    def test_load_config_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            config_file = config_dir / "app_config.json"
            config_dir.mkdir(parents=True, exist_ok=True)
            config_file.write_text("{bad json", encoding="utf-8")
            with patch.object(AppConfig, "CONFIG_DIR", config_dir):
                with patch.object(AppConfig, "CONFIG_FILE", config_file):
                    config = AppConfig.load_config()
            self.assertEqual(config["export_folder"], "export")

    def test_save_and_get_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            config_file = config_dir / "app_config.json"
            with patch.object(AppConfig, "CONFIG_DIR", config_dir):
                with patch.object(AppConfig, "CONFIG_FILE", config_file):
                    self.assertTrue(AppConfig.save_config({"language": "ru"}))
                    self.assertEqual(AppConfig.get("language"), "ru")
                    AppConfig.set("tf2_game_folder", "C:/TF2")
            data = json.loads(config_file.read_text(encoding="utf-8"))
            self.assertEqual(data["tf2_game_folder"], "C:/TF2")

    def test_set_tf2_game_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            config_file = config_dir / "app_config.json"
            with patch.object(AppConfig, "CONFIG_DIR", config_dir):
                with patch.object(AppConfig, "CONFIG_FILE", config_file):
                    self.assertTrue(AppConfig.set_tf2_game_folder("C:/TF2"))
            data = json.loads(config_file.read_text(encoding="utf-8"))
            self.assertEqual(data["tf2_game_folder"], "C:/TF2")


if __name__ == "__main__":
    unittest.main()
