"""
Утилиты для работы с путями TF2
"""

import os
from typing import Tuple, Optional


class TF2Paths:
    """Класс для разрешения путей TF2"""
    
    CROWBAR_PATH = "tools/crowbar/CrowbarCommandLineDecomp.exe"
    
    @staticmethod
    def resolve(tf2_root_dir: str) -> Tuple[str, str, str]:
        """
        Разрешает пути к необходимым файлам TF2
        
        Args:
            tf2_root_dir: Корневая директория TF2 (steamapps/common/Team Fortress 2)
            
        Returns:
            Tuple[studiomdl_exe, tf2_misc_dir_vpk, tf_dir]
            
        Raises:
            FileNotFoundError: Если какой-то файл не найден
        """
        if not os.path.exists(tf2_root_dir):
            raise FileNotFoundError(f"TF2 корневая директория не найдена: {tf2_root_dir}")
        
        # Путь к studiomdl.exe
        studiomdl_exe = os.path.join(tf2_root_dir, "bin", "studiomdl.exe")
        if not os.path.exists(studiomdl_exe):
            raise FileNotFoundError(
                f"studiomdl.exe не найден по пути: {studiomdl_exe}\n"
                f"Ожидаемый путь: <tf2_root_dir>\\bin\\studiomdl.exe"
            )
        
        # Путь к tf2_misc_dir.vpk
        tf_dir = os.path.join(tf2_root_dir, "tf")
        tf2_misc_dir_vpk = os.path.join(tf_dir, "tf2_misc_dir.vpk")
        if not os.path.exists(tf2_misc_dir_vpk):
            raise FileNotFoundError(
                f"tf2_misc_dir.vpk не найден по пути: {tf2_misc_dir_vpk}\n"
                f"Ожидаемый путь: <tf2_root_dir>\\tf\\tf2_misc_dir.vpk"
            )
        
        # Путь к tf2_textures_dir.vpk (для извлечения VMT файлов)
        tf2_textures_dir_vpk = os.path.join(tf_dir, "tf2_textures_dir.vpk")
        # Проверяем наличие, но не выбрасываем ошибку если не найден (может быть в другом месте)
        
        return studiomdl_exe, tf2_misc_dir_vpk, tf_dir
    
    @staticmethod
    def resolve_textures_vpk(tf2_root_dir: str) -> Optional[str]:
        """
        Разрешает путь к tf2_textures_dir.vpk для извлечения VMT файлов
        
        Args:
            tf2_root_dir: Корневая директория TF2
            
        Returns:
            Путь к tf2_textures_dir.vpk или None если не найден
        """
        if not os.path.exists(tf2_root_dir):
            return None
        
        tf_dir = os.path.join(tf2_root_dir, "tf")
        tf2_textures_dir_vpk = os.path.join(tf_dir, "tf2_textures_dir.vpk")
        if os.path.exists(tf2_textures_dir_vpk):
            return tf2_textures_dir_vpk
        
        return None
    
    @staticmethod
    def get_crowbar_path() -> str:
        """
        Возвращает путь к Crowbar CLI
        
        Returns:
            Путь к CrowbarCommandLineDecomp.exe
        """
        return TF2Paths.CROWBAR_PATH
    
    @staticmethod
    def check_crowbar() -> Tuple[bool, Optional[str]]:
        """
        Проверяет наличие Crowbar CLI
        
        Returns:
            Tuple[exists, error_message]
        """
        crowbar_path = TF2Paths.get_crowbar_path()
        if not os.path.exists(crowbar_path):
            return False, f"Crowbar CLI missing: {crowbar_path}"
        return True, None

