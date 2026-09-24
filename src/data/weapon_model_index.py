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
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

from src.shared.logging_config import get_logger
from src.shared.paths import data_dir

logger = get_logger(__name__)

_CACHE_FILE = data_dir() / "cache" / "weapon_paths_cache.json"
_MODEL_RE = re.compile(r'"model_player[^"]*"\s+"([^"]+\.mdl)"', re.IGNORECASE)
_MODEL_ANY_RE = re.compile(r'"model"\s+"([^"]+\.mdl)"', re.IGNORECASE)
_ATTACHED_BLOCK_RE = re.compile(r'"attached_models"\s*\{(.*?)\n\s*\}', re.S | re.I)

# Память процесса: tf2_root -> индекс (чтобы не парсить 8 МБ повторно за сессию).
_MEM: Dict[str, Dict[str, str]] = {}
#: tf2_root -> стебли моделей-украшений (см. attachment_only_models).
_MEM_ATTACHED: Dict[str, set] = {}


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


def attachment_only_models(tf2_root: str) -> set:
    """
    Модели, которые игра только НАВЕШИВАЕТ на оружие, а не рисует как оружие.

    Праздничные пушки собраны из базовой модели плюс отдельная модель-гирлянда,
    объявленная в items_game блоком "attached_models" (c_minigun_xmas — это
    ровно гирлянда: в ней два материала, оба — лампочки). Ключ такой модели
    выглядит в списке как обычное оружие, но перекраска меняет украшение, а не
    ствол: сам ствол — базовая запись оружия.

    Возвращает стебли имён, встречающиеся ТОЛЬКО в attached_models. Пусто, если
    items_game недоступен.
    """
    if not tf2_root:
        return set()
    cached = _MEM_ATTACHED.get(tf2_root)
    if cached is not None:
        return cached
    items = get_items_game_path(tf2_root)
    if not items:
        return set()
    try:
        txt = items.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"weapon index: не прочитать {items}: {e}")
        return set()
    attached = set()
    for block in _ATTACHED_BLOCK_RE.finditer(txt):
        for m in _MODEL_ANY_RE.finditer(block.group(1)):
            stem = os.path.splitext(os.path.basename(
                m.group(1).replace("\\", "/").lower()))[0]
            if stem:
                attached.add(stem)
    result = attached - set(weapon_model_index(tf2_root))
    _MEM_ATTACHED[tf2_root] = result
    logger.info(f"items_game: моделей-украшений (attached_models): {len(result)}")
    return result


#: Ключи нашего списка, которых items_game не знает под этим именем: модель
#: в каталоге старая или переименованная, а иконка объявлена у нынешней.
_ICON_ALIASES = {
    "c_dartgun": "c_sydney_sleeper",      # Sydney Sleeper
    "c_batt_buffpack": "c_buffpack",      # Buff Banner (extra_wearable)
    "tankerboots": "mantreads",           # Mantreads
}
_ANY_MDL_RE = re.compile(r'"([^"]+\.mdl)"', re.IGNORECASE)


def _mdl_stems(game, block: str, depth: int = 0) -> list:
    """Стебли всех .mdl блока и его цепочки prefab (model_player, model_world,
    extra_wearable, model_player_per_class — ключ здесь не важен)."""
    from src.data.items_game_kv import MAX_PREFAB_DEPTH, flat_value

    stems = [os.path.splitext(os.path.basename(m.replace("\\", "/").lower()))[0]
             for m in _ANY_MDL_RE.findall(block)]
    if depth < MAX_PREFAB_DEPTH:
        for name in (flat_value(block, "prefab") or "").split():
            parent = game.prefabs.get(name)
            if parent is not None:
                stems += _mdl_stems(game, parent, depth + 1)
    return stems


@lru_cache(maxsize=4)
def _icon_index(tf2_root: str) -> Dict[str, str]:
    """{стебель модели: image_inventory}. Первый предмет выигрывает: items_game
    идёт по defindex, и стоковое оружие стоит раньше скинов и промо-копий."""
    from src.data.items_game_kv import ItemsGame

    items = get_items_game_path(tf2_root)
    if not items:
        return {}
    try:
        game = ItemsGame.parse(items.read_text(encoding="utf-8", errors="replace"))
    except Exception as e:
        logger.warning(f"weapon icons: не прочитать {items}: {e}")
        return {}
    idx: Dict[str, str] = {}
    for _key, block in game.items:
        icon = game.inherited(block, "image_inventory")
        if not icon:
            continue
        icon = icon.replace("\\", "/").strip().lower()
        for stem in _mdl_stems(game, block):
            idx.setdefault(stem, icon)
    return idx


def weapon_icon(weapon_key: str, tf2_root: str) -> Optional[str]:
    """
    Иконка рюкзака (путь image_inventory) для ключа оружия, либо None.

    Имя иконки часто не совпадает с именем модели (Scottish Resistance —
    `w_stickybomb_defender`), и поиск по имени файла отдавал развёртку
    текстуры вместо иконки. items_game связывает их напрямую.
    """
    if not weapon_key or not tf2_root:
        return None
    from src.data.weapons import WEAPON_MDL_PATHS

    key = weapon_key.lower()
    mdl = WEAPON_MDL_PATHS.get(weapon_key, "")
    candidates = (key, _ICON_ALIASES.get(key),
                  os.path.splitext(os.path.basename(mdl.lower()))[0] if mdl else None,
                  "c_" + key[2:] if key.startswith("w_") else None)
    idx = _icon_index(tf2_root)
    for c in candidates:
        if c and c in idx:
            return idx[c]
    return None


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
