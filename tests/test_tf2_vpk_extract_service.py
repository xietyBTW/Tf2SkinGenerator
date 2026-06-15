import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import src.services.tf2_vpk_extract_service as tf2_module
from src.services.tf2_vpk_extract_service import TF2VPKExtractService


class FakeEntry:
    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data


class FakeVPK:
    def __init__(self, files):
        self._files = files

    def __contains__(self, key):
        return key in self._files

    def __getitem__(self, key):
        return FakeEntry(self._files[key])

    def close(self):
        return None


class TF2VpkExtractServiceTests(unittest.TestCase):
    def test_check_mdl_exists_not_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vpk_path = base / "tf2_misc_dir.vpk"
            vpk_path.write_bytes(b"data")
            with patch.object(tf2_module, "VPK_AVAILABLE", False):
                self.assertFalse(TF2VPKExtractService.check_mdl_exists(str(vpk_path), "models/test.mdl"))

    def test_check_mdl_exists_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vpk_path = base / "tf2_misc_dir.vpk"
            vpk_path.write_bytes(b"data")
            files = {"models/test.mdl": b"mdl"}
            with patch.object(tf2_module, "VPK_AVAILABLE", True):
                with patch.object(tf2_module.vpk, "open", return_value=FakeVPK(files)):
                    self.assertTrue(TF2VPKExtractService.check_mdl_exists(str(vpk_path), "models/test.mdl"))

    def test_extract_file_set_missing_mdl_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vpk_path = base / "tf2_misc_dir.vpk"
            vpk_path.write_bytes(b"data")
            files = {}
            with patch.object(tf2_module, "VPK_AVAILABLE", True):
                with patch.object(tf2_module.vpk, "open", return_value=FakeVPK(files)):
                    with self.assertRaises(RuntimeError):
                        TF2VPKExtractService.extract_file_set(str(vpk_path), "models/weapons/c_models/c_test.mdl", str(base))

    def test_extract_file_set_sanitize_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vpk_path = base / "tf2_misc_dir.vpk"
            vpk_path.write_bytes(b"data")
            files = {"../escape.mdl": b"mdl"}
            with patch.object(tf2_module, "VPK_AVAILABLE", True):
                with patch.object(tf2_module.vpk, "open", return_value=FakeVPK(files)):
                    with self.assertRaises(RuntimeError):
                        TF2VPKExtractService.extract_file_set(str(vpk_path), "../escape.mdl", str(base))

    def test_extract_file_set_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vpk_path = base / "tf2_misc_dir.vpk"
            vpk_path.write_bytes(b"data")
            mdl_rel_path = "models/weapons/c_models/c_test.mdl"
            files = {
                "models/weapons/c_models/c_test.mdl": b"mdl",
                "models/weapons/c_models/c_test.dx90.vtx": b"vtx",
                "models/weapons/c_models/c_test.vvd": b"vvd",
                "models/weapons/c_models/c_test.sw.vtx": b"vtx",
                "models/weapons/c_models/c_test.dx80.vtx": b"vtx",
                "models/weapons/c_models/c_test.phy": b"phy",
            }
            with patch.object(tf2_module, "VPK_AVAILABLE", True):
                with patch.object(tf2_module.vpk, "open", return_value=FakeVPK(files)):
                    out_dir = base / "out"
                    extracted = TF2VPKExtractService.extract_file_set(str(vpk_path), mdl_rel_path, str(out_dir))
                    for path in extracted:
                        self.assertTrue(Path(path).exists())

    def test_extract_vmt_file_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vpk_path = base / "tf2_misc_dir.vpk"
            vpk_path.write_bytes(b"data")
            rel_path = "materials/models/weapons/c_models/c_test/c_test.vmt"
            files = {rel_path: b"vmt"}
            with patch.object(tf2_module, "VPK_AVAILABLE", True):
                with patch.object(tf2_module.vpk, "open", return_value=FakeVPK(files)):
                    out_dir = base / "out"
                    result = TF2VPKExtractService.extract_vmt_file(str(vpk_path), "models/weapons/c_models/c_test", "c_test", str(out_dir))
                    self.assertTrue(Path(result).exists())

    def test_extract_vmt_file_no_materials_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vpk_path = base / "tf2_misc_dir.vpk"
            vpk_path.write_bytes(b"data")
            rel_path = "materials/models/weapons/c_models/c_test/c_test.vmt"
            files = {rel_path: b"vmt"}
            with patch.object(tf2_module, "VPK_AVAILABLE", True):
                with patch.object(tf2_module.vpk, "open", return_value=FakeVPK(files)):
                    out_dir = base / "out"
                    result = TF2VPKExtractService.extract_vmt_file(str(vpk_path), "models/weapons/c_models/c_test", "c_test", str(out_dir))
                    self.assertTrue(Path(result).exists())

    def test_extract_vmt_file_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vpk_path = base / "tf2_misc_dir.vpk"
            vpk_path.write_bytes(b"data")
            files = {}
            with patch.object(tf2_module, "VPK_AVAILABLE", True):
                with patch.object(tf2_module.vpk, "open", return_value=FakeVPK(files)):
                    result = TF2VPKExtractService.extract_vmt_file(str(vpk_path), "materials/models", "c_test", str(base))
                    self.assertIsNone(result)

    def test_convert_vtf_to_image_missing_vtf2img(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vtf_path = base / "c_test.vtf"
            vtf_path.write_bytes(b"vtf")
            with patch.dict(sys.modules, {"vtf2img": None}):
                result = TF2VPKExtractService._convert_vtf_to_image(str(vtf_path), str(base), "PNG")
                self.assertIsNone(result)

    def test_convert_vtf_to_image_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vtf_path = base / "c_test.vtf"
            vtf_path.write_bytes(b"vtf")

            class FakeParser:
                def __init__(self, path):
                    self.path = path

                def get_image(self):
                    from PIL import Image
                    return Image.new("RGBA", (4, 4), (255, 0, 0, 128))

            fake_module = types.SimpleNamespace(Parser=FakeParser)
            with patch.dict(sys.modules, {"vtf2img": fake_module}):
                result = TF2VPKExtractService._convert_vtf_to_image(str(vtf_path), str(base), "PNG")
                self.assertTrue(Path(result).exists())


if __name__ == "__main__":
    unittest.main()
