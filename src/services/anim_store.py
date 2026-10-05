"""
Последовательности анимаций, которыми пользуются сцены «На модели» и
насмешка, — своей копией.

Сцене нужна одна-две последовательности модели анимаций класса по сотне
килобайт, а её распаковка Crowbar'ом весит 120-165 МБ и идёт до полуминуты.
Общий кэш декомпиляции (1 ГБ на всё, decompile_cache) такие записи вытеснял
первыми, и сцена снова ждала Crowbar, даже после перезапуска. Здесь лежит
только использованное: SMD последовательности и её параметры, пока не
обновится игра (mtime VPK).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import replace
from typing import Optional, Tuple

from src.services.weapon_anim_catalog import AnimSequence
from src.shared.logging_config import get_logger
from src.shared.paths import data_dir

logger = get_logger(__name__)

_ROOT = data_dir() / "cache" / "anims"


def _stamp(vpk_path: str) -> str:
    try:
        return f"{os.path.getmtime(vpk_path):.0f}"
    except OSError:
        return ""


def _base(key: str) -> str:
    return str(_ROOT / hashlib.sha1(key.encode("utf-8")).hexdigest()[:20])


def get(key: str, vpk_path: str) -> Optional[Tuple[AnimSequence, float]]:
    """(последовательность из своей копии, поворот её модели) или None."""
    base = _base(key)
    try:
        with open(base + ".json", encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return None
    if (meta.get("key") != key or meta.get("vpk") != _stamp(vpk_path)
            or not os.path.isfile(base + ".smd")):
        return None
    sequence = AnimSequence(
        name=str(meta.get("name") or ""), smd_path=base + ".smd",
        activity=str(meta.get("activity") or ""), fps=float(meta.get("fps") or 30.0),
        loop=bool(meta.get("loop")),
        hide_events=tuple((int(f), bool(h)) for f, h in meta.get("hide_events") or ()))
    return sequence, float(meta.get("rotation") or 0.0)


def put(key: str, vpk_path: str, sequence: AnimSequence, rotation: float) -> AnimSequence:
    """Кладёт копию SMD и параметры последовательности; отдаёт её из копии
    (или исходную, если записать не вышло — сцена от этого не страдает)."""
    base = _base(key)
    try:
        os.makedirs(_ROOT, exist_ok=True)
        shutil.copyfile(sequence.smd_path, base + ".smd.tmp")
        os.replace(base + ".smd.tmp", base + ".smd")
        meta = {"key": key, "vpk": _stamp(vpk_path), "name": sequence.name,
                "activity": sequence.activity, "fps": sequence.fps, "loop": sequence.loop,
                "hide_events": [list(e) for e in sequence.hide_events],
                "rotation": rotation}
        with open(base + ".json.tmp", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
        os.replace(base + ".json.tmp", base + ".json")
    except OSError as exc:
        logger.warning(f"[anims] не сохранить {key}: {exc}")
        return sequence
    return replace(sequence, smd_path=base + ".smd")
