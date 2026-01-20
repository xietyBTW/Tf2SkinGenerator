"""
Утилиты для работы с файлами
"""

import os
import shutil
from pathlib import Path
from typing import Optional, List
from .exceptions import FileNotFoundError, DirectoryNotFoundError


def ensure_file_exists(file_path: str | Path) -> Path:
    """
    Проверяет существование файла, выбрасывает исключение если нет
    
    Args:
        file_path: Путь к файлу
        
    Returns:
        Path объект файла
        
    Raises:
        FileNotFoundError: Если файл не существует
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(str(path))
    if not path.is_file():
        raise FileNotFoundError(str(path), f"Путь не является файлом: {path}")
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


def ensure_directory_exists_strict(dir_path: str | Path) -> Path:
    """
    Проверяет существование директории, выбрасывает исключение если нет
    
    Args:
        dir_path: Путь к директории
        
    Returns:
        Path объект директории
        
    Raises:
        DirectoryNotFoundError: Если директория не существует
    """
    path = Path(dir_path)
    if not path.exists():
        raise DirectoryNotFoundError(str(path))
    if not path.is_dir():
        raise DirectoryNotFoundError(str(path), f"Путь не является директорией: {path}")
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


def sanitize_path(user_path: str, base_dir: Path) -> Path:
    """
    Обезопашивает путь, предотвращая path traversal атаки
    
    Args:
        user_path: Пользовательский путь
        base_dir: Базовая директория
        
    Returns:
        Обезопасенный Path объект
        
    Raises:
        ValueError: Если путь выходит за пределы базовой директории
    """
    base_resolved = base_dir.resolve()
    resolved = (base_dir / user_path).resolve()
    
    try:
        resolved.relative_to(base_resolved)
    except ValueError:
        raise ValueError(f"Недопустимый путь: {user_path} (выходит за пределы {base_dir})")
    
    return resolved


def get_file_size_mb(file_path: str | Path) -> float:
    """
    Получает размер файла в мегабайтах
    
    Args:
        file_path: Путь к файлу
        
    Returns:
        Размер файла в MB
    """
    path = Path(file_path)
    if not path.exists():
        return 0.0
    return path.stat().st_size / (1024 * 1024)


def find_files_by_extension(
    directory: str | Path,
    extensions: List[str],
    recursive: bool = True
) -> List[Path]:
    """
    Находит все файлы с указанными расширениями
    
    Args:
        directory: Директория для поиска
        extensions: Список расширений (например, ['.mdl', '.vmt'])
        recursive: Рекурсивный поиск
        
    Returns:
        Список найденных файлов
    """
    directory = Path(directory)
    if not directory.exists():
        return []
    
    found_files = []
    extensions_lower = [ext.lower() for ext in extensions]
    
    if recursive:
        for file_path in directory.rglob('*'):
            if file_path.is_file() and file_path.suffix.lower() in extensions_lower:
                found_files.append(file_path)
    else:
        for file_path in directory.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in extensions_lower:
                found_files.append(file_path)
    
    return found_files


def copy_file_safe(source: str | Path, destination: str | Path) -> Path:
    """
    Безопасно копирует файл, создавая директорию назначения если нужно
    
    Args:
        source: Путь к исходному файлу
        destination: Путь к файлу назначения
        
    Returns:
        Path к скопированному файлу
        
    Raises:
        FileNotFoundError: Если исходный файл не существует
    """
    source_path = ensure_file_exists(source)
    dest_path = Path(destination)
    
    # Создаем директорию назначения если нужно
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    
    shutil.copy2(source_path, dest_path)
    return dest_path


def get_temp_file_path(prefix: str = "temp", suffix: str = ".tmp", directory: Optional[Path] = None) -> Path:
    """
    Генерирует путь к временному файлу
    
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

