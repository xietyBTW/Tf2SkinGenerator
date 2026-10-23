"""
War Paint на оружии, для которого в игре War Paint нет

Рецепту War Paint от пушки нужны четыре картинки в её развёртке: альбедо
(«голый металл» под краской), маска групп (какой узор на какую деталь), маска
износа (где краска стирается первой) и AO (затенение щелей). У пушек War
Paint их рисовал художник Valve (`p_<пушка>_albedo/_groups/_wearblend/_ao`).
Здесь они строятся из самой модели:

* группы - части модели (куски геометрии, как их видит человек, с разрезами
  из редактора частей), раздаются по слоям узора от крупной к мелкой;
* износ - расстояние до края детали на развёртке: края стираются первыми,
  как у настоящих масок Valve;
* AO - мягкое затенение по локальному контрасту текстуры (альбедо и так
  несёт запечённый свет, сильный AO затемнил бы её второй раз);
* альбедо - игровая текстура пушки: под стёртой краской видна она

Результат - словарь «виртуальных» текстур для загрузчика компоновщика и
значения переменных рецепта, которые на них указывают

Украшенное оружие коллекций (Current Event, Night Owl…) шаблона не имеет:
его рецепт нарисован под маски одной пушки, пути к ним и номера её групп
записаны в самом рецепте. Такой рецепт переносится иначе (``recipe_looks``):
его «виды» - что получает деталь в зависимости от группы - раздаются по
деталям модели в тех долях, что на пушке-оригинале, а маски оригинала
подменяются масками модели (``swap_weapon_textures``)
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Имена виртуальных текстур (их отдаёт загрузчик, в VPK таких нет)
GEN = '__generated__/'


@dataclass
class GenericInputs:
    textures: Dict[str, np.ndarray]      # имя -> RGBA uint8
    forced: Dict[str, str]               # переменные рецепта
    #: Ключ детали -> слой узора
    assignment: Dict[str, int]


def _rasterize(polys_by_value: Sequence[Tuple[int, List]], size: int) -> np.ndarray:
    """Треугольники развёртки -> карта значений (0 - вне развёртки)"""
    from PIL import Image, ImageDraw

    img = Image.new('L', (size, size), 0)
    draw = ImageDraw.Draw(img)
    for value, tris in polys_by_value:
        for tri in tris:
            # Текстура повторяется, и развёртку кладут и в соседнюю плитку (у
            # линзы Базарной безделушки u от 1 до 2): её место на холсте то же,
            # что в плитке 0..1. Треугольник через край плитки рисуется и с
            # другой стороны - лишнее за холстом PIL обрежет сам
            cu = math.floor(sum(u for u, _ in tri) / 3)
            cv = math.floor(sum(v for _, v in tri) / 3)
            tri = [(u - cu, v - cv) for u, v in tri]
            us, vs = [u for u, _ in tri], [v for _, v in tri]
            for du in {0, -1 if max(us) > 1 else 0, 1 if min(us) < 0 else 0}:
                for dv in {0, -1 if max(vs) > 1 else 0, 1 if min(vs) < 0 else 0}:
                    # v вверх у SMD/OBJ; строка картинки - сверху вниз
                    pts = [((u + du) * size, (1.0 - (v + dv)) * size) for u, v in tri]
                    draw.polygon(pts, fill=int(value), outline=int(value))
    return np.asarray(img)


def assign_layers(areas: Sequence[float], layers: Sequence[int], over_albedo: bool,
                  layout_seed: int = 0) -> List[int]:
    """
    Слой узора для каждой части (части - от крупной к мелкой)

    Крупнейшая часть получает первый слой - это «корпус», на нём главный узор.
    Остальные идут по кругу по прочим слоям, так что крупные детали получают
    разные узоры. ``layout_seed`` перемешивает круг - кнопка «Перемешать
    детали». Слой 0 значит «основа»: у обычного шаблона это первый слой (он и
    так лежит везде, где нет другого), у «поверх альбедо» - сама текстура
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
    # иначе две крупнейшие детали получили бы один узор
    shift = 0 if over_albedo else 1
    for i in range(1, len(areas)):
        out.append(cycle[(i - shift) % len(cycle)])
    if layout_seed:
        # Корпус тоже может уйти в другой слой - иначе «перемешать» меняло бы
        # только мелочь, а главное пятно оставалось бы прежним
        first = rng.choice(list(layers))
        out[0] = first
    return [0 if (not over_albedo and x == base) else x for x in out]


