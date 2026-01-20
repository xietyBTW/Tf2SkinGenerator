import os
import re
from typing import Optional, Tuple


class SMDService:
    
    @staticmethod
    def replace_model_sections(
        user_smd_path: str,
        original_smd_path: str,
        output_smd_path: Optional[str] = None
    ) -> str:
        """
        Заменяет секции nodes и названия материалов в пользовательском SMD файле
        на соответствующие из исходного SMD файла игры.
        
        Нужно потому что юзерская модель может иметь другие nodes (костяк модели) и названия материалов,
        а нам нужны оригинальные из игры, иначе модель не скомпилируется или текстуры не загрузятся.
        Это костыль, но так работает - берем геометрию от юзера, костяк от оригинала.
        
        Args:
            user_smd_path: Путь к SMD файлу пользователя (с его данными треугольников - это то, что юзер хочет заменить)
            original_smd_path: Путь к исходному SMD файлу из игры (с nodes и названиями материалов - это эталон)
            output_smd_path: Путь для сохранения результата (если None, перезаписывает user_smd_path)
            
        Returns:
            Путь к обработанному файлу
            
        Raises:
            FileNotFoundError: Если один из файлов не найден
            ValueError: Если файлы не являются валидными SMD (не удалось распарсить)
        """
        if not os.path.exists(user_smd_path):
            raise FileNotFoundError(f"Пользовательский SMD файл не найден: {user_smd_path}")
        
        if not os.path.exists(original_smd_path):
            raise FileNotFoundError(f"Исходный SMD файл не найден: {original_smd_path}")
        
        with open(user_smd_path, 'r', encoding='utf-8') as f:
            user_content = f.read()
        
        with open(original_smd_path, 'r', encoding='utf-8') as f:
            original_content = f.read()
        
        # Парсим оба файла (разбиваем на секции: version, nodes, skeleton, triangles)
        user_parts = SMDService._parse_smd_file(user_content)
        original_parts = SMDService._parse_smd_file(original_content)
        
        if not user_parts or not original_parts:
            raise ValueError("Не удалось распарсить один из SMD файлов")
        
        new_content_parts = []
        
        # Берем version из оригинала, если есть, иначе из юзерского (обычно одинаковые, но на всякий случай)
        if original_parts.get('version'):
            new_content_parts.append(original_parts['version'])
        elif user_parts.get('version'):
            new_content_parts.append(user_parts['version'])
        
        # Берем nodes из оригинала (это костяк модели, должен быть из игры)
        if original_parts.get('nodes'):
            new_content_parts.append(original_parts['nodes'])
        else:
            # Fallback на юзерский, если в оригинале нет (маловероятно, но на всякий случай)
            if user_parts.get('nodes'):
                new_content_parts.append(user_parts['nodes'])
        
        # Берем skeleton из оригинала (это тоже костяк, должен быть из игры)
        if original_parts.get('skeleton'):
            new_content_parts.append(original_parts['skeleton'])
        else:
            # Fallback на юзерский, если в оригинале нет
            if user_parts.get('skeleton'):
                new_content_parts.append(user_parts['skeleton'])
        
        # Объединяем треугольники из юзерского файла с названиями материалов из оригинала
        # (костыль, но так работает - берем геометрию от юзера, названия материалов от оригинала)
        triangles_section = SMDService._merge_triangles(
            user_parts.get('triangles_data', []),
            original_parts.get('material_names', [])
        )
        if triangles_section:
            new_content_parts.append(triangles_section)
        
        new_content = '\n'.join(new_content_parts)
        
        if output_smd_path is None:
            output_smd_path = user_smd_path
        
        with open(output_smd_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        
        return output_smd_path
    
    @staticmethod
    def _parse_smd_file(content: str) -> dict:
        result = {
            'version': None,
            'nodes': None,
            'skeleton': None,
            'triangles_data': [],
            'material_names': []
        }
        
        lines = content.split('\n')
        i = 0
        
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith('version'):
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
        
        if i < len(lines) and lines[i].strip().startswith('nodes'):
            nodes_start = i
            i += 1
            while i < len(lines):
                if lines[i].strip() == 'end':
                    result['nodes'] = '\n'.join(lines[nodes_start:i+1])
                    i += 1
                    break
                i += 1
        
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
        
        while i < len(lines):
            if lines[i].strip().startswith('triangles'):
                i += 1
                current_material = None
                current_triangles = []
                
                while i < len(lines):
                    line = lines[i].strip()
                    
                    if not line:
                        i += 1
                        continue
                    
                    is_triangle_data = False
                    if line:
                        parts = line.split()
                        if len(parts) > 0:
                            first_part = parts[0]
                            try:
                                float(first_part)
                                is_triangle_data = True
                            except ValueError:
                                pass
                    
                    if is_triangle_data:
                        if current_material is not None:
                            current_triangles.append(lines[i])
                    else:
                        if current_material is not None and current_triangles:
                            result['triangles_data'].append((current_material, current_triangles))
                            result['material_names'].append(current_material)
                        
                        current_material = line
                        current_triangles = []
                    
                    i += 1
                
                if current_material is not None and current_triangles:
                    result['triangles_data'].append((current_material, current_triangles))
                    result['material_names'].append(current_material)
                
                break
            i += 1
        
        return result
    
    @staticmethod
    def _merge_triangles(user_triangles_data: list, original_material_names: list) -> str:
        # Объединяем треугольники из юзерского файла с названиями материалов из оригинала
        result_lines = ['triangles']
        
        if not user_triangles_data:
            return '\n'.join(result_lines)
        
        # Если есть названия материалов из оригинала - используем их (приоритет оригиналу)
        # Если материалов больше чем в оригинале - повторяем последний (костыль, но работает)
        if original_material_names:
            materials_to_use = []
            for i in range(len(user_triangles_data)):
                if i < len(original_material_names):
                    materials_to_use.append(original_material_names[i])
                else:
                    materials_to_use.append(original_material_names[-1])  # Повторяем последний, если не хватает
        else:
            # Если нет оригинальных названий - используем юзерские (fallback)
            materials_to_use = [name for name, _ in user_triangles_data]
        
        # Собираем секцию triangles: название материала, потом треугольники
        for idx, (material_name, triangle_lines) in enumerate(user_triangles_data):
            current_material = materials_to_use[idx] if idx < len(materials_to_use) else material_name
            
            result_lines.append(current_material)
            result_lines.extend(triangle_lines)
        
        return '\n'.join(result_lines)
    
    @staticmethod
    def find_reference_smd(decompile_dir: str, weapon_key: str) -> Optional[str]:
        # Ищем reference SMD файл (это оригинальная модель из игры, нужна для замены nodes и материалов)
        if not os.path.exists(decompile_dir):
            return None
        
        # Пробуем стандартные имена (Crowbar обычно создает такие)
        possible_names = [
            f"{weapon_key}_reference.smd",
            f"{weapon_key}.smd",
        ]
        
        for name in possible_names:
            file_path = os.path.join(decompile_dir, name)
            if os.path.exists(file_path):
                return file_path
        
        # Если не нашли по стандартному имени - ищем любой файл с "reference" в названии
        for file_name in os.listdir(decompile_dir):
            if (file_name.endswith('.smd') and 
                'reference' in file_name.lower() and
                weapon_key.lower() in file_name.lower()):
                return os.path.join(decompile_dir, file_name)
        
        # Последний шанс - ищем любой SMD файл с именем оружия, но не physics и не anim
        # (потому что physics и anim файлы - это не модели, а вспомогательные данные - мусор)
        for file_name in os.listdir(decompile_dir):
            if (file_name.endswith('.smd') and 
                'physics' not in file_name.lower() and 
                'anim' not in file_name.lower() and
                'anims' not in file_name.lower() and
                weapon_key.lower() in file_name.lower()):
                return os.path.join(decompile_dir, file_name)
        
        return None

