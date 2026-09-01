import unittest
from unittest.mock import Mock, patch

from src.services.merge_vpk_worker import MergeVpkWorker






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
        worker.requestInterruption()
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
