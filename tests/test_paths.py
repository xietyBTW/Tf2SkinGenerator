"""
Разделение папки установки и папки данных.

Смысл разделения — обновление: оно заменяет папку установки целиком, и всё,
что человек сделал, обязано лежать в другом месте. Проверяем обе стороны: в
разработке ничего не изменилось, в собранном приложении данные ушли в
%LOCALAPPDATA%, а старые данные переезжают туда один раз и не затирают новые.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.shared import paths


class DevModeTest(unittest.TestCase):
    """Из репозитория пути обязаны остаться прежними — иначе поедут тесты."""

    def test_both_roots_are_the_current_folder(self):
        with patch.object(paths, "is_frozen", return_value=False):
            self.assertEqual(paths.data_dir() / "cache", Path("cache"))
            self.assertEqual(paths.data_dir() / "work", Path("work"))
            self.assertEqual(paths.install_dir() / "tools/VTF",
                             Path("tools/VTF"))


class FrozenModeTest(unittest.TestCase):
    def test_data_goes_to_localappdata(self):
        with patch.object(paths, "is_frozen", return_value=True):
            with patch.dict("os.environ", {"LOCALAPPDATA": r"C:\Users\x\AppData\Local"}):
                self.assertEqual(
                    paths.data_dir(),
                    Path(r"C:\Users\x\AppData\Local") / paths.APP_DIR_NAME)

    def test_without_localappdata_falls_back_to_install_dir(self):
        """Урезанное окружение не повод падать — ведём себя как раньше."""
        with patch.object(paths, "is_frozen", return_value=True):
            with patch.object(paths, "install_dir", return_value=Path(r"C:\App")):
                with patch.dict("os.environ", {}, clear=True):
                    self.assertEqual(paths.data_dir(), Path(r"C:\App"))


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.install = Path(self._tmp.name) / "install"
        self.data = Path(self._tmp.name) / "data"
        self.install.mkdir()
        self.data.mkdir()

    def _migrate(self):
        with patch.object(paths, "is_frozen", return_value=True):
            with patch.object(paths, "install_dir", return_value=self.install):
                with patch.object(paths, "data_dir", return_value=self.data):
                    paths.migrate_legacy_data()

    def test_old_data_moves_once(self):
        (self.install / "work").mkdir()
        (self.install / "work" / "item.json").write_text("моя работа", encoding="utf-8")
        self._migrate()
        self.assertFalse((self.install / "work").exists())
        self.assertEqual((self.data / "work" / "item.json").read_text(encoding="utf-8"),
                         "моя работа")

    def test_existing_data_is_never_overwritten(self):
        """Второй запуск не должен затирать то, что человек уже наработал."""
        (self.install / "config").mkdir()
        (self.install / "config" / "app_config.json").write_text("старое", encoding="utf-8")
        (self.data / "config").mkdir()
        (self.data / "config" / "app_config.json").write_text("новое", encoding="utf-8")
        self._migrate()
        self.assertEqual(
            (self.data / "config" / "app_config.json").read_text(encoding="utf-8"),
            "новое")

    def test_nothing_to_move_is_fine(self):
        self._migrate()
        self.assertEqual(list(self.data.iterdir()), [])

    def test_dev_mode_moves_nothing(self):
        (self.install / "work").mkdir()
        with patch.object(paths, "is_frozen", return_value=False):
            paths.migrate_legacy_data()
        self.assertTrue((self.install / "work").exists())


if __name__ == "__main__":
    unittest.main()
