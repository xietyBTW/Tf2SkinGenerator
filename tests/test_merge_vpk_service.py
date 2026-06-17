import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.services.merge_vpk_service import MergeVPKService
from src.shared.exceptions import VPKCreationError


class FakeEntry:
    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data


class FakeVPK:
    def __init__(self, files):
        self._files = files

    def __iter__(self):
        return iter(self._files.keys())

    def __getitem__(self, key):
        return FakeEntry(self._files[key])


class MergeVpkServiceTests(unittest.TestCase):
    def test_extract_weapon_name(self):
        self.assertEqual(MergeVPKService._extract_weapon_name("models/weapons/c_models/c_test/c_test.mdl"), "c_test")
        self.assertEqual(MergeVPKService._extract_weapon_name("models/weapons/v_models/v_test.mdl"), "v_test")
        self.assertIsNone(MergeVPKService._extract_weapon_name("materials/models/weapons/c_models/c_test.vtf"))
    
    def test_check_duplicate_weapons(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vpk_a = base / "a.vpk"
            vpk_b = base / "b.vpk"
            vpk_a.write_bytes(b"data")
            vpk_b.write_bytes(b"data")
            files_a = {"models/weapons/c_models/c_test/c_test.mdl": b"mdl"}
            files_b = {"models/workshop_partner/weapons/c_models/c_test.mdl": b"mdl"}
            with patch("src.services.merge_vpk_service.VPK_AVAILABLE", True):
                with patch("src.services.merge_vpk_service.vpk.open", side_effect=[FakeVPK(files_a), FakeVPK(files_b)]):
                    duplicates = MergeVPKService.check_duplicate_weapons([vpk_a, vpk_b])
            self.assertIn("c_test", duplicates)
            self.assertEqual(len(duplicates["c_test"]), 2)
    def test_merge_vpk_files_library_missing(self):
        with patch("src.services.merge_vpk_service.VPK_AVAILABLE", False):
            success, message = MergeVPKService.merge_vpk_files([], "out.vpk")
        self.assertFalse(success)
        self.assertTrue(message)

    def test_merge_vpk_files_no_files(self):
        with patch("src.services.merge_vpk_service.VPK_AVAILABLE", True):
            success, message = MergeVPKService.merge_vpk_files([], "out.vpk")
        self.assertFalse(success)
        self.assertTrue(message)

    def test_merge_vpk_files_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vpk_path = base / "missing.vpk"
            with patch("src.services.merge_vpk_service.VPK_AVAILABLE", True):
                success, message = MergeVPKService.merge_vpk_files([vpk_path], "out.vpk")
            self.assertFalse(success)
            self.assertIn("missing", message)

    def test_merge_vpk_files_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vpk_path = base / "a.vpk"
            vpk_path.write_bytes(b"data")
            fake_files = {"models/a.mdl": b"mdl"}
            with patch("src.services.merge_vpk_service.VPK_AVAILABLE", True):
                with patch("src.services.merge_vpk_service.vpk.open", return_value=FakeVPK(fake_files)):
                    with patch("src.services.merge_vpk_service.MergeVPKService._create_vpk_from_directory", return_value=str(base / "out.vpk")):
                        success, message = MergeVPKService.merge_vpk_files([vpk_path], "out.vpk", export_folder=str(base))
                        self.assertTrue(success)
                        self.assertIn("out.vpk", message)

    def test_merge_directory_renames_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            target = base / "target"
            (source / "folder").mkdir(parents=True)
            (target / "folder").mkdir(parents=True)
            (source / "folder" / "file.txt").write_text("a", encoding="utf-8")
            (target / "folder" / "file.txt").write_text("b", encoding="utf-8")
            MergeVPKService._merge_directory(source, target)
            files = list((target / "folder").iterdir())
            self.assertEqual(len(files), 2)
    
    def test_merge_vpk_files_cancel(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vpk_path = base / "a.vpk"
            vpk_path.write_bytes(b"data")
            fake_files = {"models/a.mdl": b"mdl"}
            with patch("src.services.merge_vpk_service.vpk.open", return_value=FakeVPK(fake_files)):
                success, message = MergeVPKService.merge_vpk_files(
                    [vpk_path],
                    "out.vpk",
                    export_folder=str(base),
                    should_cancel=lambda: True
                )
            self.assertFalse(success)
            self.assertTrue(message)

    def test_create_vpk_from_directory_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vpkroot = base / "vpkroot"
            vpkroot.mkdir()
            def fake_run(*args, **kwargs):
                (base / "vpkroot.vpk").write_bytes(b"vpk")
                return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            # vpk.exe вызывается в PackagingService.pack_directory — патчим там.
            with patch("src.services.packaging_service.subprocess.run", side_effect=fake_run):
                with patch("src.services.packaging_service.ToolPaths.get_vpk_tool", return_value=Path("vpk.exe")):
                    result = MergeVPKService._create_vpk_from_directory(vpkroot, "out.vpk", export_folder=str(base))
                    self.assertTrue(result.endswith("out.vpk"))

    def test_create_vpk_from_directory_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            vpkroot = base / "vpkroot"
            vpkroot.mkdir()
            def fake_run(*args, **kwargs):
                return type("R", (), {"returncode": 1, "stdout": "bad", "stderr": "err"})()
            # vpk.exe вызывается в PackagingService.pack_directory — патчим там.
            with patch("src.services.packaging_service.subprocess.run", side_effect=fake_run):
                with patch("src.services.packaging_service.ToolPaths.get_vpk_tool", return_value=Path("vpk.exe")):
                    with self.assertRaises(VPKCreationError):
                        MergeVPKService._create_vpk_from_directory(vpkroot, "out.vpk", export_folder=str(base))


if __name__ == "__main__":
    unittest.main()
