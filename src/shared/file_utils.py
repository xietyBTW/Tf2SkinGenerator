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
