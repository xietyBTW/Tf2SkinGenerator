import os
import re
from typing import Tuple

from src.data.weapons import SPECIAL_MODES


class VMTService:
    """Сервис для работы с VMT файлами (материалы Source Engine, хуйня с путями и шаблонами)"""
    
    @staticmethod
    def cdmaterials_path_to_materials_path(cdmaterials_path: str) -> Tuple[str, str]:
        """
        Конвертирует путь из $cdmaterials в путь для материалов и имя файла.
        
        В QC файлах пути могут быть с обратными слешами и без префикса materials/,
        а в VPK нужны прямые слеши и префикс materials/. Это костыль, но так работает Source Engine.
        
        Args:
            cdmaterials_path: Путь из $cdmaterials (например, "vgui\\replay\\thumbnails\\models\\workshop_partner\\weapons\\c_models\\"
                             или "vgui\\replay\\thumbnails\\models\\workshop_partner\\weapons\\v_machete")
        
        Returns:
            Tuple[materials_path, filename_prefix]
            materials_path: Путь для материалов (например, "materials/vgui/replay/thumbnails/models/workshop_partner/weapons/c_models")
            filename_prefix: Префикс имени файла (часть пути после weapons/, например "c_models" или "v_machete")
        """
        # Нормализуем путь (заменяем обратные слеши на прямые, убираем пробелы - QC может использовать оба формата)
        normalized = cdmaterials_path.replace('\\', '/').strip().rstrip('/')
        
        # Убираем начальный "materials/" если есть (на всякий случай, обычно его нет в QC)
        if normalized.startswith('materials/'):
            normalized = normalized[len('materials/'):]
        
        # Добавляем "materials/" в начало (нужно для структуры VPK)
        materials_path = f"materials/{normalized}"
        
        # Вытаскиваем последнюю часть пути для имени файла (может быть папка или имя оружия)
        path_parts = normalized.split('/')
        if path_parts:
            filename_prefix = path_parts[-1] if path_parts[-1] else path_parts[-2] if len(path_parts) > 1 else ""
        else:
            filename_prefix = ""
        
        return materials_path, filename_prefix
    
    @staticmethod
    def get_weapon_relpaths(mode: str) -> Tuple[str, str, str]:
        """
        Возвращает относительные пути для конкретного оружия (без basepath).
        
        Для спец режимов (critHIT) - простая структура в effects/.
        Для обычного оружия - используем VGUI структуру (костыль, но так работает в TF2).
        
        Args:
            mode: Режим оружия
            
        Returns:
            Tuple[rel_path, vmt_filename, vtf_filename]
        """
        if mode in SPECIAL_MODES.values():
            if mode == "critHIT":
                rel_path = os.path.join("materials", "effects")
                vmt_filename = "crit.vmt"
                vtf_filename = "crit.vtf"
            else:
                # Для других специальных режимов (если будут добавлены новые)
                rel_path = os.path.join("materials", "effects")
                vmt_filename = f"{mode}.vmt"
                vtf_filename = f"{mode}.vtf"
        else:
            # Для обычного оружия - всегда используем VGUI структуру (костыль, но так работает в TF2)
            weapon_key = mode.split('_', 1)[1] if '_' in mode else mode
            
            # Определяем путь в зависимости от типа оружия (v_ или c_)
            # v_ - viewmodel (оружие в руках), c_ - worldmodel (оружие на земле/в инвентаре)
            if weapon_key.startswith('v_'):
                # Для v_ оружия: materials/vgui/replay/thumbnails/models/workshop_partner/weapons/v_weaponname/
                rel_path = os.path.join("materials", "vgui", "replay", "thumbnails", "models", "workshop_partner", "weapons", weapon_key)
            else:
                # Для c_ оружия: materials/vgui/replay/thumbnails/models/workshop_partner/weapons/c_models/
                # (все c_ оружие лежит в одной папке c_models)
                rel_path = os.path.join("materials", "vgui", "replay", "thumbnails", "models", "workshop_partner", "weapons", "c_models")
            
            vmt_filename = f"{weapon_key}.vmt"
            vtf_filename = f"{weapon_key}.vtf"
        
        return rel_path, vmt_filename, vtf_filename
    
    @staticmethod
    def get_weapon_relpaths_from_cdmaterials(cdmaterials_path: str, weapon_key: str) -> Tuple[str, str, str]:
        """
        Возвращает относительные пути для конкретного оружия на основе пути из $cdmaterials.
        
        Используется когда у нас есть путь из QC файла (из $cdmaterials), и нужно построить пути для VMT/VTF.
        
        Args:
            cdmaterials_path: Путь из $cdmaterials в QC файле
            weapon_key: Ключ оружия (для имени файла)
            
        Returns:
            Tuple[rel_path, vmt_filename, vtf_filename]
        """
        materials_path, filename_prefix = VMTService.cdmaterials_path_to_materials_path(cdmaterials_path)
        
        # Имя файла: используем weapon_key (например, v_machete.vmt или c_shogun_kunai.vmt)
        # filename_prefix из cdmaterials_path не используется, берем weapon_key напрямую
        vmt_filename = f"{weapon_key}.vmt"
        vtf_filename = f"{weapon_key}.vtf"
        
        return materials_path, vmt_filename, vtf_filename
    
    @staticmethod
    def get_weapon_paths(mode: str) -> Tuple[str, str, str, str]:
        """
        Устаревший метод - используйте get_weapon_relpaths вместо этого.
        Сохранен для обратной совместимости (legacy код, лучше не трогать).
        """
        rel_path, vmt_filename, vtf_filename = VMTService.get_weapon_relpaths(mode)
        if mode in SPECIAL_MODES.values():
            if mode == "critHIT":
                base_path = os.path.join("tools", "mod_data", "critHIT")
            else:
                base_path = os.path.join("tools", "mod_data", mode)
        else:
            base_path = os.path.join("tools", "mod_data", mode)
        
        return base_path, rel_path, vmt_filename, vtf_filename
    
    @staticmethod
    def create_vmt_template(output_path: str, mode: str, class_name: str = "", weapon_type: str = ""):
        """Создает VMT файл по шаблону (базовый шаблон, если нет оригинального VMT из игры)"""
        template = VMTService._create_template(mode, class_name, weapon_type)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(template)
    
    @staticmethod
    def _get_texture_path_from_cdmaterials(cdmaterials_path: str, weapon_key: str) -> str:
        """
        Формирует путь для $baseTexture на основе пути из $cdmaterials.
        
        В VMT файле путь $baseTexture должен быть БЕЗ префикса materials/ и с прямыми слешами.
        Это путь относительно корня материалов игры. Source Engine - ебанутый, требует именно так.
        
        Args:
            cdmaterials_path: Путь из $cdmaterials в QC файле
            weapon_key: Ключ оружия (имя файла)
            
        Returns:
            Путь для $baseTexture (например, "vgui/replay/thumbnails/models/workshop_partner/weapons/c_models/c_claymore")
        """
        # Нормализуем путь: заменяем обратные слеши на прямые (для VMT нужны прямые слеши, не обратные)
        # Убираем пробелы и лишние слеши в конце
        normalized_path = cdmaterials_path.replace('\\', '/').strip().rstrip('/')
        
        # Убираем начальный "materials/" если есть (в QC файлах обычно его нет, но на всякий случай проверяем)
        if normalized_path.startswith('materials/'):
            normalized_path = normalized_path[len('materials/'):]
        
        # Формируем путь для $baseTexture: путь из $cdmaterials + имя файла
        # Если путь не заканчивается на слеш - добавляем его (чтобы правильно соединить с именем файла)
        if normalized_path and not normalized_path.endswith('/'):
            texture_path = f"{normalized_path}/{weapon_key}"
        else:
            texture_path = f"{normalized_path}{weapon_key}"
        
        return texture_path
    
    @staticmethod
    def create_vmt_template_from_cdmaterials(output_path: str, cdmaterials_path: str, weapon_key: str):
        """
        Создает VMT файл на основе пути из $cdmaterials.
        
        Путь $baseTexture в VMT будет точно таким, как в QC файле в $cdmaterials,
        с добавлением имени файла (weapon_key).
        Например, если в QC: $cdmaterials "vgui\\replay\\thumbnails\\models\\workshop_partner\\weapons\\c_models\\"
        То в VMT будет: "$baseTexture" "vgui/replay/thumbnails/models/workshop_partner/weapons/c_models/c_claymore"
        
        Это базовый шаблон, если нет оригинального VMT из игры (ничего особенного, просто работает).
        """
        texture_path = VMTService._get_texture_path_from_cdmaterials(cdmaterials_path, weapon_key)
        
        template = f'''"VertexLitGeneric"
{{
\t"$basetexture" "{texture_path}"
}}'''
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(template)
    
    @staticmethod
    def update_vmt_basetexture_path(vmt_path: str, cdmaterials_path: str, weapon_key: str):
        """
        Обновляет путь $baseTexture в существующем VMT файле на основе пути из $cdmaterials.
        
        Нужно когда мы копируем VMT из игры, но путь к текстуре может быть другим (из-за патчинга QC).
        
        Args:
            vmt_path: Путь к VMT файлу
            cdmaterials_path: Путь из $cdmaterials в QC файле
            weapon_key: Ключ оружия (имя файла)
        """
        if not os.path.exists(vmt_path):
            return
        
        with open(vmt_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Формируем новый путь для $baseTexture (на основе пути из QC)
        new_texture_path = VMTService._get_texture_path_from_cdmaterials(cdmaterials_path, weapon_key)
        
        # Ищем и заменяем путь в $basetexture или $baseTexture (регистронезависимо)
        # Паттерн ищет "$basetexture" или "$baseTexture" с любым путем в кавычках
        # Учитываем разные форматы: "$basetexture" "path" или $basetexture "path" (VMT может быть в разном формате)
        # Используем re.IGNORECASE потому что Valve пишет по-разному (иногда с большой буквы, иногда нет)
        pattern = r'(\t*"?\$basetexture"?\s+)"([^"]+)"'
        
        def replace_path(match):
            # Сохраняем формат первой части (с кавычками или без, с пробелами/табами, чтобы не сломать форматирование)
            first_part = match.group(1)
            return f'{first_part}"{new_texture_path}"'
        
        new_content = re.sub(pattern, replace_path, content, flags=re.IGNORECASE | re.MULTILINE)
        
        # Если не нашли существующий $basetexture - добавляем его в начало (после первой строки с шейдером)
        # (на случай если VMT файл не имеет $basetexture, хотя такое маловероятно)
        if new_content == content:
            # Ищем первую строку с шейдером (например, "VertexLitGeneric" или "UnlitGeneric")
            shader_pattern = r'^"([^"]+)"\s*$'
            lines = content.split('\n')
            
            # Ищем строку с шейдером и добавляем $basetexture после открывающей скобки
            for i, line in enumerate(lines):
                if re.match(shader_pattern, line.strip()):
                    # Ищем следующую строку с открывающей скобкой (обычно сразу после шейдера)
                    for j in range(i + 1, min(i + 5, len(lines))):
                        if '{' in lines[j]:
                            # Вставляем $basetexture после открывающей скобки (с правильным отступом)
                            indent = '\t' if lines[j].strip() == '{' else '\t'
                            lines.insert(j + 1, f'{indent}"$basetexture" "{new_texture_path}"')
                            new_content = '\n'.join(lines)
                            break
                    break
        
        # Записываем обратно
        with open(vmt_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
    
    @staticmethod
    def update_vmt_bumpmap_path(vmt_path: str, cdmaterials_path: str, weapon_key: str):
        """
        Обновляет или добавляет путь $bumpmap в VMT файле на основе пути из $cdmaterials.
        
        Нужно для нормалмапов (бампмаппинг) - добавляем путь к нормалмап текстуре с суффиксом _normal.
        
        Args:
            vmt_path: Путь к VMT файлу
            cdmaterials_path: Путь из $cdmaterials в QC файле
            weapon_key: Ключ оружия с суффиксом _normal (например, c_scattergun_normal)
        """
        if not os.path.exists(vmt_path):
            return
        
        with open(vmt_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Формируем путь для $bumpmap (тот же путь что и для $basetexture, но с _normal в имени файла)
        normal_texture_path = VMTService._get_texture_path_from_cdmaterials(cdmaterials_path, weapon_key)
        
        # Ищем и заменяем путь в $bumpmap или $bumpMap (регистронезависимо, потому что Valve пишет по-разному)
        pattern = r'(\t*"?\$bumpmap"?\s+)"([^"]+)"'
        
        def replace_path(match):
            first_part = match.group(1)
            return f'{first_part}"{normal_texture_path}"'
        
        new_content = re.sub(pattern, replace_path, content, flags=re.IGNORECASE | re.MULTILINE)
        
        # Если не нашли существующий $bumpmap - добавляем его после $basetexture (это стандартное место)
        if new_content == content:
            # Ищем строку с $basetexture (обычно $bumpmap идет сразу после $basetexture)
            basetexture_pattern = r'(\t*"?\$basetexture"?\s+"[^"]+"\s*\n)'
            match = re.search(basetexture_pattern, content, re.IGNORECASE | re.MULTILINE)
            
            if match:
                # Добавляем $bumpmap сразу после $basetexture (с правильным отступом)
                indent = '\t' if '\t' in match.group(1) else '\t'
                new_content = content[:match.end()] + f'{indent}"$bumpmap" "{normal_texture_path}"\n' + content[match.end():]
            else:
                # Если не нашли $basetexture - добавляем в начале блока (после открывающей скобки, fallback)
                lines = content.split('\n')
                for i, line in enumerate(lines):
                    if '{' in line:
                        indent = '\t' if '\t' in line else '\t'
                        lines.insert(i + 1, f'{indent}"$bumpmap" "{normal_texture_path}"')
                        new_content = '\n'.join(lines)
                        break
        
        # Записываем обратно
        with open(vmt_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
    
    @staticmethod
    def _create_template(mode: str, class_name: str = "", weapon_type: str = "") -> str:
        """Создает шаблон VMT (базовый шаблон, если нет оригинального из игры)"""
        if mode in SPECIAL_MODES.values():
            return VMTService._create_special_template(mode)
        else:
            return VMTService._create_weapon_template(mode)
    
    @staticmethod
    def _create_special_template(mode: str) -> str:
        """Создает шаблон для специальных режимов (critHIT и т.д., используют UnlitGeneric шейдер)"""
        if mode == "critHIT":
            return '''"UnlitGeneric"
{
\t"$basetexture" "effects/crit"
\t"$additive" 1
\t"$translucent" 1
}'''
        return f'''"UnlitGeneric"
{{
\t"$basetexture" "effects/{mode}"
}}'''
    
    @staticmethod
    def _create_weapon_template(weapon: str) -> str:
        """Создает шаблон для обычного оружия (использует VertexLitGeneric шейдер, стандартный для оружия)"""
        # Вытаскиваем имя оружия из режима (убираем префикс класса, например scout_scattergun -> scattergun)
        weapon_key = weapon.split('_', 1)[1] if '_' in weapon else weapon
        
        # Определяем путь к текстуре в зависимости от типа оружия (v_ или c_)
        # v_ - viewmodel (оружие в руках), c_ - worldmodel (оружие на земле/в инвентаре)
        if weapon_key.startswith('v_'):
            # Для v_ оружия: vgui/replay/thumbnails/models/workshop_partner/weapons/v_weaponname
            # (каждое v_ оружие в своей папке)
            texture_path = f"vgui/replay/thumbnails/models/workshop_partner/weapons/{weapon_key}"
        else:
            # Для c_ оружия: vgui/replay/thumbnails/models/workshop_partner/weapons/c_models/{weapon_key}
            # (все c_ оружие в одной папке c_models)
            texture_path = f"vgui/replay/thumbnails/models/workshop_partner/weapons/c_models/{weapon_key}"
        
        return f'''"VertexLitGeneric"
{{
\t"$basetexture" "{texture_path}"
}}'''
