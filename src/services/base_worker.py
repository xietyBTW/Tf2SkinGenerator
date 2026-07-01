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

from PySide6.QtCore import QMutex, QThread, QWaitCondition, Signal

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# Sentinel «ответ ещё не получен». None — допустимый ответ пользователя
# (отказался), поэтому None как sentinel не годится.
_NO_ANSWER = object()


class UiRequest:
    """
    Синхронный запрос данных из воркера в UI-поток: emit сигнала → ожидание ответа.

    Воркер (фоновый поток) вызывает ask(*args):
      1. Под мьютексом сбрасывает результат в sentinel.
      2. Эмитит сигнал (НЕ под мьютексом — иначе дедлок, если UI ответит сразу).
      3. Берёт мьютекс и ждёт (condition.wait атомарно отпускает мьютекс).

    UI-поток (слот сигнала, QueuedConnection) вызывает answer(value):
      4. Показывает диалог, берёт мьютекс (свободен — воркер в wait).
      5. Записывает результат, wakeAll() → воркер просыпается и читает ответ.

    Гонка «UI ответил между emit и wait» безопасна: ask() проверяет sentinel
    в while перед wait — если ответ уже записан, в wait не входит.
    """

    def __init__(self, signal, timeout_ms: int = 300_000):
        self._signal = signal
        self._timeout_ms = timeout_ms
        self._mutex = QMutex()
        self._condition = QWaitCondition()
        self._result: object = _NO_ANSWER

    def ask(self, *args):
        """Эмитит сигнал и блокируется до answer() или таймаута. None при таймауте."""
        self._mutex.lock()
        try:
            self._result = _NO_ANSWER
        finally:
            self._mutex.unlock()

        self._signal.emit(*args)

        self._mutex.lock()
        try:
            while self._result is _NO_ANSWER:
                if not self._condition.wait(self._mutex, self._timeout_ms):
                    logger.warning(f"UiRequest: таймаут ожидания ответа от UI ({self._timeout_ms} мс)")
                    break
            return self._result if self._result is not _NO_ANSWER else None
        finally:
            self._mutex.unlock()

    def answer(self, value) -> None:
        """Передаёт ответ ждущему воркеру (вызывается из UI-потока)."""
        self._mutex.lock()
        try:
            self._result = value
            self._condition.wakeAll()
        finally:
            self._mutex.unlock()


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
