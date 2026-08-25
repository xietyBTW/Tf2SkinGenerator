"""
Единая цепочка «материал → картинка».

Проверяется против фейкового VPK — раньше этот код можно было проверить
только руками на установленной игре, и именно поэтому в нём годами
расходились копии.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.services.material_resolver import MaterialResolver
from tests.fake_vpk import fake_reader, vmt

CD = ["models/workshop/player/items/scout/hat"]


def _png_bytes(color=(10, 20, 30, 255), size=(4, 4)) -> bytes:
    """Настоящий PNG нужного цвета — VTF в тестах подменяем на него."""
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGBA", size, color).save(buf, format="PNG")
    return buf.getvalue()


class _StubVtf:
    """Подменяет декодер VTF: «VTF-байты» здесь — это готовый PNG."""

    def __enter__(self):
        from src.services import vtf_preview_service as vps

        self._orig = vps.vtf_bytes_to_png
        vps.vtf_bytes_to_png = self._fake
        return self

    def __exit__(self, *exc):
        from src.services import vtf_preview_service as vps

        vps.vtf_bytes_to_png = self._orig

    @staticmethod
    def _fake(data, out_png_path, tmp_dir=None):
        if not data:
            return None
        Path(out_png_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_png_path).write_bytes(data)
        return out_png_path


class ResolverTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.out = self._tmp.name
        self._vtf = _StubVtf()
        self._vtf.__enter__()

    def tearDown(self):
        self._vtf.__exit__(None, None, None)
        self._tmp.cleanup()

    def _resolver(self, files, extra=None, apply_tint=True):
        return MaterialResolver(fake_reader(files, extra), self.out,
                                apply_tint=apply_tint)

    def test_full_chain(self):
        r = self._resolver({
            f"materials/{CD[0]}/hat.vmt": vmt(basetexture="models/hat/hat_color"),
            "materials/models/hat/hat_color.vtf": _png_bytes(),
        })
        res = r.resolve("hat", CD)
        self.assertTrue(res.ok)
        self.assertEqual(res.basetexture, "models/hat/hat_color")
        self.assertEqual(res.shader, "vertexlitgeneric")
        self.assertTrue(Path(res.png_path).is_file())

    def test_vmt_and_vtf_live_in_different_archives(self):
        """Как в игре: VMT в tf2_misc, VTF в tf2_textures."""
        r = self._resolver(
            {f"materials/{CD[0]}/hat.vmt": vmt(basetexture="models/hat/hat_color")},
            extra={"materials/models/hat/hat_color.vtf": _png_bytes()})
        self.assertTrue(r.resolve("hat", CD).ok)

    def test_missing_pieces_do_not_raise(self):
        empty = self._resolver({})
        res = empty.resolve("hat", CD)
        self.assertFalse(res.ok)
        self.assertIsNone(res.basetexture)

        no_vtf = self._resolver(
            {f"materials/{CD[0]}/hat.vmt": vmt(basetexture="models/hat/missing")})
        res = no_vtf.resolve("hat", CD)
        self.assertFalse(res.ok)
        self.assertEqual(res.basetexture, "models/hat/missing", "VMT всё же прочли")

        no_base = self._resolver({f"materials/{CD[0]}/hat.vmt": vmt(phong="1")})
        self.assertFalse(no_base.resolve("hat", CD).ok)

    def test_material_name_with_path(self):
        """В модели у материала иногда записан полный путь, а не голое имя."""
        r = self._resolver({
            "materials/models/hat/hat.vmt": vmt(basetexture="models/hat/hat_color"),
            "materials/models/hat/hat_color.vtf": _png_bytes(),
        })
        self.assertTrue(r.resolve("models/hat/hat", []).ok)

    def test_cache_reads_vpk_once(self):
        """Материал в модели встречается по несколько раз — архив читаем один."""
        files = {
            f"materials/{CD[0]}/hat.vmt": vmt(basetexture="models/hat/hat_color"),
            "materials/models/hat/hat_color.vtf": _png_bytes(),
        }
        reader = fake_reader(files)
        r = MaterialResolver(reader, self.out)
        for _ in range(5):
            r.resolve("hat", CD)
        vmt_hits = [p for p in reader.paks[0].hits if p.endswith(".vmt")]
        self.assertEqual(len(vmt_hits), 1, reader.paks[0].hits)

    def test_tint_is_applied(self):
        """Командная краска впечатывается здесь — иначе её забудут."""
        from PIL import Image

        files = {
            f"materials/{CD[0]}/hat.vmt": vmt(
                basetexture="models/hat/hat_color",
                blendtintbybasealpha="1",
                blendtintcoloroverbase="0.99",
                colortint_base="{ 189 59 59 }"),
            # Тёмный пиксель под маской краски (альфа 255)
            "materials/models/hat/hat_color.vtf": _png_bytes((8, 8, 8, 255)),
        }
        painted = self._resolver(files).resolve("hat", CD)
        self.assertIsNotNone(painted.tint)
        self.assertEqual(painted.tint.color, (189, 59, 59))
        with Image.open(painted.png_path) as img:
            px = img.convert("RGBA").getpixel((0, 0))
        self.assertLess(abs(px[0] - 189), 6, px)
        self.assertEqual(px[3], 255, "альфа была маской, а не прозрачностью")

    def test_tint_can_be_switched_off_for_export(self):
        """Экспорт отдаёт сырую текстуру: в игре краску наложит движок."""
        from PIL import Image

        files = {
            f"materials/{CD[0]}/hat.vmt": vmt(
                basetexture="models/hat/hat_color",
                blendtintbybasealpha="1",
                colortint_base="{ 189 59 59 }"),
            "materials/models/hat/hat_color.vtf": _png_bytes((8, 8, 8, 255)),
        }
        raw = self._resolver(files, apply_tint=False).resolve("hat", CD)
        with Image.open(raw.png_path) as img:
            self.assertEqual(img.convert("RGBA").getpixel((0, 0)), (8, 8, 8, 255))
        self.assertIsNotNone(raw.tint, "краску всё равно распознали")

    def test_same_look_compares_texture_and_paint(self):
        """Ответ на «отличается ли BLU от RED» даёт сам резолвер."""
        files = {
            f"materials/{CD[0]}/hat.vmt": vmt(
                basetexture="models/hat/hat_color",
                blendtintbybasealpha="1", colortint_base="{ 189 59 59 }"),
            f"materials/{CD[0]}/hat_blue.vmt": vmt(
                basetexture="models/hat/hat_color",
                blendtintbybasealpha="1", colortint_base="{ 91 122 140 }"),
            f"materials/{CD[0]}/hat_copy.vmt": vmt(
                basetexture="models/hat/hat_color",
                blendtintbybasealpha="1", colortint_base="{ 189 59 59 }"),
            "materials/models/hat/hat_color.vtf": _png_bytes(),
        }
        r = self._resolver(files)
        red = r.resolve("hat", CD)
        blu = r.resolve("hat_blue", CD, out_name="blu_hat")
        copy = r.resolve("hat_copy", CD, out_name="copy_hat")
        self.assertFalse(red.same_look(blu), "разная краска — разный вид")
        self.assertTrue(red.same_look(copy), "та же текстура и та же краска")
        self.assertFalse(red.same_look(None))

    def test_resolve_many_and_texture_map(self):
        files = {
            f"materials/{CD[0]}/body.vmt": vmt(basetexture="models/hat/body"),
            f"materials/{CD[0]}/lens.vmt": vmt(basetexture="models/hat/lens"),
            "materials/models/hat/body.vtf": _png_bytes(),
            "materials/models/hat/lens.vtf": _png_bytes(),
        }
        r = self._resolver(files)
        found = r.resolve_many(["body", "lens", "нет-такого"], CD)
        self.assertEqual(sorted(found), ["body", "lens"])
        tex = r.texture_map(["body", "lens"], CD)
        self.assertTrue(all(Path(p).is_file() for p in tex.values()))

    def test_out_name_keeps_files_apart(self):
        """RED и BLU одного материала не должны затирать PNG друг друга."""
        files = {
            f"materials/{CD[0]}/hat.vmt": vmt(basetexture="models/hat/a"),
            f"materials/{CD[0]}/hat_blue.vmt": vmt(basetexture="models/hat/b"),
            "materials/models/hat/a.vtf": _png_bytes((1, 2, 3, 255)),
            "materials/models/hat/b.vtf": _png_bytes((9, 9, 9, 255)),
        }
        r = self._resolver(files)
        red = r.resolve("hat", CD)
        blu = r.resolve("hat_blue", CD, out_name="blu_hat")
        self.assertNotEqual(red.png_path, blu.png_path)

    def test_slashes_in_name_do_not_escape_out_dir(self):
        """Имя материала с путём не должно уводить запись из папки превью."""
        files = {
            "materials/models/hat/hat.vmt": vmt(basetexture="models/hat/hat_color"),
            "materials/models/hat/hat_color.vtf": _png_bytes(),
        }
        res = self._resolver(files).resolve("models/hat/hat", [])
        self.assertEqual(Path(res.png_path).parent, Path(self.out))


if __name__ == "__main__":
    unittest.main()
