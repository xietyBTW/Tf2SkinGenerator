import tempfile
import unittest
from pathlib import Path

from src.services.vmt_service import VMTService


class VMTServiceTests(unittest.TestCase):
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
    
    def test_animated_bumpmap_adds_second_proxy(self):
        """Гифка + normal map: прокси $bumpmap добавляется, $basetexture не теряется."""
        with tempfile.TemporaryDirectory() as tmp:
            vmt_path = Path(tmp) / "a.vmt"
            vmt_path.write_text(
                '"VertexLitGeneric"\n{\n\t"$basetexture" "models/c_test"\n'
                '\t"$bumpmap" "models/c_test_normal"\n}',
                encoding="utf-8")

            VMTService.enable_animated_basetexture(str(vmt_path), 12)
            VMTService.enable_animated_bumpmap(str(vmt_path), 12)
            content = vmt_path.read_text(encoding="utf-8").lower()

            self.assertIn('"animatedtexturevar" "$basetexture"', content)
            self.assertIn('"animatedtexturevar" "$bumpmap"', content)
            self.assertIn('"$frame" "0"', content)
            self.assertIn('"$bumpframe" "0"', content)
            self.assertIn('"animatedtextureframenumvar" "$bumpframe"', content)
            self.assertEqual(content.count('"animatedtexture"'), 2)
            # Оба прокси на одном fps, иначе бамп уедет по фазе от картинки.
            self.assertEqual(content.count('"animatedtextureframerate" "12"'), 2)

    def test_animated_bumpmap_idempotent(self):
        """Повторный вызов не дублирует прокси, только обновляет fps."""
        with tempfile.TemporaryDirectory() as tmp:
            vmt_path = Path(tmp) / "a.vmt"
            vmt_path.write_text(
                '"VertexLitGeneric"\n{\n\t"$bumpmap" "models/c_test_normal"\n}',
                encoding="utf-8")
            VMTService.enable_animated_bumpmap(str(vmt_path), 10)
            VMTService.enable_animated_bumpmap(str(vmt_path), 25)
            content = vmt_path.read_text(encoding="utf-8").lower()
            self.assertEqual(content.count('"animatedtexturevar" "$bumpmap"'), 1)
            self.assertIn('"animatedtextureframerate" "25"', content)
            self.assertNotIn('"animatedtextureframerate" "10"', content)

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


def test_bumpmap_skips_commented_line(tmp_path):
    """У снайперской винтовки $bumpmap только в комментарии: нужна живая строка."""
    from src.services.vmt_service import VMTService
    vmt = tmp_path / 'c_sniperrifle.vmt'
    vmt.write_text('"VertexLitGeneric"\n{\n\t"$basetexture"\t"models/weapons/c_items/c_sniperrifle"\n'
                   '//\t"$bumpmap" "models/weapons/w_sniperrifle/w_sniperrifle_normal"\n}\n',
                   encoding='utf-8')
    VMTService.update_vmt_bumpmap_path(str(vmt), 'models/weapons/c_items', 'c_sniperrifle_normal')
    VMTService.update_vmt_bumpmap_path(str(vmt), 'models/weapons/c_items', 'c_sniperrifle_normal')
    lines = vmt.read_text(encoding='utf-8').splitlines()
    live = [line for line in lines if '$bumpmap' in line and not line.startswith('//')]
    assert live == ['\t"$bumpmap" "models/weapons/c_items/c_sniperrifle_normal"']
    assert '//\t"$bumpmap" "models/weapons/w_sniperrifle/w_sniperrifle_normal"' in lines


def test_has_live_param_ignores_comments():
    from src.services.vmt_service import VMTService
    text = '"VertexLitGeneric"\n{\n//\t"$bumpmap" "a"\n\t"$bumpmap2" "b"\n}\n'
    assert not VMTService.has_live_param(text, '$bumpmap')
    assert VMTService.has_live_param(text + '\t$BumpMap models/x\n', '$bumpmap')
