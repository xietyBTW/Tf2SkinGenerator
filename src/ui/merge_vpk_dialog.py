"""
Диалог выбора VPK модов для объединения
"""

import os
from pathlib import Path
from typing import List
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QPushButton, QScrollArea, QWidget, QMessageBox
)
from PySide6.QtCore import Qt
from src.data.translations import TRANSLATIONS
from src.config.app_config import AppConfig
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class MergeVPKDialog(QDialog):
    """Диалог для выбора VPK файлов для объединения"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected_vpk_files = []
        
        # Получаем язык из родителя или конфига
        if parent and hasattr(parent, 't'):
            self.t = parent.t
        else:
            config = AppConfig.load_config()
            current_lang = config.get('language') or 'en'
            self.t = TRANSLATIONS[current_lang]
        
        self.init_ui()
        self.load_vpk_files()
    
    def init_ui(self):
        """Инициализация интерфейса"""
        self.setWindowTitle(self.t.get('merge_vpk_title', 'Объединить моды'))
        self.setMinimumSize(500, 400)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)
        
        # Заголовок
        title_label = QLabel(self.t.get('merge_vpk_description', 'Выберите моды для объединения:'))
        title_label.setStyleSheet("font-size: 14px; font-weight: 500; color: #ccc;")
        layout.addWidget(title_label)
        
        # Область прокрутки с чекбоксами
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: 1px solid #333;
                border-radius: 4px;
                background-color: #1a1a1a;
            }
        """)
        
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setSpacing(8)
        scroll_layout.setContentsMargins(12, 12, 12, 12)
        
        self.checkboxes = []
        self.vpk_files_list = []
        
        # Контейнер для чекбоксов будет заполнен в load_vpk_files
        self.scroll_content = scroll_widget
        scroll_area.setWidget(scroll_widget)
        layout.addWidget(scroll_area)
        
        # Кнопки
        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        
        # Кнопка "Выбрать все"
        self.select_all_btn = QPushButton(self.t.get('select_all', 'Выбрать все'))
        self.select_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a;
                color: #ccc;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #333;
            }
        """)
        self.select_all_btn.clicked.connect(self.select_all)
        buttons_layout.addWidget(self.select_all_btn)
        
        # Кнопка "Снять все"
        self.deselect_all_btn = QPushButton(self.t.get('deselect_all', 'Снять все'))
        self.deselect_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a;
                color: #ccc;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #333;
            }
        """)
        self.deselect_all_btn.clicked.connect(self.deselect_all)
        buttons_layout.addWidget(self.deselect_all_btn)
        
        # Кнопка "Отмена"
        cancel_btn = QPushButton(self.t.get('cancel', 'Отмена'))
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a;
                color: #ccc;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #333;
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        buttons_layout.addWidget(cancel_btn)
        
        # Кнопка "Объединить"
        self.merge_btn = QPushButton(self.t.get('merge', 'Объединить'))
        self.merge_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a9eff;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: 13px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #5aaeff;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                color: #666;
            }
        """)
        self.merge_btn.clicked.connect(self.accept)
        self.merge_btn.setEnabled(False)
        buttons_layout.addWidget(self.merge_btn)
        
        layout.addLayout(buttons_layout)
    
    def load_vpk_files(self):
        """Загружает список VPK файлов из папки export"""
        # Получаем путь к папке export из конфига
        config = AppConfig.load_config()
        export_folder = config.get('export_folder', 'export')
        export_path = Path(export_folder)
        
        if not export_path.exists():
            # Если папка не существует, показываем сообщение
            no_files_label = QLabel(self.t.get('no_vpk_files', 'В папке export нет VPK файлов'))
            no_files_label.setStyleSheet("color: #888; padding: 20px;")
            self.scroll_content.layout().addWidget(no_files_label)
            return
        
        # Ищем все VPK файлы
        vpk_files = list(export_path.glob("*.vpk"))
        
        if not vpk_files:
            no_files_label = QLabel(self.t.get('no_vpk_files', 'В папке export нет VPK файлов'))
            no_files_label.setStyleSheet("color: #888; padding: 20px;")
            self.scroll_content.layout().addWidget(no_files_label)
            return
        
        # Сортируем файлы по имени
        vpk_files.sort(key=lambda x: x.name.lower())
        
        # Создаем чекбоксы для каждого файла
        for vpk_file in vpk_files:
            checkbox = QCheckBox(vpk_file.name)
            checkbox.setStyleSheet("""
                QCheckBox {
                    color: #ccc;
                    font-size: 13px;
                    padding: 4px;
                }
                QCheckBox::indicator {
                    width: 18px;
                    height: 18px;
                }
            """)
            checkbox.stateChanged.connect(self.on_checkbox_changed)
            self.checkboxes.append(checkbox)
            self.vpk_files_list.append(vpk_file)
            self.scroll_content.layout().addWidget(checkbox)
        
        # Добавляем растяжку в конец
        self.scroll_content.layout().addStretch()
    
    def on_checkbox_changed(self):
        """Обработчик изменения состояния чекбокса"""
        # Проверяем, есть ли хотя бы один выбранный чекбокс
        has_selection = any(cb.isChecked() for cb in self.checkboxes)
        self.merge_btn.setEnabled(has_selection)
    
    def select_all(self):
        """Выбирает все чекбоксы"""
        for checkbox in self.checkboxes:
            checkbox.setChecked(True)
    
    def deselect_all(self):
        """Снимает выбор со всех чекбоксов"""
        for checkbox in self.checkboxes:
            checkbox.setChecked(False)
    
    def get_selected_files(self) -> List[Path]:
        """Возвращает список выбранных VPK файлов"""
        selected = []
        for i, checkbox in enumerate(self.checkboxes):
            if checkbox.isChecked():
                selected.append(self.vpk_files_list[i])
        return selected



