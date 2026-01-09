#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Современные методы удаления заднего фона с использованием OpenCV
"""

from PIL import Image
import numpy as np

# Импорт OpenCV с обработкой ошибки
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    print("ВНИМАНИЕ: opencv-python не установлен. Установите его командой: pip install opencv-python")
    print("Функции удаления фона будут недоступны.")

def remove_background_grabcut(image_array):
    """
    Удаление фона с использованием алгоритма GrabCut от OpenCV
    Возвращает PIL Image с прозрачным фоном
    """
    if not CV2_AVAILABLE:
        print("OpenCV не доступен. Установите opencv-python: pip install opencv-python")
        return None
    try:
        # Конвертируем PIL в OpenCV формат
        if len(image_array.shape) == 3 and image_array.shape[2] == 4:
            # Убираем альфа-канал для обработки
            cv_image = cv2.cvtColor(image_array[:, :, :3], cv2.COLOR_RGBA2BGR)
        else:
            cv_image = cv2.cvtColor(image_array, cv2.COLOR_RGB2BGR)
        
        height, width = cv_image.shape[:2]
        
        # Создаем маску
        mask = np.zeros((height, width), np.uint8)
        
        # Определяем прямоугольник для инициализации (оставляем небольшие отступы)
        rect = (10, 10, width-20, height-20)
        
        # Модели фона и переднего плана
        bgd_model = np.zeros((1, 65), np.float64)
        fgd_model = np.zeros((1, 65), np.float64)
        
        # Применяем GrabCut
        cv2.grabCut(cv_image, mask, rect, bgd_model, fgd_model, 5, cv2.GC_INIT_WITH_RECT)
        
        # Создаем финальную маску
        mask2 = np.where((mask == 2) | (mask == 0), 0, 1).astype('uint8')
        
        # Применяем маску к изображению
        result = image_array.copy()
        result[:, :, 3] = mask2 * 255
        
        return Image.fromarray(result, 'RGBA')
        
    except Exception as e:
        print(f"Ошибка при удалении фона (GrabCut): {e}")
        return None

def remove_background_color_range(image_array, lower_color=(200, 200, 200), upper_color=(255, 255, 255)):
    """
    Удаление фона на основе диапазона цветов
    """
    if not CV2_AVAILABLE:
        print("OpenCV не доступен. Установите opencv-python: pip install opencv-python")
        return None
    try:
        # Конвертируем в HSV для лучшего выделения цветов
        hsv = cv2.cvtColor(image_array[:, :, :3], cv2.COLOR_RGB2HSV)
        
        # Создаем маску для указанного диапазона цветов
        lower = np.array([0, 0, 200])  # Нижний порог для светлых цветов
        upper = np.array([180, 30, 255])  # Верхний порог
        
        mask = cv2.inRange(hsv, lower, upper)
        
        # Инвертируем маску (фон становится 0, объект 255)
        mask = cv2.bitwise_not(mask)
        
        # Применяем морфологические операции для очистки маски
        kernel = np.ones((3,3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        
        # Применяем размытие для сглаживания краев
        mask = cv2.GaussianBlur(mask, (5, 5), 0)
        
        # Создаем результат
        result = image_array.copy()
        result[:, :, 3] = mask
        
        return Image.fromarray(result, 'RGBA')
        
    except Exception as e:
        print(f"Ошибка при удалении фона (color range): {e}")
        return None

def remove_background_adaptive(image_array):
    """
    Адаптивное удаление фона с использованием нескольких методов
    """
    try:
        # Пробуем GrabCut
        result = remove_background_grabcut(image_array)
        if result is not None:
            return result
        
        # Если GrabCut не сработал, пробуем цветовой метод
        result = remove_background_color_range(image_array)
        if result is not None:
            return result
        
        # Последний резерв - простое удаление светлого фона
        return remove_background_simple_fallback(image_array)
        
    except Exception as e:
        print(f"Ошибка при адаптивном удалении фона: {e}")
        return None

def remove_background_simple_fallback(image_array):
    """
    Простое удаление светлого фона как резервный метод
    """
    if not CV2_AVAILABLE:
        print("OpenCV не доступен. Установите opencv-python: pip install opencv-python")
        return None
    try:
        # Создаем маску для светлых пикселей
        gray = cv2.cvtColor(image_array[:, :, :3], cv2.COLOR_RGB2GRAY)
        _, mask = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY)
        
        # Инвертируем маску
        mask = cv2.bitwise_not(mask)
        
        # Применяем размытие
        mask = cv2.GaussianBlur(mask, (3, 3), 0)
        
        # Создаем результат
        result = image_array.copy()
        result[:, :, 3] = mask
        
        return Image.fromarray(result, 'RGBA')
        
    except Exception as e:
        print(f"Ошибка при простом удалении фона: {e}")
        return None

# Основная функция для удаления фона
def remove_background_from_image(image_path):
    """
    Основная функция для удаления фона с изображения
    Возвращает PIL Image с прозрачным фоном
    """
    try:
        # Загружаем изображение
        img = Image.open(image_path)
        
        # Конвертируем в RGBA если нужно
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
        
        # Получаем массив пикселей
        image_array = np.array(img)
        
        # Используем адаптивный метод
        result = remove_background_adaptive(image_array)
        
        return result
        
    except Exception as e:
        print(f"Ошибка при загрузке изображения: {e}")
        return None
