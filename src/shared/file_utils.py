"""
Утилиты для работы с файлами
"""

import os
import shutil
from pathlib import Path
from typing import Optional
from .exceptions import RequiredFileMissingError


def ensure_file_exists(file_path: str | Path) -> Path:
    """
    Проверяет существование файла, выбрасывает исключение если нет

    Args:
        file_path: Путь к файлу

    Returns:
        Path объект файла

    Raises:
        RequiredFileMissingError: Если файл не существует
    """
    path = Path(file_path)
    if not path.exists():
        raise RequiredFileMissingError(str(path))
    if not path.is_file():
        raise RequiredFileMissingError(str(path), f"Путь не является файлом: {path}")
    return path


def ensure_directory_exists(dir_path: str | Path) -> Path:
    """
    Создает директорию если не существует

    Args:
        dir_path: Путь к директории

    Returns:
        Path объект директории
    """
    path = Path(dir_path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_remove(path: str | Path, is_dir: bool = False) -> bool:
    """
    Безопасно удаляет файл или директорию

    Args:
        path: Путь к файлу/директории
        is_dir: True если это директория

    Returns:
        True если удаление успешно, False если ошибка
    """
    try:
        path_obj = Path(path)
        if not path_obj.exists():
            return True

        if is_dir:
            shutil.rmtree(path_obj)
        else:
            path_obj.unlink()
        return True
    except Exception:
        return False


def copy_file_safe(source: str | Path, destination: str | Path) -> Path:
    """
    Безопасно копирует файл, создавая директорию назначения если нужно

    Args:
        source: Путь к исходному файлу
        destination: Путь к файлу назначения

    Returns:
        Path к скопированному файлу

    Raises:
        RequiredFileMissingError: Если исходный файл не существует
    """
    source_path = ensure_file_exists(source)
    dest_path = Path(destination)

    # Создаем директорию назначения если нужно
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    shutil.copy2(source_path, dest_path)
    return dest_path


# Префиксы наших временных файлов/папок в системной temp (3D-превью, VTF-превью,
# декомпиляция и т.п.). Файлы нужны UI и после завершения воркеров, поэтому
# удаляются не сразу, а отложенно — cleanup_stale_temp_artifacts при старте.
_TEMP_ARTIFACT_PREFIXES = (
    "tf2sg_",
    "tf2_crithit_", "tf2_smd_preview_", "tf2_3d_", "tf2_3ddrop_",
    "tf2_deatheff_", "tf2_model_tex_", "tf2_vtf_",
)


def cleanup_stale_temp_artifacts(max_age_hours: float = 24.0,
                                 temp_dir: Optional[Path] = None) -> int:
    """
    Удаляет из системной temp-папки устаревшие артефакты приложения
    (папки/файлы с нашими префиксами старше max_age_hours).

    Раньше temp-папки превью (tf2sg_3d_* и др.) не удалялись вовсе и копились
    бесконечно. Порог по возрасту защищает файлы текущего и параллельного
    запусков. Ошибки удаления (файл занят) молча пропускаются.

    Returns:
        Количество удалённых записей.
    """
    import tempfile
    import time

    root = Path(temp_dir) if temp_dir else Path(tempfile.gettempdir())
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    try:
        entries = list(os.scandir(root))
    except OSError:
        return 0
    for entry in entries:
        if not entry.name.startswith(_TEMP_ARTIFACT_PREFIXES):
            continue
        try:
            if entry.stat().st_mtime >= cutoff:
                continue
            if entry.is_dir():
                shutil.rmtree(entry.path, ignore_errors=True)
            else:
                os.unlink(entry.path)
            removed += 1
        except OSError:
            continue
    return removed


def get_temp_file_path(prefix: str = "temp", suffix: str = ".tmp", directory: Optional[Path] = None) -> Path:
    """
    Генерирует путь к временному файлу (безопасная замена tempfile.mktemp)

    Args:
        prefix: Префикс имени файла
        suffix: Суффикс (расширение)
        directory: Директория для временного файла (если None, используется системная)

    Returns:
        Path к временному файлу
    """
    import tempfile

    if directory:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        return directory / f"{prefix}_{os.urandom(8).hex()}{suffix}"
    else:
        fd, path = tempfile.mkstemp(prefix=prefix, suffix=suffix)
        os.close(fd)
        return Path(path)
