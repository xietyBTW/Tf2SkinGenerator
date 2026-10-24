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
from src.services.material_plan import plan_materials
from src.services.vpk_texture_builder import VpkTextureBuilder
from src.services.texture_service import TextureService
from src.services.packaging_service import PackagingService
from src.services.model_service import ModelService
from src.shared.validators import validate_build_params
from src.shared.exceptions import VPKCreationError, RequiredFileMissingError as SharedFileNotFoundError


class PlanMaterialsBypassTests(unittest.TestCase):
    """plan_materials должен прокинуть выбранную папку обхода в patch_qc_file"""

    def _minimal_qc(self, tmp: str) -> str:
        qc = Path(tmp) / "m.qc"
        qc.write_text(
            '$modelname "weapons/c_x.mdl"\n'
            '$cdmaterials "models\\weapons\\c_items"\n'
            '$texturegroup "skinfamilies"\n{\n\t{ "c_x" }\n}\n',
            encoding="utf-8")
        return str(qc)

    def _run(self, bypass_prefix):
        captured = {}

        def fake_patch(qc_path, prefix="console"):
            captured["prefix"] = prefix

        with tempfile.TemporaryDirectory() as tmp:
            qc = self._minimal_qc(tmp)
            ctx = BuildContext("id", "scout_c_x", "c_x", Path(tmp) / "ctx")
            ctx.create_directories()
            with patch("src.services.model_build_service.ModelBuildService.patch_qc_file",
                       side_effect=fake_patch):
                plan_materials(
                    qc, "scout_c_x", "c_x", ctx, "c_x", None, None,
                    {}, None, False, "none", None, False, None, None,
                    bypass_prefix=bypass_prefix,
                )
        return captured.get("prefix")

    def test_console_default_forwarded(self):
        self.assertEqual(self._run("console"), "console")

    def test_vgui_prefix_forwarded(self):
        self.assertEqual(
            self._run("vgui\\replay\\thumbnails"), "vgui\\replay\\thumbnails")


class PlanMaterialsOwnOnlyTests(unittest.TestCase):
    """Часы-вьюмодель (Часы ярого поклонника): руки шпиона стоят в строке
    первыми, но это общая текстура всего его оружия - главной должна стать
    текстура часов, а руки не попадают в мод ни запросом, ни оригиналом"""

    def test_watch_viewmodel_builds_only_the_watch(self):
        rows = ('\t{ "spy_hands_red" "ttg_watch" "spy_hands_blue" }\n'
                '\t{ "spy_hands_blue" "ttg_watch" "spy_hands_blue" }\n')
        with tempfile.TemporaryDirectory() as tmp:
            qc = Path(tmp) / "v_ttg_watch_spy.qc"
            qc.write_text(
                '$modelname "weapons/v_models/v_ttg_watch_spy.mdl"\n'
                '$cdmaterials "models\\weapons\\c_items"\n'
                '$texturegroup "skinfamilies"\n{\n' + rows + '}\n', encoding="utf-8")
            ctx = BuildContext("id", "spy_v_ttg_watch_spy", "spy_hands_red", Path(tmp) / "ctx")
            ctx.create_directories()
            plan = plan_materials(
                str(qc), "spy_v_ttg_watch_spy", "v_ttg_watch_spy", ctx, "spy_hands_red",
                None, None, {}, None, False, "none", None, False, None, None)
        self.assertEqual(plan.texture_filename, "ttg_watch")
        self.assertEqual(plan.extra_materials, [])
        self.assertEqual(plan.blu_row, [])
        self.assertFalse([m for m in plan.blacklisted_extra if "hands" in m])


class PlanMaterialsAskSplitTests(unittest.TestCase):
    """Сборка спрашивает то, что человек видел карточкой, остальное - молча

    Тело шпиона: глаза в геометрии, но без текстуры (карточки нет) - молча;
    убер-вариант не в геометрии, но страница показала его в «Прочем» -
    спросят; `spy_red` из ЧС и маска (своя страница) - молча, оригиналом
    """

    def test_spy_body_split(self):
        row = ('{ "spy_head_red" "eyeball_l" "spy_red" "mask_spy" '
               '"spy_red_invun" "spy_red_zombie" "mask_scout" }')
        with tempfile.TemporaryDirectory() as tmp:
            qc = Path(tmp) / "spy.qc"
            qc.write_text(
                '$modelname "player/spy.mdl"\n'
                '$cdmaterials "models\\player\\spy"\n'
                '$texturegroup "skinfamilies"\n{\n\t' + row + '\n\t' + row + '\n}\n',
                encoding="utf-8")
            ctx = BuildContext("id", "spy_body", "spy_head_red", Path(tmp) / "ctx")
            ctx.create_directories()
            weights = {"spy_head_red": 50, "eyeball_l": 5, "spy_red": 40,
                       "mask_spy": 5, "mask_scout": 5}
            with patch("src.data.material_filter._user_patterns", return_value=["=spy_red"]),                  patch("src.services.qc_skin_parser.mesh_material_weights",
                       return_value=weights):
                plan = plan_materials(
                    str(qc), "spy_body", "spy", ctx, "spy_head_red", None, None,
                    {}, None, False, "none", None, False, None, None,
                    misc_materials=["spy_red_invun", "SPY_RED_ZOMBIE", "spy_red",
                                    "not_in_this_model"],
                )
        self.assertEqual(plan.extra_materials, ["spy_red_invun", "spy_red_zombie"])
        self.assertEqual(
            set(plan.blacklisted_extra),
            {"eyeball_l", "spy_red", "mask_spy", "mask_scout"})