def _edge_wear(labels: np.ndarray, size: int) -> np.ndarray:
    """Маска износа: 0 на краях деталей и вне развёртки, 1 в глубине детали

    Расстояние до края считается последовательным «сжатием» маски: полоса
    износа узкая (~2 % стороны), и дальше неё считать незачем. Без scipy -
    в приложении его нет, а ради одной функции он весит десятки мегабайт
    """
    inside = labels > 0
    # Край детали - и граница между разными деталями, не только с пустотой
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
    """Мягкое затенение щелей по локальному контрасту яркости текстуры"""
    from PIL import Image, ImageFilter

    lum = base[..., :3].astype(np.float32).mean(axis=2)
    blurred = Image.fromarray(np.clip(lum, 0, 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(radius=max(size / 96.0, 2.0)))
    local = np.asarray(blurred, np.float32) + 1.0
    ratio = np.clip(lum / local, 0.0, 1.0)
    return 0.6 + 0.4 * ratio


def build_inputs(parts_model, obj_material: str, base_rgba: np.ndarray, size: int,
                 layers: Sequence[int], over_albedo: bool,
                 layout_seed: int = 0,
                 assign: Optional[Dict[str, int]] = None) -> Optional[GenericInputs]:
    """
    Входы рецепта для модели без War Paint. None - у модели нет развёртки

    ``parts_model`` - разбор mesh_parts_service, ``obj_material`` - материал
    в OBJ, на который ложится War Paint; ``base_rgba`` - его игровая текстура
    """
    units = units_for(parts_model, obj_material, len(layers))
    if not units or not layers:
        return None
    chosen = layout_for(units, layers, over_albedo, layout_seed, assign)
    textures = _textures(units, [c * 16 for c in chosen], base_rgba, size)
    forced = {'weapon_albedo': GEN + 'albedo', 'weapon_groups': GEN + 'groups',
              'weapon_wearblend': GEN + 'wearblend', 'weapon_ao': GEN + 'ao'}
    # Выбор групп: слой N берёт группу N (значение N·16 в маске). Остальные
    # девять ячеек обнуляются - у пушки-донора там её собственные номера
    for layer in layers:
        for k in range(1, 11):
            forced[f'texture_layer_{layer}_select_{k}'] = str(layer * 16) if k == 1 else '0'
    return GenericInputs(textures=textures, forced=forced,
                         assignment={u.key: chosen[i] for i, u in enumerate(units)})


def _textures(units: Sequence['Unit'], values: Sequence[int], base_rgba: np.ndarray,
              size: int) -> Dict[str, np.ndarray]:
    """Альбедо, группы, износ и AO по деталям: деталь i - значение values[i] в маске групп"""
    from PIL import Image

    groups = np.zeros((size, size, 4), np.uint8)
    groups[..., 0] = _rasterize([(values[i], u.uv) for i, u in enumerate(units)], size)
    groups[..., 3] = 255
    labels = _rasterize([(min(i + 1, 255), u.uv) for i, u in enumerate(units)], size)
    base = np.asarray(Image.fromarray(base_rgba, 'RGBA').resize((size, size), Image.LANCZOS))
    wear = (_edge_wear(labels, size) * 255).astype(np.uint8)
    ao = (_soft_ao(base, size) * 255).astype(np.uint8)
    gray = lambda a: np.dstack([a, a, a, np.full_like(a, 255)])  # noqa: E731
    return {GEN + 'albedo': base, GEN + 'groups': groups,
            GEN + 'wearblend': gray(wear), GEN + 'ao': gray(ao)}


# Украшенное оружие: ручной рецепт одной пушки на любой модели

@dataclass
class Looks:
    """
    Виды ручного рецепта: что получает деталь, смотря по номеру её группы

    Вид - набор узлов select, которые группу выбирают, вид 0 - «ни один»
    (узор под всеми выборами, группу 0 рецепт не выбирает никогда)
    """
    groups: str              # маска групп пушки-оригинала в рецепте
    values: List[int]        # значение маски у вида (номер группы · 16)
    shares: List[float]      # доля вида на пушке-оригинале


def _selects(node: dict, out: List[dict]) -> List[dict]:
    if node.get('type') == 'select':
        out.append(node)
    for child in node.get('nodes') or []:
        _selects(child, out)
    return out


def _group(value) -> int:
    try:
        return round(int(float(str(value).split()[0])) / 16.0)
    except (ValueError, IndexError):
        return 0


def recipe_looks(recipe: dict, loader) -> Looks:
    """
    Виды рецепта и их доли на пушке-оригинале (по её маске групп, без маски -
    поровну). Номера групп у разных select бывают одними и теми же (у Coffin
    Nail узор и цвет выбирают одну группу) - это один вид
    """
    nodes = _selects(recipe, [])
    wanted = [{_group(v) for v in n.get('select') or []} - {0} for n in nodes]
    by_look: Dict[frozenset, List[int]] = {}
    # Групп 17: 248 и 255 в маске и в select - это round(·/16) = 16 (у ножа
    # такая пятая часть, у Stabbed to Hell на ней трещины)
    for gid in range(17):
        look = frozenset(i for i, ids in enumerate(wanted) if gid in ids)
        by_look.setdefault(look, []).append(gid)
    gids = [by_look.pop(frozenset(), [0])] + sorted(by_look.values())
    groups = next(((n.get('fields') or {}).get('groups', '') for n in nodes), '')

    mask = loader(groups, raw=True) if groups else None
    counts = (np.bincount(np.round(mask[..., 0] / 16.0).astype(np.int64).ravel(), minlength=17)
              if mask is not None else None)
    # Группа 0 у масок Valve - фон вне развёртки: в доли не входит
    areas = ([float(sum(counts[g] for g in ids if g)) for ids in gids]
             if counts is not None else [])
    total = sum(areas)
    shares = ([a / total for a in areas] if total
              else [1.0 / len(gids)] * len(gids))
    # Группе 16 - 255: 256 в восьмибитную маску не влезет
    return Looks(groups=groups, values=[min(ids[0] * 16, 255) for ids in gids],
                 shares=shares)


def assign_shares(areas: Sequence[float], shares: Sequence[float],
                  layout_seed: int = 0) -> List[int]:
    """
    Вид каждой детали (детали - от крупной к мелкой) так, чтобы площади видов
    шли в тех же долях, что на пушке-оригинале: деталь достаётся виду, которому
    сейчас больше всех недостаёт. ``layout_seed`` выбирает вид случайно, с
    весом по недостаче
    """
    total = sum(areas) or 1.0
    got = [0.0] * len(shares)
    rng = random.Random(layout_seed)
    out = []
    for area in areas:
        lack = [max(share - have / total, 0.0) for share, have in zip(shares, got)]
        if layout_seed and sum(lack) > 0:
            look = rng.choices(range(len(shares)), weights=lack)[0]
        else:
            look = max(range(len(shares)), key=lambda k: lack[k])
        got[look] += area
        out.append(look)
    return out


def looks_inputs(parts_model, obj_material: str, base_rgba: np.ndarray, size: int,
                 looks: Looks, layout_seed: int = 0,
                 assign: Optional[Dict[str, int]] = None) -> Optional[GenericInputs]:
    """Входы ручного рецепта на модели: маска групп - значения видов. None - нет развёртки"""
    units = units_for(parts_model, obj_material, len(looks.values))
    if not units:
        return None
    auto = assign_shares([u.area for u in units], looks.shares, layout_seed)
    chosen = _manual(units, auto, set(range(len(looks.values))), assign)
    return GenericInputs(
        textures=_textures(units, [looks.values[c] for c in chosen], base_rgba, size),
        forced={}, assignment={u.key: chosen[i] for i, u in enumerate(units)})


def swap_weapon_textures(recipe: dict) -> dict:
    """
    Ручной рецепт на чужой модели: маски пушки-оригинала заменяются масками
    модели. Её текстура и альбедо (``p_<пушка>_albedo``, у Old Country -
    сама ``c_revolver``) - альбедо модели, группы, износ (у Gun Mettle бывает
    свой: ``p_smg_wearblend_gunmettle``) и затенение - её же. Рисунок под
    развёртку оригинала снимается
    """
    from src.data.paintkit_defs import weapon_drawn

    def swap(path: str) -> str:
        low = (path or '').replace('\\', '/').lower()
        weapon = low.startswith('models/weapons/')
        # Картинка под развёртку оригинала (у Killer Bee - поверх узора
        # умножением) на чужой модели легла бы куда попало: белое - без неё
        if weapon_drawn(low):
            return 'patterns/blank_white'
        if '_wearblend' in low:
            return GEN + 'wearblend'
        if weapon and low.endswith('_groups'):
            return GEN + 'groups'
        if weapon and low.endswith('_ao'):
            return GEN + 'ao'
        return GEN + 'albedo' if weapon else path

    fields = dict(recipe.get('fields') or {})
    if recipe.get('type') == 'select':
        fields['groups'] = GEN + 'groups'
    for key in ('texture', 'texture_red', 'texture_blue'):
        if fields.get(key):
            fields[key] = swap(fields[key])
    return dict(recipe, fields=fields,
                nodes=[swap_weapon_textures(n) for n in recipe.get('nodes') or []])


def _uv_area(tris) -> float:
    return sum(abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) / 2
               for a, b, c in tris)


