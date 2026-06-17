"""
Индекс путей моделей оружия из items_game.txt (как у шапок, но для c_model оружия).

Источник: {tf2_root}/tf/scripts/items/items_game.txt — авторитетные пути model_player.
Это убирает разрозненные ручные оверрайды путей: точный путь (папка+файл) берётся
прямо из игры. Кэшируется по mtime в cache/weapon_paths_cache.json.

Публичное API:
  weapon_model_index(tf2_root) -> {basename_lower: model_player_path}
  resolve_weapon_mdl(weapon_key, tf2_root) -> Optional[str]
"""

import json
import os
import re
from pathlib import Path
from typing import Dict, Optional

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

_CACHE_FILE = Path("cache") / "weapon_paths_cache.json"
_MODEL_RE = re.compile(r'"model_player[^"]*"\s+"([^"]+\.mdl)"', re.IGNORECASE)

# Память процесса: tf2_root -> индекс (чтобы не парсить 8 МБ повторно за сессию).
_MEM: Dict[str, Dict[str, str]] = {}


def get_items_game_path(tf2_root: str) -> Optional[Path]:
    if not tf2_root:
        return None
    p = Path(tf2_root) / "tf" / "scripts" / "items" / "items_game.txt"
    return p if p.exists() else None


def _parse(filepath: Path) -> Dict[str, str]:
    """basename(.mdl без расш., lower) -> исходный model_player путь.

    Берём только оружейные модели (c_models / c_items). Первый встреченный путь
    для стебля выигрывает (model_player идёт раньше прочих вариантов в блоке)."""
    try:
        txt = filepath.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"weapon index: не прочитать {filepath}: {e}")
        return {}
    idx: Dict[str, str] = {}
    for m in _MODEL_RE.finditer(txt):
        raw = m.group(1).replace("\\", "/").strip()
        low = raw.lower()
        if "/c_models/" not in low and "/c_items/" not in low:
            continue
        stem = os.path.splitext(os.path.basename(low))[0]
        if stem and stem not in idx:
            idx[stem] = raw
    return idx


def _cache_valid(tf2_root: str) -> bool:
    if not _CACHE_FILE.exists():
        return False
    try:
        if _CACHE_FILE.stat().st_size < 10:
            return False
    except Exception:
        return False
    items = get_items_game_path(tf2_root)
    if not items:
        return False
    return items.stat().st_mtime <= _CACHE_FILE.stat().st_mtime


def weapon_model_index(tf2_root: str) -> Dict[str, str]:
    """Индекс {basename: model_player_path}. Пустой, если items_game недоступен."""
    if not tf2_root:
        return {}
    if tf2_root in _MEM:
        return _MEM[tf2_root]
    if _cache_valid(tf2_root):
        try:
            data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _MEM[tf2_root] = data
                return data
        except Exception:
            pass
    items = get_items_game_path(tf2_root)
    if not items:
        return {}
    idx = _parse(items)
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.debug(f"weapon index: кэш не сохранён: {e}")
    _MEM[tf2_root] = idx
    logger.info(f"Индекс путей оружия из items_game: {len(idx)} моделей")
    return idx


def resolve_weapon_mdl(weapon_key: str, tf2_root: str) -> Optional[str]:
    """Точный путь model_player для ключа оружия из items_game (или None)."""
    if not weapon_key or not tf2_root:
        return None
    return weapon_model_index(tf2_root).get(weapon_key.lower())


def tf2_root_from_misc_vpk(misc_vpk_path: Optional[str]) -> Optional[str]:
    """Корень установки TF2 из пути к tf2_misc_dir.vpk
    ({root}/tf/tf2_misc_dir.vpk → {root}). None, если не похоже."""
    if not misc_vpk_path:
        return None
    p = Path(misc_vpk_path)
    # .../<root>/tf/tf2_misc_dir.vpk → parents[1] == <root>
    if len(p.parents) >= 2 and p.parents[0].name.lower() == "tf":
        return str(p.parents[1])
    return None
