"""
Фабрика для создания и настройки приложения
Централизует логику инициализации приложения
"""

import sys
import os
from PySide6.QtWidgets import QApplication
from src.utils.dependencies import QDARKSTYLE_AVAILABLE, qdarkstyle
from src.utils.themes import apply_dark_theme


class AppFactory:
    """Фабрика для создания и настройки Qt приложений"""
    
    @staticmethod
    def setup_working_directory():
        """
        Устанавливает рабочую директорию приложения
        Работает как для frozen (cx_Freeze/PyInstaller) так и для обычного запуска
        """
        if getattr(sys, 'frozen', False):
            # Запуск из собранного исполняемого файла
            os.chdir(os.path.dirname(sys.executable))
        else:
            # Обычный запуск из исходников
            os.chdir(os.path.dirname(os.path.abspath(__file__ + '/../../')))
    
    @staticmethod
    def create_app(apply_theme=True):
        """
        Создает и настраивает QApplication
        
        Args:
            apply_theme: Применять ли темную тему
            
        Returns:
            QApplication: Настроенное приложение
        """
        # Устанавливаем рабочую директорию
        AppFactory.setup_working_directory()
        
        # Создаем приложение
        app = QApplication(sys.argv)
        
        # Применяем тему если требуется
        if apply_theme:
            AppFactory._apply_theme(app)
        
        return app
    
    @staticmethod
    def _apply_theme(app):
        """
        Применяет темную тему к приложению
        Пробует qdarkstyle, если недоступен - использует встроенную тему
        
        Args:
            app: QApplication для применения темы
        """
        if QDARKSTYLE_AVAILABLE:
            try:
                app.setStyleSheet(qdarkstyle.load_stylesheet(qt_api='pyside6'))
                return
            except Exception as e:
                print(f"Ошибка применения qdarkstyle: {e}, используется встроенная тема")
        
        # Fallback на встроенную тему
        print("qdarkstyle не найден, используется встроенная тема")
        apply_dark_theme(app)

