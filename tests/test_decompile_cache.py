import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.services import decompile_cache as dc


def _make_vpk(base: Path, name: str = "tf2_misc_dir.vpk") -> Path:
    vpk = base / name
    vpk.write_bytes(b"fake vpk")
    return vpk


def _make_decompile_dir(base: Path) -> Path:
    d = base / "decompiled"
    d.mkdir()
    (d / "weapon.qc").write_text("$modelname x", encoding="utf-8")
    (d / "weapon.smd").write_text("triangles", encoding="utf-8")
    return d


class DecompileCacheTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.cache_dir = self.base / "cache"
        self._patch = patch.object(dc, "_CACHE_DIR", self.cache_dir)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def test_save_and_get_roundtrip(self):
        vpk = _make_vpk(self.base)
        decomp = _make_decompile_dir(self.base)

        saved = dc.save_to_cache("c_test", str(vpk), "models/c_test.mdl", str(decomp))
        self.assertIsNotNone(saved)
        self.assertTrue((Path(saved) / "weapon.qc").exists())

        cached = dc.get_cached_decompile("c_test", str(vpk), "models/c_test.mdl")
        self.assertEqual(cached, saved)

    def test_miss_for_unknown_weapon(self):
        vpk = _make_vpk(self.base)
        self.assertIsNone(dc.get_cached_decompile("c_unknown", str(vpk), "models/c_unknown.mdl"))

    def test_vpk_update_invalidates_entry(self):
        """После изменения mtime VPK старая запись не должна возвращаться."""
        vpk = _make_vpk(self.base)
        decomp = _make_decompile_dir(self.base)
        dc.save_to_cache("c_test", str(vpk), "models/c_test.mdl", str(decomp))

        # «Обновление игры»: меняем mtime VPK
        import os
        st = vpk.stat()
        os.utime(vpk, (st.st_atime, st.st_mtime + 100))

        self.assertIsNone(dc.get_cached_decompile("c_test", str(vpk), "models/c_test.mdl"))

    def test_find_cached_qc_for_weapon(self):
        vpk = _make_vpk(self.base)
        decomp = _make_decompile_dir(self.base)
        dc.save_to_cache("c_test", str(vpk), "models/c_test.mdl", str(decomp))

        qc = dc.find_cached_qc_for_weapon("c_test")
        self.assertIsNotNone(qc)
        self.assertTrue(qc.endswith("weapon.qc"))
        self.assertIsNone(dc.find_cached_qc_for_weapon("c_other"))

    def test_find_cached_qc_skips_stale_vpk(self):
        """find_cached_qc_for_weapon не должен возвращать QC от старой версии игры."""
        vpk = _make_vpk(self.base)
        decomp = _make_decompile_dir(self.base)
        dc.save_to_cache("c_test", str(vpk), "models/c_test.mdl", str(decomp))

        import os
        st = vpk.stat()
        os.utime(vpk, (st.st_atime, st.st_mtime + 100))

        self.assertIsNone(dc.find_cached_qc_for_weapon("c_test"))

    def test_save_purges_stale_entries(self):
        """Новая запись для того же оружия удаляет запись со старым mtime."""
        vpk = _make_vpk(self.base)
        decomp = _make_decompile_dir(self.base)
        dc.save_to_cache("c_test", str(vpk), "models/c_test.mdl", str(decomp))
        entries_before = [p for p in self.cache_dir.iterdir() if p.is_dir()]
        self.assertEqual(len(entries_before), 1)

        # «Обновление игры» → новый mtime → новый ключ кэша
        import os
        st = vpk.stat()
        os.utime(vpk, (st.st_atime, st.st_mtime + 100))
        dc.save_to_cache("c_test", str(vpk), "models/c_test.mdl", str(decomp))

        entries_after = [p for p in self.cache_dir.iterdir() if p.is_dir()]
        self.assertEqual(len(entries_after), 1, "устаревшая запись должна быть удалена")

    def test_restore_from_cache(self):
        vpk = _make_vpk(self.base)
        decomp = _make_decompile_dir(self.base)
        saved = dc.save_to_cache("c_test", str(vpk), "models/c_test.mdl", str(decomp))

        target = self.base / "restored"
        qc_path = dc.restore_from_cache(saved, str(target))
        self.assertTrue(Path(qc_path).exists())
        self.assertTrue((target / "weapon.smd").exists())
        # Мета-файл кэша не должен копироваться в рабочую папку
        self.assertFalse((target / "_cache_meta.json").exists())

    def test_clear_cache_all_and_by_weapon(self):
        vpk = _make_vpk(self.base)
        decomp = _make_decompile_dir(self.base)
        dc.save_to_cache("c_a", str(vpk), "models/c_a.mdl", str(decomp))
        dc.save_to_cache("c_b", str(vpk), "models/c_b.mdl", str(decomp))

        removed = dc.clear_cache("c_a")
        self.assertEqual(removed, 1)
        self.assertIsNone(dc.find_cached_qc_for_weapon("c_a"))
        self.assertIsNotNone(dc.find_cached_qc_for_weapon("c_b"))

        removed_all = dc.clear_cache()
        self.assertEqual(removed_all, 1)

    def test_get_cache_size_mb(self):
        vpk = _make_vpk(self.base)
        decomp = _make_decompile_dir(self.base)
        dc.save_to_cache("c_test", str(vpk), "models/c_test.mdl", str(decomp))
        self.assertGreater(dc.get_cache_size_mb(), 0)

    def test_corrupt_meta_is_miss(self):
        vpk = _make_vpk(self.base)
        decomp = _make_decompile_dir(self.base)
        saved = dc.save_to_cache("c_test", str(vpk), "models/c_test.mdl", str(decomp))
        meta = Path(saved) / "_cache_meta.json"
        meta.write_text("{not json", encoding="utf-8")
        self.assertIsNone(dc.get_cached_decompile("c_test", str(vpk), "models/c_test.mdl"))

    def test_old_cache_version_is_miss(self):
        vpk = _make_vpk(self.base)
        decomp = _make_decompile_dir(self.base)
        saved = dc.save_to_cache("c_test", str(vpk), "models/c_test.mdl", str(decomp))
        meta_path = Path(saved) / "_cache_meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["version"] = 1
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        self.assertIsNone(dc.get_cached_decompile("c_test", str(vpk), "models/c_test.mdl"))

    @staticmethod
    def _entry_size(entry: Path) -> int:
        return sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())

    def test_enforce_cache_limit_evicts_lru(self):
        """enforce_cache_limit удаляет самые давно used записи, укладываясь в лимит."""
        import os
        vpk = _make_vpk(self.base)
        decomp = _make_decompile_dir(self.base)
        e_a = Path(dc.save_to_cache("c_a", str(vpk), "models/c_a.mdl", str(decomp)))
        e_b = Path(dc.save_to_cache("c_b", str(vpk), "models/c_b.mdl", str(decomp)))
        e_c = Path(dc.save_to_cache("c_c", str(vpk), "models/c_c.mdl", str(decomp)))
        # Явные mtime: c_a — самая старая, c_c — свежая.
        os.utime(e_a, (1000, 1000))
        os.utime(e_b, (2000, 2000))
        os.utime(e_c, (3000, 3000))

        total = sum(self._entry_size(e) for e in (e_a, e_b, e_c))
        one = self._entry_size(e_b)
        # Лимит чуть выше (total - один размер) → должна уйти ровно самая старая.
        limit_mb = (total - one // 2) / (1024 * 1024)
        removed = dc.enforce_cache_limit(max_mb=limit_mb)

        self.assertEqual(removed, 1)
        self.assertFalse(e_a.exists(), "самая старая запись удаляется первой")
        self.assertTrue(e_b.exists())
        self.assertTrue(e_c.exists())

    def test_enforce_cache_limit_disabled(self):
        """max_mb<=0 — лимит выключен, ничего не удаляется."""
        vpk = _make_vpk(self.base)
        decomp = _make_decompile_dir(self.base)
        dc.save_to_cache("c_a", str(vpk), "models/c_a.mdl", str(decomp))
        self.assertEqual(dc.enforce_cache_limit(max_mb=0), 0)
        self.assertIsNotNone(dc.find_cached_qc_for_weapon("c_a"))

    def test_get_cached_decompile_touches_mtime_for_lru(self):
        """Cache hit обновляет mtime записи (иначе LRU считала бы её старой)."""
        import os
        vpk = _make_vpk(self.base)
        decomp = _make_decompile_dir(self.base)
        saved = Path(dc.save_to_cache("c_test", str(vpk), "models/c_test.mdl", str(decomp)))
        os.utime(saved, (1000, 1000))
        old_mtime = saved.stat().st_mtime

        self.assertIsNotNone(dc.get_cached_decompile("c_test", str(vpk), "models/c_test.mdl"))
        self.assertGreater(saved.stat().st_mtime, old_mtime)


if __name__ == "__main__":
    unittest.main()
