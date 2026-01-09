"""
Сервис для генерации UV разметки из SMD файлов
"""

import os
import re
from typing import List, Tuple, Optional
from PIL import Image, ImageDraw, ImageFont


class UVLayoutService:
    """Сервис для создания UV разметки из SMD файлов"""
    
    @staticmethod
    def parse_smd_uv_coordinates(smd_path: str) -> List[Tuple[float, float, float, float, float, float]]:
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
                    bone_id = int(parts[0])
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
        uv_coords: List[Tuple[float, float, float, float, float, float]],
        output_path: str,
        image_size: Tuple[int, int] = (1024, 1024),
        line_color: str = "red",
        line_width: int = 1,
        point_size: int = 2
    ) -> None:
        """
        Рисует UV разметку на изображении
        
        Args:
            uv_coords: Список UV координат (u, v, x, y, z, nx, ny, nz)
            output_path: Путь для сохранения изображения
            image_size: Размер выходного изображения
            line_color: Цвет линий
            line_width: Толщина линий
            point_size: Размер точек вершин
        """
        if not uv_coords:
            raise ValueError("Нет UV координат для отрисовки")
        
        # Создаем изображение
        img = Image.new('RGB', image_size, color='white')
        draw = ImageDraw.Draw(img)
        
        # Конвертируем UV координаты в пиксели
        # UV координаты обычно в диапазоне [0, 1], но могут быть и вне этого диапазона
        # Находим минимальные и максимальные значения для нормализации
        u_values = [coord[0] for coord in uv_coords]
        v_values = [coord[1] for coord in uv_coords]
        
        u_min, u_max = min(u_values), max(u_values)
        v_min, v_max = min(v_values), max(v_values)
        
        # Добавляем небольшой отступ
        u_range = u_max - u_min if u_max != u_min else 1.0
        v_range = v_max - v_min if v_max != v_min else 1.0
        
        padding = 0.05  # 5% отступ
        u_min -= u_range * padding
        u_max += u_range * padding
        v_min -= v_range * padding
        v_max += v_range * padding
        
        u_range = u_max - u_min if u_max != u_min else 1.0
        v_range = v_max - v_min if v_max != v_min else 1.0
        
        # Функция для конвертации UV в пиксели
        def uv_to_pixel(u: float, v: float) -> Tuple[int, int]:
            # Инвертируем V координату (в UV координатах V растет вниз, в изображениях - вверх)
            normalized_u = (u - u_min) / u_range
            normalized_v = (v - v_min) / v_range
            
            x = int(normalized_u * image_size[0])
            y = int((1 - normalized_v) * image_size[1])  # Инвертируем Y
            
            # Ограничиваем координаты границами изображения
            x = max(0, min(image_size[0] - 1, x))
            y = max(0, min(image_size[1] - 1, y))
            
            return x, y
        
        # Рисуем треугольники (по 3 вершины)
        for i in range(0, len(uv_coords) - 2, 3):
            if i + 2 < len(uv_coords):
                # Получаем координаты трех вершин треугольника
                u1, v1 = uv_coords[i][0], uv_coords[i][1]
                u2, v2 = uv_coords[i + 1][0], uv_coords[i + 1][1]
                u3, v3 = uv_coords[i + 2][0], uv_coords[i + 2][1]
                
                # Конвертируем в пиксели
                p1 = uv_to_pixel(u1, v1)
                p2 = uv_to_pixel(u2, v2)
                p3 = uv_to_pixel(u3, v3)
                
                # Рисуем треугольник (три линии)
                draw.line([p1, p2], fill=line_color, width=line_width)
                draw.line([p2, p3], fill=line_color, width=line_width)
                draw.line([p3, p1], fill=line_color, width=line_width)
                
                # Рисуем точки вершин
                if point_size > 0:
                    for point in [p1, p2, p3]:
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
            print(f"Начинаем генерацию UV разметки из SMD файла: {smd_path}")
            uv_coords = UVLayoutService.parse_smd_uv_coordinates(smd_path)
            print(f"Найдено UV координат: {len(uv_coords)}")
            if not uv_coords:
                print(f"Предупреждение: Не найдено UV координат в SMD файле: {smd_path}")
                return False
            
            print(f"Рисуем UV разметку на изображении размером {image_size}")
            UVLayoutService.draw_uv_layout(uv_coords, output_path, image_size)
            print(f"UV разметка успешно создана: {output_path}")
            return True
        except Exception as e:
            import traceback
            print(f"Ошибка при создании UV разметки: {e}")
            print(f"Трассировка: {traceback.format_exc()}")
            return False

