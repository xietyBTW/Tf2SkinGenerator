"""
Записи покраски частей: один вид на всё приложение.

Цвет части и картинки на ней за время жизни фичи хранились тремя способами:
цвет — строкой «#rrggbb» или словарём с градиентом, картинка — строкой-путём,
словарём с посадкой или списком таких словарей. Настройки кисти (сила, точный
цвет, окантовка) у старых записей не хранились вовсе и подставлялись «нынешние»
при каждом чтении.

Теперь запись приводится к ОДНОМУ виду на входе — когда приходит со страницы и
когда работа возвращается с диска — и дальше её читают как есть. Вид
JSON-родной (списки, а не кортежи): тот же словарь уходит в работу на диске и в
снимки отмены, и сравнивается с ними без перевода.

Здесь же — ключ слота (карточка плюс стиль или команда) и перевод работ,
записанных до того, как основа склейки стала храниться явно.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

from src.shared.constants import Team

#: Настройки кисти, которые старые записи не хранили: подставляются из работы.
BRUSH_DEFAULTS = {'strength': 1.0, 'exact': False, 'edge': 0.0, 'edge_color': None}

_FITS = ('contain', 'cover', 'stretch')


def fraction(value: Any, default: float) -> float:
    """Доля 0..1 из того, что прислала страница. Мусор — умолчание."""
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return default


def _anchor(value: Any) -> Optional[List[float]]:
    """Габарит (u0, v0, u1, v1). Мусор — как будто его нет."""
    try:
        u0, v0, u1, v1 = (float(x) for x in value)
    except (TypeError, ValueError):
        return None
    return [u0, v0, u1, v1] if u1 > u0 and v1 > v0 else None


def color_spec(value: Any, brush: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Цвет части полной записью.

    Строка «#rrggbb» — старая работа: градиента нет, а настройки кисти берутся
    из `brush` (те, что работа помнила на момент записи). Флаг `horizontal`
    из ещё более старых работ переводится в угол: 90° — слева направо.
    """
    at = {**BRUSH_DEFAULTS, **(brush or {})}
    raw = value if isinstance(value, dict) else {'color': value}

    def kept(name: str) -> Any:
        got = raw.get(name)
        return at[name] if got is None else got

    angle = raw.get('angle')
    if angle is None:
        angle = 90.0 if raw.get('horizontal') else 0.0
    return {
        'color': str(raw.get('color') or ''),
        'color2': str(raw['color2']) if raw.get('color2') else None,
        'angle': float(angle),
        # Настройки кисти в момент мазка: переключатель кисти задним числом
        # уже покрашенное не меняет.
        'strength': float(kept('strength')),
        'exact': bool(kept('exact')),
        'edge': float(kept('edge')),
        'edge_color': kept('edge_color') or None,
        # Края и середина перехода: у обычного градиента — от края до края.
        'start': fraction(raw.get('start'), 0.0),
        'end': fraction(raw.get('end'), 1.0),
        'mid': fraction(raw.get('mid'), 0.5),
    }


def image_spec(value: Any, brush: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Картинка части полной записью: путь и посадка.

    Умолчание посадки — 'contain': растяжение по прямоугольнику корёжило
    логотипы, а заметно это становилось только в игре.
    """
    at = {**BRUSH_DEFAULTS, **(brush or {})}
    raw = value if isinstance(value, dict) else {'path': value}
    offset = raw.get('offset') or (0.0, 0.0)
    fit = str(raw.get('fit') or 'contain')
    scale = raw.get('scale') or 1.0
    return {
        'path': str(raw.get('path') or ''),
        'fit': fit if fit in _FITS else 'contain',
        'angle': float(raw.get('angle') or 0.0),
        # Ноль и отрицательный масштаб — это исчезнувшая картинка; такой
        # «результат» человек примет за поломку, а не за свою настройку.
        'scale': max(0.05, min(20.0, float(scale))),
        # По высоте — свой множитель; нет его — равен ширинному.
        'scale_y': max(0.05, min(20.0, float(raw.get('scale_y') or scale))),
        'offset': [float(offset[0]), float(offset[1])],
        # Отражение по своим осям картинки: тянут сторону рамки за
        # противоположную — картинка переворачивается, как в редакторах.
        'flip_x': bool(raw.get('flip_x')),
        'flip_y': bool(raw.get('flip_y')),
        # Габарит части, в который картинку вписали изначально: после разреза
        # наклейка остаётся на месте развёртки, а не рисуется в каждой половине.
        'anchor': _anchor(raw.get('anchor')),
        'edge': float(raw['edge'] if raw.get('edge') is not None else at['edge']),
        'edge_color': raw.get('edge_color') or at['edge_color'] or None,
    }


def image_list(value: Any, brush: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Картинки части списком, снизу вверх. Одна запись могла быть не списком."""
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    return [image_spec(v, brush) for v in items if v]


# ── Слот: чей это набор мазков ───────────────────────────────────────────── #

def slot_key(card: str, style: int = 0, blu: bool = False) -> str:
    """Ключ хранения покраски: карточка плюс стиль (`@style1`) или синяя
    команда (`@blu`). Старые работы без суффикса читаются как базовые."""
    if style:
        return f"{card}@style{int(style)}"
    return f"{card}@blu" if blu else card


def parse_slot(key: str) -> Tuple[str, int, str]:
    """(карточка, стиль, команда) из ключа хранения покраски."""
    card, sep, tail = key.partition('@')
    if not sep:
        return key, 0, Team.RED
    if tail.startswith('style'):
        return card, int(tail[5:] or 0), Team.RED
    if tail == 'blu':
        return card, 0, Team.BLU
    return key, 0, Team.RED


# ── Работы до явной основы ───────────────────────────────────────────────── #

#: Как называются склейки: `parts_<номер>.png`, а `work_store` дописывает хвост
#: `_<номер>`, когда рядом лежит одноимённый файл другого материала. Нужно ТОЛЬКО
#: для работ, записанных до `part_bases`: там «склейка это или своя текстура
#: человека» можно было понять лишь по имени.
COMPOSITE_NAME = re.compile(r'^parts_\d+(?:_\d+)*\.png$', re.IGNORECASE)


def is_composite_name(path: str) -> bool:
    """Похож ли файл на склейку частей."""
    return bool(COMPOSITE_NAME.match(os.path.basename(path or '')))


def migrate_part_bases(textures: Dict[str, Dict[str, str]],
                       skin_overrides: Dict[int, Dict[str, str]],
                       painted: set) -> Dict[str, str]:
    """
    Основы склеек для работы, записанной до того, как их стали хранить.

    Возвращает {слот: своя текстура под мазками или '' — игровая}. Слот без
    мазков, на котором висит склейка (осталась, когда «Убрать всё» когда-то не
    сработало), чистится здесь же: мазков нет — и склейке быть не с чего.
    """
    bases: Dict[str, str] = {}
    for slot in painted:
        card, style, team = parse_slot(slot)
        where = skin_overrides.get(style, {}) if style else textures.get(team, {})
        current = where.get(card)
        # Своя текстура поверх мазков — её клали после покраски. Показанной она
        # и останется до следующего мазка, а он ляжет уже поверх неё.
        bases[slot] = current if current and not is_composite_name(current) else ''

    owners = {parse_slot(slot)[0] for slot in painted}
    for by_mat in [*textures.values(), *skin_overrides.values()]:
        for mat, path in list(by_mat.items()):
            if mat not in owners and path and is_composite_name(path):
                del by_mat[mat]
    return bases
