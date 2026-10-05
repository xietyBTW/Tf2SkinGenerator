"""
Часть модели как отдельный материал.

Зачем. Эффекты VMT (блеск, свечение, прозрачность, анимация текстуры)
действуют на материал целиком, а материал у оружия обычно один на всю модель.
Чтобы светился только экран или блестел только ствол, часть надо сделать
своим материалом: её треугольники получают в SMD новое имя, и у нового имени
свой VMT.

Где это живёт. Разбор на части и покраска об этом не знают: часть остаётся
частью своего материала, а пока у нового материала нет своей картинки, он
берёт текстуру исходного вместе с её покраской. Своё у него — VMT, карты
материала, настройки текстуры и, если человек положит, картинка.

Как сборка находит треугольники. Номера треугольников части — номера в OBJ
превью внутри материала. OBJ пишется из SMD подряд: основной файл, затем
бодигруппы, и треугольник попадает в него, только если все три вершины
разобрались (`SmdToObjService`). Здесь тот же обход тех же файлов тем же
разбором, поэтому номер ведёт ровно к тому треугольнику. Список файлов OBJ
помнит сам — строкой `# Sources:` в шапке.
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Строка шапки OBJ со списком исходных SMD (имена через «|», по порядку).
SOURCES_PREFIX = '# Sources:'

_RE_TRIANGLES = re.compile(r"\btriangles\b(.*?)\bend\b", re.DOTALL | re.IGNORECASE)


# ── Имена ─────────────────────────────────────────────────────────────────── #

def model_name(material: str) -> str:
    """Имя материала, с которым его скомпилирует studiomdl: нижний регистр
    (Source ищет материалы в нижнем регистре, а VPK — нет) и без точек
    (studiomdl обрезает имя на первой точке). Так же делает и подмена
    геометрии своей модели (SMDService._sanitize_material_name)."""
    return str(material or '').strip().lower().replace('.', '_')


def next_name(base: str, taken: Iterable[str],
              busy: Callable[[str], bool] = lambda name: False) -> str:
    """Свободное имя нового материала: `<исходный>_part<N>`, по `model_name`
    (у своей модели материалы бывают и с точками: `Material.001`).

    `busy` — имя занято не моделью: под ним лежит правка VMT прежнего
    материала (правки хранятся по имени), и новый унаследовал бы её.
    """
    used = {model_name(t) for t in taken}
    stem = model_name(base)
    n = 1
    while f"{stem}_part{n}" in used or busy(f"{stem}_part{n}"):
        n += 1
    return f"{stem}_part{n}"


def variant_name(part: str, base: str, variant: str, row: int) -> str:
    """Имя части в строке скина, где исходный материал заменён вариантом.

    Хвост варианта переезжает к части: `c_x_blue` → `c_x_part1_blue`,
    `hat_red`/`hat_blue` → `hat_red_part1_blue`. Так у части выходит
    `<часть>_blue`, а это имя сборка уже знает: карты материала она сама
    дублирует в `<материал>_blue.vmt`.
    """
    a, b = base.lower(), variant.lower()
    common = os.path.commonprefix([a, b])
    tail = b[len(common):].strip('_')
    return f"{part}_{tail}" if tail else f"{part}_s{row}"


# ── OBJ превью → SMD ─────────────────────────────────────────────────────── #

def sources_of_obj(obj_path: str) -> List[str]:
    """Имена SMD, из которых по порядку собран OBJ превью (пусто — не знаем)."""
    try:
        with open(obj_path, encoding='utf-8', errors='replace') as f:
            for _ in range(8):
                line = f.readline()
                if line.startswith(SOURCES_PREFIX):
                    names = line[len(SOURCES_PREFIX):].strip()
                    return [n for n in names.split('|') if n]
    except OSError:
        pass
    return []


def rename_triangles(smd_text: str, material: str, names: Dict[int, str],
                     start: int = 0) -> Tuple[str, int, Counter]:
    """
    Переименовывает материал у выбранных треугольников одного SMD.

    `names` — {номер треугольника `material` в OBJ превью: новое имя},
    `start` — сколько таких треугольников было в предыдущих файлах. Все части
    одного материала идут ОДНИМ проходом: переименованный треугольник уже не
    `material`, и вторая часть, пройдя файл после первой, считала бы номера со
    сдвигом. Обход повторяет `SmdToObjService._parse_triangles_by_mat`:
    непустые строки секции, имя и три вершины подряд, в счёт идёт только
    треугольник с тремя разобранными вершинами.

    Returns:
        (новый текст, сколько треугольников `material` в файле,
        {новое имя: сколько треугольников получило его})
    """
    renamed: Counter = Counter()
    m = _RE_TRIANGLES.search(smd_text)
    if not m:
        return smd_text, 0, renamed
    lines = smd_text[m.start(1):m.end(1)].splitlines(keepends=True)
    count = 0
    for name_at, name, _verts in _triangles(lines):
        if name != material:
            continue
        new_name = names.get(start + count)
        if new_name:
            line = lines[name_at]
            lead = line[:len(line) - len(line.lstrip())]
            end = line[len(line.rstrip('\r\n')):]
            lines[name_at] = lead + new_name + end
            renamed[new_name] += 1
        count += 1
    text = smd_text[:m.start(1)] + ''.join(lines) + smd_text[m.end(1):]
    return text, count, renamed


def _triangles(lines: Sequence[str]):
    """(номер строки имени, имя материала, вершины) каждого треугольника
    секции, который превью кладёт в OBJ: непустые строки, имя и три вершины
    подряд, все три разобрались (`SmdToObjService._parse_triangles_by_mat`)."""
    from src.services.smd_to_obj_service import SmdToObjService

    filled = [i for i, ln in enumerate(lines) if ln.strip()]
    for k in range(0, len(filled), 4):
        verts = [SmdToObjService._parse_vertex(lines[j].strip())
                 for j in filled[k + 1:k + 4]]
        if len(verts) == 3 and all(v is not None for v in verts):
            yield filled[k], lines[filled[k]].strip(), verts


def material_counts(smd_text: str) -> Counter:
    """Сколько треугольников каждого материала в SMD (тот же счёт, что у превью)."""
    m = _RE_TRIANGLES.search(smd_text)
    if not m:
        return Counter()
    return Counter(name for _, name, _verts in _triangles(
        smd_text[m.start(1):m.end(1)].splitlines(keepends=True)))


def fits(spec: dict, total: int, weapon_end: int) -> bool:
    """
    Годятся ли номера треугольников материала части для модели, где у
    исходного материала `total` треугольников и первые `weapon_end` из них —
    само оружие, а дальше снаряд в оружии (граната Loch-n-Load).

    Модель та же (`total` совпал) — годятся. Иначе годятся части самого
    оружия, если оно не изменилось: снаряд идёт в конце, и его смена (своя
    модель, «скрыт») номеров оружия не двигает. `late` части — сколько
    треугольников было у оружия при выборе; у выбранных до того, как снаряд
    появился в кадре, это весь `total`.
    """
    was = int(spec.get('total') or 0)
    if not was or was == total:
        return True
    tris = spec.get('tris') or ()
    late = spec.get('late')
    return (bool(tris) and max(int(t) for t in tris) < weapon_end
            and int(was if late is None else late) == weapon_end)


def specs_for_custom_model(specs: Sequence[dict], reference_smd: str,
                           keep_materials: bool) -> List[dict]:
    """
    Спеки частей своей модели — в имена собранной модели.

    Превью нумерует треугольники по SMD человека, а сборка к этому шагу уже
    перенесла их в reference-SMD разобранной модели (подмена геометрии) —
    тем же порядком, но под другими именами: с «сохранить материалы» — под
    `model_name` своих, без него — под материалом оригинала. Источник у части
    один — этот reference-SMD; число треугольников (`total`) сверит, что
    нумерация совпала, и иначе часть не перенесётся.
    """
    if keep_materials:
        base_of = model_name
    else:
        try:
            with open(reference_smd, 'r', encoding='utf-8', errors='replace') as f:
                counts = material_counts(f.read())
        except OSError:
            counts = Counter()
        model_main = counts.most_common(1)[0][0] if counts else ''
        base_of = lambda raw: model_main    # noqa: E731 — вся геометрия на одном
    source = os.path.basename(reference_smd)
    return [{**s, 'base': base_of(str(s['base'])), 'sources': [source]} for s in specs]


# ── Другая модель того же предмета ───────────────────────────────────────── #

def _uv_triangles(path: str) -> List[Tuple[str, tuple]]:
    """(имя материала, UV трёх вершин) треугольников SMD в счёте превью."""
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            text = f.read()
    except OSError:
        return []
    m = _RE_TRIANGLES.search(text)
    if not m:
        return []
    lines = text[m.start(1):m.end(1)].splitlines()
    return [(name, tuple(v['uv'] for v in verts))
            for _, name, verts in _triangles(lines)]


def _covers(point, tri, eps: float = 1e-6) -> bool:
    (x, y), ((x1, y1), (x2, y2), (x3, y3)) = point, tri
    d = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
    if abs(d) < 1e-12:
        return False
    a = ((y2 - y3) * (x - x3) + (x3 - x2) * (y - y3)) / d
    b = ((y3 - y1) * (x - x3) + (x1 - x3) * (y - y3)) / d
    return a >= -eps and b >= -eps and 1 - a - b >= -eps


def _centre(tri) -> Tuple[float, float]:
    return sum(u for u, _ in tri) / 3, sum(v for _, v in tri) / 3


def _finite(tri) -> bool:
    return all(math.isfinite(c) for point in tri for c in point)


class _UvGrid:
    """Треугольники в сетке UV: какие накрывают точку текстуры."""

    def __init__(self, tris: Sequence[tuple], cells: int = 64):
        good = [t for t in tris if _finite(t)]
        us = [u for t in good for u, _ in t] or [0.0]
        vs = [v for t in good for _, v in t] or [0.0]
        self.u0, self.v0 = min(us), min(vs)
        self.du = (max(us) - self.u0) / cells or 1.0
        self.dv = (max(vs) - self.v0) / cells or 1.0
        self.cells = cells
        self.tris = tris
        self.grid: Dict[Tuple[int, int], List[int]] = {}
        for i, t in enumerate(tris):
            if not _finite(t):
                continue    # нечисловые UV ничего не накрывают
            (a, b), (c, d) = self._cell(min(u for u, _ in t), min(v for _, v in t)),                 self._cell(max(u for u, _ in t), max(v for _, v in t))
            for x in range(a, c + 1):
                for y in range(b, d + 1):
                    self.grid.setdefault((x, y), []).append(i)

    def _cell(self, u: float, v: float) -> Tuple[int, int]:
        clamp = lambda n: min(max(n, 0), self.cells)    # noqa: E731
        return clamp(int((u - self.u0) / self.du)), clamp(int((v - self.v0) / self.dv))

    def covering(self, point) -> List[int]:
        return [i for i in self.grid.get(self._cell(*point), ())
                if _covers(point, self.tris[i])]

    def nearest(self, point) -> List[int]:
        """Треугольники с ближайшим к точке центром в UV (все, если поровну)."""
        def dist(t):
            if not _finite(t):
                return math.inf
            cu, cv = _centre(t)
            return (cu - point[0]) ** 2 + (cv - point[1]) ** 2
        dists = [dist(t) for t in self.tris]
        best = min(dists, default=math.inf)
        return [i for i, d in enumerate(dists) if d <= best + 1e-12] if best < math.inf else []


#: Часть по текстуре не отличить: UV наложены.
_CLASH = object()


def _part_of(grid: _UvGrid, source: Sequence[tuple], tri: tuple):
    """
    Решение для треугольника другой модели: имя части, None (остаётся в
    исходном материале) или _CLASH.

    Голосуют четыре точки его UV: центр и точки у вершин. Точка, которую
    накрывают треугольники с разным решением, не голосует: так бывает на
    ребре между частью и остальным (у квадрата, разрезанного по другой
    диагонали, центр треугольника ложится ровно на неё). При равенстве
    голосов решает первая проголосовавшая точка, центр раньше всех. Точки
    накрыты, но не проголосовала ни одна: UV наложены, как у зеркальных
    половин, и часть не отличить. Не накрыта ни одна: решает ближайший
    треугольник, если такой один.
    """
    if not _finite(tri):
        return None
    a, b, c = tri
    near = [((4 * p[0] + q[0] + r[0]) / 6, (4 * p[1] + q[1] + r[1]) / 6)
            for p, q, r in ((a, b, c), (b, c, a), (c, a, b))]
    votes: Counter = Counter()
    covered = False
    for point in (_centre(tri), *near):
        hits = grid.covering(point)
        covered = covered or bool(hits)
        names = {source[h][0] for h in hits}
        if len(names) == 1:
            votes[names.pop()] += 1
    if votes:
        return max(votes, key=votes.get)
    if covered:
        return _CLASH
    names = {source[h][0] for h in grid.nearest(_centre(tri))}
    return names.pop() if len(names) == 1 else _CLASH


def _body_smds(qc_path: str) -> List[str]:
    """SMD, которые QC собирает в модель: `$body`/`$model` и `studio` групп.
    Без LOD (`replacemodel`, сборка их всё равно вырезает) и физики."""
    try:
        with open(qc_path, 'r', encoding='utf-8', errors='replace') as f:
            text = f.read()
    except OSError:
        return []
    found = re.findall(r'(?:\bstudio\s+|\$(?:model|body)\b[^\n{]*?)"([^"]+\.smd)"',
                       text, re.IGNORECASE)
    return list(dict.fromkeys(os.path.basename(f.replace(chr(92), '/')) for f in found))


def _projectile_files(qc_path: str) -> set:
    """Имена SMD снарядов в оружии из QC (нижний регистр): в OBJ превью их
    треугольники идут после треугольников самого оружия."""
    from src.services.model_build_service import ModelBuildService

    out = set()
    for name, variants in ModelBuildService.extract_bodygroups(qc_path):
        shown = ModelBuildService.projectile_variant(name, variants)
        if shown is not None:
            out.add(os.path.basename(str(variants[shown]).replace(chr(92), '/')).lower())
    return out


def specs_for_other_model(specs: Sequence[dict], source_folder: str,
                          qc_path: str) -> Tuple[List[dict], List[str]]:
    """
    Части, выбранные на одной модели предмета, — для другой его модели с той
    же текстурой (остальные классы мультиклассовой шапки).

    Номера треугольников не переносятся: сетка у модели класса своя (у шляпы
    Билла скаута и солдата общих треугольников 602 из 668, и порядок другой).
    Общая у них текстура, а часть — её участок. Поэтому треугольник модели
    класса уходит в ту часть, чьи треугольники на исходной модели накрывают
    его в UV (_part_of). Если UV наложены (зеркальные половины) и часть по
    текстуре не отличить, части этого материала не переносятся вовсе.

    `source_folder` — папка исходной модели, где части уже стали своими
    материалами (apply_to_model). Returns: (спеки для модели `qc_path`,
    имена частей, которые перенести не вышло).
    """
    folder = os.path.dirname(qc_path)
    smds = [f for f in _body_smds(qc_path) if os.path.isfile(os.path.join(folder, f))]
    walked = {f: _uv_triangles(os.path.join(folder, f)) for f in smds}

    groups: Dict[str, List[dict]] = {}
    for spec in specs:
        groups.setdefault(str(spec['base']), []).append(spec)

    out: List[dict] = []
    missed: List[str] = []
    for base, group in groups.items():
        parts = {str(s['name']).lower() for s in group}
        source = [(name.lower() if name.lower() in parts else None, uv)
                  for src in group[0].get('sources') or ()
                  for name, uv in _uv_triangles(os.path.join(source_folder, os.path.basename(src)))
                  if name == base or name.lower() in parts]
        files = [f for f in smds if any(name == base for name, _ in walked[f])]
        target = [uv for f in files for name, uv in walked[f] if name == base]
        if not source or not target:
            missed += sorted(parts)
            continue
        grid = _UvGrid([uv for _, uv in source])
        chosen: Dict[str, List[int]] = {}
        clash = False
        for i, uv in enumerate(target):
            name = _part_of(grid, source, uv)
            if name is _CLASH:
                clash = True
                break
            if name:
                chosen.setdefault(name, []).append(i)
        if clash:
            logger.warning(f"[ЧАСТИ] {base}: UV наложены, части на {os.path.basename(qc_path)} "
                           f"не перенести")
            missed += sorted(parts)
            continue
        for s in group:
            name = str(s['name']).lower()
            if chosen.get(name):
                out.append({**s, 'tris': chosen[name], 'total': len(target), 'sources': files})
            else:
                missed.append(name)
    return out, missed


def add_part_columns(rows: List[List[str]],
                     parts: Sequence[Tuple[str, str]]
                     ) -> Tuple[List[List[str]], Dict[str, str]]:
    """
    Добавляет части столбцами в строки `$texturegroup`.

    `parts` — пары (часть, исходный материал). В строке, где исходный
    материал заменён вариантом (BLU, австралий, стиль), часть получает свой
    вариант (см. variant_name). Исходного материала в группе нет — часть в
    неё не добавляется: материал вне группы одинаков во всех скинах, и так
    было с ним и раньше.

    Returns:
        (новые строки, {имя части в строке: материал, чей VMT она берёт}).
    """
    rows = [list(r) for r in rows]
    variants: Dict[str, str] = {}
    for part, base in parts:
        head = [n.lower() for n in rows[0]] if rows else []
        col = head.index(base.lower()) if base.lower() in head else -1
        if col < 0:
            variants[part] = base
            continue
        for r, row in enumerate(rows):
            source = row[col] if col < len(row) else base
            name = (part if source.lower() == base.lower()
                    else variant_name(part, base, source, r))
            if variants.get(name, source).lower() != source.lower():
                name = f"{part}_s{r}"
            variants[name] = source
            row.append(name)
    return rows, variants


def apply_to_model(qc_path: str, specs: Sequence[dict],
                   warn: Callable[[str], None] = lambda message: None) -> Dict[str, str]:
    """
    Делает части своими материалами в разобранной модели перед компиляцией.

    Переписывает SMD рядом с QC и `$texturegroup` в самом QC. `specs` —
    [{name, base, tris, total, sources}] (см. AppSession._part_material_specs).

    Номера треугольников годятся только для той модели, на которой выбирали
    части. Нет какого-то из её SMD или у материала не столько треугольников,
    сколько было тогда (`total`), — части этого материала не переносятся
    вовсе, и `warn` говорит об этом: по чужим номерам они легли бы не на те
    треугольники.

    Returns:
        {имя материала части: материал, чей VMT она берёт} — по нему сборка
        пишет VMT частей.
    """
    folder = os.path.dirname(qc_path)
    groups: Dict[str, List[dict]] = {}
    for spec in specs:
        groups.setdefault(str(spec['base']), []).append(spec)
    shells = _projectile_files(qc_path)

    applied: List[Tuple[str, str]] = []
    for base, group in groups.items():
        # Самый длинный список: выбранные до того, как снаряд в оружии попал в
        # кадр, помнят OBJ без его SMD, а нумерация у всех одна — снаряд в конце.
        sources = max((s.get('sources') or [] for s in group), key=len)
        paths = [os.path.join(folder, os.path.basename(src)) for src in sources]
        texts: List[Tuple[str, str]] = []
        if paths and all(os.path.isfile(p) for p in paths):
            for path in paths:
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    texts.append((path, f.read()))
        # Сколько треугольников у материала и сколько из них — само оружие:
        # снаряд в оружии (своя модель) мог смениться после выбора (fits).
        counts = [material_counts(text)[base] for _, text in texts]
        seen = sum(counts)
        weapon = sum(n for (path, _), n in zip(texts, counts)
                     if os.path.basename(path).lower() not in shells)
        good = [s for s in group if texts and fits(s, seen, weapon)]
        for s in group:
            if s not in good:
                logger.warning(f"[ЧАСТИ] {base}: SMD {len(texts)}/{len(paths)}, "
                               f"треугольников {seen} при выборе {s.get('total')} — "
                               f"часть {s['name']} пропущена")
                warn(f"Материал части «{str(s['name']).lower()}» не собран: "
                     f"модель не та, на которой выбирали части")
        if not good:
            continue
        names = {int(t): str(s['name']).lower() for s in good for t in s.get('tris') or ()}
        out, offset, renamed = [], 0, Counter()
        for path, text in texts:
            text, count, done = rename_triangles(text, base, names, offset)
            offset += count
            renamed += done
            out.append((path, text, done))
        for path, text, done in out:
            if done:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(text)
        for s in good:
            name = str(s['name']).lower()
            if renamed[name]:
                applied.append((name, base))
                logger.info(f"[ЧАСТИ] {name}: {renamed[name]} треугольников из {base}")
            else:
                logger.warning(f"[ЧАСТИ] {name}: треугольники не найдены — часть пропущена")

    variants: Dict[str, str] = {}
    if not applied:
        return variants
    from src.services import qc_skin_parser
    from src.services.model_build_service import ModelBuildService
    rows = qc_skin_parser.parse_texturegroup_rows(qc_path)
    if rows:
        rows, variants = add_part_columns(rows, applied)
        ModelBuildService.replace_texturegroup_in_qc(
            qc_path, ModelBuildService.generate_renamed_texturegroup(rows, {}))
    else:
        variants = {name: base for name, base in applied}
    return variants


# ── VMT ───────────────────────────────────────────────────────────────────── #

def _spelled(key: str) -> str:
    """Ключ для записи: разбор хранит его без «$» и в нижнем регистре."""
    return key if key.startswith('%') else f'${key}'


def _drop_key(text: str, key: str) -> str:
    from src.services.vmt_effects import _key_re
    return re.sub(_key_re(key).pattern + r'\n?', '', text,
                  flags=re.IGNORECASE | re.MULTILINE)


#: Текстуры VMT, которые ложатся по развёртке модели (и ключи, без них
#: бессмысленные). У своей модели снаряда развёртка своя: карта нормалей
#: оружия легла бы на неё пятнами. Lightwarp, envmap и маска блеска
#: killstreak от развёртки не зависят — они остаются.
UV_BOUND_KEYS = ('bumpmap', 'bumpframe', 'bumptransform', 'normalmapalphaenvmapmask',
                 'phongexponenttexture', 'envmapmask', 'envmapmaskframe',
                 'envmapmasktransform', 'selfillummask', 'detail', 'detailscale',
                 'detailblendfactor', 'detailblendmode', 'detailtint', 'detailframe',
                 'detailtexturetransform')


def without_uv_maps(vmt_text: str) -> str:
    """VMT без текстур, привязанных к развёртке исходной модели (UV_BOUND_KEYS)."""
    from src.services import vmt_parse

    present = vmt_parse.parse(vmt_text).root.params
    out = vmt_text
    for key in UV_BOUND_KEYS:
        if key in present:
            out = _drop_key(out, _spelled(key))
    return out


def _proxies_span(text: str) -> Optional[Tuple[int, int]]:
    """Начало и конец (включительно с «}») блока Proxies, если он есть."""
    from src.services.vmt_effects import _PROXIES_RE, _match_brace
    m = _PROXIES_RE.search(text)
    if not m:
        return None
    close = _match_brace(text, m.end() - 1)
    return (m.start(), close + 1) if close >= 0 else None


def _set_shader(text: str, shader: str) -> str:
    from src.services.vmt_effects import _first_brace
    at = _first_brace(text)
    if at < 0:
        return text
    head = re.sub(r'"?[\w.\-]+"?(\s*)$', lambda m: f'"{shader}"{m.group(1)}',
                  text[:at], count=1)
    return head + text[at:]


def _basetexture(vmt_text: str) -> str:
    from src.services import vmt_parse
    value = vmt_parse.parse(vmt_text).get('basetexture') or ''
    return value.replace('\\', '/').strip('/').lower()


def basetexture_changed(original: str, edited: str) -> bool:
    """Человек сам сменил $basetexture в правке части. Это выбор (белая основа
    под свечение, чужая текстура игры), а не устаревший путь: сборка его не
    подменяет, как и у главного материала (VpkTextureBuilder._basetexture_chosen)."""
    chosen = _basetexture(edited)
    return bool(chosen) and chosen != _basetexture(original)


def overlay_vmt(base: str, original: str, edited: str) -> str:
    """
    Переносит на VMT другого скина то, что человек поменял в VMT части.

    `original` — с чего человек начинал правку (VMT исходного материала),
    `edited` — что получилось. Изменённые и добавленные параметры ставятся в
    `base`, удалённые убираются, блок Proxies заменяется целиком, если его
    трогали. $basetexture переносится, только если человек выбрал его сам
    (basetexture_changed): иначе текстура у каждого скина своя (у синего —
    синяя, у австралия — золото).
    """
    from src.services import vmt_parse
    from src.services.vmt_effects import _set_key

    was, now = vmt_parse.parse(original), vmt_parse.parse(edited)
    keep = set() if basetexture_changed(original, edited) else {'basetexture'}
    out = base
    if now.shader and now.shader != was.shader:
        out = _set_shader(out, now.shader)
    for key, value in now.root.params.items():
        if key not in keep and was.root.params.get(key) != value:
            out = _set_key(out, _spelled(key), value)
    for key in was.root.params:
        if key != 'basetexture' and key not in now.root.params:
            out = _drop_key(out, _spelled(key))
    if now.block('proxies') != was.block('proxies'):
        theirs = _proxies_span(edited)
        mine = _proxies_span(out)
        block = edited[theirs[0]:theirs[1]] if theirs else ''
        if mine:
            out = out[:mine[0]] + block + out[mine[1]:]
        elif block:
            close = out.rfind('}')
            out = (out[:close].rstrip() + '\n' + block + '\n' + out[close:]
                   if close >= 0 else out + '\n' + block)
    return out
