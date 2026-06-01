import unittest
from pathlib import Path
from unittest import mock

from src.services.texture_service import TextureService


class TestResolveVtfFlagsAndOptions(unittest.TestCase):
    def test_merges_ui_options_with_flag_options(self):
        flags, merged = TextureService.resolve_vtf_flags_and_options(
            ["NOMIP", "CLAMPS"], {"srgb": True}
        )
        # NOMIP → опция nomipmaps, CLAMPS остаётся флагом
        self.assertEqual(flags, ["CLAMPS"])
        self.assertTrue(merged["nomipmaps"])
        self.assertTrue(merged["srgb"])

    def test_flag_options_override_ui_options(self):
        # nomipmaps из UI=False должен быть переопределён флагом NOMIP=True
        _, merged = TextureService.resolve_vtf_flags_and_options(
            ["NOMIP"], {"nomipmaps": False}
        )
        self.assertTrue(merged["nomipmaps"])

    def test_drop_normal_removes_normal_key(self):
        _, merged = TextureService.resolve_vtf_flags_and_options(
            [], {"normal": True}, drop_normal=True
        )
        self.assertNotIn("normal", merged)

    def test_keeps_normal_by_default(self):
        _, merged = TextureService.resolve_vtf_flags_and_options([], {"normal": True})
        self.assertTrue(merged["normal"])

    def test_none_options_yields_empty_merge(self):
        flags, merged = TextureService.resolve_vtf_flags_and_options(None, None)
        self.assertEqual(flags, [])
        self.assertEqual(merged, {})

    def test_does_not_mutate_input_options(self):
        opts = {"srgb": True}
        TextureService.resolve_vtf_flags_and_options(["NOMIP"], opts)
        self.assertEqual(opts, {"srgb": True})


class TestRenderImageToVtf(unittest.TestCase):
    """Проверяем маршрутизацию рендера (animated / normal / обычный) без внешних инструментов."""

    def _call(self, animated: bool, vtf_options):
        out_dir = Path("out")
        with mock.patch.object(TextureService, "is_animated_image", return_value=animated), \
             mock.patch.object(TextureService, "create_animated_vtf", return_value=12.0) as m_anim, \
             mock.patch.object(TextureService, "process_image") as m_proc, \
             mock.patch.object(TextureService, "create_vtf") as m_vtf, \
             mock.patch("src.services.texture_service.shutil.copy2"):
            fps, is_normal = TextureService.render_image_to_vtf(
                "img.png",
                vtf_output_path=out_dir,
                out_vtf_path=out_dir / "tex.vtf",
                temp_png_path=out_dir / "tex.png",
                normal_base="tex",
                size=(512, 512),
                format_type="DXT5",
                flags=[],
                vtf_options=vtf_options,
            )
        return fps, is_normal, m_anim, m_proc, m_vtf

    def test_animated_branch_uses_create_animated_vtf(self):
        fps, is_normal, m_anim, m_proc, m_vtf = self._call(animated=True, vtf_options=None)
        self.assertEqual(fps, 12.0)
        self.assertFalse(is_normal)
        m_anim.assert_called_once()
        m_proc.assert_not_called()
        m_vtf.assert_not_called()

    def test_plain_branch_creates_single_vtf(self):
        fps, is_normal, m_anim, m_proc, m_vtf = self._call(animated=False, vtf_options=None)
        self.assertIsNone(fps)
        self.assertFalse(is_normal)
        m_proc.assert_called_once()
        self.assertEqual(m_vtf.call_count, 1)

    def test_normal_map_branch_creates_two_vtf(self):
        # normal-map: основной VTF + _normal VTF (два вызова create_vtf)
        fps, is_normal, m_anim, m_proc, m_vtf = self._call(
            animated=False, vtf_options={"normal": True}
        )
        self.assertTrue(is_normal)
        self.assertEqual(m_vtf.call_count, 2)


if __name__ == "__main__":
    unittest.main()