@dataclass
class Unit:
    """Деталь, которой раскладка War Paint даёт слой"""
    key: str                  # 'p3' - часть модели, 'i17' - остров, 'g2' - группа Valve
    area: float               # доля развёртки
    uv: list                  # UV-треугольники - маска для раскладки
    tris: List[int]           # номера треугольников материала - для клика во вьювере


def units_for(parts_model, material: str, n_layers: int) -> List[Unit]:
    """
    Детали, по которым раздаются слои узора, от крупной к мелкой

    Обычно это части модели (ствол, приклад) - так их видит человек. Но у
    цельной модели (бита - одна деталь) слой один на всё, и War Paint вышел бы
    одним узором. Тогда берём острова развёртки: их больше, и на них у
    художников TF2 обычно и лежат разные узоры
    """
    parts = [p for p in parts_model.parts_of(material) if p.paintable]
    units = [Unit(f'p{p.index}', p.uv_area, parts_model.polygons(material, p.index),
                  list(p.triangles)) for p in parts]
    islands = (parts_model.tri_island or {}).get(material) or []
    uv = (parts_model.uv or {}).get(material) or []
    if len(units) < n_layers and islands and uv:
        by_island: Dict[int, List[int]] = {}
        for tri, island in enumerate(islands):
            if tri < len(uv):
                by_island.setdefault(island, []).append(tri)
        from_islands = []
        for key, tris in by_island.items():
            polys = [uv[t] for t in tris]
            area = _uv_area(polys)
            if area > 0:
                from_islands.append(Unit(f'i{key}', area, polys, tris))
        if len(from_islands) > len(units):
            units = from_islands
    units.sort(key=lambda u: u.area, reverse=True)
    return units


