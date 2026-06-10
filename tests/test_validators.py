import os
import tempfile
import unittest
from pathlib import Path

from src.shared.validators import (
    validate_vpk_filename,
    validate_build_params,
    sanitize_path,
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


class SanitizePathTests(unittest.TestCase):
    def test_allows_inside_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = sanitize_path("subdir/file.txt", tmp)
            self.assertTrue(result.startswith(os.path.abspath(tmp)))

    def test_blocks_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                sanitize_path("../outside.txt", tmp)

    def test_blocks_drive_letters(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                sanitize_path("C:/evil.txt", tmp)

    def test_blocks_sibling_prefix_dir(self):
        """'C:/base_evil' не должен проходить проверку для базы 'C:/base'."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "base"
            base.mkdir()
            with self.assertRaises(ValueError):
                sanitize_path("../base_evil/file.txt", str(base))


class ValidateBuildParamsTests(unittest.TestCase):
    def _t(self):
        from src.data.translations import TRANSLATIONS
        return TRANSLATIONS["en"]

    def test_missing_image(self):
        err = validate_build_params(
            image_path="", mode="x", filename="a.vpk",
            size=(512, 512), format_type="DXT1", tf2_root_dir="", t=self._t(),
        )
        self.assertIsNotNone(err)

    def test_special_mode_does_not_require_tf2(self):
        special = next(iter(SPECIAL_MODES.values()))
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "img.png"
            image.write_bytes(b"123")
            err = validate_build_params(
                image_path=str(image), mode=special, filename="a.vpk",
                size=(512, 512), format_type="DXT1", tf2_root_dir="", t=self._t(),
            )
        self.assertIsNone(err)

    def test_weapon_mode_requires_tf2(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "img.png"
            image.write_bytes(b"123")
            err = validate_build_params(
                image_path=str(image), mode="scout_c_scattergun", filename="a.vpk",
                size=(512, 512), format_type="DXT1", tf2_root_dir="", t=self._t(),
            )
        self.assertIsNotNone(err)

    def test_invalid_format_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "img.png"
            image.write_bytes(b"123")
            err = validate_build_params(
                image_path=str(image),
                mode=next(iter(SPECIAL_MODES.values())),
                filename="a.vpk",
                size=(512, 512), format_type="NOT_A_FORMAT",
                tf2_root_dir="", t=self._t(),
            )
        self.assertIsNotNone(err)

    def test_invalid_size_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "img.png"
            image.write_bytes(b"123")
            for bad_size in [(512,), (0, 512), ("512", 512), None]:
                err = validate_build_params(
                    image_path=str(image),
                    mode=next(iter(SPECIAL_MODES.values())),
                    filename="a.vpk",
                    size=bad_size, format_type="DXT1",
                    tf2_root_dir="", t=self._t(),
                )
                self.assertIsNotNone(err, f"size={bad_size!r} должен быть отклонён")

    def test_filename_must_end_with_vpk(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "img.png"
            image.write_bytes(b"123")
            err = validate_build_params(
                image_path=str(image),
                mode=next(iter(SPECIAL_MODES.values())),
                filename="a.zip",
                size=(512, 512), format_type="DXT1",
                tf2_root_dir="", t=self._t(),
            )
        self.assertIsNotNone(err)

    def test_custom_vtf_path_must_exist(self):
        err = validate_build_params(
            image_path=None,
            mode=next(iter(SPECIAL_MODES.values())),
            filename="a.vpk",
            size=(512, 512), format_type="DXT1",
            tf2_root_dir="", t=self._t(),
            custom_vtf_path="missing.vtf",
        )
        self.assertIsNotNone(err)


if __name__ == "__main__":
    unittest.main()
