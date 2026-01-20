"""
Сервис для объединения нескольких VPK файлов в один
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Tuple, Set, Dict
from src.shared.logging_config import get_logger
from src.shared.constants import ToolPaths, DirectoryPaths
from src.shared.file_utils import ensure_directory_exists, copy_file_safe
from src.shared.exceptions import VPKCreationError

logger = get_logger(__name__)

try:
    import vpk
    VPK_AVAILABLE = True
except ImportError:
    VPK_AVAILABLE = False
    vpk = None


class MergeVPKService:
    """Сервис для объединения VPK файлов"""
    
    @staticmethod
    def check_duplicate_weapons(vpk_files: List[Path]) -> Dict[str, List[str]]:
        """
        Проверяет наличие дубликатов оружий в VPK файлах
        
        Args:
            vpk_files: Список путей к VPK файлам
            
        Returns:
            Словарь {weapon_name: [vpk_file1, vpk_file2, ...]} с оружиями, найденными в нескольких VPK
        """
        if not VPK_AVAILABLE:
            return {}
        
        # Словарь для хранения оружий и VPK файлов, в которых они найдены
        weapon_to_vpk: Dict[str, List[str]] = {}
        
        for vpk_file in vpk_files:
            if not vpk_file.exists():
                continue
            
            try:
                vpk_archive = vpk.open(str(vpk_file))
                
                # Проходим по всем файлам в VPK
                for file_path in vpk_archive:
                    # Ищем файлы моделей (.mdl)
                    if file_path.lower().endswith('.mdl'):
                        # Извлекаем имя оружия из пути
                        weapon_name = MergeVPKService._extract_weapon_name(file_path)
                        if weapon_name:
                            if weapon_name not in weapon_to_vpk:
                                weapon_to_vpk[weapon_name] = []
                            if vpk_file.name not in weapon_to_vpk[weapon_name]:
                                weapon_to_vpk[weapon_name].append(vpk_file.name)
                
            except Exception as e:
                logger.warning(f"Ошибка при проверке {vpk_file.name}: {e}", exc_info=True)
                continue
        
        # Фильтруем только оружия, найденные в нескольких VPK
        duplicates = {weapon: vpk_list for weapon, vpk_list in weapon_to_vpk.items() if len(vpk_list) > 1}
        
        return duplicates
    
    @staticmethod
    def _extract_weapon_name(file_path: str) -> str:
        """
        Извлекает имя оружия из пути к MDL файлу
        
        Примеры:
            models/weapons/c_models/c_scattergun/c_scattergun.mdl -> c_scattergun
            models/workshop_partner/weapons/c_models/c_scattergun.mdl -> c_scattergun
            materials/models/weapons/c_models/c_scattergun.mdl -> c_scattergun
        
        Args:
            file_path: Путь к MDL файлу
            
        Returns:
            Имя оружия или None
        """
        # Нормализуем путь
        path = file_path.replace('\\', '/').lower()
        
        # Убираем расширение .mdl
        if not path.endswith('.mdl'):
            return None
        
        path = path[:-4]  # Убираем .mdl
        
        # Разбиваем путь на части
        parts = path.split('/')
        
        # Ищем имя файла (обычно последняя часть пути)
        if not parts:
            return None
        
        filename = parts[-1]
        
        # Имя оружия обычно начинается с c_ или v_
        if filename.startswith('c_') or filename.startswith('v_'):
            return filename
        
        # Если это не так, пытаемся найти оружие в пути
        # Ищем части пути, которые могут быть именами оружий
        for part in reversed(parts):
            if part.startswith('c_') or part.startswith('v_'):
                return part
        
        return None
    
    @staticmethod
    def merge_vpk_files(
        vpk_files: List[Path],
        output_filename: str,
        export_folder: str = "export",
        language: str = "en"
    ) -> Tuple[bool, str]:
        """
        Объединяет несколько VPK файлов в один
        
        Args:
            vpk_files: Список путей к VPK файлам для объединения
            output_filename: Имя выходного VPK файла
            export_folder: Папка для экспорта
            language: Язык для сообщений об ошибках
            
        Returns:
            Tuple[success, message]
        """
        from src.data.translations import TRANSLATIONS
        t = TRANSLATIONS.get(language, TRANSLATIONS['en'])
        
        if not VPK_AVAILABLE:
            return False, t.get('vpk_library_not_available', 'VPK library not available')
        
        if not vpk_files:
            return False, t.get('no_vpk_files_selected', 'No VPK files selected')
        
        # Проверяем существование всех файлов
        for vpk_file in vpk_files:
            if not vpk_file.exists():
                return False, t.get('vpk_file_not_found', 'VPK file not found: {path}').format(path=vpk_file)
        
        # Создаем временную директорию для объединения
        import time
        temp_dir = DirectoryPaths.BASE_TEMP_DIR / f"merge_{int(time.time())}"
        merged_root = temp_dir / "vpkroot"
        
        try:
            ensure_directory_exists(merged_root)
            
            # Извлекаем и объединяем каждый VPK
            logger.info(f"Начинаем объединение {len(vpk_files)} VPK файлов")
            
            for i, vpk_file in enumerate(vpk_files, 1):
                logger.info(f"[{i}/{len(vpk_files)}] Обрабатываем: {vpk_file.name}")
                
                # Извлекаем содержимое VPK во временную папку
                extract_dir = temp_dir / f"extract_{i}"
                ensure_directory_exists(extract_dir)
                
                try:
                    # Открываем VPK файл
                    vpk_archive = vpk.open(str(vpk_file))
                    
                    # Извлекаем все файлы
                    for file_path in vpk_archive:
                        # Получаем содержимое файла
                        file_data = vpk_archive[file_path].read()
                        
                        # Создаем путь в извлеченной директории
                        extract_file_path = extract_dir / file_path
                        ensure_directory_exists(extract_file_path.parent)
                        
                        # Записываем файл
                        with open(extract_file_path, 'wb') as f:
                            f.write(file_data)
                    
                    # Объединяем извлеченные файлы в merged_root
                    MergeVPKService._merge_directory(extract_dir, merged_root)
                    
                    logger.info(f"Файлы из {vpk_file.name} объединены")
                    
                except Exception as e:
                    logger.error(f"Ошибка при извлечении {vpk_file.name}: {e}", exc_info=True)
                    return False, t.get('error_extracting_vpk', 'Error extracting VPK: {file}').format(file=vpk_file.name)
            
            # Создаем новый VPK из объединенной папки
            logger.info("Создаем объединенный VPK файл...")
            vpk_path = MergeVPKService._create_vpk_from_directory(merged_root, output_filename, export_folder, language)
            
            if not vpk_path:
                return False, t.get('error_creating_merged_vpk', 'Error creating merged VPK file')
            
            # Очищаем временные файлы
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                logger.warning(f"Не удалось удалить временную директорию: {e}")
            
            success_msg = t.get('merge_vpk_success', 'VPK files successfully merged: {path}').format(path=vpk_path)
            return True, success_msg
            
        except Exception as e:
            logger.error(f"Ошибка при объединении VPK: {e}", exc_info=True)
            # Пытаемся очистить временные файлы
            try:
                if temp_dir.exists():
                    shutil.rmtree(temp_dir)
            except:
                pass
            return False, t.get('error_merging_vpk', 'Error merging VPK files: {error}').format(error=str(e))
    
    @staticmethod
    def _merge_directory(source_dir: Path, target_dir: Path):
        """
        Объединяет содержимое source_dir в target_dir
        
        Если папки с одинаковыми именами существуют, они объединяются рекурсивно.
        Если файлы с одинаковыми именами существуют, они не перезаписываются (оставляем оба).
        
        Args:
            source_dir: Исходная директория
            target_dir: Целевая директория
        """
        if not source_dir.exists():
            return
        
        # Проходим по всем элементам в исходной директории
        for root, dirs, files in os.walk(source_dir):
            # Получаем относительный путь от source_dir
            rel_root = Path(root).relative_to(source_dir)
            target_root = target_dir / rel_root
            
            # Создаем директорию в целевой папке
            ensure_directory_exists(target_root)
            
            # Копируем файлы
            for file_name in files:
                source_file = Path(root) / file_name
                target_file = target_root / file_name
                
                # Если файл уже существует, создаем уникальное имя
                if target_file.exists():
                    # Добавляем суффикс к имени файла
                    stem = target_file.stem
                    suffix = target_file.suffix
                    counter = 1
                    
                    while target_file.exists():
                        new_name = f"{stem}_{counter}{suffix}"
                        target_file = target_root / new_name
                        counter += 1
                    
                    logger.debug(f"Файл {rel_root / file_name} уже существует, переименован в {target_file.name}")
                
                # Копируем файл
                copy_file_safe(source_file, target_file)
    
    @staticmethod
    def _create_vpk_from_directory(
        vpkroot_dir: Path,
        filename: str,
        export_folder: str = "export",
        language: str = "en"
    ) -> str:
        """
        Создает VPK файл из директории vpkroot
        
        Args:
            vpkroot_dir: Директория с содержимым для упаковки
            filename: Имя выходного файла
            export_folder: Папка для экспорта
            language: Язык для сообщений об ошибках
            
        Returns:
            Путь к созданному VPK файлу или None при ошибке
        """
        from src.data.translations import TRANSLATIONS
        t = TRANSLATIONS.get(language, TRANSLATIONS['en'])
        
        # vpk.exe создает файл с именем папки, т.е. vpkroot.vpk
        # Файл создается в директории vpkroot_dir (в родительской папке)
        vpkroot_parent = vpkroot_dir.parent
        temp_vpk_path = vpkroot_parent / "vpkroot.vpk"
        
        # Удаляем существующий VPK если есть
        if temp_vpk_path.exists():
            temp_vpk_path.unlink()
        
        # Создаем VPK
        logger.info("Запуск vpk.exe для создания объединенного VPK...")
        result = subprocess.run([
            str(ToolPaths.get_vpk_tool()),
            "-v", str(vpkroot_dir.resolve())
        ], cwd=str(vpkroot_parent), capture_output=True, text=True)
        
        logger.debug(f"vpk.exe завершился с кодом: {result.returncode}")
        if result.stdout:
            logger.debug(f"STDOUT: {result.stdout}")
        if result.stderr:
            logger.debug(f"STDERR: {result.stderr}")
        
        if result.returncode != 0:
            error_msg = t.get('error_vpk_creation_failed', 'VPK creation failed').format(
                stdout=result.stdout,
                stderr=result.stderr
            )
            logger.error(f"Ошибка создания VPK: {error_msg}")
            raise VPKCreationError(result.stdout, result.stderr)
        
        if not temp_vpk_path.exists():
            error_msg = t.get('error_vpkroot_not_found', 'VPK file not found after creation').format(path=vpkroot_parent)
            logger.error(error_msg)
            raise FileNotFoundError(temp_vpk_path, error_msg)
        
        # Перемещаем в export
        export_folder_path = Path(export_folder)
        ensure_directory_exists(export_folder_path)
        final_output = export_folder_path / filename
        if final_output.exists():
            final_output.unlink()
        shutil.move(str(temp_vpk_path), str(final_output))
        
        logger.info(f"Объединенный VPK успешно создан: {final_output}")
        return str(final_output)
