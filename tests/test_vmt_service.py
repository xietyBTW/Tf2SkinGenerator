import tempfile
import unittest
from pathlib import Path

from src.services.vmt_service import VMTService


class VMTServiceTests(unittest.TestCase):
    def test_cdmaterials_path_to_materials_path(self):
        materials_path, prefix = VMTService.cdmaterials_path_to_materials_path("materials\\models\\weapons\\c_models\\")
        self.assertEqual(materials_path, "materials/models/weapons/c_models")
        self.assertEqual(prefix, "c_models")

    def test_get_weapon_relpaths_special(self):
        rel_path, vmt, vtf = VMTService.get_weapon_relpaths("critHIT")
        self.assertIn("materials", rel_path)
        self.assertEqual(vmt, "crit.vmt")
        self.assertEqual(vtf, "crit.vtf")

    def test_get_weapon_relpaths_normal(self):
        rel_path, vmt, vtf = VMTService.get_weapon_relpaths("scout_c_scattergun")
        self.assertIn("c_models", rel_path)
        self.assertEqual(vmt, "c_scattergun.vmt")
        self.assertEqual(vtf, "c_scattergun.vtf")
    
    def test_get_weapon_relpaths_viewmodel(self):
        rel_path, vmt, vtf = VMTService.get_weapon_relpaths("scout_v_machete")
        self.assertIn("weapons", rel_path)
        self.assertIn("v_machete", rel_path)
        self.assertEqual(vmt, "v_machete.vmt")
        self.assertEqual(vtf, "v_machete.vtf")

    def test_get_weapon_relpaths_from_cdmaterials(self):
        rel_path, vmt, vtf = VMTService.get_weapon_relpaths_from_cdmaterials("vgui\\replay\\thumbnails\\models\\weapons\\c_models", "c_test")
        self.assertEqual(rel_path, "materials/vgui/replay/thumbnails/models/weapons/c_models")
        self.assertEqual(vmt, "c_test.vmt")
        self.assertEqual(vtf, "c_test.vtf")

    def test_create_vmt_template_from_cdmaterials(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            out_path = base / "out.vmt"
            VMTService.create_vmt_template_from_cdmaterials(str(out_path), "vgui\\replay\\thumbnails\\models\\c_models", "c_test")
            content = out_path.read_text(encoding="utf-8")
            self.assertIn("$basetexture", content.lower())
            self.assertIn("vgui/replay/thumbnails/models/c_models/c_test", content)
    
    def test_create_vmt_template_special_and_weapon(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            special_path = base / "crit.vmt"
            weapon_path = base / "weapon.vmt"
            VMTService.create_vmt_template(str(special_path), "critHIT")
            VMTService.create_vmt_template(str(weapon_path), "scout_c_scattergun")
            self.assertIn("UnlitGeneric", special_path.read_text(encoding="utf-8"))
            self.assertIn("VertexLitGeneric", weapon_path.read_text(encoding="utf-8"))

    def test_update_vmt_basetexture_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vmt_path = base / "a.vmt"
            vmt_path.write_text('"VertexLitGeneric"\n{\n\t"$baseTexture" "old/path"\n}', encoding="utf-8")
            VMTService.update_vmt_basetexture_path(str(vmt_path), "vgui\\replay\\thumbnails\\models\\c_models", "c_test")
            content = vmt_path.read_text(encoding="utf-8")
            self.assertIn("vgui/replay/thumbnails/models/c_models/c_test", content)
    
    def test_update_vmt_basetexture_insert_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vmt_path = base / "a.vmt"
            vmt_path.write_text('"VertexLitGeneric"\n{\n\t"$envmap" "env_cubemap"\n}', encoding="utf-8")
            VMTService.update_vmt_basetexture_path(str(vmt_path), "models\\c_models", "c_test")
            content = vmt_path.read_text(encoding="utf-8")
            self.assertIn("$basetexture", content.lower())
            self.assertIn("models/c_models/c_test", content)
    
    def test_update_vmt_basetexture_path_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vmt_path = base / "missing.vmt"
            VMTService.update_vmt_basetexture_path(str(vmt_path), "models\\c_models", "c_test")
            self.assertFalse(vmt_path.exists())
    
    def test_update_vmt_bumpmap_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vmt_path = base / "a.vmt"
            vmt_path.write_text('"VertexLitGeneric"\n{\n\t"$bumpmap" "old/path"\n}', encoding="utf-8")
            VMTService.update_vmt_bumpmap_path(str(vmt_path), "models\\c_models", "c_test_normal")
            content = vmt_path.read_text(encoding="utf-8")
            self.assertIn("models/c_models/c_test_normal", content)
    
    def test_update_vmt_bumpmap_insert_after_basetexture(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vmt_path = base / "a.vmt"
            vmt_path.write_text('"VertexLitGeneric"\n{\n\t"$basetexture" "path/base"\n}', encoding="utf-8")
            VMTService.update_vmt_bumpmap_path(str(vmt_path), "models\\c_models", "c_test_normal")
            content = vmt_path.read_text(encoding="utf-8")
            self.assertIn("$bumpmap", content)
            self.assertIn("models/c_models/c_test_normal", content)
    
    def test_update_vmt_bumpmap_insert_when_no_basetexture(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vmt_path = base / "a.vmt"
            vmt_path.write_text('"VertexLitGeneric"\n{\n}', encoding="utf-8")
            VMTService.update_vmt_bumpmap_path(str(vmt_path), "models\\c_models", "c_test_normal")
            content = vmt_path.read_text(encoding="utf-8")
            self.assertIn("$bumpmap", content)


if __name__ == "__main__":
    unittest.main()
