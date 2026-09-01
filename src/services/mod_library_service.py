"""
Библиотека чужих модов: папка на диске плюс правила обращения с ней.

Зачем. Мод, открытый через браузер, приезжает во временную папку: путь к
исходному файлу страница не знает и знать не может. Временную папку рано или
поздно чистят, и «открой мод, который я смотрел вчера» превращается в «найди
его заново». Поэтому открытый мод кладётся в постоянную папку, и она же
работает списком.

Отдельной базы нет намеренно: папка и есть список. Один источник правды,
никакой рассинхронизации индекса с файлами, и человек может положить туда
мод руками.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Куда складываются открытые моды. Рядом с export — это тоже рабочие файлы
#: пользователя, а не служебный кэш.
LIBRARY_DIR = Path('mods')


def library_dir() -> Path:
    """Папка библиотеки; создаётся при первом обращении."""
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    return LIBRARY_DIR


def _free_name(name: str) -> Path:
    """
    Свободное имя в библиотеке.

    Одноимённый мод не затираем: два разных `weapon.vpk` от разных авторов —
    обычное дело, и молча потерять один из них хуже, чем показать два.
    """
    folder = library_dir()
    candidate = folder / name
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    for i in range(1, 1000):
        candidate = folder / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError('не подобрать имя в библиотеке модов')


def resolve(name: str) -> Optional[Path]:
    """
    Путь к моду по ИМЕНИ файла — или None, если такого в библиотеке нет.

    Наружу отдаются только имена, и путь собирается здесь: иначе присланное
    «../../что-нибудь» увело бы открытие и удаление к любому файлу на диске.
    """
    if not name:
        return None
    path = library_dir() / Path(str(name)).name
    return path if path.is_file() else None


def add(source: str) -> Optional[Path]:
    """
    Кладёт мод в библиотеку и отдаёт его новый путь.

    Файл, который УЖЕ лежит в библиотеке, не копируется второй раз: иначе
    повторное открытие плодило бы `mod_1.vpk`, `mod_2.vpk` из одного и того же.
    """
    if not source or not os.path.isfile(source):
        return None

    src = Path(source).resolve()
    folder = library_dir().resolve()
    if src.parent == folder:
        return src

    target = _free_name(src.name)
    shutil.copy2(src, target)
    logger.info(f"мод в библиотеке: {target}")
    return target


def _icon_path(name: str) -> Path:
    folder = library_dir() / ICON_DIR_NAME
    folder.mkdir(parents=True, exist_ok=True)
    return folder / (Path(name).stem + '.png')


def items() -> List[Dict[str, object]]:
    """Что лежит в библиотеке: имя, размер, когда добавлен. Новые сверху."""
    folder = library_dir()
    out: List[Dict[str, object]] = []
    for file in folder.glob('*.vpk'):
        try:
            stat = file.stat()
        except OSError:
            continue
        # Обложку здесь только ПОКАЗЫВАЕМ, если она уже есть: строить её на
        # каждый показ каталога — это декодировать VTF столько раз, сколько
        # модов в библиотеке. Недостающие достраиваются по одной (icon).
        ready = _icon_path(file.name)
        out.append({
            'name': file.name,
            'path': str(file),
            'size': stat.st_size,
            'modified': stat.st_mtime,
            'icon': (str(ready) if ready.is_file()
                     and ready.stat().st_mtime >= stat.st_mtime else None),
        })
    out.sort(key=lambda item: item['modified'], reverse=True)
    return out


def remove(name: str) -> bool:
    """Удаляет мод из библиотеки. False — такого файла в ней нет."""
    path = resolve(name)
    if path is None:
        return False
    try:
        path.unlink()
    except OSError as exc:
        logger.warning(f"не удалить мод {path}: {exc}")
        return False
    # Обложка без мода не нужна и опасна: одноимённый мод получил бы чужую.
    icon_file = _icon_path(path.name)
    if icon_file.is_file():
        try:
            icon_file.unlink()
        except OSError:
            pass
    logger.info(f"мод удалён из библиотеки: {path}")
    return True


# ═══════════════════════════════════════════════════════════════════════════ #
# Обложки
# ═══════════════════════════════════════════════════════════════════════════ #
#
# Обложка мода — его основная текстура. Не рендер модели: чтобы получить
# картинку модели, нужен работающий вьювер, а текстура лежит в самом файле и
# достаётся чтением. Для списка этого достаточно — моды узнаются по ней.

#: Обложки живут рядом с модами, но отдельно: точка в имени прячет папку от
#: glob('*.vpk') и от глаз в проводнике.
ICON_DIR_NAME = '.icons'
#: Больше не нужно: карточка в каталоге размером с ноготь.
ICON_SIZE = 256


def _main_vtf(pak) -> Optional[bytes]:
    """
    Байты основной текстуры мода.

    Порядок тот же, что у превью: сначала $baseTexture из VMT (авторитетно —
    так текстуру находит сама игра), и только потом догадка по именам файлов.
    """
    from src.services.game_vpk_reader import GameVpkReader
    from src.services.preview_vpk_mod_worker import is_base_vtf

    paths = list(pak)
    for vmt in (p for p in paths if p.lower().endswith('.vmt')):
        try:
            content = pak[vmt].read().decode('utf-8', errors='ignore')
        except (KeyError, OSError):
            continue
        base = GameVpkReader.parse_basetexture(content)
        data = GameVpkReader.find_vtf_in_pak(pak, base) if base else None
        if data:
            return data

    # VMT может не быть вовсе (мод из одних текстур) — берём первую неслужебную.
    for vtf in sorted(p for p in paths if p.lower().endswith('.vtf')):
        if is_base_vtf(vtf):
            try:
                return pak[vtf].read()
            except (KeyError, OSError):
                continue
    return None


def icon(name: str) -> Optional[Path]:
    """
    Путь к обложке мода; при необходимости строит её.

    Обложка кэшируется на диске и переснимается, только если сам мод новее:
    декодировать VTF на каждый показ каталога незачем.
    """
    mod = resolve(name)
    if mod is None:
        return None

    out = _icon_path(mod.name)
    if out.is_file() and out.stat().st_mtime >= mod.stat().st_mtime:
        return out

    from PIL import Image
    from src.services.vpk_cache import open_vpk_cached
    from src.services.vtf_preview_service import vtf_bytes_to_png

    try:
        pak = open_vpk_cached(str(mod))
    except Exception as exc:                      # noqa: BLE001 — vpk кидает своё
        logger.warning(f"обложка: не открыть {mod.name}: {exc}")
        return None
    if pak is None:
        return None

    data = _main_vtf(pak)
    if not data or not vtf_bytes_to_png(data, str(out)):
        logger.info(f"обложка: в {mod.name} не нашлось основной текстуры")
        return None

    # Уменьшаем на месте: полноразмерная текстура в каталоге — мегабайты
    # трафика ради картинки в палец шириной.
    try:
        with Image.open(out) as img:
            img.thumbnail((ICON_SIZE, ICON_SIZE))
            img.save(out)
    except OSError as exc:
        logger.warning(f"обложка: не уменьшить {out.name}: {exc}")
    return out
