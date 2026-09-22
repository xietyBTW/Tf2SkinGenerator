"""
Экран модели — vgui-панель на attachment'ах ``controlpanelN_ll`` / ``_ur``.

Циферблат Звона смерти в игре не геометрия: движок рисует на модели
vgui-панель (``scripts/screens/pda_spy_invis_pocket.res``) в прямоугольнике
между двумя attachment'ами, а её картинки — ``pocket_watch_bg`` (фон) и
``pocket_watch_fg`` (заполнение круглой шкалы). В меше их нет, и превью
показывало пустой циферблат — положенная на карточку картинка не
появлялась ни в кадре, ни от первого лица.

Здесь панель становится обычной геометрией: отдельный SMD с квадом фона и
веером заполнения, привязанный к кости нижнего левого угла. Дальше он идёт
как любая бодигруппа — скиннинг, поза, вид от первого лица, раскладка
текстур по имени материала, — и ничего специального о нём знать не нужно.

Геометрия по конвенции Source: панель лежит в плоскости XY attachment'а
нижнего левого угла, X — ширина, Y — высота, Z — нормаль; ``pixels`` — размер
панели в vgui-пикселях (``vgui_screens.txt``), ``rect`` — где в ней лежит
шкала с картинками (``.res``).
"""

from __future__ import annotations

import math
import os
import re
from typing import Dict, List, Optional, Sequence, Tuple

from src.services import smd_pose
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Экраны известных моделей — по стему ``$modelname`` в QC.
#: pixels — размер панели (vgui_screens.txt), rect — (x, y, w, h) шкалы в
#: ней (.res), bg/fg — имена материалов картинок, progress — какую долю
#: круга закрывает fg: половина показывает и фон, и заполнение разом.
SCREENS: Dict[str, dict] = {
    'v_watch_pocket_spy': {
        'pixels': (280, 100),
        'rect': (10, 10, 260, 80),
        'bg': 'pocket_watch_bg',
        'fg': 'pocket_watch_fg',
        'progress': 0.5,
    },
}

_RE_MODELNAME = re.compile(r'^\s*\$modelname\s+"([^"]+)"', re.IGNORECASE | re.MULTILINE)
_RE_ATTACH = re.compile(
    r'^\s*\$attachment\s+"controlpanel(\d+)_(ll|ur)"\s+"([^"]+)"'
    r'\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)'
    r'(?:\s+rotate\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+))?',
    re.IGNORECASE | re.MULTILINE)


def screen_spec(qc_path: str) -> Optional[dict]:
    """Описание экрана модели по её ``$modelname``, если он известен."""
    try:
        with open(qc_path, 'r', encoding='utf-8', errors='replace') as f:
            text = f.read()
    except OSError:
        return None
    m = _RE_MODELNAME.search(text)
    if not m:
        return None
    stem = os.path.splitext(os.path.basename(m.group(1).replace('\\', '/')))[0].lower()
    return SCREENS.get(stem)


def _attachments(qc_path: str) -> Dict[Tuple[int, str], Tuple[str, tuple, tuple]]:
    """{(номер, 'll'|'ur'): (кость, смещение, поворот в градусах)}."""
    try:
        with open(qc_path, 'r', encoding='utf-8', errors='replace') as f:
            text = f.read()
    except OSError:
        return {}
    out = {}
    for m in _RE_ATTACH.finditer(text):
        offset = tuple(float(m.group(i)) for i in (4, 5, 6))
        rotate = tuple(float(m.group(i)) if m.group(i) else 0.0 for i in (7, 8, 9))
        out[(int(m.group(1)), m.group(2).lower())] = (m.group(3), offset, rotate)
    return out


def _frame(world: smd_pose.Mat, offset: Sequence[float], rotate: Sequence[float]) -> smd_pose.Mat:
    """Матрица attachment'а: кость, затем его собственные смещение и поворот."""
    local = smd_pose.local_matrix(offset, tuple(math.radians(a) for a in rotate))
    return smd_pose.mul(world, local)


def _pos(m: smd_pose.Mat) -> Tuple[float, float, float]:
    return (m[3], m[7], m[11])


