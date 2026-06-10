import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config.app_config import AppConfig


class AppConfigServiceTests(unittest.TestCase):
    def setUp(self):
        AppConfig.invalidate_cache()

    def tearDown(self):
        AppConfig.invalidate_cache()

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

    def test_cache_serves_repeated_reads(self):
        """Повторный load_config без изменения файла не должен читать диск."""
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            config_file = config_dir / "app_config.json"
            with patch.object(AppConfig, "CONFIG_DIR", config_dir):
                with patch.object(AppConfig, "CONFIG_FILE", config_file):
                    AppConfig.save_config({"language": "ru"})
                    first = AppConfig.load_config()
                    with patch("builtins.open", side_effect=AssertionError("диск читался")):
                        second = AppConfig.load_config()
            self.assertEqual(first["language"], "ru")
            self.assertEqual(second["language"], "ru")

    def test_mutating_result_does_not_pollute_defaults(self):
        """Мутация результата не должна менять DEFAULT_CONFIG или кэш."""
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            config_file = config_dir / "app_config.json"
            with patch.object(AppConfig, "CONFIG_DIR", config_dir):
                with patch.object(AppConfig, "CONFIG_FILE", config_file):
                    config = AppConfig.load_config()
                    config["last_flags"].append("MUTATED")
                    config["material_blacklist"].append("MUTATED")
                    fresh = AppConfig.load_config()
            self.assertEqual(AppConfig.DEFAULT_CONFIG["last_flags"], [])
            self.assertEqual(AppConfig.DEFAULT_CONFIG["material_blacklist"], [])
            self.assertNotIn("MUTATED", fresh["last_flags"])

    def test_external_file_change_invalidates_cache(self):
        """Изменение файла на диске (mtime) должно сбрасывать кэш."""
        import os
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            config_file = config_dir / "app_config.json"
            with patch.object(AppConfig, "CONFIG_DIR", config_dir):
                with patch.object(AppConfig, "CONFIG_FILE", config_file):
                    AppConfig.save_config({"language": "ru"})
                    AppConfig.load_config()
                    # Внешняя правка файла
                    config_file.write_text(
                        json.dumps({"language": "en"}), encoding="utf-8")
                    st = config_file.stat()
                    os.utime(config_file, (st.st_atime, st.st_mtime + 100))
                    self.assertEqual(AppConfig.get("language"), "en")

    def test_save_is_atomic_no_tmp_left(self):
        """После сохранения не должно оставаться временного файла."""
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            config_file = config_dir / "app_config.json"
            with patch.object(AppConfig, "CONFIG_DIR", config_dir):
                with patch.object(AppConfig, "CONFIG_FILE", config_file):
                    self.assertTrue(AppConfig.save_config({"language": "ru"}))
            leftovers = list(config_dir.glob("*.tmp"))
            self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
