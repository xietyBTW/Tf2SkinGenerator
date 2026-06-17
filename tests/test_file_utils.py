import tempfile
import unittest
from pathlib import Path

from src.shared.exceptions import RequiredFileMissingError
from src.shared.file_utils import (
    ensure_file_exists,
    ensure_directory_exists,
    safe_remove,
    copy_file_safe,
    get_temp_file_path,
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

    def test_get_temp_file_path_system_dir(self):
        path = get_temp_file_path(prefix="tf2sg_test_", suffix=".tmp")
        try:
            # mkstemp создаёт файл — он должен существовать (нет race window)
            self.assertTrue(path.exists())
        finally:
            safe_remove(path)


if __name__ == "__main__":
    unittest.main()
