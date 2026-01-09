"""
Сервис для работы с изображениями
"""

import os
import tempfile
from typing import Optional, Tuple
from PIL import Image
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt

# Импорт проверки зависимостей
from src.utils.dependencies import REMBG_AVAILABLE, rembg, OPENCV_AVAILABLE, cv2, np


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
    def remove_background(image_path: str) -> Optional[Image.Image]:
        """
        Удаляет задний фон с изображения
        
        Args:
            image_path: Путь к изображению
            
        Returns:
            PIL Image с удаленным фоном или None при ошибке
        """
        if not os.path.exists(image_path):
            print(f"Файл изображения не найден: {image_path}")
            return None
        
        try:
            if REMBG_AVAILABLE:
                return ImageService._remove_background_rembg(image_path)
            elif OPENCV_AVAILABLE:
                return ImageService._remove_background_opencv(image_path)
            else:
                print("Нет доступных методов удаления фона. Установите rembg или opencv-python")
                return None
        except Exception as e:
            print(f"Ошибка при удалении фона: {e}")
            return None
    
    @staticmethod
    def _remove_background_rembg(image_path: str) -> Optional[Image.Image]:
        """Удаление фона с помощью rembg"""
        try:
            with open(image_path, 'rb') as input_file:
                input_data = input_file.read()
            
            output_data = rembg.remove(input_data)
            
            # Конвертируем в PIL Image
            from io import BytesIO
            return Image.open(BytesIO(output_data))
        except Exception as e:
            print(f"Ошибка при удалении фона (rembg): {e}")
            return None
    
    @staticmethod
    def _remove_background_opencv(image_path: str) -> Optional[Image.Image]:
        """Удаление фона с помощью OpenCV"""
        try:
            from src.utils.background_removal import remove_background_from_image
            return remove_background_from_image(image_path)
        except Exception as e:
            print(f"Ошибка при удалении фона (OpenCV): {e}")
            return None
    
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
            print(f"Ошибка при конвертации PIL в QPixmap: {e}")
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

