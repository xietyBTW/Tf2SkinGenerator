import tempfile
import unittest
from pathlib import Path

from src.shared.file_utils import (
    ensure_file_exists,
    ensure_directory_exists,
    ensure_directory_exists_strict,
    safe_remove,
    get_file_size_mb,
    find_files_by_extension,
    copy_file_safe,
    get_temp_file_path,
)
from src.shared.validators import sanitize_path


class FileUtilsTests(unittest.TestCase):
    def test_sanitize_path_allows_inside_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            safe_path = sanitize_path("subdir/file.txt", base)
            self.assertTrue(str(safe_path).startswith(str(base)))

    def test_sanitize_path_blocks_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with self.assertRaises(ValueError):
                sanitize_path("../outside.txt", base)

    def test_ensure_file_exists_returns_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "example.txt"
            file_path.write_text("data", encoding="utf-8")
            result = ensure_file_exists(file_path)
            self.assertEqual(result, file_path)

    def test_ensure_directory_exists_creates(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested"
            result = ensure_directory_exists(target)
            self.assertTrue(result.exists())
            self.assertTrue(result.is_dir())

    def test_ensure_directory_exists_strict_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing"
            with self.assertRaises(Exception):
                ensure_directory_exists_strict(missing)

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

    def test_get_file_size_mb(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "size.bin"
            file_path.write_bytes(b"1234567890")
            size = get_file_size_mb(file_path)
            self.assertGreater(size, 0)

    def test_find_files_by_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "a.txt").write_text("a", encoding="utf-8")
            nested = base / "nested"
            nested.mkdir()
            (nested / "b.txt").write_text("b", encoding="utf-8")
            (nested / "c.md").write_text("c", encoding="utf-8")
            recursive = find_files_by_extension(base, [".txt"], recursive=True)
            non_recursive = find_files_by_extension(base, [".txt"], recursive=False)
            self.assertEqual(len(recursive), 2)
            self.assertEqual(len(non_recursive), 1)

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


if __name__ == "__main__":
    unittest.main()
