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
