"""
Точки крепления (attachment) моделей Source — источник трансформа для
контрол-пойнта в редакторе частиц.

В игре анюжуал висит не «в воздухе», а на attachment модели (`unusual_0`…
`unusual_5` у оружия, `head`/свой у шапок): клиент каждый кадр кладёт в CP0
позицию И ОРИЕНТАЦИЮ этой точки. Ориентация — не украшение: по базису CP
раскладываются локальные системы координат инициализаторов скорости и
плоскость спрайтов при orientation_type 2/3.

Данные берутся из уже декомпилированных Crowbar моделей (кэш
~/.tf2skingen_cache/decompiled), никакой распаковки VPK здесь не происходит:
    QC:  $attachment "unusual_0" "weapon_bone" 0 3.77 45.82 rotate -90 0 0
    SMD: секции nodes (дерево костей) и skeleton/time 0 (бинд-поза)

Мировой трансформ точки = цепочка костей до корня × локальная матрица
attachment. Все матрицы — matrix3x4 в конвенции Source (столбцы = forward,
left, up; четвёртый столбец — позиция), углы — QAngle (pitch, yaw, roll) в
градусах, ровно в том виде, который принимает setControlPointOrientation.
"""

import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.services.smd_service import NON_REFERENCE_SMD_KEYWORDS
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: matrix3x4: три ряда по четыре числа
Matrix3x4 = List[List[float]]

_IDENTITY: Matrix3x4 = [[1.0, 0.0, 0.0, 0.0],
                        [0.0, 1.0, 0.0, 0.0],
                        [0.0, 0.0, 1.0, 0.0]]

#: $attachment "имя" "кость" X Y Z [rotate P Y R]
_ATTACHMENT_RE = re.compile(
    r'^\s*\$attachment\s+"?([^"\s]+)"?\s+"?([^"\s]+)"?\s+'
    r'(-?[\d.eE+]+)\s+(-?[\d.eE+]+)\s+(-?[\d.eE+]+)'
    r'(?:\s+.*?rotate\s+(-?[\d.eE+]+)\s+(-?[\d.eE+]+)\s+(-?[\d.eE+]+))?',
    re.IGNORECASE)


@dataclass(frozen=True)
class Attachment:
    """Точка крепления в мировых координатах бинд-позы."""
    name: str
    bone: str
    pos: Tuple[float, float, float]
    angles: Tuple[float, float, float]   # pitch, yaw, roll — как в QAngle


# ── Математика Source ────────────────────────────────────────────────────── #

def angle_matrix(pitch: float, yaw: float, roll: float) -> Matrix3x4:
    """Порт AngleMatrix(QAngle): матрица = (YAW * PITCH) * ROLL, градусы."""
    sy, cy = math.sin(math.radians(yaw)), math.cos(math.radians(yaw))
    sp, cp = math.sin(math.radians(pitch)), math.cos(math.radians(pitch))
    sr, cr = math.sin(math.radians(roll)), math.cos(math.radians(roll))
    crcy, crsy = cr * cy, cr * sy
    srcy, srsy = sr * cy, sr * sy
    return [
        [cp * cy, sp * srcy - crsy, sp * crcy + srsy, 0.0],
        [cp * sy, sp * srsy + crcy, sp * crsy - srcy, 0.0],
        [-sp, sr * cp, cr * cp, 0.0],
    ]


def matrix_angles(m: Matrix3x4) -> Tuple[float, float, float]:
    """Порт MatrixAngles: матрица → QAngle (pitch, yaw, roll) в градусах."""
    fwd = (m[0][0], m[1][0], m[2][0])
    left = (m[0][1], m[1][1], m[2][1])
    up_z = m[2][2]
    xy_dist = math.hypot(fwd[0], fwd[1])
    pitch = math.degrees(math.atan2(-fwd[2], xy_dist))
    if xy_dist > 0.001:
        yaw = math.degrees(math.atan2(fwd[1], fwd[0]))
        roll = math.degrees(math.atan2(left[2], up_z))
    else:
        # Взгляд почти вертикально: одна степень свободы потеряна (yaw == roll)
        yaw = math.degrees(math.atan2(-left[0], left[1]))
        roll = 0.0
    return (pitch, yaw, roll)


def radian_euler_matrix(rx: float, ry: float, rz: float,
                        pos: Tuple[float, float, float]) -> Matrix3x4:
    """Порт AngleMatrix(RadianEuler) — то, как SMD хранит поворот кости.

    В mathlib RadianEuler(x, y, z) превращается в QAngle(y, z, x) в градусах,
    поэтому порядок осей здесь именно такой, а не «как записано в файле».
    """
    m = angle_matrix(math.degrees(ry), math.degrees(rz), math.degrees(rx))
    for i in range(3):
        m[i][3] = pos[i]
    return m


def concat_transforms(a: Matrix3x4, b: Matrix3x4) -> Matrix3x4:
    """Порт ConcatTransforms: out = a * b (b применяется первым)."""
    out: Matrix3x4 = [[0.0] * 4 for _ in range(3)]
    for i in range(3):
        for j in range(3):
            out[i][j] = (a[i][0] * b[0][j] + a[i][1] * b[1][j] + a[i][2] * b[2][j])
        out[i][3] = (a[i][0] * b[0][3] + a[i][1] * b[1][3]
                     + a[i][2] * b[2][3] + a[i][3])
    return out


# ── Разбор файлов ────────────────────────────────────────────────────────── #

