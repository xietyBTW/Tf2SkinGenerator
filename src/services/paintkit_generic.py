"""
War Paint на оружии, для которого в игре War Paint нет.

Рецепту War Paint от пушки нужны четыре картинки в её развёртке: альбедо
(«голый металл» под краской), маска групп (какой узор на какую деталь), маска
износа (где краска стирается первой) и AO (затенение щелей). У пушек War
Paint их рисовал художник Valve (`p_<пушка>_albedo/_groups/_wearblend/_ao`).
Здесь они строятся из самой модели:

* группы — части модели (куски геометрии, как их видит человек, с разрезами
  из редактора частей), раздаются по слоям узора от крупной к мелкой;
* износ — расстояние до края детали на развёртке: края стираются первыми,
  как у настоящих масок Valve;
* AO — мягкое затенение по локальному контрасту текстуры (альбедо и так
  несёт запечённый свет, сильный AO затемнил бы её второй раз);
* альбедо — игровая текстура пушки: под стёртой краской видна она.

Результат — словарь «виртуальных» текстур для загрузчика компоновщика и
значения переменных рецепта, которые на них указывают.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Имена виртуальных текстур (их отдаёт загрузчик, в VPK таких нет).
GEN = '__generated__/'


@dataclass
class GenericInputs:
    textures: Dict[str, np.ndarray]      # имя → RGBA uint8
    forced: Dict[str, str]               # переменные рецепта
    #: Номер части → слой узора (для подсказки человеку).
    assignment: Dict[int, int]


def _rasterize(polys_by_value: Sequence[Tuple[int, List]], size: int) -> np.ndarray:
    """Треугольники развёртки → карта значений (0 — вне развёртки)."""
    from PIL import Image, ImageDraw

    img = Image.new('L', (size, size), 0)
    draw = ImageDraw.Draw(img)
    for value, tris in polys_by_value:
        for tri in tris:
            # v вверх у SMD/OBJ; строка картинки — сверху вниз.
            pts = [(u * size, (1.0 - v) * size) for u, v in tri]
            draw.polygon(pts, fill=int(value), outline=int(value))
    return np.asarray(img)


def assign_layers(areas: Sequence[float], layers: Sequence[int], over_albedo: bool,
                  layout_seed: int = 0) -> List[int]:
    """
    Слой узора для каждой части (части — от крупной к мелкой).

    Крупнейшая часть получает первый слой — это «корпус», на нём главный узор.
    Остальные идут по кругу по прочим слоям, так что крупные детали получают
    разные узоры. ``layout_seed`` перемешивает круг — кнопка «Перемешать
    детали». Слой 0 значит «основа»: у обычного шаблона это первый слой (он и
    так лежит везде, где нет другого), у «поверх альбедо» — сама текстура.
    """
    if not areas:
        return []
    pool = list(layers)
    base = 0 if over_albedo else pool.pop(0)
    rest = pool[:] or [base]
    rng = random.Random(layout_seed)
    if layout_seed:
        rng.shuffle(rest)
    cycle = rest + ([base] if not over_albedo else [])
    out = [rest[0] if over_albedo else base]
    # «Поверх альбедо»: корпус уже взял rest[0], круг идёт дальше с rest[1],
    # иначе две крупнейшие детали получили бы один узор.
    shift = 0 if over_albedo else 1
    for i in range(1, len(areas)):
        out.append(cycle[(i - shift) % len(cycle)])
    if layout_seed:
        # Корпус тоже может уйти в другой слой — иначе «перемешать» меняло бы
        # только мелочь, а главное пятно оставалось бы прежним.
        first = rng.choice(list(layers))
        out[0] = first
    return [0 if (not over_albedo and x == base) else x for x in out]


def _edge_wear(labels: np.ndarray, size: int) -> np.ndarray:
    """Маска износа: 0 на краях деталей и вне развёртки, 1 в глубине детали.

    Расстояние до края считается последовательным «сжатием» маски: полоса
    износа узкая (~2 % стороны), и дальше неё считать незачем. Без scipy —
    в приложении его нет, а ради одной функции он весит десятки мегабайт.
    """
    inside = labels > 0
    # Край детали — и граница между разными деталями, не только с пустотой.
    edges = np.zeros_like(inside)
    edges[:, 1:] |= labels[:, 1:] != labels[:, :-1]
    edges[1:, :] |= labels[1:, :] != labels[:-1, :]
    reach = int(max(size * 0.02, 3))
    alive = inside & ~edges
    dist = np.zeros(labels.shape, np.float32)
    for step in range(1, reach + 1):
        dist[alive] = step
        shrunk = alive.copy()
        shrunk[1:, :] &= alive[:-1, :]
        shrunk[:-1, :] &= alive[1:, :]
        shrunk[:, 1:] &= alive[:, :-1]
        shrunk[:, :-1] &= alive[:, 1:]
        alive = shrunk
        if not alive.any():
            break
    dist[alive] = reach
    wear = np.clip(dist / reach, 0.0, 1.0) ** 0.7
    return np.where(inside, wear, 0.0)


def _soft_ao(base: np.ndarray, size: int) -> np.ndarray:
    """Мягкое затенение щелей по локальному контрасту яркости текстуры."""
    from PIL import Image, ImageFilter

    lum = base[..., :3].astype(np.float32).mean(axis=2)
    blurred = Image.fromarray(np.clip(lum, 0, 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(radius=max(size / 96.0, 2.0)))
    local = np.asarray(blurred, np.float32) + 1.0
    ratio = np.clip(lum / local, 0.0, 1.0)
    return 0.6 + 0.4 * ratio


def build_inputs(parts_model, obj_material: str, base_rgba: np.ndarray, size: int,
                 layers: Sequence[int], over_albedo: bool,
                 layout_seed: int = 0) -> Optional[GenericInputs]:
    """
    Входы рецепта для модели без War Paint. None — у модели нет развёртки.

    ``parts_model`` — разбор mesh_parts_service, ``obj_material`` — материал
    в OBJ, на который ложится War Paint; ``base_rgba`` — его игровая текстура.
    """
    units = _units(parts_model, obj_material, len(layers))
    if not units or not layers:
        return None
    chosen = assign_layers([area for area, _tris, _key in units], layers,
                           over_albedo, layout_seed)

    polys = []
    labels_src = []
    for i, (_area, tris, _key) in enumerate(units):
        polys.append((chosen[i] * 16, tris))
        labels_src.append((min(i + 1, 255), tris))
    groups_r = _rasterize(polys, size)
    labels = _rasterize(labels_src, size)

    groups = np.zeros((size, size, 4), np.uint8)
    groups[..., 0] = groups_r
    groups[..., 3] = 255

    from PIL import Image
    base = np.asarray(Image.fromarray(base_rgba, 'RGBA').resize((size, size), Image.LANCZOS))

    wear = (_edge_wear(labels, size) * 255).astype(np.uint8)
    ao = (_soft_ao(base, size) * 255).astype(np.uint8)
    gray = lambda a: np.dstack([a, a, a, np.full_like(a, 255)])  # noqa: E731

    textures = {GEN + 'albedo': base, GEN + 'groups': groups,
                GEN + 'wearblend': gray(wear), GEN + 'ao': gray(ao)}
    forced = {'weapon_albedo': GEN + 'albedo', 'weapon_groups': GEN + 'groups',
              'weapon_wearblend': GEN + 'wearblend', 'weapon_ao': GEN + 'ao'}
    # Выбор групп: слой N берёт группу N (значение N·16 в маске). Остальные
    # девять ячеек обнуляются — у пушки-донора там её собственные номера.
    for layer in layers:
        for k in range(1, 11):
            forced[f'texture_layer_{layer}_select_{k}'] = str(layer * 16) if k == 1 else '0'
    return GenericInputs(textures=textures, forced=forced,
                         assignment={key: chosen[i] for i, (_a, _t, key) in enumerate(units)})


def _uv_area(tris) -> float:
    return sum(abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) / 2
               for a, b, c in tris)


def _units(parts_model, material: str, n_layers: int) -> List[Tuple[float, list, int]]:
    """
    Куски, по которым раздаются слои узора: [(площадь, треугольники, ключ)],
    от крупного к мелкому.

    Обычно это части модели (ствол, приклад) — так их видит человек. Но у
    цельной модели (бита — одна деталь) слой один на всё, и War Paint вышел бы
    одним узором. Тогда берём острова развёртки: их больше, и на них у
    художников TF2 обычно и лежат разные узоры.
    """
    parts = [p for p in parts_model.parts_of(material) if p.paintable]
    units = [(p.uv_area, parts_model.polygons(material, p.index), p.index) for p in parts]
    islands = (parts_model.tri_island or {}).get(material) or []
    uv = (parts_model.uv or {}).get(material) or []
    if len(units) < n_layers and islands and uv:
        by_island: Dict[int, list] = {}
        for tri, island in enumerate(islands):
            if tri < len(uv):
                by_island.setdefault(island, []).append(uv[tri])
        from_islands = [(_uv_area(tris), tris, 1000 + key) for key, tris in by_island.items()]
        from_islands = [u for u in from_islands if u[0] > 0]
        if len(from_islands) > len(units):
            units = from_islands
    units.sort(key=lambda u: u[0], reverse=True)
    return units
