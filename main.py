#!/usr/bin/env python3

import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.shared.logging_config import setup_logging
from src.shared.constants import DirectoryPaths

logger = setup_logging(
    log_level="INFO",
    console_output=True
)

from src.ui.main_window import MainWindow

def main():
    logger.info("Запуск TF2 Skin Generator")
    
    try:
        from src.core.app_factory import AppFactory
        
        DirectoryPaths.ensure_exists()
        
        app = AppFactory.create_app(apply_theme=True)
        
        window = MainWindow()
        window.show()
        
        logger.info("Приложение успешно запущено")
        
        sys.exit(app.exec())
    except Exception as e:
        logger.critical(f"Критическая ошибка при запуске: {e}", exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    main()

