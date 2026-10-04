"""
Упаковка VPK: что происходит, когда готовый файл занят.

Повторная сборка поверх мода, который сейчас держит запущенная игра (или
GCFScape, или проводник с превью), — обычное дело. Раньше отсюда улетал сырой
WinError 32, из которого не следует, что делать; проверяем, что теперь это
понятная ошибка со ссылкой на файл.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.services.packaging_service import PackagingService
from src.shared.exceptions import FileLockedError


def _fake_tool(base: Path) -> Path:
    tool = base / "vpk.exe"
    tool.write_bytes(b"stub")     # pack_directory проверяет .exists()
    return tool


class PackDirectoryLockedTests(unittest.TestCase):

    def _pack(self, base: Path, export: Path):
        vpkroot = base / "vpkroot"
        vpkroot.mkdir(exist_ok=True)

        def fake_run(*_a, **_k):
            (base / "vpkroot.vpk").write_bytes(b"vpk")
            return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        with patch("src.services.packaging_service.subprocess.run", side_effect=fake_run), \
             patch("src.services.packaging_service.ToolPaths.get_vpk_tool",
                   return_value=_fake_tool(base)):
            return PackagingService.pack_directory(
                vpkroot, "out.vpk", export_folder=str(export), language="en")

    def test_locked_output_reports_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            export = base / "export"
            export.mkdir()
            busy = export / "out.vpk"
            busy.write_bytes(b"old")
            # Windows не даёт удалить открытый файл — ровно это и делает игра.
            with open(busy, "rb"):
                with self.assertRaises(FileLockedError) as caught:
                    self._pack(base, export)
            self.assertIn("out.vpk", str(caught.exception))

    def test_free_output_is_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            export = base / "export"
            export.mkdir()
            (export / "out.vpk").write_bytes(b"old")
            result = self._pack(base, export)
            self.assertTrue(result.endswith("out.vpk"))
            self.assertEqual(Path(result).read_bytes(), b"vpk")


class PackDirectoryLongPathTests(unittest.TestCase):
    """vpk.exe падает на пути длиннее 260 символов с обрезанным именем файла,
    из которого причину не понять, — говорим её до запуска."""

    def test_too_long_path_is_named_before_vpk_runs(self):
        from src.shared.error_classifier import classify
        from src.shared.exceptions import VPKCreationError

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "vpkroot").mkdir()
            deep = "C:\\" + "x" * 300 + ".vtf"
            with patch.object(PackagingService, "longest_path", return_value=deep), \
                 patch("src.services.packaging_service.subprocess.run") as run, \
                 patch("src.services.packaging_service.ToolPaths.get_vpk_tool",
                       return_value=_fake_tool(base)):
                with self.assertRaises(VPKCreationError) as caught:
                    PackagingService.pack_directory(base / "vpkroot", "out.vpk",
                                                    export_folder=str(base), language="en")
            run.assert_not_called()
            title, _ = classify(str(caught.exception), "en")
            self.assertEqual(title, "File path is too long")

    def test_longest_path_reads_real_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "a" / "bb").mkdir(parents=True)
            (base / "a" / "bb" / "ccc.vtf").write_bytes(b"x")
            (base / "d.vmt").write_bytes(b"x")
            self.assertTrue(PackagingService.longest_path(base).endswith("ccc.vtf"))
            self.assertEqual(PackagingService.longest_path(base / "a" / "none"), "")


if __name__ == "__main__":
    unittest.main()
