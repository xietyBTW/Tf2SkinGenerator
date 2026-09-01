"""
Базовые классы фоновых воркеров (чистый Python, без Qt).

Зачем без Qt: воркеры — это фоновая РАБОТА (распаковка VPK, декомпиляция,
рендер превью), она ничего не знает про то, чем её результат рисуют. Пока
базой был QThread, а сигналы приходили из PySide6, весь `src/services` тянул
за собой Qt: его нельзя было ни запустить без GUI-тулкита, ни протестировать
без подмены PySide6 заглушкой в sys.modules (см. комментарий в
tests/conftest.py — из-за таких заглушек шесть тест-модулей молча
пропускались в общем прогоне).

Контракт СОХРАНЁН по именам (isRunning / wait / requestInterruption /
isInterruptionRequested / stop / deleteLater, Signal.connect / emit), поэтому
тела воркеров и точки .connect() в UI не менялись.

Доставка в UI-поток. Qt при AutoConnection сам перекидывал слот в поток
получателя; здесь это делает диспетчер, который ставит слой UI:

    src/ui/qt_dispatch.py → set_dispatcher(...)

Без диспетчера (тесты, CLI, headless) слот вызывается прямо в потоке
воркера. Поэтому трогать Qt-виджеты из слотов можно ТОЛЬКО когда диспетчер
установлен — за это отвечает AppFactory.create_app().
"""

from __future__ import annotations

import threading
from typing import Callable, Optional, Tuple

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# Sentinel «ответ ещё не получен». None — допустимый ответ пользователя
# (отказался), поэтому None как sentinel не годится.
_NO_ANSWER = object()


# ═══════════════════════════════════════════════════════════════════════════ #
# Диспетчер доставки сигналов
# ═══════════════════════════════════════════════════════════════════════════ #

#: Callable[[slot, args_tuple], None] или None — прямой вызов.
_dispatcher: Optional[Callable[[Callable, tuple], None]] = None


def set_dispatcher(fn: Optional[Callable[[Callable, tuple], None]]) -> None:
    """Ставит доставщик слотов (UI-слой) или снимает его (None)."""
    global _dispatcher
    _dispatcher = fn


def _deliver(slot: Callable, args: tuple) -> None:
    """Доставляет один вызов слота. Исключение в слоте не валит воркер."""
    try:
        if _dispatcher is not None:
            _dispatcher(slot, args)
        else:
            slot(*args)
    except Exception:  # noqa: BLE001 — верхняя граница доставки сигнала
        logger.exception("Ошибка в обработчике сигнала")


# ═══════════════════════════════════════════════════════════════════════════ #
# Сигналы
# ═══════════════════════════════════════════════════════════════════════════ #

class _BoundSignal:
    """Сигнал конкретного экземпляра: список слотов + emit."""

    def __init__(self, name: str):
        self._name = name
        self._slots: list = []
        self._lock = threading.Lock()

    def connect(self, slot: Callable) -> None:
        with self._lock:
            self._slots.append(slot)

    def disconnect(self, slot: Optional[Callable] = None) -> None:
        """Отключает слот; без аргумента — все."""
        with self._lock:
            if slot is None:
                self._slots.clear()
            else:
                try:
                    self._slots.remove(slot)
                except ValueError:
                    pass

    def emit(self, *args) -> None:
        # Копию берём под замком, а ВЫЗЫВАЕМ без него: слот вправе
        # подключить/отключить что-то в ответ, иначе — дедлок.
        with self._lock:
            slots = tuple(self._slots)
        for slot in slots:
            _deliver(slot, args)

    def __repr__(self) -> str:
        return f"<Signal {self._name} slots={len(self._slots)}>"


class Signal:
    """
    Объявление сигнала в классе — замена PySide6.QtCore.Signal.

    Типы аргументов принимаются для совместимости с существующими
    объявлениями (`Signal(int, str)`) и не проверяются: контракт и так описан
    в комментариях рядом с объявлением, а рантайм-проверка типов здесь ловила
    бы то, что ловит ревью.
    """

    def __init__(self, *arg_types):
        self._arg_types = arg_types
        self._name = '<unnamed>'

    def __set_name__(self, owner, name: str) -> None:
        self._name = name

    def __get__(self, obj, owner=None):
        if obj is None:
            return self
        # Ключ намеренно отличается от имени атрибута: иначе запись в
        # __dict__ перекрыла бы сам дескриптор (он не data-descriptor).
        key = f'__signal_{self._name}'
        bound = obj.__dict__.get(key)
        if bound is None:
            # setdefault атомарен: при гонке лишний объект просто отбросится.
            bound = obj.__dict__.setdefault(key, _BoundSignal(self._name))
        return bound


