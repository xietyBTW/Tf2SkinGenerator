"""
Значки классов из игры (`materials/hud/leaderboard_class_<класс>.vtf`, 64×64).

Нужны окнам, где выбирают классы: имя класса текстом читается хуже, чем
знакомая по таблице счёта голова. PNG кладутся в кэш данных один раз.
"""

from __future__ import annotations

import os
import tempfile
from typing import Dict

from src.shared.logging_config import get_logger
from src.shared.paths import data_dir

logger = get_logger(__name__)

#: Класс приложения → имя значка в игре (у подрывника он «demo»).
_STEMS = {'scout': 'scout', 'soldier': 'soldier', 'pyro': 'pyro',
          'demoman': 'demo', 'heavy': 'heavy', 'engineer': 'engineer',
          'medic': 'medic', 'sniper': 'sniper', 'spy': 'spy'}


def class_icons(textures_vpk: str, misc_vpk: str) -> Dict[str, str]:
    """{класс: путь PNG}. Класса без значка в ответе нет."""
    folder = (data_dir() / 'cache' / 'class_icons').resolve()
    out: Dict[str, str] = {}
    missing = []
    for cls, stem in _STEMS.items():
        png = folder / f'{cls}.png'
        if png.is_file():
            out[cls] = str(png)
        else:
            missing.append((cls, stem, png))
    if not missing:
        return out

    from PIL import Image
    import numpy as np

    from src.services.game_vpk_reader import GameVpkReader
    from src.services.vtflib_wrapper import VTFLib

    folder.mkdir(parents=True, exist_ok=True)
    reader = GameVpkReader([p for p in (textures_vpk, misc_vpk) if p])
    try:
        for cls, stem, png in missing:
            data = reader.read(f'materials/hud/leaderboard_class_{stem}.vtf')
            if not data:
                continue
            fd, tmp = tempfile.mkstemp(suffix='.vtf', prefix='tf2sg_icon_')
            try:
                with os.fdopen(fd, 'wb') as f:
                    f.write(data)
                rgba, w, h = VTFLib.read_vtf_as_rgba(tmp)
                Image.fromarray(np.frombuffer(rgba, np.uint8).reshape(h, w, 4), 'RGBA').save(png)
                out[cls] = str(png)
            except Exception as exc:                      # noqa: BLE001
                logger.warning(f'[class_icons] {cls}: {exc}')
            finally:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
    finally:
        reader.close()
    return out
