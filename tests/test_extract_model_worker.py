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
    qtcore.QMutex = object
    qtcore.QWaitCondition = object
    sys.modules["PySide6"] = pyside
    sys.modules["PySide6.QtCore"] = qtcore


class ExtractModelWorkerTests(unittest.TestCase):
    def setUp(self):
        setup_fake_pyside6()
        # base_worker тоже переимпортируем под фейковым PySide6 (воркер от него наследует).
        for _m in ("src.services.base_worker", "src.services.extract_model_worker"):
            sys.modules.pop(_m, None)
        self.module = importlib.import_module("src.services.extract_model_worker")
        self.ExtractModelWorker = self.module.ExtractModelWorker

    def test_run_success(self):
        worker = self.ExtractModelWorker("tf2", "scout_c_test", "c_test", language="en")
        with patch(
            "src.services.extract_model_worker.ExtractModelService.prepare_decompiled_model_files_with_progress",
            return_value=(True, "ok", False, {"temp_dir": "t", "decompile_dir": "d", "files": ["a.smd"]}),
        ):
            worker.run()
        self.assertTrue(worker.finished.calls)
        self.assertEqual(worker.prepared_temp_dir, "t")
        self.assertEqual(worker.prepared_decompile_dir, "d")
        self.assertEqual(worker.prepared_files, ["a.smd"])

    def test_run_fail(self):
        worker = self.ExtractModelWorker("tf2", "scout_c_test", "c_test", language="en")
        with patch(
            "src.services.extract_model_worker.ExtractModelService.prepare_decompiled_model_files_with_progress",
            return_value=(False, "fail", False, None),
        ):
            worker.run()
        self.assertTrue(worker.finished.calls)


if __name__ == "__main__":
    unittest.main()
