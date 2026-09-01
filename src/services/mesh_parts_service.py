"""
Разделение модели на ЧАСТИ: связные куски меша и их места на развёртке.

Зачем. У оружия TF2 материал почти всегда один: `$texturegroup` из одной
строки, одна VTF на всю модель. Отдельно покрасить ствол и приклад через
материалы нельзя — движок назначает материал на треугольник, а внутри
материала никаких «частей» не существует. Зато существует развёртка: у ствола
и приклада свои острова UV, и покрасить их по отдельности можно прямо в
текстуре.

Что считается частью. Связный кусок ГЕОМЕТРИИ (вершины сварены по позиции), а
не остров UV. Так человек и видит модель: у револьвера 29 кусков (барабан,
рамка, ствол) против 106 островов развёртки — списком из 106 пунктов
пользоваться нельзя. Каждая часть тянет за собой свои острова, их и красим.

Чего этот путь не может. Если куски модели ДЕЛЯТ область развёртки (у
w_stickybomb 21 кусок на 5 островов, суммарная площадь UV 2.18), то в игре у
них один и тот же пиксель, и разными их не сделать никаким композитом. Такие
части помечаются `shared` — врать об этом нельзя, иначе человек рисует и не
понимает, почему покрасилось ещё в трёх местах.

Разбор идёт по OBJ, а не по SMD: именно OBJ уехал во вьювер, и номера
треугольников в нём те же, по которым вьювер вернёт попадание мыши. Считать
то же самое из SMD — значит завести второй порядок треугольников и однажды
разойтись с показанным.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Точность сварки вершин по позиции. OBJ пишется с шестью знаками, но
#: декомпилированная геометрия приходит с накопленной погрешностью — сварка
#: «в точности» рассыпала бы цельный кусок на десятки.
_WELD = 4

UvTri = Tuple[Tuple[float, float], Tuple[float, float], Tuple[float, float]]


@dataclass(frozen=True)
class Part:
    """Один связный кусок меша одного материала."""

    index: int
    #: Номера треугольников материала (в порядке OBJ) — по ним подсвечивает вьювер.
    triangles: Tuple[int, ...]
    #: Прямоугольник на развёртке, в который часть укладывается целиком.
    uv_bbox: Tuple[float, float, float, float]
    #: Доля развёртки. Мелкие части (винтики) красить бессмысленно, но прятать
    #: их нельзя: человек может искать именно винтик.
    uv_area: float
    #: Части, с которыми эта делит вершины развёртки, — покрасятся вместе.
    shared: Tuple[int, ...] = ()

    @property
    def paintable(self) -> bool:
        """Есть ли что красить: у вырожденной развёртки площадь нулевая."""
        return self.uv_area > 0.0


@dataclass(frozen=True)
class ModelParts:
    """Разбор одной модели: части и развёртка по материалам."""

    #: {материал: части, от крупной к мелкой}
    materials: Dict[str, List[Part]]
    #: {материал: UV каждого треугольника} — из них строится маска композита.
    uv: Dict[str, List[UvTri]]

    def parts_of(self, material: str) -> List[Part]:
        return self.materials.get(material, [])

    def polygons(self, material: str, part_index: int) -> List[UvTri]:
        """UV-треугольники одной части — маска для наложения картинки."""
        uv = self.uv.get(material) or []
        for part in self.materials.get(material, []):
            if part.index == part_index:
                return [uv[t] for t in part.triangles if t < len(uv)]
        return []


class _Union:
    """Система непересекающихся множеств: сварка вершин в куски."""

    def __init__(self) -> None:
        self._parent: Dict[object, object] = {}

    def find(self, x):
        p = self._parent
        p.setdefault(x, x)
        while p[x] != x:
            p[x] = p[p[x]]
            x = p[x]
        return x

    def union(self, a, b) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb


def _parse_obj(obj_path: str) -> Dict[str, List[Tuple[List[int], List[int]]]]:
    """
    Треугольники OBJ по материалам: (индексы позиций, индексы UV).

    Вьювер группирует геометрию по `usemtl`, и номер треугольника в попадании
    мыши отсчитывается внутри группы — здесь тот же порядок.
    """
    positions: List[Tuple[float, float, float]] = []
    uvs: List[Tuple[float, float]] = []
    by_mat: Dict[str, List[Tuple[List[int], List[int]]]] = {}
    current = ''

    with open(obj_path, encoding='utf-8', errors='replace') as f:
        for line in f:
            if line.startswith('v '):
                x, y, z = line.split()[1:4]
                positions.append((round(float(x), _WELD),
                                  round(float(y), _WELD),
                                  round(float(z), _WELD)))
            elif line.startswith('vt '):
                u, v = line.split()[1:3]
                uvs.append((float(u), float(v)))
            elif line.startswith('usemtl '):
                current = line.split(None, 1)[1].strip()
            elif line.startswith('f '):
                verts = line.split()[1:4]
                if len(verts) < 3:
                    continue
                pos_idx, uv_idx = [], []
                for vert in verts:
                    chunks = vert.split('/')
                    pos_idx.append(int(chunks[0]) - 1)
                    uv_idx.append(int(chunks[1]) - 1 if len(chunks) > 1
                                  and chunks[1] else -1)
                by_mat.setdefault(current, []).append((pos_idx, uv_idx))

    return {mat: [(tuple(positions[i] for i in p),        # type: ignore[misc]
                   tuple(uvs[i] if 0 <= i < len(uvs) else (0.0, 0.0)
                         for i in u))
                  for p, u in tris]
            for mat, tris in by_mat.items()}


def _tri_area(tri: UvTri) -> float:
    (u1, v1), (u2, v2), (u3, v3) = tri
    return abs((u2 - u1) * (v3 - v1) - (u3 - u1) * (v2 - v1)) / 2


def _split(triangles: Sequence[Tuple[tuple, UvTri]]) -> List[Part]:
    """Связные куски одного материала, от крупного к мелкому."""
    union = _Union()
    for positions, _ in triangles:
        union.union(positions[0], positions[1])
        union.union(positions[1], positions[2])

    groups: Dict[object, List[int]] = {}
    for index, (positions, _) in enumerate(triangles):
        groups.setdefault(union.find(positions[0]), []).append(index)

    # Кто с кем делит развёртку: вершина UV, попавшая в два куска, означает, что
    # в игре у них общий пиксель.
    owners: Dict[Tuple[float, float], set] = {}
    for key, indexes in groups.items():
        for index in indexes:
            for uv in triangles[index][1]:
                owners.setdefault(uv, set()).add(key)
    shared: Dict[object, set] = {}
    for holders in owners.values():
        if len(holders) > 1:
            for key in holders:
                shared.setdefault(key, set()).update(holders - {key})

    raw = []
    for key, indexes in groups.items():
        polys = [triangles[i][1] for i in indexes]
        us = [u for tri in polys for u, _ in tri]
        vs = [v for tri in polys for _, v in tri]
        raw.append((key, indexes,
                    (min(us), min(vs), max(us), max(vs)) if us else (0, 0, 0, 0),
                    sum(_tri_area(tri) for tri in polys)))

    raw.sort(key=lambda item: -item[3])
    order = {key: index for index, (key, *_ ) in enumerate(raw)}
    return [Part(index=order[key],
                 triangles=tuple(indexes),
                 uv_bbox=bbox,
                 uv_area=area,
                 shared=tuple(sorted(order[k] for k in shared.get(key, ()))))
            for key, indexes, bbox, area in raw]


#: Разбор дорогой ровно один раз на модель: у ревовльвера это 5676
#: треугольников. Ключ — файл и его время: пересборка превью пишет новый OBJ.
_CACHE: Dict[Tuple[str, float], ModelParts] = {}


def load(obj_path: str) -> Optional[ModelParts]:
    """Части модели по её OBJ. None — файла нет или в нём нет геометрии."""
    if not obj_path or not os.path.isfile(obj_path):
        return None
    key = (os.path.abspath(obj_path), os.path.getmtime(obj_path))
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    try:
        by_mat = _parse_obj(obj_path)
    except (OSError, ValueError, IndexError) as exc:
        logger.warning(f"разбор частей не удался ({obj_path}): {exc}")
        return None
    if not by_mat:
        return None

    parts = ModelParts(
        materials={mat: _split(tris) for mat, tris in by_mat.items()},
        uv={mat: [uv for _, uv in tris] for mat, tris in by_mat.items()},
    )
    _CACHE.clear() if len(_CACHE) > 8 else None
    _CACHE[key] = parts
    logger.info("части модели %s: %s", os.path.basename(obj_path),
                {m: len(p) for m, p in parts.materials.items()})
    return parts
