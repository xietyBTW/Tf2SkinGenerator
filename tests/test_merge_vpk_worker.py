import importlib
import sys
import types
import unittest
from unittest.mock import Mock, patch


def setup_fake_pyside6():
    """Подменяет PySide6.QtCore заглушкой — воркер тестируется без реального Qt."""
    qtcore = types.ModuleType("PySide6.QtCore")

    class DummySignal:
        def __init__(self, *args, **kwargs):
            self.calls = []

        def emit(self, *args, **kwargs):
            self.calls.append(args)

    class DummyThread:
        def __init__(self, *args, **kwargs):
            self._interrupted = False

        def isInterruptionRequested(self):
            return self._interrupted

    qtcore.QThread = DummyThread
    qtcore.Signal = DummySignal
    sys.modules.setdefault("PySide6", types.ModuleType("PySide6"))
    sys.modules["PySide6.QtCore"] = qtcore


setup_fake_pyside6()
sys.modules.pop("src.services.base_worker", None)
sys.modules.pop("src.services.merge_vpk_worker", None)
MergeVpkWorker = importlib.import_module("src.services.merge_vpk_worker").MergeVpkWorker


class MergeVpkWorkerTests(unittest.TestCase):
    def _make(self):
        worker = MergeVpkWorker(["a.vpk", "b.vpk"], "out", "export", "en")
        worker.finished.emit = Mock()
        worker.progress.emit = Mock()
        return worker

    def test_success_emits_result_and_progress(self):
        worker = self._make()
        with patch(
            "src.services.merge_vpk_worker.MergeVPKService.merge_vpk_files",
            return_value=(True, "done"),
        ):
            worker.run()
        worker.finished.emit.assert_called_with(True, "done")
        # стартовый (10%) и финальный (100%) прогресс
        self.assertGreaterEqual(worker.progress.emit.call_count, 2)

    def test_interruption_marks_cancelled(self):
        worker = self._make()
        worker._interrupted = True
        with patch(
            "src.services.merge_vpk_worker.MergeVPKService.merge_vpk_files",
            return_value=(True, "done"),
        ):
            worker.run()
        ok, _msg = worker.finished.emit.call_args.args
        self.assertFalse(ok)

    def test_exception_reports_failure(self):
        worker = self._make()
        with patch(
            "src.services.merge_vpk_worker.MergeVPKService.merge_vpk_files",
            side_effect=RuntimeError("boom"),
        ):
            worker.run()
        ok, msg = worker.finished.emit.call_args.args
        self.assertFalse(ok)
        self.assertIn("boom", msg)


if __name__ == "__main__":
    unittest.main()
