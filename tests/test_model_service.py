import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.services.model_service import ModelService
from src.services.build_context import BuildContext


class ModelServiceTests(unittest.TestCase):
    def test_copy_compiled_models_to_vpkroot(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ctx = BuildContext("id", "m", "w", base / "ctx")
            ctx.create_directories()
            (ctx.compile_dir / "c_test.mdl").write_text("mdl", encoding="utf-8")
            (ctx.compile_dir / "c_test.vvd").write_text("vvd", encoding="utf-8")
            with patch("src.services.model_service.ModelBuildService.extract_modelname_path", return_value="models/weapons/c_models/c_test/c_test.mdl"):
                ModelService.copy_compiled_models_to_vpkroot(ctx, "qc")
            target = ctx.vpkroot_dir / "models" / "models" / "weapons" / "c_models" / "c_test" / "c_test.mdl"
            self.assertTrue(target.exists())

    def test_generate_uv_layout_missing_smd(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ctx = BuildContext("id", "m", "w", base / "ctx")
            ctx.create_directories()
            with patch("src.services.model_service.SMDService.find_reference_smd", return_value=None):
                ModelService.generate_uv_layout(ctx, "weapon", (4, 4), export_folder=str(base))

    def test_generate_uv_layout_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ctx = BuildContext("id", "m", "w", base / "ctx")
            ctx.create_directories()
            smd_path = base / "weapon_reference.smd"
            smd_path.write_text("x", encoding="utf-8")
            with patch("src.services.model_service.SMDService.find_reference_smd", return_value=str(smd_path)):
                with patch("src.services.uv_layout_service.UVLayoutService.generate_uv_layout_from_smd", return_value=True) as generate:
                    ModelService.generate_uv_layout(ctx, "weapon", (4, 4), export_folder=str(base))
            generate.assert_called()


if __name__ == "__main__":
    unittest.main()
