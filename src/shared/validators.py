"""
Валидаторы для входных данных
"""

import os
from typing import Tuple, Optional
from src.data.weapons import SPECIAL_MODES
from .constants import ValidationLimits


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


def sanitize_path(path: str, base_dir: str) -> str:
    """
    Преобразует относительный путь в абсолютный внутри base_dir.

    Защита от path traversal: результат обязан лежать строго внутри
    base_dir (сравнение через commonpath, а не префикс строки — иначе
    'C:/base_evil' проходил бы проверку для базы 'C:/base').

    Raises:
        ValueError: Если путь выходит за пределы base_dir или содержит ':'.
    """
    base_dir_abs = os.path.abspath(base_dir)
    if path.startswith('/'):
        path = path[1:]
    if ':' in path:
        raise ValueError(f"Недопустимый путь: {path}")
    full_path = os.path.abspath(os.path.join(base_dir_abs, path))
    try:
        is_inside = os.path.commonpath([full_path, base_dir_abs]) == base_dir_abs
    except ValueError:
        # Разные диски на Windows → точно за пределами базы
        is_inside = False
    if not is_inside:
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
        # Sentinel EXTRA_TEX_USE_GAME_ORIGINAL — не файл, а команда использовать
        # оригинал из игры. Пропускаем проверку существования файла.
        from src.shared.constants import EXTRA_TEX_USE_GAME_ORIGINAL
        if image_path != EXTRA_TEX_USE_GAME_ORIGINAL:
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
    # Персонажи, руки и оружия — полный pipeline через VPK + Crowbar.
    _no_tf2_needed = mode in SPECIAL_MODES.values()
    if not _no_tf2_needed:
        if not tf2_root_dir or not isinstance(tf2_root_dir, str):
            return t['error_tf2_required']
        if not os.path.exists(tf2_root_dir):
            return t['error_tf2_not_found'].format(path=tf2_root_dir)
        if not os.path.isdir(tf2_root_dir):
            return t['error_tf2_not_dir'].format(path=tf2_root_dir)
    return None
