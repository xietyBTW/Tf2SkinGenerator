"""
Поза вьюмодели: руки класса держат оружие.

В TF2 то, что игрок видит от первого лица, собирается из трёх моделей:

    c_<class>_arms.mdl        меш рук, скелет в bind-позе, своих анимаций нет
    c_<class>_animations.mdl  геометрии нет, только последовательности
    c_<weapon>.mdl            меш оружия, 2-3 кости, `$bonemerge "weapon_bone"`

Руки берут позу из модели анимаций, а оружие — ведомое: перечисленные в
`$bonemerge` кости получают мировую матрицу от родительской модели по ИМЕНИ.
Важно, что список из QC — исчерпывающий: у оружия обычно сливаются только
`weapon_bone` и `c_weapon_stattrack`, а `weapon_bone_1..4` — это его
собственные курок, барабан и цевьё, и они едут за своим родителем.

Отсюда две операции:

    руки     S[i] = W_анимации[имя i] · W_bind[i]⁻¹
    оружие   S[i] = W_итог[i]         · W_bind[i]⁻¹

где W_итог[i] — мировая матрица рук, если имя кости у них есть, иначе цепочка
от родителя на собственных локальных матрицах оружия.

Скелеты разных моделей сопоставляются ТОЛЬКО по имени: номера костей у рук,
анимаций и оружия свои. Проверено на heavy — имена сходятся 60 из 60.

Вся матричная арифметика (конвенция углов studiomdl, обращение жёсткого
преобразования, линейный скиннинг) живёт в [smd_pose]; здесь — сопоставление
скелетов. Результат обеих функций — `{кость: матрица}` в том виде, который
принимает `smd_pose.apply_to_vertex`.

Модуль без Qt.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple

from src.services import smd_pose
from src.services.smd_pose import Mat
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Какая доля костей меша должна найтись в позе, чтобы ей верить. Ниже —
#: скелеты разные (не та модель анимаций, чужие руки), и лучше остаться в bind,
#: чем показать порванный меш.
MIN_BONE_MATCH = 0.5


class NotHeldInHands(Exception):
    """Ни одна кость предмета не совпала с рукой — его носят, а не держат.

    Ранцы, знамёна, ботинки и часы-«статик» крепятся не к руке, и вида от
    первого лица у них нет вовсе. Это не поломка сборки, и разговаривать с
    пользователем об этом надо иначе.
    """


@dataclass(frozen=True)
class Rig:
    """Скелет SMD в одном кадре: имена, иерархия, мировые матрицы."""

    names: Dict[int, str]
    parents: Dict[int, int]
    #: {кость: (позиция, углы)} — локальные преобразования кадра.
    frame: Dict[int, Tuple[tuple, tuple]]
    world: Dict[int, Mat]
    by_name: Dict[str, Mat]


def load_rig(smd_path: str, frame_index: int = 0) -> Optional[Rig]:
    """
    Скелет из SMD на заданном кадре. None — нет секций или нет такого кадра.

    Кадр вынесен сюда намеренно: это единственное место, где выбирается момент
    времени. Анимация (несколько кадров подряд) — это несколько Rig, а функции
    ниже остаются без изменений.
    """
    if not smd_path:
        return None
    nodes = smd_pose.parse_node_table(smd_path)
    frame = smd_pose.parse_frame(smd_path, frame_index)
    if not nodes or not frame:
        return None

    names = {bone: name for bone, (name, _p) in nodes.items()}
    parents = {bone: parent for bone, (_n, parent) in nodes.items()}
    world = smd_pose.world_matrices(parents, frame)
    by_name = {names[bone]: mat for bone, mat in world.items() if bone in names}
    return Rig(names=names, parents=parents, frame=frame,
               world=world, by_name=by_name)


def arms_skinning(arms_ref_smd: str, pose: Rig) -> Optional[Dict[int, Mat]]:
    """
    Матрицы скиннинга рук: из bind-позы меша в позу из модели анимаций.

    Args:
        arms_ref_smd: reference SMD рук — он же и есть bind-поза.
        pose:         скелет кадра анимации (`load_rig`).

    Returns:
        {кость: матрица} либо None, если скелеты не сошлись.
    """
    bind = load_rig(arms_ref_smd)
    if bind is None or pose is None:
        return None

    mats: Dict[int, Mat] = {}
    matched = 0
    for bone, name in bind.names.items():
        wb = bind.world.get(bone)
        if wb is None:
            continue
        wp = pose.by_name.get(name)
        if wp is None:
            # Кость без анимации остаётся там, где стояла: W_позы = W_bind,
            # то есть матрица единичная. Кладём её явно, чтобы вершина с такой
            # костью считалась по всем своим весам, а не по части.
            mats[bone] = smd_pose.IDENTITY
            continue
        mats[bone] = smd_pose.mul(wp, smd_pose.rigid_inverse(wb))
        matched += 1

    if not _enough(matched, len(bind.names), arms_ref_smd):
        return None
    return mats


def bonemerge_skinning(weapon_ref_smd: str, pose: Rig,
                       merge_bones: Optional[Iterable[str]] = None
                       ) -> Optional[Dict[int, Mat]]:
    """
    Матрицы скиннинга оружия, посаженного в руку через bonemerge.

    Args:
        weapon_ref_smd: reference SMD оружия (он же bind-поза).
        pose:           скелет кадра анимации рук.
        merge_bones:    имена костей из `$bonemerge` в QC оружия — ТОЛЬКО они
            получают положение от руки. Остальные (курок, барабан, цевьё,
            `c_weapon_stattrack`) строятся от родителя на собственных
            локальных матрицах, ровно как в движке.

    Список из QC исчерпывающий: у револьвера там всего две кости, а
    `weapon_bone_1..4` — его собственные курок и барабан. Слияние их по имени с
    одноимённой лесенкой точек крепления у руки разносило модель на 73 единицы
    вместо её восемнадцати.

    Списка нет (Crowbar его не всегда выводит) — отбираем сами: сливаем те
    одноимённые кости, что в позе остались на своих местах в скелете оружия
    (см. `_rigid_subset`). Через них анимация класса и водит подвижными
    частями: крышку флергана открывает `weapon_bone_2` из `fg_fire`, ведь
    своих кадров у моделей оружия нет.

    Returns:
        {кость: матрица}, либо None, если оружию не за что зацепиться: ни одна
        его кость не совпала с рукой по имени. Тогда сажать его в руку нечем, и
        честнее не показать ничего, чем повесить модель в начале координат.
    """
    bind = load_rig(weapon_ref_smd)
    if bind is None or pose is None:
        return None

    wanted = _merge_targets(bind, pose, merge_bones)
    if not wanted:
        logger.info(
            f"[vm] {_short(weapon_ref_smd)}: ни одна кость не совпала с рукой "
            f"({sorted(bind.names.values())[:4]}) — оружие не ставим"
        )
        return None

    final: Dict[int, Mat] = {}

    def resolve(bone: int, guard: int = 0) -> Mat:
        cached = final.get(bone)
        if cached is not None:
            return cached
        name = bind.names.get(bone, "")
        wp = pose.by_name.get(name) if name in wanted else None
        if wp is not None:
            final[bone] = wp                 # bonemerge: мировая матрица руки
            return wp
        data = bind.frame.get(bone)
        if data is None or guard > 256:      # битая иерархия — не зацикливаемся
            final[bone] = smd_pose.IDENTITY
            return final[bone]
        local = smd_pose.local_matrix(*data)
        parent = bind.parents.get(bone, -1)
        final[bone] = local if parent < 0 or parent == bone \
            else smd_pose.mul(resolve(parent, guard + 1), local)
        return final[bone]

    mats: Dict[int, Mat] = {}
    for bone in bind.frame:
        wb = bind.world.get(bone)
        if wb is None:
            continue
        mats[bone] = smd_pose.mul(resolve(bone), smd_pose.rigid_inverse(wb))
    return mats or None


def driving_bones(weapon_ref_smd: str, pose: Rig,
                  merge_bones: Optional[Iterable[str]] = None
                  ) -> Dict[int, str]:
    """
    {кость оружия: имя кости РУКИ, которая её ведёт}.

    Нужно анимации: в сцене three.js скелет один — рук, а оружие подвешивается
    к нему целиком. Кость, которая сама не сливается, ведётся ближайшим
    слитым предком: ниже него иерархия оружия жёсткая и от позы не зависит.

    Returns:
        Пустой словарь, если оружию не за что зацепиться.
    """
    bind = load_rig(weapon_ref_smd)
    if bind is None or pose is None:
        return {}
    wanted = _merge_targets(bind, pose, merge_bones)
    if not wanted:
        return {}

    driver: Dict[int, str] = {}

    def resolve(bone: int, guard: int = 0) -> Optional[str]:
        if bone in driver:
            return driver[bone]
        name = bind.names.get(bone, "")
        if name in wanted:
            driver[bone] = name
            return name
        parent = bind.parents.get(bone, -1)
        if parent < 0 or parent == bone or guard > 256:
            return None
        found = resolve(parent, guard + 1)
        if found is not None:
            driver[bone] = found
        return found

    for bone in bind.names:
        resolve(bone)
    return driver


def merged_bone_names(weapon_ref_smd: str, poses,
                      merge_bones: Optional[Iterable[str]] = None) -> list:
    """Имена костей оружия, которые в этих позах ведёт анимация класса.

    Тот же отбор, что делает `bonemerge_skinning`, но отдельно — чтобы решение
    можно было принять по кадрам анимации, а применить к другой позе. Сцена
    первого лица именно так и собирается: геометрия запекается в bind-позу рук,
    где `weapon_bone_1..4` стоят не на своих местах и отличить своё от чужого
    нельзя, а список костей берётся из кадров последовательности.

    Args:
        poses: один Rig или несколько. Кость проходит, только если своё место
            она держит в КАЖДОМ кадре: у Ответного удара патрон в `reload_loop`
            стоит на месте в первом кадре и улетает в середине, растягивая
            модель с 39 единиц до 206.
    """
    bind = load_rig(weapon_ref_smd)
    if bind is None:
        return []
    frames = [poses] if isinstance(poses, Rig) else [p for p in poses if p]
    if not frames:
        return []
    kept = set.intersection(*(_merge_targets(bind, pose, merge_bones)
                              for pose in frames))
    return sorted(kept)


def _merge_targets(bind: Rig, pose: Rig,
                   merge_bones: Optional[Iterable[str]]) -> set:
    """Имена костей оружия, которые действительно берут положение от руки."""
    available = {name for name in bind.names.values() if name in pose.by_name}
    if not available:
        return set()
    if merge_bones:
        wanted = available & {str(n) for n in merge_bones}
        if wanted:
            return wanted
        logger.info(
            "[vm] $bonemerge не пересёкся со скелетом руки — отбираем сами")
    return _rigid_subset(bind, pose, available)


#: Насколько поза вправе изменить расстояние кости до её родителя. Твёрдое тело
#: не меняет его вовсе; допуск нужен на конечную точность чисел в SMD и на
#: собственный масштаб кости — отсюда и абсолютный порог, и относительный.
RIGID_SLACK = 2.0
RIGID_TOLERANCE = 0.5

#: Кость, за которую оружие держат в руке. Имя одно на весь TF2.
ANCHOR_BONE = "weapon_bone"


def _rigid_subset(bind: Rig, pose: Rig, available: set) -> set:
    """Кости, которые в позе остались на своих местах в скелете оружия.

    `$bonemerge` в декомпилированном QC есть не всегда, а сливать всё подряд
    нельзя: скелет модели анимаций один на весь класс, и `weapon_bone_1..4` в
    нём принадлежат ТОМУ оружию, для которого сделана последовательность.
    Чужая кость в кадре `idle` шпиона уезжает на 58 единиц от `weapon_bone` при
    собственных 3.9 — и Карающий с праздничным револьвером разлетались.

    Хват — кость, за которую оружие держат, и ей позволено уехать в руку куда
    угодно. Хватов бывает несколько: у медигана `weapon_bone_L` (левая рука) —
    не потомок `weapon_bone`, а САМОСТОЯТЕЛЬНЫЙ корень, и весь меш висит именно
    на нём. Поэтому хват — это `weapon_bone` и любой корень собственной
    иерархии оружия.

    Всё, что НИЖЕ хвата, отбирается по признаку твёрдого тела: у своей кости
    расстояние до родителя в позе то же, что в bind (вращение его не меняет),
    у чужой — какое угодно. Кость с отброшенным родителем отбрасывается тоже,
    иначе она поехала бы отдельно от модели.

    Всё, что ВЫШЕ `weapon_bone`, не сливается вовсе. У Хлебной атаки корень
    скелета зовётся `root` и в модели анимаций тоже есть — но это мировой ноль,
    и слияние с ним оставляло сапёр висеть в начале координат. Тем и отличается
    предок хвата от его соседа-корня.
    """
    keep: set = set()
    above = _above_anchor(bind) if ANCHOR_BONE in available else set()
    for bone in sorted(bind.names, key=lambda b: _depth(bind, b)):
        name = bind.names.get(bone, "")
        if name not in available or name in above:
            continue
        parent = bind.parents.get(bone, -1)
        pname = bind.names.get(parent, "") if parent >= 0 and parent != bone else ""
        if name == ANCHOR_BONE or not pname or pname not in available:
            keep.add(name)          # хват: за него оружие и держат
            continue
        if pname not in keep:
            continue
        d_bind = _distance(bind.by_name[name], bind.by_name[pname])
        d_pose = _distance(pose.by_name[name], pose.by_name[pname])
        if abs(d_pose - d_bind) <= max(RIGID_SLACK, RIGID_TOLERANCE * d_bind):
            keep.add(name)
    return keep


def _above_anchor(bind: Rig) -> set:
    """Имена костей ВЫШЕ `weapon_bone`, которые хватом не являются.

    Над `weapon_bone` в скелетах TF2 бывает ровно три вещи (проверено на всём
    арсенале): ничего (184 модели), второй ХВАТ `weapon_bone_L` (медиганы) или
    служебный корень — мировой ноль `root` у Хлебной атаки, узел по имени
    модели у Фалломорфера и Клеймора. Служебный сливать нельзя: сапёр повисал
    в начале координат. Хват — можно и нужно: на `weapon_bone_L` у медигана
    висит весь меш, 16968 вершин из 19116.
    """
    by_name = {name: bone for bone, name in bind.names.items()}
    bone = by_name.get(ANCHOR_BONE)
    above: set = set()
    guard = 0
    while bone is not None and guard <= 256:
        parent = bind.parents.get(bone, -1)
        if parent < 0 or parent == bone:
            break
        name = bind.names.get(parent, "")
        if not name or name in above:
            break
        if not name.startswith(ANCHOR_BONE):
            above.add(name)
        bone, guard = parent, guard + 1
    return above


def _depth(bind: Rig, bone: int, guard: int = 0) -> int:
    parent = bind.parents.get(bone, -1)
    if parent < 0 or parent == bone or guard > 256:
        return 0
    return 1 + _depth(bind, parent, guard + 1)


def _distance(a: Mat, b: Mat) -> float:
    return sum((a[i * 4 + 3] - b[i * 4 + 3]) ** 2 for i in range(3)) ** 0.5


def _enough(matched: int, total: int, smd_path: str) -> bool:
    if total and matched >= total * MIN_BONE_MATCH:
        return True
    logger.info(
        f"[vm] {_short(smd_path)}: скелеты не сошлись "
        f"({matched} из {total} костей) — позу не применяем"
    )
    return False


def _short(path: str) -> str:
    return os.path.basename(path or "")
