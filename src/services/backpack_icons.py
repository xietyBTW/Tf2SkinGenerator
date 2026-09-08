"""
Иконки предметов из рюкзака (materials/backpack/…) прямо из игрового VPK.

Ничего не скачивается и не распаковывается: `vpk` читает одну запись по имени,
VTF декодируется в PNG в памяти, результат кладётся в cache/icons. Это те самые
картинки, которые игрок видит в рюкзаке, — 128x128 с прозрачным фоном.

Сопоставление сделано по имени файла, а не по items_game.txt: в 8385 иконках
backpack имена уникальны (ни одного совпадения на два разных пути), поэтому
индекс «имя → путь в VPK» решает задачу без разбора 30-мегабайтного файла.
Покрытие оружия — 213 из 224; недостающие иконки просто не показываются.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from src.shared.logging_config import get_logger
from src.shared.paths import data_dir

logger = get_logger(__name__)

#: Готовые PNG между запусками. Декодирование VTF стоит ~12 мс на иконку —
#: на второй запуск это заметная разница при трёхстах карточках на экране.
_CACHE_DIR = data_dir() / "cache" / "icons"

_index: Optional[Dict[str, str]] = None


def _build_index(textures_vpk: str) -> Dict[str, str]:
    """Индекс «имя файла → путь внутри VPK» по всем иконкам рюкзака.

    Версии `_large` (512x512) пропускаем: карточка каталога не больше 150
    пикселей, а весят они в шестнадцать раз больше.
    """
    from src.services.vpk_cache import open_vpk_cached

    pak = open_vpk_cached(textures_vpk)
    if pak is None:
        return {}
    out: Dict[str, str] = {}
    for path in pak:
        if not (path.startswith("materials/backpack/") and path.endswith(".vtf")):
            continue
        name = path.rsplit("/", 1)[-1][:-4]
        if not name.endswith("_large"):
            out.setdefault(name, path)
    logger.info(f"[icons] иконок рюкзака в индексе: {len(out)}")
    return out


def vpk_path_for(key: str, textures_vpk: str) -> Optional[str]:
    """
    Путь иконки внутри VPK для ключа предмета, либо None.

    Ключом может быть:
      * путь image_inventory из items_game (``backpack/player/items/…``);
      * ключ оружия (``c_scattergun``);
      * путь к модели шапки (``models/player/items/…/hat.mdl``).

    Для стоковых оружий иконка объявлена под мировой моделью (`c_minigun` →
    `w_minigun`), поэтому после прямого совпадения пробуем `w_`-вариант.
    """
    global _index
    if not key:
        return None
    if _index is None:
        _index = _build_index(textures_vpk)

    key = key.replace("\\", "/").strip().lower()
    if key.startswith("backpack/"):
        # Явный путь из items_game — он уже точный, индекс не нужен.
        return f"materials/{key}.vtf"

    name = key.rsplit("/", 1)[-1].removesuffix(".mdl")
    for candidate in (name, "w_" + name[2:] if name.startswith("c_") else None,
                      "w_" + name):
        if candidate and candidate in _index:
            return _index[candidate]
    return None


def material_png(rel: str, textures_vpk: str) -> Optional[bytes]:
    """PNG любой игровой картинки по пути внутри `materials/`, без расширения.

    Нужна не рюкзаку, а каталогу звуков: у реплики нет предмета, зато есть
    класс, а у класса есть портрет (`vgui/class_portraits/scout`). Индекс
    рюкзака сюда не годится — он собран только по `materials/backpack/`.
    """
    rel = (rel or '').replace(chr(92), '/').strip().strip('/').lower()
    if not rel or '..' in rel.split('/'):
        return None
    path = f"materials/{rel}.vtf"
    cached = _CACHE_DIR / (rel.replace('/', '_') + '.png')
    return _decode(path, cached, textures_vpk)


def png_bytes(key: str, textures_vpk: str) -> Optional[bytes]:
    """PNG иконки предмета, либо None если её в игре нет."""
    path = vpk_path_for(key, textures_vpk)
    if not path:
        return None

    cached = _CACHE_DIR / (path[len("materials/backpack/"):].replace("/", "_")[:-4] + ".png")
    return _decode(path, cached, textures_vpk)


def _decode(path: str, cached: Path, textures_vpk: str) -> Optional[bytes]:
    """VTF из игрового архива в PNG, с оглядкой на уже разобранное."""
    if cached.exists():
        return cached.read_bytes()

    from src.services.vpk_cache import open_vpk_cached
    from src.services.vtf_preview_service import vtf_bytes_to_png

    pak = open_vpk_cached(textures_vpk)
    if pak is None:
        return None
    try:
        data = pak[path].read()
    except KeyError:
        return None
    except Exception as exc:                          # noqa: BLE001
        logger.debug(f"[icons] не прочитать {path}: {exc}")
        return None

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if vtf_bytes_to_png(data, str(cached)) is None:
        return None
    return cached.read_bytes()
