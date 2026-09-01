"""
Примитивы разбора items_game.txt (формат Valve KeyValues).

Файл на 8 МБ описывает все предметы игры и читается уже двумя потребителями:
шапками ([hats_parser]) и анимациями вьюмодели ([viewmodel_anims]). Общее у них
— именно разбор: найти секцию нужного уровня, отсчитать блок по скобкам, взять
плоское значение.

Отдельная тема — `prefab`. Значительная часть предметов не объявляет свои
свойства, а наследует их: у стокового оружия и `model_player`, и `item_class`
живут в prefab-блоке, а не в самом предмете. Наследование бывает многоуровневым
и с несколькими prefab через пробел, поэтому его разрешает `ItemsGame.inherited`,
а не вызывающий код.

Модуль без Qt и без зависимости от путей: на вход — текст файла.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Tuple

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Ограничитель глубины наследования prefab — защита от циклов в чужом файле.
MAX_PREFAB_DEPTH = 8


def skip_to_close_brace(content: str, pos: int) -> int:
    """
    Начиная с pos (на символе '{'), возвращает позицию ПОСЛЕ закрывающей '}'.
    Корректно обрабатывает вложенные блоки, строки в кавычках и комментарии.
    """
    depth = 0
    i = pos
    n = len(content)
    while i < n:
        c = content[i]
        if c == '"':
            i += 1
            while i < n:
                if content[i] == '\\':
                    i += 2
                    continue
                if content[i] == '"':
                    i += 1
                    break
                i += 1
        elif c == '{':
            depth += 1
            i += 1
        elif c == '}':
            depth -= 1
            i += 1
            if depth == 0:
                return i
        elif c == '/' and i + 1 < n and content[i + 1] == '/':
            nl = content.find('\n', i)
            i = nl + 1 if nl != -1 else n
        else:
            i += 1
    return i


def flat_value(block: str, key: str) -> Optional[str]:
    """Значение "key" "value" (не вложенное) из блока."""
    m = re.search(rf'"{re.escape(key)}"\s+"([^"]*)"', block, re.IGNORECASE)
    return m.group(1) if m else None


def find_section(content: str, name: str) -> int:
    """
    Позиция '{' секции `name` — прямого потомка корневого "items_game".

    Ищет именно на первом уровне вложенности: секции с теми же именами
    встречаются и глубже, и наивный `find` берёт не ту.

    Returns:
        Позиция '{' или -1.
    """
    root_idx = content.find('"items_game"')
    if root_idx == -1:
        logger.warning("items_game: корневая секция не найдена")
        return -1
    root_brace = content.find('{', root_idx + len('"items_game"'))
    if root_brace == -1:
        return -1

    pos, depth, n = root_brace + 1, 1, len(content)
    while pos < n and depth > 0:
        c = content[pos]
        if c == '"':
            pos += 1
            key_start = pos
            while pos < n:
                if content[pos] == '\\':
                    pos += 2
                    continue
                if content[pos] == '"':
                    break
                pos += 1
            else:
                break
            key = content[key_start:pos]
            pos += 1
            if depth == 1 and key == name:
                while pos < n and content[pos] in ' \t\r\n':
                    pos += 1
                if pos < n and content[pos] == '{':
                    return pos
                # После ключа нет '{' — это значение, а не секция.
        elif c == '{':
            depth += 1
            pos += 1
        elif c == '}':
            depth -= 1
            pos += 1
        elif c == '/' and content[pos + 1:pos + 2] == '/':
            nl = content.find('\n', pos)
            pos = nl + 1 if nl != -1 else n
        else:
            pos += 1
    return -1


def iter_blocks(content: str, section_brace: int) -> Iterator[Tuple[str, str]]:
    """(ключ, текст блока) для прямых потомков секции, открытой в section_brace."""
    if section_brace < 0:
        return
    pos, n = section_brace + 1, len(content)
    while pos < n:
        while pos < n and content[pos] in ' \t\r\n':
            pos += 1
        if pos >= n or content[pos] == '}':
            return
        if content[pos] == '/' and content[pos + 1:pos + 2] == '/':
            nl = content.find('\n', pos)
            pos = nl + 1 if nl != -1 else n
            continue
        if content[pos] != '"':
            pos += 1
            continue
        key_end = content.find('"', pos + 1)
        if key_end == -1:
            return
        key = content[pos + 1:key_end]
        pos = key_end + 1
        while pos < n and content[pos] in ' \t\r\n':
            pos += 1
        if pos >= n or content[pos] != '{':
            continue                       # это значение, а не блок
        end = skip_to_close_brace(content, pos)
        yield key, content[pos:end]
        pos = end


@dataclass
class ItemsGame:
    """Разобранный items_game.txt: блоки предметов и prefab для наследования."""

    items: List[Tuple[str, str]]
    prefabs: Dict[str, str]

    @classmethod
    def parse(cls, content: str) -> "ItemsGame":
        prefabs = dict(iter_blocks(content, find_section(content, "prefabs")))
        items = list(iter_blocks(content, find_section(content, "items")))
        logger.info(f"items_game: {len(items)} предметов, {len(prefabs)} prefab")
        return cls(items=items, prefabs=prefabs)

    def inherited(self, block: str, key: str) -> Optional[str]:
        """Плоское значение с учётом цепочки prefab. Своё значение сильнее."""
        return self._inherited(block, key, 0)

    def inherited_block(self, block: str, key: str) -> Optional[str]:
        """Текст вложенного блока "key" { … } с учётом цепочки prefab.

        Нужно для `model_player_per_class`: у части оружия (Хандзо, Ускоритель)
        модели объявлены не одним путём, а картой «класс → модель».
        """
        return self._inherited_block(block, key, 0)

    def inherited_match(self, block: str, pattern: re.Pattern) -> Optional[str]:
        """Первая группа регулярки с учётом цепочки prefab.

        Нужно там, где ключ не фиксирован: `model_player`, `model_player_per_class`
        и т. п. описывают одно и то же и подхватываются одним шаблоном.
        """
        return self._inherited_match(block, pattern, 0)

    # ── Внутреннее ────────────────────────────────────────────────────────── #

    def _inherited(self, block: str, key: str, depth: int) -> Optional[str]:
        own = flat_value(block, key)
        if own or depth >= MAX_PREFAB_DEPTH:
            return own
        for name in (flat_value(block, "prefab") or "").split():
            parent = self.prefabs.get(name)
            if parent is None:
                continue
            found = self._inherited(parent, key, depth + 1)
            if found:
                return found
        return None

    def _inherited_block(self, block: str, key: str, depth: int) -> Optional[str]:
        start = block.find(f'"{key}"')
        if start != -1:
            brace = block.find('{', start)
            if brace != -1:
                return block[brace:skip_to_close_brace(block, brace)]
        if depth >= MAX_PREFAB_DEPTH:
            return None
        for name in (flat_value(block, "prefab") or "").split():
            parent = self.prefabs.get(name)
            if parent is None:
                continue
            found = self._inherited_block(parent, key, depth + 1)
            if found:
                return found
        return None

    def _inherited_match(self, block: str, pattern: re.Pattern,
                         depth: int) -> Optional[str]:
        m = pattern.search(block)
        if m:
            return m.group(1)
        if depth >= MAX_PREFAB_DEPTH:
            return None
        for name in (flat_value(block, "prefab") or "").split():
            parent = self.prefabs.get(name)
            if parent is None:
                continue
            found = self._inherited_match(parent, pattern, depth + 1)
            if found:
                return found
        return None
