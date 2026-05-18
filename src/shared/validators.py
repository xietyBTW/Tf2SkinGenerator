"""
Валидаторы для входных данных
"""

import os
from pathlib import Path
from typing import Tuple, Optional, List
from src.data.weapons import SPECIAL_MODES
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


def sanitize_path(path: str, base_dir: str) -> str:
    base_dir_abs = os.path.abspath(base_dir)
    if path.startswith('/'):
        path = path[1:]
    if ':' in path:
        raise ValueError(f"Недопустимый путь: {path}")
    full_path = os.path.abspath(os.path.join(base_dir_abs, path))
    if not full_path.startswith(base_dir_abs):
        raise ValueError(f"Недопустимый путь: {path}")
    return full_path


def validate_build_params(
    image_path: str,
    mode: str,
    filename: str,
    size: Tuple[int, int],
    format_type: str,
    tf2_root_dir: str,
    t: dict = None,
    custom_vtf_path: str = None
) -> Optional[str]:
    if t is None:
        from src.data.translations import TRANSLATIONS
        t = TRANSLATIONS['en']
    if not custom_vtf_path:
        if not image_path or not isinstance(image_path, str):
            return t['error_image_not_specified']
        if not os.path.exists(image_path):
            return t['error_image_not_found'].format(path=image_path)
        if not os.path.isfile(image_path):
            return t['error_image_not_file'].format(path=image_path)
    else:
        if not os.path.exists(custom_vtf_path):
            error_template = t.get('error_custom_vtf_not_found')
            if error_template:
                return error_template.format(path=custom_vtf_path)
            return f'Custom VTF file not found: {custom_vtf_path}'
        if not os.path.isfile(custom_vtf_path):
            error_template = t.get('error_custom_vtf_not_file')
            if error_template:
                return error_template.format(path=custom_vtf_path)
            return f'Custom VTF path is not a file: {custom_vtf_path}'
    if not mode or not isinstance(mode, str):
        return t['error_mode_not_specified']
    if not filename or not isinstance(filename, str):
        return t['error_filename_not_specified']
    if not filename.endswith('.vpk'):
        return t['error_filename_no_vpk']
    if not isinstance(size, (tuple, list)) or len(size) != 2:
        return t['error_size_invalid']
    width, height = size
    if not isinstance(width, int) or not isinstance(height, int):
        return t['error_size_not_int']
    if width <= 0 or height <= 0:
        return t['error_size_not_positive']
    valid_formats = [
        'DXT1',
        'DXT3',
        'DXT5',
        'RGBA8888',
        'ABGR8888',
        'RGB888',
        'BGR888',
        'RGB565',
        'BGR565',
        'I8',
        'IA88',
        'A8',
        'RGB888 Bluescreen',
        'BGR888 Bluescreen',
        'ARGB8888',
        'BGRA8888',
        'BGRX8888',
        'BGRX5551',
        'BGRA4444',
        'DXT1 With One Bit Alpha',
        'BGRA5551',
        'UV88',
        'UVWQ8888',
        'RGBA16161616F',
        'RGBA16161616',
        'UVLX8888'
    ]
    if format_type not in valid_formats:
        return t['error_format_invalid'].format(format=format_type, formats=', '.join(valid_formats))
    # Только специальные режимы (спрей, крит и т.д.) не требуют TF2.
    # Режимы рук теперь используют полный пайплайн декомпил→компил, как оружие.
    _no_tf2_needed = mode in SPECIAL_MODES.values()
    if not _no_tf2_needed:
        if not tf2_root_dir or not isinstance(tf2_root_dir, str):
            return t['error_tf2_required']
        if not os.path.exists(tf2_root_dir):
            return t['error_tf2_not_found'].format(path=tf2_root_dir)
        if not os.path.isdir(tf2_root_dir):
            return t['error_tf2_not_dir'].format(path=tf2_root_dir)
    return None

