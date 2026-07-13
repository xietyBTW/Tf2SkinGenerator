import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.services.edited_vmt_service import EditedVMTService


class EditedVMTServiceTests(unittest.TestCase):
    def test_save_get_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with patch.object(EditedVMTService, "EDITED_VMT_DIR", str(base)):
                key = "c_test"
                content = '"UnlitGeneric" {}'
                saved_path = EditedVMTService.save_edited_vmt(key, content)
                self.assertTrue(Path(saved_path).exists())
                self.assertTrue(EditedVMTService.has_edited_vmt(key))
                self.assertEqual(EditedVMTService.get_edited_vmt(key), saved_path)
                self.assertTrue(EditedVMTService.delete_edited_vmt(key))
                self.assertFalse(EditedVMTService.has_edited_vmt(key))

    def test_get_edited_vmt_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with patch.object(EditedVMTService, "EDITED_VMT_DIR", str(base)):
                self.assertIsNone(EditedVMTService.get_edited_vmt("missing"))

    def test_original_backup_roundtrip_and_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with patch.object(EditedVMTService, "EDITED_VMT_DIR", str(base)):
                key = "c_test"
                self.assertFalse(EditedVMTService.has_original_backup(key))
                self.assertIsNone(EditedVMTService.read_original_backup(key))
                EditedVMTService.save_original_backup(key, "game original")
                self.assertTrue(EditedVMTService.has_original_backup(key))
                self.assertEqual(EditedVMTService.read_original_backup(key), "game original")
                # Бэкап хранится как .orig, а не .vmt — не путается с правкой.
                self.assertFalse(EditedVMTService.has_edited_vmt(key))
                # delete_edited_vmt убирает и правку, и бэкап оригинала.
                EditedVMTService.save_edited_vmt(key, "edited")
                EditedVMTService.delete_edited_vmt(key)
                self.assertFalse(EditedVMTService.has_edited_vmt(key))
                self.assertFalse(EditedVMTService.has_original_backup(key))


if __name__ == "__main__":
    unittest.main()
