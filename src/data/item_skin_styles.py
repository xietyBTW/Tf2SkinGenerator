"""
Предметы, которые берут у общей модели не нулевую строку скина

«Критокола» - та же модель, что «Бонк! Атомный залп» (`c_energy_drink`), но
с `"visuals" { "skin" "2" }`: фиолетовая банка - строка 2 её таблицы
скинов. В QC об этом ничего нет, там строка просто «Skin 2», а такие
безымянные строки в полосу стилей не попадают (у тел персонажей это
служебные скины). Имя строке даёт только items_game - он здесь и читается

Публичное API:
  item_skin_styles(tf2_root) -> {стебель модели: {строка скина: токен имени}}
  styled_skins(weapon_key, tf2_root, lang) -> [(имя, строка скина), ...]
"""

import os
import re
from functools import lru_cache
from typing import Dict, List, Tuple

from src.data.weapon_model_index import get_items_game_path

_SLOTS = frozenset({"primary", "secondary", "melee", "pda", "pda2", "building"})
_MODEL_RE = re.compile(r'"model_player"\s+"([^"]+\.mdl)"', re.I)
_SKIN_RE = re.compile(r'"skin"\s+"(\d+)"')


def item_skin_styles(tf2_root: str) -> Dict[str, Dict[int, str]]:
    """{стебель модели: {строка скина: токен имени предмета}}; первым
    выигрывает меньший индекс предмета (обычный раньше редких вариантов)"""
    path = get_items_game_path(tf2_root)
    if path is None:
        return {}
    st = os.stat(path)
    return _parse(str(path), st.st_mtime_ns, st.st_size)


@lru_cache(maxsize=2)
def _parse(path: str, _mtime_ns: int, _size: int) -> Dict[str, Dict[int, str]]:
    from src.data.items_game_kv import ItemsGame, flat_value

    game = ItemsGame.load(path)
    out: Dict[str, Dict[int, str]] = {}
    if game is None:
        return out
    for _idx, block in game.items:
        if (game.inherited(block, "item_slot") or "").lower() not in _SLOTS:
            continue
        skin = _SKIN_RE.search(game.inherited_block(block, "visuals") or "")
        model = game.inherited_match(block, _MODEL_RE)
        if not skin or skin.group(1) == "0" or not model:
            continue
        stem = os.path.splitext(os.path.basename(model.replace("\\", "/")))[0].lower()
        token = (flat_value(block, "item_name") or flat_value(block, "name") or "").lstrip("#")
        out.setdefault(stem, {}).setdefault(int(skin.group(1)), token)
    return out


def styled_skins(weapon_key: str, tf2_root: str, lang: str = "en") -> List[Tuple[str, int]]:
    """Строки скина этой модели, у которых есть свой предмет: [(имя, строка)]"""
    from src.data.hats_parser import parse_localization

    rows = item_skin_styles(tf2_root).get((weapon_key or "").lower())
    if not rows:
        return []
    loc = parse_localization(tf2_root, "russian" if lang == "ru" else "english")
    return [(loc.get(token) or loc.get(token.lower()) or token, skin)
            for skin, token in sorted(rows.items())]
