"""
Сервис для генерации UV разметки из SMD файлов
"""

import os
import re
from typing import List, Tuple
from PIL import Image, ImageDraw
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class UVLayoutService:
    """Сервис для создания UV разметки из SMD файлов"""
    
    @staticmethod
    def parse_smd_uv_coordinates(smd_path: str) -> List[Tuple[float, ...]]:
        """
        Парсит SMD файл и извлекает UV координаты и позиции вершин
        
        Args:
            smd_path: Путь к SMD файлу
            
        Returns:
            Список кортежей (u, v, x, y, z, nx, ny, nz) для каждой вершины
            Формат строки: boneId x y z nx ny nz u v ...
        """
        if not os.path.exists(smd_path):
            raise FileNotFoundError(f"SMD файл не найден: {smd_path}")
        
        uv_coords = []
        
        with open(smd_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Ищем секцию triangles
        triangles_match = re.search(r'triangles\s*\n(.*?)\nend', content, re.DOTALL)
        if not triangles_match:
            return uv_coords
        
        triangles_content = triangles_match.group(1)
        lines = triangles_content.split('\n')
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # Пропускаем пустые строки и комментарии
            if not line or line.startswith('//'):
                i += 1
                continue
            
            # Проверяем, является ли строка строкой вершины
            # Строка вершины начинается с числа (boneId) или отрицательного числа
            is_vertex_line = False
            if line and (line[0].isdigit() or (line.startswith('-') and len(line) > 1 and line[1].isdigit())):
                parts = line.split()
                # Строка вершины должна содержать минимум 9 чисел (boneId x y z nx ny nz u v ...)
                if len(parts) >= 9:
                    try:
                        # Пробуем распарсить как число
                        int(parts[0])
                        float(parts[1])
                        is_vertex_line = True
                    except (ValueError, IndexError):
                        pass
            
            if not is_vertex_line:
                # Это название материала или другая строка - пропускаем
                i += 1
                continue
            
            # Парсим строку вершины
            # Формат: boneId x y z nx ny nz u v r g b
            parts = line.split()
            if len(parts) >= 9:
                try:
                    _bone_id = int(parts[0])  # валидируем, что строка вершины начинается с bone id
                    x = float(parts[1])
                    y = float(parts[2])
                    z = float(parts[3])
                    nx = float(parts[4])
                    ny = float(parts[5])
                    nz = float(parts[6])
                    u = float(parts[7])
                    v = float(parts[8])
                    
                    uv_coords.append((u, v, x, y, z, nx, ny, nz))
                except (ValueError, IndexError):
                    # Пропускаем некорректные строки
                    pass
            
            i += 1
        
        return uv_coords
    
    @staticmethod
    def draw_uv_layout(
        uv_coords: List[Tuple[float, ...]],
        output_path: str,
        image_size: Tuple[int, int] = (1024, 1024),
        line_color: str = "red",
        line_width: int = 1,
        point_size: int = 0
    ) -> None:
        """
        Рисует UV разметку на изображении
        
        Args:
            uv_coords: Список UV координат (u, v, x, y, z, nx, ny, nz)
            output_path: Путь для сохранения изображения
            image_size: Размер выходного изображения
            line_color: Цвет линий
            line_width: Толщина линий
            point_size: Радиус точек на вершинах. По умолчанию 0 — только линии
                        (точки мешают при рисовании текстуры по разметке).
        """
        if not uv_coords:
            raise ValueError("Нет UV координат для отрисовки")

        # Создаем изображение
        w, h = image_size
        img = Image.new('RGB', image_size, color='white')
        draw = ImageDraw.Draw(img)

        # UV → пиксель в ТЕКСТУРНОМ пространстве: всё поле [0,1]² соответствует
        # всей картинке — ровно так же, как игра семплит текстуру. НИКАКОЙ
        # нормализации по bounding box и НИКАКИХ отступов: иначе разметка
        # масштабируется/смещается и не ложится на текстуру (это и был баг).
        # V инвертируем: в UV V растёт вверх, в изображении Y — вниз.
        # UV вне [0,1] (тайлинг) прижимаем к границам кадра.
        def uv_to_pixel(u: float, v: float) -> Tuple[int, int]:
            x = int(round(u * w))
            y = int(round((1.0 - v) * h))
            x = max(0, min(w - 1, x))
            y = max(0, min(h - 1, y))
            return x, y

        # Рисуем треугольники (по 3 вершины подряд).
        for i in range(0, len(uv_coords) - 2, 3):
            p1 = uv_to_pixel(uv_coords[i][0],     uv_coords[i][1])
            p2 = uv_to_pixel(uv_coords[i + 1][0], uv_coords[i + 1][1])
            p3 = uv_to_pixel(uv_coords[i + 2][0], uv_coords[i + 2][1])

            # Рисуем треугольник (три линии)
            draw.line([p1, p2], fill=line_color, width=line_width)
            draw.line([p2, p3], fill=line_color, width=line_width)
            draw.line([p3, p1], fill=line_color, width=line_width)

            # Рисуем точки вершин
            if point_size > 0:
                for point in (p1, p2, p3):
                    draw.ellipse(
                        [point[0] - point_size, point[1] - point_size,
                         point[0] + point_size, point[1] + point_size],
                        fill=line_color
                    )
        
        # Сохраняем изображение
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        img.save(output_path)
    
    @staticmethod
    def generate_uv_layout_from_smd(
        smd_path: str,
        output_path: str,
        image_size: Tuple[int, int] = (1024, 1024)
    ) -> bool:
        """
        Генерирует UV разметку из SMD файла
        
        Args:
            smd_path: Путь к SMD файлу
            output_path: Путь для сохранения изображения UV разметки
            image_size: Размер выходного изображения
            
        Returns:
            True если успешно, False если ошибка
        """
        try:
            logger.info(f"Начинаем генерацию UV разметки из SMD файла: {smd_path}")
            uv_coords = UVLayoutService.parse_smd_uv_coordinates(smd_path)
            logger.debug(f"Найдено UV координат: {len(uv_coords)}")
            if not uv_coords:
                logger.warning(f"Не найдено UV координат в SMD файле: {smd_path}")
                return False
            
            logger.debug(f"Рисуем UV разметку на изображении размером {image_size}")
            UVLayoutService.draw_uv_layout(uv_coords, output_path, image_size)
            logger.info(f"UV разметка успешно создана: {output_path}")
            return True
        except Exception as e:
            logger.error(f"Ошибка при создании UV разметки: {e}", exc_info=True)
            return False

