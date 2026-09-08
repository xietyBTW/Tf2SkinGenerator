"""
Конфигурация системы логирования
"""

import logging
import sys
from pathlib import Path
from typing import Optional


def setup_logging(
    log_level: str = "INFO",
    log_file: Optional[Path] = None,
    console_output: bool = True
) -> logging.Logger:
    """
    Настраивает систему логирования для приложения
    
    Args:
        log_level: Уровень логирования (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Путь к файлу для записи логов (опционально)
        console_output: Выводить ли логи в консоль
        
    Returns:
        Настроенный logger
    """
    # Создаем форматтер
    formatter = logging.Formatter(
        fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Получаем корневой logger
    logger = logging.getLogger('tf2_skin_generator')
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    
    # Очищаем существующие handlers
    logger.handlers.clear()
    
    # Консольный handler
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    # Файловый handler (если указан) — с ротацией, чтобы лог не рос бесконечно
    if log_file:
        from logging.handlers import RotatingFileHandler
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file, encoding='utf-8',
            maxBytes=2_000_000, backupCount=2,
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    # Кольцо для консоли в окне: те же записи, что уходят в файл, но их можно
    # показать человеку прямо в приложении (см. src/shared/log_bridge.py).
    from src.shared.log_bridge import attach as attach_ring
    attach_ring()

    logger.propagate = False

    return logger


def set_debug(enabled: bool) -> None:
    """
    Включает или гасит уровень DEBUG на ходу.

    Нужно настройке «Режим отладки»: раньше она управляла только тем, сохранять
    ли временные папки сборки, а уровень логирования был зашит в main.py как
    INFO — то есть 147 вызовов logger.debug молчали при любом её положении.
    Перезапуск для смены уровня не нужен: логгер один и живёт весь сеанс.
    """
    logging.getLogger('tf2_skin_generator').setLevel(
        logging.DEBUG if enabled else logging.INFO)


def get_logger(name: str) -> logging.Logger:
    """
    Получает logger для модуля
    
    Args:
        name: Имя модуля (обычно __name__)
        
    Returns:
        Logger для модуля
    """
    base_logger = logging.getLogger('tf2_skin_generator')
    if not base_logger.handlers:
        base_logger.addHandler(logging.NullHandler())
        base_logger.propagate = False
    return logging.getLogger(f'tf2_skin_generator.{name}')

