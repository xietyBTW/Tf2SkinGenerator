"""
Анимированная сцена вьюмодели: скелет, меши и дорожки кадров для Three.js.

Статичная поза запекается в OBJ ([viewmodel_scene]) — для одного кадра это
проще всего. Анимацию так не отдать: полсотни кадров означали бы полсотни
запечённых мешей. Поэтому здесь меш отдаётся ОДИН раз в bind-позе, а движение
— дорожками костей, и складывает их уже Three.js на видеокарте.

Ключевая мысль: скелет в сцене ОДИН — рук. Оружие не имеет в ней своего
скелета, оно подвешено к костям руки:

  * кость оружия, попавшая в `$bonemerge`, ведётся одноимённой костью руки;
  * все остальные ведутся ближайшим слитым предком — ниже него иерархия
    оружия жёсткая и от позы не зависит (см. viewmodel_pose.driving_bones).

Поэтому геометрия оружия отдаётся уже «запечённой в bind-позу руки»: та же
математика, что и для статичной сцены, только вместо кадра анимации берётся
reference-скелет рук. Дальше Three.js гоняет её обычным скиннингом.

Оси НЕ конвертируются. Сцена остаётся в координатах Source, а разворот в оси
Three.js делает один поворот корня на -90° вокруг X — он же (x,y,z) → (x,z,-y).
Разворачивать вручную ещё и кватернионы костей значило бы завести второй
источник ошибок ради того же результата.

Модуль без Qt.
"""

from __future__ import annotations

import math
import os
from typing import Dict, List, Optional, Sequence, Tuple

from src.services import smd_pose, viewmodel_pose
from src.services.smd_to_obj_service import SmdToObjService
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Поворот корня сцены, переводящий оси Source в оси Three.js.
#: Тот же (x,y,z) → (x, z, -y), что и в конвертере OBJ, только одним узлом.
ROOT_ROTATION_X = -math.pi / 2

#: Сколько весов на вершину отдаём в Three.js. Формат skinIndex/skinWeight —
#: всегда vec4; лишние веса в SMD встречаются, их приходится усекать.
MAX_WEIGHTS = 4

#: Округление чисел в выгрузке. Сцена едет в браузер строкой JSON, и полная
#: точность double тратит на ней больше половины объёма, ничего не давая:
#: единицы Source — это дюймы, а UV и кватернионы лежат в пределах единицы.
POSITION_DIGITS = 4
UV_DIGITS = 5
WEIGHT_DIGITS = 4
QUATERNION_DIGITS = 6


