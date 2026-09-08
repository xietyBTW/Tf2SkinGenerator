"""
Какая насмешка играет с этим реквизитом: класс и последовательность анимации.

Реквизит сам по себе почти всегда неподвижен — в его модели один кадр `@ref`.
Двигает его АНИМАЦИЯ ПЕРСОНАЖА: у модели игрока есть кости `prop_bone…`, и
одноимённые кости реквизита идут за ними (тот же приём, что у вида от первого
лица, где оружие ведут кости руки). Значит, чтобы показать насмешку, нужны три
вещи: модель класса, последовательность из модели анимаций класса и сам
реквизит.

Связку даёт items_game: у предмета-насмешки есть `custom_taunt_prop_per_class`
(модель реквизита по классам) и `custom_taunt_scene_per_class` (сцена .vcd).
Имя .vcd почти всегда совпадает с именем последовательности — `taunt_nuke.vcd`
и `$sequence "taunt_nuke"`, — но не всегда: у транспорта сцена одна на всех
(`taunt_vehicle_allclass`), а последовательности разные. Поэтому имя ищется по
кандидатам, а несколько выверенных случаев лежат в `OVERRIDES`.

Скомпилированные .vcd не читаем: они лежат в scenes.image, а нужное имя
достаётся и без них.
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Начало блока "taunt" внутри предмета. Тело берём по скобкам, а не
#: регуляркой до отступа: у Valve внутри есть вложенные блоки, и «до первой
#: закрывающей» их обрежет, а «до отступа в три табуляции» держится на том,
#: что файл не переформатируют.
_TAUNT_HEAD = re.compile(r'"taunt"\s*\{')
_PER_CLASS = r'"{key}"\s*\{{(.*?)\}}'
_PAIR = re.compile(r'"(\w+)"\s*"([^"]+)"')

#: Слова, которые ничего не говорят о самой насмешке: по ним не ищем.
_NOISE = {'taunt', 'vehicle', 'allclass', 'all', 'class', 'scene', 'player',
          'workshop', 'low', 'anim', 'animation'}

#: Хвосты завершающих кусков: `taunt_vehicle_tank_end` — это выход из
#: насмешки, а показать надо её саму.
_TAIL = ('_end', '_outro', '_exit', '_stop')

#: Выверенные вручную случаи: имя сцены на них не выводит.
#: Проверено по моделям анимаций классов (`*_animations.mdl`).
OVERRIDES: Dict[str, str] = {
    # Машинка и мопед: сцена одна на все классы, а последовательности свои.
    'bumpercar': 'taunt_vehicle_allclass_start',
    'scooter': 'taunt_vehicle_moped_start',
    # У танка своей анимации персонажа нет — водитель сидит неподвижно
    # (`a_vehicle_tank_*` это одиночные позы), а едет сам танк. Показываем
    # его собственной анимацией, без персонажа.
    'tank': '',
}

#: Разобранный items_game: {путь модели реквизита: {класс: имя сцены}}.
_cache: Dict[str, Dict[str, Dict[str, str]]] = {}


def _blocks(text: str) -> List[str]:
    """Тела всех блоков `"taunt" { … }` — по балансу скобок."""
    out: List[str] = []
    for head in _TAUNT_HEAD.finditer(text):
        depth, start = 1, head.end()
        i = start
        while i < len(text) and depth:
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
            i += 1
        if not depth:
            out.append(text[start:i - 1])
    return out


def per_class(body: str, key: str) -> Dict[str, str]:
    found = re.search(_PER_CLASS.format(key=key), body, re.S)
    return dict(_PAIR.findall(found.group(1))) if found else {}


def _parse(items_game_path: str) -> Dict[str, Dict[str, tuple]]:
    """{модель реквизита: {класс: (модель этого класса, имя сцены)}}.

    Одна насмешка описывает СРАЗУ все свои классы, поэтому каждая её модель
    ведёт на общую таблицу: выбрали другой класс — сменились и модель
    реквизита, и последовательность.
    """
    try:
        with open(items_game_path, encoding='utf-8', errors='replace') as fh:
            text = fh.read()
    except OSError as exc:
        logger.warning(f"[taunt] items_game не прочитан: {exc}")
        return {}

    out: Dict[str, Dict[str, tuple]] = {}
    for body in _blocks(text):
        props = per_class(body, 'custom_taunt_prop_per_class')
        if not props:
            continue
        scenes = per_class(body, 'custom_taunt_scene_per_class')
        table = {}
        for tf2_class, mdl in props.items():
            stem = os.path.basename(scenes.get(tf2_class, ''))
            table[tf2_class.lower()] = (mdl.replace('\\', '/').strip().lower(),
                                        stem.removesuffix('.vcd').lower())
        for mdl, _scene in table.values():
            out.setdefault(mdl, {}).update(table)
    logger.info(f"[taunt] реквизитов с насмешками: {len(out)}")
    return out


#: Одна и та же модель лежит в игре под двумя путями: своим и мастерской.
#: items_game ссылается на один из них, а таблица реквизита знает другой —
#: у гитары это `models/player/items/…` против
#: `models/workshop_partner/player/items/…`, и без подмены насмешка «не
#: находилась» у совершенно рабочего реквизита.
_SWAPS = (
    ('models/player/items/', 'models/workshop_partner/player/items/'),
    ('models/player/items/', 'models/workshop/player/items/'),
    ('models/workshop_partner/player/items/', 'models/player/items/'),
    ('models/workshop/player/items/', 'models/player/items/'),
)


def _variants(mdl_path: str) -> List[str]:
    """Тот же путь во всех известных написаниях."""
    path = (mdl_path or '').replace('\\', '/').lower()
    out = [path]
    for old, new in _SWAPS:
        if path.startswith(old):
            swapped = new + path[len(old):]
            if swapped not in out:
                out.append(swapped)
    return out


def uses(mdl_path: str, tf2_root: str) -> Dict[str, tuple]:
    """Кто играет насмешку с этим реквизитом: {класс: (модель, сцена)}."""
    from src.data.weapon_model_index import get_items_game_path

    path = get_items_game_path(tf2_root)
    if not path:
        return {}
    path = str(path)
    if path not in _cache:
        _cache[path] = _parse(path)
    for variant in _variants(mdl_path):
        found = _cache[path].get(variant)
        if found:
            return dict(found)
    return {}


def classes_for(mdl_path: str, tf2_root: str) -> List[str]:
    """Кто может играть эту насмешку. Порядок — как у классов в игре."""
    from src.data.viewmodel_anims import CLASS_MODEL_STEM

    found = uses(mdl_path, tf2_root)
    return [cls for cls in CLASS_MODEL_STEM if cls in found]


def class_from_prop(mdl_path: str) -> str:
    """
    Класс по имени файла реквизита: `…_scout.mdl` — насмешка скаута.

    Запасной путь: часть реквизита items_game не объявляет вовсе (у него нет
    предмета-насмешки в текущем файле), а имя последовательности при этом
    совпадает с именем модели. Без класса такой реквизит остался бы неподвижным.
    """
    from src.data.viewmodel_anims import CLASS_MODEL_STEM

    stem = os.path.basename((mdl_path or '').replace('\\', '/')).lower()
    stem = stem.removesuffix('.mdl')
    for tf2_class, model_stem in CLASS_MODEL_STEM.items():
        if stem.endswith('_' + tf2_class) or stem.endswith('_' + model_stem):
            return tf2_class
    return ''


def sequence_name(prop_key: str, scene_stem: str, tf2_class: str,
                  available: List[str], fuzzy: bool = True) -> Optional[str]:
    """
    Имя последовательности насмешки среди тех, что есть в модели анимаций.

    Порядок: выверенный случай → точное совпадение с именем сцены → по словам.
    Пустая строка в `OVERRIDES` означает «у персонажа этой анимации нет» и
    возвращается как None — показывать нужно сам реквизит.

    ``fuzzy=False`` оставляет только точные совпадения. Нужно, когда моделей
    анимаций несколько: похожее имя из первой не должно выигрывать у точного
    из второй.
    """
    fixed = OVERRIDES.get(prop_key)
    if fixed is not None:
        return fixed if fixed in available else None

    names = {name.lower(): name for name in available}
    for candidate in (scene_stem, f'taunt_{scene_stem}',
                      f'{scene_stem}_{tf2_class}',
                      f'taunt_{scene_stem}_{tf2_class}',
                      prop_key, f'taunt_{prop_key}'):
        if candidate and candidate in names:
            return names[candidate]

    if not fuzzy:
        return None
    words = [w for w in re.split(r'[_\-]+', scene_stem or prop_key)
             if w and w not in _NOISE]
    if not words:
        return None
    scored = []
    for low, name in names.items():
        hits = sum(1 for w in words if w in low)
        if hits:
            # Длинные имена — обычно уточнения («_layer», «_wheely»), а хвост
            # `_end` это выход из насмешки: и то и другое отодвигаем назад.
            scored.append((hits, -low.endswith(_TAIL), -len(low), name))
    if not scored:
        return None
    scored.sort(reverse=True)
    return scored[0][3]
