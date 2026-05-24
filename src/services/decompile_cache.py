"""
Кэш декомпилированных моделей TF2.

Crowbar decompile — самый долгий шаг (10-30 сек).
Плюс extract_file_set — ещё 3-10 сек.
Вместе это ~15-40 секунд которые можно сэкономить.

Ключ кэша = weapon_key + mdl_rel_path + mtime VPK файла.
  - mtime VPK меняется при обновлении TF2 → кэш автоматически инвалидируется.
  - Проверка mtime мгновенная (один stat() вызов).
  - На cache hit: пропускаем и extraction, и decompile.
"""

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Optional

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

_CACHE_DIR = Path(os.path.expanduser("~")) / ".tf2skingen_cache" / "decompiled"
_META_FILENAME = "_cache_meta.json"
_CACHE_VERSION = 3  # v3: использует vpk_mtime вместо mdl_hash


def get_cache_dir() -> Path:
    """Возвращает папку кэша, создаёт если нет."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR


def _vpk_mtime(vpk_path: str) -> str:
    """Время модификации VPK файла — меняется при обновлении игры."""
    try:
        mtime = os.path.getmtime(vpk_path)
        return f"{mtime:.0f}"
    except OSError:
        return "0"


def _cache_key(weapon_key: str, vpk_path: str, mdl_rel_path: str) -> str:
    """
    Ключ кэша на основе оружия, VPK файла и пути к MDL.
    Используем hash чтобы избежать проблем с длинными путями.
    """
    raw = f"{weapon_key}|{vpk_path}|{mdl_rel_path}|{_vpk_mtime(vpk_path)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _meta_path(cache_entry_dir: Path) -> Path:
    return cache_entry_dir / _META_FILENAME


def get_cached_decompile(
    weapon_key: str,
    vpk_path: str,
    mdl_rel_path: str,
) -> Optional[str]:
    """
    Проверяет кэш **до** extraction — только по mtime VPK.

    Args:
        weapon_key:   Ключ оружия (например "c_flaregun_pyro")
        vpk_path:     Путь к tf2_misc_dir.vpk
        mdl_rel_path: Относительный путь к MDL внутри VPK

    Returns:
        Путь к закэшированной папке с QC/SMD, или None при промахе.
    """
    try:
        key = _cache_key(weapon_key, vpk_path, mdl_rel_path)
        entry_dir = get_cache_dir() / key

        if not entry_dir.exists():
            logger.debug(f"Кэш декомпила не найден: {weapon_key}")
            return None

        meta_file = _meta_path(entry_dir)
        if not meta_file.exists():
            shutil.rmtree(entry_dir, ignore_errors=True)
            return None

        with open(meta_file, "r", encoding="utf-8") as f:
            meta = json.load(f)

        if meta.get("version") != _CACHE_VERSION:
            logger.info(f"Версия кэша устарела для {weapon_key}, сбрасываем")
            shutil.rmtree(entry_dir, ignore_errors=True)
            return None

        # Проверяем что VPK не изменился (дополнительная страховка)
        stored_mtime = meta.get("vpk_mtime", "")
        current_mtime = _vpk_mtime(vpk_path)
        if stored_mtime != current_mtime:
            logger.info(f"VPK обновился, кэш для {weapon_key} недействителен")
            shutil.rmtree(entry_dir, ignore_errors=True)
            return None

        # Проверяем что QC файл на месте
        qc_name = meta.get("qc_filename")
        if not qc_name or not (entry_dir / qc_name).exists():
            logger.warning(f"QC файл в кэше не найден: {weapon_key}")
            shutil.rmtree(entry_dir, ignore_errors=True)
            return None

        logger.info(f"✓ Кэш декомпила: {weapon_key} — пропускаем extraction + decompile")
        return str(entry_dir)

    except Exception as e:
        logger.warning(f"Ошибка при чтении кэша декомпила: {e}")
        return None


def save_to_cache(
    weapon_key: str,
    vpk_path: str,
    mdl_rel_path: str,
    decompile_dir: str,
) -> Optional[str]:
    """
    Сохраняет декомпилированные файлы в кэш.

    Args:
        weapon_key:    Ключ оружия
        vpk_path:      Путь к VPK файлу
        mdl_rel_path:  Относительный путь MDL в VPK
        decompile_dir: Папка с QC + SMD после Crowbar
    """
    try:
        key = _cache_key(weapon_key, vpk_path, mdl_rel_path)
        entry_dir = get_cache_dir() / key

        if entry_dir.exists():
            shutil.rmtree(entry_dir)

        shutil.copytree(decompile_dir, entry_dir)

        # Имя QC
        qc_name = None
        for f in Path(decompile_dir).iterdir():
            if f.suffix.lower() == ".qc":
                qc_name = f.name
                break

        meta = {
            "version": _CACHE_VERSION,
            "weapon_key": weapon_key,
            "vpk_path": vpk_path,
            "mdl_rel_path": mdl_rel_path,
            "vpk_mtime": _vpk_mtime(vpk_path),
            "qc_filename": qc_name,
        }
        with open(_meta_path(entry_dir), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        logger.info(f"✓ Кэш декомпила сохранён: {weapon_key}")
        return str(entry_dir)

    except Exception as e:
        logger.warning(f"Не удалось сохранить кэш декомпила: {e}")
        return None


def restore_from_cache(cache_dir: str, target_dir: str) -> str:
    """
    Копирует QC/SMD из кэша в рабочую директорию.

    Returns:
        Путь к QC файлу в target_dir.
    """
    cache_path = Path(cache_dir)
    target_path = Path(target_dir)
    target_path.mkdir(parents=True, exist_ok=True)

    shutil.copytree(
        cache_path, target_path,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(_META_FILENAME),
    )

    with open(cache_path / _META_FILENAME, "r", encoding="utf-8") as f:
        meta = json.load(f)

    qc_name = meta.get("qc_filename")
    if qc_name and (target_path / qc_name).exists():
        return str(target_path / qc_name)

    for f in target_path.iterdir():
        if f.suffix.lower() == ".qc":
            return str(f)

    raise RuntimeError(f"QC file not found after restoring from cache in {target_dir}")


def find_cached_qc_for_weapon(weapon_key: str) -> Optional[str]:
    """
    Ищет в кэше декомпиляции QC-файл для любого варианта weapon_key
    (не требует знать точный vpk_path или mdl_rel_path).

    Используется, например, при извлечении текстуры шапки — чтобы
    узнать реальное имя текстуры из $texturegroup, а не угадывать его
    по имени MDL-файла.

    Returns:
        Полный путь к QC-файлу или None если кэша нет.
    """
    try:
        cache_dir = get_cache_dir()
        for entry in cache_dir.iterdir():
            if not entry.is_dir():
                continue
            meta_file = _meta_path(entry)
            if not meta_file.exists():
                continue
            try:
                with open(meta_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:
                continue
            if meta.get("weapon_key") != weapon_key:
                continue
            if meta.get("version") != _CACHE_VERSION:
                continue
            qc_name = meta.get("qc_filename")
            if not qc_name:
                continue
            qc_path = entry / qc_name
            if qc_path.exists():
                logger.debug(f"QC найден в кэше для {weapon_key}: {qc_path}")
                return str(qc_path)
    except Exception as e:
        logger.warning(f"Ошибка поиска QC в кэше для {weapon_key}: {e}")
    return None


def clear_cache(weapon_key: Optional[str] = None) -> int:
    """
    Очищает кэш.

    Args:
        weapon_key: Если указан — только для этого оружия. None — весь кэш.

    Returns:
        Количество удалённых записей.
    """
    cache_dir = get_cache_dir()
    count = 0
    try:
        for entry in cache_dir.iterdir():
            if not entry.is_dir():
                continue
            if weapon_key is not None:
                meta_file = _meta_path(entry)
                if meta_file.exists():
                    try:
                        with open(meta_file, "r", encoding="utf-8") as f:
                            meta = json.load(f)
                        if meta.get("weapon_key") != weapon_key:
                            continue
                    except Exception:
                        pass
                else:
                    continue
            shutil.rmtree(entry, ignore_errors=True)
            count += 1
    except Exception as e:
        logger.warning(f"Ошибка при очистке кэша: {e}")
    return count


def get_cache_size_mb() -> float:
    """Размер кэша в МБ."""
    try:
        total = sum(
            f.stat().st_size
            for f in get_cache_dir().rglob("*")
            if f.is_file()
        )
        return total / (1024 * 1024)
    except Exception:
        return 0.0