def valve_units(parts_model, material: str, groups_rgba: np.ndarray) -> List[Unit]:
    """
    Детали пушки со своими War Paint - группы маски Valve (`p_<пушка>_groups`)

    Группа треугольника берётся по центру его развёртки. Группа 0 в раскладку
    не входит: выбрать её рецепт не может (нуль в select - «пусто»), она всегда
    под основой
    """
    uv = (parts_model.uv or {}).get(material) or []
    h, w = groups_rgba.shape[:2]
    by_group: Dict[int, List[int]] = {}
    for tri, (a, b, c) in enumerate(uv):
        cu = (a[0] + b[0] + c[0]) / 3.0
        cv = (a[1] + b[1] + c[1]) / 3.0
        x = min(max(int((cu % 1.0) * w), 0), w - 1)
        y = min(max(int(((1.0 - cv) % 1.0) * h), 0), h - 1)
        gid = int(round(groups_rgba[y, x, 0] / 16.0))
        if gid:
            by_group.setdefault(gid, []).append(tri)
    units = []
    for gid, tris in by_group.items():
        polys = [uv[t] for t in tris]
        units.append(Unit(f'g{gid}', _uv_area(polys), polys, tris))
    units.sort(key=lambda u: u.area, reverse=True)
    return units


def layout_for(units: Sequence[Unit], layers: Sequence[int], over_albedo: bool,
               layout_seed: int = 0, assign: Optional[Dict[str, int]] = None) -> List[int]:
    """Слой каждой детали: ручной выбор человека поверх автоматической раскладки"""
    auto = assign_layers([u.area for u in units], layers, over_albedo, layout_seed)
    return _manual(units, auto, set(layers) | {0}, assign)


def _manual(units: Sequence[Unit], auto: Sequence[int], allowed: set,
            assign: Optional[Dict[str, int]]) -> List[int]:
    """Ручной выбор человека поверх автомата, слой, которого нет, не в счёт"""
    out = []
    for unit, default in zip(units, auto):
        chosen = (assign or {}).get(unit.key)
        out.append(int(chosen) if chosen is not None and int(chosen) in allowed else default)
    return out
