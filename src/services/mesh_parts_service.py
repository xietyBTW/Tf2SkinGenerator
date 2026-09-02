"""
Разделение модели на ЧАСТИ: связные куски меша и их места на развёртке.

Зачем. У оружия TF2 материал почти всегда один: `$texturegroup` из одной
строки, одна VTF на всю модель. Отдельно покрасить ствол и приклад через
материалы нельзя — движок назначает материал на треугольник, а внутри
материала никаких «частей» не существует. Зато существует развёртка: у ствола
и приклада свои острова UV, и покрасить их по отдельности можно прямо в
текстуре.

Что считается частью. По умолчанию — связный кусок ГЕОМЕТРИИ (вершины сварены
по позиции), а не остров UV. Так человек и видит модель: у револьвера 29 кусков
(барабан, рамка, ствол) против 106 островов развёртки — списком из 106 пунктов
пользоваться нельзя. Каждая часть тянет за собой свои острова, их и красим.

Но иногда нужно мельче. Внутри одного куска геометрии развёртка часто разрезана
ещё раз: у руки шпиона кусок один, а пальцы — отдельные острова, и покрасить
палец по-другому развёртка позволяет. Поэтому часть — это пара «кусок геометрии
+ остров развёртки». Пара, а не просто остров: остров может лежать сразу на двух
кусках (см. `shared` ниже), и тогда «часть» перестала бы быть куском модели.

Что резать, называется ПОИМЕННО (`cuts`: {номер группы: список НАБОРОВ
островов}). Не «сколько швов», а «какой»: счётчик отделял острова в своём
порядке — от крупного, — и добраться до мизинца можно было только перерезав
перед ним всё остальное.

Набор, а не один остров: развёртка режет вещи не так, как их видит человек —
палец у неё нередко разложен на верх и низ. Отрезок из нескольких островов
позволяет собрать «палец» обратно и красить его как одно целое.

Номер острова — его место по площади ВНУТРИ ГРУППЫ, от крупного. Он не зависит
от того, что уже отрезано, поэтому годится в ключ настройки; номер части
меняется вместе с разбиением и в ключ не годится.

Группа — куски, которые ДЕЛЯТ развёртку. У рук шпиона это левая и правая: в
игре у них общие пиксели, и разрезать одну, не разрезав другую, нельзя даже
теоретически — краска легла бы на обе. Поэтому настройка на группу, а разрез
применяется ко всем её кускам сразу. Частями они при этом остаются РАЗНЫМИ:
кусок модели — то, что человек видит и подсвечивает, и сливать левую руку с
правой в один пункт списка было бы враньём в другую сторону.

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
from dataclasses import dataclass, field
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
    #: Номер КУСКА геометрии, из которого часть вышла (нумерация нулевого
    #: дробления). По нему настраивается подробность именно этого куска.
    chunk: int = 0
    #: Номер ГРУППЫ: куски, делящие развёртку, режутся вместе (левая и правая
    #: рука шпиона — общие пиксели, разрезать одну без другой нельзя).
    group: int = 0
    #: Острова развёртки, из которых собран этот отрезок; пусто — неразрезанный
    #: остаток куска. По ним и хранится, что отрезано.
    islands: Tuple[int, ...] = ()
    #: Номер кусочка ВНУТРИ куска, с единицы; 0 — кусок не разрезан. По нему
    #: строится подпись «04·2»: сквозная нумерация от каждого разреза съезжала,
    #: и человек терял из виду ту часть, с которой работал.
    sub: int = 0

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
    #: {материал: номер острова каждого треугольника}. Вьювер по ней обводит
    #: тот остров, на который навели, и он же режется щелчком: «что отрежется»
    #: должно быть видно ДО разреза, а не выясняться после.
    tri_island: Dict[str, List[int]] = field(default_factory=dict)
    #: {материал: {номер группы: сколько в ней островов}} — чтобы сказать, что
    #: резать больше нечего.
    group_islands: Dict[str, Dict[int, int]] = field(default_factory=dict)

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


def _weigh(items: Sequence[object], triangles: Sequence[Tuple[tuple, UvTri]],
           of) -> Tuple[Dict[object, float], Dict[object, int]]:
    """Площадь развёртки и номер первого треугольника для каждого ключа.

    Первый треугольник — запасной ключ сортировки: у одинаковых по площади
    островов иначе менялись бы номера частей от запуска к запуску.
    """
    area: Dict[object, float] = {}
    first: Dict[object, int] = {}
    for index, item in enumerate(items):
        key = of(item)
        area[key] = area.get(key, 0.0) + _tri_area(triangles[index][1])
        first.setdefault(key, index)
    return area, first


def _chunk_order(keys: Sequence[tuple],
                 triangles: Sequence[Tuple[tuple, UvTri]]) -> Dict[object, int]:
    """Номера кусков по площади — нумерация НУЛЕВОГО дробления.

    Настройка живёт под номером группы, а он выводится из этого порядка,
    поэтому номер куска обязан не зависеть от разбиения: номер части меняется
    вместе с ним, номер куска — нет.
    """
    area, first = _weigh(keys, triangles, lambda key: key[0])
    ordered = sorted(area, key=lambda c: (-area[c], first[c]))
    return {chunk: index for index, chunk in enumerate(ordered)}


def _groups_of(keys: Sequence[tuple], order: Dict[object, int]) -> Dict[object, int]:
    """Номер ГРУППЫ для каждого куска: куски, делящие развёртку, — одна группа.

    Общий остров означает общие пиксели в игре: разрезать один кусок и не
    разрезать другой нельзя, краска всё равно ляжет на оба. Номер группы —
    наименьший номер куска в ней, он так же не зависит от разбиения.
    """
    union = _Union()
    for chunk, island in keys:
        union.union(('c', chunk), ('i', island))

    best: Dict[object, int] = {}
    for chunk in order:
        root = union.find(('c', chunk))
        best[root] = min(best.get(root, order[chunk]), order[chunk])
    return {chunk: best[union.find(('c', chunk))] for chunk in order}


def _island_numbers(keys: Sequence[tuple],
                    triangles: Sequence[Tuple[tuple, UvTri]],
                    groups: Dict[object, int]) -> Dict[object, int]:
    """Номер острова ВНУТРИ его группы, от крупного.

    По этим номерам хранится, что отрезано, поэтому нумерация не должна
    зависеть от уже сделанных разрезов — она считается по всей развёртке
    группы разом. Первый треугольник — запасной ключ: у равных по площади
    островов иначе порядок плавал бы между запусками.
    """
    area, first = _weigh(keys, triangles, lambda key: key[1])
    group_of = {island: groups[chunk] for chunk, island in keys}

    by_group: Dict[int, List[object]] = {}
    for island in area:
        by_group.setdefault(group_of[island], []).append(island)

    out: Dict[object, int] = {}
    for members in by_group.values():
        members.sort(key=lambda i: (-area[i], first[i]))
        for number, island in enumerate(members):
            out[island] = number
    return out


def bundles_of(cuts) -> Dict[int, List[Tuple[int, ...]]]:
    """Приводит разрезы к канону: наборы без пустых и без повторов, по порядку.

    Один и тот же остров в двух наборах означал бы часть с двумя ответами на
    вопрос «чем красить», поэтому повторы снимаются в пользу первого набора.
    Канон нужен и ключу кэша: {1:[[0,2]]} и {1:[[2,0]]} — одно и то же.
    """
    out: Dict[int, List[Tuple[int, ...]]] = {}
    for group, raw in (cuts or {}).items():
        taken: set = set()
        made: List[Tuple[int, ...]] = []
        for bundle in raw or ():
            # Одиночный остров разрешаем писать числом: так его и режут.
            items = (bundle,) if isinstance(bundle, int) else bundle
            clean = tuple(sorted({int(i) for i in items} - taken))
            if not clean:
                continue
            taken.update(clean)
            made.append(clean)
        if made:
            out[int(group)] = sorted(made)
    return out


def _regroup(keys: Sequence[tuple], cuts: Dict[int, List[Tuple[int, ...]]],
             order: Dict[object, int], groups: Dict[object, int],
             numbers: Dict[object, int]):
    """
    Ключ части для каждого треугольника при названных разрезах.

    Ключ — либо кусок геометрии (остров не отрезан), либо пара «кусок + набор»
    (отрезан). Решение принимается по НОМЕРУ ОСТРОВА В ГРУППЕ, поэтому у
    зеркальных кусков разрез происходит одновременно: остров у них общий. Все
    острова одного набора дают ОДИН ключ — так верх и низ пальца становятся
    одной частью.

    Возвращает (группы треугольников, из какого куска каждая, из каких островов
    собрана; пусто — неразрезанный остаток). Всё явно: ключ бывает и куском, и
    парой, и разбирать его по форме — способ однажды ошибиться молча.
    """
    # Остров → набор, которому он отдан. Ключом набора берём наименьший его
    # остров: он не зависит от порядка и переживает слияние соседей.
    owner: Dict[Tuple[int, int], Tuple[int, ...]] = {}
    for group, made in (cuts or {}).items():
        for bundle in made:
            for island in bundle:
                owner[(group, island)] = bundle

    out: Dict[object, List[int]] = {}
    belongs: Dict[object, int] = {}
    islands_of: Dict[object, Tuple[int, ...]] = {}
    for index, (chunk, island) in enumerate(keys):
        bundle = owner.get((groups[chunk], numbers[island]))
        key = (chunk, bundle[0]) if bundle else chunk
        out.setdefault(key, []).append(index)
        belongs[key] = order[chunk]
        islands_of[key] = bundle or ()
    return out, belongs, islands_of


def _split(triangles: Sequence[Tuple[tuple, UvTri]],
           cuts: Optional[Dict[int, set]] = None):
    """Части одного материала плюс карта «треугольник → остров».

    Возвращает (части, номер острова каждого треугольника, островов в группе).
    """
    geometry = _Union()
    layout = _Union()
    for positions, uv in triangles:
        geometry.union(positions[0], positions[1])
        geometry.union(positions[1], positions[2])
        # Остров развёртки сваривается по КООРДИНАТЕ UV, как и «общий пиксель»
        # ниже: два номера с одной координатой — это одна точка текстуры.
        layout.union(uv[0], uv[1])
        layout.union(uv[1], uv[2])

    keys = [(geometry.find(positions[0]), layout.find(uv[0]))
            for positions, uv in triangles]
    order = _chunk_order(keys, triangles)
    group_of = _groups_of(keys, order)
    numbers = _island_numbers(keys, triangles, group_of)
    groups, belongs, islands_of = _regroup(keys, bundles_of(cuts), order,
                                           group_of, numbers)

    tri_island = [numbers[island] for _, island in keys]
    per_group: Dict[int, set] = {}
    for chunk, island in keys:
        per_group.setdefault(group_of[chunk], set()).add(numbers[island])

    # Кто с кем делит развёртку: вершина UV, попавшая в две части, означает, что
    # в игре у них общий пиксель. Части одного куска, разрезанные по островам,
    # сюда не попадают по построению: общая вершина UV — это один остров.
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

    # Сначала по КУСКАМ (они уже упорядочены по площади), внутри куска — от
    # крупного. Так разрез вставляет свои кусочки на место, а не перетасовывает
    # весь список: соседние части остаются там, где человек их оставил.
    # Первый треугольник — запасной ключ, иначе порядок плавал бы между
    # запусками на равных площадях.
    raw.sort(key=lambda item: (belongs[item[0]], -item[3], item[1][0]))
    place = {key: index for index, (key, *_) in enumerate(raw)}

    # Номер внутри куска нужен только там, где кусок и правда разрезан: у
    # целого куска подпись — просто его номер.
    pieces: Dict[int, int] = {}
    for key, *_ in raw:
        pieces[belongs[key]] = pieces.get(belongs[key], 0) + 1
    seen: Dict[int, int] = {}

    out: List[Part] = []
    for key, indexes, bbox, area in raw:
        chunk = belongs[key]
        seen[chunk] = seen.get(chunk, 0) + 1
        out.append(Part(index=place[key],
                        triangles=tuple(indexes),
                        uv_bbox=bbox,
                        uv_area=area,
                        shared=tuple(sorted(place[k]
                                            for k in shared.get(key, ()))),
                        chunk=chunk,
                        sub=seen[chunk] if pieces[chunk] > 1 else 0,
                        group=group_of[_chunk_key(key)],
                        islands=islands_of[key]))
    return out, tri_island, {g: len(v) for g, v in per_group.items()}


def _chunk_key(key):
    """Корень КУСКА из ключа группы: он бывает и куском, и парой «кусок+остров»."""
    return key[0] if isinstance(key, tuple) and len(key) == 2 else key


#: Разбор дорогой ровно один раз на модель: у ревовльвера это 5676
#: треугольников. Ключ — файл, его время и дробление: пересборка превью пишет
#: новый OBJ, а другое дробление даёт другое разбиение того же файла.
_CACHE: Dict[tuple, ModelParts] = {}


def load(obj_path: str,
         cuts: Optional[Dict[int, object]] = None) -> Optional[ModelParts]:
    """Части модели по её OBJ. None — файла нет или в нём нет геометрии.

    ``cuts`` — {номер группы: список наборов островов}. Каждый набор — одна
    отрезанная часть; несколько островов в наборе сливаются в неё же. Пусто —
    куски геометрии целиком, как их видит человек.
    """
    if not obj_path or not os.path.isfile(obj_path):
        return None
    clean = bundles_of(cuts)
    key = (os.path.abspath(obj_path), os.path.getmtime(obj_path),
           tuple(sorted((g, tuple(v)) for g, v in clean.items())))
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

    done = {mat: _split(tris, clean) for mat, tris in by_mat.items()}
    parts = ModelParts(
        materials={mat: got[0] for mat, got in done.items()},
        uv={mat: [uv for _, uv in tris] for mat, tris in by_mat.items()},
        tri_island={mat: got[1] for mat, got in done.items()},
        group_islands={mat: got[2] for mat, got in done.items()},
    )
    _CACHE.clear() if len(_CACHE) > 8 else None
    _CACHE[key] = parts
    logger.info("части модели %s: %s", os.path.basename(obj_path),
                {m: len(p) for m, p in parts.materials.items()})
    return parts
