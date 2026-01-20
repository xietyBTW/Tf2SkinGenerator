"""
Темы для приложения - Элегантный минималистичный дизайн
"""

from typing import Dict, Any
from PySide6.QtGui import QColor, QPalette, QFont
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

def apply_dark_theme(app: QApplication) -> None:
    """Применяет элегантную темную тему к приложению"""
    palette = QPalette()
    
    # Основные цвета - глубокие темные тона с элегантностью
    palette.setColor(QPalette.Window, QColor("#0a0a0a"))           # Почти черный
    palette.setColor(QPalette.WindowText, QColor("#ffffff"))       # Чистый белый
    palette.setColor(QPalette.Base, QColor("#1a1a1a"))             # Темно-серый
    palette.setColor(QPalette.AlternateBase, QColor("#2a2a2a"))    # Средне-серый
    palette.setColor(QPalette.ToolTipBase, QColor("#1a1a1a"))
    palette.setColor(QPalette.ToolTipText, QColor("#ffffff"))
    palette.setColor(QPalette.Text, QColor("#ffffff"))
    palette.setColor(QPalette.Button, QColor("#2a2a2a"))
    palette.setColor(QPalette.ButtonText, QColor("#ffffff"))
    palette.setColor(QPalette.BrightText, QColor("#ff4757"))
    palette.setColor(QPalette.Link, QColor("#ff6b35"))             # Теплый оранжевый
    palette.setColor(QPalette.Highlight, QColor("#ff6b35"))
    palette.setColor(QPalette.HighlightedText, QColor("#0a0a0a"))
    
    app.setPalette(palette)

    # Элегантный шрифт
    font = QFont("Inter", 11, QFont.Normal)
    app.setFont(font)

    app.setStyleSheet("""
        QWidget {
            background-color: #0a0a0a;
            color: #ffffff;
            font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
        }
        
        QMainWindow {
            background-color: #0a0a0a;
        }
        
        QLabel {
            color: #ffffff;
            font-size: 13px;
            font-weight: 400;
        }
        
        QComboBox, QLineEdit, QTextEdit {
            background-color: transparent;
            border: none;
            border-bottom: 1px solid #333333;
            color: #ffffff;
            font-size: 14px;
            font-weight: 300;
            padding: 8px 0px;
        }
        
        QComboBox:focus, QLineEdit:focus, QTextEdit:focus {
            border-bottom: 2px solid #ff6b35;
            background-color: rgba(255, 107, 53, 0.05);
        }
        
        QComboBox QAbstractItemView {
            background-color: #1a1a1a;
            color: #ffffff;
            selection-background-color: #ff6b35;
            selection-color: #0a0a0a;
            border: 1px solid #333333;
            border-radius: 0px;
        }
        
        QComboBox::drop-down {
            border: none;
            width: 20px;
        }
        
        QComboBox::down-arrow {
            image: none;
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 6px solid #ffffff;
            margin-right: 8px;
        }
        
        QPushButton {
            background-color: transparent;
            color: #ffffff;
            border: none;
            padding: 12px 24px;
            font-size: 13px;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        QPushButton:hover {
            background-color: rgba(255, 107, 53, 0.1);
            color: #ff6b35;
        }
        
        QPushButton:pressed {
            background-color: rgba(255, 107, 53, 0.2);
        }
        
        QRadioButton {
            spacing: 12px;
            color: #ffffff;
            font-size: 13px;
            font-weight: 300;
        }
        
        QRadioButton::indicator {
            width: 18px;
            height: 18px;
            border-radius: 9px;
            border: 2px solid #333333;
            background-color: transparent;
        }
        
        QRadioButton::indicator:checked {
            background-color: #ff6b35;
            border: 2px solid #ff6b35;
        }
        
        QCheckBox {
            spacing: 12px;
            color: #ffffff;
            font-size: 13px;
            font-weight: 300;
        }
        
        QCheckBox::indicator {
            width: 18px;
            height: 18px;
            border: 2px solid #333333;
            border-radius: 3px;
            background-color: transparent;
        }
        
        QCheckBox::indicator:checked {
            background-color: #ff6b35;
            border: 2px solid #ff6b35;
            border-radius: 3px;
        }
        
        QScrollBar:vertical {
            background-color: transparent;
            width: 8px;
            border-radius: 4px;
        }
        
        QScrollBar::handle:vertical {
            background-color: #333333;
            border-radius: 4px;
            min-height: 20px;
        }
        
        QScrollBar::handle:vertical:hover {
            background-color: #ff6b35;
        }
        
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
        }
        
        QMenuBar {
            background-color: #0a0a0a;
            color: #ffffff;
            border: none;
            padding: 8px;
        }
        
        QMenuBar::item {
            padding: 8px 16px;
            background-color: transparent;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        
        QMenuBar::item:selected {
            background-color: rgba(255, 107, 53, 0.1);
            color: #ff6b35;
        }
        
        QMenu {
            background-color: #1a1a1a;
            color: #ffffff;
            border: 1px solid #333333;
            border-radius: 0px;
        }
        
        QMenu::item {
            padding: 12px 20px;
            font-weight: 300;
        }
        
        QMenu::item:selected {
            background-color: #ff6b35;
            color: #0a0a0a;
        }
    """)

