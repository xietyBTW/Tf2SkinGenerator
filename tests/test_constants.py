import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.shared.constants import ToolPaths, DirectoryPaths


class ConstantsTests(unittest.TestCase):
    def test_tool_paths_resolve(self):
        with tempfile.TemporaryDirectory() as tmp:
            tool_file = Path(tmp) / "tool.exe"
            tool_file.write_text("x", encoding="utf-8")
            with patch.object(ToolPaths, "VTF_TOOL", tool_file):
                result = ToolPaths.get_vtf_tool()
            self.assertEqual(result, tool_file.resolve())

    def test_tool_paths_missing_no_tf2(self):
        # Бандл отсутствует И путь к TF2 не задан → возвращаем бандл-путь как есть.
        missing = Path("tools/missing.exe")
        with patch.object(ToolPaths, "VPK_TOOL", missing):
            with patch("src.config.app_config.AppConfig.get_tf2_game_folder", return_value=""):
                result = ToolPaths.get_vpk_tool()
        self.assertEqual(result, missing)

    def test_tool_paths_vpk_falls_back_to_tf2_bin(self):
        # Бандл отсутствует, но у пользователя установлена TF2 → берём bin/vpk.exe.
        with tempfile.TemporaryDirectory() as tmp:
            tf2_root = Path(tmp)
            bin_dir = tf2_root / "bin"
            bin_dir.mkdir()
            bin_vpk = bin_dir / "vpk.exe"
            bin_vpk.write_text("x", encoding="utf-8")
            with patch.object(ToolPaths, "VPK_TOOL", Path("tools/missing.exe")):
                with patch("src.config.app_config.AppConfig.get_tf2_game_folder",
                           return_value=str(tf2_root)):
                    result = ToolPaths.get_vpk_tool()
            self.assertEqual(result, bin_vpk.resolve())

    def test_directory_paths_ensure_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with patch.object(DirectoryPaths, "BASE_TEMP_DIR", base / "temp"):
                with patch.object(DirectoryPaths, "MOD_DATA_DIR", base / "mod_data"):
                    with patch.object(DirectoryPaths, "EXPORT_DIR", base / "export"):
                        with patch.object(DirectoryPaths, "CONFIG_DIR", base / "config"):
                            with patch.object(DirectoryPaths, "EDITED_VMT_DIR", base / "edited_vmt"):
                                with patch.object(DirectoryPaths, "TEMP_VMT_EXTRACT_DIR", base / "temp_vmt"):
                                    DirectoryPaths.ensure_exists()
            self.assertTrue((base / "temp").exists())
            self.assertTrue((base / "temp_vmt").exists())


if __name__ == "__main__":
    unittest.main()
