import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.services.build_context import BuildContext


class BuildContextTests(unittest.TestCase):
    def test_create_and_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ctx = BuildContext.create("scout_c_scattergun", "c_scattergun", base_temp_dir=base, debug_mode=False)
            self.assertTrue(ctx.temp_dir.exists())
            self.assertTrue(ctx.vpkroot_dir.exists())
            self.assertTrue(ctx.extract_dir.exists())
            self.assertTrue(ctx.decompile_dir.exists())
            ctx.cleanup(on_error=False, keep_on_error=False, debug_mode=False)
            self.assertFalse(ctx.temp_dir.exists())

    def test_debug_mode_keeps_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ctx = BuildContext.create("scout_c_scattergun", "c_scattergun", base_temp_dir=base, debug_mode=True)
            self.assertTrue(ctx.debug_dir.exists())
            ctx.cleanup(on_error=False, keep_on_error=False, debug_mode=True)
            self.assertTrue(ctx.temp_dir.exists())

    def test_cleanup_keeps_on_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ctx = BuildContext.create("scout_c_scattergun", "c_scattergun", base_temp_dir=base, debug_mode=False)
            ctx.cleanup(on_error=True, keep_on_error=True, debug_mode=False)
            self.assertTrue(ctx.temp_dir.exists())

    def test_cleanup_safe_remove_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ctx = BuildContext.create("scout_c_scattergun", "c_scattergun", base_temp_dir=base, debug_mode=False)
            with patch("src.services.build_context.safe_remove", return_value=False):
                ctx.cleanup(on_error=False, keep_on_error=False, debug_mode=False)
            self.assertTrue(ctx.temp_dir.exists())


if __name__ == "__main__":
    unittest.main()
