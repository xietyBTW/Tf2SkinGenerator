"""
Модуль для проверки доступности внешних зависимостей
"""

# Проверка rembg
REMBG_AVAILABLE = False
rembg = None

try:
    import rembg
    REMBG_AVAILABLE = True
except ImportError:
    pass

# Проверка OpenCV
OPENCV_AVAILABLE = False
cv2 = None
np = None

try:
    import cv2
    import numpy as np
    OPENCV_AVAILABLE = True
except ImportError:
    pass

# Проверка qdarkstyle
QDARKSTYLE_AVAILABLE = False
qdarkstyle = None

try:
    import qdarkstyle
    QDARKSTYLE_AVAILABLE = True
except ImportError:
    pass


def check_dependencies():
    """
    Возвращает словарь с информацией о доступности зависимостей
    
    Returns:
        dict: Словарь с ключами 'rembg', 'opencv', 'qdarkstyle' и значениями bool
    """
    return {
        'rembg': REMBG_AVAILABLE,
        'opencv': OPENCV_AVAILABLE,
        'qdarkstyle': QDARKSTYLE_AVAILABLE
    }