def get_modern_styles():
    """Возвращает элегантные стили для компонентов"""
    return {
        'groupbox': """
            QGroupBox {
                font-weight: 600;
                font-size: 14px;
                color: #fff;
                border: 1px solid #333;
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 16px;
                background-color: rgba(255, 255, 255, 0.02);
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 4px;
                color: #ccc;
                background-color: transparent;
            }
        """,
        
        'sidebar': """
            QWidget {
                background-color: #0a0a0a;
                border-right: 1px solid #333333;
            }
        """,
        
        'main_content': """
            QWidget {
                background-color: #0a0a0a;
            }
        """,
        
        'combo': """
            QComboBox {
                background-color: rgba(255, 255, 255, 0.03);
                border: 1px solid #333;
                border-radius: 4px;
                color: #fff;
                font-size: 14px;
                font-weight: 400;
                padding: 8px 12px;
                min-height: 24px;
            }
            QComboBox:focus {
                border-color: #ff6b35;
                background-color: rgba(255, 107, 53, 0.1);
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 6px solid #ccc;
                margin-right: 4px;
            }
            QComboBox QAbstractItemView {
                background-color: #1a1a1a;
                color: #fff;
                selection-background-color: #ff6b35;
                selection-color: #0a0a0a;
                border: 1px solid #333;
                border-radius: 4px;
                padding: 4px;
            }
        """,
        
        'button_primary': """
            QPushButton {
                background-color: #ff6b35;
                color: #0a0a0a;
                border: none;
                padding: 14px 24px;
                font-size: 14px;
                font-weight: 600;
                border-radius: 4px;
                min-height: 24px;
            }
            QPushButton:hover {
                background-color: #ff7f4d;
            }
            QPushButton:pressed {
                background-color: #e55a2b;
            }
            QPushButton:disabled {
                background-color: #444;
                color: #888;
            }
        """,
        
        'button_secondary': """
            QPushButton {
                background-color: transparent;
                color: #ccc;
                border: 1px solid #444;
                padding: 10px 20px;
                font-size: 13px;
                font-weight: 500;
                border-radius: 4px;
                min-height: 24px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.05);
                border-color: #666;
                color: #fff;
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 0.1);
            }
        """,
        
        'button_success': """
            QPushButton {
                background-color: #2ed573;
                color: #0a0a0a;
                border: none;
                padding: 12px 24px;
                font-size: 13px;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 1px;
                min-height: 24px;
            }
            QPushButton:hover {
                background-color: #3ee584;
            }
            QPushButton:pressed {
                background-color: #26c965;
            }
        """,
        
        'button_warning': """
            QPushButton {
                background-color: #ffa502;
                color: #0a0a0a;
                border: none;
                padding: 12px 24px;
                font-size: 13px;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 1px;
                min-height: 24px;
            }
            QPushButton:hover {
                background-color: #ffb733;
            }
            QPushButton:pressed {
                background-color: #e6940a;
            }
        """,
        
        'button_danger': """
            QPushButton {
                background-color: #ff4757;
                color: #ffffff;
                border: none;
                padding: 12px 24px;
                font-size: 13px;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 1px;
                min-height: 24px;
            }
            QPushButton:hover {
                background-color: #ff6b7a;
            }
            QPushButton:pressed {
                background-color: #e63946;
            }
        """,
        
        'line_edit': """
            QLineEdit {
                background-color: rgba(255, 255, 255, 0.03);
                border: 1px solid #333;
                border-radius: 4px;
                color: #fff;
                font-size: 14px;
                font-weight: 400;
                padding: 8px 12px;
                min-height: 24px;
            }
            QLineEdit:focus {
                border-color: #ff6b35;
                background-color: rgba(255, 107, 53, 0.1);
            }
        """,
        
        'drop_area': """
            QLabel {
                border: 2px dashed #333333;
                border-radius: 0px;
                background-color: transparent;
                color: #666666;
                font-size: 16px;
                font-weight: 300;
                padding: 40px;
                text-align: center;
                text-transform: uppercase;
                letter-spacing: 2px;
            }
        """,
        
        'drop_area_hover': """
            QLabel {
                border: 2px dashed #ff6b35;
                border-radius: 0px;
                background-color: rgba(255, 107, 53, 0.05);
                color: #ff6b35;
                font-size: 16px;
                font-weight: 300;
                padding: 40px;
                text-align: center;
                text-transform: uppercase;
                letter-spacing: 2px;
            }
        """,
        
        'preview': """
            QLabel {
                border: 1px solid #333333;
                border-radius: 0px;
                background-color: #1a1a1a;
                min-height: 300px;
            }
        """,
        
        'list_widget': """
            QListWidget {
                background-color: transparent;
                border: none;
                color: #ffffff;
                font-size: 13px;
                font-weight: 300;
            }
            QListWidget::item {
                padding: 12px 16px;
                border-bottom: 1px solid #333333;
                background-color: transparent;
            }
            QListWidget::item:selected {
                background-color: rgba(255, 107, 53, 0.1);
                color: #ff6b35;
            }
            QListWidget::item:hover {
                background-color: rgba(255, 107, 53, 0.05);
            }
        """,
        
        'status_label': """
            QLabel {
                color: #666666;
                font-size: 11px;
                font-weight: 300;
                font-style: italic;
                padding: 4px 0px;
            }
        """,
        
        'info_label': """
            QLabel {
                color: #ff6b35;
                font-size: 12px;
                font-weight: 500;
                padding: 4px 0px;
                text-transform: uppercase;
                letter-spacing: 1px;
            }
        """,
        
        'weapon_info': """
            QLabel {
                font-weight: 600;
                color: #ffffff;
                font-size: 16px;
                padding: 16px 0px;
                background-color: transparent;
                border-bottom: 1px solid #333333;
                text-transform: uppercase;
                letter-spacing: 2px;
            }
        """,
        
        'title': """
            QLabel {
                font-weight: 700;
                color: #ffffff;
                font-size: 24px;
                padding: 20px 0px;
                background-color: transparent;
                text-transform: uppercase;
                letter-spacing: 3px;
            }
        """,
        
        'subtitle': """
            QLabel {
                font-weight: 500;
                color: #cccccc;
                font-size: 14px;
                padding: 8px 0px;
                background-color: transparent;
                text-transform: uppercase;
                letter-spacing: 1px;
            }
        """,
        
        'divider': """
            QFrame {
                background-color: #333333;
                border: none;
                max-height: 1px;
            }
        """,
        
        'card': """
            QWidget {
                background-color: rgba(255, 255, 255, 0.02);
                border: 1px solid #333333;
                border-radius: 0px;
                padding: 20px;
            }
        """
    }


