"""
vtf_writer повторяет файл VTFCmd: числа ниже сняты с VTFCmd 1.3.2 прогоном
по всем форматам. Тест держит и обращения к внутренностям srctools (_frames,
_low_res): если новая версия srctools их поменяет, упадёт здесь
"""

import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image
from srctools.vtf import VTF, ImageFormats, VTFFlags

from src.services import vtf_writer
from src.services.vtflib_wrapper import VTFLib


def _gradient(width, height, alpha=True):
    y, x = np.mgrid[0:height, 0:width]
    a = np.stack([x * 255 // max(width - 1, 1), y * 255 // max(height - 1, 1), (x ^ y) & 255,
                  128 + x * 127 // max(width - 1, 1) if alpha else np.full_like(x, 255)], -1)
    return Image.fromarray(a.astype(np.uint8), "RGBA")


class VtfWriterTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, image, fmt, **kw):
        out = self.dir / f"{fmt}.vtf"
        vtf_writer.write_vtf(image, out, fmt, **kw)
        with open(out, "rb") as f:
            vtf = VTF.read(f)
            vtf.load()
        return vtf, out

    def test_header_like_vtfcmd(self):
        vtf, _ = self._write(_gradient(64, 64), "DXT5")
        self.assertEqual(vtf.version, (7, 3))
        self.assertEqual(vtf.mipmap_count, 7)
        self.assertEqual(vtf.flags, VTFFlags.EIGHTBITALPHA)
        self.assertEqual(vtf.low_format, ImageFormats.DXT1)
        # reflectivity VTFCmd на этой картинке
        np.testing.assert_allclose(tuple(vtf.reflectivity), (0.3134, 0.3134, 0.0146), atol=2e-3)

    def test_alpha_flags_by_format(self):
        self.assertEqual(vtf_writer.alpha_flags("DXT1"), 0)
        self.assertEqual(vtf_writer.alpha_flags("DXT1_ONEBITALPHA"), VTFFlags.ONEBITALPHA.value)
        self.assertEqual(vtf_writer.alpha_flags("BGRA5551"), VTFFlags.ONEBITALPHA.value)
        for fmt in ("DXT3", "RGBA8888", "IA88", "UVLX8888"):
            self.assertEqual(vtf_writer.alpha_flags(fmt), VTFFlags.EIGHTBITALPHA.value, fmt)

    def test_non_square_mips_reach_1x1(self):
        # Так у всех стоковых неквадратных текстур TF2
        vtf, _ = self._write(_gradient(128, 32), "DXT5")
        self.assertEqual(vtf.mipmap_count, 8)
        last = vtf.get(mipmap=7)
        self.assertEqual((last.width, last.height), (1, 1))

    def test_mipmaps_ignore_alpha_weighting(self):
        # Pillow при уменьшении RGBA учитывает альфу, VTFCmd - нет
        img = Image.new("RGBA", (2, 2))
        img.putdata([(255, 0, 0, 255), (0, 0, 255, 0)] * 2)
        vtf, _ = self._write(img, "RGBA8888")
        r, g, b, a = vtf.get(mipmap=1).to_PIL().getpixel((0, 0))
        self.assertAlmostEqual(r, 128, delta=1)
        self.assertAlmostEqual(b, 128, delta=1)

    def test_thumbnail_filled(self):
        vtf, _ = self._write(Image.new("RGBA", (64, 32), (200, 100, 30, 255)), "DXT1")
        low = vtf._low_res
        self.assertEqual((low.width, low.height), (16, 8))
        low.load()
        r, g, b, _ = low.to_PIL().getpixel((0, 0))
        self.assertGreater(r, 150)

    def test_thumbnail_keeps_colour_for_converted_formats(self):
        # srctools при сохранении перерисовывал превью из мипа с переложенными каналами
        for fmt in ("RGB565", "I8"):
            vtf, _ = self._write(Image.new("RGBA", (64, 64), (255, 0, 0, 255)), fmt)
            vtf._low_res.load()
            r, g, b, _ = vtf._low_res.to_PIL().getpixel((0, 0))
            self.assertGreater(r, 200, fmt)
            self.assertLess(b, 50, fmt)

    def test_gamma_value_from_text_field(self):
        from src.services.texture_service import TextureService
        self.assertAlmostEqual(TextureService._gamma_value({"gcorrection": "2,2"}), 2.2)
        self.assertEqual(TextureService._gamma_value({"gcorrection": ""}), 2.0)
        self.assertEqual(TextureService._gamma_value({}), 2.0)
        self.assertEqual(TextureService._gamma_value({"gcorrection": "-1"}), 2.0)
        self.assertEqual(TextureService._gamma_value({"gcorrection": 1.8}), 1.8)

    def test_no_thumbnail_and_no_mips(self):
        vtf, _ = self._write(_gradient(16, 16), "DXT5", thumbnail=False, mipmaps=False,
                             flags=VTFFlags.NO_MIP.value | VTFFlags.NO_LOD.value)
        self.assertEqual(vtf.version, (7, 2))
        self.assertEqual(vtf.low_format, ImageFormats.NONE)
        self.assertEqual(vtf.mipmap_count, 1)

    def test_565_channel_order_matches_vtflib(self):
        img = Image.new("RGBA", (16, 16), (200, 100, 30, 255))
        for fmt in ("RGB565", "BGR565"):
            _, out = self._write(img, fmt)
            frames, _, _ = VTFLib.read_vtf_all_frames(str(out))
            r, g, b = frames[0][:3]
            self.assertGreater(r, 180, fmt)
            self.assertLess(b, 50, fmt)

    def test_gray_uses_luma(self):
        vtf, _ = self._write(Image.new("RGBA", (16, 16), (200, 100, 30, 255)), "I8")
        self.assertAlmostEqual(vtf.get().to_PIL().getpixel((0, 0))[0], 122, delta=1)

    def test_gamma(self):
        vtf, _ = self._write(Image.new("RGBA", (16, 16), (64, 64, 64, 128)), "RGBA8888", gamma=2.0)
        r, _, _, a = vtf.get().to_PIL().getpixel((0, 0))
        self.assertEqual(r, 128)
        self.assertEqual(a, 128)

    def test_hdr_goes_through_vtflib(self):
        out = self.dir / "hdr.vtf"
        vtf_writer.write_vtf(Image.new("RGBA", (16, 16), (200, 100, 30, 255)), out, "RGBA16161616F")
        with open(out, "rb") as f:
            vtf = VTF.read(f, header_only=True)
        self.assertEqual(vtf.format, ImageFormats.RGBA16161616F)

    def test_vtflib_handles_non_ascii_folder(self):
        # VTFLib сам открывал файлы по пути в ANSI: кириллица в папке пользователя
        # ломала и запись, и чтение
        folder = self.dir / "Пользователь 用户"
        folder.mkdir()
        img = _gradient(16, 16)
        out = folder / "hdr.vtf"
        vtf_writer.write_vtf(img, out, "RGBA16161616F")
        self.assertTrue(out.exists())
        anim = folder / "anim.vtf"
        VTFLib.create_animated_vtf([img.tobytes()], 16, 16, 0, 0, str(anim))
        frames, w, h = VTFLib.read_vtf_all_frames(str(anim))
        self.assertEqual(frames[0], img.tobytes())
        rgba, _, _ = VTFLib.read_vtf_as_rgba(str(anim))
        self.assertEqual(rgba, img.tobytes())

    def test_non_power_of_two_fails_without_file(self):
        out = self.dir / "npot.vtf"
        with self.assertRaises(ValueError):
            vtf_writer.write_vtf(Image.new("RGBA", (12, 8)), out, "DXT1")
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
