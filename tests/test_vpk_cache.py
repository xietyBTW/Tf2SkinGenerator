"""
Кэш открытых VPK: каталог разбирается один раз на запуск.

Разбор каталога игровых архивов (131 тысяча записей) стоит около полусекунды.
Пока кэш был потоко-локальным, он не переживал ни одной операции: каждый воркер
работает в своём QThread, так что за разбор платили при каждом переключении
оружия. Проверяем, что теперь объект переиспользуется и из чужого потока, а
обновление архива на диске кэш всё же замечает.
"""

import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.services import vpk_cache


class FakePak:
    """Дублёр vpk.VPK: каталог пуст до read_index (как у настоящего)."""

    opened = 0
    indexed = 0

    def __init__(self, path):
        self.path = path
        self.tree = None
        FakePak.opened += 1

    def read_index(self):
        self.tree = {"materials/x.vmt": ()}
        FakePak.indexed += 1


class VpkCacheTests(unittest.TestCase):

    def setUp(self):
        FakePak.opened = FakePak.indexed = 0
        vpk_cache.clear_vpk_cache()

    def _archive(self, base: Path) -> str:
        path = base / "tf2_misc_dir.vpk"
        path.write_bytes(b"header")
        return str(path)

    def test_index_is_built_once_and_survives_other_threads(self):
        with TemporaryDirectory() as tmp, \
             patch.object(vpk_cache, "_vpk") as fake_vpk:
            fake_vpk.open.side_effect = FakePak
            archive = self._archive(Path(tmp))

            first = vpk_cache.open_vpk_cached(archive)
            self.assertEqual(FakePak.indexed, 1, "каталог строится при открытии")

            from_thread = {}
            t = threading.Thread(
                target=lambda: from_thread.update(
                    pak=vpk_cache.open_vpk_cached(archive)))
            t.start()
            t.join()

            self.assertIs(from_thread["pak"], first,
                          "чужой поток обязан получить тот же объект")
            self.assertEqual(FakePak.opened, 1)
            self.assertEqual(FakePak.indexed, 1, "второй разбор — потерянные полсекунды")

    def test_updated_archive_is_reopened(self):
        """Steam может обновить игру, пока приложение открыто."""
        with TemporaryDirectory() as tmp, \
             patch.object(vpk_cache, "_vpk") as fake_vpk:
            fake_vpk.open.side_effect = FakePak
            archive = self._archive(Path(tmp))

            first = vpk_cache.open_vpk_cached(archive)
            with patch.object(vpk_cache, "_mtime", return_value=999999999.0):
                second = vpk_cache.open_vpk_cached(archive)

            self.assertIsNot(second, first, "каталог старого архива уже не годится")
            self.assertEqual(FakePak.opened, 2)

    def test_missing_library_is_not_an_error(self):
        with patch.object(vpk_cache, "_VPK_AVAILABLE", False):
            self.assertIsNone(vpk_cache.open_vpk_cached("whatever.vpk"))


if __name__ == "__main__":
    unittest.main()
