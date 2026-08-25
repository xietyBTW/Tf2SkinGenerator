"""
Поза из анимации вместо bind-позы: то, что игрок реально видит.

Превью показывает reference-меш как есть — позу, в которой модель собирали.
Игра же всегда проигрывает последовательность, и у части моделей она заметно
двигает геометрию. У Мутировавшего молока хлеб в bind-позе торчит из банки на
2.58 единицы, а первый кадр `idle` смещает кости ровно на 2.69 — то есть в игре
хлеб внутри, а в превью снаружи. Из проверенных пушек геометрию двигает
`idle` у Шприцемёта (8.9), Ракетомёта (4.4), Боксёрских перчаток (3.7) и
Мутировавшего молока (2.7); у остальных отличается только поворот корня.

Как это работает:

    для каждой кости    M = T(позиция) · R(углы)      — локально относительно родителя
    мировая             W[i] = W[родитель] · M[i]
    матрица скиннинга   S[i] = W_анимации[i] · W_bind[i]⁻¹
    вершина             v' = Σ вес · (S[кость] · v)

Порядок эйлеровых углов — `Rz · Ry · Rx`. Он не угадан: в MDL каждая кость
несёт и углы, и посчитанный компилятором Valve кватернион, и на 35 костях
стоковых моделей этот порядок воспроизводит кватернион с ошибкой 0.000000
(ближайший другой — 0.78).

Матрица здесь — 12 чисел (три строки по четыре), обратная считается как для
жёсткого преобразования: Rᵀ и −Rᵀ·t. Numpy не нужен: вершин тысячи, не миллионы.

Модуль без Qt.
"""

from __future__ import annotations

import math
import os
import re
from typing import Dict, List, Optional, Sequence, Tuple

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Матрица 3x4: (m00 m01 m02 m03, m10 … m13, m20 … m23).
Mat = Tuple[float, ...]

IDENTITY: Mat = (1.0, 0.0, 0.0, 0.0,
                 0.0, 1.0, 0.0, 0.0,
                 0.0, 0.0, 1.0, 0.0)

#: Ниже этого сдвига (в единицах Source) поза считается совпадающей с bind —
#: пересчитывать вершины незачем. У большинства моделей разница ровно нулевая.
POSE_EPSILON = 1e-4


# ── Разбор SMD ───────────────────────────────────────────────────────────── #

def parse_nodes(smd_path: str) -> Dict[int, int]:
    """{кость: родитель} из секции nodes (−1 у корня). Пусто, если секции нет."""
    parents: Dict[int, int] = {}
    for line in _section(smd_path, "nodes"):
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            # id "имя может быть в кавычках с пробелами" parent
            parents[int(parts[0])] = int(parts[-1])
        except ValueError:
            continue
    return parents


def parse_frame0(smd_path: str) -> Dict[int, Tuple[Tuple[float, float, float],
                                                   Tuple[float, float, float]]]:
    """{кость: (позиция, углы)} из ПЕРВОГО кадра секции skeleton."""
    frame: Dict[int, Tuple[tuple, tuple]] = {}
    started = False
    for line in _section(smd_path, "skeleton"):
        low = line.lower()
        if low.startswith("time"):
            if started:
                break                       # начался второй кадр — хватит
            started = True
            continue
        parts = line.split()
        if len(parts) < 7:
            continue
        try:
            bone = int(parts[0])
            values = [float(x) for x in parts[1:7]]
        except ValueError:
            continue
        frame[bone] = (tuple(values[:3]), tuple(values[3:]))
    return frame


def _section(smd_path: str, name: str) -> List[str]:
    """Непустые строки секции SMD (`name` … `end`)."""
    out: List[str] = []
    try:
        with open(smd_path, "r", encoding="utf-8", errors="replace") as f:
            inside = False
            for line in f:
                stripped = line.strip()
                if not stripped:
                    continue
                if not inside:
                    inside = stripped.lower() == name
                    continue
                if stripped.lower() == "end":
                    break
                out.append(stripped)
    except OSError as exc:
        logger.debug(f"[pose] {os.path.basename(smd_path)}: {exc}")
    return out


# ── Матрицы ──────────────────────────────────────────────────────────────── #

