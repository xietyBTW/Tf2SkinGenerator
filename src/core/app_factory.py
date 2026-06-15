import sys
import os
from pathlib import Path
from typing import Optional
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
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
            base_path = Path(sys.executable).parent

            frozen_paths = [
                base_path / "icon.ico",
                base_path / "installer" / "assets" / "icon.ico",
            ]

            if hasattr(sys, '_MEIPASS'):
                temp_path = Path(sys._MEIPASS)
                # src/static бандлится всегда → кладём иконку туда (надёжный путь),
                # плюс старые пути на случай отдельной поставки icon.ico.
                frozen_paths.insert(0, temp_path / "src" / "static" / "icon.ico")
                frozen_paths.insert(1, temp_path / "installer" / "assets" / "icon.ico")

            for icon_path in frozen_paths:
                if icon_path.exists():
                    return icon_path

        base_dir = Path(__file__).parent.parent.parent
        dev_paths = [
            base_dir / "src" / "static" / "icon.ico",
            base_dir / "installer" / "assets" / "icon.ico",
            Path("installer/assets/icon.ico"),
        ]

        for icon_path in dev_paths:
            if icon_path.exists():
                return icon_path

        return None
    
    @staticmethod
    def _set_windows_app_id() -> None:
        """
        Задаёт явный AppUserModelID (Windows), чтобы панель задач показывала
        иконку окна, а не группировала приложение под дефолтным значком.
        """
        if sys.platform != 'win32':
            return
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "Tf2SkinGenerator.App"
            )
        except Exception as e:
            logger.debug(f"Не удалось задать AppUserModelID: {e}")

    @staticmethod
    def create_app(apply_theme: bool = True) -> QApplication:
        AppFactory.setup_working_directory()
        AppFactory._set_windows_app_id()

        app = QApplication(sys.argv)
        logger.info("QApplication создан")

        # Иконку окна/панели задач задаём из .ico-файла И в dev, И в frozen:
        # QIcon(sys.executable) не умеет извлекать иконку из .exe (PE-ресурс),
        # поэтому окно оставалось без значка, хотя у файла он есть.
        icon_path = AppFactory.get_icon_path()
        if icon_path:
            app.setWindowIcon(QIcon(str(icon_path)))
            logger.debug(f"Установлена иконка приложения: {icon_path}")
        else:
            logger.warning("Иконка приложения (.ico) не найдена — окно без значка")

        if apply_theme:
            AppFactory._apply_theme(app)

        return app
    
    @staticmethod
    def _apply_theme(app: QApplication) -> None:
        from src.utils.themes import apply_theme
        config = AppConfig.load_config()
        theme_name = config.get('theme', 'dark')
        
        if theme_name not in ['dark', 'blue']:
            theme_name = 'dark'
            logger.warning("Неизвестная тема в конфиге, используется темная")
        
        logger.info(f"Применяется тема: {theme_name}")
        apply_theme(app, theme_name)