# Доступные темы
THEMES = {
    'dark': 'Темная',
    'blue': 'Синяя'
}


def apply_blue_theme(app: QApplication) -> None:
    """Применяет синюю тему к приложению"""
    palette = QPalette()
    
    palette.setColor(QPalette.Window, QColor("#0d1b2a"))
    palette.setColor(QPalette.WindowText, QColor("#e0e1dd"))
    palette.setColor(QPalette.Base, QColor("#1b263b"))
    palette.setColor(QPalette.AlternateBase, QColor("#415a77"))
    palette.setColor(QPalette.ToolTipBase, QColor("#1b263b"))
    palette.setColor(QPalette.ToolTipText, QColor("#e0e1dd"))
    palette.setColor(QPalette.Text, QColor("#e0e1dd"))
    palette.setColor(QPalette.Button, QColor("#415a77"))
    palette.setColor(QPalette.ButtonText, QColor("#e0e1dd"))
    palette.setColor(QPalette.BrightText, QColor("#ff6b6b"))
    palette.setColor(QPalette.Link, QColor("#4a90e2"))
    palette.setColor(QPalette.Highlight, QColor("#4a90e2"))
    palette.setColor(QPalette.HighlightedText, QColor("#0d1b2a"))
    
    app.setPalette(palette)
    
    font = QFont("Inter", 11, QFont.Normal)
    app.setFont(font)
    
    app.setStyleSheet("""
        QWidget {
            background-color: #0d1b2a;
            color: #e0e1dd;
            font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
        }
        
        QMainWindow {
            background-color: #0d1b2a;
        }
        
        QComboBox, QLineEdit, QTextEdit {
            background-color: #1b263b;
            border: 1px solid #415a77;
            border-radius: 4px;
            color: #e0e1dd;
            padding: 8px 12px;
        }
        
        QComboBox:focus, QLineEdit:focus, QTextEdit:focus {
            border: 2px solid #4a90e2;
        }
        
        QPushButton {
            background-color: #4a90e2;
            color: #0d1b2a;
            border: none;
            padding: 12px 24px;
            border-radius: 4px;
        }
        
        QPushButton:hover {
            background-color: #5ba0f2;
        }
        
        QRadioButton {
            spacing: 12px;
            color: #e0e1dd;
            font-size: 13px;
            font-weight: 300;
        }
        
        QRadioButton::indicator {
            width: 18px;
            height: 18px;
            border-radius: 9px;
            border: 2px solid #415a77;
            background-color: transparent;
        }
        
        QRadioButton::indicator:checked {
            background-color: #4a90e2;
            border: 2px solid #4a90e2;
        }
        
        QCheckBox {
            spacing: 12px;
            color: #e0e1dd;
            font-size: 13px;
            font-weight: 300;
        }
        
        QCheckBox::indicator {
            width: 18px;
            height: 18px;
            border: 2px solid #415a77;
            border-radius: 3px;
            background-color: transparent;
        }
        
        QCheckBox::indicator:checked {
            background-color: #4a90e2;
            border: 2px solid #4a90e2;
            border-radius: 3px;
        }
        
        QScrollBar::handle:vertical:hover {
            background-color: #4a90e2;
        }
        
        QMenu::item:selected {
            background-color: #4a90e2;
        }
    """)


def apply_theme(app: QApplication, theme_name: str = 'dark') -> None:
    """
    Применяет указанную тему к приложению
    
    Args:
        app: QApplication для применения темы
        theme_name: Имя темы ('dark', 'blue')
    """
    theme_map = {
        'dark': apply_dark_theme,
        'blue': apply_blue_theme
    }
    
    if theme_name not in theme_map:
        theme_name = 'dark'  # Fallback на темную тему
    
    theme_map[theme_name](app)