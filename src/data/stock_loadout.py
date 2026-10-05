"""
Стоковое снаряжение класса: чем персонаж держит стойку в сцене «На модели».

Шапку смотрят на персонаже, а персонаж в игре не стоит с пустыми руками: у
каждого слота своя стойка (`stand_PRIMARY`, `stand_MELEE`…) и своё оружие в
руке. Что это за оружие — знает items_game: стоковые предметы помечены
`baseitem 1`, у них есть `item_slot`, `used_by_classes` и `model_player`.
Угадывать по именам файлов нельзя: топор пиро лежит в `c_fireaxe_pyro`,
набор маскировки шпиона — `w_cigarette_case`, у кулаков пулемётчика модели нет
вовсе.

Стойку задаёт не слот предмета, а его `anim_slot`, когда он есть: гранатомёт
демомана — основное оружие, но держат его анимациями вспомогательного, а
липучкомёт — наоборот.

Порядок слотов — как в раскладке игры (1, 2, 3, 4). У шпиона основного слота
нет: револьвер числится вспомогательным, вторым идёт сапёр («building»).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from src.data import items_game_kv as kv
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Слоты раскладки по порядку. `building` — только у шпиона (сапёр); у
#: инженера это ящик с инструментами, отдельного слота раскладки у него нет.
_ORDER = ("primary", "secondary", "building", "melee", "pda")

_MODEL = re.compile(r'"model_player"\s+"([^"]+)"', re.I)
_CLASS = re.compile(r'"(\w+)"\s+"1"')


@dataclass(frozen=True)
class StockWeapon:
    """Стоковое оружие слота: что держать и какой стойкой."""
    slot: str               # слот раскладки: primary / secondary / …
    anim: str               # чья стойка: PRIMARY / SECONDARY / MELEE / PDA …
    model: Optional[str]    # модель в руке; None — пустые руки (кулаки)


_cache: Dict[str, Dict[str, List[StockWeapon]]] = {}


def _parse(path: str) -> Dict[str, List[StockWeapon]]:
    game = kv.ItemsGame.load(path)
    if game is None:
        logger.warning(f"[loadout] items_game не прочитан: {path}")
        return {}
    found: Dict[str, Dict[str, StockWeapon]] = {}
    for _idx, block in game.items:
        if game.inherited(block, "baseitem") != "1":
            continue
        slot = (game.inherited(block, "item_slot") or "").lower()
        if slot not in _ORDER:
            continue
        anim = (game.inherited(block, "anim_slot") or slot).upper()
        model = game.inherited_match(block, _MODEL)
        classes = _CLASS.findall(game.inherited_block(block, "used_by_classes") or "")
        for cls in classes:
            cls = cls.lower()
            if slot == "building" and cls != "spy":
                continue
            # Первый стоковый предмет слота и есть стоковый (дубли вроде
            # второго КПК инженера идут своим слотом pda2 и сюда не попадают).
            found.setdefault(cls, {}).setdefault(slot, StockWeapon(slot, anim, model))
    return {cls: [slots[s] for s in _ORDER if s in slots]
            for cls, slots in found.items()}


def loadout(tf2_class: str, tf2_root: str) -> List[StockWeapon]:
    """Стоковые слоты класса по порядку раскладки (пусто — не нашли)."""
    path = os.path.join(tf2_root or "", "tf", "scripts", "items", "items_game.txt")
    if path not in _cache:
        _cache[path] = _parse(path)
    return list(_cache[path].get((tf2_class or "").lower(), []))
