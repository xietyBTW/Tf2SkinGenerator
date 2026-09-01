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


if __name__ == "__main__":
    unittest.main()