def local_matrix(pos: Sequence[float], rot: Sequence[float]) -> Mat:
    """T(позиция) · Rz · Ry · Rx — конвенция studiomdl (см. док модуля)."""
    sx, cx = math.sin(rot[0]), math.cos(rot[0])
    sy, cy = math.sin(rot[1]), math.cos(rot[1])
    sz, cz = math.sin(rot[2]), math.cos(rot[2])
    return (
        cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx, pos[0],
        sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx, pos[1],
        -sy,     cy * sx,                cy * cx,                pos[2],
    )


def mul(a: Mat, b: Mat) -> Mat:
    """Произведение двух 3x4 (нижняя строка подразумевается 0 0 0 1)."""
    out = []
    for r in range(3):
        r4 = r * 4
        for c in range(3):
            out.append(a[r4] * b[c] + a[r4 + 1] * b[4 + c] + a[r4 + 2] * b[8 + c])
        out.append(a[r4] * b[3] + a[r4 + 1] * b[7] + a[r4 + 2] * b[11] + a[r4 + 3])
    return tuple(out)


def rigid_inverse(m: Mat) -> Mat:
    """Обратная к жёсткому преобразованию: Rᵀ и −Rᵀ·t (без общего обращения)."""
    r00, r01, r02, tx = m[0], m[1], m[2], m[3]
    r10, r11, r12, ty = m[4], m[5], m[6], m[7]
    r20, r21, r22, tz = m[8], m[9], m[10], m[11]
    return (
        r00, r10, r20, -(r00 * tx + r10 * ty + r20 * tz),
        r01, r11, r21, -(r01 * tx + r11 * ty + r21 * tz),
        r02, r12, r22, -(r02 * tx + r12 * ty + r22 * tz),
    )


def world_matrices(parents: Dict[int, int],
                   frame: Dict[int, Tuple[tuple, tuple]]) -> Dict[int, Mat]:
    """Мировые матрицы костей: W[i] = W[родитель] · локальная[i]."""
    world: Dict[int, Mat] = {}

    def resolve(bone: int, guard: int = 0) -> Mat:
        cached = world.get(bone)
        if cached is not None:
            return cached
        data = frame.get(bone)
        if data is None or guard > 256:      # битая иерархия — не зацикливаемся
            return IDENTITY
        local = local_matrix(*data)
        parent = parents.get(bone, -1)
        result = local if parent < 0 or parent == bone \
            else mul(resolve(parent, guard + 1), local)
        world[bone] = result
        return result

    for bone in frame:
        resolve(bone)
    return world


def transform_point(m: Mat, p: Sequence[float]) -> Tuple[float, float, float]:
    return (m[0] * p[0] + m[1] * p[1] + m[2] * p[2] + m[3],
            m[4] * p[0] + m[5] * p[1] + m[6] * p[2] + m[7],
            m[8] * p[0] + m[9] * p[1] + m[10] * p[2] + m[11])


def transform_dir(m: Mat, v: Sequence[float]) -> Tuple[float, float, float]:
    return (m[0] * v[0] + m[1] * v[1] + m[2] * v[2],
            m[4] * v[0] + m[5] * v[1] + m[6] * v[2],
            m[8] * v[0] + m[9] * v[1] + m[10] * v[2])


# ── Публичное ────────────────────────────────────────────────────────────── #

def skinning_matrices(ref_smd: str, pose_smd: str) -> Optional[Dict[int, Mat]]:
    """
    {кость: матрица} для перевода меша из bind-позы в позу анимации.

    None, если позу применять не нужно или нельзя: нет файлов, скелеты не
    совпали, поза совпадает с bind. Отказ здесь безобиден — превью просто
    останется в bind-позе, как было раньше.
    """
    if not ref_smd or not pose_smd:
        return None
    if not (os.path.isfile(ref_smd) and os.path.isfile(pose_smd)):
        return None

    bind = parse_frame0(ref_smd)
    pose = parse_frame0(pose_smd)
    if not bind or not pose:
        return None

    common = set(bind) & set(pose)
    if not common or len(common) < len(bind) * 0.5:
        logger.info(
            f"[pose] скелеты не сошлись ({len(common)} из {len(bind)} костей) — "
            f"оставляем bind-позу")
        return None

    parents = parse_nodes(ref_smd)
    # Корневым костям оставляем bind-положение. В анимации корень разворачивает
    # предмет так, как он лежит в руке (у скаттергана это ровно поворот на 90°),
    # а превью показывает предмет в его собственной позе — крутить всю модель
    # не надо. Двигаться должно только то, что движется ОТНОСИТЕЛЬНО корня.
    pose = dict(pose)
    for bone in list(pose):
        if parents.get(bone, -1) < 0 and bone in bind:
            pose[bone] = bind[bone]

    # Сравниваем ПОСЛЕ подмены корня: у большинства моделей вся разница с
    # bind-позой в нём и сидит, и трогать вершины незачем.
    if all(_same_bone(bind[b], pose[b]) for b in common):
        return None

    bind_world = world_matrices(parents, bind)
    pose_world = world_matrices(parents, pose)

    mats: Dict[int, Mat] = {}
    for bone in common:
        wb, wp = bind_world.get(bone), pose_world.get(bone)
        if wb is None or wp is None:
            continue
        mats[bone] = mul(wp, rigid_inverse(wb))
    return mats or None


