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
             mock.patch.object(TextureService, "write_normal_png"):
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
        # Нормаль — своим форматом и с флагом NORMAL, как у нормалей Valve.
        _png, _out, fmt, flags, _opts = m_vtf.call_args_list[1].args
        self.assertEqual((fmt, flags), ("DXT5", ["NORMAL"]))

    def test_normal_map_keeps_quality_on_dxt1_base(self):
        """База в DXT1 — нормаль всё равно DXT5: иначе блоки и нет альфы."""
        m_vtf = mock.MagicMock()
        with mock.patch.object(TextureService, "is_animated_image", return_value=False),              mock.patch.object(TextureService, "process_image"),              mock.patch.object(TextureService, "create_vtf", m_vtf),              mock.patch.object(TextureService, "write_normal_png"):
            TextureService.render_image_to_vtf(
                "img.png", vtf_output_path=Path("out"), out_vtf_path=Path("out/tex.vtf"),
                temp_png_path=Path("out/tex.png"), normal_base="tex", size=(512, 512),
                format_type="DXT1", flags=[], vtf_options={"normal": True})
        self.assertEqual(m_vtf.call_args_list[1].args[2], "DXT5")


if __name__ == "__main__":
    unittest.main()


def test_normal_map_matches_source_axes():
    """Выпуклость (светлый центр) в осях Source X+ Y- Z+: слева и сверху < 128."""
    import numpy as np
    from src.services import normal_map
    yy, xx = np.mgrid[0:64, 0:64]
    dome = np.clip(255 - np.hypot(xx - 32, yy - 32) * 8, 0, 255).astype(np.uint8)
    n = normal_map.encode(normal_map.from_image(np.dstack([dome] * 3))).astype(int)
    assert n[32, 22, 0] < 128 < n[32, 42, 0]
    assert n[22, 32, 1] < 128 < n[42, 32, 1]
    length = np.linalg.norm(n[..., :3] / 127.5 - 1, axis=2)
    assert abs(length - 1).max() < 0.02


def test_normal_map_over_stock_keeps_stock_alpha_and_relief():
    """Поверх родной нормали: её альфа (маска блеска) цела, её наклон виден."""
    import numpy as np
    from src.services import normal_map
    flat = np.full((32, 32, 3), 128, np.uint8)
    tilted = normal_map.encode(np.dstack([np.full((16, 16), 0.5), np.zeros((16, 16)),
                                          np.full((16, 16), 0.866)]).astype(np.float32),
                               np.full((16, 16), 40, np.uint8))
    out = normal_map.make(flat, normal_map.NormalSettings(), tilted)
    assert out.shape == (32, 32, 4)
    assert (out[..., 3] == 40).all()
    assert abs(int(out[16, 16, 0]) - 191) <= 2
    plain = normal_map.make(flat, normal_map.NormalSettings(over_stock=False), tilted)
    assert abs(int(plain[16, 16, 0]) - 128) <= 1 and (plain[..., 3] == 40).all()


def test_normal_strength_and_invert():
    import numpy as np
    from src.services import normal_map
    ramp = np.dstack([np.tile(np.linspace(0, 255, 64, dtype=np.float32), (64, 1)).astype(np.uint8)] * 3)
    weak = normal_map.from_image(ramp, 0.5)[32, 32, 0]
    strong = normal_map.from_image(ramp, 2.0)[32, 32, 0]
    assert strong < weak < 0                         # светлеет вправо — склон влево
    assert normal_map.from_image(ramp, 1.0, invert=True)[32, 32, 0] > 0
    assert normal_map.from_image(ramp, 0.0)[32, 32, 2] == 1.0


def test_normal_settings_from_build_options():
    from src.services.normal_map import NormalSettings
    s = NormalSettings.from_options({'normal': True, 'normal_strength': '1.5',
                                     'normal_invert': True, 'normal_replace_stock': True})
    assert (s.strength, s.invert, s.over_stock) == (1.5, True, False)
    assert NormalSettings.from_options({'normal_strength': 'x'}).strength == 1.0
    assert NormalSettings.from_options(None).over_stock


def test_normal_strength_does_not_depend_on_resolution():
    """Сборка 512 и превью 1024 одной картинки — рельеф одной силы."""
    import numpy as np
    from PIL import Image
    from src.services import normal_map
    yy, xx = np.mgrid[0:1024, 0:1024]
    img = (128 + 100 * np.sin(xx / 1024 * 12 * np.pi)).astype(np.uint8)
    big = np.dstack([img] * 3)
    small = np.asarray(Image.fromarray(big).resize((512, 512), Image.LANCZOS))
    tilt = lambda a: np.degrees(np.arccos(normal_map.from_image(a)[..., 2])).mean()  # noqa: E731
    assert abs(tilt(big) - tilt(small)) < 0.15 * tilt(big)
