import importlib
import sys
import tempfile
import types
import unittest

from PIL import Image


def setup_fake_pyside6():
    qtcore = types.ModuleType("PySide6.QtCore")
    qtgui = types.ModuleType("PySide6.QtGui")
    pyside = types.ModuleType("PySide6")

    class DummyPixmap:
        def __init__(self, *args, **kwargs):
            pass

        def scaled(self, *args, **kwargs):
            return self

        @staticmethod
        def fromImage(image):
            return DummyPixmap()

    class DummyQt:
        KeepAspectRatio = 1
        SmoothTransformation = 2

    qtgui.QPixmap = DummyPixmap
    qtcore.Qt = DummyQt
    sys.modules["PySide6"] = pyside
    sys.modules["PySide6.QtCore"] = qtcore
    sys.modules["PySide6.QtGui"] = qtgui


class ImageServiceTests(unittest.TestCase):
    def setUp(self):
        setup_fake_pyside6()
        if "src.services.image_service" in sys.modules:
            del sys.modules["src.services.image_service"]
        self.module = importlib.import_module("src.services.image_service")
        self.ImageService = self.module.ImageService

    def test_is_image_file(self):
        self.assertTrue(self.ImageService.is_image_file("a.png"))
        self.assertFalse(self.ImageService.is_image_file("a.txt"))

    def test_save_pil_to_temp(self):
        image = Image.new("RGB", (10, 10), color="red")
        path = self.ImageService.save_pil_to_temp(image)
        self.assertTrue(path.endswith(".png"))

    def test_pil_to_qpixmap_fallback(self):
        image = Image.new("RGB", (10, 10), color="red")
        with tempfile.TemporaryDirectory() as tmp:
            with unittest.mock.patch("PIL.ImageQt.ImageQt", side_effect=Exception("fail"), create=True):
                pixmap = self.ImageService.pil_to_qpixmap(image)
        self.assertIsNotNone(pixmap)


if __name__ == "__main__":
    unittest.main()
