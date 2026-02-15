import unittest

from src.shared.exceptions import (
    FileNotFoundError,
    DirectoryNotFoundError,
    TF2PathNotFoundError,
    ModelNotFoundError,
    ModelDecompilationError,
    ModelCompilationError,
    VTFCreationError,
    VPKCreationError,
    BuildError,
    PathTooLongError,
    InvalidFilenameError,
    InvalidImageError,
)


class ExceptionsTests(unittest.TestCase):
    def test_file_not_found_error(self):
        err = FileNotFoundError("path.txt")
        self.assertIn("path.txt", str(err))

    def test_directory_not_found_error(self):
        err = DirectoryNotFoundError("dir")
        self.assertIn("dir", str(err))

    def test_tf2_path_not_found_error(self):
        err = TF2PathNotFoundError("tf2")
        self.assertIn("tf2", str(err))

    def test_model_not_found_error(self):
        err = ModelNotFoundError("weapon", searched_paths=["a", "b"])
        self.assertIn("weapon", str(err))
        self.assertIn("a", str(err))

    def test_model_decompilation_error(self):
        err = ModelDecompilationError("model.mdl", "bad")
        self.assertIn("model.mdl", str(err))

    def test_model_compilation_error(self):
        err = ModelCompilationError("model.qc", "bad")
        self.assertIn("model.qc", str(err))

    def test_vtf_creation_error(self):
        err = VTFCreationError("cmd", stdout="out", stderr="err")
        self.assertIn("cmd", str(err))
        self.assertIn("out", str(err))
        self.assertIn("err", str(err))

    def test_vpk_creation_error(self):
        err = VPKCreationError(stdout="out", stderr="err")
        self.assertIn("out", str(err))
        self.assertIn("err", str(err))

    def test_build_error(self):
        err = BuildError("fail", details="detail")
        self.assertIn("detail", str(err))

    def test_path_too_long_error(self):
        err = PathTooLongError("path", max_length=10)
        self.assertIn("10", str(err))

    def test_invalid_filename_error(self):
        err = InvalidFilenameError("file", "bad")
        self.assertIn("file", str(err))

    def test_invalid_image_error(self):
        err = InvalidImageError("img", "bad")
        self.assertIn("img", str(err))


if __name__ == "__main__":
    unittest.main()
