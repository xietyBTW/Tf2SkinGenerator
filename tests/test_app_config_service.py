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

    def test_load_config_with_bom_keeps_settings(self):
        # Блокнот и PowerShell сохраняют с BOM — настройки не должны слетать.
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            config_file = config_dir / "app_config.json"
            config_dir.mkdir(parents=True, exist_ok=True)
            config_file.write_bytes(b"\xef\xbb\xbf" + json.dumps(
                {"tf2_game_folder": "D:/TF2", "language": "ru"}).encode("utf-8"))
            with patch.object(AppConfig, "CONFIG_DIR", config_dir):
                with patch.object(AppConfig, "CONFIG_FILE", config_file):
                    config = AppConfig.load_config()
            self.assertEqual(config["tf2_game_folder"], "D:/TF2")

    def test_broken_config_is_kept_before_it_gets_overwritten(self):
        # Первая же запись настроек положит на место нечитаемого файла
        # умолчания — путь к игре и прочее остаются только в копии.
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            config_file = config_dir / "app_config.json"
            config_dir.mkdir(parents=True, exist_ok=True)
            config_file.write_text('{"tf2_game_folder": "D:/TF2",', encoding="utf-8")
            with patch.object(AppConfig, "CONFIG_DIR", config_dir):
                with patch.object(AppConfig, "CONFIG_FILE", config_file):
                    AppConfig.load_config()
                    AppConfig.set("language", "en")
            broken = config_dir / "app_config.broken.json"
            self.assertIn("D:/TF2", broken.read_text(encoding="utf-8"))

    def test_locked_config_is_not_overwritten_with_defaults(self):
        # Файл держит антивирус: чтение не удалось, и запись настройки
        # положила бы на его место умолчания. Отпустили — всё как было.
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            config_file = config_dir / "app_config.json"
            config_dir.mkdir(parents=True, exist_ok=True)
            config_file.write_text(json.dumps({"tf2_game_folder": "D:/TF2"}), encoding="utf-8")
            AppConfig.invalidate_cache()
            with patch.object(AppConfig, "CONFIG_DIR", config_dir),                     patch.object(AppConfig, "CONFIG_FILE", config_file):
                with patch("builtins.open", side_effect=PermissionError("locked")),                         patch("time.sleep"):
                    self.assertFalse(AppConfig.set("language", "en"))
                self.assertEqual(AppConfig.get("tf2_game_folder"), "D:/TF2")
                self.assertTrue(AppConfig.set("language", "en"))
            data = json.loads(config_file.read_text(encoding="utf-8"))
            self.assertEqual(data, {**AppConfig.DEFAULT_CONFIG, "tf2_game_folder": "D:/TF2",
                                    "language": "en"})

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

    def test_parallel_set_keeps_every_key(self):
        """Потоки API пишут разные ключи разом — ни один не теряется."""
        import threading
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "config"
            config_file = config_dir / "app_config.json"
            with patch.object(AppConfig, "CONFIG_DIR", config_dir):
                with patch.object(AppConfig, "CONFIG_FILE", config_file):
                    AppConfig.save_config({})
                    threads = [threading.Thread(target=AppConfig.set, args=(f"k{i}", i))
                               for i in range(16)]
                    for t in threads:
                        t.start()
                    for t in threads:
                        t.join()
                    AppConfig.invalidate_cache()
                    cfg = AppConfig.load_config()
            self.assertEqual({k: cfg.get(k) for k in (f"k{i}" for i in range(16))},
                             {f"k{i}": i for i in range(16)})


if __name__ == "__main__":
    unittest.main()
