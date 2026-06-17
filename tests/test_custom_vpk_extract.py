"""
Тесты распаковки VPK в CustomVPKService._extract_via_vpk_exe.

Регрессия: модуль использовал `subprocess` и `ToolPaths` без импорта — вызов
падал с NameError на первой же строке (ToolPaths.get_vpk_tool() вне try/except),
ломая быстрый путь распаковки через vpk.exe. Эти тесты гарантируют, что путь
работает и имена доступны.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.services.custom_vpk_service import CustomVPKService


def _fake_completed(returncode=0, stdout="", stderr=""):
    return type("R", (), {"returncode": returncode, "stdout": stdout, "stderr": stderr})()


class ExtractViaVpkExeTests(unittest.TestCase):
    def test_module_has_subprocess_and_toolpaths(self):
        # Прямая защита от регрессии отсутствующих импортов: оба имени должны
        # быть доступны в неймспейсе модуля (иначе путь падает с NameError).
        import src.services.custom_vpk_service as mod
        self.assertTrue(hasattr(mod, "subprocess"))
        self.assertTrue(hasattr(mod, "ToolPaths"))
        self.assertTrue(hasattr(mod, "ToolTimeouts"))

    def test_success_returns_true_when_files_extracted(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            out_dir = base / "out"
            out_dir.mkdir()
            vpk_tool = base / "vpk.exe"
            vpk_tool.write_bytes(b"stub")  # ToolPaths.get_vpk_tool().exists() → True

            def fake_run(*args, **kwargs):
                # Эмулируем успешную распаковку: vpk.exe создаёт файл.
                (out_dir / "extracted.txt").write_text("data")
                return _fake_completed(returncode=0)

            with patch("src.services.custom_vpk_service.ToolPaths.get_vpk_tool", return_value=vpk_tool):
                with patch("src.services.custom_vpk_service.subprocess.run", side_effect=fake_run):
                    ok = CustomVPKService._extract_via_vpk_exe("mod.vpk", str(out_dir))
            self.assertTrue(ok)

    def test_missing_tool_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "out"
            out_dir.mkdir()
            missing = Path(tmp) / "does_not_exist" / "vpk.exe"
            with patch("src.services.custom_vpk_service.ToolPaths.get_vpk_tool", return_value=missing):
                ok = CustomVPKService._extract_via_vpk_exe("mod.vpk", str(out_dir))
            self.assertFalse(ok)

    def test_nonzero_returncode_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            out_dir = base / "out"
            out_dir.mkdir()
            vpk_tool = base / "vpk.exe"
            vpk_tool.write_bytes(b"stub")
            with patch("src.services.custom_vpk_service.ToolPaths.get_vpk_tool", return_value=vpk_tool):
                with patch("src.services.custom_vpk_service.subprocess.run",
                           return_value=_fake_completed(returncode=1, stderr="boom")):
                    ok = CustomVPKService._extract_via_vpk_exe("mod.vpk", str(out_dir))
            self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
