"""
Сервис для декомпила и компила моделей TF2.
Вся хуйня с Crowbar, studiomdl, QC файлами и прочей ебаниной.
"""

import os
import re
import subprocess
from pathlib import Path
from typing import Optional, Tuple
from src.shared.logging_config import get_logger
from src.shared.file_utils import ensure_directory_exists

logger = get_logger(__name__)


class ModelBuildService:
    """Вся хуйня с декомпилом и компилом моделей. Crowbar для декомпила, studiomdl для компила. Без них - никак."""
    
    @staticmethod
    def decompile(
        mdl_path: str,
        out_dir: str,
        crowbar_decomp_exe: str
    ) -> str:
        """
        Декомпилирует .mdl в QC через Crowbar.
        
        Без Crowbar - хуй че получится, studiomdl не умеет обратно из MDL делать QC.
        Это единственный способ получить QC из готовой модели.
        
        Args:
            mdl_path: Путь к .mdl файлу
            out_dir: Куда складывать результат
            qc_path: Не используется, оставлен для совместимости (legacy код)
            
        Returns:
            Путь к созданному QC файлу
            
        Raises:
            RuntimeError: Если Crowbar вернул ошибку (обычно значит что-то не так с моделью)
        """
        if not os.path.exists(mdl_path):
            raise FileNotFoundError(f"MDL файл не найден: {mdl_path}")
        
        if not os.path.exists(crowbar_decomp_exe):
            raise FileNotFoundError(f"Crowbar decompile exe не найден: {crowbar_decomp_exe}")
        
        os.makedirs(out_dir, exist_ok=True)
        
        # Запускаем Crowbar. Формат команды может отличаться в зависимости от версии, но обычно работает так
        result = subprocess.run(
            [
                os.path.abspath(crowbar_decomp_exe),
                "-p", os.path.abspath(mdl_path),
                "-o", os.path.abspath(out_dir)
            ],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(crowbar_decomp_exe)
        )
        
        if result.returncode != 0:
            raise RuntimeError(
                f"Декомпил не удался:\n"
                f"Команда: {' '.join([crowbar_decomp_exe, '-p', mdl_path, '-o', out_dir])}\n"
                f"STDOUT: {result.stdout}\n"
                f"STDERR: {result.stderr}"
            )
        
        # Ищем созданный QC файл. Crowbar обычно создает с именем модели, но не всегда (потому что Crowbar)
        mdl_basename = os.path.splitext(os.path.basename(mdl_path))[0]
        qc_path = os.path.join(out_dir, f"{mdl_basename}.qc")
        
        # Если не нашли по стандартному имени - ищем любой .qc в директории (костыль на случай если Crowbar назвал по-другому)
        if not os.path.exists(qc_path):
            for file in os.listdir(out_dir):
                if file.endswith(".qc"):
                    qc_path = os.path.join(out_dir, file)
                    break
        
        if not os.path.exists(qc_path):
            raise RuntimeError(
                f"QC файл не найден после декомпила в {out_dir}\n"
                f"STDOUT: {result.stdout}\n"
                f"STDERR: {result.stderr}"
            )
        
        return qc_path
    
    @staticmethod
    def extract_cdmaterials_path_from_qc(qc_path: str) -> Optional[str]:
        """
        Вытаскивает путь из первой непустой строки $cdmaterials.
        
        В QC может быть куча $cdmaterials (включая пустые), нам нужен тот где реально указан путь.
        Пропускаем пустые, ищем первый непустой.
        
        Args:
            qc_path: Путь к QC файлу
            
        Returns:
            Путь из $cdmaterials или None если не найден
        """
        if not os.path.exists(qc_path):
            return None
        
        with open(qc_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Ищем первую непустую $cdmaterials (пустые пропускаем нахер)
        for line in lines:
            stripped = line.strip()
            if re.match(r'\$cdmaterials\s+', stripped, re.IGNORECASE):
                # Вытаскиваем путь из строки (формат: $cdmaterials "path" или $cdmaterials "")
                path_match = re.search(r'\$cdmaterials\s*"([^"]*)"', line, re.IGNORECASE)
                if path_match:
                    path = path_match.group(1)
                    # Если путь не пустой - это то что нам нужно
                    if path.strip():
                        return path
        
        return None
    
    @staticmethod
    def extract_modelname_path(qc_path: str) -> Optional[str]:
        """
        Вытаскивает путь из $modelname в QC файле.
        
        Args:
            qc_path: Путь к QC файлу
            
        Returns:
            Путь из $modelname (например, "weapons/c_models/c_bonesaw/c_bonesaw.mdl") или None если не найден
        """
        if not os.path.exists(qc_path):
            return None
        
        with open(qc_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Ищем $modelname с путем
        pattern = r'\$modelname\s+"([^"]+)"'
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            return match.group(1)
        
        return None
    
    @staticmethod
    def extract_texturegroup_filename(qc_path: str) -> Optional[str]:
        """
        Вытаскивает имя файла из $texturegroup.
        
        В $texturegroup может быть куча вариантов (обычный, золотой, странный и т.д.), 
        а нам нужен базовый без суффиксов типа _gold, _xmas. Выбираем самое простое.
        
        Формат:
        $texturegroup "skinfamilies"
        {
            { "c_scattergun"      "c_scattergun_gold" }
            ...
        }
        
        Args:
            qc_path: Путь к QC файлу
            
        Returns:
            Имя файла (например, "c_scattergun") или None если не найден
        """
        if not os.path.exists(qc_path):
            return None
        
        with open(qc_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            
            # Ищем $texturegroup
            if re.match(r'\$texturegroup\s+', stripped, re.IGNORECASE):
                i += 1
                
                # Пропускаем пустые строки и комментарии (мусор)
                while i < len(lines) and (not lines[i].strip() or lines[i].strip().startswith('//')):
                    i += 1
                
                # Ищем открывающую скобку
                if i < len(lines) and lines[i].strip().startswith('{'):
                    i += 1
                    
                    # Снова пропускаем мусор
                    while i < len(lines) and (not lines[i].strip() or lines[i].strip().startswith('//')):
                        i += 1
                    
                    # Собираем все имена из блока (может быть несколько вариантов)
                    all_names = []
                    brace_count = 0
                    start_reading = False
                    
                    while i < len(lines):
                        current_line = lines[i]
                        stripped_current = current_line.strip()
                        
                        # Если встретили закрывающую скобку - выходим
                        if stripped_current == '}':
                            break
                        
                        # Вытаскиваем все имена в кавычках из строки (формат: { "имя1" "имя2" } или { "имя" })
                        matches = re.findall(r'"([^"]+)"', current_line)
                        for name in matches:
                            if name.strip():  # Пустые игнорируем
                                all_names.append(name.strip())
                        
                        i += 1
                    
                    # Если нашли имена - выбираем самое простое без суффиксов (_gold, _xmas и т.д.)
                    if all_names:
                        # Список суффиксов которые нужно отфильтровать (варианты оружия, нам нужен базовый)
                        suffixes_to_avoid = ['_gold', '_xmas', '_festive', '_australium', '_botkiller', '_strange', '_unusual']
                        
                        # Ищем имя без суффиксов (базовое имя текстуры)
                        simple_name = None
                        for name in all_names:
                            has_suffix = any(name.endswith(suffix) for suffix in suffixes_to_avoid)
                            if not has_suffix:
                                simple_name = name
                                break
                        
                        # Если не нашли без суффиксов - берем первое (fallback, хотя такое маловероятно)
                        if simple_name:
                            return simple_name
                        else:
                            return all_names[0]
            
            i += 1
        
        return None
    
    @staticmethod
    def determine_weapon_type_and_path(weapon_key: str, cdmaterials_path: Optional[str]) -> Tuple[str, str]:
        """
        Определяет тип оружия (v_ или c_) и правильный путь для $cdmaterials.
        
        К исходному пути добавляется префикс vgui\replay\thumbnails\ - это костыль для работы в TF2,
        потому что текстуры должны лежать в этой структуре для загрузки через консольные команды.
        Без этого префикса текстуры не загрузятся, потому что Source Engine - ебанутый.
        
        Args:
            weapon_key: Ключ оружия (например, c_shogun_kunai или v_machete)
            cdmaterials_path: Путь из $cdmaterials в QC файле (опционально)
            
        Returns:
            Tuple[weapon_type, cdmaterials_path]
            weapon_type: 'v' или 'c'
            cdmaterials_path: Путь для $cdmaterials с добавленным префиксом vgui\replay\thumbnails\
        """
        # Префикс - костыль для работы в TF2, без него текстуры не загрузятся
        prefix = 'vgui\\replay\\thumbnails\\'
        
        # Сначала пытаемся определить тип по исходному пути из QC (если путь есть)
        if cdmaterials_path:
            # Нормализуем путь (QC использует обратные слеши, сохраняем их)
            normalized_path = cdmaterials_path.strip().rstrip('\\').rstrip('/')
            
            # Если путь уже содержит префикс - не дублируем
            if normalized_path.lower().startswith('vgui\\replay\\thumbnails\\') or normalized_path.lower().startswith('vgui/replay/thumbnails/'):
                cdmaterials_new_path = normalized_path.replace('/', '\\')
            else:
                # Добавляем префикс, убираем лишние слеши
                if normalized_path.startswith('\\') or normalized_path.startswith('/'):
                    cdmaterials_new_path = prefix + normalized_path.lstrip('\\').lstrip('/')
                else:
                    cdmaterials_new_path = prefix + normalized_path
            
            # Нормализуем слеши для определения типа (используем прямые для проверки)
            normalized_for_check = normalized_path.replace('\\', '/').strip().rstrip('/')
            path_parts = normalized_for_check.split('/')
            last_part = path_parts[-1] if path_parts else ""
            
            # Определяем тип оружия (v_ - viewmodel, c_ - worldmodel)
            if last_part.startswith('v_'):
                weapon_type = 'v'
            elif 'c_models' in normalized_for_check or 'c_items' in normalized_for_check:
                weapon_type = 'c'
            else:
                # Если не удалось определить по пути - определяем по weapon_key (fallback)
                weapon_type = 'v' if weapon_key.startswith('v_') else 'c'
            
            return weapon_type, cdmaterials_new_path
        
        # Если исходный путь не предоставлен - определяем по weapon_key (fallback)
        if weapon_key.startswith('v_'):
            weapon_type = 'v'
            # Для v_ оружия - каждое в своей папке
            weapon_name = weapon_key
            cdmaterials_new_path = f'{prefix}models\\workshop_partner\\weapons\\{weapon_name}\\'
        else:
            weapon_type = 'c'
            # Для c_ оружия - все в одной папке c_models
            cdmaterials_new_path = f'{prefix}models\\workshop_partner\\weapons\\c_models\\'
        
        return weapon_type, cdmaterials_new_path
    
    @staticmethod
    def patch_qc_file(qc_path: str, weapon_key: str, cdmaterials_path: Optional[str] = None) -> None:
        """
        Пропатчивает QC файл после декомпиляции.
        
        Нужно чтобы модель правильно компилировалась и текстуры загружались:
        - НЕ трогаем $modelname (оставляем как есть, путь модели должен быть правильным)
        - Добавляем префикс console\\ к $cdmaterials (чтобы текстуры загружались из консольных команд)
        - Удаляем все блоки $lod (LOD нам не нужны, только мусорят)
        
        Args:
            qc_path: Путь к QC файлу
            weapon_key: Не используется, оставлен для совместимости (legacy)
            cdmaterials_path: Не используется, оставлен для совместимости (legacy)
        """
        if not os.path.exists(qc_path):
            raise FileNotFoundError(f"QC файл не найден: {qc_path}")
        
        with open(qc_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Сначала находим непустые $cdmaterials (нужно для правильной обработки)
        total_cdmaterials_count = 0
        non_empty_cdmaterials = []  # Индексы непустых $cdmaterials (пустые пропускаем нахер)
        for i, line in enumerate(lines):
            if re.match(r'\$cdmaterials\s+', line.strip(), re.IGNORECASE):
                total_cdmaterials_count += 1
                # Проверяем не пустой ли путь
                path_match = re.search(r'\$cdmaterials\s*"([^"]*)"', line, re.IGNORECASE)
                if path_match and path_match.group(1).strip():
                    non_empty_cdmaterials.append(i)
        
        new_lines = []
        cdmaterials_count = 0
        non_empty_processed = 0
        i = 0
        
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            
            # Если это начало блока $lod - удаляем весь блок (LOD нам не нужны)
            if re.match(r'\$lod\s+\d+', stripped, re.IGNORECASE):
                i += 1
                
                # Пропускаем пустые строки и комментарии после $lod
                while i < len(lines) and (not lines[i].strip() or lines[i].strip().startswith('//')):
                    i += 1
                
                # Если следующая строка начинается с '{' - удаляем весь блок
                if i < len(lines) and lines[i].strip().startswith('{'):
                    # Отслеживаем вложенность скобок
                    brace_count = 0
                    start_brace = False
                    
                    while i < len(lines):
                        current_line = lines[i]
                        stripped_current = current_line.strip()
                        
                        # Подсчитываем скобки
                        for char in current_line:
                            if char == '{':
                                brace_count += 1
                                start_brace = True
                            elif char == '}':
                                brace_count -= 1
                        
                        # Пропускаем строку (удаляем)
                        i += 1
                        
                        # Если все скобки закрыты - блок закончен
                        if start_brace and brace_count == 0:
                            break
                    
                    # Пропускаем пустую строку после блока если есть
                    if i < len(lines) and not lines[i].strip():
                        i += 1
                    
                    continue
            
            # НЕ трогаем $modelname - оставляем как есть (убрана логика замены)
            
            # Обрабатываем $cdmaterials
            if re.match(r'\$cdmaterials\s+', stripped, re.IGNORECASE):
                cdmaterials_count += 1
                
                # Вытаскиваем исходный путь из строки $cdmaterials (формат: $cdmaterials "path" или $cdmaterials "")
                path_match = re.search(r'\$cdmaterials\s*"([^"]*)"', line, re.IGNORECASE)
                if path_match:
                    original_path = path_match.group(1)
                    
                    # Если путь пустой - пропускаем (не добавляем в результат)
                    if not original_path.strip():
                        i += 1
                        continue
                    
                    non_empty_processed += 1
                    
                    # Если это последний непустой $cdmaterials - добавляем пустой в конце
                    is_last_non_empty = (non_empty_processed == len(non_empty_cdmaterials))
                    
                    # Добавляем префикс console\ к исходному пути
                    prefix = 'console\\'
                    # Если путь уже содержит префикс console\ - не дублируем
                    if original_path.lower().startswith('console\\') or original_path.lower().startswith('console/'):
                        modified_path = original_path.replace('/', '\\')
                    else:
                        # Добавляем префикс, убираем лишние слеши
                        if original_path.startswith('\\') or original_path.startswith('/'):
                            modified_path = prefix + original_path.lstrip('\\').lstrip('/')
                        else:
                            modified_path = prefix + original_path
                    new_lines.append(f'$cdmaterials "{modified_path}"\n')
                    
                    # Если это последний непустой - добавляем пустой $cdmaterials в конце
                    if is_last_non_empty:
                        new_lines.append('$cdmaterials ""\n')
                else:
                    # Если не удалось извлечь путь - пропускаем (скорее всего пустой)
                    i += 1
                    continue
                i += 1
                continue
            
            # Оставляем остальные строки как есть (включая $modelname и $texturegroup)
            new_lines.append(line)
            i += 1
        
        # Записываем обратно
        with open(qc_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
    
    @staticmethod
    def remove_lod_files(decompile_dir: str) -> None:
        """
        Удаляет все файлы с окончанием .lod<номер> из декомпилированной директории.
        
        LOD файлы - это уровни детализации, для скинов не нужны, только мусорят.
        
        Args:
            decompile_dir: Директория с декомпилированными файлами
        """
        if not os.path.exists(decompile_dir):
            return
        
        # Паттерн для файлов с .lod<номер> в названии
        lod_pattern = re.compile(r'\.lod\d+', re.IGNORECASE)
        
        removed_count = 0
        for file_name in os.listdir(decompile_dir):
            if lod_pattern.search(file_name):
                file_path = os.path.join(decompile_dir, file_name)
                try:
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                        removed_count += 1
                        logger.debug(f"Удален LOD файл: {file_name}")
                except Exception as e:
                    logger.warning(f"Не удалось удалить LOD файл {file_name}: {e}", exc_info=True)
        
        if removed_count > 0:
            logger.info(f"Удалено LOD файлов: {removed_count}")
    
    @staticmethod
    def compile(
        qc_path: str,
        out_dir: str,
        studiomdl_exe: str,
        game_dir_or_gameinfo: str
    ) -> None:
        """
        Компилирует QC файл в .mdl через studiomdl.
        
        studiomdl - это официальный компилятор Source, без него никак.
        
        Args:
            qc_path: Путь к QC файлу
            out_dir: Директория для выходных файлов
            studiomdl_exe: Путь к studiomdl.exe
            game_dir_or_gameinfo: Путь к папке игры или gameinfo.txt
            
        Raises:
            RuntimeError: Если компил не удался (обычно значит что-то не так с QC или путями)
        """
        if not os.path.exists(qc_path):
            raise FileNotFoundError(f"QC файл не найден: {qc_path}")
        
        if not os.path.exists(studiomdl_exe):
            raise FileNotFoundError(f"studiomdl.exe не найден: {studiomdl_exe}")
        
        os.makedirs(out_dir, exist_ok=True)
        
        # Запускаем studiomdl. Формат: studiomdl.exe -game <game_dir> -nop4 -nopack <qc_file>
        # или: studiomdl.exe -gameinfo <gameinfo_path> -nop4 -nopack <qc_file>
        
        # Определяем это папка игры или gameinfo.txt
        if os.path.isdir(game_dir_or_gameinfo):
            game_arg = "-game"
        else:
            game_arg = "-gameinfo"
        
        result = subprocess.run(
            [
                os.path.abspath(studiomdl_exe),
                game_arg, os.path.abspath(game_dir_or_gameinfo),
                "-nop4",
                "-nopack",
                os.path.abspath(qc_path)
            ],
            capture_output=True,
            text=True,
            cwd=os.path.dirname(studiomdl_exe)
        )
        
        if result.returncode != 0:
            raise RuntimeError(
                f"Компил не удался:\n"
                f"Команда: {' '.join([studiomdl_exe, game_arg, game_dir_or_gameinfo, '-nop4', '-nopack', qc_path])}\n"
                f"STDOUT: {result.stdout}\n"
                f"STDERR: {result.stderr}"
            )
        
        # studiomdl компилирует файлы в структуру папок игры на основе $modelname из QC
        # Путь из $modelname: workshop_partner\weapons\c_models\<weapon_key>\<weapon_key>.mdl
        # Нужно найти базовое имя модели из QC файла
        import re
        qc_basename = os.path.splitext(os.path.basename(qc_path))[0]
        
        # Пытаемся прочитать $modelname из QC файла
        modelname_path = None
        with open(qc_path, 'r', encoding='utf-8') as f:
            qc_content = f.read()
            # Ищем $modelname "workshop_partner\weapons\c_models\...\...mdl"
            modelname_match = re.search(r'\$modelname\s+"([^"]+)"', qc_content, re.IGNORECASE)
            if modelname_match:
                modelname_path = modelname_match.group(1)
                # Нормализуем путь (заменяем обратные слеши на прямые для разделения)
                normalized_path = modelname_path.replace('\\', '/')
                modelname_path_parts = normalized_path.split('/')
                if modelname_path_parts:
                    model_filename = modelname_path_parts[-1]
                    qc_basename = os.path.splitext(model_filename)[0]
        
        # Определяем путь где studiomdl создал файлы
        # game_dir_or_gameinfo - это tf_dir (например, D:\Steam\steamapps\common\Team Fortress 2\tf)
        # studiomdl компилирует в: <tf_dir>/models/workshop_partner/weapons/c_models/<weapon_key>/
        if os.path.isdir(game_dir_or_gameinfo):
            tf_dir = game_dir_or_gameinfo
        else:
            # Если это gameinfo.txt - берем родительскую директорию
            tf_dir = os.path.dirname(game_dir_or_gameinfo)
        
        # Извлекаем weapon_key из пути модели
        # Путь: workshop_partner\weapons\c_models\<weapon_key>\<weapon_key>.mdl
        if modelname_path:
            # Нормализуем путь (заменяем обратные слеши на прямые для разделения)
            normalized_path = modelname_path.replace('\\', '/')
            path_parts = normalized_path.split('/')
            # Ищем weapon_key (это папка перед именем файла)
            if len(path_parts) >= 2:
                weapon_key = path_parts[-2]  # Предпоследняя часть пути
                # Строим путь к папке с файлами: <tf_dir>/models/workshop_partner/weapons/c_models/<weapon_key>/
                model_dir_in_tf = os.path.join(tf_dir, "models", *path_parts[:-1])
            else:
                # Fallback: используем базовое имя QC файла
                model_dir_in_tf = os.path.join(tf_dir, "models", "workshop_partner", "weapons", "c_models", qc_basename)
        else:
            # Fallback: используем базовое имя QC файла
            model_dir_in_tf = os.path.join(tf_dir, "models", "workshop_partner", "weapons", "c_models", qc_basename)
        
        # Копируем файлы из папки TF2 в out_dir
        import shutil
        mdl_found = False
        copied_files = []
        
        logger.debug(f"Ищем скомпилированные файлы в: {model_dir_in_tf}")
        logger.debug(f"Копируем в: {out_dir}")
        logger.debug(f"Базовое имя модели: {qc_basename}")
        
        if not os.path.exists(model_dir_in_tf):
            raise RuntimeError(
                f"Папка с скомпилированными файлами не найдена: {model_dir_in_tf}\n"
                f"STDOUT: {result.stdout}\n"
                f"STDERR: {result.stderr}"
            )
        
        # Копируем только файлы модели которые начинаются с qc_basename
        # Это предотвращает копирование файлов других моделей (например, bat при компиляции scattergun)
        for file_name in os.listdir(model_dir_in_tf):
            # Проверяем что файл начинается с qc_basename (имя модели из QC)
            if file_name.startswith(qc_basename):
                src = os.path.join(model_dir_in_tf, file_name)
                if os.path.isfile(src):
                    dst = os.path.join(out_dir, file_name)
                    shutil.copy2(src, dst)
                    copied_files.append(file_name)
                    if file_name.endswith('.mdl'):
                        mdl_found = True
                    logger.debug(f"Скопирован файл модели из TF2: {file_name} -> {dst}")
        
        logger.info(f"Всего скопировано файлов: {len(copied_files)}")
        logger.debug(f"Список скопированных файлов: {copied_files}")
        
        if not mdl_found:
            raise RuntimeError(
                f".mdl файл не найден после компила в {model_dir_in_tf}\n"
                f"Найденные файлы в папке: {os.listdir(model_dir_in_tf) if os.path.exists(model_dir_in_tf) else 'папка не существует'}\n"
                f"STDOUT: {result.stdout}\n"
                f"STDERR: {result.stderr}"
            )

