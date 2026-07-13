"""Тесты базовых воркеров (StandardWorker.run-шаблон, BaseWorker.stop)."""

import importlib
import sys
import types
import unittest


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

        def isRunning(self):
            return False

    qtcore.QThread = DummyThread
    qtcore.Signal = DummySignal
    qtcore.QMutex = object
    qtcore.QWaitCondition = object
    sys.modules["PySide6"] = pyside
    sys.modules["PySide6.QtCore"] = qtcore


setup_fake_pyside6()
sys.modules.pop("src.services.base_worker", None)
_bw = importlib.import_module("src.services.base_worker")
StandardWorker = _bw.StandardWorker


class _OkWorker(StandardWorker):
    def work(self):
        self.progress.emit(50, "half")
        return True, "done"


class _FailWorker(StandardWorker):
    def work(self):
        raise RuntimeError("boom")


class StandardWorkerTests(unittest.TestCase):
    def test_work_success_emits_finished(self):
        w = _OkWorker()
        w.run()
        self.assertEqual(w.finished.calls[-1][0], (True, "done"))

    def test_work_exception_becomes_error_and_finished_false(self):
        w = _FailWorker()
        w.run()
        self.assertTrue(w.error.calls)
        success, message = w.finished.calls[-1][0]
        self.assertFalse(success)
        self.assertEqual(message, "boom")

    def test_stop_when_not_running_returns_true(self):
        w = _OkWorker()
        self.assertTrue(w.stop())


if __name__ == "__main__":
    unittest.main()
