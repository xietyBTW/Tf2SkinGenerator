"""
Краски игры: банки из items_game.txt с цветом и именем из локализации.

Список нужен превью шапки: две трети косметики красится по альфа-маске
текстуры (см. services/vmt_tint), и что именно закрасится у своей текстуры,
автор иначе видит только в игре. Игра хранит краски предметами-инструментами
(`paint_can`) с атрибутами `set item tint RGB` и, у командных, `… RGB 2`.
"""

import re
from typing import Dict, List, Tuple

from src.data import items_game_kv as kv

_TINT = re.compile(r'"set item tint RGB"\s*\{[^}]*"value"\s*"([\d.]+)"')
_TINT2 = re.compile(r'"set item tint RGB 2"\s*\{[^}]*"value"\s*"([\d.]+)"')


def _rgb(value: str) -> Tuple[int, int, int]:
    n = int(float(value))
    return (n >> 16) & 255, (n >> 8) & 255, n & 255


def parse(items_game_text: str, loc: Dict[str, str]) -> List[dict]:
    """
    Краски: [{key, name, red, blu}], цвета — (r, g, b); у обычной краски
    red == blu. Порядок — как в файле (порядок выпуска).
    """
    game = kv.ItemsGame.parse(items_game_text)
    out: List[dict] = []
    for defindex, block in game.items:
        if 'paint_can' not in (kv.flat_value(block, 'prefab') or ''):
            continue
        attrs = game.inherited_block(block, 'attributes') or ''
        one = _TINT.search(attrs)
        if not one:
            continue
        two = _TINT2.search(attrs)
        token = (kv.flat_value(block, 'item_name') or '').lstrip('#')
        name = loc.get(token) or loc.get(token.lower()) or kv.flat_value(block, 'name') or defindex
        red = _rgb(one.group(1))
        out.append({'key': defindex, 'name': name, 'red': red,
                    'blu': _rgb(two.group(1)) if two else red})
    return out