def _axis(m: smd_pose.Mat, c: int) -> Tuple[float, float, float]:
    return (m[c], m[4 + c], m[8 + c])


def _quad(reference_smd: str, qc_path: str, index: int = 0):
    """
    Углы экрана в пространстве reference-SMD и кость, к которой он привязан:
    (origin, ширина-вектор, высота-вектор, нормаль, кость) либо None.
    """
    found = _attachments(qc_path)
    ll = found.get((index, 'll'))
    ur = found.get((index, 'ur'))
    if not ll or not ur:
        return None
    names = smd_pose.parse_node_names(reference_smd)
    by_name = {name: bone for bone, name in names.items()}
    if ll[0] not in by_name or ur[0] not in by_name:
        logger.debug(f"[screen] костей {ll[0]!r}/{ur[0]!r} нет в {os.path.basename(reference_smd)}")
        return None
    world = smd_pose.world_matrices(smd_pose.parse_nodes(reference_smd),
                                    smd_pose.parse_frame0(reference_smd))
    ll_m = _frame(world[by_name[ll[0]]], ll[1], ll[2])
    ur_m = _frame(world[by_name[ur[0]]], ur[1], ur[2])
    origin, corner = _pos(ll_m), _pos(ur_m)
    x_axis, y_axis, z_axis = _axis(ll_m, 0), _axis(ll_m, 1), _axis(ll_m, 2)
    delta = tuple(corner[i] - origin[i] for i in range(3))
    width = sum(delta[i] * x_axis[i] for i in range(3))
    height = sum(delta[i] * y_axis[i] for i in range(3))
    if width <= 1e-4 or height <= 1e-4:
        logger.debug(f"[screen] вырожденный экран: {width:.3f}×{height:.3f}")
        return None
    return (origin, tuple(a * width for a in x_axis), tuple(a * height for a in y_axis),
            z_axis, by_name[ll[0]])


def _rect_points(spec: dict) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """Прямоугольник шкалы в долях панели: (u0, v0), (u1, v1); v — сверху."""
    pw, ph = spec['pixels']
    x, y, w, h = spec['rect']
    return (x / pw, y / ph), ((x + w) / pw, (y + h) / ph)


def _ray_to_rect(cx: float, cy: float, angle: float,
                 u0: float, v0: float, u1: float, v1: float) -> Tuple[float, float]:
    """Точка на границе прямоугольника по лучу из центра под углом (v — вниз)."""
    dx, dy = math.cos(angle), math.sin(angle)
    best = float('inf')
    for edge, d in (((u0 - cx), dx), ((u1 - cx), dx), ((v0 - cy), dy), ((v1 - cy), dy)):
        if abs(d) > 1e-9:
            t = edge / d
            if t > 0:
                best = min(best, t)
    return cx + dx * best, cy + dy * best


def _triangles(spec: dict) -> Tuple[List[Tuple[tuple, tuple, tuple]], List[Tuple[tuple, tuple, tuple]]]:
    """
    Треугольники фона и заполнения в долях ПАНЕЛИ (u вправо, v вниз).

    Фон — квад шкалы. Заполнение — веер от центра по часовой стрелке от
    12 часов на долю ``progress`` (так рисует CircularProgressBar), обрезанный
    по прямоугольнику шкалы.
    """
    (u0, v0), (u1, v1) = _rect_points(spec)
    bg = [((u0, v0), (u0, v1), (u1, v1)), ((u0, v0), (u1, v1), (u1, v0))]

    fg: List[Tuple[tuple, tuple, tuple]] = []
    progress = max(0.0, min(1.0, float(spec.get('progress', 0.5))))
    if progress > 0:
        cx, cy = (u0 + u1) / 2, (v0 + v1) / 2
        start = -math.pi / 2                      # 12 часов; v вниз → по часовой
        steps = max(1, int(round(72 * progress)))
        prev = _ray_to_rect(cx, cy, start, u0, v0, u1, v1)
        for i in range(1, steps + 1):
            angle = start + 2 * math.pi * progress * i / steps
            point = _ray_to_rect(cx, cy, angle, u0, v0, u1, v1)
            fg.append(((cx, cy), point, prev))     # против часовой в Y-вверх — лицом наружу
            prev = point
    return bg, fg


