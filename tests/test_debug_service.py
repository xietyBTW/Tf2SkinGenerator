import os
import tempfile
import unittest
from pathlib import Path

from src.services.debug_service import DebugService


class Ctx:
    def __init__(self, base: Path):
        self.extract_dir = str(base / "extract")
        self.debug_stage1_extracted_dir = str(base / "debug" / "01_extracted")
        self.debug_stage2_decompiled_dir = str(base / "debug" / "02_decompiled")
        self.debug_stage3_patched_dir = str(base / "debug" / "03_patched")
        self.debug_stage4_compiled_dir = str(base / "debug" / "04_compiled")


class DebugServiceTests(unittest.TestCase):
    def test_save_extracted_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            extract_dir = base / "extract"
            debug_dir = base / "debug" / "01_extracted"
            extract_dir.mkdir(parents=True, exist_ok=True)
            debug_dir.mkdir(parents=True, exist_ok=True)
            file_path = extract_dir / "file.txt"
            file_path.write_text("x", encoding="utf-8")
            ctx = Ctx(base)
            DebugService.save_extracted_stage(ctx, [str(file_path)])
            copied = debug_dir / "file.txt"
            self.assertTrue(copied.exists())

    def test_save_extracted_stage_missing_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ctx = Ctx(base)
            DebugService.save_extracted_stage(ctx, [str(base / "missing.txt")])
            self.assertFalse(os.path.exists(ctx.debug_stage1_extracted_dir))

    def test_save_decompiled_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            decompile_dir = base / "decompile"
            debug_dir = base / "debug" / "02_decompiled"
            (decompile_dir / "sub").mkdir(parents=True, exist_ok=True)
            debug_dir.mkdir(parents=True, exist_ok=True)
            src = decompile_dir / "sub" / "file.qc"
            src.write_text("x", encoding="utf-8")
            ctx = Ctx(base)
            DebugService.save_decompiled_stage(ctx, str(decompile_dir))
            self.assertTrue((debug_dir / "sub" / "file.qc").exists())

    def test_save_patched_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            decompile_dir = base / "decompile"
            debug_dir = base / "debug" / "03_patched"
            (decompile_dir / "sub").mkdir(parents=True, exist_ok=True)
            debug_dir.mkdir(parents=True, exist_ok=True)
            src = decompile_dir / "sub" / "file.qc"
            src.write_text("x", encoding="utf-8")
            ctx = Ctx(base)
            DebugService.save_patched_stage(ctx, str(decompile_dir))
            self.assertTrue((debug_dir / "sub" / "file.qc").exists())

    def test_save_compiled_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            compile_dir = base / "compile"
            debug_dir = base / "debug" / "04_compiled"
            (compile_dir / "sub").mkdir(parents=True, exist_ok=True)
            debug_dir.mkdir(parents=True, exist_ok=True)
            src = compile_dir / "sub" / "file.mdl"
            src.write_text("x", encoding="utf-8")
            ctx = Ctx(base)
            DebugService.save_compiled_stage(ctx, str(compile_dir))
            self.assertTrue((debug_dir / "sub" / "file.mdl").exists())


if __name__ == "__main__":
    unittest.main()
