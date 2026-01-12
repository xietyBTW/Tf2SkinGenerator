"""
Модуль для проверки доступности внешних зависимостей
"""

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
        dict: Словарь с ключами 'qdarkstyle' и значениями bool
    """
    return {
        'qdarkstyle': QDARKSTYLE_AVAILABLE
    }