def build_scene(
    *,
    arms_ref_smd: str,
    weapon_ref_smd: str = "",
    anim_smd: str = "",
    clip_name: str = "",
    fps: float = 30.0,
    loop: bool = True,
    weapon_merge_bones: Optional[Sequence[str]] = None,
    weapon_carrier_smd: str = "",
    carrier_extra_smds: Sequence[str] = (),
    weapon_extra_smds: Sequence[str] = (),
    editable_mats: Optional[Sequence[str]] = None,
    arms_extra_smds: Sequence[str] = (),
    arms_include_mats: Optional[set] = None,
    frame_step: int = 1,
) -> Optional[dict]:
    """
    Готовит данные анимированной сцены для вьювера.

    Args:
        arms_ref_smd:   reference SMD рук — он же bind-поза и источник скелета.
        weapon_ref_smd: reference SMD оружия. Пусто — предмет показывается
            СВОЕЙ моделью вида (часы шпиона): руки и предмет там в одном
            меше, и сажать в руку нечего.
        editable_mats:  какие материалы правит пользователь. Нужно как раз
            модели вида: руки в её меше вперемешку с предметом.
        anim_smd:       SMD последовательности (кадры).
        clip_name/fps/loop: как проигрывать (из каталога анимаций).
        weapon_merge_bones: кости из `$bonemerge` в QC оружия. Запасной
            вариант: обычно список костей берётся из кадров анимации —
            Crowbar `$bonemerge` выводит не всегда, а там, где выводит,
            он оказывается уже отобранного по кадрам (у револьвера одна
            кость вместо четырёх, и барабан оставался неподвижным).
        carrier_extra_smds: бодигруппы носителя — шланг медигана лежит
            отдельным SMD, и без него пушка в кадре обрублена.
        weapon_carrier_smd: reference SMD пушки, НА КОТОРОЙ висит модель.
            Праздничное оружие — гирлянда, а не пушка: в `c_medigun_xmas`
            лежат одни огоньки, и без носителя они висели бы в пустой
            руке. Носитель показывается, но остаётся нередактируемым:
            перекрашивают гирлянду, а не медиган под ней.
        *_extra_smds:   бодигруппы соответствующей части, видимые по
            умолчанию: правая рука пиро и инженера объявлена именно так.
        arms_include_mats: оставить у рук только эти материалы — ракета
            солдата лежит в модели рук и вне перезарядки не нужна.
        frame_step:     брать каждый N-й кадр. Для длинных анимаций способ
                        уменьшить объём, не трогая всё остальное.

    Returns:
        Словарь для `window.loadViewmodelAnimated`, либо None — если скелеты не
        сошлись или оружие не крепится к руке.
    """
    bind = viewmodel_pose.load_rig(arms_ref_smd)
    if bind is None:
        logger.warning(f"[anim] нет скелета рук: {_short(arms_ref_smd)}")
        return None

    order = _bone_order(bind)
    index_of = {name: i for i, name in enumerate(order)}

    # Какие кости оружия садятся в руку, решают КАДРЫ анимации, а не bind рук:
    # в bind-позе `weapon_bone_1..4` у пиро свалены в одну точку, у шпиона
    # выстроены лесенкой — по ним не отличить свою кость оружия от чужой.
    weapon_part = None
    editable = list(editable_mats or ())
    if weapon_ref_smd:
        merge = _merge_names(weapon_ref_smd, anim_smd) or weapon_merge_bones
        weapon_part = _weapon_part(weapon_ref_smd, bind, index_of, merge,
                                   weapon_extra_smds)
        if weapon_part is None:
            return None
        editable = list(editable_mats or weapon_part["materials"])
        if weapon_carrier_smd:
            _add_carrier(weapon_part, weapon_carrier_smd, bind, index_of,
                         anim_smd, carrier_extra_smds)
    arms_part = _arms_part(arms_ref_smd, bind, index_of,
                           arms_extra_smds, arms_include_mats)
    if arms_part is None:
        return None

    clip = _clip(anim_smd, order, clip_name, fps, frame_step)
    if clip is None:
        logger.warning(f"[anim] нет кадров: {_short(anim_smd)}")
        return None
    clip["loop"] = bool(loop)

    return {
        "rootRotationX": ROOT_ROTATION_X,
        "bones": _bones(bind, order, index_of),
        "parts": [p for p in (weapon_part, arms_part) if p],
        "weaponMaterials": editable,
        "clip": clip,
    }


def build_clip(
    *,
    arms_ref_smd: str,
    anim_smd: str,
    clip_name: str = "",
    fps: float = 30.0,
    loop: bool = True,
    frame_step: int = 1,
) -> Optional[dict]:
    """Только дорожки кадров — без геометрии, скелета и текстур.

    Смена анимации меняет ровно это. Меш, скелет, материалы и картинки у
    одного оружия одни и те же, и пересобирать их значит каждый раз заново
    распаковывать VTF и перечитывать SMD: замер дал секунду на нажатие вместо
    нескольких миллисекунд.

    Дорожки адресуют кости и по имени тоже, поэтому клип ложится на уже
    собранную сцену без предположений о совпадении порядка костей.
    """
    bind = viewmodel_pose.load_rig(arms_ref_smd)
    if bind is None:
        logger.warning(f"[anim] нет скелета рук: {_short(arms_ref_smd)}")
        return None
    clip = _clip(anim_smd, _bone_order(bind), clip_name, fps, frame_step)
    if clip is None:
        logger.warning(f"[anim] нет кадров: {_short(anim_smd)}")
        return None
    clip["loop"] = bool(loop)
    return clip