def _same_bone(a: Tuple[tuple, tuple], b: Tuple[tuple, tuple]) -> bool:
    return all(abs(x - y) <= POSE_EPSILON
               for pair in zip(a, b) for x, y in zip(*pair))


#: Во сколько раз габариты вправе вырасти после позы. Реальная поза модель
#: не раздувает: у Мутировавшего молока она наоборот убирает выступ.
MAX_POSE_GROWTH = 3.0


def looks_sane(before: Sequence[Sequence[float]],
               after: Sequence[Sequence[float]]) -> bool:
    """
    Похожа ли поза на позу, а не на разлетевшийся меш.

    Страховка на незнакомых моделях: в игре их тысячи, проверить все нельзя, а
    цена ошибки — превью с геометрией во всю сцену. Отказ здесь возвращает
    bind-позу, то есть ровно прежнее поведение.
    """
    if not before or not after or len(before) != len(after):
        return False
    if any(p != p or p in (float("inf"), float("-inf"))
           for point in after for p in point):
        return False                          # NaN/inf — точно не поза
    return _extent(after) <= _extent(before) * MAX_POSE_GROWTH


def _extent(points: Sequence[Sequence[float]]) -> float:
    """Наибольшая сторона габаритного ящика."""
    lo = [min(p[i] for p in points) for i in range(3)]
    hi = [max(p[i] for p in points) for i in range(3)]
    return max(hi[i] - lo[i] for i in range(3))


def apply_to_vertex(mats: Dict[int, Mat], links: Sequence[Tuple[int, float]],
                    pos: Sequence[float], nrm: Sequence[float]) -> Tuple[tuple, tuple]:
    """Линейный скиннинг одной вершины. Без весов и костей — возвращает как было."""
    if not mats or not links:
        return tuple(pos), tuple(nrm)
    px = py = pz = nx = ny = nz = 0.0
    total = 0.0
    for bone, weight in links:
        m = mats.get(bone)
        if m is None or weight <= 0.0:
            continue
        tp = transform_point(m, pos)
        tn = transform_dir(m, nrm)
        px += tp[0] * weight; py += tp[1] * weight; pz += tp[2] * weight
        nx += tn[0] * weight; ny += tn[1] * weight; nz += tn[2] * weight
        total += weight
    if total <= 0.0:
        return tuple(pos), tuple(nrm)
    if abs(total - 1.0) > 1e-6:              # веса в SMD не всегда нормированы
        px /= total; py /= total; pz /= total
        nx /= total; ny /= total; nz /= total
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length > 1e-8:
        nx /= length; ny /= length; nz /= length
    else:
        nx, ny, nz = nrm
    return (px, py, pz), (nx, ny, nz)


# ── Поиск SMD анимации в QC ──────────────────────────────────────────────── #

_RE_SEQUENCE = re.compile(r'\$sequence\b(.*?)(?=\$|\Z)', re.IGNORECASE | re.DOTALL)
_RE_SMD = re.compile(r'"([^"]+\.smd)"', re.IGNORECASE)


def find_pose_smd(qc_path: str) -> Optional[str]:
    """
    SMD первой последовательности QC — та поза, в которой модель видна в игре.

    Берём именно первую: у косметики и оружия это `idle`, и другой игрок её
    почти всегда и видит. None, если последовательностей нет или файл потерян.
    """
    if not qc_path or not os.path.isfile(qc_path):
        return None
    try:
        with open(qc_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError:
        return None
    qc_dir = os.path.dirname(qc_path)
    for block in _RE_SEQUENCE.finditer(content):
        for ref in _RE_SMD.finditer(block.group(1)):
            candidate = os.path.join(qc_dir, ref.group(1).replace("\\", os.sep))
            if os.path.isfile(candidate):
                return candidate
    return None
