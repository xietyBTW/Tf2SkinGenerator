"""Фоновый прогон диагностики VPK — чтобы UI не подвисал на распаковке/осмотре."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class DiagnosticsWorker(QThread):
    """Гоняет inspect_vpk в отдельном потоке. Сигнал finished несёт
    DiagnosticReport (или None при неожиданной ошибке — тогда шлём error)."""

    finished = Signal(object)   # DiagnosticReport
    error = Signal(str)

    def __init__(self, vpk_path: str, parent=None):
        super().__init__(parent)
        self._vpk_path = vpk_path

    def run(self) -> None:
        try:
            from src.services.diagnostics import inspect_vpk
            report = inspect_vpk(self._vpk_path)
            self.finished.emit(report)
        except Exception as e:                   # noqa: BLE001
            logger.error(f"Диагностика упала: {e}", exc_info=True)
            self.error.emit(str(e))
