"""
Контекст сборки для управления временными путями
"""

import os
import shutil
from dataclasses import dataclass
from typing import Optional
import time


@dataclass
class BuildContext:
    """Контекст сборки с временными путями"""
    
    build_id: str
    mode: str
    weapon_key: str
    temp_dir: str
    
    @property
    def vpkroot_dir(self) -> str:
        """Корень VPK для упаковки"""
        return os.path.join(self.temp_dir, "vpkroot")
    
    @property
    def extract_dir(self) -> str:
        """Директория для извлечения файлов из VPK"""
        return os.path.join(self.temp_dir, "extract")
    
    @property
    def decompile_dir(self) -> str:
        """Директория для декомпилированных файлов"""
        return os.path.join(self.temp_dir, "decompile")
    
    @property
    def compile_dir(self) -> str:
        """Директория для скомпилированных файлов"""
        return os.path.join(self.temp_dir, "compile_out")
    
    @property
    def logs_dir(self) -> str:
        """Директория для логов"""
        return os.path.join(self.temp_dir, "logs")
    
    @property
    def debug_dir(self) -> str:
        """Директория для отладки (если включен режим отладки)"""
        return os.path.join(self.temp_dir, "debug")
    
    @property
    def debug_stage1_extracted_dir(self) -> str:
        """Папка отладки: после извлечения MDL"""
        return os.path.join(self.debug_dir, "01_extracted")
    
    @property
    def debug_stage2_decompiled_dir(self) -> str:
        """Папка отладки: после декомпиляции"""
        return os.path.join(self.debug_dir, "02_decompiled")
    
    @property
    def debug_stage3_patched_dir(self) -> str:
        """Папка отладки: после редактирования (патчинга)"""
        return os.path.join(self.debug_dir, "03_patched")
    
    @property
    def debug_stage4_compiled_dir(self) -> str:
        """Папка отладки: после компиляции"""
        return os.path.join(self.debug_dir, "04_compiled")
    
    def create_directories(self, debug_mode: bool = False):
        """Создает все необходимые директории"""
        os.makedirs(self.vpkroot_dir, exist_ok=True)
        os.makedirs(self.extract_dir, exist_ok=True)
        os.makedirs(self.decompile_dir, exist_ok=True)
        os.makedirs(self.compile_dir, exist_ok=True)
        os.makedirs(self.logs_dir, exist_ok=True)
        
        if debug_mode:
            os.makedirs(self.debug_dir, exist_ok=True)
            os.makedirs(self.debug_stage1_extracted_dir, exist_ok=True)
            os.makedirs(self.debug_stage2_decompiled_dir, exist_ok=True)
            os.makedirs(self.debug_stage3_patched_dir, exist_ok=True)
            os.makedirs(self.debug_stage4_compiled_dir, exist_ok=True)
    
    def cleanup(self, on_error: bool = False, keep_on_error: bool = False, debug_mode: bool = False):
        """
        Удаляет временную папку
        
        Args:
            on_error: True если очистка происходит после ошибки
            keep_on_error: True если нужно сохранить файлы при ошибке
            debug_mode: True если включен режим отладки (сохраняет файлы даже при успехе)
        """
        if debug_mode:
            # В режиме отладки всегда сохраняем файлы
            return
        
        if on_error and keep_on_error:
            # Сохраняем при ошибке если включено
            return
        
        # Удаляем временную папку
        if os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
            except Exception as e:
                print(f"Предупреждение: Не удалось удалить временную папку {self.temp_dir}: {e}")
    
    @staticmethod
    def create(mode: str, weapon_key: str, base_temp_dir: str = "tools/temp", debug_mode: bool = False) -> 'BuildContext':
        """
        Создает новый контекст сборки
        
        Args:
            mode: Режим оружия
            weapon_key: Ключ оружия
            base_temp_dir: Базовая директория для временных файлов
            
        Returns:
            BuildContext: Новый контекст сборки
        """
        timestamp = int(time.time())
        build_id = f"build_{timestamp}_{mode}"
        temp_dir = os.path.join(base_temp_dir, build_id)
        
        ctx = BuildContext(
            build_id=build_id,
            mode=mode,
            weapon_key=weapon_key,
            temp_dir=temp_dir
        )
        
        ctx.create_directories(debug_mode=debug_mode)
        
        return ctx

