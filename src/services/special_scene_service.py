"""
Сцена спец-режимов: крит и эффекты смерти (без Qt).

Показывать в этих режимах нечего, кроме персонажа: у крита текстура висит
билбордом над ним, у эффекта смерти — ложится на него самого. Персонаж
процедурный (его строит вьювер), а из папки `tools/Model/<класс>` подхватывается
своя модель, если человек её туда положил.

Вынесено из ``PreviewCritHitMixin``: правила «где искать модель» и «какая
текстура у эффекта по умолчанию» к виджетам отношения не имеют, а нужны и окну,
и странице.
"""

from __future__ import annotations

import os
from typing import List, Optional, Tuple

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Куда класть свою модель персонажа для сцены (по папке на класс).
MODEL_ROOT = os.path.join('tools', 'Model')

_MODEL_EXTS = ('.obj', '.smd')
_TEXTURE_EXTS = ('.png', '.jpg', '.jpeg', '.bmp', '.tga', '.vtf', '.webp')


def find_scene_model(class_name: str = 'soldier') -> Tuple[str, str]:
    """
    (модель, текстура) для сцены — или пустые строки.

    Сначала папка класса, потом общая: у людей обычно лежит одна модель на всех.
    Пусто — нормальный случай: вьювер нарисует процедурного персонажа.
    """
    def scan(folder: str) -> Tuple[str, str]:
        if not os.path.isdir(folder):
            return '', ''
        model = texture = ''
        for name in sorted(os.listdir(folder)):
            if name.startswith('.'):
                continue
            low, full = name.lower(), os.path.join(folder, name)
            if not model and low.endswith(_MODEL_EXTS):
                model = full
            if not texture and low.endswith(_TEXTURE_EXTS):
                texture = full
        return model, texture

    model, texture = scan(os.path.join(MODEL_ROOT, (class_name or '').lower()))
    if model:
        return model, texture
    return scan(MODEL_ROOT)


def vtf_to_png(vtf_path: str) -> str:
    """VTF → PNG во временный файл. Пустая строка, если не вышло."""
    try:
        from PIL import Image

        from src.shared.file_utils import get_temp_file_path
        from src.services.vtflib_wrapper import VTFLib

        rgba, width, height = VTFLib.read_vtf_as_rgba(vtf_path)
        png = str(get_temp_file_path(prefix='tf2_scene_tex_', suffix='.png'))
        Image.frombytes('RGBA', (width, height), rgba).save(png)
        return png
    except Exception as exc:                      # noqa: BLE001 — VTFLib своё
        logger.warning(f"VTF→PNG сцены: {exc}")
        return ''


def game_texture(mode: str, vpk_paths: List[Optional[str]]) -> str:
    """
    Игровая текстура спец-режима как PNG: лёд, золото, огонь, крит.

    Нужна дважды. Во-первых, для показа по умолчанию: пока человек не дал
    свою, сцена должна выглядеть так, как выглядит в игре. Во-вторых, для
    карточки — она стояла пустой, и было не видно, что именно заменяешь.
    Пусто — покажем без текстуры.
    """
    try:
        from src.services import vtf_preview_service as vps
        from src.services.vmt_service import VMTService

        rel, _vmt, vtf = VMTService.get_weapon_relpaths(mode)
        folder = rel.replace('\\', '/').rstrip('/')
        candidates = [f"{folder}/{vtf}"]
        if vtf.lower() != vtf:
            candidates.append(f"{folder}/{vtf.lower()}")

        for pak in vps.open_vpks(vpk_paths):
            for candidate in candidates:
                try:
                    data = pak[candidate].read()
                except KeyError:
                    continue
                from src.shared.file_utils import get_temp_file_path
                tmp = str(get_temp_file_path(prefix='tf2_deatheff_', suffix='.vtf'))
                with open(tmp, 'wb') as f:
                    f.write(data)
                png = vtf_to_png(tmp)
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                if png:
                    logger.info(f"[спец-режим] игровая текстура: {candidate}")
                    return png
    except Exception as exc:                      # noqa: BLE001
        logger.debug(f"[спец-режим] игровую текстуру не достать: {exc}")
    return ''
