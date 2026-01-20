"""
Сервис для работы с изображениями
"""

import os
import tempfile
from typing import Optional, Tuple
from PIL import Image
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class ImageService:
    """Сервис для работы с изображениями"""
    
    SUPPORTED_FORMATS = ['.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff', '.webp']
    
    @staticmethod
    def is_image_file(file_path: str) -> bool:
        """Проверяет, является ли файл изображением"""
        return any(file_path.lower().endswith(ext) for ext in ImageService.SUPPORTED_FORMATS)
    
    @staticmethod
    def load_image_as_pixmap(image_path: str, max_size: Tuple[int, int] = (400, 400)) -> QPixmap:
        """
        Загружает изображение как QPixmap с масштабированием
        
        Args:
            image_path: Путь к изображению
            max_size: Максимальный размер (width, height)
            
        Returns:
            QPixmap: Масштабированное изображение
        """
        pixmap = QPixmap(image_path)
        return pixmap.scaled(max_size[0], max_size[1], Qt.KeepAspectRatio, Qt.SmoothTransformation)
    
    @staticmethod
    def pil_to_qpixmap(pil_image: Image.Image, max_size: Tuple[int, int] = (400, 400)) -> QPixmap:
        """
        Конвертирует PIL Image в QPixmap
        
        Args:
            pil_image: PIL Image
            max_size: Максимальный размер
            
        Returns:
            QPixmap: Конвертированное изображение
        """
        try:
            from PIL.ImageQt import ImageQt
            qt_image = ImageQt(pil_image)
            pixmap = QPixmap.fromImage(qt_image)
            return pixmap.scaled(max_size[0], max_size[1], Qt.KeepAspectRatio, Qt.SmoothTransformation)
        except Exception as e:
            logger.warning(f"Ошибка при конвертации PIL в QPixmap: {e}, используем fallback", exc_info=True)
            # Fallback - сохраняем во временный файл
            temp_path = tempfile.mktemp(suffix='.png')
            pil_image.save(temp_path, 'PNG')
            return ImageService.load_image_as_pixmap(temp_path, max_size)
    
    @staticmethod
    def save_pil_to_temp(pil_image: Image.Image, suffix: str = '.png') -> str:
        """
        Сохраняет PIL Image во временный файл
        
        Args:
            pil_image: PIL Image
            suffix: Суффикс файла
            
        Returns:
            str: Путь к временному файлу
        """
        temp_path = tempfile.mktemp(suffix=suffix)
        pil_image.save(temp_path, suffix[1:].upper())
        return temp_path

