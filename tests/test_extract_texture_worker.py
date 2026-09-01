import unittest
from unittest.mock import Mock, patch

from src.services.extract_texture_worker import ExtractTextureWorker


class ExtractTextureWorkerTests(unittest.TestCase):
    def _make(self, *args, **kwargs):
        worker = ExtractTextureWorker(*args, **kwargs)
        worker.finished_calls = Mock()
        worker.finished.connect(worker.finished_calls)
        return worker

    def test_run_success(self):
        worker = self._make("file.vpk", "c_test", "out", export_format="PNG", language="en")
        with patch("src.services.extract_texture_worker.TF2VPKExtractService.extract_texture_with_progress", return_value=(True, "ok", False)):
            worker.run()
        worker.finished_calls.assert_called_once()

    def test_run_fail(self):
        worker = self._make("file.vpk", "c_test", "out", export_format="PNG", language="en")
        with patch("src.services.extract_texture_worker.TF2VPKExtractService.extract_texture_with_progress", return_value=(False, "fail", False)):
            worker.run()
        worker.finished_calls.assert_called_once()


if __name__ == "__main__":
    unittest.main()
