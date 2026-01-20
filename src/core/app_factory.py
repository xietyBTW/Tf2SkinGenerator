import sys
import os
from pathlib import Path
from typing import Optional
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from src.utils.themes import apply_theme
from src.config.app_config import AppConfig
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class AppFactory:
    @staticmethod
    def setup_working_directory() -> None:
        if getattr(sys, 'frozen', False):
            os.chdir(os.path.dirname(sys.executable))
            logger.debug(f"Установлена рабочая директория (frozen): {os.getcwd()}")
        else:
            base_dir = Path(__file__).parent.parent.parent
            os.chdir(str(base_dir))
            logger.debug(f"Установлена рабочая директория: {os.getcwd()}")
    
    @staticmethod
    def get_icon_path() -> Optional[Path]:
        if getattr(sys, 'frozen', False):
            base_path = Path(sys.executable).parent if hasattr(sys, '_MEIPASS') else Path(sys.executable).parent
            
            frozen_paths = [
                base_path / "icon.ico",
                base_path / "installer" / "assets" / "icon.ico",
            ]
            
            if hasattr(sys, '_MEIPASS'):
                temp_path = Path(sys._MEIPASS)
                frozen_paths.insert(0, temp_path / "installer" / "assets" / "icon.ico")
            
            for icon_path in frozen_paths:
                if icon_path.exists():
                    return icon_path
        
        base_dir = Path(__file__).parent.parent.parent
        dev_paths = [
            base_dir / "installer" / "assets" / "icon.ico",
            Path("installer/assets/icon.ico"),
        ]
        
        for icon_path in dev_paths:
            if icon_path.exists():
                return icon_path
        
        return None
    
    @staticmethod
    def create_app(apply_theme: bool = True) -> QApplication:
        AppFactory.setup_working_directory()
        
        app = QApplication(sys.argv)
        logger.info("QApplication создан")
        
        icon_path = AppFactory.get_icon_path()
        if icon_path:
            app.setWindowIcon(QIcon(str(icon_path)))
            logger.debug(f"Установлена иконка приложения: {icon_path}")
        else:
            logger.warning("Иконка приложения не найдена")
        
        if apply_theme:
            AppFactory._apply_theme(app)
        
        return app
    
    @staticmethod
    def _apply_theme(app: QApplication) -> None:
        config = AppConfig.load_config()
        theme_name = config.get('theme', 'dark')
        
        if theme_name not in ['dark', 'blue']:
            theme_name = 'dark'
            logger.warning(f"Неизвестная тема в конфиге, используется темная")
        
        logger.info(f"Применяется тема: {theme_name}")
        apply_theme(app, theme_name)

