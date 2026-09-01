import unittest
from unittest.mock import Mock, patch

from src.services.extract_model_worker import ExtractModelWorker


class ExtractModelWorkerTests(unittest.TestCase):
    def _make(self, *args, **kwargs):
        worker = ExtractModelWorker(*args, **kwargs)
        worker.finished_calls = Mock()
        worker.finished.connect(worker.finished_calls)
        return worker

    def test_run_success(self):
        worker = self._make("tf2", "scout_c_test", "c_test", language="en")
        with patch(
            "src.services.extract_model_worker.ExtractModelService.prepare_decompiled_model_files_with_progress",
            return_value=(True, "ok", False, {"temp_dir": "t", "decompile_dir": "d", "files": ["a.smd"]}),
        ):
            worker.run()
        worker.finished_calls.assert_called_once()
        self.assertEqual(worker.prepared_temp_dir, "t")
        self.assertEqual(worker.prepared_decompile_dir, "d")
        self.assertEqual(worker.prepared_files, ["a.smd"])

    def test_run_fail(self):
        worker = self._make("tf2", "scout_c_test", "c_test", language="en")
        with patch(
            "src.services.extract_model_worker.ExtractModelService.prepare_decompiled_model_files_with_progress",
            return_value=(False, "fail", False, None),
        ):
            worker.run()
        worker.finished_calls.assert_called_once()


if __name__ == "__main__":
    unittest.main()
