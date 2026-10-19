"""
История правок предмета: снимки `user_edits()` и позиция в них (Ctrl+Z / Ctrl+Y).

Одна на всё — текстуры, части, свою модель, карты: красят и подставляют на
ощупь, и «попробовал, не понравилось» должно откатываться, иначе человек
боится трогать. Здесь только стек: что в нём лежит и куда можно шагнуть.
Как снимок ложится обратно на предмет (геометрия, склейки частей, небо) -
дело сеанса (`AppSession.undo_edits`).
"""

from __future__ import annotations

import copy
import os
import shutil
from typing import Any, Callable, Dict, List, Optional

from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def _in_work_dir(path: str) -> bool:
    """Лежит ли путь в папке сохранённых работ (Windows регистр не различает)."""
    from src.services.work_store import WORK_DIR
    try:
        root = os.path.normcase(str(WORK_DIR.resolve())) + os.sep
        return os.path.normcase(os.path.abspath(path)).startswith(root)
    except (OSError, ValueError):
        return False


class EditHistory:
    """Снимки правок одного предмета (или эффекта) и позиция в них."""

    #: Глубже тридцати шагов не помнит никто.
    LIMIT = 30

    def __init__(self, work_dir: Callable[[], str] = lambda: '',
                 limit: int = LIMIT) -> None:
        #: Временная папка сеанса: туда - копии файлов работы для снимков.
        self._work_dir = work_dir
        self.limit = limit
        self._snaps: List[Dict[str, Any]] = []
        self.pos = -1
        #: {путь в папке работы|размер|время: своя копия} — см. `_shield`.
        self._copies: Dict[str, str] = {}
        #: Снимок, который сейчас на диске (см. `mark_saved`).
        self._saved: Optional[Dict[str, Any]] = None

    def __len__(self) -> int:
        return len(self._snaps)

    def snapshot(self, edits: Dict[str, Any]) -> Dict[str, Any]:
        """Снимок правок — то же, что уходит на диск, своей копией."""
        return self._shield(copy.deepcopy(edits))

    def reset(self, snap: Optional[Dict[str, Any]]) -> None:
        """Точка отсчёта: предмет открыт (с работой или без). Раньше неё
        откатываться нельзя — там правки другого предмета. None - снимать
        нечего: история пуста. Открытое считается сохранённым."""
        self._snaps = [] if snap is None else [snap]
        self.pos = len(self._snaps) - 1
        self.mark_saved()

    def mark_saved(self) -> None:
        """Текущее состояние - на диске. Помним сам снимок, а не номер шага:
        номера сдвигаются, когда история упирается в лимит."""
        self._saved = self.at(self.pos)

    @property
    def unsaved(self) -> bool:
        """Есть правки, которых нет ни в одном сохранённом состоянии."""
        return self.at(self.pos) is not self._saved

    def commit(self, snap: Dict[str, Any]) -> None:
        """Шаг истории после правки. Снимок, равный текущему, не дублируем:
        часть правок пишет состояние дважды (положил текстуру и тут же
        пересобрал склейку), и Ctrl+Z на них был бы холостым."""
        if self._snaps and snap == self._snaps[self.pos]:
            return
        del self._snaps[self.pos + 1:]
        self._snaps.append(snap)
        if len(self._snaps) > self.limit:
            self._snaps.pop(0)
        self.pos = len(self._snaps) - 1

    def state(self) -> Dict[str, bool]:
        """Есть ли куда откатываться и что возвращать."""
        return {'undo': self.pos > 0,
                'redo': 0 <= self.pos < len(self._snaps) - 1}

    def at(self, pos: int) -> Optional[Dict[str, Any]]:
        """Снимок шага `pos`; None - такого шага нет."""
        return self._snaps[pos] if 0 <= pos < len(self._snaps) else None

    def move_to(self, pos: int) -> None:
        self.pos = pos

    def refresh(self, pos: int, snap: Dict[str, Any]) -> None:
        """Снимок шага `pos` узнаёт новые имена файлов (пересобранные
        склейки), иначе следующая правка легла бы в историю дважды."""
        if 0 <= pos < len(self._snaps):
            self._snaps[pos] = snap

    def _shield(self, node: Any) -> Any:
        """
        Пути в папку работы заменяет своими копиями.

        Вернувшаяся с диска работа ссылается в `work/<ключ>/files`, а
        автосохранение при каждой записи убирает оттуда всё, на что правки
        больше не ссылаются (и всю папку, когда правок не осталось). Снимку
        истории эти файлы ещё нужны: сняли текстуру — Ctrl+Z обязан её
        вернуть. Копия делается один раз на файл и живёт с сеансом.
        """
        if isinstance(node, dict):
            return {k: self._shield(v) for k, v in node.items()}
        if isinstance(node, list):
            return [self._shield(v) for v in node]
        if not isinstance(node, str) or not _in_work_dir(node):
            return node
        try:
            stat = os.stat(node)
        except OSError:
            return node
        # Ключ — вместе с размером и временем: под тем же именем в папке
        # работы позже может лежать другой файл, и старая копия соврала бы.
        key = f"{node}|{stat.st_size}|{stat.st_mtime_ns}"
        owned = self._copies.get(key)
        if owned is None:
            owned = os.path.join(self._work_dir(),
                                 f"undo_{len(self._copies)}_{os.path.basename(node)}")
            try:
                shutil.copy2(node, owned)
            except OSError as exc:
                logger.warning(f"копия для отмены не сделана: {exc}")
                return node
            self._copies[key] = owned
        return owned
