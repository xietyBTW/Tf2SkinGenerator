"""
Сцена вида от первого лица: руки класса с оружием в одном OBJ.

Собирает то, что игрок видит в игре, из трёх декомпилированных моделей:

    руки      c_<class>_arms       меш + скелет в bind-позе
    анимация  c_<class>_animations кадр, задающий позу
    оружие    c_<weapon>           меш, сажаемый в руку через bonemerge

Матрицы считает [viewmodel_pose], геометрию пишет `SmdToObjService.convert_parts`.
Здесь — только связывание: какой части какая поза и кто чей материал.

Материалы рук и оружия разводятся по спискам намеренно: пользовательская
текстура относится к ОРУЖИЮ, руки остаются стоковыми, и панель материалов
должна знать, что из показанного можно править.

Пути к SMD приходят готовыми — искать их в папках декомпиляции будет вызывающий
воркер. Так модуль остаётся без Qt и проверяется на любых файлах.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from src.services import viewmodel_pose
from src.services.smd_to_obj_service import MeshPart, SmdToObjService
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Камера, соответствующая собранной здесь сцене. Оси замерены на настоящих
#: моделях TF2 и записаны в осях OBJ (после конвертации (x,y,z) → (x, z, -y)):
#: глаз в начале координат, взгляд по +Z, вверх +Y. FOV — калибровочная ручка,
#: у Source вьюмодель рисуется своим полем зрения (cvar viewmodel_fov).
#: Те же значения продублированы дефолтами в js/viewer_camera.js — менять надо
#: вместе, и там это проверяет тест.
VIEWMODEL_RIG = {
    "eye": [0.0, 0.0, 0.0],
    "forward": [0.0, 0.0, 1.0],
    "up": [0.0, 1.0, 0.0],
    "fov": 54,
}


#: Предмет носят, а не держат в руках. Живёт в [viewmodel_pose]: это его
#: находка, а имя здесь оставлено ради вызывающих.
NotHeldInHands = viewmodel_pose.NotHeldInHands


@dataclass(frozen=True)
class ViewmodelScene:
    """Готовая сцена: файл модели и разделённые по частям материалы."""

    obj_path: str
    #: Материалы оружия — их правит пользователь.
    weapon_materials: List[str]
    #: Материалы рук — стоковые, показываются, но не редактируются.
    arms_materials: List[str]
    #: Материалы пушки-НОСИТЕЛЯ: праздничное оружие — это гирлянда, надетая на
    #: обычную пушку. Пушка в кадре нужна (иначе огоньки висят в пустой руке),
    #: но правит человек гирлянду, поэтому список отдельный от weapon_materials.
    carrier_materials: List[str] = field(default_factory=list)

    @property
    def materials(self) -> List[str]:
        return (self.weapon_materials + self.carrier_materials
                + self.arms_materials)


def build(
    obj_path: str,
    *,
    weapon_ref_smd: str,
    arms_ref_smd: str,
    anim_smd: str,
    frame_index: int = 0,
    weapon_extra_smds: Sequence[str] = (),
    arms_extra_smds: Sequence[str] = (),
    weapon_include_mats: Optional[set] = None,
    weapon_merge_bones: Optional[Sequence[str]] = None,
    arms_include_mats: Optional[set] = None,
    weapon_carrier_smd: str = "",
    carrier_extra_smds: Sequence[str] = (),
) -> Optional[ViewmodelScene]:
    """
    Собирает OBJ + MTL со сценой вьюмодели.

    Args:
        obj_path:      Куда писать модель (MTL ляжет рядом).
        weapon_ref_smd: reference SMD оружия.
        arms_ref_smd:   reference SMD рук — он же bind-поза.
        anim_smd:       SMD последовательности из модели анимаций класса.
        frame_index:    Кадр анимации. Для статичной позы — 0.
        *_extra_smds:   Бодигруппы соответствующей части.
        *_include_mats: Оставить у части только эти материалы.
        weapon_merge_bones: Кости из `$bonemerge` в QC оружия — только
            они сажаются в руку (см. viewmodel_pose).
        weapon_carrier_smd: reference SMD пушки, НА КОТОРОЙ висит модель.
            Праздничное оружие — навесная гирлянда, и без носителя в руке
            оказывались одни огоньки. Свой список костей ей не нужен: их
            отбирает `bonemerge_skinning` сама.
        carrier_extra_smds: бодигруппы носителя — шланг медигана лежит
            отдельным SMD, и без него пушка в кадре обрублена.

    Returns:
        ViewmodelScene, либо None — если позу собрать не удалось. Отказ здесь
        честнее половинчатой сцены: руки без оружия или оружие в начале
        координат выглядят как поломка, а не как превью.
    """
    pose = viewmodel_pose.load_rig(anim_smd, frame_index)
    if pose is None:
        logger.warning(
            f"[vm] не прочитать позу: {os.path.basename(anim_smd or '')} "
            f"кадр {frame_index}"
        )
        return None

    weapon_mats = viewmodel_pose.bonemerge_skinning(
        weapon_ref_smd, pose, weapon_merge_bones)
    if weapon_mats is None:
        # Ни одна кость не крепится к руке — предмет носят, а не держат
        # (ранцы, реактивный ранец, рюкзак-знамя). Это не поломка сборки.
        raise NotHeldInHands(os.path.basename(weapon_ref_smd or ""))

    arms_mats = viewmodel_pose.arms_skinning(arms_ref_smd, pose)
    if arms_mats is None:
        return None

    parts = [
        MeshPart(smd_path=weapon_ref_smd,
                 extra_smd_paths=tuple(weapon_extra_smds),
                 skinning=weapon_mats,
                 include_mats=weapon_include_mats),
        MeshPart(smd_path=arms_ref_smd,
                 extra_smd_paths=tuple(arms_extra_smds),
                 skinning=arms_mats,
                 include_mats=arms_include_mats),
    ]
    carrier_names: set = set()
    if weapon_carrier_smd:
        # Носитель садится в руку теми же костями, что и сама модель: у
        # праздничного минигана гирлянда и миниган ложатся одинаково. Не
        # получилось — показываем сцену без него: гирлянда в руке лучше, чем
        # отказ собрать вид целиком.
        carrier_mats = viewmodel_pose.bonemerge_skinning(weapon_carrier_smd, pose)
        if carrier_mats is None:
            logger.info(f"[vm] носитель не сел в руку: "
                        f"{os.path.basename(weapon_carrier_smd)}")
        else:
            parts.insert(1, MeshPart(smd_path=weapon_carrier_smd,
                                     extra_smd_paths=tuple(carrier_extra_smds),
                                     skinning=carrier_mats))
            carrier_names = set(SmdToObjService.scan_material_names(
                [weapon_carrier_smd, *carrier_extra_smds]))

    ok, produced = SmdToObjService.convert_parts(
        parts,
        obj_path,
        source_zup=True,   # все части уже в общем пространстве вьюмодели
    )
    if not ok:
        return None

    # Кто чей материал: быстрый скан по именам, без повторного разбора вершин.
    weapon_names = SmdToObjService.scan_material_names(
        [weapon_ref_smd, *weapon_extra_smds])
    scene = ViewmodelScene(
        obj_path=obj_path,
        weapon_materials=[m for m in produced if m in weapon_names],
        # Общий материал (гирлянда и пушка на одной текстуре) остаётся за
        # ПРЕДМЕТОМ: его человек и правит.
        carrier_materials=[m for m in produced
                           if m in carrier_names and m not in weapon_names],
        arms_materials=[m for m in produced
                        if m not in weapon_names and m not in carrier_names],
    )
    logger.info(
        f"[vm] сцена собрана: оружие {scene.weapon_materials}, "
        f"носитель {scene.carrier_materials}, руки {scene.arms_materials}"
    )
    return scene
