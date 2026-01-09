"""
Диалог настроек приложения
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, 
    QLineEdit, QFileDialog, QComboBox, QCheckBox
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from src.config.app_config import AppConfig
from src.utils.themes import get_modern_styles

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.setMinimumWidth(500)
        self.styles = get_modern_styles()
        self.config = AppConfig.load_config()
        # Инициализация переводов
        from src.data.translations import TRANSLATIONS
        current_lang = self.config.get('language') or 'ru'
        self.t = TRANSLATIONS[current_lang]
        
        self.init_ui()
        self.load_settings()
    
    def init_ui(self):
        """Инициализация UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(24, 24, 24, 24)
        
        # Заголовок
        title_label = QLabel(self.t['settings_title'])
        title_label.setStyleSheet("""
            font-size: 18px;
            font-weight: 600;
            color: #fff;
            padding-bottom: 16px;
            border-bottom: 1px solid #333;
        """)
        layout.addWidget(title_label)
        
        # TF2 Game Folder
        tf2_label = QLabel(self.t['tf2_folder_label'])
        tf2_label.setStyleSheet("font-weight: 500; font-size: 13px; color: #ccc; margin-top: 8px;")
        layout.addWidget(tf2_label)
        
        tf2_game_layout = QHBoxLayout()
        self.tf2_game_path = QLineEdit()
        self.tf2_game_path.setPlaceholderText(self.t['tf2_folder_placeholder'])
        self.tf2_game_path.setStyleSheet(self.styles['line_edit'])
        self.tf2_game_path.setMinimumHeight(40)
        
        tf2_game_browse = QPushButton(self.t['browse'])
        tf2_game_browse.setStyleSheet(self.styles['button_secondary'])
        tf2_game_browse.setMinimumHeight(40)
        tf2_game_browse.clicked.connect(self.browse_tf2_game_folder)
        
        tf2_game_layout.addWidget(self.tf2_game_path)
        tf2_game_layout.addWidget(tf2_game_browse)
        layout.addLayout(tf2_game_layout)
        
        # Выбор языка
        lang_label = QLabel(self.t['language_label'])
        lang_label.setStyleSheet("font-weight: 500; font-size: 13px; color: #ccc; margin-top: 16px;")
        layout.addWidget(lang_label)
        
        self.language_combo = QComboBox()
        self.language_combo.addItem("Русский", "ru")
        self.language_combo.addItem("English", "en")
        self.language_combo.setStyleSheet(self.styles['combo'])
        self.language_combo.setMinimumHeight(40)
        layout.addWidget(self.language_combo)
        
        # Кнопка поддержки
        support_label = QLabel(self.t.get('support_header', 'Поддержка')) # Fallback if key missing or just use existing logic
        support_label.setStyleSheet("font-weight: 500; font-size: 13px; color: #ccc; margin-top: 16px;")
        layout.addWidget(support_label)
        # Ссылка на поддержку
        support_btn = QPushButton(self.t['support'])
        support_btn.setCursor(Qt.PointingHandCursor)
        support_btn.setStyleSheet("text-align: left; padding: 5px; color: #aaa;")
        support_btn.clicked.connect(self.open_support_link)
        layout.addWidget(support_btn)

        # Разделитель
        layout.addWidget(QLabel(""))

        # Настройки отладки
        self.keep_temp_checkbox = QCheckBox(self.t['keep_temp_files'])
        self.keep_temp_checkbox.setStyleSheet("color: #ccc;")
        layout.addWidget(self.keep_temp_checkbox)
        
        self.debug_mode_checkbox = QCheckBox(self.t['debug_mode'])
        self.debug_mode_checkbox.setStyleSheet("color: #ccc;")
        layout.addWidget(self.debug_mode_checkbox)
        
        layout.addStretch()
        
        # Кнопки
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        
        self.cancel_button = QPushButton(self.t['cancel'])
        self.cancel_button.setStyleSheet(self.styles['button_secondary'])
        self.cancel_button.setMinimumHeight(40)
        self.cancel_button.clicked.connect(self.reject)
        buttons_layout.addWidget(self.cancel_button)
        
        self.save_button = QPushButton(self.t['save'])
        self.save_button.setStyleSheet(self.styles['button_primary'])
        self.save_button.setMinimumHeight(40)
        self.save_button.clicked.connect(self.save_settings)
        buttons_layout.addWidget(self.save_button)
        
        layout.addLayout(buttons_layout)
    
    def browse_tf2_game_folder(self):
        """Выбор корневой папки TF2"""
        folder = QFileDialog.getExistingDirectory(
            self,
            self.t['tf2_folder_placeholder'],
            self.tf2_game_path.text() if self.tf2_game_path.text() else ""
        )
        if folder:
            self.tf2_game_path.setText(folder)
    
    def load_settings(self):
        """Загружает настройки из конфига"""
        tf2_path = self.config.get("tf2_game_folder", "")
        if tf2_path:
            self.tf2_game_path.setText(tf2_path)
        
        # Язык
        current_lang = self.config.get('language', 'ru')
        index = self.language_combo.findData(current_lang)
        if index >= 0:
            self.language_combo.setCurrentIndex(index)
            
        # Настройки отладки
        self.keep_temp_checkbox.setChecked(self.config.get('keep_temp_files', False))
        self.debug_mode_checkbox.setChecked(self.config.get('debug_mode', False))
    
    def save_settings(self):
        """Сохраняет настройки"""
        # Сохраняем путь TF2
        path = self.tf2_game_path.text().strip()
        self.config['tf2_game_folder'] = path
        
        # Сохраняем язык
        selected_lang = self.language_combo.currentData()
        self.config['language'] = selected_lang
        
        # Сохраняем настройки отладки
        self.config['keep_temp_files'] = self.keep_temp_checkbox.isChecked()
        self.config['debug_mode'] = self.debug_mode_checkbox.isChecked()
        
        # Сохраняем в файл
        AppConfig.save_config(self.config)
        
        # Применяем язык немедленно
        if hasattr(self.parent(), 'change_language_from_combo'):
            self.parent().change_language_from_combo(self.language_combo.currentIndex())
        
        self.accept()
    
    def open_support_link(self):
        """Открывает ссылку поддержки"""
        QDesktopServices.openUrl(QUrl("https://steamcommunity.com/tradeoffer/new/?partner=394814324&token=GNGCagXk"))
    
    def get_tf2_path(self):
        """Возвращает путь к TF2"""
        return self.tf2_game_path.text().strip()


