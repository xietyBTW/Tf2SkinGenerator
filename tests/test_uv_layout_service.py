import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.services.uv_layout_service import UVLayoutService


class UVLayoutServiceTests(unittest.TestCase):
    def test_parse_smd_uv_coordinates(self):
        content = "\n".join([
            "triangles",
            "mat",
            "0 1 2 3 0 0 1 0.1 0.2",
            "0 1 2 3 0 0 1 0.3 0.4",
            "0 1 2 3 0 0 1 0.5 0.6",
            "end",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            smd_path = Path(tmp) / "file.smd"
            smd_path.write_text(content, encoding="utf-8")
            coords = UVLayoutService.parse_smd_uv_coordinates(str(smd_path))
            self.assertEqual(len(coords), 3)
    
    def test_parse_smd_uv_coordinates_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            UVLayoutService.parse_smd_uv_coordinates("missing.smd")
    
    def test_parse_smd_uv_coordinates_with_comments(self):
        content = "\n".join([
            "triangles",
            "// comment",
            "",
            "mat",
            "0 1 2 3 0 0 1 0.1 0.2",
            "0 1 2 3 0 0 1 0.3 0.4",
            "0 1 2 3 0 0 1 0.5 0.6",
            "end",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            smd_path = Path(tmp) / "file.smd"
            smd_path.write_text(content, encoding="utf-8")
            coords = UVLayoutService.parse_smd_uv_coordinates(str(smd_path))
            self.assertEqual(len(coords), 3)

    def test_draw_uv_layout_and_generate(self):
        coords = [(0.1, 0.2, 0, 0, 0, 0, 0, 1), (0.3, 0.4, 0, 0, 0, 0, 0, 1), (0.5, 0.6, 0, 0, 0, 0, 0, 1)]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "uv.png"
            UVLayoutService.draw_uv_layout(coords, str(output), image_size=(64, 64))
            self.assertTrue(output.exists())
    
    def test_draw_uv_layout_maps_uv_to_full_texture_space(self):
        # UV [0,1]² должно ложиться на всю картинку без отступов/нормализации:
        # рисуем один «треугольник» в трёх известных UV и проверяем пиксели.
        from PIL import Image
        # (0,0)=низ-лево, (1,1)=верх-право, (0.5,0.5)=центр (V инвертируется).
        coords = [
            (0.0, 0.0, 0, 0, 0, 0, 0, 1),
            (1.0, 1.0, 0, 0, 0, 0, 0, 1),
            (0.5, 0.5, 0, 0, 0, 0, 0, 1),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "uv.png"
            UVLayoutService.draw_uv_layout(
                coords, str(output), image_size=(64, 64),
                line_color="black", point_size=0,
            )
            im = Image.open(str(output)).convert("RGB")
            w, h = im.size

            def near_black(px):
                return px[0] < 128 and px[1] < 128 and px[2] < 128

            # Угол UV(0,0) → низ-лево; UV(1,1) → верх-право; центр UV(0.5,0.5).
            self.assertTrue(near_black(im.getpixel((0, h - 1))))
            self.assertTrue(near_black(im.getpixel((w - 1, 0))))
            self.assertTrue(near_black(im.getpixel((w // 2, h // 2))))
            # Противоположные «пустые» углы должны остаться белыми (нет паддинга,
            # но и разметка туда не заходит) — верх-лево и низ-право.
            self.assertFalse(near_black(im.getpixel((0, 0))))
            self.assertFalse(near_black(im.getpixel((w - 1, h - 1))))

    def test_draw_uv_layout_default_has_no_vertex_dots(self):
        # По умолчанию (point_size=0) — только линии, без «жирных» точек на
        # вершинах: пиксель рядом с вершиной, но вне линий, остаётся белым.
        from PIL import Image
        coords = [
            (0.1, 0.9, 0, 0, 0, 0, 0, 1),   # → пиксель (10,10) на 100x100
            (0.9, 0.9, 0, 0, 0, 0, 0, 1),
            (0.5, 0.1, 0, 0, 0, 0, 0, 1),
        ]
        off = (7, 10)   # 3px левее вершины (10,10) — вне всех рёбер треугольника
        with tempfile.TemporaryDirectory() as tmp:
            default_png = Path(tmp) / "d.png"
            dots_png = Path(tmp) / "p.png"
            UVLayoutService.draw_uv_layout(coords, str(default_png),
                                           image_size=(100, 100), line_color="black")
            UVLayoutService.draw_uv_layout(coords, str(dots_png), image_size=(100, 100),
                                           line_color="black", point_size=3)
            d = Image.open(str(default_png)).convert("RGB")
            p = Image.open(str(dots_png)).convert("RGB")
            self.assertFalse(d.getpixel(off)[0] < 128)  # без точек — бело
            self.assertTrue(p.getpixel(off)[0] < 128)   # с точками — закрашено

    def test_draw_uv_layout_no_coords(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "uv.png"
            with self.assertRaises(ValueError):
                UVLayoutService.draw_uv_layout([], str(output), image_size=(64, 64))

    def test_generate_uv_layout_no_coords(self):
        content = "version 1\nend\n"
        with tempfile.TemporaryDirectory() as tmp:
            smd_path = Path(tmp) / "file.smd"
            output = Path(tmp) / "uv.png"
            smd_path.write_text(content, encoding="utf-8")
            result = UVLayoutService.generate_uv_layout_from_smd(str(smd_path), str(output))
            self.assertFalse(result)
    
    def test_generate_uv_layout_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            smd_path = Path(tmp) / "file.smd"
            smd_path.write_text("triangles\nend\n", encoding="utf-8")
            output = Path(tmp) / "uv.png"
            with patch.object(UVLayoutService, "parse_smd_uv_coordinates", side_effect=RuntimeError("boom")):
                result = UVLayoutService.generate_uv_layout_from_smd(str(smd_path), str(output))
            self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
