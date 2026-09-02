"""
Пушка-НОСИТЕЛЬ: модель, на которой висит другая.

Праздничное оружие в TF2 — не отдельная пушка. В items_game `c_*_xmas`
записан в `visuals → attached_models`, а `model_player` предмета остаётся
базовым оружием; в самой модели `c_*_xmas` лежат ОДНИ ОГОНЬКИ (у
`c_medigun_xmas` габарит 21 против 68 у медигана). Без носителя в кадре висит
гирлянда, а оружия нет.

Модуль отвечает на один вопрос: какие SMD показать РЯДОМ с предметом. Он
появился, когда ответ понадобился в трёх местах сразу — обычное превью, вид от
первого лица и подстановка своей модели, — и три копии успели разъехаться:
одна из них искала меш не по имени и брала у медигана шланг вместо пушки.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from src.shared.logging_config import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class Carrier:
    """Носитель: что показать и откуда брать его материалы."""

    #: Reference SMD пушки плюс её бодигруппы (шланг медигана лежит отдельно).
    smds: List[str] = field(default_factory=list)
    #: Папка декомпиляции: `$cdmaterials` у носителя СВОИ — гирлянда лежит в
    #: папке оружия, а сама пушка в своей, и без второго пути она серая.
    directory: str = ""
    #: Имя модели-носителя (`c_scattergun`). Пусто — носителя нет.
    key: str = ""

    def __bool__(self) -> bool:
        return bool(self.smds)


#: Носителя нет: обычное оружие, шапка, персонаж.
NONE = Carrier()


def carrier_key(weapon_key: str, tf2_root: str) -> str:
    """Имя пушки, на которой висит эта модель. Пусто — ни на чём не висит."""
    if not weapon_key or not tf2_root:
        return ""
    from src.data import viewmodel_anims
    try:
        info = viewmodel_anims.anim_info(weapon_key, tf2_root)
    except Exception as exc:                                  # noqa: BLE001
        logger.debug(f"[носитель] items_game не прочитан: {exc}")
        return ""
    return info.carried_on if info else ""


def find(weapon_key: str, misc_vpk_path: str, tf2_root: str,
         cancelled: Optional[Callable[[], bool]] = None,
         on_progress: Optional[Callable] = None) -> Carrier:
    """
    Достаёт и декомпилирует носителя. `NONE` — его нет или не получилось.

    Отказ здесь не ошибка: показать гирлянду без пушки хуже, чем с пушкой, но
    лучше, чем не показать ничего.
    """
    base = carrier_key(weapon_key, tf2_root)
    if not base:
        return NONE

    from src.services import model_decompile_service as mds
    from src.services import smd_service

    result = mds.ensure_decompiled(base, misc_vpk_path, _candidates(base, tf2_root),
                                   cancelled=cancelled, on_progress=on_progress)
    if result is None:
        logger.info(f"[носитель] {weapon_key}: {base} не достали")
        return NONE

    # ПО ИМЕНИ, а не первым попавшимся `*_reference.smd`: у медигана рядом
    # лежит `c_medigun_hose_reference.smd`, и без подсказки в кадр попадал
    # один шланг вместо пушки.
    smd = smd_service.find_reference_smd(result.directory, base)
    if not smd:
        logger.info(f"[носитель] {weapon_key}: меш {base} не нашёлся")
        return NONE

    smds = [smd] + _bodygroups(result.directory, smd)
    logger.info(f"[носитель] {weapon_key} висит на {base}: "
                f"{[os.path.basename(s) for s in smds]}")
    return Carrier(smds=smds, directory=result.directory, key=base)


def materials(carrier: Carrier) -> set:
    """Материалы носителя — их показывают, но человек их не правит."""
    if not carrier:
        return set()
    from src.services.smd_to_obj_service import SmdToObjService
    return set(SmdToObjService.scan_material_names(carrier.smds))


def _candidates(base: str, tf2_root: str) -> list:
    """Пути MDL носителя внутри VPK.

    Носитель — всегда обычное оружие, каким бы ни был режим самого предмета,
    поэтому режим подставляется формальный.
    """
    from src.services.extract_model_service import ExtractModelService
    try:
        return ExtractModelService._build_paths_to_try(f"scout_{base}", base, tf2_root)
    except Exception as exc:                                  # noqa: BLE001
        logger.debug(f"[носитель] пути {base} не собрались: {exc}")
        return [f"models/weapons/c_models/{base}/{base}.mdl"]


def _bodygroups(directory: str, reference_smd: str) -> list:
    """Части носителя, видные по умолчанию: шланг медигана лежит отдельно."""
    from src.services import qc_skin_parser
    model = qc_skin_parser.load_model(directory)
    if model is None:
        return []
    try:
        from src.services.model_build_service import ModelBuildService
        found = set(ModelBuildService.extract_default_body_smds(model.qc_path))
    except Exception as exc:                                  # noqa: BLE001
        logger.debug(f"[носитель] бодигруппы {directory} не собрались: {exc}")
        return []
    found.discard(reference_smd)
    found.discard(os.path.abspath(reference_smd))
    return sorted(found)
