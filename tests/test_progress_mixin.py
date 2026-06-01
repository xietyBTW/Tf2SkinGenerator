import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from src.ui.progress_mixin import ProgressDialogMixin


class _Owner(ProgressDialogMixin):
    """Лёгкая заглушка-владелец (без Qt) для проверки логики миксина."""


class ProgressDialogMixinTests(unittest.TestCase):
    def test_close_progress_closes_dialog_and_enables_button(self):
        owner = _Owner()
        owner._dlg = Mock()
        btn = Mock()
        owner.settings_panel = SimpleNamespace(my_button=btn)

        owner._close_progress("_dlg", "my_button")

        owner_dialog_after = owner._dlg
        self.assertIsNone(owner_dialog_after)
        btn.setEnabled.assert_called_once_with(True)

    def test_close_progress_without_dialog_is_safe(self):
        owner = _Owner()
        owner.settings_panel = SimpleNamespace()
        # Атрибута диалога нет вовсе — не должно падать
        owner._close_progress("_missing_dlg", "absent_button")

    def test_close_progress_missing_button_skipped(self):
        owner = _Owner()
        dlg = Mock()
        owner._dlg = dlg
        owner.settings_panel = SimpleNamespace()  # такой кнопки нет

        owner._close_progress("_dlg", "absent_button")

        dlg.close.assert_called_once()
        self.assertIsNone(owner._dlg)

    def test_close_progress_without_button_arg(self):
        owner = _Owner()
        dlg = Mock()
        owner._dlg = dlg
        owner.settings_panel = SimpleNamespace()

        owner._close_progress("_dlg")  # button=None

        dlg.close.assert_called_once()
        self.assertIsNone(owner._dlg)

    def test_update_progress_sets_value_and_label(self):
        owner = _Owner()
        owner._dlg = Mock()

        owner._update_progress("_dlg", 42, "working")

        owner._dlg.setValue.assert_called_once_with(42)
        owner._dlg.setLabelText.assert_called_once_with("working")

    def test_update_progress_without_dialog_is_safe(self):
        owner = _Owner()
        owner._update_progress("_missing", 10, "x")  # не должно падать

    def test_cancel_worker_running_requests_interruption(self):
        owner = _Owner()
        worker = Mock()
        worker.isRunning.return_value = True
        owner._wk = worker
        owner._cancel_worker("_wk")
        worker.requestInterruption.assert_called_once()

    def test_cancel_worker_not_running_does_nothing(self):
        owner = _Owner()
        worker = Mock()
        worker.isRunning.return_value = False
        owner._wk = worker
        owner._cancel_worker("_wk")
        worker.requestInterruption.assert_not_called()

    def test_cancel_worker_missing_is_safe(self):
        owner = _Owner()
        owner._cancel_worker("_absent")  # не должно падать

    def test_cancel_worker_marks_dialog_cancelling(self):
        owner = _Owner()
        worker = Mock()
        worker.isRunning.return_value = True
        owner._wk = worker
        owner._dlg = Mock()
        owner._cancel_worker("_wk", "_dlg")
        owner._dlg.mark_cancelling.assert_called_once()
        worker.requestInterruption.assert_called_once()


if __name__ == "__main__":
    unittest.main()
