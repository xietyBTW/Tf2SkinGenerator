#!/usr/bin/env python3

import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.shared.logging_config import setup_logging
from src.shared.constants import DirectoryPaths

# В frozen-режиме __file__ указывает внутрь _internal/ — лог пишем рядом с .exe
if getattr(sys, 'frozen', False):
    _log_dir = Path(sys.executable).parent
else:
    _log_dir = Path(os.path.dirname(os.path.abspath(__file__)))
_log_file = _log_dir / "tf2sg.log"

logger = setup_logging(
    log_level="INFO",
    console_output=True,
    log_file=_log_file,
)


def _make_splash(app):
    """Создаёт и показывает сплэш-экран."""
    from PySide6.QtWidgets import QSplashScreen
    from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QPen
    from PySide6.QtCore import Qt

    W, H = 420, 220

    # Рисуем сплэш вручную
    pixmap = QPixmap(W, H)
    pixmap.fill(QColor("#111111"))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    # Рамка
    painter.setPen(QPen(QColor("#2a2a2a"), 1))
    painter.drawRect(0, 0, W - 1, H - 1)

    # Оранжевая полоска сверху
    painter.fillRect(0, 0, W, 3, QColor("#cc5522"))

    # Название приложения
    font = QFont("Segoe UI", 22, QFont.Weight.Bold)
    painter.setFont(font)
    painter.setPen(QColor("#eeeeee"))
    painter.drawText(0, 50, W, 40, Qt.AlignCenter, "TF2 Skin Generator")

    # Версия
    from src.shared.version import __version__
    font_ver = QFont("Segoe UI", 10, QFont.Weight.Normal)
    painter.setFont(font_ver)
    painter.setPen(QColor("#555555"))
    painter.drawText(0, 88, W, 24, Qt.AlignCenter, f"v{__version__}")

    painter.end()

    splash = QSplashScreen(pixmap, Qt.WindowStaysOnTopHint)
    splash.setFont(QFont("Segoe UI", 9))
    splash.show()
    app.processEvents()
    return splash


def _splash_msg(splash, app, text: str):
    """Обновляет статус на сплэше."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor
    splash.showMessage(
        f"  {text}",
        Qt.AlignBottom | Qt.AlignLeft,
        QColor("#666666"),
    )
    app.processEvents()


def main():
    logger.info("Запуск TF2 Skin Generator")

    try:
        from src.core.app_factory import AppFactory

        DirectoryPaths.ensure_exists()

        # ── Создаём приложение и сразу показываем сплэш ──────────────────── #
        app = AppFactory.create_app(apply_theme=True)
        splash = _make_splash(app)

        # ── Тяжёлые импорты с обновлением статуса ────────────────────────── #
        _splash_msg(splash, app, "Loading modules...")

        from src.ui.main_window import MainWindow

        _splash_msg(splash, app, "Initializing interface...")

        window = MainWindow()

        _splash_msg(splash, app, "Starting...")

        window.show()
        splash.finish(window)   # закрываем сплэш как только окно готово

        logger.info("Приложение успешно запущено")

        sys.exit(app.exec())

    except Exception as e:
        logger.critical(f"Критическая ошибка при запуске: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
