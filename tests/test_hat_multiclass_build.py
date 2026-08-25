"""
Мультиклассовая шапка: модель собирается для КАЖДОГО выбранного класса.

У all-class шапки каждый класс — отдельный файл модели, и при компиляции путь
к материалам переписывается на папку обхода sv_pure. Класс, чью модель не
пересобрали, продолжает грузить оригинальную текстуру игры — мод «работает
только на одном классе». Раньше остальные классы собирались ТОЛЬКО когда
пользователь менял ещё и геометрию.

Внешние инструменты (Crowbar/studiomdl/VTFCmd/упаковка) замоканы — проверяется
состав работы, а не результат компиляции.
"""

import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from src.services.build_context import BuildContext
from src.services.vpk_service import VPKService

CLASSES = {
    "scout": "models/player/items/all_class/hat_scout.mdl",
    "soldier": "models/player/items/all_class/hat_soldier.mdl",
    "heavy": "models/player/items/all_class/hat_heavy.mdl",
}


class MulticlassHatBuildTests(unittest.TestCase):
    def _build(self, *, classes=None, replace_model=False):
        """Гоняет build_vpk для шапки. → (ok, сколько моделей скомпилировано)."""
        from PIL import Image

        base = Path(tempfile.mkdtemp())
        img = base / "img.png"
        Image.new("RGB", (8, 8), color="red").save(img)
        (base / "src.vmt").write_text('"VertexLitGeneric"\n{\n}\n', encoding="utf-8")
        smd = base / "user.smd"
        smd.write_text("version 1\n", encoding="utf-8")

        ctx = BuildContext("id", "hat", "hat_scout", base / "ctx")
        ctx.create_directories()
        ctx.decompile_dir.mkdir(parents=True, exist_ok=True)
        qc = ctx.decompile_dir / "hat_scout.qc"
        qc.write_text("// qc", encoding="utf-8")

        compiled = []
        P = "src.services.vpk_service."
        MP = "src.services.vpk_model_pipeline."
        with ExitStack() as es:
            m = es.enter_context
            m(patch(P + "BuildContext.create", return_value=ctx))
            m(patch(P + "TF2Paths.check_crowbar", return_value=(True, "")))
            m(patch(P + "TF2Paths.resolve",
                    return_value=("studiomdl.exe", "tf2_misc_dir.vpk", str(base))))
            m(patch(P + "TF2Paths.resolve_textures_vpk", return_value="tf2_textures_dir.vpk"))
            m(patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService."
                    "check_mdl_exists", return_value=True))
            m(patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService."
                    "extract_file_set", return_value=[str(base / "hat.mdl")]))
            m(patch("src.services.tf2_vpk_extract_service.TF2VPKExtractService."
                    "extract_vmt_file", return_value=str(base / "src.vmt")))
            m(patch(MP + "get_cached_decompile", return_value=None))
            m(patch(MP + "save_to_cache"))
            m(patch(P + "ModelBuildService.decompile", return_value=str(qc)))
            m(patch(MP + "ModelBuildService.decompile", return_value=str(qc)))
            m(patch(P + "ModelBuildService.extract_cdmaterials_path_from_qc",
                    return_value="models/player/items/all_class"))
            m(patch(P + "ModelBuildService.extract_all_cdmaterials_paths_from_qc",
                    return_value=["models/player/items/all_class"]))
            m(patch(P + "ModelBuildService.extract_texturegroup_filename",
                    return_value="hat"))
            m(patch(P + "ModelBuildService.extract_texturegroup_structure",
                    return_value={"red_row": ["hat"], "blu_row": [],
                                  "blu_is_team": False, "main_texture": "hat",
                                  "extra_materials": [], "all_rows": [["hat"]]}))
            m(patch(P + "ModelBuildService.patch_qc_file"))
            m(patch(P + "ModelBuildService.remove_lod_files"))
            m(patch(P + "ModelBuildService.compile",
                    side_effect=lambda q, *a, **k: compiled.append(str(q))))
            m(patch(MP + "ModelBuildService.compile",
                    side_effect=lambda q, *a, **k: compiled.append(str(q))))
            m(patch("src.services.vmt_service.VMTService.update_vmt_basetexture_path"))
            m(patch("src.services.vmt_service.VMTService.create_vmt_template_from_cdmaterials"))
            m(patch(P + "ModelService.copy_compiled_models_to_vpkroot"))
            m(patch(MP + "ModelService.copy_compiled_models_to_vpkroot"))
            m(patch(MP + "SMDService.replace_model_sections"))
            m(patch(MP + "VpkModelPipeline._find_decompiled_reference_smd",
                    return_value=str(smd)))
            m(patch(P + "PackagingService.create_vpk_file",
                    return_value=str(base / "out.vpk")))
            m(patch(P + "TextureService.create_vtf",
                    side_effect=lambda png, out, *a, **k:
                        (Path(out) / f"{Path(png).stem}.vtf").write_bytes(b"VTF")))
            m(patch(P + "TextureService.process_image",
                    side_effect=lambda i, o, s: Path(o).write_bytes(b"png")))

            ok, msg = VPKService.build_vpk(
                image_path=str(img),
                mode="hat",
                filename="out.vpk",
                tf2_root_dir=str(base),
                export_folder=str(base / "export"),
                size=(512, 512),
                format_type="DXT5",
                flags=[],
                language="ru",
                hat_mdl_path=CLASSES["scout"],
                hat_class_models=dict(classes if classes is not None else CLASSES),
                replace_model_enabled=replace_model,
                replace_model_path=str(smd) if replace_model else None,
            )
        return ok, len(compiled), msg

    def test_texture_only_build_covers_every_class(self):
        ok, compiled, msg = self._build()
        self.assertTrue(ok, msg)
        self.assertEqual(compiled, len(CLASSES),
                         "каждый выбранный класс — своя модель в моде")

    def test_model_replacement_still_covers_every_class(self):
        ok, compiled, msg = self._build(replace_model=True)
        self.assertTrue(ok, msg)
        self.assertEqual(compiled, len(CLASSES))

    def test_single_class_hat_builds_one_model(self):
        """Обычная шапка одного класса лишних компиляций не получает."""
        ok, compiled, msg = self._build(classes={"scout": CLASSES["scout"]})
        self.assertTrue(ok, msg)
        self.assertEqual(compiled, 1)


if __name__ == "__main__":
    unittest.main()
