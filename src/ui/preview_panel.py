"""
Панель предварительного просмотра - Минималистичный дизайн
"""

from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QLabel, QPushButton, QWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QSizePolicy
from src.utils.themes import get_modern_styles

class PreviewPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__()
        self.parent = parent
        self.styles = get_modern_styles()
        self.styles = get_modern_styles()
        self.image_path = None
        self.vtf_path = None  # Путь к загруженному VTF файлу
        self.image_info = {}  # Хранит информацию об изображении
        
        # Загружаем настройки перевода
        from src.config.app_config import AppConfig
        from src.data.translations import TRANSLATIONS
        config = AppConfig.load_config()
        current_lang = config.get('language') or 'en'
        self.t = TRANSLATIONS[current_lang]
        
        # Включаем поддержку drag & drop
        self.setAcceptDrops(True)
        
        self.init_ui()
    
    def init_ui(self):
        """Инициализация UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Устанавливаем размерную политику для расширения по ширине
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        
        # Область для перетаскивания/просмотра изображения
        self.preview_container = QWidget()
        self.preview_container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        preview_layout = QVBoxLayout(self.preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(12)
        # Устанавливаем выравнивание по центру для предпросмотра
        preview_layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        
        # Пустое состояние
        self.empty_state = QWidget()
        # Устанавливаем такие же размеры, как у preview виджета
        self.empty_state.setFixedHeight(500)
        self.empty_state.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.empty_state.setMinimumWidth(800)
        self.empty_state.setMaximumWidth(16777215)  # Qt максимальное значение
        # Добавляем стиль, чтобы было видно границы (как у preview)
        self.empty_state.setStyleSheet("""
            QWidget {
                border: 1px solid #333;
                border-radius: 4px;
                background-color: #1a1a1a;
            }
        """)
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_layout.setSpacing(16)
        
        self.empty_text = QLabel(self.t['drag_text'])
        self.empty_text.setStyleSheet("""
            color: #666;
            font-size: 14px;
            font-weight: 300;
            text-align: center;
            padding: 40px;
        """)
        self.empty_text.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self.empty_text)
        
        self.select_file_button = QPushButton(self.t['select_file_btn'])
        self.select_file_button.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #888;
                border: 1px solid #333;
                padding: 10px 24px;
                font-size: 13px;
                font-weight: 500;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.05);
                border-color: #555;
                color: #ccc;
            }
        """)
        self.select_file_button.clicked.connect(self.browse_image)
        empty_layout.addWidget(self.select_file_button, alignment=Qt.AlignCenter)
        
        preview_layout.addWidget(self.empty_state)
        
        # Предварительный просмотр изображения
        self.preview = QLabel()
        self.preview_style = """
            QLabel {
                border: 1px solid #333;
                border-radius: 4px;
                background-color: #1a1a1a;
            }
        """
        self.preview.setStyleSheet(self.preview_style)
        self.preview.setAlignment(Qt.AlignCenter)
        # Устанавливаем фиксированную высоту, ширина зависит от доступного пространства
        self.preview.setFixedHeight(500)
        self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # Устанавливаем минимальную ширину, чтобы избежать слишком узкого изображения
        self.preview.setMinimumWidth(800)
        # Убираем максимальную ширину, чтобы виджет мог расширяться
        self.preview.setMaximumWidth(16777215)  # Qt максимальное значение
        self.preview.hide()
        preview_layout.addWidget(self.preview, alignment=Qt.AlignCenter)
        
        # Резюме информации
        self.info_summary = QWidget()
        info_layout = QVBoxLayout(self.info_summary)
        info_layout.setContentsMargins(12, 12, 12, 12)
        info_layout.setSpacing(8)
        
        self.info_title = QLabel(self.t['info_title'])
        self.info_title.setStyleSheet("""
            font-weight: 600;
            font-size: 13px;
            color: #ccc;
            padding-bottom: 8px;
            border-bottom: 1px solid #333;
        """)
        info_layout.addWidget(self.info_title)
        
        self.info_resolution = QLabel("")
        self.info_resolution.setStyleSheet("font-size: 12px; color: #888;")
        info_layout.addWidget(self.info_resolution)
        
        self.info_format = QLabel("")
        self.info_format.setStyleSheet("font-size: 12px; color: #888;")
        info_layout.addWidget(self.info_format)
        
        self.info_flags = QLabel("")
        self.info_flags.setStyleSheet("font-size: 12px; color: #888;")
        info_layout.addWidget(self.info_flags)
        
        self.info_filename = QLabel("")
        self.info_filename.setStyleSheet("font-size: 12px; color: #888;")
        info_layout.addWidget(self.info_filename)
        
        self.info_summary.setStyleSheet("""
            QWidget {
                background-color: rgba(255, 255, 255, 0.02);
                border: 1px solid #333;
                border-radius: 4px;
            }
        """)
        # Устанавливаем фиксированный размер для блока информации
        # Высота примерно для 4 строк информации + заголовок + отступы
        self.info_summary.setFixedHeight(220)
        self.info_summary.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # Устанавливаем минимальную ширину для блока информации
        self.info_summary.setMinimumWidth(600)
        # Всегда показываем блок информации (даже если нет изображения)
        self.info_summary.show()
        preview_layout.addWidget(self.info_summary)
        
        layout.addWidget(self.preview_container)
        
        # Настраиваем drag & drop
        self.setup_drag_drop()
        
        # Инициализируем информацию при запуске
        self.update_info_summary()
    
    def setup_drag_drop(self):
        """Настраивает drag & drop"""
        self.empty_state.setAcceptDrops(True)
        self.preview.setAcceptDrops(True)
    
    def browse_image(self):
        """Открывает диалог выбора файла (изображение или VTF)"""
        from PySide6.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self,  # parent
            self.t.get('open_dialog_title', 'Select file'),  # caption
            "",  # dir
            f"{self.t.get('images_filter', 'Images')} (*.png *.jpg *.jpeg *.bmp *.gif *.tiff *.webp);;VTF Files (*.vtf);;All Files (*.*)"  # filter
        )
        if file_path:
            if self.is_vtf_file(file_path):
                self.load_vtf(file_path)
            elif self.is_image_file(file_path):
                self.load_image(file_path)
    
    def load_image(self, path):
        """Загружает изображение для предварительного просмотра"""
        self.image_path = path
        # Очищаем путь к VTF, так как используется изображение
        self.vtf_path = None
        self.empty_state.hide()
        self.preview.show()
        # Восстанавливаем стиль для изображения
        self.preview.setStyleSheet(self.preview_style)
        
        # Принудительно обновляем геометрию виджета
        self.preview.updateGeometry()
        self.updateGeometry()
        
        # Используем QTimer для отложенного масштабирования после показа виджета
        from PySide6.QtCore import QTimer
        def scale_image():
            # Пробуем получить ширину preview виджета
            preview_width = self.preview.width()
            
            # Если ширина еще не установлена, используем ширину родительского виджета
            if preview_width <= 0:
                preview_width = self.width()
            
            # Если и это не помогло, используем разумное значение по умолчанию
            if preview_width <= 0:
                preview_width = 600
            
            # Масштабируем изображение
            pixmap = QPixmap(path).scaled(preview_width, 500, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.preview.setPixmap(pixmap)
        
        # Используем несколько попыток с увеличивающейся задержкой
        QTimer.singleShot(50, scale_image)
        QTimer.singleShot(200, scale_image)
        
        # Обновляем информацию
        self.update_info_summary()
    
    def clear_preview(self):
        """Очищает предварительный просмотр"""
        self.image_path = None
        self.vtf_path = None
        self.image_info = {}
        self.preview.clear()
        self.preview.hide()
        self.empty_state.show()
        # Обновляем информацию, но не скрываем блок
        self.update_info_summary()
    
    def get_image_path(self):
        """Возвращает путь к загруженному изображению"""
        return self.image_path
    
    def get_vtf_path(self):
        """Возвращает путь к загруженному VTF файлу"""
        return self.vtf_path
    
    def load_vtf(self, path):
        """Загружает VTF файл (сохраняет путь)"""
        import os
        if not os.path.exists(path):
            return
        
        self.vtf_path = path
        # Очищаем путь к изображению, так как используется VTF
        self.image_path = None
        
        # Показываем информацию о VTF файле
        self.empty_state.hide()
        self.preview.show()
        self.preview.clear()
        
        # Отображаем текст о том, что VTF файл загружен
        self.preview.setText(f"VTF файл загружен:\n{os.path.basename(path)}")
        self.preview.setStyleSheet(self.preview_style + """
            QLabel {
                color: #ccc;
                font-size: 14px;
            }
        """)
        self.preview.setAlignment(Qt.AlignCenter)
        
        # Обновляем информацию
        self.update_info_summary()
    
    def display_image(self, pil_image):
        """Отображает PIL Image в превью"""
        try:
            # Сохраняем PIL изображение во временный файл для последующей загрузки
            import tempfile
            temp_path = tempfile.mktemp(suffix='.png')
            pil_image.save(temp_path, 'PNG')
            
            # Обновляем путь к изображению (для совместимости)
            self.image_path = temp_path
            # Очищаем путь к VTF, так как используется изображение
            self.vtf_path = None
            
            self.preview.show()
            self.empty_state.hide()
            
            # Принудительно обновляем геометрию виджета
            self.preview.updateGeometry()
            self.updateGeometry()
            
            # Используем QTimer для отложенного масштабирования после показа виджета
            from PySide6.QtCore import QTimer
            def scale_image():
                # Пробуем получить ширину preview виджета
                preview_width = self.preview.width()
                
                # Если ширина еще не установлена, используем ширину родительского виджета
                if preview_width <= 0:
                    preview_width = self.width()
                
                # Если и это не помогло, используем разумное значение по умолчанию
                if preview_width <= 0:
                    preview_width = 600
                
                # Масштабируем изображение
                pixmap = QPixmap(temp_path).scaled(preview_width, 500, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.preview.setPixmap(pixmap)
            
            # Используем несколько попыток с увеличивающейся задержкой
            QTimer.singleShot(50, scale_image)
            QTimer.singleShot(200, scale_image)
            
            # Обновляем информацию
            self.update_info_summary()
            
        except Exception as e:
            print(f"Ошибка при отображении изображения: {e}")
            # Fallback - сохраняем во временный файл
            import tempfile
            temp_path = tempfile.mktemp(suffix='.png')
            pil_image.save(temp_path, 'PNG')
            self.load_image(temp_path)
    
    def update_info_summary(self):
        """Обновляет резюме информации"""
        # Получаем настройки из settings_panel
        if hasattr(self.parent, 'settings_panel'):
            settings = self.parent.settings_panel.get_settings()
            
            # Разрешение
            size = settings.get('size', (512, 512))
            self.info_resolution.setText(f"{self.t['info_resolution']} {size[0]}x{size[1]}")
            
            # Формат
            format_type = settings.get('format', 'DXT1')
            self.info_format.setText(f"{self.t['info_format']} {format_type}")
            
            # Флаги
            flags = settings.get('flags', [])
            if flags:
                self.info_flags.setText(f"{self.t['info_flags']} {', '.join(flags)}")
            else:
                self.info_flags.setText(self.t['info_flags_none'])
            
            # Имя файла
            filename = settings.get('filename', '')
            if filename:
                self.info_filename.setText(f"{self.t['info_filename']} {filename}")
            else:
                self.info_filename.setText(self.t['info_filename_none'])
        else:
            # Если нет настроек, показываем пустые значения
            self.info_resolution.setText(f"{self.t['info_resolution']} -")
            self.info_format.setText(f"{self.t['info_format']} -")
            self.info_flags.setText(self.t['info_flags_none'])
            self.info_filename.setText(self.t['info_filename_none'])
    
    def dragEnterEvent(self, event):
        """Обработка события входа в область перетаскивания"""
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls:
                file_path = urls[0].toLocalFile()
                if self.is_image_file(file_path) or self.is_vtf_file(file_path):
                    event.accept()
                    return
        event.ignore()
    
    def dropEvent(self, event):
        """Обработка события отпускания файла"""
        urls = event.mimeData().urls()
        if urls:
            file_path = urls[0].toLocalFile()
            if self.is_vtf_file(file_path):
                self.load_vtf(file_path)
                event.accept()
                return
            elif self.is_image_file(file_path):
                self.load_image(file_path)
                event.accept()
                return
        event.ignore()
    
    def is_image_file(self, file_path):
        """Проверяет, является ли файл изображением"""
        image_extensions = ['.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff', '.webp']
        return any(file_path.lower().endswith(ext) for ext in image_extensions)
    
    def is_vtf_file(self, file_path):
        """Проверяет, является ли файл VTF"""
        return file_path.lower().endswith('.vtf')
                
    def update_language(self, t):
        """Обновляет язык интерфейса"""
        self.t = t
        self.empty_text.setText(self.t['drag_text'])
        self.select_file_button.setText(self.t['select_file_btn'])
        self.info_title.setText(self.t['info_title'])
        # Обновляем резюме, если оно открыто
        if self.info_summary.isVisible():
            self.update_info_summary()
    
    def resizeEvent(self, event):
        """Обработка изменения размера окна - перемасштабируем изображение"""
        super().resizeEvent(event)
        # Если есть загруженное изображение, перемасштабируем его
        if self.image_path and self.preview.isVisible():
            # Используем QTimer для отложенного масштабирования после изменения размера
            from PySide6.QtCore import QTimer
            def scale_image():
                # Пробуем получить ширину preview виджета
                preview_width = self.preview.width()
                
                # Если ширина еще не установлена, используем ширину родительского виджета
                if preview_width <= 0:
                    preview_width = self.width()
                
                # Если и это не помогло, используем разумное значение по умолчанию
                if preview_width <= 0:
                    preview_width = 600
                
                if self.image_path:
                    # Проверяем, существует ли файл (может быть временный файл)
                    import os
                    if os.path.exists(self.image_path):
                        pixmap = QPixmap(self.image_path)
                        if not pixmap.isNull():
                            scaled_pixmap = pixmap.scaled(preview_width, 500, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                            self.preview.setPixmap(scaled_pixmap)
                    else:
                        # Если файл не существует, используем текущий pixmap
                        current_pixmap = self.preview.pixmap()
                        if current_pixmap:
                            scaled_pixmap = current_pixmap.scaled(preview_width, 500, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                            self.preview.setPixmap(scaled_pixmap)
            
            QTimer.singleShot(50, scale_image)
