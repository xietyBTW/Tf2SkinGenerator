import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.services.build_context import BuildContext, TextureBuildContext


class TextureBuildContextTests(unittest.TestCase):
    def _ctx(self, custom=None):
        return TextureBuildContext(
            vtf_output_path=Path("out"),
            size=(512, 512),
            format_type="DXT5",
            flags=[],
            vtf_options={},
            custom_vtf_path=custom,
        )

    def test_custom_vtf_just_copies(self):
        ctx = self._ctx(custom="user.vtf")
        with patch("src.services.build_context.copy_file_safe") as m_copy:
            fps = ctx.render_user_image_vtf("img.png", Path("out/t.vtf"), "t.png")
        self.assertIsNone(fps)
        m_copy.assert_called_once()

    def test_animated_returns_fps(self):
        ctx = self._ctx()
        with patch("src.services.texture_service.TextureService.is_animated_image", return_value=True), \
             patch("src.services.texture_service.TextureService.create_animated_vtf", return_value=24.0) as m_anim, \
             patch("src.services.texture_service.TextureService.create_vtf") as m_vtf:
            fps = ctx.render_user_image_vtf("img.gif", Path("out/t.vtf"), "t.png")
        self.assertEqual(fps, 24.0)
        m_anim.assert_called_once()
        m_vtf.assert_not_called()

    def test_plain_creates_vtf(self):
        ctx = self._ctx()
        with patch("src.services.texture_service.TextureService.is_animated_image", return_value=False), \
             patch("src.services.texture_service.TextureService.process_image") as m_proc, \
             patch("src.services.texture_service.TextureService.create_vtf") as m_vtf:
            fps = ctx.render_user_image_vtf("img.png", Path("out/t.vtf"), "t.png")
        self.assertIsNone(fps)
        m_proc.assert_called_once()
        m_vtf.assert_called_once()


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
