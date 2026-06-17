import unittest

from src.shared.exceptions import (
    ErrorPayload,
    TF2SkinGeneratorError,
    RequiredFileMissingError,
    VTFCreationError,
    VPKCreationError,
)


class ExceptionsTests(unittest.TestCase):
    def test_required_file_missing_error(self):
        err = RequiredFileMissingError("path.txt")
        self.assertIn("path.txt", str(err))
        self.assertEqual(err.file_path, "path.txt")

    def test_required_file_missing_error_custom_message(self):
        err = RequiredFileMissingError("path.txt", "custom message")
        self.assertEqual(str(err), "custom message")

    def test_required_file_missing_is_builtin_file_not_found(self):
        """except FileNotFoundError должен ловить кастомный тип."""
        err = RequiredFileMissingError("path.txt")
        self.assertIsInstance(err, FileNotFoundError)
        self.assertIsInstance(err, TF2SkinGeneratorError)

    def test_vtf_creation_error(self):
        err = VTFCreationError("cmd", stdout="out", stderr="err")
        self.assertIn("cmd", str(err))
        self.assertIn("out", str(err))
        self.assertIn("err", str(err))

    def test_vpk_creation_error(self):
        err = VPKCreationError(stdout="out", stderr="err")
        self.assertIn("out", str(err))
        self.assertIn("err", str(err))

    def test_error_payload_to_text(self):
        payload = ErrorPayload(code="x", message="msg", details="det")
        self.assertEqual(payload.to_text(), "msg\ndet")
        payload_no_details = ErrorPayload(code="x", message="msg")
        self.assertEqual(payload_no_details.to_text(), "msg")


if __name__ == "__main__":
    unittest.main()
