"""
Необычные эффекты игры: какая система частиц как называется.

В items_game лежит таблица `attribute_controlled_attached_particles`: номер
эффекта, имя системы частиц и где она крепится. Имя, которое видит игрок
(«Burning Flames»), даёт локализация по токену `Attrib_Particle<номер>`.
Это единственная связка «имя в игре → система → файл PCF», и без неё
эффект приходится искать по 134 файлам, зная рабочее имя Valve
(`superrare_burning1`).
"""

from __future__ import annotations

import re
from typing import Dict, List

#: Подраздел таблицы → категория. Ключ уходит в фильтр, подпись — человеку.
CATEGORIES: Dict[str, str] = {
    'cosmetic_unusual_effects': 'cosmetic',
    'weapon_unusual_effects': 'weapon',
    'taunt_unusual_effects': 'taunt',
    'killstreak_eyeglows': 'killstreak',
    'other_particles': 'other',
}

CATEGORY_NAMES: Dict[str, str] = {
    'cosmetic': 'Косметика', 'weapon': 'Оружие', 'taunt': 'Насмешки',
    'killstreak': 'Килстрик', 'other': 'Прочее',
}

_HEAD = '"attribute_controlled_attached_particles"'
_BRACE = re.compile(r'[{}]')
#: Подраздел: имя в кавычках и открывающая скобка.
_SUB = re.compile(r'"([a-z_]+)"\s*\{')
#: Запись эффекта: номер и тело без вложенных скобок.
_ENTRY = re.compile(r'"(\d+)"\s*\{([^{}]*)\}')
_SYSTEM = re.compile(r'"system"\s+"([^"]+)"')


def _block(text: str) -> str:
    """Тело таблицы по балансу скобок. Пусто — таблицы нет."""
    start = text.find(_HEAD)
    if start < 0:
        return ''
    first = text.find('{', start)
    depth = 0
    for brace in _BRACE.finditer(text, first):
        depth += 1 if brace.group() == '{' else -1
        if not depth:
            return text[first + 1:brace.start()]
    return ''


def parse(items_game_text: str, loc: Dict[str, str]) -> List[dict]:
    """[{id, system, name, category}] — эффекты с именами из локализации.

    Без имени эффект тоже остаётся: у полусотни записей токена в
    локализации нет (служебные, вроде `burningplayer_red`), но система у
    них настоящая, и найти её по рабочему имени должно быть можно.
    """
    body = _block(items_game_text)
    out: List[dict] = []
    pos = 0
    for sub in _SUB.finditer(body):
        if sub.start() < pos:
            continue
        depth, end = 0, len(body)
        for brace in _BRACE.finditer(body, sub.end() - 1):
            depth += 1 if brace.group() == '{' else -1
            if not depth:
                end = brace.start()
                break
        category = CATEGORIES.get(sub.group(1), 'other')
        for entry in _ENTRY.finditer(body, sub.end(), end):
            system = _SYSTEM.search(entry.group(2))
            if not system:
                continue
            num = int(entry.group(1))
            token = f'Attrib_Particle{num}'
            out.append({
                'id': num,
                'system': system.group(1),
                'name': loc.get(token, loc.get(token.lower(), '')),
                'category': category,
            })
        pos = end
    return out
