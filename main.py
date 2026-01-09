#!/usr/bin/env python3
"""
TF2 Skin Generator - Главный файл приложения
"""

import sys
import os

# Добавляем src в путь для импорта
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.ui.main_window import MainWindow

def main():
    """Главная функция приложения"""
    from src.core.app_factory import AppFactory
    
    # Создаем и настраиваем приложение
    app = AppFactory.create_app(apply_theme=True)
    
    # Создаем и показываем главное окно
    window = MainWindow()
    window.show()
    
    # Запускаем приложение
    sys.exit(app.exec())

if __name__ == '__main__':
    main()