def parse_qc_attachments(qc_text: str) -> List[dict]:
    """Строки $attachment из QC → [{name, bone, offset, angles}]."""
    out: List[dict] = []
    for line in qc_text.splitlines():
        m = _ATTACHMENT_RE.match(line)
        if m is None:
            continue
        name, bone = m.group(1), m.group(2)
        offset = tuple(float(m.group(i)) for i in (3, 4, 5))
        angles = ((float(m.group(6)), float(m.group(7)), float(m.group(8)))
                  if m.group(6) is not None else (0.0, 0.0, 0.0))
        out.append({"name": name, "bone": bone,
                    "offset": offset, "angles": angles})
    return out


def parse_smd_bind_pose(smd_text: str) -> Dict[str, Matrix3x4]:
    """Секции nodes + skeleton/time 0 → мировые матрицы костей бинд-позы."""
    lines = smd_text.splitlines()
    parents: Dict[int, int] = {}
    names: Dict[int, str] = {}
    local: Dict[int, Matrix3x4] = {}

    section = ""
    frame_seen = False
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        if low in ("nodes", "skeleton", "triangles", "vertexanimation"):
            section = low
            continue
        if low == "end":
            section = ""
            continue
        if section == "nodes":
            m = re.match(r'^(\d+)\s+"([^"]*)"\s+(-?\d+)', line)
            if m:
                idx = int(m.group(1))
                names[idx] = m.group(2)
                parents[idx] = int(m.group(3))
        elif section == "skeleton":
            if low.startswith("time"):
                # Нужен только первый кадр — это и есть бинд-поза
                if frame_seen:
                    break
                frame_seen = True
                continue
            parts = line.split()
            if len(parts) < 7:
                continue
            try:
                idx = int(parts[0])
                vals = [float(v) for v in parts[1:7]]
            except ValueError:
                continue
            local[idx] = radian_euler_matrix(
                vals[3], vals[4], vals[5], (vals[0], vals[1], vals[2]))

    world: Dict[int, Matrix3x4] = {}

    def resolve(idx: int, guard: int = 0) -> Matrix3x4:
        if idx in world:
            return world[idx]
        mat = local.get(idx)
        if mat is None:
            return [row[:] for row in _IDENTITY]
        parent = parents.get(idx, -1)
        # guard — защита от битого дерева с циклом
        if parent >= 0 and parent != idx and guard < 128:
            mat = concat_transforms(resolve(parent, guard + 1), mat)
        world[idx] = mat
        return mat

    return {names[i]: resolve(i) for i in names if i in local}


def reference_smd_for_qc(qc_path: str) -> Optional[str]:
    """Путь к reference-SMD модели — из него же строится меш для превью."""
    smd = _reference_smd(Path(qc_path))
    return None if smd is None else str(smd)


def _reference_smd(qc_path: Path) -> Optional[Path]:
    """Reference-SMD рядом с QC: не физика, не анимация, не поза."""
    candidates = [p for p in qc_path.parent.glob("*.smd")
                  if not any(k in p.stem.lower()
                             for k in NON_REFERENCE_SMD_KEYWORDS)]
    if not candidates:
        return None
    # Совпадение с именем QC надёжнее любого перебора
    same = [p for p in candidates if p.stem.lower() == qc_path.stem.lower()]
    return (same or candidates)[0]


def attachments_from_qc(qc_path: str) -> List[Attachment]:
    """Мировые трансформы всех attachment модели по её QC + reference SMD.

    Кости, которых нет в SMD, дают точку в начале координат — это лучше, чем
    молча выкинуть attachment: пользователь увидит её в списке и поймёт, что
    модель декомпилирована не полностью.
    """
    qc = Path(qc_path)
    try:
        qc_text = qc.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.warning(f"QC не прочитан ({qc_path}): {exc}")
        return []
    raw = parse_qc_attachments(qc_text)
    if not raw:
        return []

    bones: Dict[str, Matrix3x4] = {}
    smd = _reference_smd(qc)
    if smd is not None:
        try:
            bones = parse_smd_bind_pose(
                smd.read_text(encoding="utf-8", errors="ignore"))
        except OSError as exc:
            logger.warning(f"SMD не прочитан ({smd}): {exc}")
    lower = {k.lower(): v for k, v in bones.items()}

    out: List[Attachment] = []
    for item in raw:
        local = angle_matrix(*item["angles"])
        for i in range(3):
            local[i][3] = item["offset"][i]
        bone_mat = lower.get(item["bone"].lower())
        world = local if bone_mat is None else concat_transforms(bone_mat, local)
        out.append(Attachment(
            name=item["name"],
            bone=item["bone"],
            pos=(world[0][3], world[1][3], world[2][3]),
            angles=matrix_angles(world),
        ))
    return out


# ── Модели из кэша декомпиляции ──────────────────────────────────────────── #

def list_decompiled_models() -> List[Tuple[str, str]]:
    """Модели, уже разобранные Crowbar: [(подпись, путь к QC)], по алфавиту.

    Своей распаковки VPK здесь нет намеренно: Crowbar долгий, а модели
    попадают в кэш при обычной работе на вкладках оружия и шапок.
    """
    cache = Path(os.path.expanduser("~")) / ".tf2skingen_cache" / "decompiled"
    out: List[Tuple[str, str]] = []
    if not cache.is_dir():
        return out
    for entry in cache.iterdir():
        if not entry.is_dir():
            continue
        meta_file = entry / "_cache_meta.json"
        qc_name = None
        label = entry.name
        if meta_file.is_file():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                qc_name = meta.get("qc_filename")
                label = meta.get("weapon_key") or label
            except Exception:
                pass
        qc = entry / qc_name if qc_name else next(iter(entry.glob("*.qc")), None)
        if qc is None or not Path(qc).is_file():
            continue
        out.append((label, str(qc)))
    out.sort(key=lambda pair: pair[0].lower())
    return out
