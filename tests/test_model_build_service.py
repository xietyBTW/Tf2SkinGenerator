import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.services.model_build_service import ModelBuildService


class ModelBuildServiceTests(unittest.TestCase):
    def test_decompile_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with self.assertRaises(FileNotFoundError):
                ModelBuildService.decompile(str(base / "missing.mdl"), str(base), str(base / "crowbar.exe"))
            mdl_path = base / "model.mdl"
            mdl_path.write_text("mdl", encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                ModelBuildService.decompile(str(mdl_path), str(base), str(base / "crowbar.exe"))

    def test_decompile_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            mdl = base / "a.mdl"
            crowbar = base / "crowbar.exe"
            mdl.write_text("x", encoding="utf-8")
            crowbar.write_text("x", encoding="utf-8")
            out_dir = base / "out"
            def fake_run(*args, **kwargs):
                (out_dir / "a.qc").write_text("$modelname \"weapons/a.mdl\"", encoding="utf-8")
                return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            with patch("src.services.model_build_service.subprocess.run", side_effect=fake_run):
                result = ModelBuildService.decompile(str(mdl), str(out_dir), str(crowbar))
            self.assertTrue(result.endswith(".qc"))

    def test_decompile_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            mdl = base / "a.mdl"
            crowbar = base / "crowbar.exe"
            mdl.write_text("x", encoding="utf-8")
            crowbar.write_text("x", encoding="utf-8")
            out_dir = base / "out"
            def fake_run(*args, **kwargs):
                return type("R", (), {"returncode": 1, "stdout": "bad", "stderr": "err"})()
            with patch("src.services.model_build_service.subprocess.run", side_effect=fake_run):
                with self.assertRaises(RuntimeError):
                    ModelBuildService.decompile(str(mdl), str(out_dir), str(crowbar))

    def test_extract_cdmaterials_and_modelname(self):
        with tempfile.TemporaryDirectory() as tmp:
            qc = Path(tmp) / "a.qc"
            qc.write_text('$cdmaterials ""\n$cdmaterials "models\\c_models"\n$modelname "weapons/c.mdl"', encoding="utf-8")
            cd = ModelBuildService.extract_cdmaterials_path_from_qc(str(qc))
            modelname = ModelBuildService.extract_modelname_path(str(qc))
            self.assertEqual(cd, "models\\c_models")
            self.assertEqual(modelname, "weapons/c.mdl")

    def test_extract_texturegroup_filename(self):
        content = "\n".join([
            "$texturegroup \"skinfamilies\"",
            "{",
            "{ \"c_scattergun\" \"c_scattergun_gold\" }",
            "}",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            qc = Path(tmp) / "a.qc"
            qc.write_text(content, encoding="utf-8")
            name = ModelBuildService.extract_texturegroup_filename(str(qc))
            self.assertEqual(name, "c_scattergun")
    
    def test_extract_texturegroup_filename_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            qc = Path(tmp) / "a.qc"
            qc.write_text("$modelname \"x\"", encoding="utf-8")
            name = ModelBuildService.extract_texturegroup_filename(str(qc))
            self.assertIsNone(name)
    
    def test_extract_cdmaterials_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            qc = Path(tmp) / "a.qc"
            qc.write_text("$modelname \"x\"", encoding="utf-8")
            self.assertIsNone(ModelBuildService.extract_cdmaterials_path_from_qc(str(qc)))
    
    def test_remove_lod_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "model.lod1").write_text("x", encoding="utf-8")
            (base / "model.LOD2").write_text("x", encoding="utf-8")
            (base / "model.mdl").write_text("x", encoding="utf-8")
            ModelBuildService.remove_lod_files(str(base))
            self.assertFalse((base / "model.lod1").exists())
            self.assertFalse((base / "model.LOD2").exists())
            self.assertTrue((base / "model.mdl").exists())
    
    def test_compile_success_and_missing_mdl(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            tf_dir = base / "tf"
            tf_dir.mkdir()
            out_dir = base / "out"
            qc_path = base / "model.qc"
            qc_path.write_text('$modelname "workshop_partner\\weapons\\c_models\\c_test\\c_test.mdl"', encoding="utf-8")
            studiomdl = base / "studiomdl.exe"
            studiomdl.write_text("exe", encoding="utf-8")
            model_dir = tf_dir / "models" / "workshop_partner" / "weapons" / "c_models" / "c_test"
            model_dir.mkdir(parents=True, exist_ok=True)
            (model_dir / "c_test.mdl").write_text("mdl", encoding="utf-8")
            (model_dir / "c_test.vvd").write_text("vvd", encoding="utf-8")
            def fake_run(*args, **kwargs):
                return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            with patch("src.services.model_build_service.subprocess.run", side_effect=fake_run):
                ModelBuildService.compile(str(qc_path), str(out_dir), str(studiomdl), str(tf_dir))
            self.assertTrue((out_dir / "c_test.mdl").exists())
            self.assertTrue((out_dir / "c_test.vvd").exists())

            for file_path in model_dir.iterdir():
                file_path.unlink()
            (model_dir / "c_test.vvd").write_text("vvd", encoding="utf-8")
            with patch("src.services.model_build_service.subprocess.run", side_effect=fake_run):
                with self.assertRaises(RuntimeError):
                    ModelBuildService.compile(str(qc_path), str(out_dir), str(studiomdl), str(tf_dir))

    def test_determine_weapon_type_and_path(self):
        w_type, path = ModelBuildService.determine_weapon_type_and_path("v_machete", "models\\workshop_partner\\weapons\\v_machete")
        self.assertEqual(w_type, "v")
        self.assertIn("vgui\\replay\\thumbnails\\", path)
        w_type2, path2 = ModelBuildService.determine_weapon_type_and_path("c_test", None)
        self.assertEqual(w_type2, "c")
        self.assertIn("c_models", path2)

    def test_patch_qc_file(self):
        content = "\n".join([
            "$modelname \"weapons/c_test.mdl\"",
            "$cdmaterials \"models\\c_models\"",
            "$lod 1",
            "{",
            "}",
            "$cdmaterials \"\"",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            qc = Path(tmp) / "a.qc"
            qc.write_text(content, encoding="utf-8")
            ModelBuildService.patch_qc_file(str(qc), "c_test")
            updated = qc.read_text(encoding="utf-8")
            self.assertIn("console\\models\\c_models", updated)
            self.assertNotIn("$lod", updated.lower())
    def test_extract_texturegroup_all_columns_red_and_blue(self):
        """Тест: texturegroup с двумя столбцами (RED и BLU)"""
        content = "\n".join([
            "$texturegroup \"skinfamilies\"",
            "{",
            "{ \"c_rocketlauncher\" \"c_rocketlauncher_blue\" }",
            "{ \"c_rocketlauncher_gold\" \"c_rocketlauncher_gold_blue\" }",
            "}",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            qc = Path(tmp) / "a.qc"
            qc.write_text(content, encoding="utf-8")
            columns = ModelBuildService.extract_texturegroup_all_columns(str(qc))
            self.assertEqual(columns, ["c_rocketlauncher", "c_rocketlauncher_blue"])
    
    def test_extract_texturegroup_all_columns_single(self):
        """Тест: texturegroup с одним столбцом (только RED, без BLU)"""
        content = "\n".join([
            "$texturegroup \"skinfamilies\"",
            "{",
            "{ \"c_scattergun\" }",
            "{ \"c_scattergun_gold\" }",
            "}",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            qc = Path(tmp) / "a.qc"
            qc.write_text(content, encoding="utf-8")
            columns = ModelBuildService.extract_texturegroup_all_columns(str(qc))
            self.assertEqual(columns, ["c_scattergun"])
    
    def test_extract_texturegroup_all_columns_missing(self):
        """Тест: нет $texturegroup в QC файле"""
        with tempfile.TemporaryDirectory() as tmp:
            qc = Path(tmp) / "a.qc"
            qc.write_text("$modelname \"x\"", encoding="utf-8")
            columns = ModelBuildService.extract_texturegroup_all_columns(str(qc))
            self.assertEqual(columns, [])
    
    def test_extract_texturegroup_all_columns_skips_gold(self):
        """Тест: если первая строка с суффиксом _gold, а вторая - базовая"""
        content = "\n".join([
            "$texturegroup \"skinfamilies\"",
            "{",
            "{ \"c_weapon_gold\" \"c_weapon_gold_blue\" }",
            "{ \"c_weapon\" \"c_weapon_blue\" }",
            "}",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            qc = Path(tmp) / "a.qc"
            qc.write_text(content, encoding="utf-8")
            columns = ModelBuildService.extract_texturegroup_all_columns(str(qc))
            # Должен выбрать базовую строку (без _gold), а не первую
            self.assertEqual(columns, ["c_weapon", "c_weapon_blue"])
    
    def test_extract_texturegroup_all_columns_file_not_found(self):
        """Тест: несуществующий QC файл"""
        columns = ModelBuildService.extract_texturegroup_all_columns("/nonexistent/path.qc")
        self.assertEqual(columns, [])


if __name__ == "__main__":
    unittest.main()
