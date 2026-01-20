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
    
    # Файловый handler (если указан)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Получает logger для модуля
    
    Args:
        name: Имя модуля (обычно __name__)
        
    Returns:
        Logger для модуля
    """
    return logging.getLogger(f'tf2_skin_generator.{name}')