def _merge_names(weapon_ref_smd: str, anim_smd: str) -> Optional[List[str]]:
    """Имена костей оружия, которые ведёт анимация класса. None — решать позже.

    Отбор идёт по кадрам последовательности: только там видно, стоит ли
    одноимённая кость там же, где у оружия, или принадлежит другому оружию из
    того же набора (см. `viewmodel_pose._rigid_subset`). Кадров берём три —
    начало, середину и конец: в первом кадре чужая кость нередко ещё на месте.
    """
    total = len(smd_pose.parse_frames(anim_smd))
    if not total:
        return None
    frames = sorted({0, total // 2, total - 1})
    names = viewmodel_pose.merged_bone_names(
        weapon_ref_smd,
        [viewmodel_pose.load_rig(anim_smd, n) for n in frames])
    return names or None


# ── Скелет ────────────────────────────────────────────────────────────────── #

def _bone_order(bind: viewmodel_pose.Rig) -> List[str]:
    """Имена костей так, чтобы родитель всегда шёл раньше ребёнка.

    Three.js собирает иерархию добавлением ребёнка в уже созданного родителя,
    и обратный порядок оставил бы часть костей висеть в корне.
    """
    order: List[str] = []
    seen = set()

    def add(bone: int, guard: int = 0) -> None:
        name = bind.names.get(bone)
        if name is None or name in seen or guard > 256:
            return
        parent = bind.parents.get(bone, -1)
        if parent >= 0 and parent != bone:
            add(parent, guard + 1)
        if name not in seen:
            seen.add(name)
            order.append(name)

    for bone in sorted(bind.names):
        add(bone)
    return order


def _bones(bind: viewmodel_pose.Rig, order: List[str],
           index_of: Dict[str, int]) -> List[dict]:
    """Кости в bind-позе: локальное смещение и поворот кватернионом."""
    by_name = {name: bone for bone, name in bind.names.items()}
    out: List[dict] = []
    for name in order:
        bone = by_name[name]
        pos, rot = bind.frame.get(bone, ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)))
        parent = bind.parents.get(bone, -1)
        parent_name = bind.names.get(parent) if parent >= 0 and parent != bone else None
        out.append({
            "name": name,
            "parent": index_of.get(parent_name, -1) if parent_name else -1,
            "position": [round(float(p), POSITION_DIGITS) for p in pos],
            "quaternion": [round(q, QUATERNION_DIGITS)
                           for q in quaternion_from_euler(rot)],
        })
    return out


