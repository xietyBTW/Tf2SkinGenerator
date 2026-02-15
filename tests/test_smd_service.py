import tempfile
import unittest
from pathlib import Path

from src.services.smd_service import SMDService


class SMDServiceTests(unittest.TestCase):
    def test_parse_and_merge_triangles(self):
        content = "\n".join([
            "version 1",
            "nodes",
            "0 \"root\" -1",
            "end",
            "skeleton",
            "time 0",
            "0 0 0 0 0 0 0",
            "end",
            "triangles",
            "mat1",
            "0 0 0 0 0 0 0 0 0",
            "0 0 0 0 0 0 0 0 0",
            "0 0 0 0 0 0 0 0 0",
        ])
        parsed = SMDService._parse_smd_file(content)
        self.assertTrue(parsed["version"])
        self.assertTrue(parsed["nodes"])
        self.assertTrue(parsed["skeleton"])
        self.assertEqual(parsed["material_names"], ["mat1"])
        merged = SMDService._merge_triangles(parsed["triangles_data"], ["orig"])
        self.assertIn("orig", merged)

    def test_replace_model_sections(self):
        user_content = "\n".join([
            "version 1",
            "nodes",
            "0 \"user\" -1",
            "end",
            "skeleton",
            "time 0",
            "0 0 0 0 0 0 0",
            "end",
            "triangles",
            "user_mat",
            "0 0 0 0 0 0 0 0 0",
            "0 0 0 0 0 0 0 0 0",
            "0 0 0 0 0 0 0 0 0",
        ])
        original_content = "\n".join([
            "version 1",
            "nodes",
            "0 \"orig\" -1",
            "end",
            "skeleton",
            "time 0",
            "0 0 0 0 0 0 0",
            "end",
            "triangles",
            "orig_mat",
            "0 0 0 0 0 0 0 0 0",
            "0 0 0 0 0 0 0 0 0",
            "0 0 0 0 0 0 0 0 0",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            user_path = base / "user.smd"
            orig_path = base / "orig.smd"
            out_path = base / "out.smd"
            user_path.write_text(user_content, encoding="utf-8")
            orig_path.write_text(original_content, encoding="utf-8")
            result = SMDService.replace_model_sections(str(user_path), str(orig_path), str(out_path))
            self.assertEqual(result, str(out_path))
            output = out_path.read_text(encoding="utf-8")
            self.assertIn("\"orig\"", output)
            self.assertIn("orig_mat", output)
    
    def test_replace_model_sections_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            user_path = base / "user.smd"
            orig_path = base / "orig.smd"
            user_path.write_text("x", encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                SMDService.replace_model_sections(str(user_path), str(orig_path))
    
    def test_replace_model_sections_invalid_smd(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            user_path = base / "user.smd"
            orig_path = base / "orig.smd"
            user_path.write_text("bad", encoding="utf-8")
            orig_path.write_text("bad", encoding="utf-8")
            result = SMDService.replace_model_sections(str(user_path), str(orig_path))
            self.assertEqual(result, str(user_path))
            self.assertEqual(user_path.read_text(encoding="utf-8"), "triangles")

    def test_find_reference_smd(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "weapon_reference.smd").write_text("x", encoding="utf-8")
            found = SMDService.find_reference_smd(str(base), "weapon")
            self.assertTrue(found.endswith("weapon_reference.smd"))
    
    def test_find_reference_smd_fallbacks(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "weapon_anim.smd").write_text("x", encoding="utf-8")
            (base / "weapon_reference_custom.smd").write_text("x", encoding="utf-8")
            found = SMDService.find_reference_smd(str(base), "weapon")
            self.assertTrue(found.endswith("weapon_reference_custom.smd"))
    
    def test_find_reference_smd_non_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "weapon_physics.smd").write_text("x", encoding="utf-8")
            (base / "weapon_anim.smd").write_text("x", encoding="utf-8")
            (base / "weapon_mesh.smd").write_text("x", encoding="utf-8")
            found = SMDService.find_reference_smd(str(base), "weapon")
            self.assertTrue(found.endswith("weapon_mesh.smd"))
    
    def test_merge_triangles_without_original_names(self):
        merged = SMDService._merge_triangles([("mat", ["1 2 3"])], [])
        self.assertIn("mat", merged)
    
    def test_merge_triangles_empty(self):
        merged = SMDService._merge_triangles([], [])
        self.assertEqual(merged.strip(), "triangles")


if __name__ == "__main__":
    unittest.main()
