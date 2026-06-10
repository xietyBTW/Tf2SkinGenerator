import builtins
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from src.data.weapons import SPECIAL_MODES
from src.data.translations import TRANSLATIONS
from src.services.build_context import BuildContext
from src.services.vpk_service import VPKService
from src.shared.exceptions import VPKCreationError, RequiredFileMissingError as SharedFileNotFoundError


class VPKServiceTests(unittest.TestCase):
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
                            ok, msg, _ = VPKService._build_special_mode_vpk(
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
                    ok, msg, vmt_to_delete = VPKService._build_special_mode_vpk(
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
                            ok, msg, _ = VPKService._build_special_mode_vpk(
                                ctx, "critHIT", str(base / "img.png"), (4, 4), "DXT1", [], vtf_options={"normal": True}
                            )
            self.assertTrue(ok, msg)

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


if __name__ == "__main__":
    unittest.main()