def write_screen_smd(reference_smd: str, qc_path: str, out_path: str,
                     spec: Optional[dict] = None) -> Optional[str]:
    """
    Пишет SMD с экраном модели. None — экрана нет (неизвестная модель или
    в QC нет attachment'ов controlpanel0).

    Скелет копируется из reference-SMD целиком: SMD экрана обязан говорить о
    тех же костях, чтобы конвертер и скиннинг считали его частью модели.
    """
    spec = spec or screen_spec(qc_path)
    if not spec:
        return None
    quad = _quad(reference_smd, qc_path)
    if quad is None:
        return None
    origin, wide, tall, normal, bone = quad
    (u0, v0), (u1, v1) = _rect_points(spec)

    def vertex(u: float, v: float, lift: float = 0.0) -> str:
        # Панель: u вправо, v вниз от верхнего края; SMD-UV — от нижнего.
        # `lift` — отступ по нормали: заполнение лежит НАД фоном, а не в той же
        # плоскости, иначе они мерцают друг сквозь друга.
        pos = tuple(origin[i] + wide[i] * u + tall[i] * (1.0 - v) + normal[i] * lift
                    for i in range(3))
        tu = (u - u0) / (u1 - u0)
        tv = 1.0 - (v - v0) / (v1 - v0)
        return (f"{bone} {pos[0]:.6f} {pos[1]:.6f} {pos[2]:.6f} "
                f"{normal[0]:.6f} {normal[1]:.6f} {normal[2]:.6f} "
                f"{tu:.6f} {tv:.6f} 1 {bone} 1.000000")

    bg, fg = _triangles(spec)
    lines = ['version 1', 'nodes']
    lines += smd_pose._section(reference_smd, 'nodes')
    lines += ['end', 'skeleton', 'time 0']
    lines += [ln for ln in smd_pose._section(reference_smd, 'skeleton')
              if not ln.lower().startswith('time')]
    lines += ['end', 'triangles']
    for material, tris, lift in ((spec['bg'], bg, 0.0), (spec['fg'], fg, 0.02)):
        for tri in tris:
            lines.append(material)
            lines += [vertex(*p, lift=lift) for p in tri]
    lines.append('end')
    try:
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
    except OSError as exc:
        logger.warning(f"[screen] SMD экрана не записан: {exc}")
        return None
    logger.info(f"[screen] экран {spec['bg']}/{spec['fg']} → {os.path.basename(out_path)}")
    return out_path


def screen_hints(decomp_dir: str) -> Dict[str, dict]:
    """
    Как рисовать материалы экрана: с альфой и с двух сторон.

    Картинки панели — vgui-материалы (UnlitGeneric, $translucent), их VMT
    лежат не в $cdmaterials модели, и обычный разбор их не находит. Без альфы
    вокруг круглой шкалы был бы чёрный квадрат.
    """
    try:
        qcs = [os.path.join(decomp_dir, f) for f in os.listdir(decomp_dir)
               if f.lower().endswith('.qc')]
    except OSError:
        return {}
    for qc in qcs:
        spec = screen_spec(qc)
        if spec:
            return {name: {'blend': 'alpha', 'twoSided': True}
                    for name in (spec['bg'], spec['fg'])}
    return {}


def screen_smds(decomp_dir: str, reference_smd: str) -> List[str]:
    """
    SMD экрана модели из папки декомпиляции — как ещё одна часть модели.

    Файл кладётся рядом с reference, чтобы жить столько же, сколько кэш
    декомпиляции; перезаписывается при каждом обращении — он дешёвый.
    """
    if not reference_smd or not os.path.isfile(reference_smd):
        return []
    try:
        qcs = [os.path.join(decomp_dir, f) for f in os.listdir(decomp_dir)
               if f.lower().endswith('.qc')]
    except OSError:
        return []
    for qc in qcs:
        spec = screen_spec(qc)
        if not spec:
            continue
        out = os.path.join(decomp_dir, '__screen0.smd')
        path = write_screen_smd(reference_smd, qc, out, spec)
        return [path] if path else []
    return []
