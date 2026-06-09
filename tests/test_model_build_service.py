import os
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
    def test_extract_texturegroup_all_columns_with_extra_materials(self):
        """Тест: texturegroup со столбцами = доп. материалы (body + shell)"""
        content = "\n".join([
            "$texturegroup \"skinfamilies\"",
            "{",
            "{ \"c_flaregun\" \"c_flaregun_shell\" }",
            "{ \"c_flaregun_blue\" \"c_flaregun_shell_blue\" }",
            "}",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            qc = Path(tmp) / "a.qc"
            qc.write_text(content, encoding="utf-8")
            # extract_texturegroup_all_columns возвращает RED строку (все столбцы)
            columns = ModelBuildService.extract_texturegroup_all_columns(str(qc))
            self.assertEqual(columns, ["c_flaregun", "c_flaregun_shell"])
    
    def test_extract_texturegroup_all_columns_single_material(self):
        """Тест: texturegroup с одним столбцом (одним материалом)"""
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
            "{ \"c_weapon_gold\" }",
            "{ \"c_weapon\" }",
            "}",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            qc = Path(tmp) / "a.qc"
            qc.write_text(content, encoding="utf-8")
            columns = ModelBuildService.extract_texturegroup_all_columns(str(qc))
            # Должен выбрать базовую строку (без _gold)
            self.assertEqual(columns, ["c_weapon"])
    
    def test_extract_texturegroup_all_columns_file_not_found(self):
        """Тест: несуществующий QC файл"""
        columns = ModelBuildService.extract_texturegroup_all_columns("/nonexistent/path.qc")
        self.assertEqual(columns, [])
    
    # === Тесты для extract_texturegroup_structure ===
    
    def test_extract_texturegroup_structure_with_teams_and_extras(self):
        """Тест: полная структура с RED/BLU командами и доп. материалами"""
        content = "\n".join([
            "$texturegroup \"skinfamilies\"",
            "{",
            "{ \"c_flaregun\" \"c_flaregun_shell\" }",
            "{ \"c_flaregun_blue\" \"c_flaregun_shell_blue\" }",
            "}",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            qc = Path(tmp) / "a.qc"
            qc.write_text(content, encoding="utf-8")
            info = ModelBuildService.extract_texturegroup_structure(str(qc))
            
            self.assertEqual(info['red_row'], ["c_flaregun", "c_flaregun_shell"])
            self.assertEqual(info['blu_row'], ["c_flaregun_blue", "c_flaregun_shell_blue"])
            self.assertEqual(info['main_texture'], "c_flaregun")
            self.assertEqual(info['extra_materials'], ["c_flaregun_shell"])
    
    def test_extract_texturegroup_structure_teams_only(self):
        """Тест: RED/BLU команды без доп. материалов"""
        content = "\n".join([
            "$texturegroup \"skinfamilies\"",
            "{",
            "{ \"c_rocketlauncher\" }",
            "{ \"c_rocketlauncher_blue\" }",
            "}",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            qc = Path(tmp) / "a.qc"
            qc.write_text(content, encoding="utf-8")
            info = ModelBuildService.extract_texturegroup_structure(str(qc))
            
            self.assertEqual(info['red_row'], ["c_rocketlauncher"])
            self.assertEqual(info['blu_row'], ["c_rocketlauncher_blue"])
            self.assertEqual(info['main_texture'], "c_rocketlauncher")
            self.assertEqual(info['extra_materials'], [])
    
    def test_extract_texturegroup_structure_no_teams(self):
        """Тест: нет BLU команды (только одна строка)"""
        content = "\n".join([
            "$texturegroup \"skinfamilies\"",
            "{",
            "{ \"c_scattergun\" }",
            "}",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            qc = Path(tmp) / "a.qc"
            qc.write_text(content, encoding="utf-8")
            info = ModelBuildService.extract_texturegroup_structure(str(qc))
            
            self.assertEqual(info['red_row'], ["c_scattergun"])
            self.assertEqual(info['blu_row'], [])
            self.assertEqual(info['main_texture'], "c_scattergun")
            self.assertEqual(info['extra_materials'], [])
    
    def test_extract_texturegroup_structure_with_gold_variants(self):
        """Тест: RED/BLU + gold варианты (gold строки должны игнорироваться)"""
        content = "\n".join([
            "$texturegroup \"skinfamilies\"",
            "{",
            "{ \"c_rocketlauncher\" }",
            "{ \"c_rocketlauncher_blue\" }",
            "{ \"c_rocketlauncher_gold\" }",
            "{ \"c_rocketlauncher_gold_blue\" }",
            "}",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            qc = Path(tmp) / "a.qc"
            qc.write_text(content, encoding="utf-8")
            info = ModelBuildService.extract_texturegroup_structure(str(qc))
            
            # Gold строки должны быть отфильтрованы
            self.assertEqual(info['red_row'], ["c_rocketlauncher"])
            self.assertEqual(info['blu_row'], ["c_rocketlauncher_blue"])
            self.assertEqual(info['extra_materials'], [])
            self.assertEqual(len(info['all_rows']), 4)
    
    def test_extract_texturegroup_structure_extras_only(self):
        """Тест: доп. материалы без BLU команды"""
        content = "\n".join([
            "$texturegroup \"skinfamilies\"",
            "{",
            "{ \"c_flaregun\" \"c_flaregun_shell\" }",
            "}",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            qc = Path(tmp) / "a.qc"
            qc.write_text(content, encoding="utf-8")
            info = ModelBuildService.extract_texturegroup_structure(str(qc))
            
            self.assertEqual(info['red_row'], ["c_flaregun", "c_flaregun_shell"])
            self.assertEqual(info['blu_row'], [])
            self.assertEqual(info['main_texture'], "c_flaregun")
            self.assertEqual(info['extra_materials'], ["c_flaregun_shell"])
    
    def test_extract_texturegroup_structure_empty(self):
        """Тест: нет $texturegroup"""
        with tempfile.TemporaryDirectory() as tmp:
            qc = Path(tmp) / "a.qc"
            qc.write_text("$modelname \"x\"", encoding="utf-8")
            info = ModelBuildService.extract_texturegroup_structure(str(qc))
            
            self.assertEqual(info['red_row'], [])
            self.assertEqual(info['blu_row'], [])
            self.assertIsNone(info['main_texture'])
            self.assertEqual(info['extra_materials'], [])

    # === Тесты для extract_extra_body_smds ===
    
    def test_extract_extra_body_smds_with_shell(self):
        """Тест: модель с дополнительной частью (shell)"""
        qc_content = "\n".join([
            "$modelname \"weapons/c_flaregun.mdl\"",
            "$body studio \"c_flaregun_reference.smd\"",
            "$bodygroup \"shell\"",
            "{",
            "    studio \"c_flaregun_shell.smd\"",
            "    blank",
            "}",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            qc = Path(tmp) / "c_flaregun.qc"
            qc.write_text(qc_content, encoding="utf-8")
            # Создаем SMD файлы чтобы extract нашел их
            (Path(tmp) / "c_flaregun_reference.smd").write_text("version 1", encoding="utf-8")
            (Path(tmp) / "c_flaregun_shell.smd").write_text("version 1", encoding="utf-8")
            
            extras = ModelBuildService.extract_extra_body_smds(str(qc), "c_flaregun")
            self.assertEqual(len(extras), 1)
            self.assertIn("c_flaregun_shell.smd", os.path.basename(extras[0]))
    
    def test_extract_extra_body_smds_no_extras(self):
        """Тест: модель без дополнительных частей"""
        qc_content = "\n".join([
            "$modelname \"weapons/c_bat.mdl\"",
            "$body studio \"c_bat_reference.smd\"",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            qc = Path(tmp) / "c_bat.qc"
            qc.write_text(qc_content, encoding="utf-8")
            (Path(tmp) / "c_bat_reference.smd").write_text("version 1", encoding="utf-8")
            
            extras = ModelBuildService.extract_extra_body_smds(str(qc), "c_bat")
            self.assertEqual(extras, [])
    
    def test_extract_extra_body_smds_filters_physics_and_anim(self):
        """Тест: physics и animation файлы должны быть отфильтрованы"""
        qc_content = "\n".join([
            "$modelname \"weapons/c_flaregun.mdl\"",
            "$body studio \"c_flaregun_reference.smd\"",
            "$bodygroup \"shell\"",
            "{",
            "    studio \"c_flaregun_shell.smd\"",
            "}",
            "$collisionmodel \"c_flaregun_physics.smd\"",
            "{",
            "}",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            qc = Path(tmp) / "c_flaregun.qc"
            qc.write_text(qc_content, encoding="utf-8")
            (Path(tmp) / "c_flaregun_reference.smd").write_text("version 1", encoding="utf-8")
            (Path(tmp) / "c_flaregun_shell.smd").write_text("version 1", encoding="utf-8")
            (Path(tmp) / "c_flaregun_physics.smd").write_text("version 1", encoding="utf-8")
            
            extras = ModelBuildService.extract_extra_body_smds(str(qc), "c_flaregun")
            self.assertEqual(len(extras), 1)
            self.assertIn("c_flaregun_shell.smd", os.path.basename(extras[0]))
    
    def test_extract_extra_body_smds_missing_file(self):
        """Тест: если SMD файл указан в QC, но не существует - пропускаем"""
        qc_content = "\n".join([
            "$body studio \"c_weapon_reference.smd\"",
            "$bodygroup \"shell\"",
            "{",
            "    studio \"c_weapon_shell.smd\"",
            "}",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            qc = Path(tmp) / "c_weapon.qc"
            qc.write_text(qc_content, encoding="utf-8")
            (Path(tmp) / "c_weapon_reference.smd").write_text("version 1", encoding="utf-8")
            # НЕ создаем c_weapon_shell.smd
            
            extras = ModelBuildService.extract_extra_body_smds(str(qc), "c_weapon")
            self.assertEqual(extras, [])
    
    def test_extract_extra_body_smds_multiple_bodygroups(self):
        """Тест: модель с несколькими bodygroup"""
        qc_content = "\n".join([
            "$body studio \"c_weapon_reference.smd\"",
            "$bodygroup \"shell\"",
            "{",
            "    studio \"c_weapon_shell.smd\"",
            "    blank",
            "}",
            "$bodygroup \"scope\"",
            "{",
            "    studio \"c_weapon_scope.smd\"",
            "    blank",
            "}",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            qc = Path(tmp) / "c_weapon.qc"
            qc.write_text(qc_content, encoding="utf-8")
            (Path(tmp) / "c_weapon_reference.smd").write_text("version 1", encoding="utf-8")
            (Path(tmp) / "c_weapon_shell.smd").write_text("version 1", encoding="utf-8")
            (Path(tmp) / "c_weapon_scope.smd").write_text("version 1", encoding="utf-8")
            
            extras = ModelBuildService.extract_extra_body_smds(str(qc), "c_weapon")
            self.assertEqual(len(extras), 2)
            basenames = [os.path.basename(e) for e in extras]
            self.assertIn("c_weapon_shell.smd", basenames)
            self.assertIn("c_weapon_scope.smd", basenames)

    def test_generate_texturegroup_block_empty(self):
        self.assertEqual(ModelBuildService.generate_texturegroup_block(["m"], {}), "")

    def test_generate_texturegroup_block_only_variant_materials(self):
        # В группу попадают только переменные материалы; постоянные опускаются.
        block = ModelBuildService.generate_texturegroup_block(
            ["body", "lefteye"], {1: {"lefteye": "lefteye_bloody"}},
        )
        self.assertIn('"lefteye"', block)
        self.assertIn('"lefteye_bloody"', block)
        self.assertNotIn('body', block)   # постоянный материал не пишется

    def test_generate_texturegroup_block_lowercases_names(self):
        # Имена приводятся к нижнему регистру (иначе фиолетовые текстуры).
        block = ModelBuildService.generate_texturegroup_block(
            ["Material.001"], {1: {"Material.001": "Material.001_Bloody"}},
        )
        self.assertIn('"material.001"', block)
        self.assertIn('"material.001_bloody"', block)
        self.assertNotIn("Material.001", block)

    def test_generate_texturegroup_block_skin0_is_base(self):
        block = ModelBuildService.generate_texturegroup_block(
            ["mat"], {2: {"mat": "mat_v2"}},
        )
        lines = [l for l in block.splitlines() if l.strip().startswith('{') and '"' in l]
        # 3 строки скинов: skin0=base, skin1=наследует base, skin2=variant
        self.assertEqual(lines[0].strip(), '{ "mat" }')
        self.assertEqual(lines[1].strip(), '{ "mat" }')
        self.assertEqual(lines[2].strip(), '{ "mat_v2" }')


if __name__ == "__main__":
    unittest.main()
