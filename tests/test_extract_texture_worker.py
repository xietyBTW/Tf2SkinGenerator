import importlib
import sys
import types
import unittest
from unittest.mock import patch


def setup_fake_pyside6():
    qtcore = types.ModuleType("PySide6.QtCore")
    pyside = types.ModuleType("PySide6")

    class DummySignal:
        def __init__(self, *args, **kwargs):
            self.calls = []

        def emit(self, *args, **kwargs):
            self.calls.append((args, kwargs))

    class DummyThread:
        def __init__(self, *args, **kwargs):
            self._interrupted = False

        def isInterruptionRequested(self):
            return self._interrupted

    qtcore.QThread = DummyThread
    qtcore.Signal = DummySignal
    sys.modules["PySide6"] = pyside
    sys.modules["PySide6.QtCore"] = qtcore


class ExtractTextureWorkerTests(unittest.TestCase):
    def setUp(self):
        setup_fake_pyside6()
        for _m in ("src.services.base_worker", "src.services.extract_texture_worker"):
            sys.modules.pop(_m, None)
        self.module = importlib.import_module("src.services.extract_texture_worker")
        self.ExtractTextureWorker = self.module.ExtractTextureWorker

    def test_run_success(self):
        worker = self.ExtractTextureWorker("file.vpk", "c_test", "out", export_format="PNG", language="en")
        with patch("src.services.extract_texture_worker.TF2VPKExtractService.extract_texture_with_progress", return_value=(True, "ok", False)):
            worker.run()
        self.assertTrue(worker.finished.calls)

    def test_run_fail(self):
        worker = self.ExtractTextureWorker("file.vpk", "c_test", "out", export_format="PNG", language="en")
        with patch("src.services.extract_texture_worker.TF2VPKExtractService.extract_texture_with_progress", return_value=(False, "fail", False)):
            worker.run()
        self.assertTrue(worker.finished.calls)


if __name__ == "__main__":
    unittest.main()