# ═══════════════════════════════════════════════════════════════════════════ #
# Запрос данных из воркера в UI
# ═══════════════════════════════════════════════════════════════════════════ #

class UiRequest:
    """
    Синхронный запрос данных из воркера в UI-поток: emit сигнала → ожидание ответа.

    Воркер (фоновый поток) вызывает ask(*args):
      1. Сбрасывает результат в sentinel.
      2. Эмитит сигнал (НЕ под замком — иначе дедлок, если UI ответит сразу).
      3. Ждёт ответа на условной переменной.

    UI-поток (слот сигнала) вызывает answer(value):
      4. Показывает диалог, пишет результат, notify_all().

    Гонка «UI ответил между emit и wait» безопасна: wait_for сначала проверяет
    предикат и в ожидание не входит, если ответ уже записан.
    """

    def __init__(self, signal, timeout_ms: int = 300_000):
        self._signal = signal
        self._timeout = timeout_ms / 1000.0
        self._cond = threading.Condition()
        self._result: object = _NO_ANSWER

    def ask(self, *args):
        """Эмитит сигнал и блокируется до answer() или таймаута. None при таймауте."""
        with self._cond:
            self._result = _NO_ANSWER

        self._signal.emit(*args)

        with self._cond:
            answered = self._cond.wait_for(
                lambda: self._result is not _NO_ANSWER, self._timeout)
            if not answered:
                logger.warning(
                    f"UiRequest: таймаут ожидания ответа от UI ({self._timeout:g} с)")
                return None
            return self._result

    def answer(self, value) -> None:
        """Передаёт ответ ждущему воркеру (вызывается из UI-потока)."""
        with self._cond:
            self._result = value
            self._cond.notify_all()


# ═══════════════════════════════════════════════════════════════════════════ #
# Воркеры
# ═══════════════════════════════════════════════════════════════════════════ #

class BaseWorker(threading.Thread):
    """
    Общий предок воркеров: кооперативная остановка.

    Имена методов повторяют QThread намеренно — тела воркеров и вызовы из UI
    писались под них, а переименование дало бы диффом сотни строк без единого
    изменения смысла.
    """

    def __init__(self, parent=None):
        # parent игнорируется: у QThread он задавал владение в дереве QObject,
        # у обычного потока владельца нет — объект живёт, пока на него есть
        # ссылка. Аргумент оставлен, чтобы не править вызовы
        # super().__init__(parent) в наследниках.
        super().__init__(daemon=True, name=type(self).__name__)
        self._interrupt = threading.Event()

    # ── Отмена ────────────────────────────────────────────────────────────── #
    def requestInterruption(self) -> None:
        """Просит воркер прерваться при следующей проверке."""
        self._interrupt.set()

    def isInterruptionRequested(self) -> bool:
        """Проверяется воркером в циклах и колбэках."""
        return self._interrupt.is_set()

    # ── Состояние и ожидание ──────────────────────────────────────────────── #
    def isRunning(self) -> bool:
        return self.is_alive()

    def wait(self, timeout_ms: Optional[int] = None) -> bool:
        """Ждёт завершения. True, если поток завершился в отведённое время."""
        if not self.is_alive():
            return True
        self.join(None if timeout_ms is None else timeout_ms / 1000.0)
        return not self.is_alive()

    def stop(self, timeout_ms: int = 5000) -> bool:
        """
        Просит поток прерваться и ждёт завершения.

        Returns:
            True, если поток не запущен или завершился в отведённое время.
        """
        if not self.is_alive():
            return True
        self.requestInterruption()
        return self.wait(timeout_ms)

    def deleteLater(self) -> None:
        """No-op ради совместимости с местами вызова.

        У QThread это снимало объект с родителя (мёртвые потоки копились
        детьми панели). У обычного потока родителя нет — освободит GC.
        """


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
