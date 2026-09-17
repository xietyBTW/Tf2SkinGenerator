"""
Чем вызывается система частиц: оружие, постройка, игрок, необычный эффект…

Игра такой таблицы не хранит. Она собрана скриптом
scripts/particle_sources_build.py из скриптов оружия, кода игры и дерева
PCF и лежит в particle_sources_table.py; здесь — подписи видов и перевод
токена в слова на языке интерфейса. Файлы, которых при сборке таблицы ещё
не было (новые сезонные анюжуалы), получают вид по имени файла.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from src.data.particle_sources_table import SOURCES, WEAPON_NAMES
from src.data.sound_catalog import BUILDING_TOKENS

#: Вид источника → подпись. Порядок — порядок фасета и приоритет: система,
#: которую зовёт и оружие, и правила игры, показывается как оружейная.
KIND_NAMES: Dict[str, str] = {
    'weapon': 'Оружие',
    'building': 'Постройки',
    'player': 'Игрок',
    'impact': 'Попадания и взрывы',
    'unusual': 'Анюжуалы',
    'taunt': 'Насмешки',
    'halloween': 'Хэллоуин',
    'mvm': 'MvM',
    'game': 'Режимы и правила',
    'world': 'Карты и окружение',
}

#: Имя файла PCF → вид, когда системы нет в таблице (файл новее таблицы).
_FILE_KINDS: Tuple[Tuple[str, str], ...] = (
    ('unusual', 'unusual'), ('taunt', 'taunt'), ('halloween', 'halloween'),
    ('mvm', 'mvm'), ('killstreak', 'unusual'),
)

#: Скрипты, чей `printname` в локализации не значится (остатки у Valve):
#: имя предмета по-английски, как в каталоге оружия — по нему находится
#: перевод.
_STEM_NAMES: Dict[str, str] = {
    'buff_item': 'Buff Banner', 'raygun': 'Righteous Bison',
    'flaregun_revenge': 'Manmelter', 'drg_pomson': 'Pomson 6000',
    'mechanical_arm': 'Short Circuit', 'robot_arm': 'Gunslinger',
    'jar_gas': 'Gas Passer', 'jar_milk': 'Mad Milk', 'spellbook': 'Spellbook',
    'sapper': 'Sapper', 'builder': 'Toolbox', 'parachute': 'B.A.S.E. Jumper',
    'parachute_primary': 'B.A.S.E. Jumper', 'parachute_secondary': 'B.A.S.E. Jumper',
    'invis': 'Invis Watch', 'pda_spy': 'Disguise Kit',
    'pda_engineer_build': 'Construction PDA', 'pda_engineer_destroy': 'Destruction PDA',
    'passtime_gun': 'PASS Time',
}

#: Ключ таблицы — как в файле игры; ищем без учёта регистра.
_LOWER: Dict[str, Tuple[str, ...]] = {k.lower(): v for k, v in SOURCES.items()}


def tokens_of(system: str, pcf: str = '') -> Tuple[str, ...]:
    """Токены `вид:метка` системы. Пусто — ничего не известно."""
    found = _LOWER.get((system or '').lower())
    if found:
        return found
    base = (pcf or '').rsplit('/', 1)[-1].lower()
    for word, kind in _FILE_KINDS:
        if word in base:
            return (f'{kind}:',)
    return ()


def kinds_of(system: str, pcf: str = '') -> List[str]:
    """Виды источников в порядке `KIND_NAMES`."""
    have = {t.partition(':')[0] for t in tokens_of(system, pcf)}
    return [k for k in KIND_NAMES if k in have]


def labels_of(system: str, pcf: str, loc: Dict[str, str],
              unusual_names: Optional[Dict[str, str]] = None,
              lang: str = 'ru') -> List[str]:
    """Кто зовёт систему, словами: «Огнемёт», «Турель», «Язычки пламени».

    Вид без метки словом не становится: «Оружие» как подпись у строки не
    говорит ничего сверх фасета.
    """
    out: List[str] = []
    for token in tokens_of(system, pcf):
        kind, _, label = token.partition(':')
        if not label:
            continue
        text = ''
        if kind == 'weapon':
            text = (_loc(loc, WEAPON_NAMES.get(label, ''))
                    or _catalog_name(_STEM_NAMES.get(label, ''), lang)
                    or label.replace('_', ' '))
        elif kind == 'building':
            text = _loc(loc, BUILDING_TOKENS.get(label, ''))
        elif kind == 'unusual':
            text = (unusual_names or {}).get(label, '')
        if text and text not in out:
            out.append(text)
    return out


def _catalog_name(english: str, lang: str) -> str:
    """Имя предмета на языке интерфейса по его английскому имени в каталоге."""
    if not english:
        return ''
    from src.data.weapons import TF2_WEAPONS

    for slots in TF2_WEAPONS.values():
        for weapons in slots.values():
            for names in weapons.values():
                if isinstance(names, dict) and names.get('en') == english:
                    return names.get(lang, english)
    return english


def _loc(loc: Dict[str, str], token: str) -> str:
    token = (token or '').lstrip('#')
    if not token:
        return ''
    return loc.get(token, loc.get(token.lower(), ''))
