"""
Контекст сборки для управления временными путями
"""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import time
from src.shared.logging_config import get_logger
from src.shared.constants import DirectoryPaths
from src.shared.file_utils import ensure_directory_exists, safe_remove

logger = get_logger(__name__)


@dataclass
class BuildContext:
    """Контекст сборки с временными путями"""
    
    build_id: str
    mode: str
    weapon_key: str
    temp_dir: Path
    
    @property
    def vpkroot_dir(self) -> Path:
        """Корень VPK для упаковки"""
        return self.temp_dir / "vpkroot"
    
    @property
    def extract_dir(self) -> Path:
        """Директория для извлечения файлов из VPK"""
        return self.temp_dir / "extract"
    
    @property
    def decompile_dir(self) -> Path:
        """Директория для декомпилированных файлов"""
        return self.temp_dir / "decompile"
    
    @property
    def compile_dir(self) -> Path:
        """Директория для скомпилированных файлов"""
        return self.temp_dir / "compile_out"
    
    @property
    def logs_dir(self) -> Path:
        """Директория для логов"""
        return self.temp_dir / "logs"
    
    @property
    def debug_dir(self) -> Path:
        """Директория для отладки (если включен режим отладки)"""
        return self.temp_dir / "debug"
    
    @property
    def debug_stage1_extracted_dir(self) -> Path:
        """Папка отладки: после извлечения MDL"""
        return self.debug_dir / "01_extracted"
    
    @property
    def debug_stage2_decompiled_dir(self) -> Path:
        """Папка отладки: после декомпиляции"""
        return self.debug_dir / "02_decompiled"
    
    @property
    def debug_stage3_patched_dir(self) -> Path:
        """Папка отладки: после редактирования (патчинга)"""
        return self.debug_dir / "03_patched"
    
    @property
    def debug_stage4_compiled_dir(self) -> Path:
        """Папка отладки: после компиляции"""
        return self.debug_dir / "04_compiled"
    
    def create_directories(self, debug_mode: bool = False) -> None:
        """
        Создает все необходимые директории
        
        Args:
            debug_mode: Включен ли режим отладки
        """
        ensure_directory_exists(self.vpkroot_dir)
        ensure_directory_exists(self.extract_dir)
        ensure_directory_exists(self.decompile_dir)
        ensure_directory_exists(self.compile_dir)
        ensure_directory_exists(self.logs_dir)
        
        if debug_mode:
            ensure_directory_exists(self.debug_dir)
            ensure_directory_exists(self.debug_stage1_extracted_dir)
            ensure_directory_exists(self.debug_stage2_decompiled_dir)
            ensure_directory_exists(self.debug_stage3_patched_dir)
            ensure_directory_exists(self.debug_stage4_compiled_dir)
        
        logger.debug(f"Созданы директории для сборки: {self.temp_dir}")
    
    def cleanup(self, on_error: bool = False, keep_on_error: bool = False, debug_mode: bool = False) -> None:
        """
        Удаляет временную папку
        
        Args:
            on_error: True если очистка происходит после ошибки
            keep_on_error: True если нужно сохранить файлы при ошибке
            debug_mode: True если включен режим отладки (сохраняет файлы даже при успехе)
        """
        if debug_mode:
            # В режиме отладки всегда сохраняем файлы
            logger.debug(f"Режим отладки: временные файлы сохранены в {self.temp_dir}")
            return
        
        if on_error and keep_on_error:
            # Сохраняем при ошибке если включено
            logger.warning(f"Ошибка сборки: временные файлы сохранены в {self.temp_dir}")
            return
        
        # Удаляем временную папку
        if self.temp_dir.exists():
            if safe_remove(self.temp_dir, is_dir=True):
                logger.debug(f"Временная папка удалена: {self.temp_dir}")
            else:
                logger.warning(f"Не удалось удалить временную папку: {self.temp_dir}")
    
    @staticmethod
    def create(
        mode: str,
        weapon_key: str,
        base_temp_dir: Optional[Path] = None,
        debug_mode: bool = False
    ) -> 'BuildContext':
        """
        Создает новый контекст сборки
        
        Args:
            mode: Режим оружия
            weapon_key: Ключ оружия
            base_temp_dir: Базовая директория для временных файлов (если None, используется из констант)
            debug_mode: Включен ли режим отладки
            
        Returns:
            BuildContext: Новый контекст сборки
        """
        if base_temp_dir is None:
            base_temp_dir = DirectoryPaths.BASE_TEMP_DIR
        
        timestamp = int(time.time())
        build_id = f"build_{timestamp}_{mode}"
        temp_dir = base_temp_dir / build_id
        
        ctx = BuildContext(
            build_id=build_id,
            mode=mode,
            weapon_key=weapon_key,
            temp_dir=temp_dir
        )
        
        ctx.create_directories(debug_mode=debug_mode)
        logger.info(f"Создан контекст сборки: {build_id} для режима {mode}")
        
        return ctx

