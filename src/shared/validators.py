"""
Валидаторы для входных данных
"""

from pathlib import Path
from typing import Tuple, Optional, List
from .constants import ValidationLimits, VTFFormat, Resolution
from .exceptions import InvalidFilenameError, InvalidImageError, ValidationError


def validate_vpk_filename(filename: str) -> Tuple[bool, Optional[str]]:
    """
    Валидирует имя VPK файла
    
    Args:
        filename: Имя файла для проверки
        
    Returns:
        Tuple[bool, Optional[str]]: (is_valid, error_message)
    """
    if not filename:
        return False, "Имя файла не может быть пустым"
    
    filename = filename.strip()
    
    # Проверка длины
    if len(filename) < ValidationLimits.MIN_FILENAME_LENGTH:
        return False, f"Имя файла слишком короткое (минимум {ValidationLimits.MIN_FILENAME_LENGTH} символ)"
    
    if len(filename) > ValidationLimits.MAX_FILENAME_LENGTH:
        return False, f"Имя файла слишком длинное (максимум {ValidationLimits.MAX_FILENAME_LENGTH} символов)"
    
    # Проверка на недопустимые символы
    for char in ValidationLimits.INVALID_FILENAME_CHARS:
        if char in filename:
            return False, f"Недопустимый символ: {char}"
    
    # Проверка расширения
    if not filename.lower().endswith('.vpk'):
        return False, "Имя файла должно заканчиваться на .vpk"
    
    return True, None


def validate_tf2_path(path: str) -> Tuple[bool, Optional[str]]:
    """
    Валидирует путь к TF2
    
    Args:
        path: Путь к директории TF2
        
    Returns:
        Tuple[bool, Optional[str]]: (is_valid, error_message)
    """
    if not path:
        return False, "Путь не указан"
    
    path_obj = Path(path)
    
    if not path_obj.exists():
        return False, "Путь не существует"
    
    if not path_obj.is_dir():
        return False, "Путь не является директорией"
    
    # Проверка наличия необходимых файлов
    required_files = ["tf2.exe"]
    for file in required_files:
        if not (path_obj / file).exists():
            return False, f"Не найден файл: {file}"
    
    return True, None


def validate_image_path(image_path: str | Path) -> Tuple[bool, Optional[str]]:
    """
    Валидирует путь к изображению
    
    Args:
        image_path: Путь к изображению
        
    Returns:
        Tuple[bool, Optional[str]]: (is_valid, error_message)
    """
    if not image_path:
        return False, "Путь к изображению не указан"
    
    path = Path(image_path)
    
    if not path.exists():
        return False, f"Изображение не найдено: {image_path}"
    
    if not path.is_file():
        return False, f"Путь не является файлом: {image_path}"
    
    # Проверка расширения
    valid_extensions = ['.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff', '.webp']
    if path.suffix.lower() not in valid_extensions:
        return False, f"Неподдерживаемый формат изображения: {path.suffix}"
    
    # Проверка размера файла (максимум 100MB)
    max_size_mb = 100
    file_size_mb = path.stat().st_size / (1024 * 1024)
    if file_size_mb > max_size_mb:
        return False, f"Файл слишком большой: {file_size_mb:.2f}MB (максимум {max_size_mb}MB)"
    
    return True, None


def validate_vtf_format(format_type: str) -> Tuple[bool, Optional[str]]:
    """
    Валидирует формат VTF
    
    Args:
        format_type: Формат VTF
        
    Returns:
        Tuple[bool, Optional[str]]: (is_valid, error_message)
    """
    if not format_type:
        return False, "Формат не указан"
    
    if not VTFFormat.is_valid(format_type):
        valid_formats = ", ".join(VTFFormat.VALID_FORMATS)
        return False, f"Недопустимый формат: {format_type}. Допустимые: {valid_formats}"
    
    return True, None


def validate_resolution(size: Tuple[int, int] | List[int]) -> Tuple[bool, Optional[str]]:
    """
    Валидирует разрешение изображения
    
    Args:
        size: Кортеж (width, height)
        
    Returns:
        Tuple[bool, Optional[str]]: (is_valid, error_message)
    """
    if not size or len(size) != 2:
        return False, "Разрешение должно быть кортежем из двух чисел"
    
    width, height = size
    
    if not isinstance(width, int) or not isinstance(height, int):
        return False, "Ширина и высота должны быть целыми числами"
    
    if width < ValidationLimits.MIN_IMAGE_SIZE or height < ValidationLimits.MIN_IMAGE_SIZE:
        return False, f"Размер должен быть минимум {ValidationLimits.MIN_IMAGE_SIZE}x{ValidationLimits.MIN_IMAGE_SIZE}"
    
    if width > ValidationLimits.MAX_IMAGE_SIZE or height > ValidationLimits.MAX_IMAGE_SIZE:
        return False, f"Размер должен быть максимум {ValidationLimits.MAX_IMAGE_SIZE}x{ValidationLimits.MAX_IMAGE_SIZE}"
    
    # Проверка на степень двойки (рекомендация)
    if width & (width - 1) != 0 or height & (height - 1) != 0:
        return False, "Размеры должны быть степенью двойки (512, 1024, 2048, etc.)"
    
    return True, None


def validate_mode(mode: str) -> Tuple[bool, Optional[str]]:
    """
    Валидирует режим оружия
    
    Args:
        mode: Режим оружия (например, "scout_c_scattergun" или "critHIT")
        
    Returns:
        Tuple[bool, Optional[str]]: (is_valid, error_message)
    """
    if not mode:
        return False, "Режим не указан"
    
    if not isinstance(mode, str):
        return False, "Режим должен быть строкой"
    
    # Проверка на специальные режимы
    from src.data.weapons import SPECIAL_MODES
    if mode in SPECIAL_MODES.values():
        return True, None
    
    # Проверка формата обычного режима: class_weapon
    if '_' not in mode:
        return False, "Режим должен быть в формате 'class_weapon' (например, 'scout_c_scattergun')"
    
    parts = mode.split('_', 1)
    if len(parts) != 2:
        return False, "Режим должен быть в формате 'class_weapon'"
    
    return True, None

