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
                weapon_key = "c_test"
                content = '"UnlitGeneric" {}'
                saved_path = EditedVMTService.save_edited_vmt(weapon_key, content)
                self.assertTrue(Path(saved_path).exists())
                self.assertTrue(EditedVMTService.has_edited_vmt(weapon_key))
                self.assertEqual(EditedVMTService.get_edited_vmt(weapon_key), saved_path)
                self.assertTrue(EditedVMTService.delete_edited_vmt(weapon_key))
                self.assertFalse(EditedVMTService.has_edited_vmt(weapon_key))

    def test_get_edited_vmt_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            with patch.object(EditedVMTService, "EDITED_VMT_DIR", str(base)):
                self.assertIsNone(EditedVMTService.get_edited_vmt("missing"))


if __name__ == "__main__":
    unittest.main()
