"""
Хранилище правок: что человек сделал над предметом, между запусками.

Зачем. Положенная текстура, своя геометрия и правленый QC не берутся ниоткуда:
их либо сохранили, либо потеряли. Всё остальное (имена материалов, игровые
оригиналы, кадры команд) модель отдаёт заново при каждой загрузке, и хранить
его нельзя — замёрзнут пути во временные папки.

Ключ — ПРЕДМЕТ, а не мод: та же потеря происходит с обычным оружием, и второй
такой же механизм для него заводить незачем.

Файлы, на которые ссылаются правки, копируются к себе. Причина та же, что у
библиотеки модов: текстура, пришедшая через браузер, лежит во временной папке
системы, и сохранённая работа рассыпалась бы при первой же её чистке.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Dict, Optional

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Рядом с export и mods: это данные пользователя, а не служебный кэш.
WORK_DIR = Path('work')

#: Версия формата. Файл от другой версии не читаем — правила «моё/производное»
#: могут разойтись, и молча применённый чужой формат хуже потерянной работы.
FORMAT = 1


def work_dir() -> Path:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    return WORK_DIR


def key_for(mode: str, item: str = '') -> str:
    """
    Имя папки работы по предмету.

    Режим плюс ключ предмета: у оружия это `scout_c_scattergun` + `c_scattergun`,
    у мода — `custom` + имя файла в библиотеке. Всё, что не буква и не цифра,
    сводим к подчёркиванию: ключом бывает и путь к MDL.
    """
    raw = f"{mode}__{item}" if item else str(mode)
    slug = re.sub(r'[^a-zA-Z0-9._-]+', '_', raw).strip('_').lower()
    return slug[:120] or 'unknown'


def _folder(key: str) -> Path:
    folder = work_dir() / key
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _own_file(path: Optional[str], files_dir: Path) -> Optional[str]:
    """
    Кладёт файл рядом с работой и отдаёт новый путь.

    Файл, который уже внутри нашей папки, не копируется: иначе каждое
    сохранение плодило бы копию копии.
    """
    if not path or not os.path.isfile(path):
        return None
    src = Path(path).resolve()
    files_dir.mkdir(parents=True, exist_ok=True)
    if src.parent == files_dir.resolve():
        return str(src)

    target = files_dir / src.name
    # Разные материалы могут ссылаться на разные файлы с одинаковым именем.
    if target.exists() and target.stat().st_size != src.stat().st_size:
        stem, suffix = target.stem, target.suffix
        for i in range(1, 1000):
            candidate = files_dir / f"{stem}_{i}{suffix}"
            if not candidate.exists():
                target = candidate
                break
    if not target.exists():
        shutil.copy2(src, target)
    return str(target)


def _own_paths(edits: Dict[str, object], files_dir: Path) -> Dict[str, object]:
    """
    Заменяет пути в правках на свои копии.

    Места перечислены явно, а не обходом по всему словарю: так видно, что
    именно считается файлом, и случайная строка не превратится в копию.
    """
    out = dict(edits)

    out['textures'] = {
        team: {mat: owned for mat, path in (paths or {}).items()
               if (owned := _own_file(path, files_dir))}
        for team, paths in (edits.get('textures') or {}).items()
    }
    out['skin_overrides'] = {
        skin: {mat: owned for mat, path in (paths or {}).items()
               if (owned := _own_file(path, files_dir))}
        for skin, paths in (edits.get('skin_overrides') or {}).items()
    }
    # Картинки частей: без своей копии «покрасил ствол» пропадало бы, стоило
    # человеку переложить исходник в другую папку.
    out['part_textures'] = {
        mat: {part: owned for part, path in (items or {}).items()
              if (owned := _own_file(path, files_dir))}
        for mat, items in (edits.get('part_textures') or {}).items()
    }
    out['australium_user_tex'] = _own_file(
        edits.get('australium_user_tex'), files_dir)
    out['custom_smd_path'] = _own_file(edits.get('custom_smd_path'), files_dir)

    maps: Dict[str, dict] = {}
    for mat, by_id in (edits.get('texture_maps') or {}).items():
        clean = {}
        for map_id, spec in (by_id or {}).items():
            spec = dict(spec or {})
            if spec.get('image'):
                owned = _own_file(spec['image'], files_dir)
                if not owned:
                    continue          # картинки больше нет — карта без неё пуста
                spec['image'] = owned
            clean[map_id] = spec
        if clean:
            maps[mat] = clean
    out['texture_maps'] = maps
    return out


def save(key: str, edits: Dict[str, object]) -> Optional[Path]:
    """Сохраняет правки предмета. Пишем через временный файл: две вкладки
    могут сохранять одновременно, и половина файла хуже его отсутствия."""
    if not key or not edits:
        return None

    folder = _folder(key)
    payload = {'format': FORMAT, 'edits': _own_paths(edits, folder / 'files')}
    target = folder / 'edits.json'
    tmp = folder / 'edits.json.tmp'
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                       encoding='utf-8')
        os.replace(tmp, target)
    except OSError as exc:
        logger.warning(f"работа «{key}» не сохранена: {exc}")
        return None
    return target


def load(key: str) -> Optional[Dict[str, object]]:
    """
    Возвращает правки предмета или None.

    Пути, файлов по которым уже нет, отбрасываются: лучше вернуть три текстуры
    из четырёх, чем упасть или показать пустой кадр вместо картинки.
    """
    path = work_dir() / key / 'edits.json'
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        logger.warning(f"работа «{key}» не прочитана: {exc}")
        return None
    if payload.get('format') != FORMAT:
        logger.info(f"работа «{key}» от другой версии формата — пропущена")
        return None

    edits = payload.get('edits') or {}
    for team, paths in list((edits.get('textures') or {}).items()):
        edits['textures'][team] = {m: p for m, p in paths.items()
                                   if os.path.isfile(p)}
    for skin, paths in list((edits.get('skin_overrides') or {}).items()):
        edits['skin_overrides'][skin] = {m: p for m, p in paths.items()
                                         if os.path.isfile(p)}
    if edits.get('custom_smd_path') and not os.path.isfile(edits['custom_smd_path']):
        edits['custom_smd_path'] = None
    return edits


def forget(key: str) -> bool:
    """Удаляет работу над предметом вместе с её файлами."""
    folder = work_dir() / key
    if not folder.is_dir():
        return False
    shutil.rmtree(folder, ignore_errors=True)
    logger.info(f"работа «{key}» удалена")
    return not folder.exists()


def has(key: str) -> bool:
    """Есть ли сохранённая работа над предметом."""
    return (work_dir() / key / 'edits.json').is_file()
