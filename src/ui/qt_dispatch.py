"""
Доставка сигналов воркеров в UI-поток.

Воркеры (`src/services`) больше не знают про Qt и эмитят сигналы в своём
потоке. Трогать виджеты оттуда нельзя, поэтому слой UI ставит сюда
диспетчер, который повторяет поведение Qt AutoConnection:

  • emit из UI-потока  → слот вызывается сразу (как DirectConnection);
  • emit из воркера    → слот ставится в очередь событий UI-потока.

Прямой вызов в первом случае обязателен: при безусловной очереди
UiRequest.ask() из UI-потока ждал бы ответа, который не может прийти до
следующего оборота цикла событий, а обработчики, рассчитывающие на
синхронный порядок, поехали бы.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QObject, Qt, QThread, Signal

from src.services.base_worker import set_dispatcher


class _MainThreadDispatcher(QObject):
    """Перекидывает вызов слота в поток, которому принадлежит сам объект."""

    _invoke = Signal(object, object)   # (slot, args_tuple)

    def __init__(self):
        super().__init__()             # создаётся в UI-потоке → его affinity
        self._invoke.connect(self._run, Qt.QueuedConnection)

    @staticmethod
    def _run(slot: Callable, args: tuple) -> None:
        slot(*args)

    def __call__(self, slot: Callable, args: tuple) -> None:
        if QThread.currentThread() is self.thread():
            slot(*args)
        else:
            self._invoke.emit(slot, args)


_instance: Optional[_MainThreadDispatcher] = None


def install() -> None:
    """Ставит диспетчер. Вызывать из UI-потока, после создания QApplication."""
    global _instance
    if _instance is None:
        _instance = _MainThreadDispatcher()
        set_dispatcher(_instance)
