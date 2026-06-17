import importlib
import sys
import types
import unittest
from unittest.mock import Mock, patch

from src.data.weapons import SPECIAL_MODES


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
    qtcore.QTimer = object
    qtcore.QMutex = object
    qtcore.QWaitCondition = object
    sys.modules["PySide6"] = pyside
    sys.modules["PySide6.QtCore"] = qtcore


setup_fake_pyside6()
sys.modules.pop("src.services.base_worker", None)
sys.modules.pop("src.services.build_worker", None)
BuildWorker = importlib.import_module("src.services.build_worker").BuildWorker


class BuildWorkerTests(unittest.TestCase):
    def test_run_special_mode_success(self):
        mode = next(iter(SPECIAL_MODES.values()))
        worker = BuildWorker(
            image_path="img.png",
            mode=mode,
            filename="out.vpk",
            size=(512, 512),
            tf2_root_dir="C:/TF2",
        )
        worker.progress.emit = Mock()
        worker.finished.emit = Mock()
        worker.error.emit = Mock()
        with patch("src.services.build_worker.VPKService.build_with_progress", return_value=(True, "ok", False)):
            worker.run()
        worker.finished.emit.assert_called()

    def test_run_failure(self):
        worker = BuildWorker(
            image_path="img.png",
            mode="scout_c_scattergun",
            filename="out.vpk",
            size=(512, 512),
            tf2_root_dir="C:/TF2",
        )
        worker.finished.emit = Mock()
        with patch("src.services.build_worker.VPKService.build_with_progress", return_value=(False, "fail", False)):
            worker.run()
        worker.finished.emit.assert_called_with(False, "fail")
    
    def test_run_cancelled(self):
        worker = BuildWorker(
            image_path="img.png",
            mode="scout_c_scattergun",
            filename="out.vpk",
            size=(512, 512),
            tf2_root_dir="C:/TF2",
        )
        worker.finished.emit = Mock()
        with patch("src.services.build_worker.VPKService.build_with_progress", return_value=(False, "cancelled", True)):
            worker.run()
        worker.finished.emit.assert_called()
    
    def test_run_exception(self):
        mode = next(iter(SPECIAL_MODES.values()))
        worker = BuildWorker(
            image_path="img.png",
            mode=mode,
            filename="out.vpk",
            size=(512, 512),
            tf2_root_dir="C:/TF2",
        )
        worker.progress.emit = Mock()
        worker.finished.emit = Mock()
        worker.error.emit = Mock()
        with patch("src.services.build_worker.VPKService.build_with_progress", side_effect=RuntimeError("boom")):
            worker.run()
        worker.error.emit.assert_called()
        worker.finished.emit.assert_called()


if __name__ == "__main__":
    unittest.main()
