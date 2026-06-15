"""
Базовые классы фоновых воркеров (QThread).

Зачем:
  • единый предок → один способ безопасной остановки потока (stop);
  • StandardWorker задаёт типовой контракт сигналов (finished/progress/error)
    и шаблонный run(), который ловит исключения и превращает их в
    error + finished(False, ...) — чтобы не дублировать try/except в каждом
    воркере и не расходиться в обработке ошибок.

Воркеры со своим набором сигналов (preview-воркеры, skin-detect) наследуют
BaseWorker ради безопасного stop(), а сигналы и run() объявляют сами.
"""

from typing import Tuple

from PySide6.QtCore import QThread, Signal

from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class BaseWorker(QThread):
    """Общий предок воркеров: безопасная кооперативная остановка."""

    def stop(self, timeout_ms: int = 5000) -> bool:
        """
        Просит поток прерваться и ждёт завершения — перед deleteLater, чтобы не
        словить «QThread: Destroyed while thread is still running».

        Воркеры проверяют isInterruptionRequested() в своих циклах/колбэках.

        Returns:
            True, если поток не запущен или завершился в отведённое время.
        """
        if not self.isRunning():
            return True
        self.requestInterruption()
        return self.wait(timeout_ms)


class StandardWorker(BaseWorker):
    """
    Воркер с типовым контрактом «(успех, сообщение) + прогресс + ошибка».

    Наследник реализует work() и ВОЗВРАЩАЕТ (success, message) — finished
    эмитится автоматически. Любое исключение в work() логируется и
    превращается в error(msg) + finished(False, msg).

    Отмену наследник проверяет сам через isInterruptionRequested().
    """

    finished = Signal(bool, str)   # (success, message)
    progress = Signal(int, str)    # (percent 0-100, status)
    error = Signal(str)            # (error_message)

    def work(self) -> Tuple[bool, str]:
        """Полезная нагрузка воркера. Должна вернуть (success, message)."""
        raise NotImplementedError

    def run(self) -> None:
        try:
            success, message = self.work()
        except Exception as exc:  # noqa: BLE001 — верхняя граница воркера
            message = str(exc)
            logger.critical(
                f"{type(self).__name__}: критическая ошибка: {message}",
                exc_info=True,
            )
            self.error.emit(message)
            self.finished.emit(False, message)
            return
        self.finished.emit(success, message)
