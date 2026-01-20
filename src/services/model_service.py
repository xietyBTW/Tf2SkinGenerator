"""
Сервис для работы с файлами модели оружия TF2
"""

import os
import sys
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from src.data.weapons import SPECIAL_MODES
from src.shared.logging_config import get_logger
from src.shared.file_utils import ensure_directory_exists

logger = get_logger(__name__)


class ModelService:
    """Сервис для работы с файлами модели оружия"""
    
    # Базовый путь к файлам модели
    MODELS_BASE_PATH = "tools/c_models"
    
    @staticmethod
    def _resolve_path(relative_path: str) -> str:
        """
        Разрешает относительный путь, работая как в frozen приложении, так и в обычном
        
        Args:
            relative_path: Относительный путь (например, "tools/c_models")
            
        Returns:
            Абсолютный путь (для надежности в обоих режимах)
        """
        if getattr(sys, 'frozen', False):
            # Запуск из собранного исполняемого файла
            # Рабочая директория уже установлена в папку с exe через AppFactory
            base_dir = os.path.dirname(sys.executable)
        else:
            # Обычный запуск из исходников
            # Рабочая директория уже установлена в корень проекта через AppFactory.setup_working_directory()
            # Используем текущую рабочую директорию (которая должна быть корнем проекта)
            base_dir = os.getcwd()
        
        resolved_path = os.path.join(base_dir, relative_path)
        return os.path.normpath(os.path.abspath(resolved_path))
    
    @staticmethod
    def get_models_base_path() -> str:
        """
        Возвращает правильный путь к базовой директории моделей
        Работает как в frozen приложении, так и в обычном
        
        Returns:
            Путь к tools/c_models (абсолютный для frozen, относительный для обычного)
        """
        return ModelService._resolve_path(ModelService.MODELS_BASE_PATH)
    
    # Расширения файлов модели
    MODEL_EXTENSIONS = ['.mdl', '.vtx', '.vvd', '.phy']
    VTX_VARIANTS = ['dx80', 'dx90', 'sw']
    
    # Приписки, которые нужно игнорировать
    IGNORED_SUFFIXES = ['_xmas', '_festivizer', '_festive', '_christmas', '_holiday']
    
    @staticmethod
    def get_available_weapons() -> List[str]:
        """
        Возвращает список доступных оружий с файлами модели
        
        Returns:
            List[str]: Список ключей оружия
        """
        available_weapons = []
        
        models_path = ModelService.get_models_base_path()
        logger.debug(f"Ищем модели в: {models_path}")
        
        if not os.path.exists(models_path):
            logger.warning(f"Папка моделей не найдена: {models_path}")
            return available_weapons
        
        for item in os.listdir(models_path):
            item_path = os.path.join(models_path, item)
            
            # Проверяем, что это папка
            if not os.path.isdir(item_path):
                continue
            
            # Игнорируем файлы с нежелательными приписками
            if ModelService._should_ignore_weapon(item):
                continue
            
            # Проверяем, что в папке есть файлы модели
            if ModelService._has_model_files(item):
                available_weapons.append(item)
        
        return sorted(available_weapons)
    
    @staticmethod
    def _should_ignore_weapon(weapon_name: str) -> bool:
        """
        Проверяет, нужно ли игнорировать оружие
        
        Args:
            weapon_name: Название оружия
            
        Returns:
            bool: True если нужно игнорировать
        """
        weapon_lower = weapon_name.lower()
        
        # Игнорируем файлы с нежелательными приписками
        for suffix in ModelService.IGNORED_SUFFIXES:
            if suffix in weapon_lower:
                return True
        
        # Игнорируем файлы анимаций и рук
        if any(part in weapon_lower for part in ['_animations', '_arms', '_watch']):
            return True
        
        return False
    
    @staticmethod
    def _has_model_files(weapon_name: str) -> bool:
        """
        Проверяет, есть ли в папке файлы модели
        
        Args:
            weapon_name: Название оружия
            
        Returns:
            bool: True если есть файлы модели
        """
        models_path = ModelService.get_models_base_path()
        weapon_path = os.path.join(models_path, weapon_name)
        
        if not os.path.exists(weapon_path):
            return False
        
        # Проверяем наличие основных файлов модели
        required_files = [
            f"{weapon_name}.mdl",
            f"{weapon_name}.vvd",
            f"{weapon_name}.phy"
        ]
        
        # Проверяем наличие хотя бы одного VTX файла
        vtx_files = [
            f"{weapon_name}.dx80.vtx",
            f"{weapon_name}.dx90.vtx", 
            f"{weapon_name}.sw.vtx"
        ]
        
        has_required = any(os.path.exists(os.path.join(weapon_path, f)) for f in required_files)
        has_vtx = any(os.path.exists(os.path.join(weapon_path, f)) for f in vtx_files)
        
        return has_required and has_vtx
    
    @staticmethod
    def get_weapon_model_files(weapon_key: str) -> Dict[str, str]:
        """
        Возвращает пути к файлам модели для конкретного оружия
        
        Args:
            weapon_key: Ключ оружия (например, 'c_shogun_kunai')
            
        Returns:
            Dict с путями к файлам модели
        """
        model_files = {}
        
        models_path = ModelService.get_models_base_path()
        weapon_path = os.path.join(models_path, weapon_key)
        
        logger.debug(f"Ищем файлы модели для {weapon_key} в: {weapon_path}")
        
        if not os.path.exists(weapon_path):
            logger.warning(f"Папка модели не найдена для {weapon_key} по пути: {weapon_path}")
            logger.debug(f"Текущая рабочая директория: {os.getcwd()}")
            return model_files
        
        # Сканируем файлы в папке
        for file_name in os.listdir(weapon_path):
            file_path = os.path.join(weapon_path, file_name)
            
            if os.path.isfile(file_path):
                # Проверяем, что это файл модели
                if ModelService._is_model_file(file_name, weapon_key):
                    model_files[file_name] = file_path
        
        return model_files
    
    @staticmethod
    def _is_model_file(file_name: str, weapon_key: str) -> bool:
        """
        Проверяет, является ли файл файлом модели
        
        Args:
            file_name: Имя файла
            weapon_key: Ключ оружия
            
        Returns:
            bool: True если это файл модели
        """
        # Файл должен начинаться с названия оружия
        if not file_name.startswith(weapon_key):
            return False
        
        # Проверяем расширение
        for ext in ModelService.MODEL_EXTENSIONS:
            if file_name.endswith(ext):
                return True
        
        return False
    
    @staticmethod
    def copy_model_files_to_vpk(weapon_key: str, vpk_root_path: str) -> bool:
        """
        Копирует файлы модели в VPK директорию
        
        Args:
            weapon_key: Ключ оружия
            vpk_root_path: Путь к корню VPK
            
        Returns:
            bool: True если успешно скопированы
        """
        try:
            # Получаем файлы модели
            model_files = ModelService.get_weapon_model_files(weapon_key)
            
            if not model_files:
                logger.warning(f"Файлы модели не найдены для {weapon_key}")
                return False
            
            # Создаем целевую директорию
            target_dir = os.path.join(vpk_root_path, "models", "workshop_partner", "weapons", "c_models", weapon_key)
            logger.debug(f"Создаем директорию: {target_dir}")
            os.makedirs(target_dir, exist_ok=True)
            
            # Копируем файлы
            copied_count = 0
            for file_name, source_path in model_files.items():
                target_path = os.path.join(target_dir, file_name)
                shutil.copy2(source_path, target_path)
                copied_count += 1
                logger.debug(f"Скопирован файл модели: {file_name}")
            
            logger.info(f"Скопировано {copied_count} файлов модели для {weapon_key}")
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при копировании файлов модели: {e}", exc_info=True)
            return False
    
    @staticmethod
    def validate_model_files(weapon_key: str) -> Dict[str, bool]:
        """
        Проверяет наличие всех необходимых файлов модели
        
        Args:
            weapon_key: Ключ оружия
            
        Returns:
            Dict с результатами проверки каждого типа файла
        """
        validation = {
            'mdl': False,
            'vvd': False,
            'phy': False,
            'vtx_dx80': False,
            'vtx_dx90': False,
            'vtx_sw': False
        }
        
        model_files = ModelService.get_weapon_model_files(weapon_key)
        
        for file_name in model_files.keys():
            if file_name.endswith('.mdl'):
                validation['mdl'] = True
            elif file_name.endswith('.vvd'):
                validation['vvd'] = True
            elif file_name.endswith('.phy'):
                validation['phy'] = True
            elif file_name.endswith('.dx80.vtx'):
                validation['vtx_dx80'] = True
            elif file_name.endswith('.dx90.vtx'):
                validation['vtx_dx90'] = True
            elif file_name.endswith('.sw.vtx'):
                validation['vtx_sw'] = True
        
        return validation
    
    @staticmethod
    def get_model_file_info(weapon_key: str) -> Dict[str, Dict[str, any]]:
        """
        Возвращает подробную информацию о файлах модели
        
        Args:
            weapon_key: Ключ оружия
            
        Returns:
            Dict с информацией о файлах
        """
        model_files = ModelService.get_weapon_model_files(weapon_key)
        file_info = {}
        
        for file_name, file_path in model_files.items():
            try:
                stat = os.stat(file_path)
                file_info[file_name] = {
                    'path': file_path,
                    'size': stat.st_size,
                    'extension': os.path.splitext(file_name)[1],
                    'type': ModelService._get_file_type(file_name)
                }
            except Exception as e:
                logger.warning(f"Ошибка при получении информации о файле {file_name}: {e}", exc_info=True)
        
        return file_info
    
    @staticmethod
    def _get_file_type(file_name: str) -> str:
        """
        Определяет тип файла модели
        
        Args:
            file_name: Имя файла
            
        Returns:
            str: Тип файла
        """
        if file_name.endswith('.mdl'):
            return 'Model'
        elif file_name.endswith('.vvd'):
            return 'Vertex Animation'
        elif file_name.endswith('.phy'):
            return 'Physics'
        elif file_name.endswith('.vtx'):
            if 'dx80' in file_name:
                return 'Vertex Data (DX8)'
            elif 'dx90' in file_name:
                return 'Vertex Data (DX9)'
            elif 'sw' in file_name:
                return 'Vertex Data (Software)'
            else:
                return 'Vertex Data'
        else:
            return 'Unknown'
