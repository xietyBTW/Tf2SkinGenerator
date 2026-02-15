import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.shared.validators import (
    validate_vpk_filename,
    validate_tf2_path,
    validate_image_path,
    validate_vtf_format,
    validate_resolution,
    validate_mode,
)
from src.data.weapons import SPECIAL_MODES


class ValidatorsTests(unittest.TestCase):
    def test_validate_vpk_filename(self):
        self.assertEqual(validate_vpk_filename(""), (False, "Имя файла не может быть пустым"))
        self.assertEqual(validate_vpk_filename(" ")[0], False)
        self.assertEqual(validate_vpk_filename("a" * 60 + ".vpk")[0], False)
        self.assertEqual(validate_vpk_filename("bad:name.vpk")[0], False)
        self.assertEqual(validate_vpk_filename("a.vpk")[0], True)
        self.assertEqual(validate_vpk_filename("a.txt")[0], False)
        self.assertEqual(validate_vpk_filename("bad|name.vpk")[0], False)

    def test_validate_tf2_path(self):
        self.assertEqual(validate_tf2_path("")[0], False)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self.assertEqual(validate_tf2_path(str(base))[0], False)
            file_path = base / "file.txt"
            file_path.write_text("x", encoding="utf-8")
            self.assertEqual(validate_tf2_path(str(file_path))[0], False)
            (base / "tf2.exe").write_text("x", encoding="utf-8")
            self.assertEqual(validate_tf2_path(str(base))[0], True)

    def test_validate_image_path(self):
        self.assertEqual(validate_image_path("")[0], False)
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            image = base / "img.png"
            image.write_bytes(b"123")
            self.assertEqual(validate_image_path(image)[0], True)
            self.assertEqual(validate_image_path(base / "missing.png")[0], False)
            bad = base / "img.txt"
            bad.write_text("x", encoding="utf-8")
            self.assertEqual(validate_image_path(bad)[0], False)
            self.assertEqual(validate_image_path(base)[0], False)
            with patch.object(Path, "is_file", return_value=True):
                with patch.object(Path, "stat", return_value=type("S", (), {"st_size": 200 * 1024 * 1024})()):
                    self.assertEqual(validate_image_path(image)[0], False)

    def test_validate_vtf_format(self):
        self.assertEqual(validate_vtf_format("")[0], False)
        self.assertEqual(validate_vtf_format("DXT1")[0], True)
        self.assertEqual(validate_vtf_format("BAD")[0], False)

    def test_validate_resolution(self):
        self.assertEqual(validate_resolution(None)[0], False)
        self.assertEqual(validate_resolution((512,))[0], False)
        self.assertEqual(validate_resolution((512, 512))[0], True)
        self.assertEqual(validate_resolution((0, 512))[0], False)
        self.assertEqual(validate_resolution(("512", 512))[0], False)
        self.assertEqual(validate_resolution((300, 300))[0], False)
        self.assertEqual(validate_resolution((5000, 5000))[0], False)

    def test_validate_mode(self):
        self.assertEqual(validate_mode(None)[0], False)
        self.assertEqual(validate_mode(123)[0], False)
        special = next(iter(SPECIAL_MODES.values()))
        self.assertEqual(validate_mode(special)[0], True)
        self.assertEqual(validate_mode("scout_c_scattergun")[0], True)
        self.assertEqual(validate_mode("badmode")[0], False)


if __name__ == "__main__":
    unittest.main()
