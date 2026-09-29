"""
Раскладка War Paint по деталям: какой слой узора лежит на какой детали.

Два режима, одна картина для страницы:

* ``parts`` — у оружия нет своих War Paint. Детали — части модели или острова
  развёртки (paintkit_generic.units_for), слои раздаёт автомат по площади.
* ``groups`` — War Paint свой, игровой. Детали — группы маски Valve
  (``p_<пушка>_groups``), слой выбирает их переменными
  ``texture_layer_N_select_k`` (значение — номер группы · 16).

Слой 0 везде значит «основа»: первый слой обычного шаблона (лежит всюду, где
не выбран другой) или сама текстура пушки у шаблона «поверх альбедо».
Раскладка человека — ``{ключ детали: слой}``; деталей, которых в ней нет,
касается автомат (или раскладка самого War Paint).
"""

from __future__ import annotations

import hashlib
import os
from typing import Dict, List, Optional, Sequence

import numpy as np

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: У слоя десять ячеек select — больше групп игра одному слою не выберет.
SELECT_SLOTS = 10


def _num(value) -> int:
    try:
        return int(float(str(value).split()[0]))
    except (ValueError, IndexError):
        return 0


def _paint_layers(layers: Sequence[int], over_albedo: bool) -> List[int]:
    """Слои, которые выбирают группы (основа обычного шаблона не выбирает)."""
    return list(layers) if over_albedo else list(layers[1:])


def own_groups(values: Dict[str, str], layers: Sequence[int],
               over_albedo: bool) -> Dict[int, int]:
    """Группа → слой, как их раскладывает сам War Paint. Позже — поверх, как в lerp."""
    out: Dict[int, int] = {}
    for layer in _paint_layers(layers, over_albedo):
        for k in range(1, SELECT_SLOTS + 1):
            group = round(_num(values.get(f'texture_layer_{layer}_select_{k}')) / 16.0)
            if group:
                out[group] = layer
    return out


def own_forced(original: Dict[int, int], assign: Optional[Dict[str, int]],
               layers: Sequence[int], over_albedo: bool) -> Dict[str, str]:
    """Переменные select под раскладку человека (``{'g3': слой}``); пусто — не трогать."""
    allowed = set(layers) | {0}
    final = dict(original)
    touched = False
    for key, layer in (assign or {}).items():
        if key.startswith('g') and key[1:].isdigit() and int(layer) in allowed:
            final[int(key[1:])] = int(layer)
            touched = True
    if not touched:
        return {}
    forced: Dict[str, str] = {}
    for layer in _paint_layers(layers, over_albedo):
        # ponytail: лишние группы сверх десяти у слоя отбрасываются — так же
        # поступила бы игра; на пушках Valve групп меньше.
        groups = sorted(g for g, got in final.items() if got == layer)[:SELECT_SLOTS]
        for k in range(1, SELECT_SLOTS + 1):
            forced[f'texture_layer_{layer}_select_{k}'] = (
                str(groups[k - 1] * 16) if k <= len(groups) else '0')
    return forced


def _swatch(loader, path: str, out_dir: str) -> Dict[str, str]:
    """Плитка узора слоя (96 px) и его средний цвет."""
    rgba = loader(path) if path else None
    if rgba is None:
        return {'swatch': '', 'color': '#808080'}
    from PIL import Image
    name = hashlib.sha1(path.lower().encode('utf-8')).hexdigest()[:12]
    out = os.path.join(out_dir, f'warpaint_layer_{name}.png')
    if not os.path.isfile(out):
        os.makedirs(out_dir, exist_ok=True)
        Image.fromarray(np.ascontiguousarray(rgba), 'RGBA').convert('RGB') \
            .resize((96, 96), Image.LANCZOS).save(out)
    mean = rgba[..., :3].reshape(-1, 3).mean(axis=0)
    return {'swatch': out, 'color': '#' + ''.join(f'{int(v):02x}' for v in mean)}


def describe(defs, kit, item, parts_model, obj_material: str, own: bool,
             loader, swatch_loader, swatch_dir: str,
             assign: Optional[Dict[str, int]] = None, layout_seed: int = 0) -> dict:
    """
    Раскладка для страницы: слои (с плитками узоров), детали с их слоем и
    карта «треугольник → деталь» для вьювера. ``{'error': …}`` — раскладывать
    нечего.

    ``loader`` читает маску групп (raw), ``swatch_loader`` — узоры для плиток.
    """
    from src.data.paintkit_defs import template_layers
    from src.services.paintkit_generic import assign_layers, units_for, valve_units

    layers, over_albedo = template_layers(defs, kit)
    found = defs.variables(kit, item, 1) if layers else None
    if not found:
        return {'error': 'Этот War Paint нарисован под одну пушку — его детали не переложить'}
    _op, values = found

    if own:
        mask = loader(values.get('weapon_groups', ''), raw=True)
        if mask is None:
            return {'error': 'В игре нет маски групп этой пушки'}
        units = valve_units(parts_model, obj_material, mask)
        original = own_groups(values, layers, over_albedo)
        auto = [original.get(int(u.key[1:]), 0) for u in units]
    else:
        units = units_for(parts_model, obj_material, len(layers))
        auto = assign_layers([u.area for u in units], layers, over_albedo, layout_seed)
    if not units:
        return {'error': 'У модели нет развёртки — War Paint положить некуда'}

    allowed = set(layers) | {0}
    total = sum(u.area for u in units) or 1.0
    tri_unit: List[Optional[int]] = [None] * len((parts_model.uv or {}).get(obj_material) or [])
    out_units = []
    for i, (unit, default) in enumerate(zip(units, auto)):
        chosen = (assign or {}).get(unit.key)
        manual = chosen is not None and int(chosen) in allowed
        out_units.append({'key': unit.key, 'area': round(unit.area / total, 4),
                          'layer': int(chosen) if manual else int(default),
                          'auto': int(default), 'manual': manual})
        for tri in unit.tris:
            if tri < len(tri_unit):
                tri_unit[tri] = i

    out_layers = [{'n': 0, 'base': True,
                   **(_swatch(swatch_loader, values.get(f'texture_layer_{layers[0]}', ''),
                              swatch_dir) if not over_albedo
                      else {'swatch': '', 'color': '#6b6b6b'})}]
    for layer in _paint_layers(layers, over_albedo):
        out_layers.append({'n': layer, 'base': False,
                           **_swatch(swatch_loader, values.get(f'texture_layer_{layer}', ''),
                                     swatch_dir)})
    return {'mode': 'groups' if own else 'parts', 'over_albedo': over_albedo,
            'layers': out_layers, 'units': out_units, 'tri_unit': tri_unit}
