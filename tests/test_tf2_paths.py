import tempfile
import unittest
from pathlib import Path

from src.services.tf2_paths import TF2Paths


class TF2PathsTests(unittest.TestCase):
    def test_resolve_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "missing"
            with self.assertRaises(FileNotFoundError):
                TF2Paths.resolve(str(base))

    def test_resolve_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "bin").mkdir()
            (base / "tf").mkdir()
            (base / "bin" / "studiomdl.exe").write_text("x", encoding="utf-8")
            (base / "tf" / "tf2_misc_dir.vpk").write_text("x", encoding="utf-8")
            studiomdl, misc_vpk, tf_dir = TF2Paths.resolve(str(base))
            self.assertTrue(studiomdl.endswith("studiomdl.exe"))
            self.assertTrue(misc_vpk.endswith("tf2_misc_dir.vpk"))
            self.assertTrue(tf_dir.endswith("tf"))

    def test_resolve_textures_vpk(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "tf").mkdir()
            (base / "tf" / "tf2_textures_dir.vpk").write_text("x", encoding="utf-8")
            result = TF2Paths.resolve_textures_vpk(str(base))
            self.assertTrue(result.endswith("tf2_textures_dir.vpk"))

    def test_check_crowbar(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            crowbar = base / "CrowbarCommandLineDecomp.exe"
            crowbar.write_text("x", encoding="utf-8")
            TF2Paths.CROWBAR_PATH = str(crowbar)
            exists, error = TF2Paths.check_crowbar()
            self.assertTrue(exists)
            self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()
