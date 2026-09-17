"""
Косметика в позе игрока: как её ставит игра, а не как она лежит в MDL.

Шапка в игре не стоит сама по себе: её кости сливаются с костями игрока
(bonemerge), и вершины оказываются там, куда смотрит `bip_head` игрока. Сам
же MDL хранит их как автору было удобно — у собранных против скелета с
`$upaxis Y` верх смотрит по +Y, у собранных в чужом инструменте — по −Z
(bak_teufort_knight: голова на z = −73 с поворотом на 96°). Превью, читающее
вершины как есть, показывает такие шапки боком.

Ответ тот же, что у игры: взять кость, к которой шапка прикреплена, и
перенести её из позы MDL в позу игрока. Перенос ЖЁСТКИЙ — одна матрица на
все вершины: косметика собрана против скелета своего класса, и её кости уже
стоят друг относительно друга как надо; двигать их по одной под чужой
(канонический) класс значило бы исказить пальто Пулемётчика под Солдата.

    T = W_игрока[якорь] · W_bind[якорь]⁻¹
    v' = T · v

Якорь — `bip_head`, если он есть (у шапок это всегда он), иначе первая кость
модели, известная скелету игрока. Ни одной известной кости — модель не
трогаем: так было и раньше.

Модуль без Qt.
"""

from __future__ import annotations

import os
from typing import Dict, Optional

from src.data.player_skeleton import BONES
from src.services import smd_pose
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Игрок в reference-позе смотрит по +Y движка, а камера превью стоит со
#: стороны −Y (в осях сцены — на +Z): без разворота шапка показывала бы
#: затылок. Поворот на 180° вокруг вертикали — чистая подача, к позе игры
#: отношения не имеет.
_FACE_CAMERA: smd_pose.Mat = (-1.0, 0.0, 0.0, 0.0,
                              0.0, -1.0, 0.0, 0.0,
                              0.0, 0.0, 1.0, 0.0)

#: Кость, за которую игра держит шапку. Смотрим первой: у косметики с целой
#: цепочкой позвоночника корень — таз, а собран он против СВОЕГО класса, и
#: голова по нему встала бы на высоту чужой.
_PREFERRED = 'bip_head'


def _bone_names(smd: str) -> Dict[int, str]:
    names: Dict[int, str] = {}
    for line in smd_pose._section(smd, 'nodes'):
        m = smd_pose._RE_NODE.match(line)
        if m:
            names[int(m.group(1))] = m.group(2)
    return names


def anchor_transform(ref_smd: str) -> Optional[smd_pose.Mat]:
    """Матрица переноса bind-позы модели в позу игрока. None — якоря нет."""
    if not ref_smd or not os.path.isfile(ref_smd):
        return None
    names = _bone_names(ref_smd)
    if not names:
        return None
    known = {b for b, n in names.items() if n in BONES}
    if not known:
        return None
    anchor = next((b for b, n in names.items() if n == _PREFERRED), None)
    if anchor is None:
        anchor = min(known)
    bind = smd_pose.world_matrices(smd_pose.parse_nodes(ref_smd),
                                   smd_pose.parse_frame0(ref_smd))
    w_bind = bind.get(anchor)
    if w_bind is None:
        return None
    logger.info(f"[cosmetic] {os.path.basename(ref_smd)}: ставим на игрока "
                f"за {names[anchor]}")
    return smd_pose.mul(_FACE_CAMERA,
                        smd_pose.mul(BONES[names[anchor]], smd_pose.rigid_inverse(w_bind)))


def on_player(ref_smd: str,
              skinning: Optional[Dict[int, smd_pose.Mat]] = None
              ) -> Optional[Dict[int, smd_pose.Mat]]:
    """
    Матрицы скиннинга {кость: матрица}, ставящие модель на игрока.

    `skinning` — уже посчитанная поза (см. smd_pose.skinning_matrices): она
    применяется первой, перенос — поверх. Якоря нет — возвращает `skinning`
    как есть.
    """
    t = anchor_transform(ref_smd)
    if t is None:
        return skinning
    bones = smd_pose.parse_nodes(ref_smd)
    return {b: smd_pose.mul(t, skinning[b]) if skinning and b in skinning else t
            for b in bones}
