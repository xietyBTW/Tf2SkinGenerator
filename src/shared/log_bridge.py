"""
Журнал Python — на страницу.

В приложении 700 вызовов логгера, и 640 из них в `src/services`, то есть ровно
там, где идёт работа: что нашлось в VPK, какой VMT взят, почему упал Crowbar.
Всё это писалось только в файл, а консоль в окне показывала лишь обмен
страницы с Python — факт вызова, но не рассказ о работе. Отсюда и ощущение,
что в консоли пусто.

Как устроено. Обычный ``logging.Handler`` складывает записи в кольцевой буфер,
страница забирает их по номеру: «дай всё, что новее N». Каждая запись
пронумерована сквозным счётчиком, поэтому потерю (буфер переполнился, пока
консоль была закрыта) видно по разрыву номеров, а не по молчанию.

Почему буфер + опрос, а НЕ поток событий воркеров. Очередь событий держит 500
штук и при переполнении выбрасывает старые (MAX_PENDING в src/app/session.py).
Лог одной сборки — это сотни строк; пущенный туда, он вытеснил бы `progress` и
`model_ready`, и превью бы залипло. Страница опрашивает раз в секунду и только
пока консоль открыта, а закрыта она почти всегда.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Dict, List, Optional

#: Сколько записей помним. 2000 строк — это примерно одна большая сборка
#: целиком; больше держать незачем, полная история и так лежит в файле.
CAPACITY = 2000

#: Уровни, которые страница показывает по умолчанию. Остальное — чипами.
#: Совпадает с умолчанием фильтра в интерфейсе (frontend/mockup/log.js).
DEFAULT_LEVELS = ("WARNING", "ERROR", "CRITICAL")


class RingHandler(logging.Handler):
    """Хендлер-кольцо: держит последние записи и раздаёт их по номеру."""

    def __init__(self, capacity: int = CAPACITY):
        super().__init__(level=logging.DEBUG)
        self._items: deque = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._seq = 0

    def emit(self, record: logging.LogRecord) -> None:
        # Хендлер зовут из любого потока-воркера, поэтому под замком. Формат
        # сообщения считаем ЗДЕСЬ: record хранит аргументы отдельно, а к
        # моменту чтения страницей они могут быть уже изменены вызывающим.
        try:
            text = record.getMessage()
        except Exception:                                    # noqa: BLE001
            text = str(record.msg)
        if record.exc_info:
            text += "\n" + self.format_exception(record)

        with self._lock:
            self._seq += 1
            self._items.append({
                "seq": self._seq,
                "time": record.created,
                "level": record.levelname,
                # Полное имя логгера длинное («tf2_skin_generator.src.services.
                # vpk_service»); странице интересен хвост.
                "source": record.name.rsplit(".", 1)[-1],
                "text": text,
            })

    def format_exception(self, record: logging.LogRecord) -> str:
        import traceback
        return "".join(traceback.format_exception(*record.exc_info))

    def tail(self, since: int = 0, limit: int = 500) -> Dict[str, object]:
        """
        Записи новее `since`.

        `dropped` — сколько записей вытеснено из буфера между `since` и тем,
        что реально осталось. Молча отдать «дырку» нельзя: человек решит, что
        в этот момент ничего не происходило.
        """
        with self._lock:
            items: List[dict] = [e for e in self._items if e["seq"] > since]
            newest = self._seq
            oldest = self._items[0]["seq"] if self._items else newest + 1

        dropped = max(0, oldest - since - 1) if since else 0
        if len(items) > limit:
            dropped += len(items) - limit
            items = items[-limit:]
        return {"entries": items, "next": newest, "dropped": dropped}

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


#: Единственный экземпляр: логгер один на приложение, буфер тоже.
_handler: Optional[RingHandler] = None
_attach_lock = threading.Lock()


def attach(logger_name: str = "tf2_skin_generator") -> RingHandler:
    """
    Вешает кольцо на логгер приложения. Повторный вызов ничего не делает.

    Зовётся и из setup_logging (обычный запуск), и из api.log_tail — второе
    ради dev-сервера, который setup_logging не вызывает.
    """
    global _handler
    with _attach_lock:
        if _handler is None:
            _handler = RingHandler()
            logging.getLogger(logger_name).addHandler(_handler)
        return _handler


def tail(since: int = 0, limit: int = 500) -> Dict[str, object]:
    return attach().tail(since, limit)


def clear() -> None:
    attach().clear()
