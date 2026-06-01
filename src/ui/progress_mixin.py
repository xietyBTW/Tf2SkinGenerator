"""
Mixin для управления прогресс-диалогами главного окна.

Намеренно без зависимостей от Qt: методы оперируют атрибутами `self`
(прогресс-диалог по имени и кнопка панели), поэтому легко тестируются
с обычной заглушкой-объектом, без запуска QApplication.
"""

from typing import Optional


class ProgressDialogMixin:
    """Общие операции с прогресс-диалогами (закрытие, обновление)."""

    def _close_progress(self, attr: str, button: Optional[str] = None) -> None:
        """
        Закрывает прогресс-диалог `self.<attr>` (если есть) и обнуляет его,
        затем — при указанном `button` — включает кнопку `self.settings_panel.<button>`.
        """
        dlg = getattr(self, attr, None)
        if dlg is not None:
            dlg.close()
            setattr(self, attr, None)
        if button and hasattr(self.settings_panel, button):
            getattr(self.settings_panel, button).setEnabled(True)

    def _update_progress(self, attr: str, percentage: int, status: str) -> None:
        """Обновляет значение и подпись прогресс-диалога `self.<attr>`, если он существует."""
        dlg = getattr(self, attr, None)
        if dlg is not None:
            dlg.setValue(percentage)
            dlg.setLabelText(status)

    def _cancel_worker(self, worker_attr: str, dialog_attr: Optional[str] = None) -> None:
        """
        Прерывает воркер `self.<worker_attr>`, если он запущен.

        Если задан `dialog_attr` и у диалога есть `mark_cancelling()` — помечает
        диалог как «отменяется» перед прерыванием.
        """
        worker = getattr(self, worker_attr, None)
        if worker is None or not worker.isRunning():
            return
        if dialog_attr:
            dlg = getattr(self, dialog_attr, None)
            if dlg is not None and hasattr(dlg, "mark_cancelling"):
                dlg.mark_cancelling()
        worker.requestInterruption()
