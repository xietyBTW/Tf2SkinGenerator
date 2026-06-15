import builtins
import contextlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from src.data.translations import TRANSLATIONS
from src.services.build_context import BuildContext
from src.services.build_service import BuildService
from src.services.vpk_service import VPKService
from src.shared.exceptions import VPKCreationError, RequiredFileMissingError as SharedFileNotFoundError


class VPKServiceTests(unittest.TestCase):
    def test_resolve_weapon_key_weapon(self):
        # Обычное оружие: weapon_key = суффикс после первого '_'
        self.assertEqual(VPKService._resolve_weapon_key("scout_c_scattergun", None), ("c_scattergun", None))
        # Без '_' — возвращаем сам mode
        self.assertEqual(VPKService._resolve_weapon_key("custom", None), ("custom", None))

    def test_resolve_weapon_key_hat(self):
        wk, err = VPKService._resolve_weapon_key("hat", "models/player/items/all_class/foo.mdl")
        self.assertEqual(wk, "foo")
        self.assertIsNone(err)

    def test_resolve_weapon_key_spy_masks(self):
        from src.data.player_characters import SPY_MASK_MODE_KEY
        wk, err = VPKService._resolve_weapon_key(SPY_MASK_MODE_KEY, None)
        self.assertEqual(wk, "spy")
        self.assertIsNone(err)

    def test_resolve_weapon_key_hands_uses_arm_model(self):
        from src.data.player_hands import HAND_MODES
        mode = next(iter(HAND_MODES))
        expected = HAND_MODES[mode].get("arm_model")
        wk, err = VPKService._resolve_weapon_key(mode, None)
        self.assertEqual(wk, expected)
        self.assertIsNone(err)

    def test_validate_build_params_errors(self):
        t = TRANSLATIONS["en"]
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            img = base / "img.png"
            Image.new("RGB", (2, 2), color="red").save(img)
            self.assertEqual(VPKService._validate_build_params("", "m", "a.vpk", (1, 1), "DXT1", "x", t), t["error_image_not_specified"])
            self.assertEqual(VPKService._validate_build_params(str(img), "", "a.vpk", (1, 1), "DXT1", "x", t), t["error_mode_not_specified"])
            self.assertEqual(VPKService._validate_build_params(str(img), "m", "", (1, 1), "DXT1", "x", t), t["error_filename_not_specified"])
            self.assertEqual(VPKService._validate_build_params(str(img), "m", "a.txt", (1, 1), "DXT1", "x", t), t["error_filename_no_vpk"])
            self.assertEqual(VPKService._validate_build_params(str(img), "m", "a.vpk", (1, ), "DXT1", "x", t), t["error_size_invalid"])
            self.assertEqual(VPKService._validate_build_params(str(img), "m", "a.vpk", ("1", 1), "DXT1", "x", t), t["error_size_not_int"])
            self.assertEqual(VPKService._validate_build_params(str(img), "m", "a.vpk", (0, 1), "DXT1", "x", t), t["error_size_not_positive"])
            self.assertIn(t["error_format_invalid"].split(":")[0], VPKService._validate_build_params(str(img), "m", "a.vpk", (1, 1), "BAD", "x", t))

    def test_validate_build_params_custom_vtf(self):
        t = TRANSLATIONS["en"]
        self.assertEqual(VPKService._validate_build_params("a", "m", "a.vpk", (1, 1), "DXT1", "x", t, custom_vtf_path="missing"), t["error_custom_vtf_not_found"].format(path="missing"))
    
    def test_validate_build_params_tf2_root_errors(self):
        t = TRANSLATIONS["en"]
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            img = base / "img.png"
            Image.new("RGB", (2, 2), color="red").save(img)
            self.assertEqual(
                VPKService._validate_build_params(str(img), "scout_c_scattergun", "a.vpk", (1, 1), "DXT1", "missing", t),
                t["error_tf2_not_found"].format(path="missing")
            )
            not_dir = base / "file.txt"
            not_dir.write_text("x", encoding="utf-8")
            self.assertEqual(
                VPKService._validate_build_params(str(img), "scout_c_scattergun", "a.vpk", (1, 1), "DXT1", str(not_dir), t),
                t["error_tf2_not_dir"].format(path=str(not_dir))
            )
    
    def test_validate_build_params_custom_vtf_not_file(self):
        t = TRANSLATIONS["en"]
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            dir_path = base / "dir"
            dir_path.mkdir()
            self.assertEqual(
                VPKService._validate_build_params("a", "m", "a.vpk", (1, 1), "DXT1", "x", t, custom_vtf_path=str(dir_path)),
                t["error_custom_vtf_not_file"].format(path=str(dir_path))
            )

    def test_parse_vtf_flags_and_options(self):
        from src.services.texture_service import TextureService
        flags, options = TextureService.parse_vtf_flags_and_options(["NOMIP", "CLAMPS"])
        self.assertEqual(flags, ["CLAMPS"])
        self.assertTrue(options["nomipmaps"])

    def test_process_image_rgb_and_rgba(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            rgb_path = base / "rgb.png"
            rgba_path = base / "rgba.png"
            Image.new("RGB", (10, 10), color="red").save(rgb_path)
            Image.new("RGBA", (10, 10), color=(255, 0, 0, 128)).save(rgba_path)
            out_rgb = base / "out_rgb.png"
            out_rgba = base / "out_rgba.png"
            VPKService._process_image(str(rgb_path), str(out_rgb), (4, 4))
            VPKService._process_image(str(rgba_path), str(out_rgba), (4, 4))
            self.assertTrue(out_rgb.exists())
            self.assertTrue(out_rgba.exists())
    
    def test_process_image_missing(self):
        with self.assertRaises(builtins.FileNotFoundError):
            VPKService._process_image("missing.png", "out.png", (4, 4))

    def test_create_vtf_builds_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            png_path = base / "img.png"
            Image.new("RGBA", (8, 8), color=(255, 0, 0, 128)).save(png_path)
            with patch("src.services.texture_service.TextureService.get_vtf_tool", return_value=Path("vtf.exe")):
                with patch("src.services.texture_service.subprocess.run") as run:
                    run.return_value = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
                    VPKService._create_vtf(str(png_path), str(base), "DXT1", ["CLAMPS"], {"nomipmaps": True})
                    args = run.call_args[0][0]
                    self.assertIn("-alphaformat", args)
                    self.assertIn("-nomipmaps", args)
    
    def test_create_vtf_error(self):
        from src.shared.exceptions import VTFCreationError
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            png_path = base / "img.png"
            Image.new("RGB", (8, 8), color="red").save(png_path)
            with patch("src.services.texture_service.TextureService.get_vtf_tool", return_value=Path("vtf.exe")):
                def fake_run(*args, **kwargs):
                    return type("R", (), {"returncode": 1, "stdout": "bad", "stderr": "err"})()
                with patch("src.services.texture_service.subprocess.run", side_effect=fake_run):
                    with self.assertRaises(VTFCreationError) as cm:
                        VPKService._create_vtf(str(png_path), str(base), "DXT1", [], {})
                    # Сообщение должно содержать вывод VTFCmd
                    self.assertIn("bad", str(cm.exception))
                    self.assertIn("err", str(cm.exception))

    def test_create_vpk_file_success_and_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ctx = BuildContext("id", "m", "w", base / "ctx")
            ctx.create_directories()
            vpkroot_parent = ctx.vpkroot_dir.parent
            temp_vpk = vpkroot_parent / "vpkroot.vpk"

            def fake_run(*args, **kwargs):
                temp_vpk.write_bytes(b"vpk")
                return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

            with patch("src.services.packaging_service.PackagingService.get_vpk_tool", return_value=Path("vpk.exe")):
                with patch("src.services.packaging_service.subprocess.run", side_effect=fake_run):
                    output = VPKService._create_vpk_file(ctx, "out.vpk", export_folder=str(base))
                    self.assertTrue(Path(output).exists())

            with patch("src.services.packaging_service.PackagingService.get_vpk_tool", return_value=Path("vpk.exe")):
                with patch("src.services.packaging_service.subprocess.run", return_value=type("R", (), {"returncode": 1, "stdout": "bad", "stderr": "err"})()):
                    with self.assertRaises(VPKCreationError):
                        VPKService._create_vpk_file(ctx, "out2.vpk", export_folder=str(base))
            
            with patch("src.services.packaging_service.PackagingService.get_vpk_tool", return_value=Path("vpk.exe")):
                with patch("src.services.packaging_service.subprocess.run", return_value=type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()):
                    with self.assertRaises(SharedFileNotFoundError):
                        VPKService._create_vpk_file(ctx, "out3.vpk", export_folder=str(base))

    def test_copy_compiled_models_to_vpkroot(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ctx = BuildContext("id", "m", "w", base / "ctx")
            ctx.create_directories()
            (ctx.compile_dir / "v_test.mdl").write_text("x", encoding="utf-8")
            (ctx.compile_dir / "v_test.vvd").write_text("x", encoding="utf-8")
            with patch("src.services.model_service.ModelBuildService.extract_modelname_path", return_value="models/weapons/v_test.mdl"):
                VPKService._copy_compiled_models_to_vpkroot(ctx, "qc")
            target = ctx.vpkroot_dir / "models" / "models" / "weapons" / "v_test.mdl"
            self.assertTrue(target.exists())

    def test_build_special_mode_vpk_with_mod_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ctx = BuildContext("id", "critHIT", "critHIT", base / "ctx")
            ctx.create_directories()
            vmt_filename = "crit.vmt"
            rel_path = "materials/effects"
            mod_data = base / "mod_data"
            mod_data.mkdir(parents=True, exist_ok=True)
            (mod_data / vmt_filename).write_text("vmt", encoding="utf-8")
            pcf_file = mod_data / "crit.pcf"
            pcf_file.write_text("pcf", encoding="utf-8")
            with patch("src.services.build_service.DirectoryPaths.MOD_DATA_DIR", mod_data):
                with patch("src.services.build_service.VMTService.get_weapon_relpaths", return_value=(rel_path, vmt_filename, "crit.vtf")):
                    with patch("src.services.build_service.TextureService.create_vtf"):
                        with patch("src.services.build_service.TextureService.process_image"):
                            ok, msg, _ = BuildService.build_special_mode_vpk(
                                ctx, "critHIT", str(base / "img.png"), (4, 4), "DXT1", [], vtf_options=None
                            )
            self.assertTrue(ok, msg)
            self.assertTrue((ctx.vpkroot_dir / "particles" / "crit.pcf").exists())
    
    def test_build_special_mode_vpk_custom_vtf_and_edited_vmt(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ctx = BuildContext("id", "critHIT", "critHIT", base / "ctx")
            ctx.create_directories()
            rel_path = "materials/effects"
            vmt_filename = "crit.vmt"
            custom_vtf = base / "custom.vtf"
            custom_vtf.write_text("vtf", encoding="utf-8")
            edited_vmt = base / "edited.vmt"
            edited_vmt.write_text("vmt", encoding="utf-8")
            with patch("src.services.build_service.VMTService.get_weapon_relpaths", return_value=(rel_path, vmt_filename, "crit.vtf")):
                with patch("src.services.edited_vmt_service.EditedVMTService.get_edited_vmt", return_value=str(edited_vmt)):
                    ok, msg, vmt_to_delete = BuildService.build_special_mode_vpk(
                        ctx, "critHIT", "img.png", (4, 4), "DXT1", [], vtf_options=None, custom_vtf_path=str(custom_vtf)
                    )
            self.assertTrue(ok, msg)
            self.assertEqual(vmt_to_delete, "crit")
    
    def test_build_special_mode_vpk_normal_map(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ctx = BuildContext("id", "critHIT", "critHIT", base / "ctx")
            ctx.create_directories()
            rel_path = "materials/effects"
            vmt_filename = "crit.vmt"
            mod_data = base / "mod_data"
            mod_data.mkdir(parents=True, exist_ok=True)
            (mod_data / vmt_filename).write_text("vmt", encoding="utf-8")

            def fake_process_image(input_path, output_path, size):
                Path(output_path).write_bytes(b"png")
            
            def fake_create_vtf(png_path, output_path, format_type, flags, options=None):
                output_dir = Path(output_path)
                output_dir.mkdir(parents=True, exist_ok=True)
                out_vtf = output_dir / f"{Path(png_path).stem}.vtf"
                out_vtf.write_bytes(b"vtf")
            
            with patch("src.services.build_service.DirectoryPaths.MOD_DATA_DIR", mod_data):
                with patch("src.services.build_service.VMTService.get_weapon_relpaths", return_value=(rel_path, vmt_filename, "crit.vtf")):
                    with patch("src.services.build_service.TextureService.process_image", side_effect=fake_process_image):
                        with patch("src.services.build_service.TextureService.create_vtf", side_effect=fake_create_vtf):
                            ok, msg, _ = BuildService.build_special_mode_vpk(
                                ctx, "critHIT", str(base / "img.png"), (4, 4), "DXT1", [], vtf_options={"normal": True}
                            )
            self.assertTrue(ok, msg)

    def test_build_vpk_real_render_flow(self):
        """Характеризационный тест РЕАЛЬНОГО пути рендера (без custom_vtf).

        В отличие от happy-path с готовым VTF, здесь отрабатывает ветка
        `elif image_path:` → TextureService.render_image_to_vtf (с замоканными
        примитивами process_image/create_vtf), затем извлечение оригинального
        VMT и запись главного VMT. Покрывает тело цикла рендера для оружия с
        одной текстурой (без extra/blu).
        """
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            img = base / "img.png"
            Image.new("RGB", (8, 8), color="red").save(img)
            vmt_source = base / "src.vmt"
            vmt_source.write_text('"VertexLitGeneric"\n{\n"$basetexture" "x"\n}\n', encoding="utf-8")

            ctx = BuildContext("id", "scout_c_scattergun", "c_scattergun", base / "ctx")
            ctx.create_directories()
            ctx.decompile_dir.mkdir(parents=True, exist_ok=True)

            tg = {"red_row": ["c_scattergun"], "blu_row": [], "extra_materials": [],
                  "blu_is_team": False, "main_texture": "c_scattergun"}
            P = "src.services.vpk_service."
            TS = "src.services.texture_service.TextureService."

            def fake_create_vtf(png_path, output_path, fmt, flags, options=None):
                # Эмулируем VTFCmd: кладём .vtf рядом по имени PNG.
                out = Path(output_path)
                out.mkdir(parents=True, exist_ok=True)
                (out / f"{Path(png_path).stem}.vtf").write_bytes(b"vtf")

            def fake_process_image(inp, outp, size):
                Path(outp).parent.mkdir(parents=True, exist_ok=True)
                Path(outp).write_bytes(b"png")

            patches = [
                patch(P + "BuildContext.create", return_value=ctx),
                patch(P + "TF2Paths.check_crowbar", return_value=(True, "")),
                patch(P + "TF2Paths.resolve", return_value=("studiomdl.exe", "tf2_misc_dir.vpk", str(base))),
                patch(P + "TF2VPKExtractService.check_mdl_exists", return_value=True),
                patch(P + "TF2VPKExtractService.extract_file_set", return_value=[str(base / "c_scattergun.mdl")]),
                patch(P + "ModelBuildService.decompile", return_value=str(base / "a.qc")),
                patch(P + "ModelBuildService.extract_cdmaterials_path_from_qc", return_value="models/weapons/c_scattergun"),
                patch(P + "ModelBuildService.extract_all_cdmaterials_paths_from_qc", return_value=["models/weapons/c_scattergun"]),
                patch(P + "ModelBuildService.extract_texturegroup_filename", return_value="c_scattergun"),
                patch(P + "ModelBuildService.extract_texturegroup_structure", return_value=tg),
                patch(P + "ModelBuildService.patch_qc_file"),
                patch(P + "ModelBuildService.compile"),
                patch(P + "ModelBuildService.remove_lod_files"),
                patch(P + "TF2Paths.resolve_textures_vpk", return_value="tf2_textures_dir.vpk"),
                patch(P + "TF2VPKExtractService.extract_vmt_file", return_value=str(vmt_source)),
                patch(P + "VPKService._copy_compiled_models_to_vpkroot"),
                patch(P + "VPKService._create_vpk_file", return_value=str(base / "out.vpk")),
                patch(P + "DirectoryPaths.TEMP_VMT_EXTRACT_DIR", base / "temp_vmt"),
                patch(TS + "is_animated_image", return_value=False),
                patch(TS + "process_image", side_effect=fake_process_image),
            ]
            with contextlib.ExitStack() as stack:
                for p in patches:
                    stack.enter_context(p)
                # Захватываем мок create_vtf, чтобы подтвердить, что ветка рендера
                # реально отработала (файлы к концу удаляет ctx.cleanup).
                m_create = stack.enter_context(patch(TS + "create_vtf", side_effect=fake_create_vtf))
                (base / "temp_vmt").mkdir(exist_ok=True)
                ok, msg = VPKService.build_vpk(
                    image_path=str(img),
                    mode="scout_c_scattergun",
                    filename="out.vpk",
                    size=(4, 4),
                    format_type="DXT1",
                    flags=[],
                    vtf_options={},
                    tf2_root_dir=str(base),
                    export_folder=str(base),
                    language="en",
                )
            self.assertTrue(ok, msg)
            # Ветка `elif image_path:` → render_image_to_vtf → create_vtf отработала.
            self.assertTrue(m_create.called)

    def test_build_vpk_extra_materials_render_flow(self):
        """РЕАЛЬНЫЙ рендер доп. материала (extra_materials): пользователь дал
        отдельную картинку для столбца shell → цикл extra-материалов рендерит её
        и пишет VMT. Покрывает тело цикла extra-материалов (не custom_vtf)."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            img = base / "img.png"
            Image.new("RGB", (8, 8), color="red").save(img)
            shell_img = base / "shell.png"
            Image.new("RGB", (8, 8), color="green").save(shell_img)
            vmt_source = base / "src.vmt"
            vmt_source.write_text('"VertexLitGeneric"\n{\n"$basetexture" "x"\n}\n', encoding="utf-8")

            ctx = BuildContext("id", "scout_c_scattergun", "c_scattergun", base / "ctx")
            ctx.create_directories()
            ctx.decompile_dir.mkdir(parents=True, exist_ok=True)

            tg = {"red_row": ["c_scattergun", "c_scattergun_shell"], "blu_row": [],
                  "extra_materials": ["c_scattergun_shell"], "blu_is_team": False,
                  "main_texture": "c_scattergun"}

            def extra_cb(mat, wk):
                return str(shell_img) if mat == "c_scattergun_shell" else None

            def fake_create_vtf(png_path, output_path, fmt, flags, options=None):
                out = Path(output_path)
                out.mkdir(parents=True, exist_ok=True)
                (out / f"{Path(png_path).stem}.vtf").write_bytes(b"vtf")

            def fake_process_image(inp, outp, size):
                Path(outp).parent.mkdir(parents=True, exist_ok=True)
                Path(outp).write_bytes(b"png")

            P = "src.services.vpk_service."
            TS = "src.services.texture_service.TextureService."
            patches = [
                patch(P + "BuildContext.create", return_value=ctx),
                patch(P + "TF2Paths.check_crowbar", return_value=(True, "")),
                patch(P + "TF2Paths.resolve", return_value=("studiomdl.exe", "tf2_misc_dir.vpk", str(base))),
                patch(P + "TF2VPKExtractService.check_mdl_exists", return_value=True),
                patch(P + "TF2VPKExtractService.extract_file_set", return_value=[str(base / "c_scattergun.mdl")]),
                patch(P + "ModelBuildService.decompile", return_value=str(base / "a.qc")),
                patch(P + "ModelBuildService.extract_cdmaterials_path_from_qc", return_value="models/weapons/c_scattergun"),
                patch(P + "ModelBuildService.extract_all_cdmaterials_paths_from_qc", return_value=["models/weapons/c_scattergun"]),
                patch(P + "ModelBuildService.extract_texturegroup_filename", return_value="c_scattergun"),
                patch(P + "ModelBuildService.extract_texturegroup_structure", return_value=tg),
                patch(P + "ModelBuildService.patch_qc_file"),
                patch(P + "ModelBuildService.compile"),
                patch(P + "ModelBuildService.remove_lod_files"),
                patch(P + "TF2Paths.resolve_textures_vpk", return_value="tf2_textures_dir.vpk"),
                patch(P + "TF2VPKExtractService.extract_vmt_file", return_value=str(vmt_source)),
                patch(P + "VPKService._copy_compiled_models_to_vpkroot"),
                patch(P + "VPKService._create_vpk_file", return_value=str(base / "out.vpk")),
                patch(P + "DirectoryPaths.TEMP_VMT_EXTRACT_DIR", base / "temp_vmt"),
                patch(TS + "is_animated_image", return_value=False),
                patch(TS + "process_image", side_effect=fake_process_image),
            ]
            with contextlib.ExitStack() as stack:
                for p in patches:
                    stack.enter_context(p)
                m_create = stack.enter_context(patch(TS + "create_vtf", side_effect=fake_create_vtf))
                (base / "temp_vmt").mkdir(exist_ok=True)
                ok, msg = VPKService.build_vpk(
                    image_path=str(img),
                    mode="scout_c_scattergun",
                    filename="out.vpk",
                    size=(4, 4),
                    format_type="DXT1",
                    flags=[],
                    vtf_options={},
                    tf2_root_dir=str(base),
                    export_folder=str(base),
                    language="en",
                    extra_texture_callback=extra_cb,
                )
            self.assertTrue(ok, msg)
            # Главная + shell → create_vtf вызван минимум дважды.
            self.assertGreaterEqual(m_create.call_count, 2)

    def test_build_vpk_blu_team_render_flow(self):
        """РЕАЛЬНЫЙ рендер BLU-командной текстуры (blu_mode='upload', blu_is_team).
        Покрывает ветку _build_blu_team_texture с генерацией {texture}_blue из
        отдельной картинки."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            img = base / "img.png"
            Image.new("RGB", (8, 8), color="red").save(img)
            blu_img = base / "blu.png"
            Image.new("RGB", (8, 8), color="blue").save(blu_img)
            vmt_source = base / "src.vmt"
            vmt_source.write_text('"VertexLitGeneric"\n{\n"$basetexture" "x"\n}\n', encoding="utf-8")

            ctx = BuildContext("id", "scout_c_scattergun", "c_scattergun", base / "ctx")
            ctx.create_directories()
            ctx.decompile_dir.mkdir(parents=True, exist_ok=True)

            tg = {"red_row": ["c_scattergun"], "blu_row": ["c_scattergun_blue"],
                  "extra_materials": [], "blu_is_team": True, "main_texture": "c_scattergun"}

            def fake_create_vtf(png_path, output_path, fmt, flags, options=None):
                out = Path(output_path)
                out.mkdir(parents=True, exist_ok=True)
                (out / f"{Path(png_path).stem}.vtf").write_bytes(b"vtf")

            def fake_process_image(inp, outp, size):
                Path(outp).parent.mkdir(parents=True, exist_ok=True)
                Path(outp).write_bytes(b"png")

            P = "src.services.vpk_service."
            TS = "src.services.texture_service.TextureService."
            patches = [
                patch(P + "BuildContext.create", return_value=ctx),
                patch(P + "TF2Paths.check_crowbar", return_value=(True, "")),
                patch(P + "TF2Paths.resolve", return_value=("studiomdl.exe", "tf2_misc_dir.vpk", str(base))),
                patch(P + "TF2VPKExtractService.check_mdl_exists", return_value=True),
                patch(P + "TF2VPKExtractService.extract_file_set", return_value=[str(base / "c_scattergun.mdl")]),
                patch(P + "ModelBuildService.decompile", return_value=str(base / "a.qc")),
                patch(P + "ModelBuildService.extract_cdmaterials_path_from_qc", return_value="models/weapons/c_scattergun"),
                patch(P + "ModelBuildService.extract_all_cdmaterials_paths_from_qc", return_value=["models/weapons/c_scattergun"]),
                patch(P + "ModelBuildService.extract_texturegroup_filename", return_value="c_scattergun"),
                patch(P + "ModelBuildService.extract_texturegroup_structure", return_value=tg),
                patch(P + "ModelBuildService.patch_qc_file"),
                patch(P + "ModelBuildService.compile"),
                patch(P + "ModelBuildService.remove_lod_files"),
                patch(P + "TF2Paths.resolve_textures_vpk", return_value="tf2_textures_dir.vpk"),
                patch(P + "TF2VPKExtractService.extract_vmt_file", return_value=str(vmt_source)),
                patch(P + "VPKService._copy_compiled_models_to_vpkroot"),
                patch(P + "VPKService._create_vpk_file", return_value=str(base / "out.vpk")),
                patch(P + "DirectoryPaths.TEMP_VMT_EXTRACT_DIR", base / "temp_vmt"),
                patch(TS + "is_animated_image", return_value=False),
                patch(TS + "process_image", side_effect=fake_process_image),
            ]
            with contextlib.ExitStack() as stack:
                for p in patches:
                    stack.enter_context(p)
                m_create = stack.enter_context(patch(TS + "create_vtf", side_effect=fake_create_vtf))
                (base / "temp_vmt").mkdir(exist_ok=True)
                ok, msg = VPKService.build_vpk(
                    image_path=str(img),
                    mode="scout_c_scattergun",
                    filename="out.vpk",
                    size=(4, 4),
                    format_type="DXT1",
                    flags=[],
                    vtf_options={},
                    tf2_root_dir=str(base),
                    export_folder=str(base),
                    language="en",
                    blu_mode="upload",
                    blu_image_path=str(blu_img),
                )
            self.assertTrue(ok, msg)
            # Главная + BLU → create_vtf вызван минимум дважды.
            self.assertGreaterEqual(m_create.call_count, 2)

    def test_build_vpk_normal_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            img = base / "img.png"
            Image.new("RGB", (8, 8), color="red").save(img)
            custom_vtf = base / "custom.vtf"
            custom_vtf.write_text("v", encoding="utf-8")
            vmt_source = base / "src.vmt"
            vmt_source.write_text("vmt", encoding="utf-8")

            ctx = BuildContext("id", "scout_c_scattergun", "c_scattergun", base / "ctx")
            ctx.create_directories()
            ctx.decompile_dir.mkdir(parents=True, exist_ok=True)

            with patch("src.services.vpk_service.BuildContext.create", return_value=ctx):
                with patch("src.services.vpk_service.TF2Paths.check_crowbar", return_value=(True, "")):
                    with patch("src.services.vpk_service.TF2Paths.resolve", return_value=("studiomdl.exe", "tf2_misc_dir.vpk", str(base))):
                        with patch("src.services.vpk_service.TF2VPKExtractService.check_mdl_exists", return_value=True):
                            with patch("src.services.vpk_service.TF2VPKExtractService.extract_file_set", return_value=[str(base / "c_scattergun.mdl")]):
                                with patch("src.services.vpk_service.ModelBuildService.decompile", return_value=str(base / "a.qc")):
                                    with patch("src.services.vpk_service.ModelBuildService.extract_cdmaterials_path_from_qc", return_value="models/weapons/c_scattergun"):
                                        with patch("src.services.vpk_service.ModelBuildService.extract_texturegroup_filename", return_value="c_scattergun"):
                                            with patch("src.services.vpk_service.ModelBuildService.patch_qc_file"):
                                                with patch("src.services.vpk_service.ModelBuildService.compile"):
                                                    with patch("src.services.vpk_service.ModelBuildService.remove_lod_files"):
                                                        with patch("src.services.vpk_service.TF2Paths.resolve_textures_vpk", return_value="tf2_textures_dir.vpk"):
                                                            with patch("src.services.vpk_service.TF2VPKExtractService.extract_vmt_file", return_value=str(vmt_source)):
                                                                with patch("src.services.vpk_service.VMTService.update_vmt_basetexture_path"):
                                                                    with patch("src.services.vpk_service.VMTService.create_vmt_template_from_cdmaterials"):
                                                                        with patch("src.services.vpk_service.VPKService._copy_compiled_models_to_vpkroot"):
                                                                            with patch("src.services.vpk_service.VPKService._create_vpk_file", return_value=str(base / "out.vpk")):
                                                                                with patch("src.services.vpk_service.DirectoryPaths.TEMP_VMT_EXTRACT_DIR", base / "temp_vmt"):
                                                                                    (base / "temp_vmt").mkdir(exist_ok=True)
                                                                                    ok, msg = VPKService.build_vpk(
                                                                                        image_path=str(img),
                                                                                        mode="scout_c_scattergun",
                                                                                        filename="out.vpk",
                                                                                        size=(4, 4),
                                                                                        format_type="DXT1",
                                                                                        flags=[],
                                                                                        vtf_options={},
                                                                                        tf2_root_dir=str(base),
                                                                                        export_folder=str(base),
                                                                                        keep_temp_on_error=False,
                                                                                        debug_mode=False,
                                                                                        replace_model_enabled=False,
                                                                                        draw_uv_layout=False,
                                                                                        language="en",
                                                                                        custom_vtf_path=str(custom_vtf)
                                                                                    )
            self.assertTrue(ok, msg)
    
    def test_build_vpk_hands_flow(self):
        """Характеризационный тест ветки рук (mode in HAND_MODE_KEYS).

        Фиксирует, что сборка рук проходит конвейер декомпиляции/компиляции и
        упаковки так же, как оружие, но weapon_key берётся из arm_model, а
        $texturegroup ограничивается текстурами руки (restrict_to_materials).
        """
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            custom_vtf = base / "custom.vtf"
            custom_vtf.write_text("v", encoding="utf-8")
            vmt_source = base / "src.vmt"
            vmt_source.write_text("vmt", encoding="utf-8")

            ctx = BuildContext("id", "scout_hands", "c_scout_arms", base / "ctx")
            ctx.create_directories()
            ctx.decompile_dir.mkdir(parents=True, exist_ok=True)

            tg = {
                "red_row": ["scout_hands"],
                "blu_row": [],
                "extra_materials": [],
                "blu_is_team": False,
                "main_texture": "scout_hands",
            }
            P = "src.services.vpk_service."
            with patch(P + "BuildContext.create", return_value=ctx), \
                 patch(P + "TF2Paths.check_crowbar", return_value=(True, "")), \
                 patch(P + "TF2Paths.resolve", return_value=("studiomdl.exe", "tf2_misc_dir.vpk", str(base))), \
                 patch(P + "TF2VPKExtractService.check_mdl_exists", return_value=True), \
                 patch(P + "TF2VPKExtractService.extract_file_set", return_value=[str(base / "c_scout_arms.mdl")]), \
                 patch(P + "ModelBuildService.decompile", return_value=str(base / "a.qc")), \
                 patch(P + "ModelBuildService.extract_cdmaterials_path_from_qc", return_value="models/player/scout"), \
                 patch(P + "ModelBuildService.extract_all_cdmaterials_paths_from_qc", return_value=["models/player/scout"]), \
                 patch(P + "ModelBuildService.extract_texturegroup_filename", return_value="scout_hands"), \
                 patch(P + "ModelBuildService.extract_texturegroup_structure", return_value=tg), \
                 patch(P + "ModelBuildService.patch_qc_file"), \
                 patch(P + "ModelBuildService.compile"), \
                 patch(P + "ModelBuildService.remove_lod_files"), \
                 patch(P + "TF2Paths.resolve_textures_vpk", return_value="tf2_textures_dir.vpk"), \
                 patch(P + "TF2VPKExtractService.extract_vmt_file", return_value=str(vmt_source)), \
                 patch(P + "VMTService.update_vmt_basetexture_path"), \
                 patch(P + "VMTService.create_vmt_template_from_cdmaterials"), \
                 patch(P + "VPKService._copy_compiled_models_to_vpkroot"), \
                 patch(P + "VPKService._create_vpk_file", return_value=str(base / "out.vpk")), \
                 patch(P + "DirectoryPaths.TEMP_VMT_EXTRACT_DIR", base / "temp_vmt"):
                (base / "temp_vmt").mkdir(exist_ok=True)
                ok, msg = VPKService.build_vpk(
                    image_path=str(custom_vtf),
                    mode="scout_hands",
                    filename="out.vpk",
                    size=(4, 4),
                    format_type="DXT1",
                    flags=[],
                    vtf_options={},
                    tf2_root_dir=str(base),
                    export_folder=str(base),
                    language="en",
                    custom_vtf_path=str(custom_vtf),
                )
            self.assertTrue(ok, msg)

    def test_build_vpk_player_body_flow(self):
        """Характеризационный тест ветки скина тела персонажа (PLAYER_BODY_MODE_KEYS).

        weapon_key берётся из стема mdl_path персонажа; модель замены принудительно
        выключается; сборка идёт через обычный конвейер декомпиляции/упаковки.
        """
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            custom_vtf = base / "custom.vtf"
            custom_vtf.write_text("v", encoding="utf-8")
            vmt_source = base / "src.vmt"
            vmt_source.write_text("vmt", encoding="utf-8")

            ctx = BuildContext("id", "demoman_body", "demo", base / "ctx")
            ctx.create_directories()
            ctx.decompile_dir.mkdir(parents=True, exist_ok=True)

            tg = {
                "red_row": ["demo"],
                "blu_row": [],
                "extra_materials": [],
                "blu_is_team": False,
                "main_texture": "demo",
            }
            P = "src.services.vpk_service."
            with patch(P + "BuildContext.create", return_value=ctx), \
                 patch(P + "TF2Paths.check_crowbar", return_value=(True, "")), \
                 patch(P + "TF2Paths.resolve", return_value=("studiomdl.exe", "tf2_misc_dir.vpk", str(base))), \
                 patch(P + "TF2VPKExtractService.check_mdl_exists", return_value=True), \
                 patch(P + "TF2VPKExtractService.extract_file_set", return_value=[str(base / "demo.mdl")]), \
                 patch(P + "ModelBuildService.decompile", return_value=str(base / "a.qc")), \
                 patch(P + "ModelBuildService.extract_cdmaterials_path_from_qc", return_value="models/player/demo"), \
                 patch(P + "ModelBuildService.extract_all_cdmaterials_paths_from_qc", return_value=["models/player/demo"]), \
                 patch(P + "ModelBuildService.extract_texturegroup_filename", return_value="demo"), \
                 patch(P + "ModelBuildService.extract_texturegroup_structure", return_value=tg), \
                 patch(P + "ModelBuildService.patch_qc_file"), \
                 patch(P + "ModelBuildService.compile"), \
                 patch(P + "ModelBuildService.remove_lod_files"), \
                 patch(P + "TF2Paths.resolve_textures_vpk", return_value="tf2_textures_dir.vpk"), \
                 patch(P + "TF2VPKExtractService.extract_vmt_file", return_value=str(vmt_source)), \
                 patch(P + "VMTService.update_vmt_basetexture_path"), \
                 patch(P + "VMTService.create_vmt_template_from_cdmaterials"), \
                 patch(P + "VPKService._copy_compiled_models_to_vpkroot"), \
                 patch(P + "VPKService._create_vpk_file", return_value=str(base / "out.vpk")), \
                 patch(P + "DirectoryPaths.TEMP_VMT_EXTRACT_DIR", base / "temp_vmt"):
                (base / "temp_vmt").mkdir(exist_ok=True)
                ok, msg = VPKService.build_vpk(
                    image_path=str(custom_vtf),
                    mode="demoman_body",
                    filename="out.vpk",
                    size=(4, 4),
                    format_type="DXT1",
                    flags=[],
                    vtf_options={},
                    tf2_root_dir=str(base),
                    export_folder=str(base),
                    language="en",
                    custom_vtf_path=str(custom_vtf),
                )
            self.assertTrue(ok, msg)

    def test_build_vpk_hat_flow(self):
        """Характеризационный тест ветки шапки (mode == 'hat', одиночный класс).

        weapon_key берётся из стема hat_mdl_path; без %s-шаблона и без
        hat_class_models доп. классовые модели не собираются — обычный конвейер.
        """
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            custom_vtf = base / "custom.vtf"
            custom_vtf.write_text("v", encoding="utf-8")
            vmt_source = base / "src.vmt"
            vmt_source.write_text("vmt", encoding="utf-8")
            hat_mdl = "models/player/items/all_class/hat_foo.mdl"

            ctx = BuildContext("id", "hat", "hat_foo", base / "ctx")
            ctx.create_directories()
            ctx.decompile_dir.mkdir(parents=True, exist_ok=True)

            tg = {
                "red_row": ["hat_foo"],
                "blu_row": [],
                "extra_materials": [],
                "blu_is_team": False,
                "main_texture": "hat_foo",
            }
            P = "src.services.vpk_service."
            with patch(P + "BuildContext.create", return_value=ctx), \
                 patch(P + "TF2Paths.check_crowbar", return_value=(True, "")), \
                 patch(P + "TF2Paths.resolve", return_value=("studiomdl.exe", "tf2_misc_dir.vpk", str(base))), \
                 patch(P + "TF2VPKExtractService.check_mdl_exists", return_value=True), \
                 patch(P + "TF2VPKExtractService.extract_file_set", return_value=[str(base / "hat_foo.mdl")]), \
                 patch(P + "ModelBuildService.decompile", return_value=str(base / "a.qc")), \
                 patch(P + "ModelBuildService.extract_cdmaterials_path_from_qc", return_value="models/player/items/all_class"), \
                 patch(P + "ModelBuildService.extract_all_cdmaterials_paths_from_qc", return_value=["models/player/items/all_class"]), \
                 patch(P + "ModelBuildService.extract_texturegroup_filename", return_value="hat_foo"), \
                 patch(P + "ModelBuildService.extract_texturegroup_structure", return_value=tg), \
                 patch(P + "ModelBuildService.patch_qc_file"), \
                 patch(P + "ModelBuildService.compile"), \
                 patch(P + "ModelBuildService.remove_lod_files"), \
                 patch(P + "TF2Paths.resolve_textures_vpk", return_value="tf2_textures_dir.vpk"), \
                 patch(P + "TF2VPKExtractService.extract_vmt_file", return_value=str(vmt_source)), \
                 patch(P + "VMTService.update_vmt_basetexture_path"), \
                 patch(P + "VMTService.create_vmt_template_from_cdmaterials"), \
                 patch(P + "VPKService._copy_compiled_models_to_vpkroot"), \
                 patch(P + "VPKService._create_vpk_file", return_value=str(base / "out.vpk")), \
                 patch(P + "DirectoryPaths.TEMP_VMT_EXTRACT_DIR", base / "temp_vmt"):
                (base / "temp_vmt").mkdir(exist_ok=True)
                ok, msg = VPKService.build_vpk(
                    image_path=str(custom_vtf),
                    mode="hat",
                    filename="out.vpk",
                    size=(4, 4),
                    format_type="DXT1",
                    flags=[],
                    vtf_options={},
                    tf2_root_dir=str(base),
                    export_folder=str(base),
                    language="en",
                    custom_vtf_path=str(custom_vtf),
                    hat_mdl_path=hat_mdl,
                )
            self.assertTrue(ok, msg)

    def test_build_vpk_keep_materials_flow(self):
        """Характеризационный тест ветки «готовая модель со своими материалами»
        (replace_model_enabled + replace_keep_materials, без доп-стилей).

        Имена материалов берутся из reference-SMD, игровой $texturegroup убирается.
        """
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            custom_vtf = base / "custom.vtf"
            custom_vtf.write_text("v", encoding="utf-8")
            vmt_source = base / "src.vmt"
            vmt_source.write_text("vmt", encoding="utf-8")
            user_smd = base / "user.smd"
            user_smd.write_text("smd", encoding="utf-8")

            ctx = BuildContext("id", "scout_c_scattergun", "c_scattergun", base / "ctx")
            ctx.create_directories()
            ctx.decompile_dir.mkdir(parents=True, exist_ok=True)

            tg = {"red_row": ["c_scattergun"], "blu_row": [], "extra_materials": [],
                  "blu_is_team": False, "main_texture": "c_scattergun"}
            P = "src.services.vpk_service."
            patches = [
                patch(P + "BuildContext.create", return_value=ctx),
                patch(P + "TF2Paths.check_crowbar", return_value=(True, "")),
                patch(P + "TF2Paths.resolve", return_value=("studiomdl.exe", "tf2_misc_dir.vpk", str(base))),
                patch(P + "TF2VPKExtractService.check_mdl_exists", return_value=True),
                patch(P + "TF2VPKExtractService.extract_file_set", return_value=[str(base / "c_scattergun.mdl")]),
                patch(P + "ModelBuildService.decompile", return_value=str(base / "a.qc")),
                patch(P + "ModelBuildService.extract_cdmaterials_path_from_qc", return_value="models/weapons/c_scattergun"),
                patch(P + "ModelBuildService.extract_all_cdmaterials_paths_from_qc", return_value=["models/weapons/c_scattergun"]),
                patch(P + "ModelBuildService.extract_texturegroup_filename", return_value="c_scattergun"),
                patch(P + "ModelBuildService.extract_texturegroup_structure", return_value=tg),
                patch(P + "ModelBuildService.patch_qc_file"),
                patch(P + "ModelBuildService.replace_texturegroup_in_qc"),
                patch(P + "ModelBuildService.compile"),
                patch(P + "ModelBuildService.remove_lod_files"),
                patch(P + "VPKService._resolve_replace_model_smd", return_value=str(user_smd)),
                patch(P + "VPKService._apply_model_replacement"),
                patch(P + "VPKService._find_decompiled_reference_smd", return_value=str(user_smd)),
                patch(P + "SMDService.ordered_unique_materials", return_value=["c_scattergun"]),
                patch(P + "TF2Paths.resolve_textures_vpk", return_value="tf2_textures_dir.vpk"),
                patch(P + "TF2VPKExtractService.extract_vmt_file", return_value=str(vmt_source)),
                patch(P + "VMTService.update_vmt_basetexture_path"),
                patch(P + "VMTService.create_vmt_template_from_cdmaterials"),
                patch(P + "VPKService._copy_compiled_models_to_vpkroot"),
                patch(P + "VPKService._create_vpk_file", return_value=str(base / "out.vpk")),
                patch(P + "DirectoryPaths.TEMP_VMT_EXTRACT_DIR", base / "temp_vmt"),
            ]
            with contextlib.ExitStack() as stack:
                for p in patches:
                    stack.enter_context(p)
                (base / "temp_vmt").mkdir(exist_ok=True)
                ok, msg = VPKService.build_vpk(
                    image_path=str(custom_vtf),
                    mode="scout_c_scattergun",
                    filename="out.vpk",
                    size=(4, 4),
                    format_type="DXT1",
                    flags=[],
                    vtf_options={},
                    tf2_root_dir=str(base),
                    export_folder=str(base),
                    language="en",
                    custom_vtf_path=str(custom_vtf),
                    replace_model_enabled=True,
                    replace_model_path=str(user_smd),
                    replace_keep_materials=True,
                )
            self.assertTrue(ok, msg)

    def test_build_vpk_skin_styles_flow(self):
        """Характеризационный тест ветки доп-стилей (skin_build_data с tg_overrides).

        _has_skins → инъекция своего $texturegroup; имена материалов выравниваются
        по reference-SMD. variant_files пуст (цикл рендера вариантов не задействуем).
        """
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            custom_vtf = base / "custom.vtf"
            custom_vtf.write_text("v", encoding="utf-8")
            vmt_source = base / "src.vmt"
            vmt_source.write_text("vmt", encoding="utf-8")
            user_smd = base / "user.smd"
            user_smd.write_text("smd", encoding="utf-8")

            ctx = BuildContext("id", "scout_c_scattergun", "c_scattergun", base / "ctx")
            ctx.create_directories()
            ctx.decompile_dir.mkdir(parents=True, exist_ok=True)

            tg = {"red_row": ["c_scattergun"], "blu_row": [], "extra_materials": [],
                  "blu_is_team": False, "main_texture": "c_scattergun"}
            skin_data = {
                "tg_overrides": {1: ["c_scattergun_blue"]},
                "mesh_materials": ["c_scattergun"],
                "variant_files": {},
            }
            P = "src.services.vpk_service."
            patches = [
                patch(P + "BuildContext.create", return_value=ctx),
                patch(P + "TF2Paths.check_crowbar", return_value=(True, "")),
                patch(P + "TF2Paths.resolve", return_value=("studiomdl.exe", "tf2_misc_dir.vpk", str(base))),
                patch(P + "TF2VPKExtractService.check_mdl_exists", return_value=True),
                patch(P + "TF2VPKExtractService.extract_file_set", return_value=[str(base / "c_scattergun.mdl")]),
                patch(P + "ModelBuildService.decompile", return_value=str(base / "a.qc")),
                patch(P + "ModelBuildService.extract_cdmaterials_path_from_qc", return_value="models/weapons/c_scattergun"),
                patch(P + "ModelBuildService.extract_all_cdmaterials_paths_from_qc", return_value=["models/weapons/c_scattergun"]),
                patch(P + "ModelBuildService.extract_texturegroup_filename", return_value="c_scattergun"),
                patch(P + "ModelBuildService.extract_texturegroup_structure", return_value=tg),
                patch(P + "ModelBuildService.patch_qc_file"),
                patch(P + "ModelBuildService.replace_texturegroup_in_qc"),
                patch(P + "ModelBuildService.generate_texturegroup_block", return_value='$texturegroup "skinfamilies" {}'),
                patch(P + "ModelBuildService.compile"),
                patch(P + "ModelBuildService.remove_lod_files"),
                patch(P + "VPKService._resolve_replace_model_smd", return_value=str(user_smd)),
                patch(P + "VPKService._apply_model_replacement"),
                patch(P + "VPKService._find_decompiled_reference_smd", return_value=str(user_smd)),
                patch(P + "VPKService._remap_skin_data_to_smd", side_effect=lambda sbd, mats: sbd),
                patch(P + "SMDService.ordered_unique_materials", return_value=["c_scattergun"]),
                patch(P + "TF2Paths.resolve_textures_vpk", return_value="tf2_textures_dir.vpk"),
                patch(P + "TF2VPKExtractService.extract_vmt_file", return_value=str(vmt_source)),
                patch(P + "VMTService.update_vmt_basetexture_path"),
                patch(P + "VMTService.create_vmt_template_from_cdmaterials"),
                patch(P + "VPKService._copy_compiled_models_to_vpkroot"),
                patch(P + "VPKService._create_vpk_file", return_value=str(base / "out.vpk")),
                patch(P + "DirectoryPaths.TEMP_VMT_EXTRACT_DIR", base / "temp_vmt"),
            ]
            with contextlib.ExitStack() as stack:
                for p in patches:
                    stack.enter_context(p)
                (base / "temp_vmt").mkdir(exist_ok=True)
                ok, msg = VPKService.build_vpk(
                    image_path=str(custom_vtf),
                    mode="scout_c_scattergun",
                    filename="out.vpk",
                    size=(4, 4),
                    format_type="DXT1",
                    flags=[],
                    vtf_options={},
                    tf2_root_dir=str(base),
                    export_folder=str(base),
                    language="en",
                    custom_vtf_path=str(custom_vtf),
                    replace_model_enabled=True,
                    replace_model_path=str(user_smd),
                    replace_keep_materials=True,
                    skin_build_data=skin_data,
                )
            self.assertTrue(ok, msg)

    def test_build_vpk_validation_error(self):
        with patch.object(VPKService, "_validate_build_params", return_value="bad"):
            ok, msg = VPKService.build_vpk(
                image_path="img.png",
                mode="scout_c_scattergun",
                filename="out.vpk",
                size=(4, 4),
                tf2_root_dir="C:/TF2"
            )
        self.assertFalse(ok)
        self.assertEqual(msg, "bad")
    
    def test_build_vpk_tf2_not_specified_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            img = base / "img.png"
            Image.new("RGB", (2, 2), color="red").save(img)
            with patch.object(VPKService, "_validate_build_params", return_value=None):
                with patch("src.services.vpk_service.BuildContext.create", return_value=BuildContext("id", "m", "w", base / "ctx")):
                    ok, msg = VPKService.build_vpk(
                        image_path=str(img),
                        mode="scout_c_scattergun",
                        filename="out.vpk",
                        size=(4, 4),
                        tf2_root_dir=""
                    )
        self.assertFalse(ok)
        self.assertIn("TF2", msg)
    
    def test_build_vpk_crowbar_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            img = base / "img.png"
            Image.new("RGB", (2, 2), color="red").save(img)
            ctx = BuildContext("id", "scout_c_scattergun", "c_scattergun", base / "ctx")
            ctx.create_directories()
            with patch.object(VPKService, "_validate_build_params", return_value=None):
                with patch("src.services.vpk_service.BuildContext.create", return_value=ctx):
                    with patch("src.services.vpk_service.TF2Paths.check_crowbar", return_value=(False, "crowbar missing")):
                        ok, msg = VPKService.build_vpk(
                            image_path=str(img),
                            mode="scout_c_scattergun",
                            filename="out.vpk",
                            size=(4, 4),
                            tf2_root_dir=str(base)
                        )
        self.assertFalse(ok)
        self.assertEqual(msg, "crowbar missing")
    
    def test_build_vpk_tf2_resolve_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            img = base / "img.png"
            Image.new("RGB", (2, 2), color="red").save(img)
            ctx = BuildContext("id", "scout_c_scattergun", "c_scattergun", base / "ctx")
            ctx.create_directories()
            with patch.object(VPKService, "_validate_build_params", return_value=None):
                with patch("src.services.vpk_service.BuildContext.create", return_value=ctx):
                    with patch("src.services.vpk_service.TF2Paths.check_crowbar", return_value=(True, "")):
                        with patch("src.services.vpk_service.TF2Paths.resolve", side_effect=FileNotFoundError("no tf2")):
                            ok, msg = VPKService.build_vpk(
                                image_path=str(img),
                                mode="scout_c_scattergun",
                                filename="out.vpk",
                                size=(4, 4),
                                tf2_root_dir=str(base)
                            )
        self.assertFalse(ok)
        self.assertIn("no tf2", msg)
    
    def test_build_vpk_weapon_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            img = base / "img.png"
            Image.new("RGB", (2, 2), color="red").save(img)
            ctx = BuildContext("id", "scout_missing", "missing", base / "ctx")
            ctx.create_directories()
            with patch.object(VPKService, "_validate_build_params", return_value=None):
                with patch("src.services.vpk_service.BuildContext.create", return_value=ctx):
                    with patch("src.services.vpk_service.TF2Paths.check_crowbar", return_value=(True, "")):
                        with patch("src.services.vpk_service.TF2Paths.resolve", return_value=("studiomdl.exe", "tf2_misc_dir.vpk", str(base))):
                            ok, msg = VPKService.build_vpk(
                                image_path=str(img),
                                mode="scout_missing",
                                filename="out.vpk",
                                size=(4, 4),
                                tf2_root_dir=str(base)
                            )
        self.assertFalse(ok)
        self.assertIn("missing", msg)
    
    def test_build_vpk_mdl_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            img = base / "img.png"
            Image.new("RGB", (2, 2), color="red").save(img)
            ctx = BuildContext("id", "scout_c_scattergun", "c_scattergun", base / "ctx")
            ctx.create_directories()
            with patch.object(VPKService, "_validate_build_params", return_value=None):
                with patch("src.services.vpk_service.BuildContext.create", return_value=ctx):
                    with patch("src.services.vpk_service.TF2Paths.check_crowbar", return_value=(True, "")):
                        with patch("src.services.vpk_service.TF2Paths.resolve", return_value=("studiomdl.exe", "tf2_misc_dir.vpk", str(base))):
                            with patch("src.services.vpk_service.TF2VPKExtractService.check_mdl_exists", return_value=False):
                                ok, msg = VPKService.build_vpk(
                                    image_path=str(img),
                                    mode="scout_c_scattergun",
                                    filename="out.vpk",
                                    size=(4, 4),
                                    tf2_root_dir=str(base)
                                )
        self.assertFalse(ok)
        self.assertIn("not found", msg.lower())
    
    def test_build_vpk_mdl_not_extracted(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            img = base / "img.png"
            Image.new("RGB", (2, 2), color="red").save(img)
            ctx = BuildContext("id", "scout_c_scattergun", "c_scattergun", base / "ctx")
            ctx.create_directories()
            with patch.object(VPKService, "_validate_build_params", return_value=None):
                with patch("src.services.vpk_service.BuildContext.create", return_value=ctx):
                    with patch("src.services.vpk_service.TF2Paths.check_crowbar", return_value=(True, "")):
                        with patch("src.services.vpk_service.TF2Paths.resolve", return_value=("studiomdl.exe", "tf2_misc_dir.vpk", str(base))):
                            with patch("src.services.vpk_service.TF2VPKExtractService.check_mdl_exists", return_value=True):
                                with patch("src.services.vpk_service.TF2VPKExtractService.extract_file_set", return_value=[str(base / "c_scattergun.vvd")]):
                                    ok, msg = VPKService.build_vpk(
                                        image_path=str(img),
                                        mode="scout_c_scattergun",
                                        filename="out.vpk",
                                        size=(4, 4),
                                        tf2_root_dir=str(base)
                                    )
        self.assertFalse(ok)
        self.assertIn("extracted", msg.lower())
    
    def test_generate_uv_layout_missing_smd(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ctx = BuildContext("id", "m", "w", base / "ctx")
            ctx.create_directories()
            with patch("src.services.model_service.SMDService.find_reference_smd", return_value=None):
                VPKService._generate_uv_layout(ctx, "weapon", (4, 4), export_folder=str(base))
    
    def test_generate_uv_layout_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ctx = BuildContext("id", "m", "w", base / "ctx")
            ctx.create_directories()
            smd_path = base / "weapon_reference.smd"
            smd_path.write_text("x", encoding="utf-8")
            with patch("src.services.model_service.SMDService.find_reference_smd", return_value=str(smd_path)):
                with patch("src.services.uv_layout_service.UVLayoutService.generate_uv_layout_from_smd", return_value=True) as generate:
                    VPKService._generate_uv_layout(ctx, "weapon", (4, 4), export_folder=str(base))
            generate.assert_called()

    def test_render_extra_texture_missing_returns_false(self):
        # Нет файла/пустой путь → False, без побочных эффектов
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            for bad in (None, "", os.path.join(tmp, "nope.png")):
                self.assertFalse(VPKService._render_extra_texture(
                    "mat", bad, out, out / "main.vmt",
                    "models/weapons/c_models", (4, 4), "DXT1", [], {},
                ))
            self.assertEqual(list(out.glob("*.vtf")), [])

    def test_render_extra_texture_vtf_input_copies_and_writes_vmt(self):
        # На вход .vtf → копируется как есть + создаётся VMT (без vtfcmd)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            src_vtf = out / "src.vtf"
            src_vtf.write_bytes(b"VTF\x00fake")
            ok = VPKService._render_extra_texture(
                "lefteye_bloody", str(src_vtf), out, out / "main.vmt",
                "models/weapons/c_models", (4, 4), "DXT1", [], {},
            )
            self.assertTrue(ok)
            self.assertTrue((out / "lefteye_bloody.vtf").exists())
            self.assertTrue((out / "lefteye_bloody.vmt").exists())
            self.assertEqual((out / "lefteye_bloody.vtf").read_bytes(), b"VTF\x00fake")


    def test_render_extra_texture_image_input_renders_vtf(self):
        # Обычная картинка → ресайз + VTF (через render_image_to_vtf) + VMT.
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            img = out / "skin.png"
            Image.new("RGB", (4, 4), color="blue").save(img)
            with patch("src.services.texture_service.TextureService.is_animated_image", return_value=False), \
                 patch("src.services.texture_service.TextureService.process_image") as m_proc, \
                 patch("src.services.texture_service.TextureService.create_vtf") as m_vtf:
                ok = VPKService._render_extra_texture(
                    "shell", str(img), out, out / "main.vmt",
                    "models/weapons/c_models", (4, 4), "DXT1", [], {},
                )
            self.assertTrue(ok)
            m_proc.assert_called_once()
            m_vtf.assert_called_once()
            self.assertTrue((out / "shell.vmt").exists())

    def test_remap_skin_data_to_smd_by_index(self):
        # UI собрал 'Material.001', SMD-материал 'material' → ремап по индексу,
        # картинки вариантов сохраняются.
        sbd = {
            'mesh_materials': ['Material.001'],
            'tg_overrides': {1: {'Material.001': 'Material.001_bloody'}},
            'variant_files': {'Material.001_bloody': '/img/bloody.png'},
        }
        out = VPKService._remap_skin_data_to_smd(sbd, ['material'])
        self.assertEqual(out['mesh_materials'], ['material'])
        self.assertEqual(out['tg_overrides'], {1: {'material': 'material_bloody'}})
        self.assertEqual(out['variant_files'], {'material_bloody': '/img/bloody.png'})

    def test_remap_skin_data_to_smd_empty_smd_noop(self):
        sbd = {'mesh_materials': ['a'], 'tg_overrides': {1: {'a': 'a_x'}},
               'variant_files': {'a_x': '/p'}}
        self.assertIs(VPKService._remap_skin_data_to_smd(sbd, []), sbd)


class BuildVpkCharacterizationTests(unittest.TestCase):
    """
    Характеризационный тест build_vpk: фиксирует, КАКИЕ VTF-файлы (и с какими
    именами) производит пайплайн для обычного оружия с панельной доп.текстурой.
    Внешние инструменты (crowbar/studiomdl/VTFCmd/упаковка) замоканы; create_vtf
    пишет маркер-файл, чтобы наблюдать именование материалов через весь конвейер.

    Назначение — сетка безопасности под рефакторинг build_vpk: рефактор не должен
    менять состав/имена выходных файлов. Имена материалов через пайплайн — то самое
    место, что ломалось ранее (фиолетовые текстуры).
    """

    def _run_build(self, base: Path, panel_extra_textures: dict, *,
                   texturegroup_extras=(), extra_texture_callback=None,
                   material_maps=None, blu_mode="none", blu_image_path=None,
                   blu_is_team=False, red_not_found=False):
        from contextlib import ExitStack
        from src.shared.constants import EXTRA_TEX_USE_GAME_ORIGINAL
        from src.services.build_context import BuildContext as _BC

        img = base / "img.png"
        Image.new("RGB", (8, 8), color="red").save(img)
        vmt_source = base / "src.vmt"
        vmt_source.write_text('"VertexLitGeneric"\n{\n}\n', encoding="utf-8")

        ctx = _BC("id", "scout_c_scattergun", "c_scattergun", base / "ctx")
        ctx.create_directories()
        ctx.decompile_dir.mkdir(parents=True, exist_ok=True)
        qc = ctx.decompile_dir / "c_scattergun.qc"
        qc.write_text("// qc", encoding="utf-8")

        def fake_create_vtf(png_path, output_dir, *a, **k):
            out = Path(output_dir) / f"{Path(png_path).stem}.vtf"
            out.write_bytes(b"VTF\x00marker")

        def fake_process_image(input_path, output_path, size):
            Path(output_path).write_bytes(b"png")

        captured = {}

        def fake_create_vpk(ctx_arg, *a, **k):
            # Снимок дерева в МОМЕНТ упаковки (после — build делает ctx.cleanup()).
            captured['vtf'] = sorted(p.name for p in Path(ctx_arg.vpkroot_dir).rglob("*.vtf"))
            return str(base / "out.vpk")

        P = "src.services.vpk_service."
        with ExitStack() as es:
            m = es.enter_context
            m(patch(P + "BuildContext.create", return_value=ctx))
            m(patch(P + "TF2Paths.check_crowbar", return_value=(True, "")))
            m(patch(P + "TF2Paths.resolve", return_value=("studiomdl.exe", "tf2_misc_dir.vpk", str(base))))
            m(patch(P + "TF2Paths.resolve_textures_vpk", return_value="tf2_textures_dir.vpk"))
            m(patch(P + "TF2VPKExtractService.check_mdl_exists", return_value=True))
            m(patch(P + "TF2VPKExtractService.extract_file_set", return_value=[str(base / "c_scattergun.mdl")]))
            # Герметичность: не читаем и не пишем глобальный кэш декомпиляции,
            # иначе соседние тесты поймают кэш-хит на c_scattergun. Патчим имена
            # в namespace vpk_service (там импорт на уровне модуля).
            m(patch(P + "get_cached_decompile", return_value=None))
            m(patch(P + "save_to_cache"))
            m(patch(P + "TF2VPKExtractService.extract_vmt_file", return_value=str(vmt_source)))
            m(patch(P + "ModelBuildService.decompile", return_value=str(qc)))
            m(patch(P + "ModelBuildService.extract_cdmaterials_path_from_qc", return_value="models/weapons/c_scattergun"))
            m(patch(P + "ModelBuildService.extract_all_cdmaterials_paths_from_qc", return_value=["models/weapons/c_scattergun"]))
            m(patch(P + "ModelBuildService.extract_texturegroup_filename", return_value="c_scattergun"))
            m(patch(P + "ModelBuildService.extract_texturegroup_structure",
                    return_value={"red_row": ["c_scattergun"], "blu_row": [],
                                  "blu_is_team": blu_is_team,
                                  "main_texture": "c_scattergun",
                                  "extra_materials": list(texturegroup_extras),
                                  "all_rows": [["c_scattergun"]]}))
            m(patch(P + "ModelBuildService.patch_qc_file"))
            m(patch(P + "ModelBuildService.compile"))
            m(patch(P + "ModelBuildService.remove_lod_files"))
            m(patch(P + "VMTService.update_vmt_basetexture_path"))
            m(patch(P + "VMTService.create_vmt_template_from_cdmaterials"))
            m(patch(P + "VPKService._copy_compiled_models_to_vpkroot"))
            m(patch(P + "VPKService._create_vpk_file", side_effect=fake_create_vpk))
            m(patch(P + "TextureService.create_vtf", side_effect=fake_create_vtf))
            m(patch(P + "TextureService.process_image", side_effect=fake_process_image))
            if red_not_found:
                # Имитируем «игровая RED-текстура не найдена» → должно дать warning.
                m(patch(P + "VPKService._get_original_vtf_bytes", return_value=None))
            ok, msg = VPKService.build_vpk(
                image_path=(EXTRA_TEX_USE_GAME_ORIGINAL if red_not_found else str(img)),
                mode="scout_c_scattergun",
                filename="out.vpk",
                size=(4, 4),
                format_type="DXT1",
                flags=[],
                vtf_options={},
                tf2_root_dir=str(base),
                export_folder=str(base),
                language="en",
                panel_extra_textures=panel_extra_textures,
                extra_texture_callback=extra_texture_callback,
                material_maps=material_maps,
                blu_mode=blu_mode,
                blu_image_path=blu_image_path,
            )
        return ok, msg, captured.get('vtf', [])

    def test_produces_expected_vtf_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            extra_png = base / "shell.png"
            Image.new("RGB", (4, 4), color="blue").save(extra_png)

            ok, msg, vtf_names = self._run_build(
                base, panel_extra_textures={"c_scattergun_shell": str(extra_png)})

            self.assertTrue(ok, msg)
            # Главная текстура и панельный доп.материал — именно с этими (lowercase) именами.
            self.assertIn("c_scattergun.vtf", vtf_names)
            self.assertIn("c_scattergun_shell.vtf", vtf_names)

    def test_extra_material_name_lowercased(self):
        # Имя материала из 2D-панели приводится к нижнему регистру в выходе.
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            extra_png = base / "shell.png"
            Image.new("RGB", (4, 4), color="blue").save(extra_png)

            ok, msg, vtf_names = self._run_build(
                base, panel_extra_textures={"C_Scattergun_SHELL": str(extra_png)})

            self.assertTrue(ok, msg)
            self.assertIn("c_scattergun_shell.vtf", vtf_names)
            self.assertNotIn("C_Scattergun_SHELL.vtf", vtf_names)

    def test_texturegroup_extra_and_detail_map(self):
        # Шире покрываем build_vpk: доп.материал из $texturegroup (через callback)
        # и файловая карта detail на главном материале — снимок VTF фиксирует их имена.
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            shell_png = base / "shell2.png"
            Image.new("RGB", (4, 4), color="green").save(shell_png)
            detail_png = base / "detail.png"
            Image.new("RGB", (4, 4), color="white").save(detail_png)

            def extra_cb(material_name, weapon_key):
                return str(shell_png)

            ok, msg, vtf_names = self._run_build(
                base,
                panel_extra_textures={},
                texturegroup_extras=["c_scattergun_shell2"],
                extra_texture_callback=extra_cb,
                material_maps={"c_scattergun": {"detail": {"image": str(detail_png)}}},
            )

            self.assertTrue(ok, msg)
            self.assertIn("c_scattergun.vtf", vtf_names)         # главный
            self.assertIn("c_scattergun_shell2.vtf", vtf_names)  # доп. из texturegroup
            self.assertIn("c_scattergun_detail.vtf", vtf_names)  # карта detail

    def test_blu_team_texture_only_for_real_team(self):
        # Командная (BLU) текстура создаётся ТОЛЬКО при настоящей команде
        # (blu_is_team). У вариант-онли оружия (австралий) — НЕ создаётся.
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            blu_img = base / "blu.vtf"
            blu_img.write_bytes(b"VTF\x00blu")

            # Настоящая команда → BLU есть.
            ok, msg, vtf_names = self._run_build(
                base, panel_extra_textures={},
                blu_mode="upload", blu_image_path=str(blu_img), blu_is_team=True)
            self.assertTrue(ok, msg)
            self.assertIn("c_scattergun_blue.vtf", vtf_names)

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            blu_img = base / "blu.vtf"
            blu_img.write_bytes(b"VTF\x00blu")

            # Нет команды (как у скаттергана: обычный+австралий) → BLU подавлен,
            # даже если blu_mode='upload'. Регресс на c_scattergun_blue.
            ok, msg, vtf_names = self._run_build(
                base, panel_extra_textures={},
                blu_mode="upload", blu_image_path=str(blu_img), blu_is_team=False)
            self.assertTrue(ok, msg)
            self.assertIn("c_scattergun.vtf", vtf_names)
            self.assertNotIn("c_scattergun_blue.vtf", vtf_names)

    def test_missing_game_texture_surfaces_warning(self):
        # Игровая текстура не найдена → сборка успешна, но в сообщении есть
        # предупреждение (иначе пользователь узнаёт о фиолете только в игре).
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ok, msg = self._run_build(
                base, panel_extra_textures={}, red_not_found=True)[:2]
            self.assertTrue(ok, msg)
            self.assertIn("Warnings:", msg)            # en по умолчанию
            self.assertIn("c_scattergun", msg)         # имя проблемного материала


class BuildContextWarnTests(unittest.TestCase):
    def test_warn_collects_and_dedups(self):
        ctx = BuildContext("id", "m", "w", Path("/tmp/x"))
        self.assertEqual(ctx.warnings, [])
        ctx.warn("texture X missing")
        ctx.warn("texture X missing")   # дубль не добавляется
        ctx.warn("texture Y missing")
        self.assertEqual(ctx.warnings, ["texture X missing", "texture Y missing"])


if __name__ == "__main__":
    unittest.main()