def quaternion_from_euler(rot: Sequence[float]) -> Tuple[float, float, float, float]:
    """Углы SMD → кватернион (x, y, z, w).

    Матрицу строит `smd_pose.local_matrix` — конвенция studiomdl (Rz·Ry·Rx)
    там уже выверена по кватернионам из MDL, и повторять её вывод здесь значило
    бы завести второй источник ошибок.
    """
    m = smd_pose.local_matrix((0.0, 0.0, 0.0), rot)
    m00, m01, m02 = m[0], m[1], m[2]
    m10, m11, m12 = m[4], m[5], m[6]
    m20, m21, m22 = m[8], m[9], m[10]

    trace = m00 + m11 + m22
    if trace > 0.0:
        s = math.sqrt(trace + 1.0) * 2.0
        return ((m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s, 0.25 * s)
    if m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2.0
        return (0.25 * s, (m01 + m10) / s, (m02 + m20) / s, (m21 - m12) / s)
    if m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2.0
        return ((m01 + m10) / s, 0.25 * s, (m12 + m21) / s, (m02 - m20) / s)
    s = math.sqrt(1.0 + m22 - m00 - m11) * 2.0
    return ((m02 + m20) / s, (m12 + m21) / s, 0.25 * s, (m10 - m01) / s)


# ── Части сцены ───────────────────────────────────────────────────────────── #

def _triangles(smds: Sequence[str]) -> Dict[str, list]:
    """Треугольники по материалам из нескольких SMD одной модели."""
    merged: Dict[str, list] = {}
    for path in smds:
        if not path:
            continue
        for material, tris in SmdToObjService._parse_triangles_by_mat(path).items():
            merged.setdefault(material, []).extend(tris)
    return merged


def _arms_part(arms_ref_smd: str, bind: viewmodel_pose.Rig,
               index_of: Dict[str, int],
               extra_smds: Sequence[str] = (),
               include_mats: Optional[set] = None) -> Optional[dict]:
    """Руки: меш как есть, веса из SMD, кости — по имени.

    Args:
        extra_smds: бодигруппы, видимые по умолчанию. У пиро и инженера ПРАВАЯ
            рука объявлена отдельной бодигруппой, и без них в сцене оставалась
            одна левая.
        include_mats: оставить только эти материалы. В модели рук лежит не
            только рука: у солдата там же ракета, и вне перезарядки её быть не
            должно.
    """
    triangles = _triangles([arms_ref_smd, *extra_smds])
    if include_mats is not None:
        triangles = {name: tris for name, tris in triangles.items()
                     if name in include_mats}
    if not triangles:
        logger.warning(f"[anim] пустой меш рук: {_short(arms_ref_smd)}")
        return None

    def links_of(vert: dict) -> List[Tuple[int, float]]:
        out = []
        for bone, weight in vert.get("links") or ():
            slot = index_of.get(bind.names.get(bone, ""))
            if slot is not None and weight > 0.0:
                out.append((slot, float(weight)))
        return out

    return _pack(triangles, links_of, "arms")


def _weapon_part(weapon_ref_smd: str, bind: viewmodel_pose.Rig,
                 index_of: Dict[str, int],
                 merge_bones: Optional[Sequence[str]],
                 extra_smds: Sequence[str] = ()) -> Optional[dict]:
    """
    Оружие, запечённое в bind-позу руки и подвешенное к её костям.

    Своего скелета у него в сцене нет: каждая вершина целиком принадлежит той
    кости руки, которая ведёт её кость оружия.

    Args:
        extra_smds: бодигруппы того же меша (откидные части, прицелы). Скелет
            у них общий с основным, поэтому и матрицы те же.
    """
    drivers = viewmodel_pose.driving_bones(weapon_ref_smd, bind, merge_bones)
    if not drivers:
        # Не поломка сборки: ранцы, знамёна и часы-«статик» к руке и не
        # крепятся. Отдельное исключение, чтобы наверху сказать об этом
        # по-человечески, а не «сцена не собралась».
        raise viewmodel_pose.NotHeldInHands(_short(weapon_ref_smd))
    mats = viewmodel_pose.bonemerge_skinning(weapon_ref_smd, bind, merge_bones)
    if not mats:
        return None

    triangles = _triangles([weapon_ref_smd, *extra_smds])
    if not triangles:
        logger.warning(f"[anim] пустой меш оружия: {_short(weapon_ref_smd)}")
        return None
    # Геометрия переезжает в bind-позу руки — ровно как в статичной сцене.
    SmdToObjService._apply_skinning(triangles, mats, os.path.basename(weapon_ref_smd))

    def links_of(vert: dict) -> List[Tuple[int, float]]:
        links = vert.get("links") or ()
        bone = links[0][0] if links else -1
        slot = index_of.get(drivers.get(bone, ""))
        return [(slot, 1.0)] if slot is not None else []

    return _pack(triangles, links_of, "weapon")


def _add_carrier(part: dict, carrier_smd: str, bind: viewmodel_pose.Rig,
                 index_of: Dict[str, int], anim_smd: str,
                 extra_smds: Sequence[str] = ()) -> None:
    """Дописывает в часть с оружием пушку-носитель. Не вышло — молча пропускаем.

    Носитель — обычная модель оружия, только собранная теми же костями: у
    праздничного минигана гирлянда и сам миниган садятся в руку одинаково.
    Материалы носителя в `weaponMaterials` не попадают, поэтому перетаскивание
    текстуры на него не действует.
    """
    try:
        carrier = _weapon_part(carrier_smd, bind, index_of,
                               _merge_names(carrier_smd, anim_smd), extra_smds)
    except viewmodel_pose.NotHeldInHands:
        carrier = None
    if carrier is None:
        logger.info(f"[anim] носитель не собрался: {_short(carrier_smd)}")
        return
    offset = len(part["positions"]) // 3
    for key in ("positions", "normals", "uvs", "skinIndex", "skinWeight"):
        part[key].extend(carrier[key])
    for group in carrier["groups"]:
        part["groups"].append({**group, "start": group["start"] + offset})
    part["materials"].extend(carrier["materials"])


def _pack(triangles: Dict[str, list], links_of, kind: str) -> dict:
    """Треугольники по материалам → плоские массивы и группы для Three.js."""
    positions: List[float] = []
    normals: List[float] = []
    uvs: List[float] = []
    skin_index: List[int] = []
    skin_weight: List[float] = []
    groups: List[dict] = []

    for material, tris in triangles.items():
        start = len(positions) // 3
        for tri in tris:
            for vert in tri:
                positions.extend(round(float(v), POSITION_DIGITS)
                                 for v in vert["pos"])
                normals.extend(round(float(v), POSITION_DIGITS)
                               for v in vert["nrm"])
                uvs.extend(round(float(v), UV_DIGITS) for v in vert["uv"])
                idx, weight = _weights(links_of(vert))
                skin_index.extend(idx)
                skin_weight.extend(weight)
        count = len(positions) // 3 - start
        if count:
            groups.append({"material": material, "start": start, "count": count})

    return {
        "kind": kind,
        "materials": [g["material"] for g in groups],
        "positions": positions,
        "normals": normals,
        "uvs": uvs,
        "skinIndex": skin_index,
        "skinWeight": skin_weight,
        "groups": groups,
    }


def _weights(links: List[Tuple[int, float]]) -> Tuple[List[int], List[float]]:
    """До четырёх нормированных весов на вершину (формат Three.js — vec4)."""
    strongest = sorted(links, key=lambda p: -p[1])[:MAX_WEIGHTS]
    idx = [0, 0, 0, 0]
    weight = [0.0, 0.0, 0.0, 0.0]
    total = sum(w for _b, w in strongest)
    if total <= 0.0:
        # Вершина без весов осталась бы в начале координат — привязываем к
        # первой кости целиком, это хотя бы не разбрасывает меш.
        return idx, [1.0, 0.0, 0.0, 0.0]
    for n, (bone, w) in enumerate(strongest):
        idx[n] = bone
        weight[n] = round(w / total, WEIGHT_DIGITS)
    return idx, weight


# ── Дорожки ───────────────────────────────────────────────────────────────── #

def _clip(anim_smd: str, order: List[str], name: str,
          fps: float, frame_step: int) -> Optional[dict]:
    """Кадры анимации → дорожки положения и поворота по костям."""
    names = smd_pose.parse_node_names(anim_smd)
    frames = smd_pose.parse_frames(anim_smd)
    if not frames or not names:
        return None

    step = max(1, int(frame_step))
    used = list(range(0, len(frames), step))
    rate = float(fps) if fps > 0 else 30.0
    times = [i / rate for i in used]

    slot_of = {name: i for i, name in enumerate(order)}
    tracks: Dict[int, dict] = {}
    for frame_no in used:
        frame = frames[frame_no]
        for bone, (pos, rot) in frame.items():
            slot = slot_of.get(names.get(bone, ""))
            if slot is None:
                continue
            track = tracks.setdefault(slot, {"bone": slot,
                                             "name": order[slot],
                                             "positions": [],
                                             "quaternions": []})
            track["positions"].extend(round(float(p), POSITION_DIGITS)
                                      for p in pos)
            track["quaternions"].extend(
                round(q, QUATERNION_DIGITS) for q in quaternion_from_euler(rot))

    ready = [t for t in tracks.values()
             if len(t["positions"]) == len(times) * 3]
    if not ready:
        return None
    logger.info(
        f"[anim] {_short(anim_smd)}: {len(times)} кадров, {len(ready)} дорожек")
    return {
        "name": name or os.path.splitext(os.path.basename(anim_smd))[0],
        "fps": rate,
        "times": times,
        "duration": times[-1] if times else 0.0,
        "tracks": ready,
    }


def _short(path: str) -> str:
    return os.path.basename(path or "")
