import os
import tempfile
import time
import unittest
from pathlib import Path

from src.shared.exceptions import RequiredFileMissingError
from src.shared.file_utils import (
    ensure_file_exists,
    ensure_directory_exists,
    safe_remove,
    copy_file_safe,
    get_temp_file_path,
    cleanup_stale_temp_artifacts,
)


class FileUtilsTests(unittest.TestCase):
    def test_ensure_file_exists_returns_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "example.txt"
            file_path.write_text("data", encoding="utf-8")
            result = ensure_file_exists(file_path)
            self.assertEqual(result, file_path)

    def test_ensure_file_exists_raises_for_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.txt"
            with self.assertRaises(RequiredFileMissingError):
                ensure_file_exists(missing)
            # Кастомное исключение должно ловиться и встроенным типом
            with self.assertRaises(FileNotFoundError):
                ensure_file_exists(missing)

    def test_ensure_file_exists_raises_for_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RequiredFileMissingError):
                ensure_file_exists(tmp)

    def test_ensure_directory_exists_creates(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested"
            result = ensure_directory_exists(target)
            self.assertTrue(result.exists())
            self.assertTrue(result.is_dir())

    def test_safe_remove_file_and_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "file.txt"
            file_path.write_text("data", encoding="utf-8")
            self.assertTrue(safe_remove(file_path))
            self.assertFalse(file_path.exists())
            dir_path = Path(tmp) / "dir"
            dir_path.mkdir()
            (dir_path / "nested.txt").write_text("data", encoding="utf-8")
            self.assertTrue(safe_remove(dir_path, is_dir=True))
            self.assertFalse(dir_path.exists())

    def test_copy_file_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source.txt"
            source.write_text("data", encoding="utf-8")
            dest = base / "out" / "dest.txt"
            result = copy_file_safe(source, dest)
            self.assertTrue(result.exists())
            self.assertEqual(result.read_text(encoding="utf-8"), "data")

    def test_get_temp_file_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            path = get_temp_file_path(prefix="x", suffix=".bin", directory=base)
            self.assertTrue(path.parent.exists())
            self.assertTrue(path.name.startswith("x_"))
            self.assertTrue(path.name.endswith(".bin"))

    def test_cleanup_stale_temp_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            old_time = time.time() - 48 * 3600

            stale_dir = base / "tf2sg_3d_abc"
            stale_dir.mkdir()
            (stale_dir / "model.obj").write_text("x", encoding="utf-8")
            stale_file = base / "tf2_vtf_old.png"
            stale_file.write_text("x", encoding="utf-8")
            os.utime(stale_dir, (old_time, old_time))
            os.utime(stale_file, (old_time, old_time))

            fresh_dir = base / "tf2sg_3d_new"       # наш, но свежий — не трогаем
            fresh_dir.mkdir()
            foreign = base / "other_app_dir"        # чужой префикс — не трогаем
            foreign.mkdir()
            os.utime(foreign, (old_time, old_time))

            removed = cleanup_stale_temp_artifacts(max_age_hours=24, temp_dir=base)

            self.assertEqual(removed, 2)
            self.assertFalse(stale_dir.exists())
            self.assertFalse(stale_file.exists())
            self.assertTrue(fresh_dir.exists())
            self.assertTrue(foreign.exists())

    def test_cleanup_missing_temp_dir_returns_zero(self):
        self.assertEqual(
            cleanup_stale_temp_artifacts(temp_dir=Path("Z:/no/such/dir_12345")), 0
        )

    def test_get_temp_file_path_system_dir(self):
        path = get_temp_file_path(prefix="tf2sg_test_", suffix=".tmp")
        try:
            # mkstemp создаёт файл — он должен существовать (нет race window)
            self.assertTrue(path.exists())
        finally:
            safe_remove(path)


if __name__ == "__main__":
    unittest.main()
