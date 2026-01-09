"""
Сервис для работы с SMD файлами и замены моделей
"""

import os
import re
from typing import Optional, Tuple


class SMDService:
    """Сервис для работы с SMD файлами"""
    
    @staticmethod
    def replace_model_sections(
        user_smd_path: str,
        original_smd_path: str,
        output_smd_path: Optional[str] = None
    ) -> str:
        """
        Заменяет секции nodes и названия материалов в пользовательском SMD файле
        на соответствующие из исходного SMD файла игры
        
        Args:
            user_smd_path: Путь к SMD файлу пользователя (с его данными треугольников)
            original_smd_path: Путь к исходному SMD файлу из игры (с nodes и названиями материалов)
            output_smd_path: Путь для сохранения результата (если None, перезаписывает user_smd_path)
            
        Returns:
            Путь к обработанному файлу
            
        Raises:
            FileNotFoundError: Если один из файлов не найден
            ValueError: Если файлы не являются валидными SMD
        """
        if not os.path.exists(user_smd_path):
            raise FileNotFoundError(f"Пользовательский SMD файл не найден: {user_smd_path}")
        
        if not os.path.exists(original_smd_path):
            raise FileNotFoundError(f"Исходный SMD файл не найден: {original_smd_path}")
        
        # Читаем пользовательский файл
        with open(user_smd_path, 'r', encoding='utf-8') as f:
            user_content = f.read()
        
        # Читаем исходный файл
        with open(original_smd_path, 'r', encoding='utf-8') as f:
            original_content = f.read()
        
        # Извлекаем секции из обоих файлов
        user_parts = SMDService._parse_smd_file(user_content)
        original_parts = SMDService._parse_smd_file(original_content)
        
        if not user_parts or not original_parts:
            raise ValueError("Не удалось распарсить один из SMD файлов")
        
        # Формируем новый файл:
        # - version из оригинального (или пользовательского, если нет)
        # - nodes из исходного
        # - skeleton из исходного (СКЕЛЕТ БЕРЕМ ИЗ ОРИГИНАЛЬНОГО)
        # - triangles: названия материалов из исходного, данные треугольников из пользовательского
        
        new_content_parts = []
        
        # Version (берем из оригинального, если есть, иначе из пользовательского)
        if original_parts.get('version'):
            new_content_parts.append(original_parts['version'])
        elif user_parts.get('version'):
            new_content_parts.append(user_parts['version'])
        
        # Nodes из исходного файла
        if original_parts.get('nodes'):
            new_content_parts.append(original_parts['nodes'])
        else:
            # Если в исходном нет nodes, берем из пользовательского
            if user_parts.get('nodes'):
                new_content_parts.append(user_parts['nodes'])
        
        # Skeleton ВСЕГДА из исходного файла (как просил пользователь)
        if original_parts.get('skeleton'):
            new_content_parts.append(original_parts['skeleton'])
        else:
            # Если в исходном нет skeleton, берем из пользовательского как fallback
            if user_parts.get('skeleton'):
                new_content_parts.append(user_parts['skeleton'])
        
        # Triangles: названия материалов из исходного, данные из пользовательского
        triangles_section = SMDService._merge_triangles(
            user_parts.get('triangles_data', []),
            original_parts.get('material_names', [])
        )
        if triangles_section:
            new_content_parts.append(triangles_section)
        
        # Собираем финальный файл
        new_content = '\n'.join(new_content_parts)
        
        # Определяем путь для сохранения
        if output_smd_path is None:
            output_smd_path = user_smd_path
        
        # Сохраняем результат
        with open(output_smd_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        return output_smd_path
    
    @staticmethod
    def _parse_smd_file(content: str) -> dict:
        """
        Парсит SMD файл и извлекает секции
        
        Returns:
            Словарь с секциями: version, nodes, skeleton, triangles_data, material_names
        """
        result = {
            'version': None,
            'nodes': None,
            'skeleton': None,
            'triangles_data': [],  # Список кортежей (material_name, lines)
            'material_names': []   # Список названий материалов для замены
        }
        
        lines = content.split('\n')
        i = 0
        
        # Version
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith('version'):
                # Сохраняем строку version и все строки до следующей секции
                version_lines = [line]
                i += 1
                while i < len(lines) and not lines[i].strip().startswith(('nodes', 'skeleton', 'triangles')):
                    version_lines.append(lines[i])
                    i += 1
                result['version'] = '\n'.join(version_lines)
                continue
            elif line.startswith('nodes'):
                break
            i += 1
        
        # Nodes
        if i < len(lines) and lines[i].strip().startswith('nodes'):
            nodes_start = i
            i += 1
            while i < len(lines):
                if lines[i].strip() == 'end':
                    result['nodes'] = '\n'.join(lines[nodes_start:i+1])
                    i += 1
                    break
                i += 1
        
        # Skeleton
        while i < len(lines):
            if lines[i].strip().startswith('skeleton'):
                skeleton_start = i
                i += 1
                while i < len(lines):
                    if lines[i].strip() == 'end':
                        result['skeleton'] = '\n'.join(lines[skeleton_start:i+1])
                        i += 1
                        break
                    i += 1
                break
            i += 1
        
        # Triangles
        while i < len(lines):
            if lines[i].strip().startswith('triangles'):
                i += 1
                current_material = None
                current_triangles = []
                
                while i < len(lines):
                    line = lines[i].strip()
                    
                    # Пустая строка - пропускаем
                    if not line:
                        i += 1
                        continue
                    
                    # Проверяем, является ли строка данными треугольника
                    # Данные треугольника начинаются с числа (может быть отрицательным)
                    # Формат: "0 0.581882 3.03838134 ..." или "0 -4.065059 0.399341 ..."
                    is_triangle_data = False
                    if line:
                        # Разделяем строку по пробелам и проверяем первый элемент
                        parts = line.split()
                        if len(parts) > 0:
                            first_part = parts[0]
                            # Проверяем, что первый элемент - это число (может быть отрицательным)
                            try:
                                float(first_part)  # Если это число, значит это данные треугольника
                                is_triangle_data = True
                            except ValueError:
                                pass  # Не число, значит это название материала
                    
                    if is_triangle_data:
                        if current_material is not None:
                            current_triangles.append(lines[i])  # Сохраняем с оригинальным форматированием
                    else:
                        # Это название материала
                        # Сохраняем предыдущий материал
                        if current_material is not None and current_triangles:
                            result['triangles_data'].append((current_material, current_triangles))
                            result['material_names'].append(current_material)
                        
                        current_material = line  # Название материала (может быть любым текстом)
                        current_triangles = []
                    
                    i += 1
                
                # Сохраняем последний материал
                if current_material is not None and current_triangles:
                    result['triangles_data'].append((current_material, current_triangles))
                    result['material_names'].append(current_material)
                
                break
            i += 1
        
        return result
    
    @staticmethod
    def _merge_triangles(user_triangles_data: list, original_material_names: list) -> str:
        """
        Объединяет данные треугольников из пользовательского файла
        с названиями материалов из исходного файла
        
        Args:
            user_triangles_data: Список кортежей (material_name, lines) из пользовательского файла
            original_material_names: Список названий материалов из исходного файла
            
        Returns:
            Строка с секцией triangles
        """
        result_lines = ['triangles']
        
        if not user_triangles_data:
            return '\n'.join(result_lines)
        
        # Если есть оригинальные названия материалов, используем их
        # Иначе используем названия из пользовательского файла
        
        if original_material_names:
            # Используем названия из оригинального файла
            # Создаем список названий материалов для каждой группы треугольников
            # Если групп больше чем названий, повторяем последнее название
            materials_to_use = []
            for i in range(len(user_triangles_data)):
                if i < len(original_material_names):
                    materials_to_use.append(original_material_names[i])
                else:
                    # Используем последнее название, если групп больше
                    materials_to_use.append(original_material_names[-1])
        else:
            # Используем названия из пользовательского файла
            materials_to_use = [name for name, _ in user_triangles_data]
        
        # Проходим по всем треугольникам пользователя и заменяем названия
        for idx, (material_name, triangle_lines) in enumerate(user_triangles_data):
            # Используем название материала из оригинального файла
            current_material = materials_to_use[idx] if idx < len(materials_to_use) else material_name
            
            # Добавляем название материала
            result_lines.append(current_material)
            
            # Добавляем строки треугольников
            result_lines.extend(triangle_lines)
        
        return '\n'.join(result_lines)
    
    @staticmethod
    def find_reference_smd(decompile_dir: str, weapon_key: str) -> Optional[str]:
        """
        Находит reference SMD файл в декомпилированной директории
        
        Ищет файлы в следующем порядке приоритета:
        1. {weapon_key}_reference.smd
        2. {weapon_key}.smd
        3. Любой файл с 'reference' в названии, который содержит weapon_key
        4. Любой .smd файл, который содержит weapon_key в имени (не physics, не animations)
        
        Важно: функция НЕ возвращает случайные файлы, которые не соответствуют weapon_key.
        Это предотвращает загрузку неправильного оружия (например, bat вместо scattergun).
        
        Args:
            decompile_dir: Директория с декомпилированными файлами
            weapon_key: Ключ оружия (например, c_scattergun)
            
        Returns:
            Путь к найденному SMD файлу или None, если файл с правильным weapon_key не найден
        """
        if not os.path.exists(decompile_dir):
            return None
        
        # Варианты имен файлов для поиска (в порядке приоритета)
        possible_names = [
            f"{weapon_key}_reference.smd",
            f"{weapon_key}.smd",
        ]
        
        # Сначала ищем по конкретным именам
        for name in possible_names:
            file_path = os.path.join(decompile_dir, name)
            if os.path.exists(file_path):
                return file_path
        
        # Если не нашли, ищем файл с reference в названии, который содержит weapon_key
        for file_name in os.listdir(decompile_dir):
            if (file_name.endswith('.smd') and 
                'reference' in file_name.lower() and
                weapon_key.lower() in file_name.lower()):
                return os.path.join(decompile_dir, file_name)
        
        # В крайнем случае, ищем любой .smd файл, который содержит weapon_key в имени
        # (не physics, не animations)
        for file_name in os.listdir(decompile_dir):
            if (file_name.endswith('.smd') and 
                'physics' not in file_name.lower() and 
                'anim' not in file_name.lower() and
                'anims' not in file_name.lower() and
                weapon_key.lower() in file_name.lower()):
                return os.path.join(decompile_dir, file_name)
        
        return None