class VPKServiceTests(unittest.TestCase):
    def test_resolve_weapon_key_weapon(self):
        # Обычное оружие: weapon_key = суффикс после первого '_'
        self.assertEqual(VPKService._resolve_weapon_key("scout_c_scattergun", None), ("c_scattergun", None))
        # Без '_' - возвращаем сам mode
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
            self.assertEqual(validate_build_params("", "m", "a.vpk", (1, 1), "DXT1", "x", t), t["error_image_not_specified"])
            self.assertEqual(validate_build_params(str(img), "", "a.vpk", (1, 1), "DXT1", "x", t), t["error_mode_not_specified"])
            self.assertEqual(validate_build_params(str(img), "m", "", (1, 1), "DXT1", "x", t), t["error_filename_not_specified"])
            self.assertEqual(validate_build_params(str(img), "m", "a.txt", (1, 1), "DXT1", "x", t), t["error_filename_no_vpk"])
            self.assertEqual(validate_build_params(str(img), "m", "a.vpk", (1, ), "DXT1", "x", t), t["error_size_invalid"])
            self.assertEqual(validate_build_params(str(img), "m", "a.vpk", ("1", 1), "DXT1", "x", t), t["error_size_not_int"])
            self.assertEqual(validate_build_params(str(img), "m", "a.vpk", (0, 1), "DXT1", "x", t), t["error_size_not_positive"])
            self.assertIn(t["error_format_invalid"].split(":")[0], validate_build_params(str(img), "m", "a.vpk", (1, 1), "BAD", "x", t))

    def test_validate_build_params_custom_vtf(self):
        t = TRANSLATIONS["en"]
        self.assertEqual(validate_build_params("a", "m", "a.vpk", (1, 1), "DXT1", "x", t, custom_vtf_path="missing"), t["error_custom_vtf_not_found"].format(path="missing"))
    
    def test_validate_build_params_tf2_root_errors(self):
        t = TRANSLATIONS["en"]
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            img = base / "img.png"
            Image.new("RGB", (2, 2), color="red").save(img)
            self.assertEqual(
                validate_build_params(str(img), "scout_c_scattergun", "a.vpk", (1, 1), "DXT1", "missing", t),
                t["error_tf2_not_found"].format(path="missing")
            )
            not_dir = base / "file.txt"
            not_dir.write_text("x", encoding="utf-8")
            self.assertEqual(
                validate_build_params(str(img), "scout_c_scattergun", "a.vpk", (1, 1), "DXT1", str(not_dir), t),
                t["error_tf2_not_dir"].format(path=str(not_dir))
            )
    
    def test_validate_build_params_custom_vtf_not_file(self):
        t = TRANSLATIONS["en"]
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            dir_path = base / "dir"
            dir_path.mkdir()
            self.assertEqual(
                validate_build_params("a", "m", "a.vpk", (1, 1), "DXT1", "x", t, custom_vtf_path=str(dir_path)),
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
            TextureService.process_image(str(rgb_path), str(out_rgb), (4, 4))
            TextureService.process_image(str(rgba_path), str(out_rgba), (4, 4))
            self.assertTrue(out_rgb.exists())
            self.assertTrue(out_rgba.exists())
    
    def test_process_image_missing(self):
        with self.assertRaises(builtins.FileNotFoundError):
            TextureService.process_image("missing.png", "out.png", (4, 4))

    def test_create_vtf_writes_options(self):
        from srctools.vtf import VTF, VTFFlags
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            png_path = base / "img.png"
            Image.new("RGBA", (8, 8), color=(255, 0, 0, 128)).save(png_path)
            TextureService.create_vtf(str(png_path), str(base), "DXT1", ["CLAMPS"], {"nomipmaps": True})
            with open(base / "img.vtf", "rb") as f:
                vtf = VTF.read(f, header_only=True)
            self.assertEqual(vtf.mipmap_count, 1)
            self.assertIn(VTFFlags.CLAMP_S, vtf.flags)
            self.assertIn(VTFFlags.NO_MIP, vtf.flags)

    def test_create_vtf_error(self):
        from src.shared.exceptions import VTFCreationError
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            png_path = base / "img.png"
            Image.new("RGB", (12, 8), color="red").save(png_path)
            with self.assertRaises(VTFCreationError) as cm:
                TextureService.create_vtf(str(png_path), str(base), "DXT1", [], {})
            # Причина (размер не степень двойки) доходит до сообщения
            self.assertIn("power of 2", str(cm.exception))
            self.assertFalse((base / "img.vtf").exists())

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

            # pack_directory резолвит vpk.exe через ToolPaths.get_vpk_tool и делает
            # pre-flight .exists() - патчим этот символ и даём реально существующий stub
            vpk_tool = base / "vpk.exe"; vpk_tool.write_bytes(b"stub")

            with patch("src.services.packaging_service.ToolPaths.get_vpk_tool", return_value=vpk_tool):
                with patch("src.services.packaging_service.subprocess.run", side_effect=fake_run):
                    output = PackagingService.create_vpk_file(ctx, "out.vpk", export_folder=str(base))
                    self.assertTrue(Path(output).exists())

            with patch("src.services.packaging_service.ToolPaths.get_vpk_tool", return_value=vpk_tool):
                with patch("src.services.packaging_service.subprocess.run", return_value=type("R", (), {"returncode": 1, "stdout": "bad", "stderr": "err"})()):
                    with self.assertRaises(VPKCreationError):
                        PackagingService.create_vpk_file(ctx, "out2.vpk", export_folder=str(base))

            with patch("src.services.packaging_service.ToolPaths.get_vpk_tool", return_value=vpk_tool):
                with patch("src.services.packaging_service.subprocess.run", return_value=type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()):
                    with self.assertRaises(SharedFileNotFoundError):
                        PackagingService.create_vpk_file(ctx, "out3.vpk", export_folder=str(base))

    def test_copy_compiled_models_to_vpkroot(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ctx = BuildContext("id", "m", "w", base / "ctx")
            ctx.create_directories()
            (ctx.compile_dir / "v_test.mdl").write_text("x", encoding="utf-8")
            (ctx.compile_dir / "v_test.vvd").write_text("x", encoding="utf-8")
            with patch("src.services.model_service.ModelBuildService.extract_modelname_path", return_value="models/weapons/v_test.mdl"):
                ModelService.copy_compiled_models_to_vpkroot(ctx, "qc")
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
                # Настоящая картинка: из неё строится карта нормалей
                Image.new("RGB", size, "gray").save(output_path)
            
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
        """Характеризационный тест РЕАЛЬНОГО пути рендера (без custom_vtf)

        В отличие от happy-path с готовым VTF, здесь отрабатывает ветка
        `elif image_path:` -> TextureService.render_image_to_vtf (с замоканными
        примитивами process_image/create_vtf), затем извлечение оригинального
        VMT и запись главного VMT. Покрывает тело цикла рендера для оружия с
        одной текстурой (без extra/blu)
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
                # Как create_vtf: кладём .vtf рядом по имени PNG
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
                patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.check_mdl_exists", return_value=True),
                patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.extract_file_set", return_value=[str(base / "c_scattergun.mdl")]),
                patch("src.services.model_decompile_service.decompile_into", return_value=str(base / "a.qc")),
                patch(P + "ModelBuildService.extract_cdmaterials_path_from_qc", return_value="models/weapons/c_scattergun"),
                patch(P + "ModelBuildService.extract_all_cdmaterials_paths_from_qc", return_value=["models/weapons/c_scattergun"]),
                patch(P + "ModelBuildService.extract_texturegroup_filename", return_value="c_scattergun"),
                patch(P + "ModelBuildService.extract_texturegroup_structure", return_value=tg),
                patch(P + "ModelBuildService.patch_qc_file"),
                patch(P + "ModelBuildService.compile"),
                patch(P + "ModelBuildService.remove_lod_files"),
                patch(P + "TF2Paths.resolve_textures_vpk", return_value="tf2_textures_dir.vpk"),
                patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.extract_vmt_file", return_value=str(vmt_source)),
                patch(P + "ModelService.copy_compiled_models_to_vpkroot"),
                patch(P + "PackagingService.create_vpk_file", return_value=str(base / "out.vpk")),
                patch(P + "DirectoryPaths.TEMP_VMT_EXTRACT_DIR", base / "temp_vmt"),
                patch(TS + "is_animated_image", return_value=False),
                patch(TS + "process_image", side_effect=fake_process_image),
            ]
            with contextlib.ExitStack() as stack:
                for p in patches:
                    stack.enter_context(p)
                # Захватываем мок create_vtf, чтобы подтвердить, что ветка рендера
                # реально отработала (файлы к концу удаляет ctx.cleanup)
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
            # Ветка `elif image_path:` -> render_image_to_vtf -> create_vtf отработала
            self.assertTrue(m_create.called)

    def test_build_vpk_extra_materials_render_flow(self):
        """РЕАЛЬНЫЙ рендер доп. материала (extra_materials): пользователь дал
        отдельную картинку для столбца shell -> цикл extra-материалов рендерит её
        и пишет VMT. Покрывает тело цикла extra-материалов (не custom_vtf)"""
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

            # Третий аргумент - сколько материалов спросят ПОСЛЕ этого:
            # по нему вопрос решает, предлагать ли «и так для остальных»
            def extra_cb(mat, wk, remaining=0):
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
                patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.check_mdl_exists", return_value=True),
                patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.extract_file_set", return_value=[str(base / "c_scattergun.mdl")]),
                patch("src.services.model_decompile_service.decompile_into", return_value=str(base / "a.qc")),
                patch(P + "ModelBuildService.extract_cdmaterials_path_from_qc", return_value="models/weapons/c_scattergun"),
                patch(P + "ModelBuildService.extract_all_cdmaterials_paths_from_qc", return_value=["models/weapons/c_scattergun"]),
                patch(P + "ModelBuildService.extract_texturegroup_filename", return_value="c_scattergun"),
                patch(P + "ModelBuildService.extract_texturegroup_structure", return_value=tg),
                patch(P + "ModelBuildService.patch_qc_file"),
                patch(P + "ModelBuildService.compile"),
                patch(P + "ModelBuildService.remove_lod_files"),
                patch(P + "TF2Paths.resolve_textures_vpk", return_value="tf2_textures_dir.vpk"),
                patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.extract_vmt_file", return_value=str(vmt_source)),
                patch(P + "ModelService.copy_compiled_models_to_vpkroot"),
                patch(P + "PackagingService.create_vpk_file", return_value=str(base / "out.vpk")),
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
            # Главная + shell -> create_vtf вызван минимум дважды
            self.assertGreaterEqual(m_create.call_count, 2)

    def test_build_vpk_blu_team_render_flow(self):
        """РЕАЛЬНЫЙ рендер BLU-командной текстуры (blu_mode='upload', blu_is_team).
        Покрывает ветку _build_blu_team_texture с генерацией {texture}_blue из
        отдельной картинки"""
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
                patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.check_mdl_exists", return_value=True),
                patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.extract_file_set", return_value=[str(base / "c_scattergun.mdl")]),
                patch("src.services.model_decompile_service.decompile_into", return_value=str(base / "a.qc")),
                patch(P + "ModelBuildService.extract_cdmaterials_path_from_qc", return_value="models/weapons/c_scattergun"),
                patch(P + "ModelBuildService.extract_all_cdmaterials_paths_from_qc", return_value=["models/weapons/c_scattergun"]),
                patch(P + "ModelBuildService.extract_texturegroup_filename", return_value="c_scattergun"),
                patch(P + "ModelBuildService.extract_texturegroup_structure", return_value=tg),
                patch(P + "ModelBuildService.patch_qc_file"),
                patch(P + "ModelBuildService.compile"),
                patch(P + "ModelBuildService.remove_lod_files"),
                patch(P + "TF2Paths.resolve_textures_vpk", return_value="tf2_textures_dir.vpk"),
                patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.extract_vmt_file", return_value=str(vmt_source)),
                patch(P + "ModelService.copy_compiled_models_to_vpkroot"),
                patch(P + "PackagingService.create_vpk_file", return_value=str(base / "out.vpk")),
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
            # Главная + BLU -> create_vtf вызван минимум дважды
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
                        with patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.check_mdl_exists", return_value=True):
                            with patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.extract_file_set", return_value=[str(base / "c_scattergun.mdl")]):
                                with patch("src.services.model_decompile_service.decompile_into", return_value=str(base / "a.qc")):
                                    with patch("src.services.vpk_service.ModelBuildService.extract_cdmaterials_path_from_qc", return_value="models/weapons/c_scattergun"):
                                        with patch("src.services.vpk_service.ModelBuildService.extract_texturegroup_filename", return_value="c_scattergun"):
                                            with patch("src.services.vpk_service.ModelBuildService.patch_qc_file"):
                                                with patch("src.services.vpk_service.ModelBuildService.compile"):
                                                    with patch("src.services.vpk_service.ModelBuildService.remove_lod_files"):
                                                        with patch("src.services.vpk_service.TF2Paths.resolve_textures_vpk", return_value="tf2_textures_dir.vpk"):
                                                            with patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.extract_vmt_file", return_value=str(vmt_source)):
                                                                with patch("src.services.vmt_service.VMTService.update_vmt_basetexture_path"):
                                                                    with patch("src.services.vmt_service.VMTService.create_vmt_template_from_cdmaterials"):
                                                                        with patch("src.services.vpk_service.ModelService.copy_compiled_models_to_vpkroot"):
                                                                            with patch("src.services.vpk_service.PackagingService.create_vpk_file", return_value=str(base / "out.vpk")):
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
        """Характеризационный тест ветки рук (mode in HAND_MODE_KEYS)

        Фиксирует, что сборка рук проходит конвейер декомпиляции/компиляции и
        упаковки так же, как оружие, но weapon_key берётся из arm_model, а
        $texturegroup ограничивается текстурами руки (restrict_to_materials)
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
                 patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.check_mdl_exists", return_value=True), \
                 patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.extract_file_set", return_value=[str(base / "c_scout_arms.mdl")]), \
                 patch("src.services.model_decompile_service.decompile_into", return_value=str(base / "a.qc")), \
                 patch(P + "ModelBuildService.extract_cdmaterials_path_from_qc", return_value="models/player/scout"), \
                 patch(P + "ModelBuildService.extract_all_cdmaterials_paths_from_qc", return_value=["models/player/scout"]), \
                 patch(P + "ModelBuildService.extract_texturegroup_filename", return_value="scout_hands"), \
                 patch(P + "ModelBuildService.extract_texturegroup_structure", return_value=tg), \
                 patch(P + "ModelBuildService.patch_qc_file"), \
                 patch(P + "ModelBuildService.compile"), \
                 patch(P + "ModelBuildService.remove_lod_files"), \
                 patch(P + "TF2Paths.resolve_textures_vpk", return_value="tf2_textures_dir.vpk"), \
                 patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.extract_vmt_file", return_value=str(vmt_source)), \
                 patch("src.services.vmt_service.VMTService.update_vmt_basetexture_path"), \
                 patch("src.services.vmt_service.VMTService.create_vmt_template_from_cdmaterials"), \
                 patch(P + "ModelService.copy_compiled_models_to_vpkroot"), \
                 patch(P + "PackagingService.create_vpk_file", return_value=str(base / "out.vpk")), \
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
        """Характеризационный тест ветки скина тела персонажа (PLAYER_BODY_MODE_KEYS)

        weapon_key берётся из стема mdl_path персонажа, модель замены принудительно
        выключается, сборка идёт через обычный конвейер декомпиляции/упаковки
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
                 patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.check_mdl_exists", return_value=True), \
                 patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.extract_file_set", return_value=[str(base / "demo.mdl")]), \
                 patch("src.services.model_decompile_service.decompile_into", return_value=str(base / "a.qc")), \
                 patch(P + "ModelBuildService.extract_cdmaterials_path_from_qc", return_value="models/player/demo"), \
                 patch(P + "ModelBuildService.extract_all_cdmaterials_paths_from_qc", return_value=["models/player/demo"]), \
                 patch(P + "ModelBuildService.extract_texturegroup_filename", return_value="demo"), \
                 patch(P + "ModelBuildService.extract_texturegroup_structure", return_value=tg), \
                 patch(P + "ModelBuildService.patch_qc_file"), \
                 patch(P + "ModelBuildService.compile"), \
                 patch(P + "ModelBuildService.remove_lod_files"), \
                 patch(P + "TF2Paths.resolve_textures_vpk", return_value="tf2_textures_dir.vpk"), \
                 patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.extract_vmt_file", return_value=str(vmt_source)), \
                 patch("src.services.vmt_service.VMTService.update_vmt_basetexture_path"), \
                 patch("src.services.vmt_service.VMTService.create_vmt_template_from_cdmaterials"), \
                 patch(P + "ModelService.copy_compiled_models_to_vpkroot"), \
                 patch(P + "PackagingService.create_vpk_file", return_value=str(base / "out.vpk")), \
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
        """Характеризационный тест ветки шапки (mode == 'hat', одиночный класс)

        weapon_key берётся из стема hat_mdl_path; без %s-шаблона и без
        hat_class_models доп. классовые модели не собираются - обычный конвейер
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
                 patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.check_mdl_exists", return_value=True), \
                 patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.extract_file_set", return_value=[str(base / "hat_foo.mdl")]), \
                 patch("src.services.model_decompile_service.decompile_into", return_value=str(base / "a.qc")), \
                 patch(P + "ModelBuildService.extract_cdmaterials_path_from_qc", return_value="models/player/items/all_class"), \
                 patch(P + "ModelBuildService.extract_all_cdmaterials_paths_from_qc", return_value=["models/player/items/all_class"]), \
                 patch(P + "ModelBuildService.extract_texturegroup_filename", return_value="hat_foo"), \
                 patch(P + "ModelBuildService.extract_texturegroup_structure", return_value=tg), \
                 patch(P + "ModelBuildService.patch_qc_file"), \
                 patch(P + "ModelBuildService.compile"), \
                 patch(P + "ModelBuildService.remove_lod_files"), \
                 patch(P + "TF2Paths.resolve_textures_vpk", return_value="tf2_textures_dir.vpk"), \
                 patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.extract_vmt_file", return_value=str(vmt_source)), \
                 patch("src.services.vmt_service.VMTService.update_vmt_basetexture_path"), \
                 patch("src.services.vmt_service.VMTService.create_vmt_template_from_cdmaterials"), \
                 patch(P + "ModelService.copy_compiled_models_to_vpkroot"), \
                 patch(P + "PackagingService.create_vpk_file", return_value=str(base / "out.vpk")), \
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
        (replace_model_enabled + replace_keep_materials, без доп-стилей)

        Имена материалов берутся из reference-SMD, игровой $texturegroup убирается
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
                patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.check_mdl_exists", return_value=True),
                patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.extract_file_set", return_value=[str(base / "c_scattergun.mdl")]),
                patch("src.services.model_decompile_service.decompile_into", return_value=str(base / "a.qc")),
                patch(P + "ModelBuildService.extract_cdmaterials_path_from_qc", return_value="models/weapons/c_scattergun"),
                patch(P + "ModelBuildService.extract_all_cdmaterials_paths_from_qc", return_value=["models/weapons/c_scattergun"]),
                patch(P + "ModelBuildService.extract_texturegroup_filename", return_value="c_scattergun"),
                patch(P + "ModelBuildService.extract_texturegroup_structure", return_value=tg),
                patch(P + "ModelBuildService.patch_qc_file"),
                patch(P + "ModelBuildService.replace_texturegroup_in_qc"),
                patch(P + "ModelBuildService.compile"),
                patch(P + "ModelBuildService.remove_lod_files"),
                patch("src.services.vpk_model_pipeline.VpkModelPipeline._resolve_replace_model_smd", return_value=str(user_smd)),
                patch("src.services.vpk_model_pipeline.VpkModelPipeline._apply_model_replacement"),
                patch("src.services.vpk_model_pipeline.VpkModelPipeline._find_decompiled_reference_smd", return_value=str(user_smd)),
                patch(P + "SMDService.ordered_unique_materials", return_value=["c_scattergun"]),
                patch(P + "TF2Paths.resolve_textures_vpk", return_value="tf2_textures_dir.vpk"),
                patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.extract_vmt_file", return_value=str(vmt_source)),
                patch("src.services.vmt_service.VMTService.update_vmt_basetexture_path"),
                patch("src.services.vmt_service.VMTService.create_vmt_template_from_cdmaterials"),
                patch(P + "ModelService.copy_compiled_models_to_vpkroot"),
                patch(P + "PackagingService.create_vpk_file", return_value=str(base / "out.vpk")),
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
        """Характеризационный тест ветки доп-стилей (skin_build_data с tg_overrides)

        _has_skins -> инъекция своего $texturegroup; имена материалов выравниваются
        по reference-SMD. variant_files пуст (цикл рендера вариантов не задействуем)
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
                patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.check_mdl_exists", return_value=True),
                patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.extract_file_set", return_value=[str(base / "c_scattergun.mdl")]),
                patch("src.services.model_decompile_service.decompile_into", return_value=str(base / "a.qc")),
                patch(P + "ModelBuildService.extract_cdmaterials_path_from_qc", return_value="models/weapons/c_scattergun"),
                patch(P + "ModelBuildService.extract_all_cdmaterials_paths_from_qc", return_value=["models/weapons/c_scattergun"]),
                patch(P + "ModelBuildService.extract_texturegroup_filename", return_value="c_scattergun"),
                patch(P + "ModelBuildService.extract_texturegroup_structure", return_value=tg),
                patch(P + "ModelBuildService.patch_qc_file"),
                patch(P + "ModelBuildService.replace_texturegroup_in_qc"),
                patch(P + "ModelBuildService.generate_texturegroup_block", return_value='$texturegroup "skinfamilies" {}'),
                patch(P + "ModelBuildService.compile"),
                patch(P + "ModelBuildService.remove_lod_files"),
                patch("src.services.vpk_model_pipeline.VpkModelPipeline._resolve_replace_model_smd", return_value=str(user_smd)),
                patch("src.services.vpk_model_pipeline.VpkModelPipeline._apply_model_replacement"),
                patch("src.services.vpk_model_pipeline.VpkModelPipeline._find_decompiled_reference_smd", return_value=str(user_smd)),
                patch("src.services.texture_build.styles.remap_skin_data_to_smd", side_effect=lambda sbd, mats: sbd),
                patch(P + "SMDService.ordered_unique_materials", return_value=["c_scattergun"]),
                patch(P + "TF2Paths.resolve_textures_vpk", return_value="tf2_textures_dir.vpk"),
                patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.extract_vmt_file", return_value=str(vmt_source)),
                patch("src.services.vmt_service.VMTService.update_vmt_basetexture_path"),
                patch("src.services.vmt_service.VMTService.create_vmt_template_from_cdmaterials"),
                patch(P + "ModelService.copy_compiled_models_to_vpkroot"),
                patch(P + "PackagingService.create_vpk_file", return_value=str(base / "out.vpk")),
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
        with patch("src.services.vpk_service.validate_build_params", return_value="bad"):
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
            with patch("src.services.vpk_service.validate_build_params", return_value=None):
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
            with patch("src.services.vpk_service.validate_build_params", return_value=None):
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
            with patch("src.services.vpk_service.validate_build_params", return_value=None):
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
            with patch("src.services.vpk_service.validate_build_params", return_value=None):
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
            with patch("src.services.vpk_service.validate_build_params", return_value=None):
                with patch("src.services.vpk_service.BuildContext.create", return_value=ctx):
                    with patch("src.services.vpk_service.TF2Paths.check_crowbar", return_value=(True, "")):
                        with patch("src.services.vpk_service.TF2Paths.resolve", return_value=("studiomdl.exe", "tf2_misc_dir.vpk", str(base))):
                            with patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.check_mdl_exists", return_value=False):
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
            with patch("src.services.vpk_service.validate_build_params", return_value=None):
                with patch("src.services.vpk_service.BuildContext.create", return_value=ctx):
                    with patch("src.services.vpk_service.TF2Paths.check_crowbar", return_value=(True, "")):
                        with patch("src.services.vpk_service.TF2Paths.resolve", return_value=("studiomdl.exe", "tf2_misc_dir.vpk", str(base))):
                            with patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.check_mdl_exists", return_value=True):
                                with patch("src.services.model_decompile_service.decompile_into", return_value=None):
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
            with patch("src.services.model_service.smd_service.find_reference_smd", return_value=None):
                ModelService.generate_uv_layout(ctx, "weapon", (4, 4), export_folder=str(base))
    
    def test_generate_uv_layout_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ctx = BuildContext("id", "m", "w", base / "ctx")
            ctx.create_directories()
            smd_path = base / "weapon_reference.smd"
            smd_path.write_text("x", encoding="utf-8")
            with patch("src.services.model_service.smd_service.find_reference_smd", return_value=str(smd_path)):
                with patch("src.services.uv_layout_service.UVLayoutService.generate_uv_layout_from_smd", return_value=True) as generate:
                    ModelService.generate_uv_layout(ctx, "weapon", (4, 4), export_folder=str(base))
            generate.assert_called()

    def test_render_extra_texture_missing_returns_false(self):
        # Нет файла/пустой путь -> False, без побочных эффектов
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            for bad in (None, "", os.path.join(tmp, "nope.png")):
                self.assertFalse(VpkTextureBuilder._render_extra_texture(
                    "mat", bad, out, out / "main.vmt",
                    "models/weapons/c_models", (4, 4), "DXT1", [], {},
                ))
            self.assertEqual(list(out.glob("*.vtf")), [])

    def test_render_extra_texture_vtf_input_copies_and_writes_vmt(self):
        # На вход .vtf -> копируется как есть + создаётся VMT (без сжатия)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            src_vtf = out / "src.vtf"
            src_vtf.write_bytes(b"VTF\x00fake")
            ok = VpkTextureBuilder._render_extra_texture(
                "lefteye_bloody", str(src_vtf), out, out / "main.vmt",
                "models/weapons/c_models", (4, 4), "DXT1", [], {},
            )
            self.assertTrue(ok)
            self.assertTrue((out / "lefteye_bloody.vtf").exists())
            self.assertTrue((out / "lefteye_bloody.vmt").exists())
            self.assertEqual((out / "lefteye_bloody.vtf").read_bytes(), b"VTF\x00fake")


    def test_render_extra_texture_image_input_renders_vtf(self):
        # Обычная картинка -> ресайз + VTF (через render_image_to_vtf) + VMT
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            img = out / "skin.png"
            Image.new("RGB", (4, 4), color="blue").save(img)
            with patch("src.services.texture_service.TextureService.is_animated_image", return_value=False), \
                 patch("src.services.texture_service.TextureService.process_image") as m_proc, \
                 patch("src.services.texture_service.TextureService.create_vtf") as m_vtf:
                ok = VpkTextureBuilder._render_extra_texture(
                    "shell", str(img), out, out / "main.vmt",
                    "models/weapons/c_models", (4, 4), "DXT1", [], {},
                )
            self.assertTrue(ok)
            m_proc.assert_called_once()
            m_vtf.assert_called_once()
            self.assertTrue((out / "shell.vmt").exists())

    def test_remap_skin_data_to_smd_by_index(self):
        # UI собрал 'Material.001', SMD-материал 'material' -> ремап по индексу,
        # картинки вариантов сохраняются
        sbd = {
            'mesh_materials': ['Material.001'],
            'tg_overrides': {1: {'Material.001': 'Material.001_bloody'}},
            'variant_files': {'Material.001_bloody': '/img/bloody.png'},
        }
        out = VpkTextureBuilder._remap_skin_data_to_smd(sbd, ['material'])
        self.assertEqual(out['mesh_materials'], ['material'])
        self.assertEqual(out['tg_overrides'], {1: {'material': 'material_bloody'}})
        self.assertEqual(out['variant_files'], {'material_bloody': '/img/bloody.png'})

    def test_remap_skin_data_to_smd_empty_smd_noop(self):
        sbd = {'mesh_materials': ['a'], 'tg_overrides': {1: {'a': 'a_x'}},
               'variant_files': {'a_x': '/p'}}
        self.assertIs(VpkTextureBuilder._remap_skin_data_to_smd(sbd, []), sbd)


class BuildVpkCharacterizationTests(unittest.TestCase):
    """
    Характеризационный тест build_vpk: фиксирует, КАКИЕ VTF-файлы (и с какими
    именами) производит пайплайн для обычного оружия с панельной доп.текстурой.
    Внешние инструменты (crowbar/studiomdl/сжатие VTF/упаковка) замоканы; create_vtf
    пишет маркер-файл, чтобы наблюдать именование материалов через весь конвейер

    Назначение - сетка безопасности под рефакторинг build_vpk: рефактор не должен
    менять состав/имена выходных файлов. Имена материалов через пайплайн - то самое
    место, что ломалось ранее (фиолетовые текстуры)
    """

    def _run_build(self, base: Path, panel_extra_textures: dict = None, *,
                   texturegroup_extras=(), extra_texture_callback=None,
                   material_maps=None, blu_mode="none", blu_image_path=None,
                   blu_is_team=False, red_not_found=False,
                   mode="scout_c_scattergun", weapon_key="c_scattergun",
                   cdmat="models/weapons/c_scattergun", patched_cdmat=None,
                   tg=None, extra_patches=None, decompiled=None, **build_kwargs):
        """Гоняет build_vpk с замоканными инструментами

        -> (ok, msg, имена VTF). Полное дерево vpkroot в момент упаковки
        ({путь: байты}) - в self.tree, моки из extra_patches - в self.mocks,
        главный прогресс - в self.progress. decompiled - {имя: текст} файлов
        декомпиляции (QC/SMD), их текст в момент упаковки - в self.decompiled
        """
        from contextlib import ExitStack
        from src.shared.constants import EXTRA_TEX_USE_GAME_ORIGINAL
        from src.services.build_context import BuildContext as _BC

        img = base / "img.png"
        Image.new("RGB", (8, 8), color="red").save(img)
        vmt_source = base / "src.vmt"
        vmt_source.write_text('"VertexLitGeneric"\n{\n}\n', encoding="utf-8")

        ctx = _BC("id", mode, weapon_key, base / "ctx")
        ctx.create_directories()
        ctx.decompile_dir.mkdir(parents=True, exist_ok=True)
        qc = ctx.decompile_dir / f"{weapon_key}.qc"
        qc.write_text("// qc", encoding="utf-8")
        for name, text in (decompiled or {}).items():
            (ctx.decompile_dir / name).write_text(text, encoding="utf-8")

        def fake_create_vtf(png_path, output_dir, *a, **k):
            out = Path(output_dir) / f"{Path(png_path).stem}.vtf"
            out.write_bytes(b"VTF\x00marker")

        def fake_process_image(input_path, output_path, size):
            Path(output_path).write_bytes(b"png")

        captured = {}

        def fake_create_vpk(ctx_arg, *a, **k):
            # Снимок дерева в МОМЕНТ упаковки (после - build делает ctx.cleanup())
            root = Path(ctx_arg.vpkroot_dir)
            captured['vtf'] = sorted(p.name for p in root.rglob("*.vtf"))
            captured['tree'] = {p.relative_to(root).as_posix(): p.read_bytes()
                                for p in sorted(root.rglob("*")) if p.is_file()}
            captured['decompiled'] = {n: (ctx.decompile_dir / n).read_text(encoding="utf-8")
                                      for n in (decompiled or {})}
            return str(base / "out.vpk")

        if tg is None:
            tg = {"red_row": [weapon_key], "blu_row": [],
                  "blu_is_team": blu_is_team,
                  "main_texture": weapon_key,
                  "extra_materials": list(texturegroup_extras),
                  "all_rows": [[weapon_key]]}
        self.progress = []
        self.mocks = {}
        P = "src.services.vpk_service."
        with ExitStack() as es:
            m = es.enter_context
            m(patch(P + "BuildContext.create", return_value=ctx))
            m(patch(P + "TF2Paths.check_crowbar", return_value=(True, "")))
            m(patch(P + "TF2Paths.resolve", return_value=("studiomdl.exe", "tf2_misc_dir.vpk", str(base))))
            m(patch(P + "TF2Paths.resolve_textures_vpk", return_value="tf2_textures_dir.vpk"))
            m(patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.check_mdl_exists", return_value=True))
            m(patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.extract_file_set", return_value=[str(base / f"{weapon_key}.mdl")]))
            # Герметичность: глобальный кэш декомпиляции не читаем и не пишем,
            # иначе соседние тесты поймают кэш-хит
            m(patch("src.services.model_decompile_service.decompile_into", return_value=str(qc)))
            m(patch(P + "VPKService._is_attachment_only", return_value=False))
            m(patch(P + "DirectoryPaths.TEMP_VMT_EXTRACT_DIR", base / "temp_vmt"))
            m(patch(P + "data_dir", return_value=base / "data"))
            # Правленые VMT человека (tools/edited_vmt) в снимок не попадают
            m(patch("src.services.edited_vmt_service.EditedVMTService.get_edited_vmt", return_value=None))
            m(patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService.extract_vmt_file", return_value=str(vmt_source)))
            # До patch_qc_file - игровой путь, после - путь обхода sv_pure
            cdmat_calls = []

            def fake_cdmat(_qc):
                cdmat_calls.append(_qc)
                if len(cdmat_calls) == 1 or patched_cdmat is None:
                    return cdmat
                return patched_cdmat
            m(patch(P + "ModelBuildService.extract_cdmaterials_path_from_qc", side_effect=fake_cdmat))
            m(patch(P + "ModelBuildService.extract_all_cdmaterials_paths_from_qc", return_value=[cdmat]))
            m(patch(P + "ModelBuildService.extract_texturegroup_filename", return_value=weapon_key))
            m(patch(P + "ModelBuildService.extract_texturegroup_structure", return_value=tg))
            m(patch(P + "ModelBuildService.patch_qc_file"))
            m(patch(P + "ModelBuildService.compile"))
            m(patch(P + "ModelBuildService.remove_lod_files"))
            m(patch("src.services.vmt_service.VMTService.update_vmt_basetexture_path"))
            m(patch("src.services.vmt_service.VMTService.create_vmt_template_from_cdmaterials"))
            m(patch(P + "ModelService.copy_compiled_models_to_vpkroot"))
            m(patch(P + "PackagingService.create_vpk_file", side_effect=fake_create_vpk))
            m(patch("src.services.texture_service.TextureService.create_vtf", side_effect=fake_create_vtf))
            m(patch("src.services.texture_service.TextureService.process_image", side_effect=fake_process_image))
            if red_not_found:
                # Имитируем «игровая RED-текстура не найдена» -> должно дать warning
                m(patch("src.services.texture_build.game_source.get_original_vtf_bytes", return_value=None))
            for target, kw in (extra_patches or {}).items():
                self.mocks[target] = m(patch(target, **kw))
            ok, msg = VPKService.build_vpk(
                image_path=(EXTRA_TEX_USE_GAME_ORIGINAL if red_not_found else str(img)),
                mode=mode,
                filename="out.vpk",
                size=(4, 4),
                format_type="DXT1",
                flags=[],
                vtf_options=build_kwargs.pop("vtf_options", {}),
                tf2_root_dir=str(base),
                export_folder=str(base),
                language="en",
                panel_extra_textures=panel_extra_textures or {},
                extra_texture_callback=extra_texture_callback,
                material_maps=material_maps,
                blu_mode=blu_mode,
                blu_image_path=blu_image_path,
                progress_callback=lambda v, _m: self.progress.append(v),
                **build_kwargs,
            )
        self.tree = captured.get('tree')
        self.decompiled = captured.get('decompiled')
        return ok, msg, captured.get('vtf', [])

    def test_produces_expected_vtf_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            extra_png = base / "shell.png"
            Image.new("RGB", (4, 4), color="blue").save(extra_png)

            ok, msg, vtf_names = self._run_build(
                base, panel_extra_textures={"c_scattergun_shell": str(extra_png)})

            self.assertTrue(ok, msg)
            # Главная текстура и панельный доп.материал - именно с этими (lowercase) именами
            self.assertIn("c_scattergun.vtf", vtf_names)
            self.assertIn("c_scattergun_shell.vtf", vtf_names)

    def test_extra_material_name_lowercased(self):
        # Имя материала из 2D-панели приводится к нижнему регистру в выходе
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
        # и файловая карта detail на главном материале - снимок VTF фиксирует их имена
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            shell_png = base / "shell2.png"
            Image.new("RGB", (4, 4), color="green").save(shell_png)
            detail_png = base / "detail.png"
            Image.new("RGB", (4, 4), color="white").save(detail_png)

            def extra_cb(material_name, weapon_key, remaining=0):
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

    def test_texturegroup_extra_copies_main_on_request(self):
        # «Скопировать главную» - материал ОБЯЗАН оказаться в моде, а не
        # потеряться как ответ None
        from src.shared.constants import EXTRA_TEX_USE_MAIN
        with tempfile.TemporaryDirectory() as tmp:
            ok, msg, vtf_names = self._run_build(
                Path(tmp),
                panel_extra_textures={},
                texturegroup_extras=["c_scattergun_shell2"],
                extra_texture_callback=lambda *a: EXTRA_TEX_USE_MAIN,
            )
            self.assertTrue(ok, msg)
            self.assertIn("c_scattergun_shell2.vtf", vtf_names)

    def test_blu_team_texture_only_for_real_team(self):
        # Командная (BLU) текстура создаётся ТОЛЬКО при настоящей команде
        # (blu_is_team). У вариант-онли оружия (австралий) - НЕ создаётся
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            blu_img = base / "blu.vtf"
            blu_img.write_bytes(b"VTF\x00blu")

            # Настоящая команда -> BLU есть
            ok, msg, vtf_names = self._run_build(
                base, panel_extra_textures={},
                blu_mode="upload", blu_image_path=str(blu_img), blu_is_team=True)
            self.assertTrue(ok, msg)
            self.assertIn("c_scattergun_blue.vtf", vtf_names)

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            blu_img = base / "blu.vtf"
            blu_img.write_bytes(b"VTF\x00blu")

            # Нет команды (как у скаттергана: обычный+австралий) -> BLU подавлен,
            # даже если blu_mode='upload'. Регресс на c_scattergun_blue
            ok, msg, vtf_names = self._run_build(
                base, panel_extra_textures={},
                blu_mode="upload", blu_image_path=str(blu_img), blu_is_team=False)
            self.assertTrue(ok, msg)
            self.assertIn("c_scattergun.vtf", vtf_names)
            self.assertNotIn("c_scattergun_blue.vtf", vtf_names)

    def test_missing_game_texture_surfaces_warning(self):
        # Игровая текстура не найдена -> сборка успешна, но в сообщении есть
        # предупреждение (иначе пользователь узнаёт о фиолете только в игре)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ok, msg = self._run_build(
                base, panel_extra_textures={}, red_not_found=True)[:2]
            self.assertTrue(ok, msg)
            self.assertIn("Warnings:", msg)            # en по умолчанию
            self.assertIn("c_scattergun", msg)         # имя проблемного материала

    # Снимки по веткам _build_model_mode_vpk (сетка под нарезку на шаги)

    VMT = b'"VertexLitGeneric"\r\n{\r\n}\r\n'
    VTF = b"VTF\x00marker"

    def test_snapshot_weapon_team_extras_maps(self):
        # Команда + доп. материал из $texturegroup + панельный + карта detail:
        # полное дерево мода, VMT побайтно
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            Image.new("RGB", (4, 4), color="green").save(base / "shell2.png")
            Image.new("RGB", (4, 4), color="blue").save(base / "shell.png")
            Image.new("RGB", (4, 4), color="white").save(base / "detail.png")
            (base / "blu.vtf").write_bytes(b"VTF\x00blu")
            tg = {"red_row": ["c_scattergun", "c_scattergun_shell2"],
                  "blu_row": ["c_scattergun_blue", "c_scattergun_shell2_blue"],
                  "blu_is_team": True, "main_texture": "c_scattergun",
                  "extra_materials": ["c_scattergun_shell2"],
                  "all_rows": [["c_scattergun", "c_scattergun_shell2"],
                               ["c_scattergun_blue", "c_scattergun_shell2_blue"]]}
            ok, msg, _ = self._run_build(
                base, {"c_scattergun_shell": str(base / "shell.png")}, tg=tg,
                extra_texture_callback=lambda *a: str(base / "shell2.png"),
                material_maps={"c_scattergun": {"detail": {"image": str(base / "detail.png")}}},
                blu_mode="upload", blu_image_path=str(base / "blu.vtf"))
        self.assertTrue(ok, msg)
        self.assertEqual(self.progress, [25, 40, 60, 80])
        d = "materials/models/weapons/c_scattergun/"
        detail_vmt = (b'"VertexLitGeneric"\r\n{\r\n'
                      b'\t"$detail" "models/weapons/c_scattergun/c_scattergun_detail"\n'
                      b'\t"$detailscale" "8"\n\t"$detailblendmode" "0"\n'
                      b'\t"$detailblendfactor" "1"\n}\r\n')
        self.assertEqual(self.tree, {
            d + "c_scattergun.vmt": detail_vmt,
            d + "c_scattergun.vtf": self.VTF,
            d + "c_scattergun_blue.vmt": detail_vmt,
            d + "c_scattergun_blue.vtf": self.VTF,
            d + "c_scattergun_detail.vtf": self.VTF,
            d + "c_scattergun_shell.vmt": self.VMT,
            d + "c_scattergun_shell.vtf": self.VTF,
            d + "c_scattergun_shell2.vmt": self.VMT,
            d + "c_scattergun_shell2.vtf": self.VTF,
            d + "c_scattergun_shell2_blue.vmt": self.VMT,
            d + "c_scattergun_shell2_blue.vtf": self.VTF,
        })

    def test_blue_waits_for_background_compression(self):
        # Красная жмётся в фоне, синяя берёт её нормаль только готовой
        import time

        def slow_vtf(png_path, output_dir, *a, **k):
            time.sleep(0.2)
            (Path(output_dir) / f"{Path(png_path).stem}.vtf").write_bytes(self.VTF)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            Image.new("RGB", (4, 4), color="blue").save(base / "blu.png")
            tg = {"red_row": ["c_scattergun"], "blu_row": ["c_scattergun_blue"],
                  "blu_is_team": True, "main_texture": "c_scattergun",
                  "extra_materials": [], "all_rows": [["c_scattergun"], ["c_scattergun_blue"]]}
            ok, msg, vtfs = self._run_build(
                base, tg=tg, extra_texture_callback=lambda *a: str(base / "blu.png"),
                vtf_options={"normal": True},
                extra_patches={
                    "src.services.texture_service.TextureService.create_vtf": {"side_effect": slow_vtf},
                    "src.services.texture_service.TextureService.write_normal_png": {}})
        self.assertTrue(ok, msg)
        self.assertEqual(vtfs, ["c_scattergun.vtf", "c_scattergun_blue.vtf",
                                "c_scattergun_blue_normal.vtf", "c_scattergun_normal.vtf"])

    def test_same_file_compressions_run_in_order(self):
        import threading
        import time
        from src.services.texture_build.vtf_jobs import VtfJobs
        log, lock = [], threading.Lock()

        def job(tag, delay):
            time.sleep(delay)
            with lock:
                log.append(tag)
        jobs = VtfJobs()
        jobs.submit(job, "first", 0.2, key="a.png")
        jobs.submit(job, "second", 0, key="a.png")
        jobs.finish()
        self.assertEqual(log, ["first", "second"])

    def test_background_compression_error_fails_build(self):
        def broken_vtf(*a, **k):
            raise RuntimeError("сжатие упало")
        with tempfile.TemporaryDirectory() as tmp:
            ok, msg, _ = self._run_build(Path(tmp), extra_patches={
                "src.services.texture_service.TextureService.create_vtf": {"side_effect": broken_vtf}})
        self.assertFalse(ok)
        self.assertIn("сжатие упало", msg)

    def test_snapshot_material_only_mirror_no_blu(self):
        # Часы шпиона: без BLU (одна текстура), зеркальный VMT по игровому
        # пути, модель в мод не кладётся
        P = "src.services.vpk_service."
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "blu.vtf").write_bytes(b"VTF\x00blu")
            tg = {"red_row": ["c_pocket_watch"], "blu_row": ["c_pocket_watch_blue"],
                  "blu_is_team": True, "main_texture": "c_pocket_watch",
                  "extra_materials": [],
                  "all_rows": [["c_pocket_watch"], ["c_pocket_watch_blue"]]}
            ok, msg, _ = self._run_build(
                base, mode="spy_c_pocket_watch", weapon_key="c_pocket_watch",
                cdmat="models/weapons/c_items",
                patched_cdmat="console/models/weapons/c_items", tg=tg,
                blu_mode="upload", blu_image_path=str(base / "blu.vtf"),
                extra_patches={P + "ModelService.copy_compiled_models_to_vpkroot": {}})
        self.assertTrue(ok, msg)
        self.assertEqual(self.mocks[P + "ModelService.copy_compiled_models_to_vpkroot"].call_count, 0)
        tree = {k: v for k, v in self.tree.items() if k.startswith("materials/")}
        self.assertEqual(tree, {
            "materials/console/models/weapons/c_items/c_pocket_watch.vmt": self.VMT,
            "materials/console/models/weapons/c_items/c_pocket_watch.vtf": self.VTF,
            "materials/models/weapons/c_items/c_pocket_watch.vmt": self.VMT,
        })
        # Циферблат не меняли - свой .res экрана не нужен: он вёл бы картинки
        # шкалы в мод, где их нет, и в игре они пропадали
        self.assertNotIn("scripts/screens/pda_spy_invis_pocket.res", self.tree)
        self.assertNotIn("info.vdf", self.tree)

    def test_snapshot_pocket_watch_hud_inserts(self):
        # Вставки циферблата по фиксированному пути: одна и та же картинка в
        # двух слотах конвертируется один раз, VMT рядом с VTF
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            Image.new("RGB", (4, 4), color="green").save(base / "a.png")
            Image.new("RGB", (4, 4), color="green").save(base / "b.png")
            tg = {"red_row": ["c_pocket_watch"], "blu_row": [], "blu_is_team": False,
                  "main_texture": "c_pocket_watch", "extra_materials": [],
                  "all_rows": [["c_pocket_watch"]]}
            ok, msg, _ = self._run_build(
                base, {"pocket_watch_fg": str(base / "a.png"),
                       "pocket_watch_bg": str(base / "b.png")},
                mode="spy_c_pocket_watch", weapon_key="c_pocket_watch",
                cdmat="models/weapons/c_items",
                patched_cdmat="console/models/weapons/c_items", tg=tg,
                extra_patches={"src.services.texture_service.TextureService.create_vtf":
                               {"side_effect": lambda png, out, *a, **k: (
                                   Path(out) / f"{Path(png).stem}.vtf").write_bytes(
                                       b"VTF\x00" + Path(png).stem.encode())}})
        self.assertTrue(ok, msg)
        d = "materials/vgui/replay/thumbnails/deadringer/"
        hud = {k: v for k, v in self.tree.items() if k.startswith(d)}

        def vmt(stem):
            return ('"UnlitGeneric"\n{\n\t"$basetexture" '
                    f'"vgui/replay/thumbnails/deadringer/{stem}"\n'
                    '\t"$translucent" "1"\n\t"$vertexalpha" "1"\n}\n').replace("\n", "\r\n").encode()
        self.assertEqual(hud, {
            d + "pocket_watch_fg.vtf": b"VTF\x00pocket_watch_fg",
            d + "pocket_watch_fg.vmt": vmt("pocket_watch_fg"),
            d + "pocket_watch_bg.vtf": b"VTF\x00pocket_watch_fg",
            d + "pocket_watch_bg.vmt": vmt("pocket_watch_bg"),
        })
        res = self.tree["scripts/screens/pda_spy_invis_pocket.res"].decode()
        self.assertIn('"fg_image"\t"replay/thumbnails/deadringer/pocket_watch_fg"', res)
        self.assertIn("info.vdf", self.tree)

    def test_snapshot_hands_mirror(self):
        P = "src.services.vpk_service."
        with tempfile.TemporaryDirectory() as tmp:
            tg = {"red_row": ["scout_hands", "scout_red"],
                  "blu_row": ["scout_hands", "scout_blue"],
                  "blu_is_team": True, "main_texture": "scout_hands",
                  "extra_materials": ["scout_red"],
                  "all_rows": [["scout_hands", "scout_red"], ["scout_hands", "scout_blue"]]}
            ok, msg, _ = self._run_build(
                Path(tmp), mode="scout_hands", weapon_key="c_scout_arms",
                cdmat="models/player/scout", patched_cdmat="console/models/player/scout",
                tg=tg, extra_patches={P + "ModelBuildService.extract_texturegroup_filename":
                                      {"return_value": "scout_hands"}})
        self.assertTrue(ok, msg)
        self.assertEqual(self.tree, {
            "materials/console/models/player/scout/scout_hands.vmt": self.VMT,
            "materials/console/models/player/scout/scout_hands.vtf": self.VTF,
            "materials/models/player/scout/scout_hands.vmt": self.VMT,
        })

    ENGI_QC = (
        '$modelname "weapons/c_models/c_engineer_arms.mdl"\n'
        '$body "arms" "c_engineer_arms_reference.smd"\n'
        '$cdmaterials "models\\\\player\\\\engineer"\n'
        '$texturegroup "skinfamilies"\n{\n'
        '\t{ "engineer_handl" "engineer_handr_red" "engineer_red" }\n'
        '\t{ "engineer_handl" "engineer_handr_blue" "engineer_blue" }\n}\n')
    ENGI_SMD = ('version 1\nnodes\n0 "root" -1\nend\nskeleton\ntime 0\n'
                '0 0 0 0 0 0 0\nend\ntriangles\n'
                + ''.join(f'{m}\n0 0 0 0 0 0 1 0 0\n0 0 0 0 0 0 1 0 0\n0 0 0 0 0 0 1 0 0\n'
                          for m in ("engineer_handl", "engineer_handr_red", "engineer_red"))
                + 'end\n')

    def test_snapshot_hands_shoulder_isolation_and_promo(self):
        # Изоляция плеч (engineer_red -> vm_engineer_red и синий вариант) и
        # промоушен нейтральной левой руки в командную: QC, SMD и дерево мода
        P = "src.services.vpk_service."
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            Image.new("RGB", (4, 4), color="green").save(base / "shoulder.png")
            Image.new("RGB", (4, 4), color="blue").save(base / "handl_blu.png")
            tg = {"red_row": ["engineer_handl", "engineer_handr_red", "engineer_red"],
                  "blu_row": ["engineer_handl", "engineer_handr_blue", "engineer_blue"],
                  "blu_is_team": True, "main_texture": "engineer_handl",
                  "extra_materials": ["engineer_handr_red", "engineer_red"],
                  "all_rows": [["engineer_handl", "engineer_handr_red", "engineer_red"],
                               ["engineer_handl", "engineer_handr_blue", "engineer_blue"]]}
            ok, msg, _ = self._run_build(
                base, {"engineer_red": str(base / "shoulder.png")},
                mode="engineer_hands", weapon_key="c_engineer_arms",
                cdmat="models/player/engineer", patched_cdmat="console/models/player/engineer",
                tg=tg, isolate_shoulders=True,
                panel_blu_textures={"engineer_handl": str(base / "handl_blu.png")},
                decompiled={"c_engineer_arms.qc": self.ENGI_QC,
                            "c_engineer_arms_reference.smd": self.ENGI_SMD},
                extra_patches={P + "ModelBuildService.extract_texturegroup_filename":
                               {"return_value": "engineer_handl"}})
        self.assertTrue(ok, msg)
        c, m = "materials/console/models/player/engineer/", "materials/models/player/engineer/"
        self.assertEqual(self.tree, {
            c + "engineer_handl.vmt": self.VMT, c + "engineer_handl.vtf": self.VTF,
            c + "engineer_handl_blue.vmt": self.VMT, c + "engineer_handl_blue.vtf": self.VTF,
            c + "engineer_red.vmt": self.VMT, c + "engineer_red.vtf": self.VTF,
            c + "vm_engineer_red.vmt": self.VMT, c + "vm_engineer_red.vtf": self.VTF,
            m + "engineer_handl.vmt": self.VMT, m + "engineer_handl_blue.vmt": self.VMT,
            m + "vm_engineer_red.vmt": self.VMT,
        })
        self.assertEqual(self.decompiled["c_engineer_arms.qc"], (
            '$modelname "weapons/c_models/c_engineer_arms.mdl"\n\n'
            '$texturegroup "skinfamilies"\n{\n'
            '\t{ "engineer_handl" "engineer_handr_red" "vm_engineer_red" }\n'
            '\t{ "engineer_handl_blue" "engineer_handr_blue" "vm_engineer_blue" }\n}\n\n'
            '$body "arms" "c_engineer_arms_reference.smd"\n'
            '$cdmaterials "models\\\\player\\\\engineer"\n'))
        self.assertEqual(self.decompiled["c_engineer_arms_reference.smd"],
                         self.ENGI_SMD.replace("engineer_red\n", "vm_engineer_red\n"))

    def test_snapshot_custom_model_styles_and_qc_text(self):
        # Своя модель: имена от материалов SMD, свой $texturegroup стилей,
        # правленый человеком QC с синхронизированной группой
        PL = "src.services.vpk_model_pipeline.VpkModelPipeline."
        smd = ('version 1\nnodes\n0 "root" -1\nend\nskeleton\ntime 0\n'
               '0 0 0 0 0 0 0\nend\ntriangles\nMyMat\n'
               + '0 0 0 0 0 0 1 0 0\n' * 3 + 'end\n')
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "user.smd").write_text(smd, encoding="utf-8")
            ok, msg, _ = self._run_build(
                base, {"MyMat": str(base / "img.png")},
                replace_model_enabled=True, replace_model_path=str(base / "user.smd"),
                replace_keep_materials=True,
                custom_qc_text='$modelname "weapons/c_x.mdl"\n$body "b" "c_scattergun_reference.smd"\n',
                skin_build_data={"mesh_materials": ["mymat"],
                                 "tg_overrides": {1: {"mymat": "mymat_bloody"}},
                                 "variant_files": {}},
                decompiled={"c_scattergun_reference.smd": smd, "c_scattergun.qc": "// qc"},
                extra_patches={PL + "_resolve_replace_model_smd": {"return_value": str(base / "user.smd")},
                               PL + "_apply_model_replacement": {}})
        self.assertTrue(ok, msg)
        d = "materials/models/weapons/c_scattergun/"
        self.assertEqual(self.tree, {d + "MyMat.vmt": self.VMT, d + "MyMat.vtf": self.VTF})
        self.assertEqual(self.decompiled["c_scattergun_reference.smd"], smd)
        self.assertEqual(self.decompiled["c_scattergun.qc"], (
            '$modelname "weapons/c_x.mdl"\n\n'
            '$texturegroup "skinfamilies"\n{\n\t{ "mymat" }\n\t{ "mymat_bloody" }\n}\n\n'
            '$body "b" "c_scattergun_reference.smd"\n'
            '$definebone "root" "" 0.000000 0.000000 0.000000 0.000000 0.000000 0.000000'
            ' 0 0 0 0 0 0\n'))

    def test_snapshot_blu_columns_and_extra_answers(self):
        # Все ответы на вопросы доп. материалов и столбцов BLU: своя картинка,
        # «из игры» (есть и нет в игре), «скопировать главную», пропуск;
        # общий столбец, вариант без RED-пары, нормаль у синего
        from src.shared.constants import EXTRA_TEX_USE_GAME_ORIGINAL as GAME, EXTRA_TEX_USE_MAIN as MAIN
        orig = "src.services.texture_build.game_source.get_original_vtf_bytes"
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            Image.new("RGB", (4, 4), color="green").save(base / "own.png")
            own = str(base / "own.png")
            answers = {"c_scattergun_shell": own, "c_scattergun_scope": GAME, "c_scattergun_strap": MAIN,
                       "c_scattergun_skip": None, "c_scattergun_blue": GAME, "c_scattergun_shell_blue": own,
                       "c_scattergun_scope_blue": MAIN, "c_lens": own, "c_scattergun_more": MAIN,
                       "c_scattergun_more2": GAME}
            red = ["c_scattergun", "c_scattergun_shell", "c_scattergun_scope", "c_scattergun_strap", "c_scattergun_skip", "c_lens"]
            blu = ["c_scattergun_blue", "c_scattergun_shell_blue", "c_scattergun_scope_blue", "c_scattergun_strap_blue",
                   "c_scattergun_skip_blue", "c_lens", "c_scattergun_more", "c_scattergun_more2"]
            tg = {"red_row": red, "blu_row": blu, "blu_is_team": True, "main_texture": "c_scattergun",
                  "extra_materials": red[1:5], "all_rows": [red, blu]}
            ok, msg, _ = self._run_build(
                base, tg=tg,
                extra_texture_callback=lambda name, *a: answers.get(name),
                vtf_options={"normal": True},
                extra_patches={orig: {"side_effect": lambda name, *a, **k:
                                      b"VTF\x00game" if name == "c_scattergun_scope" else None},
                               "src.services.texture_service.TextureService.render_image_to_vtf":
                               {"side_effect": lambda img, **k: (
                                   Path(k["out_vtf_path"]).write_bytes(self.VTF), (None, True))[1]}})
        self.assertTrue(ok, msg)
        d = "materials/models/weapons/c_scattergun/"
        game = b"VTF\x00game"

        def vmt(normal=None):
            bump = (f'\t"$bumpmap" "models/weapons/c_scattergun/{normal}"\n'.encode()
                    if normal else b"")
            return b'"VertexLitGeneric"\r\n{\r\n' + bump + b'}\r\n'
        main = vmt("c_scattergun_normal")
        expected = {
            "c_lens": (main, self.VTF), "c_scattergun": (main, self.VTF),
            "c_scattergun_blue": (vmt("c_scattergun_blue_normal"), self.VTF),
            "c_scattergun_more": (main, self.VTF), "c_scattergun_more2": (main, self.VTF),
            "c_scattergun_scope": (vmt(), game),
            "c_scattergun_scope_blue": (vmt("c_scattergun_scope_blue_normal"), game),
            "c_scattergun_shell": (main, self.VTF),
            "c_scattergun_shell_blue": (vmt("c_scattergun_shell_blue_normal"), self.VTF),
            "c_scattergun_strap": (main, self.VTF),
        }
        self.assertEqual(self.tree, {
            f"{d}{name}.{ext}": data for name, pair in expected.items()
            for ext, data in zip(("vmt", "vtf"), pair)})

    def test_snapshot_hat_extra_classes_and_styles(self):
        P = "src.services.vpk_service."
        cls, sty = (P + "VpkModelPipeline._build_extra_class_hat_models",
                    P + "VpkModelPipeline._build_extra_style_models")
        hat = "models/player/items/all_class/hat_scout.mdl"
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ok, msg, _ = self._run_build(
                base, mode="hat", weapon_key="hat_scout",
                cdmat="models/player/items/all_class",
                patched_cdmat="console/models/player/items/all_class",
                hat_mdl_path=hat,
                hat_class_models={"scout": hat,
                                  "heavy": "models/player/items/all_class/hat_heavy.mdl"},
                hat_style_builds=[{"style": 1}],
                extra_patches={cls: {}, sty: {}})
            qc = str(base / "ctx" / "decompile" / "hat_scout.qc")
            img = str(base / "img.png")
        self.assertTrue(ok, msg)
        self.assertEqual(self.tree, {
            "materials/console/models/player/items/all_class/hat_scout.vmt": self.VMT,
            "materials/console/models/player/items/all_class/hat_scout.vtf": self.VTF,
        })
        c = self.mocks[cls].call_args
        self.assertEqual(c.args[1:9], (
            hat, hat, None, False, "tf2_misc_dir.vpk", "studiomdl.exe",
            str(base), "en"))
        self.assertEqual(c.kwargs, {
            "target_mdl_paths": ["models/player/items/all_class/hat_heavy.mdl"],
            "bypass_prefix": "console", "part_specs": None,
            "part_source_qc": qc, "part_names": {}})
        s = self.mocks[sty].call_args
        self.assertEqual(s.args[1], [{"style": 1}])
        self.assertEqual(s.args[7:11], ((4, 4), "DXT1", [], {}))
        self.assertEqual(s.kwargs, {
            "bypass_prefix": "console",
            "written_textures": {"console/models/player/items/all_class/hat_scout": img}})

    def test_snapshot_decor_and_parts_plumbing(self):
        P = "src.services.vpk_service."
        dec, apply_, sec = ("src.services.decor_build.build_decor_models",
                            "src.services.part_materials.apply_to_model",
                            P + "VpkTextureBuilder._build_secondary_textures")
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ok, msg, _ = self._run_build(
                base, decor_builds=[{"model": "c_minigun_xmas"}],
                part_materials=[{"name": "p1"}],
                extra_patches={dec: {}, sec: {},
                               apply_: {"return_value": {"p1": "c_scattergun_p1"}}})
        self.assertTrue(ok, msg)
        d = self.mocks[dec].call_args
        self.assertEqual(d.args[1], [{"model": "c_minigun_xmas"}])
        self.assertEqual({k: v for k, v in d.kwargs.items() if k != "emit_sub"}, {
            "misc_vpk": "tf2_misc_dir.vpk", "textures_vpk": "tf2_textures_dir.vpk",
            "studiomdl_exe": "studiomdl.exe", "tf_dir": str(base), "size": (4, 4),
            "format_type": "DXT1", "flags": [], "vtf_options": {},
            "bypass_prefix": "console", "language": "en"})
        self.assertEqual(self.mocks[apply_].call_args.args[1], [{"name": "p1"}])
        self.assertEqual(self.mocks[sec].call_args.kwargs, {
            "part_variants": {"p1": "c_scattergun_p1"}, "part_specs": [{"name": "p1"}],
            "blu_of": None, "strip_paints": False})

    def test_snapshot_attachment_only_moves_cdmaterials(self):
        P = "src.services.vpk_service."
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ok, msg, _ = self._run_build(base, extra_patches={
                P + "VPKService._is_attachment_only": {"return_value": True},
                "src.services.decor_build._set_cdmaterials": {}})
            qc = str(base / "ctx" / "decompile" / "c_scattergun.qc")
        self.assertTrue(ok, msg)
        self.assertIn("Warnings:", msg)
        from src.services.decor_build import DECOR_MATERIALS_ROOT
        self.assertEqual(
            self.mocks["src.services.decor_build._set_cdmaterials"].call_args.args,
            (qc, DECOR_MATERIALS_ROOT + "\\c_scattergun"))

    def test_snapshot_errors(self):
        P = "src.services.vpk_service."
        cases = [
            ({"cdmat": ""}, "Failed to extract path from $cdmaterials in QC file: {qc}"),
            ({"patched_cdmat": ""},
             "Failed to extract path from $cdmaterials after patching in QC file: {qc}"),
            ({"extra_patches": {P + "ModelBuildService.extract_texturegroup_filename":
                                {"return_value": ""}}},
             "Failed to extract filename from $texturegroup in QC file: {qc}"),
            ({"extra_patches": {P + "ModelBuildService.compile":
                                {"side_effect": RuntimeError("boom")}}},
             "Error while working with model: boom"),
            ({"texture_mismatch_callback": lambda m: False,
              "extra_patches": {P + "VPKService._ready_model_texture_mismatch":
                                {"return_value": "differs"}}},
             "Build cancelled: texture mismatch in SMD file."),
        ]
        for kw, expected in cases:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                ok, msg, _ = self._run_build(base, **kw)
                qc = str(base / "ctx" / "decompile" / "c_scattergun.qc")
                self.assertEqual((ok, msg), (False, expected.format(qc=qc)))

    def test_snapshot_cancel_points(self):
        # Отмена проверяется перед 25/40/60/80 %: снимок прогресса до отмены
        for n, progress in enumerate([[], [25], [25, 40], [25, 40, 60]]):
            calls = []

            def cancel(n=n):
                calls.append(1)
                return len(calls) > n
            with self.subTest(n=n), tempfile.TemporaryDirectory() as tmp:
                ok, msg, _ = self._run_build(Path(tmp), cancel_callback=cancel)
                self.assertEqual((ok, msg), (False, "Build cancelled by user"))
                self.assertEqual(self.progress, progress)

    def test_snapshot_spy_masks(self):
        from src.data.player_characters import SPY_MASK_MODE_KEY
        from src.shared.constants import EXTRA_TEX_USE_GAME_ORIGINAL
        orig = "src.services.texture_build.game_source.get_original_vtf_bytes"
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            Image.new("RGB", (4, 4), color="red").save(base / "scout.png")
            (base / "pyro.vtf").write_bytes(b"VTF\x00pyro")
            answers = {"mask_scout": str(base / "scout.png"),
                       "mask_soldier": EXTRA_TEX_USE_GAME_ORIGINAL,
                       "mask_pyro": str(base / "pyro.vtf")}
            ok, msg, _ = self._run_build(
                base, mode=SPY_MASK_MODE_KEY, weapon_key="spy",
                extra_texture_callback=lambda name, wk: answers.get(name),
                extra_patches={orig: {"return_value": b"VTF\x00game"}})
            self.assertEqual((ok, msg), (True, str(base / "out.vpk")))
        vmt = lambda n: ('"VertexLitGeneric"\n{\n\t"$basetexture" '  # noqa: E731
                         f'"models/player/spy/{n}"\n}}\n').replace("\n", "\r\n").encode()
        d = "materials/models/player/spy/"
        self.assertEqual(self.tree, {
            d + "mask_pyro.vmt": vmt("mask_pyro"), d + "mask_pyro.vtf": b"VTF\x00pyro",
            d + "mask_scout.vmt": vmt("mask_scout"), d + "mask_scout.vtf": self.VTF,
            d + "mask_soldier.vmt": vmt("mask_soldier"), d + "mask_soldier.vtf": b"VTF\x00game",
        })

        with tempfile.TemporaryDirectory() as tmp:
            ok, msg, _ = self._run_build(Path(tmp), mode=SPY_MASK_MODE_KEY, weapon_key="spy",
                                         extra_texture_callback=lambda *a: None)
            self.assertEqual((ok, msg), (False, TRANSLATIONS["en"].get(
                'error_no_textures', 'No mask textures were provided.')))


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
