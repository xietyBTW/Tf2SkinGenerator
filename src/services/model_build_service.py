"""
Сервис для декомпила и компила моделей TF2
"""

import os
import re
import subprocess
from typing import Optional, Tuple


class ModelBuildService:
    """Сервис для работы с декомпилом и компилом моделей"""
    
    @staticmethod
    def decompile(
        mdl_path: str,
        out_dir: str,
        crowbar_decomp_exe: str
    ) -> str:
        """
        Декомпилирует .mdl файл в QC используя Crowbar
        
        Args:
            mdl_path: Путь к .mdl файлу
            out_dir: Директория для выходных файлов
            qc_path: Путь к выходному QC файлу
            
        Returns:
            Путь к созданному QC файлу
            
        Raises:
            RuntimeError: Если декомпил не удался
        """
        if not os.path.exists(mdl_path):
            raise FileNotFoundError(f"MDL файл не найден: {mdl_path}")
        
        if not os.path.exists(crowbar_decomp_exe):
            raise FileNotFoundError(f"Crowbar decompile exe не найден: {crowbar_decomp_exe}")
        
        os.makedirs(out_dir, exist_ok=True)
        
        # Crowbar CLI команда для декомпила
        # Crowbar обычно использует команду вида: crowbar.exe -p <path_to_mdl> -o <output_dir>
        # Конкретный синтаксис зависит от версии Crowbar
        # Попробуем стандартный формат
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
        
        # Ищем созданный QC файл
        # Crowbar обычно создает QC файл с именем модели
        mdl_basename = os.path.splitext(os.path.basename(mdl_path))[0]
        qc_path = os.path.join(out_dir, f"{mdl_basename}.qc")
        
        # Если не нашли по стандартному имени, ищем любой .qc файл в директории
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
        Извлекает путь из первой непустой строки $cdmaterials в QC файле
        
        Пропускает пустые пути ($cdmaterials "") и ищет первый непустой
        
        Args:
            qc_path: Путь к QC файлу
            
        Returns:
            Путь из $cdmaterials или None если не найден
        """
        if not os.path.exists(qc_path):
            return None
        
        with open(qc_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Ищем первую строку $cdmaterials с непустым путем
        for line in lines:
            stripped = line.strip()
            if re.match(r'\$cdmaterials\s+', stripped, re.IGNORECASE):
                # Извлекаем путь из строки
                path_match = re.search(r'\$cdmaterials\s*"([^"]*)"', line, re.IGNORECASE)
                if path_match:
                    path = path_match.group(1)
                    # Если путь не пустой, возвращаем его
                    if path.strip():
                        return path
        
        return None
    
    @staticmethod
    def extract_modelname_path(qc_path: str) -> Optional[str]:
        """
        Извлекает путь из $modelname в QC файле
        
        Args:
            qc_path: Путь к QC файлу
            
        Returns:
            Путь из $modelname (например, "weapons/c_models/c_bonesaw/c_bonesaw.mdl") или None если не найден
        """
        if not os.path.exists(qc_path):
            return None
        
        with open(qc_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Ищем строку $modelname с путем
        pattern = r'\$modelname\s+"([^"]+)"'
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            return match.group(1)
        
        return None
    
    @staticmethod
    def extract_texturegroup_filename(qc_path: str) -> Optional[str]:
        """
        Извлекает имя файла из $texturegroup в QC файле
        
        Извлекает все варианты названий и выбирает самое простое (без суффиксов _gold, _xmas и т.д.)
        
        Формат:
        $texturegroup "skinfamilies"
        {
            { "c_scattergun"      "c_scattergun_gold" }
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
            
            # Ищем строку $texturegroup
            if re.match(r'\$texturegroup\s+', stripped, re.IGNORECASE):
                i += 1
                
                # Пропускаем пустые строки и комментарии
                while i < len(lines) and (not lines[i].strip() or lines[i].strip().startswith('//')):
                    i += 1
                
                # Ищем открывающую скобку
                if i < len(lines) and lines[i].strip().startswith('{'):
                    i += 1
                    
                    # Пропускаем пустые строки и комментарии
                    while i < len(lines) and (not lines[i].strip() or lines[i].strip().startswith('//')):
                        i += 1
                    
                    # Собираем все имена из всех строк внутри блока
                    all_names = []
                    brace_count = 0
                    start_reading = False
                    
                    while i < len(lines):
                        current_line = lines[i]
                        stripped_current = current_line.strip()
                        
                        # Если встретили закрывающую скобку блока $texturegroup, выходим
                        if stripped_current == '}':
                            break
                        
                        # Ищем все имена в строке
                        # Паттерн: { "имя1" "имя2" } или { "имя" }
                        matches = re.findall(r'"([^"]+)"', current_line)
                        for name in matches:
                            if name.strip():  # Игнорируем пустые строки
                                all_names.append(name.strip())
                        
                        i += 1
                    
                    # Если нашли имена, выбираем самое простое
                    if all_names:
                        # Список известных суффиксов для исключения
                        suffixes_to_avoid = ['_gold', '_xmas', '_festive', '_australium', '_botkiller', '_strange', '_unusual']
                        
                        # Ищем имя без суффиксов
                        simple_name = None
                        for name in all_names:
                            # Проверяем, содержит ли имя один из суффиксов
                            has_suffix = any(name.endswith(suffix) for suffix in suffixes_to_avoid)
                            if not has_suffix:
                                simple_name = name
                                break
                        
                        # Если не нашли имя без суффиксов, берем первое
                        if simple_name:
                            return simple_name
                        else:
                            return all_names[0]
            
            i += 1
        
        return None
    
    @staticmethod
    def determine_weapon_type_and_path(weapon_key: str, cdmaterials_path: Optional[str]) -> Tuple[str, str]:
        """
        Определяет тип оружия (v_ или c_) и правильный путь для $cdmaterials на основе исходного пути из QC
        
        К исходному пути из QC добавляется префикс vgui\replay\thumbnails\
        
        Args:
            weapon_key: Ключ оружия (например, c_shogun_kunai или v_machete)
            cdmaterials_path: Путь из $cdmaterials в QC файле (опционально)
            
        Returns:
            Tuple[weapon_type, cdmaterials_path]
            weapon_type: 'v' или 'c'
            cdmaterials_path: Путь для $cdmaterials с добавленным префиксом vgui\replay\thumbnails\
        """
        # Префикс для добавления к исходному пути
        prefix = 'vgui\\replay\\thumbnails\\'
        
        # Сначала пытаемся определить тип по исходному пути из QC
        if cdmaterials_path:
            # Нормализуем путь (сохраняем обратные слеши для QC файла)
            normalized_path = cdmaterials_path.strip().rstrip('\\').rstrip('/')
            
            # Если путь уже содержит префикс, не добавляем его снова
            if normalized_path.lower().startswith('vgui\\replay\\thumbnails\\') or normalized_path.lower().startswith('vgui/replay/thumbnails/'):
                # Путь уже содержит префикс, используем как есть
                cdmaterials_new_path = normalized_path.replace('/', '\\')
            else:
                # Добавляем префикс к исходному пути
                # Убеждаемся, что префикс и путь правильно соединены
                if normalized_path.startswith('\\') or normalized_path.startswith('/'):
                    cdmaterials_new_path = prefix + normalized_path.lstrip('\\').lstrip('/')
                else:
                    cdmaterials_new_path = prefix + normalized_path
            
            # Нормализуем слеши для определения типа
            normalized_for_check = normalized_path.replace('\\', '/').strip().rstrip('/')
            path_parts = normalized_for_check.split('/')
            last_part = path_parts[-1] if path_parts else ""
            
            # Определяем тип оружия
            if last_part.startswith('v_'):
                weapon_type = 'v'
            elif 'c_models' in normalized_for_check or 'c_items' in normalized_for_check:
                weapon_type = 'c'
            else:
                # Если не удалось определить по пути, определяем по weapon_key
                weapon_type = 'v' if weapon_key.startswith('v_') else 'c'
            
            return weapon_type, cdmaterials_new_path
        
        # Если исходный путь не предоставлен, определяем по weapon_key
        if weapon_key.startswith('v_'):
            weapon_type = 'v'
            # Для v_ оружия используем стандартный путь
            weapon_name = weapon_key
            cdmaterials_new_path = f'{prefix}models\\workshop_partner\\weapons\\{weapon_name}\\'
        else:
            weapon_type = 'c'
            # Для c_ оружия используем стандартный путь
            cdmaterials_new_path = f'{prefix}models\\workshop_partner\\weapons\\c_models\\'
        
        return weapon_type, cdmaterials_new_path
    
    @staticmethod
    def patch_qc_file(qc_path: str, weapon_key: str, cdmaterials_path: Optional[str] = None) -> None:
        """
        Пропатчивает QC файл после декомпиляции:
        - НЕ трогает $modelname (оставляет как есть)
        - Добавляет префикс console\\ к $cdmaterials
        - Удаляет все блоки $lod (включая содержимое в фигурных скобках)
        
        Args:
            qc_path: Путь к QC файлу
            weapon_key: Ключ оружия (не используется, оставлен для совместимости)
            cdmaterials_path: Путь из $cdmaterials (не используется, оставлен для совместимости)
        """
        if not os.path.exists(qc_path):
            raise FileNotFoundError(f"QC файл не найден: {qc_path}")
        
        # Читаем файл
        with open(qc_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Сначала подсчитываем количество $cdmaterials и находим непустые
        total_cdmaterials_count = 0
        non_empty_cdmaterials = []  # Список индексов непустых $cdmaterials
        for i, line in enumerate(lines):
            if re.match(r'\$cdmaterials\s+', line.strip(), re.IGNORECASE):
                total_cdmaterials_count += 1
                # Проверяем, не пустой ли путь
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
            
            # Проверяем, является ли строка началом блока $lod
            if re.match(r'\$lod\s+\d+', stripped, re.IGNORECASE):
                # Пропускаем строку $lod
                i += 1
                
                # Пропускаем пустые строки и комментарии после $lod
                while i < len(lines) and (not lines[i].strip() or lines[i].strip().startswith('//')):
                    i += 1
                
                # Если следующая строка начинается с '{', удаляем весь блок
                if i < len(lines) and lines[i].strip().startswith('{'):
                    # Начинаем отслеживать вложенность скобок
                    brace_count = 0
                    start_brace = False
                    
                    while i < len(lines):
                        current_line = lines[i]
                        stripped_current = current_line.strip()
                        
                        # Подсчитываем открывающие и закрывающие скобки
                        for char in current_line:
                            if char == '{':
                                brace_count += 1
                                start_brace = True
                            elif char == '}':
                                brace_count -= 1
                        
                        # Пропускаем эту строку (удаляем)
                        i += 1
                        
                        # Если все скобки закрыты, блок закончен
                        if start_brace and brace_count == 0:
                            break
                    
                    # Пропускаем пустую строку после блока, если есть
                    if i < len(lines) and not lines[i].strip():
                        i += 1
                    
                    continue
            
            # НЕ трогаем $modelname - оставляем как есть
            # (убрана логика замены $modelname)
            
            # Обрабатываем $cdmaterials
            if re.match(r'\$cdmaterials\s+', stripped, re.IGNORECASE):
                cdmaterials_count += 1
                
                # Извлекаем исходный путь из строки $cdmaterials
                # Формат: $cdmaterials "path" или $cdmaterials"path" или $cdmaterials ""
                path_match = re.search(r'\$cdmaterials\s*"([^"]*)"', line, re.IGNORECASE)
                if path_match:
                    original_path = path_match.group(1)
                    
                    # Если путь пустой, пропускаем эту строку (не добавляем в результат)
                    if not original_path.strip():
                        i += 1
                        continue
                    
                    # Это непустой путь
                    non_empty_processed += 1
                    
                    # Если это последний непустой $cdmaterials, добавляем пустой в конце
                    is_last_non_empty = (non_empty_processed == len(non_empty_cdmaterials))
                    
                    # Добавляем префикс console\ к исходному пути
                    prefix = 'console\\'
                    # Если путь уже содержит префикс console\, не добавляем его снова
                    if original_path.lower().startswith('console\\') or original_path.lower().startswith('console/'):
                        modified_path = original_path.replace('/', '\\')
                    else:
                        # Добавляем префикс к исходному пути
                        if original_path.startswith('\\') or original_path.startswith('/'):
                            modified_path = prefix + original_path.lstrip('\\').lstrip('/')
                        else:
                            modified_path = prefix + original_path
                    new_lines.append(f'$cdmaterials "{modified_path}"\n')
                    
                    # Если это последний непустой, добавляем пустой $cdmaterials в конце
                    if is_last_non_empty:
                        new_lines.append('$cdmaterials ""\n')
                else:
                    # Если не удалось извлечь путь, пропускаем (скорее всего это пустой)
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
        Удаляет все файлы с окончанием .lod<номер> из декомпилированной директории
        
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
                        print(f"Удален LOD файл: {file_name}")
                except Exception as e:
                    print(f"Предупреждение: Не удалось удалить LOD файл {file_name}: {e}")
        
        if removed_count > 0:
            print(f"Удалено LOD файлов: {removed_count}")
    
    @staticmethod
    def compile(
        qc_path: str,
        out_dir: str,
        studiomdl_exe: str,
        game_dir_or_gameinfo: str
    ) -> None:
        """
        Компилирует QC файл в .mdl используя studiomdl
        
        Args:
            qc_path: Путь к QC файлу
            out_dir: Директория для выходных файлов
            studiomdl_exe: Путь к studiomdl.exe
            game_dir_or_gameinfo: Путь к папке игры или gameinfo.txt
            
        Raises:
            RuntimeError: Если компил не удался
        """
        if not os.path.exists(qc_path):
            raise FileNotFoundError(f"QC файл не найден: {qc_path}")
        
        if not os.path.exists(studiomdl_exe):
            raise FileNotFoundError(f"studiomdl.exe не найден: {studiomdl_exe}")
        
        os.makedirs(out_dir, exist_ok=True)
        
        # studiomdl команда
        # Формат: studiomdl.exe -game <game_dir> -nop4 -nopack <qc_file>
        # или: studiomdl.exe -gameinfo <gameinfo_path> -nop4 -nopack <qc_file>
        
        # Определяем, это папка игры или gameinfo.txt
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
        # Нужно найти базовое имя модели из QC файла (читаем $modelname)
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
        
        # Определяем путь, где studiomdl создал файлы
        # game_dir_or_gameinfo - это tf_dir (например, D:\Steam\steamapps\common\Team Fortress 2\tf)
        # studiomdl компилирует в: <tf_dir>/models/workshop_partner/weapons/c_models/<weapon_key>/
        if os.path.isdir(game_dir_or_gameinfo):
            tf_dir = game_dir_or_gameinfo
        else:
            # Если это gameinfo.txt, берем родительскую директорию
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
        
        print(f"[DEBUG] Ищем скомпилированные файлы в: {model_dir_in_tf}")
        print(f"[DEBUG] Копируем в: {out_dir}")
        print(f"[DEBUG] Базовое имя модели: {qc_basename}")
        
        if not os.path.exists(model_dir_in_tf):
            raise RuntimeError(
                f"Папка с скомпилированными файлами не найдена: {model_dir_in_tf}\n"
                f"STDOUT: {result.stdout}\n"
                f"STDERR: {result.stderr}"
            )
        
        # Копируем только файлы модели, которые начинаются с qc_basename
        # Это предотвращает копирование файлов других моделей (например, bat при компиляции scattergun)
        for file_name in os.listdir(model_dir_in_tf):
            # Проверяем, что файл начинается с qc_basename (имя модели из QC)
            if file_name.startswith(qc_basename):
                src = os.path.join(model_dir_in_tf, file_name)
                if os.path.isfile(src):
                    dst = os.path.join(out_dir, file_name)
                    shutil.copy2(src, dst)
                    copied_files.append(file_name)
                    if file_name.endswith('.mdl'):
                        mdl_found = True
                    print(f"[DEBUG] Скопирован файл модели из TF2: {file_name} -> {dst}")
        
        print(f"[DEBUG] Всего скопировано файлов: {len(copied_files)}")
        print(f"[DEBUG] Список скопированных файлов: {copied_files}")
        
        if not mdl_found:
            raise RuntimeError(
                f".mdl файл не найден после компила в {model_dir_in_tf}\n"
                f"Найденные файлы в папке: {os.listdir(model_dir_in_tf) if os.path.exists(model_dir_in_tf) else 'папка не существует'}\n"
                f"STDOUT: {result.stdout}\n"
                f"STDERR: {result.stderr}"
            )

