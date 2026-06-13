"""
Главное окно приложения TF2 Skin Generator
"""

import os
from typing import Optional, Tuple
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QMessageBox, QFileDialog, QCheckBox, QPushButton, QDialog, QScrollArea,
    QFrame,
)
from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QPixmap, QDesktopServices, QMouseEvent, QIcon

from src.ui.preview_panel import PreviewPanel
from src.ui.progress_mixin import ProgressDialogMixin
from src.ui.settings_panel import SettingsPanel
from src.ui.vmt_editor import VMTEditorDialog
from src.ui.settings_dialog import SettingsDialog
from src.data.translations import TRANSLATIONS
from src.data.weapons import (
    TF2_WEAPONS, TF2_CLASSES, WEAPON_TYPES, WEAPON_SLOT_TYPES, SPECIAL_MODES,
    get_weapon_name, get_weapon_type_name, get_weapon_type_key, weapon_key_from_mode
)
from src.shared.logging_config import get_logger
from src.ui.error_handler import ErrorHandler
from src.shared.validators import validate_vpk_filename
from src.services.update_checker import UpdateChecker

logger = get_logger(__name__)


class ExclusiveCheckBox(QCheckBox):
    """Чекбокс с взаимоисключающим поведением.

    Поддерживает несколько партнёров: при включении этого чекбокса все
    партнёры автоматически снимаются (без рекурсии через сигналы).
    """

    def __init__(self, text: str, exclusive_with=None, parent=None):
        super().__init__(text, parent)
        # Может быть одним объектом или списком
        if exclusive_with is None:
            self._exclusive_partners: list = []
        elif isinstance(exclusive_with, list):
            self._exclusive_partners = exclusive_with
        else:
            self._exclusive_partners = [exclusive_with]

    # Обратная совместимость: старый атрибут .exclusive_with возвращает первого партнёра
    @property
    def exclusive_with(self):
        return self._exclusive_partners[0] if self._exclusive_partners else None

    @exclusive_with.setter
    def exclusive_with(self, value):
        if value is None:
            self._exclusive_partners = []
        elif isinstance(value, list):
            self._exclusive_partners = value
        else:
            self._exclusive_partners = [value]

    def set_exclusive_with(self, other) -> None:
        """Добавляет другой чекбокс в список взаимоисключающих партнёров."""
        if isinstance(other, list):
            self._exclusive_partners = other
        elif other not in self._exclusive_partners:
            self._exclusive_partners.append(other)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Перехватывает клик: при включении снимает всех партнёров."""
        if event.button() == Qt.LeftButton:
            # Если уже включён — просто разрешаем отключение
            if self.isChecked():
                super().mousePressEvent(event)
                return

            # Снимаем всех партнёров (без эмиссии сигналов — обработчики сигналов
            # всё равно вызовутся из stateChanged этого чекбокса)
            for partner in self._exclusive_partners:
                if partner.isChecked():
                    partner.blockSignals(True)
                    partner.setChecked(False)
                    partner.blockSignals(False)

            super().mousePressEvent(event)
        else:
            super().mousePressEvent(event)


class MainWindow(QMainWindow, ProgressDialogMixin):
    def __init__(self) -> None:
        super().__init__()
        from src.config.app_config import AppConfig
        from src.core.app_factory import AppFactory
        self.config = AppConfig.load_config()
        self.language = self.config.get('language') or 'en'
        self.t = TRANSLATIONS[self.language]
        self.setWindowTitle("TF2 Skin Generator")
        self.setGeometry(100, 100, 1600, 800)
        # Минимум окна: ниже этого правая колонка (настройки/кнопки) обрезалась бы.
        # Qt сам поднимет минимум, если контенту нужно больше — обрезки не будет.
        self.setMinimumSize(1080, 600)

        icon_path = AppFactory.get_icon_path()
        if icon_path:
            self.setWindowIcon(QIcon(str(icon_path)))
        
        self.current_class = None
        self.current_weapon_type = None
        self.current_weapon = None
        self.mode = None
        
        self.setAcceptDrops(True)

        self.init_ui()
        self.setup_connections()

        # Запускаем проверку обновлений в фоне (не блокирует UI)
        self._start_update_check()

        # Восстанавливаем геометрию окна из конфига
        saved_geom = self.config.get('window_geometry')
        if saved_geom:
            from PySide6.QtCore import QByteArray
            self.restoreGeometry(QByteArray.fromBase64(saved_geom.encode()))
        else:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(100, self._adjust_window_size)
    
    def init_ui(self) -> None:
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_vertical_layout = QVBoxLayout(central_widget)
        main_vertical_layout.setContentsMargins(0, 0, 0, 0)
        main_vertical_layout.setSpacing(0)

        top_bar = QWidget()
        top_bar_layout = QHBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(16, 8, 16, 0)
        top_bar_layout.setSpacing(0)
        top_bar_layout.addStretch()

        self.settings_button = QPushButton()
        self.settings_button.setFixedSize(28, 28)
        self.settings_button.setIcon(_make_gear_icon("#585858", 16))
        from PySide6.QtCore import QSize as _QSize
        self.settings_button.setIconSize(_QSize(16, 16))
        self.settings_button.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 0px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.05);
                border-color: #333;
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 0.09);
                border-color: #444;
            }
        """)
        self.settings_button.setToolTip(self.t.get('settings_tooltip', 'Settings'))
        self.settings_button.clicked.connect(self.open_settings_dialog)
        top_bar_layout.addWidget(self.settings_button)

        main_vertical_layout.addWidget(top_bar)

        # Баннер обновления — скрыт по умолчанию, показывается при наличии новой версии
        self._update_banner = self._create_update_banner()
        self._update_banner.hide()
        main_vertical_layout.addWidget(self._update_banner)

        main_layout = QHBoxLayout()
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(20, 16, 20, 20)

        left_panel = self.create_weapon_selection_panel()
        main_layout.addWidget(left_panel, 1)

        self.preview_panel = PreviewPanel(self)

        main_layout.addWidget(self.preview_panel, 2)

        self.settings_panel = SettingsPanel(self)
        self.settings_panel.update_language(self.t)
        self.settings_scroll = QScrollArea()
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # Вертикальный скроллбар ВСЕГДА резервирует место (нет «прыжка» отступа
        # при раскрытии Advanced), но визуально скрыт пока скроллить нечего.
        self.settings_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.settings_scroll.setMinimumWidth(220)
        self.settings_scroll.setWidget(self.settings_panel)
        self.settings_scroll.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollArea > QWidget > QWidget { background: transparent; }
        """)

        # Динамический стиль вертикального скроллбара: тонкая линия когда есть что
        # скроллить, полностью прозрачный — когда нет (место при этом зарезервировано).
        _vsb = self.settings_scroll.verticalScrollBar()
        _SB_THIN = (
            "QScrollBar:vertical{background:transparent;width:10px;margin:2px 0;}"
            "QScrollBar::handle:vertical{background:rgba(255,255,255,0.18);"
            "border-radius:2px;min-height:30px;margin:0 3px;}"
            "QScrollBar::handle:vertical:hover{background:rgba(255,255,255,0.34);}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
            "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:transparent;}"
        )
        _SB_HIDDEN = (
            "QScrollBar:vertical{background:transparent;width:10px;}"
            "QScrollBar::handle:vertical{background:transparent;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
            "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:transparent;}"
        )

        def _sync_vsb(*_args):
            _vsb.setStyleSheet(_SB_THIN if _vsb.maximum() > _vsb.minimum() else _SB_HIDDEN)

        _vsb.rangeChanged.connect(_sync_vsb)
        _sync_vsb()
        main_layout.addWidget(self.settings_scroll, 1)

        main_vertical_layout.addLayout(main_layout)

        self.settings_panel.radio_256.toggled.connect(self.update_preview_info)
        self.settings_panel.radio_512.toggled.connect(self.update_preview_info)
        self.settings_panel.radio_1024.toggled.connect(self.update_preview_info)
        self.settings_panel.format_combo.currentTextChanged.connect(self.update_preview_info)
        self.settings_panel.filename_input.textChanged.connect(self.update_preview_info)
        self.settings_panel.flag_clamps.stateChanged.connect(self.update_preview_info)
        self.settings_panel.flag_clampt.stateChanged.connect(self.update_preview_info)
        self.settings_panel.flag_nomipmaps.stateChanged.connect(self.update_preview_info)
        self.settings_panel.flag_nolod.stateChanged.connect(self.update_preview_info)
        if hasattr(self.settings_panel, 'option_nothumbnail'):
            self.settings_panel.option_nothumbnail.stateChanged.connect(self.update_preview_info)
        if hasattr(self.settings_panel, 'option_noreflectivity'):
            self.settings_panel.option_noreflectivity.stateChanged.connect(self.update_preview_info)
        if hasattr(self.settings_panel, 'option_gamma'):
            self.settings_panel.option_gamma.stateChanged.connect(self.update_preview_info)
        if hasattr(self.settings_panel, 'gamma_value_input'):
            self.settings_panel.gamma_value_input.textChanged.connect(self.update_preview_info)

        # Применяем ограничения UI для начального состояния (режим не выбран)
        self.settings_panel.apply_mode_restrictions(self.mode)

    # ── Обновления ──────────────────────────────────────────────────────── #

    def _create_update_banner(self) -> QWidget:
        """Создаёт скрытый баннер «доступно обновление»."""
        from PySide6.QtWidgets import QLabel
        banner = QWidget()
        banner.setFixedHeight(36)
        banner.setStyleSheet("""
            QWidget {
                background-color: #1a1200;
                border-bottom: 1px solid #3a2800;
            }
        """)
        layout = QHBoxLayout(banner)
        layout.setContentsMargins(16, 0, 12, 0)
        layout.setSpacing(8)

        self._update_icon_label = QLabel("↑")
        self._update_icon_label.setStyleSheet("color: #c87820; font-size: 13px; font-weight: 700;")
        layout.addWidget(self._update_icon_label)

        self._update_text_label = QLabel()
        self._update_text_label.setStyleSheet("color: #c0a060; font-size: 12px;")
        self._update_text_label.setCursor(Qt.PointingHandCursor)
        self._update_text_label.mousePressEvent = self._open_release_url
        layout.addWidget(self._update_text_label, 1)

        dismiss_btn = QPushButton("✕")
        dismiss_btn.setFixedSize(20, 20)
        dismiss_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                color: #776040;
                font-size: 11px;
            }
            QPushButton:hover { color: #c0a060; }
        """)
        dismiss_btn.clicked.connect(banner.hide)
        layout.addWidget(dismiss_btn)

        return banner

    def _start_update_check(self) -> None:
        """Запускает фоновую проверку обновлений."""
        self._update_checker = UpdateChecker()
        self._update_checker.update_available.connect(self._on_update_available)
        self._update_checker.start()

    def _on_update_available(self, tag: str, url: str) -> None:
        """Показывает баннер когда найдена новая версия."""
        self._release_url = url
        from src.shared.version import __version__
        if self.language == 'ru':
            msg = f"Доступна новая версия {tag} (сейчас {__version__}) — нажмите, чтобы открыть страницу загрузки"
        else:
            msg = f"New version {tag} available (current {__version__}) — click to open download page"
        self._update_text_label.setText(msg)
        self._update_banner.show()

    def _open_release_url(self, _event=None) -> None:
        """Открывает страницу релиза в браузере."""
        url = getattr(self, '_release_url', '')
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def create_weapon_selection_panel(self) -> QWidget:
        from PySide6.QtWidgets import (
            QGroupBox, QVBoxLayout, QLabel, QComboBox,
            QPushButton, QWidget, QStackedWidget,
        )
        from src.utils.themes import get_modern_styles
        from src.ui.hats_panel import HatsPanel

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(10)
        layout.setContentsMargins(0, 0, 0, 0)

        self.step_1_label = QLabel(self.t['step_1_selection'])
        self.step_1_label.setStyleSheet("""
            font-size: 12px;
            font-weight: 600;
            color: #888;
            text-transform: uppercase;
            letter-spacing: 1px;
            padding-bottom: 4px;
        """)
        layout.addWidget(self.step_1_label)

        # ── Таб-бар: WEAPONS / HATS ───────────────────────────────────────── #
        self._tab_bar = QWidget()
        self._tab_bar.setStyleSheet("background: transparent;")
        tab_row = QHBoxLayout(self._tab_bar)
        tab_row.setContentsMargins(0, 0, 0, 0)
        tab_row.setSpacing(0)

        def _tab_btn_style(active: bool) -> str:
            accent = self._get_accent_color()
            if active:
                return f"""
                    QPushButton {{
                        background: transparent;
                        border: none;
                        border-bottom: 2px solid {accent};
                        color: {accent};
                        font-size: 11px;
                        font-weight: 700;
                        letter-spacing: 2px;
                        padding: 6px 14px 4px 14px;
                        text-transform: uppercase;
                    }}
                """
            return """
                QPushButton {
                    background: transparent;
                    border: none;
                    border-bottom: 2px solid transparent;
                    color: #444;
                    font-size: 11px;
                    font-weight: 500;
                    letter-spacing: 2px;
                    padding: 6px 14px 4px 14px;
                    text-transform: uppercase;
                }
                QPushButton:hover {
                    color: #777;
                    border-bottom-color: #333;
                }
            """

        self._tab_weapons_btn = QPushButton(
            self.t.get('tab_weapons', 'Weapons') if self.language == 'ru' else 'Weapons'
        )
        self._tab_weapons_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tab_weapons_btn.setStyleSheet(_tab_btn_style(True))
        self._tab_weapons_btn.clicked.connect(lambda: self._switch_tab(0))

        self._tab_hats_btn = QPushButton(
            self.t.get('tab_hats', 'Шапки') if self.language == 'ru' else 'Hats'
        )
        self._tab_hats_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tab_hats_btn.setStyleSheet(_tab_btn_style(False))
        self._tab_hats_btn.clicked.connect(lambda: self._switch_tab(1))

        tab_row.addWidget(self._tab_weapons_btn)
        tab_row.addWidget(self._tab_hats_btn)
        tab_row.addStretch()

        # Разделитель под таб-баром
        tab_sep = QFrame()
        tab_sep.setFrameShape(QFrame.Shape.HLine)
        tab_sep.setStyleSheet("background: #1a1a1a; border: none; max-height: 1px;")

        layout.addWidget(self._tab_bar)
        layout.addWidget(tab_sep)

        # ── QStackedWidget: страница 0 = оружие, страница 1 = шапки ─────── #
        self._left_stack = QStackedWidget()
        self._left_stack.setStyleSheet("background: transparent;")

        # ── Страница 0: оружие ────────────────────────────────────────────── #
        weapons_page = QWidget()
        weapons_layout = QVBoxLayout(weapons_page)
        weapons_layout.setSpacing(16)
        weapons_layout.setContentsMargins(0, 8, 0, 0)

        self.weapon_selection_group = QGroupBox(self.t['weapon_selection'])
        styles = get_modern_styles()
        self.weapon_selection_group.setStyleSheet(styles['groupbox'])

        group_layout = QVBoxLayout(self.weapon_selection_group)
        group_layout.setSpacing(12)

        _lbl_style = "font-weight: 500; font-size: 13px; color: #ccc; margin-top: 8px;"

        # ── Категория — верхний селектор: что вообще делаем ───────────────── #
        self.category_label = QLabel(self.t['category'])
        self.category_label.setStyleSheet("font-weight: 500; font-size: 13px; color: #ccc; margin-top: 4px;")
        group_layout.addWidget(self.category_label)

        # Ключи категорий в порядке отображения. Используем индекс для маппинга.
        self._category_keys = ['weapon', 'character', 'special', 'custom']
        self.category_combo = QComboBox()
        self.category_combo.setStyleSheet(styles['combo'])
        self._populate_category_combo()
        group_layout.addWidget(self.category_combo)

        # ── Класс (для категорий Оружие, Персонаж) ───────────────────────── #
        self.class_label = QLabel(self.t['class'])
        self.class_label.setStyleSheet(_lbl_style)
        group_layout.addWidget(self.class_label)

        self.class_combo = QComboBox()
        self.class_combo.setStyleSheet(styles['combo'])
        for class_name, class_info in TF2_CLASSES.items():
            self.class_combo.addItem(f"{class_info['icon']} {class_name}")
        group_layout.addWidget(self.class_combo)

        # ── Тип оружия — только слоты Primary/Secondary/Melee (Оружие) ────── #
        self.type_label = QLabel(self.t['weapon_type'])
        self.type_label.setStyleSheet(_lbl_style)
        group_layout.addWidget(self.type_label)

        self.weapon_type_combo = QComboBox()
        self.weapon_type_combo.setStyleSheet(styles['combo'])
        group_layout.addWidget(self.weapon_type_combo)

        # ── Подтип — контекстный: части персонажа ИЛИ крит/спрей ─────────── #
        self.subtype_label = QLabel(self.t['subtype_part'])
        self.subtype_label.setStyleSheet(_lbl_style)
        group_layout.addWidget(self.subtype_label)

        self._subtype_keys: list = []   # ключи текущих пунктов subtype_combo
        self.subtype_combo = QComboBox()
        self.subtype_combo.setStyleSheet(styles['combo'])
        group_layout.addWidget(self.subtype_combo)

        # ── Конкретное оружие (категория Оружие) ─────────────────────────── #
        self.weapon_label = QLabel(self.t['weapon'])
        self.weapon_label.setStyleSheet(_lbl_style)
        group_layout.addWidget(self.weapon_label)

        self.weapon_combo = QComboBox()
        self.weapon_combo.setStyleSheet(styles['combo'])
        group_layout.addWidget(self.weapon_combo)

        # ── Крит/Спрей чекбоксы — СКРЫТЫ, живут как внутреннее состояние ──── #
        # settings_panel завязан на crit_hit_checkbox (hasattr/isChecked/
        # stateChanged), поэтому объекты сохраняем. Управляются программно
        # из subtype_combo при категории «Специальное».
        self.crit_hit_label = QLabel(self.t['crit_hit_mode'])
        self.crit_hit_checkbox = ExclusiveCheckBox(self.t['enable_crit_hit'])
        self.spray_label = QLabel(self.t.get('spray_mode', 'Spray Mode:'))
        self.spray_checkbox = ExclusiveCheckBox(self.t.get('enable_spray', 'Create spray (256×256, RGBA)'))
        for _w in (self.crit_hit_label, self.crit_hit_checkbox, self.spray_label, self.spray_checkbox):
            _w.setVisible(False)
            group_layout.addWidget(_w)

        self.crit_hit_checkbox.set_exclusive_with([self.spray_checkbox])
        self.spray_checkbox.set_exclusive_with([self.crit_hit_checkbox])

        group_layout.addStretch()
        weapons_layout.addWidget(self.weapon_selection_group)
        weapons_layout.addStretch()

        # ── Страница 1: шапки ─────────────────────────────────────────────── #
        hats_page = QWidget()
        hats_page_layout = QVBoxLayout(hats_page)
        hats_page_layout.setContentsMargins(0, 8, 0, 0)
        hats_page_layout.setSpacing(0)

        self.hats_panel = HatsPanel(hats_page, language=self.language)
        self.hats_panel.hat_selected.connect(self._on_hat_selected)
        self.hats_panel.hat_deselected.connect(self._on_hat_deselected)
        hats_page_layout.addWidget(self.hats_panel)

        self._left_stack.addWidget(weapons_page)   # index 0
        self._left_stack.addWidget(hats_page)      # index 1

        layout.addWidget(self._left_stack, 1)

        self.selected_smd_path = None
        self._custom_vpk_path: Optional[str] = None
        self._hat_mdl_path: Optional[str] = None
        self._hat_display_name: str = ""
        self._current_tab = 0  # 0=weapons, 1=hats

        return container

    def _get_accent_color(self) -> str:
        try:
            from src.config.app_config import AppConfig
            return "#4a90e2" if AppConfig.load_config().get("theme") == "blue" else "#ff6b35"
        except Exception:
            return "#ff6b35"

    def _switch_tab(self, index: int) -> None:
        """Переключает вкладку Weapons / Hats."""
        self._current_tab = index
        self._left_stack.setCurrentIndex(index)

        # Стиль активной/неактивной кнопки
        accent = self._get_accent_color()

        active_style = f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-bottom: 2px solid {accent};
                color: {accent};
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 2px;
                padding: 6px 14px 4px 14px;
                text-transform: uppercase;
            }}
        """
        inactive_style = """
            QPushButton {
                background: transparent;
                border: none;
                border-bottom: 2px solid transparent;
                color: #444;
                font-size: 11px;
                font-weight: 500;
                letter-spacing: 2px;
                padding: 6px 14px 4px 14px;
                text-transform: uppercase;
            }
            QPushButton:hover { color: #777; border-bottom-color: #333; }
        """

        self._tab_weapons_btn.setStyleSheet(active_style if index == 0 else inactive_style)
        self._tab_hats_btn.setStyleSheet(active_style if index == 1 else inactive_style)

        if index == 1:
            # Загружаем шапки если ещё не загружены
            from src.config.app_config import AppConfig
            tf2_root = AppConfig.load_config().get("tf2_game_folder", "")
            self.hats_panel.load_hats(tf2_root)
            # Сбрасываем weapons mode
            self.mode = None
            self._hat_mdl_path = None
            if hasattr(self, 'settings_panel'):
                self.settings_panel.apply_mode_restrictions(None)
        else:
            # Возвращаемся к оружию — сбрасываем hat mode
            self._hat_mdl_path = None
            self._hat_display_name = ""
            self.apply_selection_auto()

    def _on_hat_selected(self, mdl_path: str, display_name: str) -> None:
        """Пользователь выбрал шапку из списка."""
        self._hat_mdl_path = mdl_path
        self._hat_display_name = display_name
        self.mode = "hat"
        logger.info(f"Выбрана шапка: {display_name} → {mdl_path}")
        if hasattr(self, 'settings_panel'):
            self.settings_panel.apply_mode_restrictions(self.mode)
        # Сбрасываем 2D панель — чтобы текстура предыдущей шапки не оставалась.
        # Передаём mdl_path как weapon_key чтобы смена шапки всегда вызывала сброс.
        if hasattr(self, 'preview_panel'):
            self.preview_panel.update_extra_slots(mdl_path, mode='hat')
        # Обновляем 3D preview и сводку
        self._update_hat_3d_preview()
        self.update_preview_info()

    def _on_hat_deselected(self) -> None:
        self._hat_mdl_path = None
        self._hat_display_name = ""
        self.mode = None
        if hasattr(self, 'settings_panel'):
            self.settings_panel.apply_mode_restrictions(None)
        if hasattr(self, 'preview_panel'):
            self.preview_panel.reset_3d_preview()
        self.update_preview_info()

    def _update_hat_3d_preview(self) -> None:
        """Обновляет 3D Preview при выборе шапки."""
        if not hasattr(self, 'preview_panel'):
            return

        hat_mdl = getattr(self, '_hat_mdl_path', None)
        if not hat_mdl:
            self.preview_panel.reset_3d_preview()
            return

        settings = self.settings_panel.get_settings()
        tf2_root_dir = settings.get('tf2_game_folder', '')
        if not tf2_root_dir:
            self.preview_panel.show_3d_no_tf2_message()
            return

        try:
            from src.services.tf2_paths import TF2Paths
            _, misc_vpk, _ = TF2Paths.resolve(tf2_root_dir)
            textures_vpk = TF2Paths.resolve_textures_vpk(tf2_root_dir)
        except Exception:
            self.preview_panel.show_3d_no_tf2_message()
            return

        if not misc_vpk:
            self.preview_panel.show_3d_no_tf2_message()
            return

        self.preview_panel.set_3d_params(
            weapon_key=hat_mdl,
            mode="hat",
            misc_vpk_path=misc_vpk,
            textures_vpk_path=textures_vpk or "",
        )

    def setup_connections(self) -> None:
        """Настраивает соединения сигналов"""
        self.category_combo.currentIndexChanged.connect(self.on_category_changed)
        self.class_combo.currentTextChanged.connect(self.on_class_changed)
        self.weapon_type_combo.currentTextChanged.connect(self.on_weapon_type_changed)
        self.subtype_combo.currentIndexChanged.connect(self.on_subtype_changed)
        self.weapon_combo.currentTextChanged.connect(self.on_weapon_changed)
        self.crit_hit_checkbox.stateChanged.connect(self._on_crit_hit_state_changed)
        self.spray_checkbox.stateChanged.connect(self._on_spray_state_changed)

        # Подключаем сигналы опций сборки из settings_panel
        if hasattr(self, 'settings_panel'):
            self.settings_panel.replace_model_toggled.connect(self.on_replace_model_changed)
            self.settings_panel.model_ready_toggled.connect(self._on_model_ready_toggled)
            # Пер-текстурные карты материала: запрос из settings_panel → диалог у превью.
            if hasattr(self, 'preview_panel'):
                self.settings_panel.material_maps_requested.connect(
                    self.preview_panel.open_material_maps)
            # Пер-текстурный VMT-редактор: запрос из settings_panel → редактор материала.
            self.settings_panel.vmt_edit_requested.connect(self._open_vmt_for_material)

        # Когда пользователь загрузил VPK мод в 3D — автоматически переключаем на Custom
        if hasattr(self, 'preview_panel'):
            self.preview_panel.vpk_mod_loaded.connect(self._on_vpk_mod_loaded)

        # Инициализируем: категория «Оружие» → класс → тип → оружие
        self.on_category_changed(0)

    def _populate_category_combo(self) -> None:
        """Заполняет category_combo локализованными названиями (сохраняя индекс)."""
        prev = self.category_combo.currentIndex() if self.category_combo.count() else 0
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        for key in self._category_keys:
            self.category_combo.addItem(self.t.get(f'category_{key}', key))
        if 0 <= prev < self.category_combo.count():
            self.category_combo.setCurrentIndex(prev)
        self.category_combo.blockSignals(False)

    @property
    def _current_category(self) -> str:
        """Текущий ключ категории ('weapon'|'character'|'special'|'custom')."""
        idx = self.category_combo.currentIndex()
        if 0 <= idx < len(self._category_keys):
            return self._category_keys[idx]
        return 'weapon'

    def _apply_category_visibility(self, cat: str) -> None:
        """Показывает/прячет списки в зависимости от выбранной категории."""
        show_class   = cat in ('weapon', 'character')
        show_type    = cat == 'weapon'
        show_weapon  = cat == 'weapon'
        show_subtype = cat in ('character', 'special')

        self.class_label.setVisible(show_class)
        self.class_combo.setVisible(show_class)
        self.type_label.setVisible(show_type)
        self.weapon_type_combo.setVisible(show_type)
        self.weapon_label.setVisible(show_weapon)
        self.weapon_combo.setVisible(show_weapon)
        self.subtype_label.setVisible(show_subtype)
        self.subtype_combo.setVisible(show_subtype)

        # Крит-режим мог задизейблить комбобоксы — восстанавливаем доступность
        for _c in (self.class_combo, self.weapon_type_combo, self.weapon_combo, self.subtype_combo):
            _c.setEnabled(True)

        if show_subtype:
            key = 'subtype_special' if cat == 'special' else 'subtype_part'
            self.subtype_label.setText(self.t.get(key, 'Подтип:'))

    def on_category_changed(self, _index: int = 0) -> None:
        """Обработка смены верхней категории."""
        cat = self._current_category
        self._apply_category_visibility(cat)

        # Покидая «Специальное» — снимаем крит/спрей чекбоксы (без сигналов,
        # чтобы их хендлеры не дёргали apply_selection_auto преждевременно) и
        # вручную уведомляем settings_panel, что крит-режим выключен.
        if cat != 'special':
            was_special = False
            for cb in (self.crit_hit_checkbox, self.spray_checkbox):
                if cb.isChecked():
                    was_special = True
                    cb.blockSignals(True)
                    cb.setChecked(False)
                    cb.blockSignals(False)
            if was_special and hasattr(self, 'settings_panel'):
                self.settings_panel.on_crit_hit_selected(False)

        if cat == 'weapon':
            # Перезаполняем слоты + оружие через стандартный путь
            self.on_class_changed(self.class_combo.currentText())
        elif cat == 'character':
            self._populate_subtype_for_character()
        elif cat == 'special':
            self._populate_subtype_for_special()
        else:  # custom
            self.apply_selection_auto()

    def _populate_subtype_for_character(self) -> None:
        """Заполняет subtype_combo частями персонажа (тело + руки) текущего класса."""
        from src.data.weapons import get_character_parts
        class_name = self.current_class or (
            self.class_combo.currentText().split(' ', 1)[1]
            if ' ' in self.class_combo.currentText() else self.class_combo.currentText()
        )
        self.current_class = class_name
        parts = get_character_parts(class_name, self.language)

        self.subtype_combo.blockSignals(True)
        self.subtype_combo.clear()
        self._subtype_keys = []
        for key, name in parts:
            self.subtype_combo.addItem(name)
            self._subtype_keys.append(key)
        self.subtype_combo.blockSignals(False)

        if self._subtype_keys:
            self.subtype_combo.setCurrentIndex(0)
            self.on_subtype_changed(0)
        else:
            self.apply_selection_auto()

    def _populate_subtype_for_special(self) -> None:
        """Заполняет subtype_combo пунктами Крит / Спрей."""
        self.subtype_combo.blockSignals(True)
        self.subtype_combo.clear()
        self._subtype_keys = ['critHIT', 'spray', 'death_ice', 'death_gold', 'death_fire']
        self.subtype_combo.addItem(self.t.get('special_crit', 'Крит'))
        self.subtype_combo.addItem(self.t.get('special_spray', 'Спрей'))
        self.subtype_combo.addItem(self.t.get('special_death_ice', 'Эффект смерти: Лёд'))
        self.subtype_combo.addItem(self.t.get('special_death_gold', 'Эффект смерти: Золото'))
        self.subtype_combo.addItem(self.t.get('special_death_fire', 'Эффект смерти: Огонь'))
        self.subtype_combo.blockSignals(False)

        self.subtype_combo.setCurrentIndex(0)
        self.on_subtype_changed(0)

    def on_subtype_changed(self, _index: int = 0) -> None:
        """Обработка смены подтипа (часть персонажа или крит/спрей)."""
        idx = self.subtype_combo.currentIndex()
        if idx < 0 or idx >= len(self._subtype_keys):
            return
        key = self._subtype_keys[idx]
        cat = self._current_category

        if cat == 'character':
            # Часть персонажа: тело/руки → mode = f"{class}_{key}"
            self.current_weapon = key
            self.apply_selection_auto()
        elif cat == 'special':
            # Подтип special — источник истины. Крит/Спрей дополнительно
            # синхронизируют свои скрытые чекбоксы; скины эффектов смерти
            # (death_*) держат оба чекбокса выключенными.
            self._special_subtype = key
            want_crit = (key == 'critHIT')
            want_spray = (key == 'spray')
            self.crit_hit_checkbox.blockSignals(True)
            self.spray_checkbox.blockSignals(True)
            self.crit_hit_checkbox.setChecked(want_crit)
            self.spray_checkbox.setChecked(want_spray)
            self.crit_hit_checkbox.blockSignals(False)
            self.spray_checkbox.blockSignals(False)
            # Побочные эффекты, которые раньше делали обработчики чекбоксов:
            self.selected_smd_path = None
            if hasattr(self, 'settings_panel'):
                self.settings_panel.reset_build_options(emit=True)
                self.settings_panel.on_crit_hit_selected(want_crit)
            self.apply_selection_auto()
    
    def update_ui_text(self) -> None:
        """Обновляет текст интерфейса при смене языка"""
        # Обновляем заголовки
        if hasattr(self, 'step_1_label'):
            self.step_1_label.setText(self.t['step_1_selection'])
        if hasattr(self, 'weapon_selection_group'):
            self.weapon_selection_group.setTitle(self.t['weapon_selection'])
        if hasattr(self, 'category_label'):
            self.category_label.setText(self.t['category'])
        if hasattr(self, 'class_label'):
            self.class_label.setText(self.t['class'])
        if hasattr(self, 'type_label'):
            self.type_label.setText(self.t['weapon_type'])
        if hasattr(self, 'subtype_label'):
            _sub_key = 'subtype_special' if self._current_category == 'special' else 'subtype_part'
            self.subtype_label.setText(self.t.get(_sub_key, 'Подтип:'))
        if hasattr(self, 'weapon_label'):
            self.weapon_label.setText(self.t['weapon'])
        
        # Обновляем дочерние панели
        if hasattr(self, 'settings_panel'):
            self.settings_panel.update_language(self.t)
            
        if hasattr(self, 'preview_panel'):
            self.preview_panel.update_language(self.t, self.language)
            
        if hasattr(self, 'crit_hit_checkbox'):
            self.crit_hit_checkbox.setText(self.t['enable_crit_hit'])
            
        if hasattr(self, 'crit_hit_label'):
            self.crit_hit_label.setText(self.t['crit_hit_mode'])
        
        if hasattr(self, 'spray_label'):
            self.spray_label.setText(self.t.get('spray_mode', 'Spray Mode:'))

        if hasattr(self, 'spray_checkbox'):
            self.spray_checkbox.setText(self.t.get('enable_spray', 'Create spray (256×256, RGBA)'))

        if hasattr(self, '_tab_weapons_btn'):
            self._tab_weapons_btn.setText(
                self.t.get('tab_weapons', 'Weapons') if self.language == 'ru' else 'Weapons'
            )
        if hasattr(self, '_tab_hats_btn'):
            self._tab_hats_btn.setText(
                self.t.get('tab_hats', 'Шапки') if self.language == 'ru' else 'Hats'
            )
        if hasattr(self, 'hats_panel'):
            self.hats_panel.update_language(self.language)

        # Обновляем категорию и зависимые списки с учётом нового языка
        if hasattr(self, 'category_combo'):
            self._populate_category_combo()
            self.on_category_changed(self.category_combo.currentIndex())

    def _find_weapon_type_index(self, type_key: str) -> int:
        """Возвращает индекс в weapon_type_combo для заданного ключа типа оружия, или -1."""
        target = get_weapon_type_name(type_key, self.language)
        for i in range(self.weapon_type_combo.count()):
            if self.weapon_type_combo.itemText(i) == target:
                return i
        return -1

    def on_class_changed(self, class_text: str) -> None:
        """Обработка изменения класса (для категорий Оружие и Персонаж)."""
        # Извлекаем имя класса из текста с иконкой
        class_name = class_text.split(' ', 1)[1] if ' ' in class_text else class_text
        self.current_class = class_name

        cat = self._current_category

        # В категории «Персонаж» смена класса перезаполняет части (тело/руки)
        if cat == 'character':
            self._populate_subtype_for_character()
            return

        # В прочих категориях, кроме «Оружие», класс не влияет на списки
        if cat != 'weapon':
            return

        # ── Категория «Оружие»: заполняем слоты Primary/Secondary/Melee ──── #
        saved_key = self.current_weapon_type if self.current_weapon_type in WEAPON_SLOT_TYPES else "Primary"

        self.weapon_type_combo.blockSignals(True)
        self.weapon_type_combo.clear()
        if class_name in TF2_WEAPONS:
            for weapon_type in WEAPON_SLOT_TYPES:
                if weapon_type in TF2_WEAPONS[class_name]:
                    self.weapon_type_combo.addItem(get_weapon_type_name(weapon_type, self.language))
        self.weapon_type_combo.blockSignals(False)

        if self.weapon_type_combo.count() > 0:
            idx = self._find_weapon_type_index(saved_key)
            if idx == -1:
                idx = self._find_weapon_type_index("Primary")
            if idx == -1:
                idx = 0
            self.weapon_type_combo.setCurrentIndex(idx)
            self.on_weapon_type_changed(self.weapon_type_combo.currentText())

    def on_weapon_type_changed(self, type_text: str) -> None:
        """Обработка изменения слота оружия (только Primary/Secondary/Melee)."""
        weapon_type = get_weapon_type_key(type_text, self.language)

        if weapon_type and self.current_class:
            self.current_weapon_type = weapon_type

            # Обновляем список конкретного оружия для выбранного слота
            self.weapon_combo.clear()
            if self.current_class in TF2_WEAPONS and weapon_type in TF2_WEAPONS[self.current_class]:
                for weapon_key in TF2_WEAPONS[self.current_class][weapon_type].keys():
                    weapon_name = get_weapon_name(self.current_class, weapon_type, weapon_key, self.language)
                    self.weapon_combo.addItem(f"{weapon_name} ({weapon_key})")

            self.apply_selection_auto()


    def on_weapon_changed(self, weapon_text: str) -> None:
        """Обработка изменения оружия"""
        if weapon_text and '(' in weapon_text:
            # Извлекаем ключ оружия из ПОСЛЕДНИХ скобок.
            # Формат: "{weapon_name} ({weapon_key})"
            # Если имя содержит скобки (напр. "Robot Hand (MvM) (mech_hands)"),
            # split('(')[1] вернёт "MvM) " — ошибка.
            # split('(')[-1] всегда берёт последнюю группу → "mech_hands)" → "mech_hands".
            weapon_key = weapon_text.split('(')[-1].rstrip(')').strip()
            self.current_weapon = weapon_key
            # Автоматически применяем выбор
            self.apply_selection_auto()
    
    def _on_crit_hit_state_changed(self, state: int) -> None:
        """Обработчик изменения состояния чекбокса CritHIT"""
        is_checked = (state == Qt.Checked)

        # Если CritHIT включается — отключаем остальные взаимоисключающие режимы
        if is_checked:
            self.spray_checkbox.blockSignals(True)
            self.spray_checkbox.setChecked(False)
            self.spray_checkbox.blockSignals(False)
            # Сбрасываем опции замены/готовой модели в меню шестерёнки
            if hasattr(self, 'settings_panel'):
                self.settings_panel.reset_build_options(emit=True)

        # Вызываем основной обработчик
        self.on_crit_hit_changed(is_checked)
    
    def _on_spray_state_changed(self, state: int) -> None:
        """Обработчик изменения состояния чекбокса Spray"""
        is_checked = (state == Qt.Checked)

        # Если спрей включается — отключаем остальные взаимоисключающие режимы
        if is_checked:
            self.crit_hit_checkbox.blockSignals(True)
            self.crit_hit_checkbox.setChecked(False)
            self.crit_hit_checkbox.blockSignals(False)
            self.selected_smd_path = None
            # Сбрасываем опции замены/готовой модели в меню шестерёнки
            if hasattr(self, 'settings_panel'):
                self.settings_panel.reset_build_options(emit=True)
            # Восстанавливаем комбобоксы (CritHIT их блокировал)
            self.class_combo.setEnabled(True)
            self.weapon_type_combo.setEnabled(True)
            self.weapon_combo.setEnabled(True)
            # Уведомляем панель настроек (сбрасываем CritHIT-специфичные настройки)
            if hasattr(self, 'settings_panel'):
                self.settings_panel.on_crit_hit_selected(False)

        self.apply_selection_auto()

    def on_crit_hit_changed(self, is_crit_hit: bool) -> None:
        """Обработка изменения состояния CritHIT режима"""
        # Отключаем/включаем элементы управления
        self.class_combo.setEnabled(not is_crit_hit)
        self.weapon_type_combo.setEnabled(not is_crit_hit)
        self.weapon_combo.setEnabled(not is_crit_hit)
        
        # Уведомляем панель настроек для обновления её UI (включая скрытие UV разметки)
        if hasattr(self, 'settings_panel'):
            self.settings_panel.on_crit_hit_selected(is_crit_hit)
        
        # Автоматически применяем выбор
        self.apply_selection_auto()
    
    def on_replace_model_changed(self, is_enabled: bool) -> None:
        """Обработка изменения состояния замены модели (вызывается из settings_panel.replace_model_toggled)"""
        if not is_enabled:
            self.selected_smd_path = None
        self.apply_selection_auto()

    def _on_model_ready_toggled(self, is_enabled: bool) -> None:
        """Обработка изменения состояния 'Модель уже готова'"""
        if not is_enabled:
            self.selected_smd_path = None
        self.apply_selection_auto()

    def _on_vpk_mod_loaded(self, vpk_path: str) -> None:
        """Вызывается когда пользователь загрузил VPK мод в 3D превью."""
        self._custom_vpk_path = vpk_path
        # Переключаем категорию на «Кастомный мод»
        try:
            custom_idx = self._category_keys.index('custom')
            if self.category_combo.currentIndex() == custom_idx:
                # Уже на custom — сигнал не сработает, пересчитываем mode вручную
                self.apply_selection_auto()
            else:
                self.category_combo.setCurrentIndex(custom_idx)
        except ValueError:
            pass
        logger.info(f"Кастомный VPK мод загружен: {vpk_path}")
    
    def apply_selection_auto(self) -> None:
        """Определяет self.mode по текущей категории и выбору пользователя."""
        # Если активна вкладка шапок — mode управляется через _on_hat_selected
        if getattr(self, '_current_tab', 0) == 1:
            return

        cat = self._current_category

        if cat == 'special':
            # Источник истины — выбранный подтип (крит/спрей/скин эффекта смерти).
            self.mode = getattr(self, '_special_subtype', None)
            if self.mode is None:
                # Fallback на чекбоксы (на случай старого состояния).
                if self.spray_checkbox.isChecked():
                    self.mode = "spray"
                elif self.crit_hit_checkbox.isChecked():
                    self.mode = "critHIT"
        elif cat == 'custom':
            self.mode = "custom" if getattr(self, '_custom_vpk_path', None) else None
        elif cat == 'character':
            # Тело/руки: mode = f"{class}_{part_key}" (scout_body, spy_masks и т.д.)
            if self.current_class and self.current_weapon:
                self.mode = f"{self.current_class.lower()}_{self.current_weapon}"
            else:
                self.mode = None
        else:  # weapon
            if self.current_class and self.current_weapon:
                self.mode = f"{self.current_class.lower()}_{self.current_weapon}"
                logger.debug(f"Выбрано оружие: {self.current_class} - {self.current_weapon}")
            else:
                self.mode = None

        # Применяем ограничения UI для текущего режима
        if hasattr(self, 'settings_panel'):
            self.settings_panel.apply_mode_restrictions(self.mode)

        # Обновляем 3D Preview
        self._update_3d_preview()

        # Обновляем карточки доп. текстурных слотов в 2D превью
        self._update_extra_slots()

        # Обновляем резюме в превью
        self.update_preview_info()

    def _resolve_3d_weapon_key(self) -> Optional[str]:
        """
        weapon_key для 3D Preview по текущему режиму, либо None если показывать нечего.

        В None-случаях сам выставляет нужное состояние превью (reset / custom-model),
        поэтому вызывающему достаточно просто выйти.
        """
        from src.data.player_hands import HAND_MODE_KEYS, HAND_MODES
        from src.data.player_characters import (
            PLAYER_BODY_MODE_KEYS, PLAYER_CHARACTERS, SPY_MASK_MODE_KEY, SPY_MDL_PATH,
        )

        is_hand_mode = self.mode in HAND_MODE_KEYS
        is_player_body = self.mode in PLAYER_BODY_MODE_KEYS
        is_spy_masks = (self.mode == SPY_MASK_MODE_KEY)
        is_normal_weapon = (
            self.mode
            and self.mode not in SPECIAL_MODES.values()
            and not is_hand_mode
            and not is_player_body
            and not is_spy_masks
            and '_' in self.mode
        )

        if is_hand_mode:
            # Руки персонажа — используем arm_model как weapon_key
            arm_key = HAND_MODES.get(self.mode, {}).get("arm_model", "")
            if not arm_key:
                self.preview_panel.reset_3d_preview()
                return None
            return arm_key
        if is_player_body:
            # Тело персонажа — передаём полный mdl_path как weapon_key (как у шапок)
            mdl_path = PLAYER_CHARACTERS.get(self.mode, {}).get("mdl_path", "")
            if not mdl_path:
                self.preview_panel.reset_3d_preview()
                return None
            return mdl_path
        if is_spy_masks:
            # Маски маскировки шпиона — тот же MDL что и у скина шпиона
            return SPY_MDL_PATH
        if is_normal_weapon:
            # Режим замены модели / готовой модели — кастомная SMD/MDL от пользователя
            if hasattr(self, 'settings_panel') and (
                self.settings_panel.is_replace_model_checked() or
                self.settings_panel.is_model_ready_checked()
            ):
                self.preview_panel.set_custom_model_mode(True)
                return None
            return weapon_key_from_mode(self.mode)

        # Spray / нет выбора — сбрасываем 3D
        self.preview_panel.reset_3d_preview()
        return None

    def _update_3d_preview(self) -> None:
        """Запускает или сбрасывает 3D Preview в зависимости от текущего режима."""
        if not hasattr(self, 'preview_panel'):
            return

        # CritHIT: показываем солдата с billboard-текстурой над головой
        if self.mode == "critHIT":
            self.preview_panel.set_crithit_mode()
            return

        # Эффекты смерти (лёд/золото/огонь): тот же персонаж, но текстура
        # пользователя ложится на саму модель — как эффект ляжет в игре.
        # Сначала показываем оригинальную игровую текстуру эффекта из VPK.
        if self.mode in ("death_ice", "death_gold", "death_fire"):
            _tex_vpk = _misc_vpk = ''
            _root = self.settings_panel.get_settings().get('tf2_game_folder', '')
            if _root:
                try:
                    from src.services.tf2_paths import TF2Paths
                    _, _misc_vpk, _ = TF2Paths.resolve(_root)
                    _tex_vpk = TF2Paths.resolve_textures_vpk(_root)
                except Exception:
                    _tex_vpk = _misc_vpk = ''
            self.preview_panel.set_death_effect_mode(
                mode=self.mode, textures_vpk=_tex_vpk or '', misc_vpk=_misc_vpk or ''
            )
            return

        weapon_key = self._resolve_3d_weapon_key()
        if weapon_key is None:
            return

        # Нормальный режим оружия или руки — пробуем запустить 3D preview (требует TF2)
        settings = self.settings_panel.get_settings()
        tf2_root_dir = settings.get('tf2_game_folder', '')
        if not tf2_root_dir:
            self.preview_panel.show_3d_no_tf2_message()
            return

        try:
            from src.services.tf2_paths import TF2Paths
            _, misc_vpk, _ = TF2Paths.resolve(tf2_root_dir)
            textures_vpk   = TF2Paths.resolve_textures_vpk(tf2_root_dir)
        except Exception:
            self.preview_panel.show_3d_no_tf2_message()
            return

        if not misc_vpk or not textures_vpk:
            self.preview_panel.show_3d_no_tf2_message()
            return

        # Включаем/выключаем режим масок шпиона
        from src.data.player_characters import SPY_MASK_MODE_KEY as _SMK
        self.preview_panel.set_spy_mask_mode(self.mode == _SMK)

        self.preview_panel.set_3d_params(
            weapon_key=weapon_key,
            mode=self.mode,
            misc_vpk_path=misc_vpk,
            textures_vpk_path=textures_vpk,
        )

    def _update_extra_slots(self) -> None:
        """Обновляет карточки доп. текстурных слотов в 2D превью при смене оружия."""
        if not hasattr(self, 'preview_panel'):
            return

        from src.data.player_hands import HAND_MODE_KEYS, HAND_MODES
        from src.data.player_characters import SPY_MASK_MODE_KEY as _SMK2, SPY_MASK_VTF_NAMES

        mode = getattr(self, 'mode', None) or ''

        if not mode or mode in set(SPECIAL_MODES.values()) | {'custom'}:
            self.preview_panel.update_extra_slots('', mode='')
            return

        if mode == _SMK2:
            # Маски шпиона: передаём список имён масок как material_names
            self.preview_panel.update_extra_slots_spy_masks(SPY_MASK_VTF_NAMES)
            return

        is_hand_mode = mode in HAND_MODE_KEYS
        if is_hand_mode:
            arm_key = HAND_MODES.get(mode, {}).get('arm_model', '')
            self.preview_panel.update_extra_slots(arm_key, mode=mode)
        elif '_' in mode:
            weapon_key = mode.split('_', 1)[1]
            self.preview_panel.update_extra_slots(weapon_key, mode=mode)
        else:
            self.preview_panel.update_extra_slots('', mode='')

    # ── Hand texture slot selector ────────────────────────────────────── #

    def update_preview_info(self) -> None:
        """Обновляет резюме информации в превью"""
        if hasattr(self, 'preview_panel'):
            self.preview_panel.update_info_summary()
    
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def change_language_from_combo(self, index: int) -> None:
        """Обработка изменения языка из настроек"""
        lang_code = 'ru' if index == 0 else 'en'
        
        # Сохраняем в конфиг
        from src.config.app_config import AppConfig
        AppConfig.set("language", lang_code)
        
        # Используем единый метод для установки языка
        self.set_language(lang_code)

    def dropEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            # Remember which texture slot this image belongs to
            self.preview_panel.load_image(path)

    def expert_mode_triggered(self) -> None:
        """Открывает редактор VMT для выбранного оружия/шапки."""
        if not hasattr(self, 'mode') or not self.mode:
            ErrorHandler.show_warning(self, self.t.get('select_weapon_error', 'Select a weapon first'), self.t['error'])
            return

        from src.data.weapons import SPECIAL_MODES
        if self.mode in set(SPECIAL_MODES.values()) | {"custom"}:
            ErrorHandler.show_warning(self, self.t.get('vmt_editor_not_available', 'VMT editor is not available for this mode.'), self.t['error'])
            return

        target = self._resolve_vmt_target()
        if target is None:
            return
        weapon_key, display_name = target
        self._open_vmt_for_target(weapon_key, display_name)

    def _resolve_vmt_target(self):
        """(weapon_key, display_name) для VMT-редактора по текущему режиму, либо None
        (с предупреждением), если режим не поддерживается."""
        from src.data.player_hands import HAND_MODE_KEYS, HAND_MODES
        from src.data.player_characters import PLAYER_BODY_MODE_KEYS, PLAYER_CHARACTERS
        if self.mode == "hat":
            hat_mdl = getattr(self, '_hat_mdl_path', None)
            if not hat_mdl:
                ErrorHandler.show_warning(
                    self,
                    self.t.get('select_weapon_error', 'Select a hat first'),
                    self.t['error'],
                )
                return None
            # Ключ для кэша — нормализованный MDL путь
            weapon_key   = hat_mdl.replace("\\", "/").lower()
            display_name = getattr(self, '_hat_display_name', weapon_key)

        elif self.mode in HAND_MODE_KEYS:
            arm_model = HAND_MODES.get(self.mode, {}).get("arm_model", "")
            if not arm_model:
                ErrorHandler.show_warning(
                    self,
                    self.t.get('vmt_editor_not_available', 'VMT editor is not available for this mode.'),
                    self.t['error'],
                )
                return None
            weapon_key   = arm_model
            display_name = arm_model

        elif self.mode in PLAYER_BODY_MODE_KEYS:
            mdl_key = PLAYER_CHARACTERS.get(self.mode, {}).get("mdl_key", "")
            if not mdl_key:
                ErrorHandler.show_warning(
                    self,
                    self.t.get('vmt_editor_not_available', 'VMT editor is not available for this mode.'),
                    self.t['error'],
                )
                return None
            weapon_key   = mdl_key
            display_name = mdl_key

        else:
            # Обычное оружие: mode = "scout_c_scattergun" → "c_scattergun"
            weapon_key   = weapon_key_from_mode(self.mode)
            display_name = weapon_key
        return weapon_key, display_name

    def _open_vmt_for_material(self, material: str = "") -> None:
        """
        Открывает VMT-редактор для КОНКРЕТНОГО материала карточки (пер-текстурно).
        material='' → главный материал текущего превью.
        """
        if not hasattr(self, 'mode') or not self.mode:
            ErrorHandler.show_warning(self, self.t.get('select_weapon_error', 'Select a weapon first'), self.t['error'])
            return
        from src.data.weapons import SPECIAL_MODES
        if self.mode in set(SPECIAL_MODES.values()) | {"custom"}:
            ErrorHandler.show_warning(self, self.t.get('vmt_editor_not_available', 'VMT editor is not available for this mode.'), self.t['error'])
            return
        target = self._resolve_vmt_target()
        if target is None:
            return
        weapon_key, display_name = target

        mat = (material or '').strip()
        if not mat and hasattr(self, 'preview_panel'):
            names = getattr(self.preview_panel, '_material_names', None) or []
            mat = names[0] if names else ''
        if not mat:
            mat = weapon_key  # запасной ключ (как у глобальной кнопки)

        # Ключ хранилища и извлекаемый файл = имя материала. Для главного материала
        # это совпадает с texture_filename, который сборка уже ищет.
        self._open_vmt_for_target(weapon_key, mat, edit_key=mat, material_name=mat)

    def _open_vmt_for_target(self, weapon_key: str, display_name: str,
                             edit_key: Optional[str] = None,
                             material_name: Optional[str] = None) -> None:
        """
        Открывает сохранённый VMT либо извлекает оригинал из игры и открывает редактор.

        edit_key      — ключ EditedVMTService (по умолч. weapon_key — главный материал).
        material_name — имя VMT-файла для извлечения (по умолч. weapon_key).
        """
        from src.services.edited_vmt_service import EditedVMTService
        edit_key = edit_key or weapon_key
        material_name = material_name or weapon_key
        # ── Открываем сохранённый VMT (если есть) ────────────────────────── #
        edited_vmt_path = EditedVMTService.get_edited_vmt(edit_key)
        if edited_vmt_path and os.path.exists(edited_vmt_path):
            self.open_vmt_editor(edited_vmt_path, edit_key, display_name)
            return

        # ── Нет сохранённого — нужен путь к TF2 для извлечения ──────────── #
        settings     = self.settings_panel.get_settings()
        tf2_root_dir = settings.get('tf2_game_folder', '')

        if not tf2_root_dir:
            ErrorHandler.show_warning(
                self,
                self.t.get('tf2_path_not_specified', 'TF2 path not specified in settings'),
                self.t['error'],
            )
            return

        # ── Извлекаем VMT из VPK ─────────────────────────────────────────── #
        if self.mode == "hat":
            vmt_path = self._extract_hat_vmt_from_game(weapon_key, tf2_root_dir, material_name)
        else:
            vmt_path = self.extract_original_vmt_from_game(weapon_key, tf2_root_dir, material_name)

        if not vmt_path:
            ErrorHandler.show_warning(
                self,
                self.t.get(
                    'vmt_extract_failed',
                    'Could not extract original VMT for: {key}\nCheck TF2 path in settings.',
                ).format(key=display_name),
                self.t['error'],
            )
            return

        self.open_vmt_editor(vmt_path, edit_key, display_name)


    def _extract_hat_vmt_from_game(self, hat_mdl: str, tf2_root_dir: str,
                                   material_name: Optional[str] = None) -> Optional[str]:
        """
        Извлекает VMT для шапки через цепочку QC → cdmaterials → VPK.
        Переиспользует ту же логику что и 3D Preview.
        """
        from src.services.tf2_paths import TF2Paths
        from src.services.preview_3d_worker import Preview3DWorker
        from src.services import decompile_cache
        import glob, tempfile

        # ── 1. Ищем QC в кэше декомпиляции ──────────────────────────────── #
        try:
            _, misc_vpk, _ = TF2Paths.resolve(tf2_root_dir)
        except Exception:
            return None

        qc_path = decompile_cache.find_cached_qc_for_weapon(hat_mdl)
        if not qc_path:
            # Нет кэша — пробуем без декомпиляции (быстро, не всегда работает)
            return None

        from src.services import qc_skin_parser
        cdmaterials = qc_skin_parser.parse_cdmaterials(qc_path)
        _rows = qc_skin_parser.parse_texturegroup_rows(qc_path)
        skin0_textures = _rows[0] if _rows else []
        if not cdmaterials:
            return None

        # Конкретный материал (пер-карточная правка) — ищем именно его.
        if material_name:
            mat_names = [material_name]
        else:
            mat_names = list(skin0_textures) if skin0_textures else []
        if not mat_names:
            import re as _re
            stem = os.path.splitext(os.path.basename(hat_mdl))[0]
            stem = _re.sub(
                r'_(heavy|scout|soldier|pyro|demoman|engineer|medic|sniper|spy)$',
                '', stem, flags=_re.IGNORECASE,
            )
            mat_names = [stem]

        # ── 2. Открываем оба VPK и ищем VMT ─────────────────────────────── #
        import vpk as vpklib
        textures_vpk = TF2Paths.resolve_textures_vpk(tf2_root_dir)
        paks: list = []
        for vp in [misc_vpk, textures_vpk]:
            if vp and os.path.exists(vp):
                try:
                    paks.append(vpklib.open(vp))
                except Exception:
                    pass

        if not paks:
            return None

        vmt_content: Optional[str] = None
        vmt_filename: str = "hat.vmt"

        for mat_name in mat_names:
            for pak in paks:
                info = Preview3DWorker._find_vmt_content_in_vpk(pak, cdmaterials, mat_name.lower())
                if info:
                    _path, _raw = info
                    vmt_content  = _raw
                    vmt_filename = os.path.basename(_path)
                    break
            if vmt_content:
                break

        for pak in paks:
            try:
                pak.close()
            except Exception:
                pass

        if not vmt_content:
            return None

        # ── 3. Сохраняем во временный файл ───────────────────────────────── #
        temp_dir = os.path.join("tools", "temp_vmt_extract")
        os.makedirs(temp_dir, exist_ok=True)
        out_path = os.path.join(temp_dir, vmt_filename)
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(vmt_content)
            return out_path
        except OSError:
            return None
    
    def extract_original_vmt_from_game(self, weapon_key: str, tf2_root_dir: str,
                                       material_name: Optional[str] = None) -> Optional[str]:
        """
        Извлекает оригинальный VMT файл из игры для оружия
        
        Пути поиска (в VPK без префикса materials/):
        - models/workshop_partner/weapons/c_models/{weapon_key}/ (с папкой)
        - models/workshop_partner/weapons/c_models/ (без папки, файл напрямую)
        - models/weapons/c_items/{weapon_key}/ (с папкой)
        - models/weapons/c_items/ (без папки, файл напрямую)
        
        Args:
            weapon_key: Ключ оружия (например, c_scattergun)
            tf2_root_dir: Корневая директория TF2
            
        Returns:
            Путь к извлеченному VMT файлу или None если не удалось извлечь
        """
        from src.services.tf2_vpk_extract_service import TF2VPKExtractService
        from src.services.tf2_paths import TF2Paths
        
        # Создаем временную директорию для извлечения
        temp_dir = os.path.join("tools", "temp_vmt_extract")
        os.makedirs(temp_dir, exist_ok=True)
        
        # Получаем пути к VPK файлам
        tf2_textures_vpk = TF2Paths.resolve_textures_vpk(tf2_root_dir)
        try:
            _, tf2_misc_vpk, _ = TF2Paths.resolve(tf2_root_dir)
        except FileNotFoundError:
            tf2_misc_vpk = None
        
        # Список путей для поиска VMT файла (в порядке приоритета)
        # В VPK файлах VMT находятся в materials/ директории
        search_paths = []
        
        if weapon_key.startswith('v_'):
            # Для v_ оружия
            search_paths = [
                f"materials/models/weapons/{weapon_key}",  # materials/models/weapons/v_weapon
                f"materials/models/workshop_partner/weapons/{weapon_key}",  # materials/models/workshop_partner/weapons/v_weapon
                f"models/weapons/{weapon_key}",  # Fallback без materials/
                f"models/workshop_partner/weapons/{weapon_key}",  # Fallback без materials/
            ]
        else:
            # Для c_ оружия пробуем несколько путей в порядке приоритета
            # Сначала с materials/, затем без (fallback)
            search_paths = [
                f"materials/models/workshop_partner/weapons/c_models/{weapon_key}",  # С папкой и materials/
                f"materials/models/workshop_partner/weapons/c_models/{weapon_key}/{weapon_key}",  # С полным путем
                f"materials/models/workshop/weapons/c_models/{weapon_key}",  # Альтернативный путь
                f"materials/models/weapons/c_models/{weapon_key}",  # Стандартный путь
                f"materials/models/weapons/c_items/{weapon_key}",  # c_items путь
                "materials/models/workshop_partner/weapons/c_models",  # Без папки (файл напрямую)
                "materials/models/weapons/c_items",  # Без папки в c_items
                # Fallback пути без materials/
                f"models/workshop_partner/weapons/c_models/{weapon_key}",  # С папкой
                "models/workshop_partner/weapons/c_models",  # Без папки (файл напрямую)
                f"models/weapons/c_items/{weapon_key}",  # С папкой в c_items
                "models/weapons/c_items",  # Без папки в c_items (файл напрямую)
            ]
        
        # Пробуем извлечь VMT по каждому пути
        vpk_files = []
        if tf2_textures_vpk:
            vpk_files.append(tf2_textures_vpk)
        if tf2_misc_vpk:
            vpk_files.append(tf2_misc_vpk)
        
        # Имя VMT-файла: для доп. материала — его имя, иначе главный (weapon_key).
        # Папки ($cdmaterials) у материалов одного оружия общие, меняется только файл.
        fname = material_name or weapon_key
        for cdmaterials_path in search_paths:
            for vpk_file in vpk_files:
                vmt_file = TF2VPKExtractService.extract_vmt_file(
                    vpk_file,
                    cdmaterials_path,
                    fname,
                    temp_dir
                )
                if vmt_file and os.path.exists(vmt_file):
                    return vmt_file
        
        return None

    def open_vmt_editor(self, path: str, weapon_key: str = "", display_name: str = "") -> None:
        """Открывает редактор VMT файла"""
        dialog = VMTEditorDialog(self, path, weapon_key, self.t, display_name=display_name)
        dialog.exec()

    def _launch_progress(
        self,
        dialog_attr: str,
        worker,
        cancel_handler=None,
        *,
        title: Optional[str] = None,
        text: Optional[str] = None,
        disable_button: Optional[str] = None,
        cancellable: bool = True,
    ) -> None:
        """
        Создаёт прогресс-диалог, запускает воркер и показывает диалог.

        Единый запуск для всех фоновых операций (сборка / извлечение текстуры
        и модели / экспорт / merge). Диалог сохраняется в self.<dialog_attr>.

        Args:
            dialog_attr:    имя атрибута для хранения диалога.
            worker:         уже созданный QThread-воркер (сигналы подключены снаружи).
            cancel_handler: слот для cancel_requested (если диалог отменяемый).
            title/text:     заголовок и подпись диалога (опционально).
            disable_button: имя кнопки в settings_panel, которую выключить на время.
            cancellable:    можно ли отменять (False → без кнопки отмены).
        """
        from src.ui.build_progress_dialog import BuildProgressDialog
        kwargs = {'language': self.language, 'cancellable': cancellable}
        if title is not None:
            kwargs['title'] = title
        dlg = BuildProgressDialog(self, **kwargs)
        if text is not None:
            dlg.setLabelText(text)
        if cancellable and cancel_handler is not None:
            dlg.cancel_requested.connect(cancel_handler)
        setattr(self, dialog_attr, dlg)

        worker.start()
        dlg.show()
        if disable_button and hasattr(self.settings_panel, disable_button):
            getattr(self.settings_panel, disable_button).setEnabled(False)

    def _worker_busy(self, attr: str, message_key: str, default: str) -> bool:
        """
        True (и показывает предупреждение), если воркер self.<attr> уже выполняется.

        Единый guard «операция уже идёт» для всех фоновых задач.
        """
        worker = getattr(self, attr, None)
        if worker is not None and worker.isRunning():
            ErrorHandler.show_warning(self, self.t.get(message_key, default), self.t['error'])
            return True
        return False

    def _dispose_build_worker(self) -> None:
        """
        Отключает сигналы и удаляет предыдущий BuildWorker (если был).

        Нужно перед повторной сборкой, иначе старые соединения вызовут
        колбэки повторно. Отключение всех сигналов обёрнуто в try/except —
        безопасно, даже если что-то уже отключено.
        """
        worker = getattr(self, '_build_worker', None)
        if worker is None:
            return
        for sig in (
            'finished', 'progress', 'sub_progress', 'error',
            'request_extra_texture', 'request_model_file',
            'request_extra_model', 'texture_mismatch_warning',
        ):
            try:
                getattr(worker, sig).disconnect()
            except Exception:
                pass
        worker.deleteLater()
        self._build_worker = None

    def build_vpk(self):
        """Запускает асинхронную сборку VPK"""
        try:
            if not hasattr(self, 'mode') or not self.mode:
                ErrorHandler.show_warning(self, self.t['select_weapon_error'], self.t['error'])
                return
                
            settings = self.settings_panel.get_settings()
            name = settings['filename']
            if not name:
                ErrorHandler.show_warning(self, self.t['enter_name'], self.t['error'])
                return
            
            # Валидация имени файла
            is_valid, error_msg = validate_vpk_filename(name)
            if not is_valid:
                ErrorHandler.show_warning(self, error_msg, self.t['error'])
                return

            size = settings['size']

            # Спрей поддерживает максимум 256×256 — предупреждаем и принудительно уменьшаем
            if self.mode == "spray" and (size[0] > 256 or size[1] > 256):
                if self.language == 'ru':
                    msg = (f"Спрей поддерживает максимум 256×256.\n"
                           f"Выбранное разрешение {size[0]}×{size[1]} будет уменьшено до 256×256.\n\n"
                           f"Совет: выберите «256×256 (Спрей)» в разделе Разрешение.")
                else:
                    msg = (f"Spray supports a maximum of 256×256.\n"
                           f"The selected resolution {size[0]}×{size[1]} will be downscaled to 256×256.\n\n"
                           f"Tip: select '256×256 (Spray)' in the Resolution section.")
                QMessageBox.warning(self, self.t['error'], msg)
                size = (256, 256)

            is_special_mode = self.mode in SPECIAL_MODES.values()
            # Для critHIT используем настройки пользователя (формат, флаги, опции)
            selected_format = settings['format']
            flags = settings['flags']
            vtf_options = settings.get('vtf_options', {})
            is_crit_hit = (hasattr(self, 'crit_hit_checkbox') and 
                          self.crit_hit_checkbox.isChecked())
            if is_crit_hit and (settings.get('draw_uv_layout', False) or vtf_options.get('normal')):
                ErrorHandler.show_warning(
                    self,
                    self.t.get(
                        'crit_hit_conflict_error',
                        'Дополнительные настройки (UV разметка / Normal Map) конфликтуют с CritHIT. Сборка не запущена.'
                    ),
                    self.t['error']
                )
                return
            # UV разметка недоступна для CritHIT режима
            draw_uv_layout = settings.get('draw_uv_layout', False) and not is_special_mode and not is_crit_hit
            
            # Проверяем, используется ли VTF файл из preview_panel
            custom_vtf_path = self.preview_panel.get_vtf_path()
            from_path = None

            if not custom_vtf_path:
                from src.shared.constants import EXTRA_TEX_USE_GAME_ORIGINAL
                from src.data.player_characters import SPY_MASK_MODE_KEY as _SPY_MASK_MODE
                if self.mode == _SPY_MASK_MODE:
                    # Маски маскировки: нет «главной» текстуры — все маски через callback.
                    # Передаём sentinel как placeholder, vpk_service обработает маски отдельно.
                    from_path = EXTRA_TEX_USE_GAME_ORIGINAL
                else:
                    # get_red_image_path() не делает fallback на BLU — возвращает
                    # None если RED не загружен.
                    from_path = self.preview_panel.get_red_image_path()
                    # В custom режиме изображение необязательно
                    if not from_path and self.mode != "custom":
                        # Главный слот пуст, но мод всё равно можно собрать, если
                        # пользователь загрузил текстуры в другие слоты (доп. карточки,
                        # 3D-дроп на не-главный меш) или BLU-команду. В этом случае
                        # главную текстуру берём оригинальную из игры (sentinel),
                        # а загруженные слоты применяются поверх.
                        has_other_textures = bool(
                            self.preview_panel.get_blu_image_path()
                            or self.preview_panel.get_slot_image_paths()
                        )
                        if has_other_textures:
                            from_path = EXTRA_TEX_USE_GAME_ORIGINAL
                        else:
                            ErrorHandler.show_warning(self, self.t['load_image_error'], self.t['error'])
                            return
            
            # Читаем опции замены/готовой модели из меню шестерёнки
            replace_model_enabled = (
                hasattr(self, 'settings_panel') and
                self.settings_panel.is_replace_model_checked()
            )
            model_ready_enabled = (
                hasattr(self, 'settings_panel') and
                self.settings_panel.is_model_ready_checked()
            )
            # Кнопка 🔄: если в превью загружена кастомная модель — включаем замену
            # автоматически (без галочки в настройках). Развязывает кнопку и настройки.
            if (not model_ready_enabled and hasattr(self, 'preview_panel')
                    and self.preview_panel.get_custom_smd_path()):
                replace_model_enabled = True

            # Взаимоисключение с CritHIT — сбрасываем оба флага если активен CritHIT
            is_crit_hit = (hasattr(self, 'crit_hit_checkbox') and
                           self.crit_hit_checkbox.isChecked())
            if is_crit_hit and (replace_model_enabled or model_ready_enabled):
                logger.warning("CritHIT + model options conflict — resetting model options.")
                if hasattr(self, 'settings_panel'):
                    self.settings_panel.reset_build_options(emit=False)
                replace_model_enabled = False
                model_ready_enabled   = False

            # Если "Замена модели" — берём путь к SMD. Сначала пробуем модель,
            # уже загруженную в 3D-превью (чтобы не просить выбрать файл повторно).
            # Если её нет — показываем диалог выбора ДО запуска воркера.
            replace_model_smd_path: Optional[str] = None
            if replace_model_enabled and not model_ready_enabled:
                if hasattr(self, 'preview_panel'):
                    replace_model_smd_path = self.preview_panel.get_custom_smd_path()
                if replace_model_smd_path:
                    logger.info(f"Замена модели: используем загруженную в превью SMD: {replace_model_smd_path}")
                else:
                    smd_file, _ = QFileDialog.getOpenFileName(
                        self,
                        self.t.get(
                            'replace_model_select_title',
                            'Select SMD file for model replacement'
                        ),
                        "",
                        "SMD Files (*.smd);;All Files (*)"
                    )
                    if not smd_file:
                        return  # Пользователь отменил
                    replace_model_smd_path = smd_file

            # Если "Модель уже готова" — запрашиваем путь к .mdl файлу ДО запуска воркера
            model_ready_path: Optional[str] = None
            if model_ready_enabled:
                mdl_file, _ = QFileDialog.getOpenFileName(
                    self,
                    self.t.get(
                        'model_ready_select_title',
                        'Select pre-compiled model file (.mdl)'
                    ),
                    "",
                    "Model Files (*.mdl *.smd);;MDL Files (*.mdl);;SMD Files (*.smd);;All Files (*)"
                )
                if not mdl_file:
                    return  # Пользователь отменил
                model_ready_path = mdl_file

            # Для шапок — спрашиваем, нужны ли краски из игры
            hat_apply_game_paints = True
            if self.mode == "hat":
                paints_title = self.t.get('hat_game_paints_title', 'Game Paints')
                paints_question = self.t.get(
                    'hat_game_paints_question',
                    'Do you want game paints to apply to your texture?\n\n'
                    'If "Yes" — the VMT file will be loaded with original paint settings.\n'
                    'If "No" — paints will be disabled, your texture will display without game coloring.'
                )
                reply = QMessageBox.question(
                    self,
                    paints_title,
                    paints_question,
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes,
                )
                hat_apply_game_paints = (reply == QMessageBox.Yes)

            # Мультиклассовая шапка: какие классы собирать (выбор в списке шапок).
            # None — обычная шапка (одна общая модель) или не режим шапки.
            hat_class_models = None
            hat_mdl_path_for_build = getattr(self, '_hat_mdl_path', None)
            if self.mode == "hat" and hasattr(self, 'hats_panel'):
                hat_class_models = self.hats_panel.get_selected_class_models()
                if hat_class_models:
                    # Основная (primary) сборка идёт по ПЕРВОМУ выбранному классу,
                    # остальные дособираются в тот же VPK в vpk_service.
                    hat_mdl_path_for_build = next(iter(hat_class_models.values()))
                    logger.info(
                        f"[HAT multiclass] классы для сборки: "
                        f"{list(hat_class_models.keys())}"
                    )

            # Сбрасываем запомненный выбор «применить ко всем» — каждая новая
            # сборка начинается без предыдущих предпочтений пользователя.
            self._extra_texture_apply_all: Optional[str] = None

            # Проверяем, не запущена ли уже сборка
            if self._worker_busy('_build_worker', 'build_already_running',
                                 'Build is already in progress. Please wait.'):
                return
            
            # Очищаем старый воркер: отключаем сигналы и удаляем
            self._dispose_build_worker()

            # Создаем и запускаем воркер для асинхронной сборки
            from src.services.build_worker import BuildWorker

            # Если пользователь загрузил BLU-текстуру в 2D панели — используем её
            # автоматически, без лишних вопросов.
            _blu_image = None
            if hasattr(self, 'preview_panel'):
                _blu_image = self.preview_panel.get_blu_image_path()
            _blu_mode = 'upload' if _blu_image else 'none'

            # Собираем все загруженные пользователем текстуры из 2D карточек.
            # Некоторые материалы (c_arrow, sniper_lens и т.п.) есть в 3D модели
            # но НЕ в QC skinfamilies → extra_texture_callback их не покрывает.
            # Передаём эти текстуры напрямую чтобы они попали в VPK.
            _panel_extra_textures: dict = {}
            if hasattr(self, 'preview_panel'):
                _panel_extra_textures = dict(
                    self.preview_panel.get_slot_image_paths()
                )
                # Убираем главную текстуру (col 0) — она уже в from_path
                main_key = (
                    self.preview_panel._material_names[0]
                    if self.preview_panel._material_names
                    else None
                )
                if main_key and main_key in _panel_extra_textures:
                    _panel_extra_textures.pop(main_key)

            # Стили (skinfamilies) кастомной модели: пользователь определил
            # доп-стили в полосе стилей → генерируем $texturegroup и варианты.
            # None, если стилей нет (обычная одно-скиновая сборка).
            _skin_build_data = None
            _replace_keep_materials = False
            if replace_model_enabled and hasattr(self, 'preview_panel'):
                _skin_build_data = self.preview_panel.get_skin_build_data()
                if _skin_build_data:
                    logger.info(
                        f"[SKIN BUILD] стили: {_skin_build_data['tg_overrides']}"
                    )
                # «Готовая» модель со своими материалами → не схлопывать в один.
                if hasattr(self.preview_panel, 'get_custom_keep_materials'):
                    _replace_keep_materials = self.preview_panel.get_custom_keep_materials()

            # Отредактированный пользователем QC (только для «готовой» модели).
            _custom_qc_text = None
            if _replace_keep_materials and hasattr(self, 'preview_panel') \
                    and hasattr(self.preview_panel, 'get_custom_qc_text'):
                _custom_qc_text = self.preview_panel.get_custom_qc_text()

            from src.services.build_request import BuildRequest
            _request = BuildRequest(
                image_path=from_path,
                mode=self.mode,
                filename=name,
                size=size,
                format_type=selected_format,
                flags=flags,
                vtf_options=vtf_options,
                tf2_root_dir=settings.get('tf2_game_folder', ''),
                export_folder=settings.get('export_folder', 'export'),
                keep_temp_on_error=settings.get('keep_temp_on_error', False),
                debug_mode=settings.get('debug_mode', False),
                replace_model_enabled=replace_model_enabled,
                replace_model_path=replace_model_smd_path,
                model_ready_path=model_ready_path,
                draw_uv_layout=draw_uv_layout,
                language=self.language,
                custom_vtf_path=custom_vtf_path,
                blu_mode=_blu_mode,
                blu_image_path=_blu_image,
                custom_vpk_source_path=getattr(self, '_custom_vpk_path', None),
                hat_mdl_path=hat_mdl_path_for_build,
                hat_apply_game_paints=hat_apply_game_paints,
                hat_class_models=hat_class_models,
                panel_extra_textures=_panel_extra_textures,
                material_maps=(self.preview_panel.get_texture_maps()
                               if hasattr(self, 'preview_panel') else {}),
                material_settings=(self.preview_panel.get_texture_overrides()
                                   if hasattr(self, 'preview_panel') else {}),
                skin_build_data=_skin_build_data,
                replace_keep_materials=_replace_keep_materials,
                custom_qc_text=_custom_qc_text,
            )
            # Без parent=self ! Если дать parent=self, Qt станет владельцем
            # и не удалит старый воркер при замене, и сигналы будут дублироваться.
            self._build_worker = BuildWorker(request=_request)
            
            # Подключаем сигналы
            self._build_worker.finished.connect(self._on_build_finished)
            self._build_worker.progress.connect(self._on_build_progress)
            self._build_worker.sub_progress.connect(self._on_build_sub_progress)
            self._build_worker.error.connect(self._on_build_error)
            self._build_worker.request_extra_texture.connect(self._on_request_extra_texture)
            # Запрос доп. частей модели (shell, scope и т.п.) остаётся через callback
            if replace_model_enabled and not model_ready_path:
                self._build_worker.request_extra_model.connect(self._on_request_extra_model)
            # Предупреждение о несовпадении текстур в SMD (режим «Модель уже готова»)
            if model_ready_enabled:
                self._build_worker.texture_mismatch_warning.connect(self._on_texture_mismatch_warning)
            
            # Создаём диалог, запускаем воркер, показываем, блокируем кнопку
            self._launch_progress(
                '_progress_dialog', self._build_worker, self._cancel_build,
                disable_button='button',
            )

        except Exception as e:
            ErrorHandler.show_error(self, e, self.t.get('build_error', 'Build error'), self.t['build_error'], language=self.language)
    
    def _on_build_finished(self, success: bool, message: str):
        """Обработчик завершения сборки"""
        self._close_progress('_progress_dialog', 'button')
        if success:
            success_title = self.t.get('build_success', 'Success')
            ErrorHandler.show_info(self, message, success_title)
        else:
            ErrorHandler.show_error(self, Exception(message), self.t.get('build_error', 'Build error'), self.t['build_error'], language=self.language)
    
    def _on_build_progress(self, percentage: int, status: str):
        """Обработчик прогресса сборки"""
        self._update_progress('_progress_dialog', percentage, status)

    def _on_build_sub_progress(self, percentage: int, label: str):
        """Обработчик детального прогресса текущего шага сборки"""
        if hasattr(self, '_progress_dialog') and self._progress_dialog:
            self._progress_dialog.set_sub_progress(percentage, label)

    def _on_build_error(self, error_message: str):
        """Обработчик ошибки сборки"""
        self._close_progress('_progress_dialog', 'button')
        ErrorHandler.show_error(self, Exception(error_message), self.t.get('build_error', 'Build error'), self.t.get('build_error', 'Build error'), language=self.language)
    
    def _cancel_build(self) -> None:
        """Отменяет сборку"""
        self._cancel_worker('_build_worker', '_progress_dialog')
    
    def _ask_extra_texture_choice(self, parent, display_name: str, weapon_key: str):
        """
        Показывает диалог выбора текстуры доп. материала (своя / из игры / основная).

        Returns:
            (choice, apply_to_all): choice ∈ {'custom','game','main'},
            apply_to_all — была ли отмечена галочка «применить ко всем».
        """
        from PySide6.QtWidgets import QMessageBox, QCheckBox as _QCheckBox
        from src.data.player_characters import PLAYER_BODY_MODE_KEYS
        is_ru = (getattr(self, 'language', 'en') == 'ru')

        if weapon_key in PLAYER_BODY_MODE_KEYS:
            msg_text = self.t.get(
                'extra_player_texture_question',
                'Apply your skin to the "{material}" texture as well?\n\n'
                'If you click "No", the main texture will be copied for this slot.'
            ).format(material=display_name)
        else:
            msg_text = self.t.get(
                'extra_texture_question',
                'The weapon model has an additional material: "{material}".\n'
                'Do you want to provide a separate image for it?\n\n'
                'If you click "No", the main texture will be used for this material.'
            ).format(material=display_name)

        msg_box = QMessageBox(parent)
        msg_box.setWindowTitle(self.t.get('extra_texture_title', 'Additional Texture'))
        msg_box.setText(msg_text)
        msg_box.setIcon(QMessageBox.Question)

        btn_custom = msg_box.addButton(
            self.t.get('extra_tex_btn_upload', 'Загрузить свою' if is_ru else 'Upload mine'),
            QMessageBox.AcceptRole,
        )
        btn_game = msg_box.addButton(
            self.t.get('extra_tex_btn_game', 'Использовать обычную' if is_ru else 'Use game original'),
            QMessageBox.ActionRole,
        )
        btn_main = msg_box.addButton(
            self.t.get('extra_tex_btn_main', 'Использовать основную' if is_ru else 'Use main texture'),
            QMessageBox.RejectRole,
        )
        msg_box.setDefaultButton(btn_main)

        apply_all_cb = _QCheckBox(
            self.t.get('extra_tex_apply_all', 'Применить ко всем оставшимся' if is_ru else 'Apply to all remaining')
        )
        msg_box.setCheckBox(apply_all_cb)
        msg_box.exec()

        clicked = msg_box.clickedButton()
        if clicked is btn_custom:
            choice = 'custom'
        elif clicked is btn_game:
            choice = 'game'
        else:
            choice = 'main'
        return choice, apply_all_cb.isChecked()

    def _on_request_extra_texture(self, material_name: str, weapon_key: str) -> None:
        """
        Обрабатывает запрос дополнительного изображения для материала модели.

        Сначала проверяет, загружено ли уже изображение для этого слота через
        карточку доп. слота в 2D превью (drag-drop или Browse). Если да — использует его
        без диалога. Иначе — показывает диалог с тремя вариантами:
          • «Загрузить свою» — выбрать файл изображения
          • «Использовать обычную» — взять текстуру прямо из игры (не добавлять в мод)
          • «Использовать основную» — скопировать основную текстуру для этого слота

        Галочка «Применить ко всем» запоминает выбор и применяет его ко всем
        последующим вопросам без повторных диалогов.
        """
        if not hasattr(self, '_build_worker'):
            return

        from src.shared.constants import EXTRA_TEX_USE_GAME_ORIGINAL

        # ── Проверяем уже загруженную текстуру из 2D-карточек ────────────────
        # get_uploaded_texture_for_mat проверяет оба словаря (_textures['red'] и
        # _textures['blu']) и делает обратный поиск через _vpk_blu_name_map для
        # случая когда build спрашивает BLU-имя ('medic_head_blue'), а карточка
        # хранит под RED-ключом ('medic_head_red') в _textures['blu'].
        pre_loaded: Optional[str] = None
        if hasattr(self, 'preview_panel'):
            pre_loaded = self.preview_panel.get_uploaded_texture_for_mat(material_name)
            if pre_loaded:
                logger.info(
                    f"extra_texture: уже загружена '{material_name}': {pre_loaded}"
                )

        if pre_loaded:
            if hasattr(self._build_worker, 'set_extra_texture_result'):
                self._build_worker.set_extra_texture_result(pre_loaded)
            return

        # ── Диалог должен появляться поверх окна прогресса ───────────────────
        _dialog_parent = (
            self._progress_dialog
            if hasattr(self, '_progress_dialog') and self._progress_dialog
            else self
        )

        # ── Человекочитаемое имя материала ────────────────────────────────────
        from src.data.player_characters import PLAYER_BODY_MODE_KEYS, get_player_body_extra_label
        lang = getattr(self, 'language', 'en')

        if weapon_key in PLAYER_BODY_MODE_KEYS:
            display_name = get_player_body_extra_label(weapon_key, material_name, lang)
        else:
            display_name = material_name

        # ── Apply-to-all: если уже есть запомненный выбор — применяем сразу ──
        _apply_all = getattr(self, '_extra_texture_apply_all', None)
        if _apply_all == 'game':
            logger.info(f"Apply-to-all (game): пропускаем '{material_name}'")
            if hasattr(self._build_worker, 'set_extra_texture_result'):
                self._build_worker.set_extra_texture_result(EXTRA_TEX_USE_GAME_ORIGINAL)
            return
        elif _apply_all == 'main':
            logger.info(f"Apply-to-all (main): '{material_name}' → основная текстура")
            if hasattr(self._build_worker, 'set_extra_texture_result'):
                self._build_worker.set_extra_texture_result(None)
            return
        elif _apply_all == 'custom':
            # Пропускаем вопрос — сразу открываем файловый диалог
            logger.info(f"Apply-to-all (custom): сразу выбираем файл для '{material_name}'")
            file_path = self._pick_extra_texture_file(_dialog_parent, display_name)
            if hasattr(self._build_worker, 'set_extra_texture_result'):
                self._build_worker.set_extra_texture_result(file_path)
            return

        # ── Спрашиваем пользователя через диалог ─────────────────────────────
        choice, apply_to_all = self._ask_extra_texture_choice(_dialog_parent, display_name, weapon_key)

        if apply_to_all:
            self._extra_texture_apply_all = choice
            logger.info(f"Apply-to-all установлен: '{choice}'")

        # ── Выполняем выбранное действие ──────────────────────────────────────
        if choice == 'custom':
            file_path = self._pick_extra_texture_file(_dialog_parent, display_name)
        elif choice == 'game':
            file_path = EXTRA_TEX_USE_GAME_ORIGINAL
        else:
            file_path = None

        if hasattr(self._build_worker, 'set_extra_texture_result'):
            self._build_worker.set_extra_texture_result(file_path)

    def _pick_extra_texture_file(self, parent, display_name: str) -> Optional[str]:
        """Открывает диалог выбора файла изображения для дополнительной текстуры."""
        dialog_title = self.t.get(
            'extra_texture_select',
            'Select image for "{material}"'
        ).format(material=display_name)

        file_path, _ = QFileDialog.getOpenFileName(
            parent,
            dialog_title,
            "",
            self.t.get('images_filter', 'Images') + " (*.png *.jpg *.jpeg *.bmp *.gif *.tga *.vtf);;All Files (*)"
        )
        return file_path if file_path else None

    def _on_request_extra_model(self, smd_name: str, weapon_key: str) -> None:
        """
        Обрабатывает запрос дополнительного SMD файла для части модели.
        Показывает диалог: хочет ли пользователь загрузить отдельную модель
        для дополнительной части (shell, scope и т.д.)
        """
        if not hasattr(self, '_build_worker'):
            return
        
        from PySide6.QtWidgets import QMessageBox
        
        msg_title = self.t.get('extra_model_title', 'Additional Model Part')
        msg_text = self.t.get(
            'extra_model_question',
            'The weapon has an additional model part: "{smd_name}".\n'
            'Do you want to provide a replacement SMD file for it?\n\n'
            'If you click "No", the original game model will be used for this part.'
        ).format(smd_name=smd_name)
        
        reply = QMessageBox.question(
            self,
            msg_title,
            msg_text,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        file_path = None
        if reply == QMessageBox.Yes:
            dialog_title = self.t.get(
                'extra_model_select',
                'Select SMD file for "{smd_name}"'
            ).format(smd_name=smd_name)
            
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                dialog_title,
                "",
                "SMD Files (*.smd);;All Files (*)"
            )
            if not file_path:
                file_path = None
        
        if hasattr(self._build_worker, 'set_extra_model_result'):
            self._build_worker.set_extra_model_result(file_path)

    def _on_texture_mismatch_warning(self, warning_message: str) -> None:
        """
        Обрабатывает предупреждение о несовпадении текстур в пользовательском SMD.
        Показывает диалог с подробностями, позволяет продолжить или отменить сборку.
        """
        if not hasattr(self, '_build_worker'):
            return

        from PySide6.QtWidgets import QMessageBox

        title = self.t.get('texture_mismatch_title', 'Texture Mismatch Warning')

        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Warning)
        msg_box.setWindowTitle(title)
        msg_box.setText(warning_message)

        btn_continue = msg_box.addButton(
            self.t.get('texture_mismatch_continue', 'Continue anyway'),
            QMessageBox.AcceptRole
        )
        btn_cancel = msg_box.addButton(
            self.t.get('texture_mismatch_cancel', 'Cancel build'),
            QMessageBox.RejectRole
        )
        msg_box.setDefaultButton(btn_cancel)
        msg_box.exec()

        decision = 'continue' if msg_box.clickedButton() == btn_continue else 'cancel'

        if hasattr(self._build_worker, 'set_texture_mismatch_result'):
            self._build_worker.set_texture_mismatch_result(decision)


    def extract_original_model(self) -> None:
        try:
            if not hasattr(self, 'mode') or not self.mode:
                ErrorHandler.show_warning(self, self.t['select_weapon_error'], self.t['error'])
                return

            from src.data.weapons import SPECIAL_MODES
            if self.mode in SPECIAL_MODES.values():
                error_msg = self.t.get('extract_model_special_mode_error', 'Cannot extract model for special modes')
                ErrorHandler.show_warning(self, error_msg, self.t['error'])
                return

            # Для режимов рук weapon_key — это ключ arm-модели (например "c_pyro_arms"),
            # для скинов персонажа — это ключ MDL модели (например "player_scout").
            from src.data.player_hands import HAND_MODE_KEYS, HAND_MODES
            from src.data.player_characters import PLAYER_BODY_MODE_KEYS, PLAYER_CHARACTERS
            if self.mode in HAND_MODE_KEYS:
                weapon_key = HAND_MODES[self.mode].get("arm_model", "")
                if not weapon_key:
                    ErrorHandler.show_warning(self, self.t.get('extract_model_special_mode_error', 'Cannot extract model for this mode'), self.t['error'])
                    return
            elif self.mode in PLAYER_BODY_MODE_KEYS:
                # Для персонажей weapon_key = полный MDL путь (как в 3D preview)
                weapon_key = PLAYER_CHARACTERS[self.mode].get("mdl_path", "")
                if not weapon_key:
                    ErrorHandler.show_warning(self, self.t.get('extract_model_special_mode_error', 'Cannot extract model for this mode'), self.t['error'])
                    return
            elif self.mode == "hat":
                weapon_key = getattr(self, '_hat_mdl_path', None)
                if not weapon_key:
                    ErrorHandler.show_warning(self, self.t.get('select_weapon_error', 'Select a hat first'), self.t['error'])
                    return
            else:
                weapon_key = weapon_key_from_mode(self.mode)

            settings = self.settings_panel.get_settings()
            tf2_root_dir = settings.get('tf2_game_folder', '')
            if not tf2_root_dir:
                error_msg = self.t.get('tf2_path_not_specified', 'TF2 path not specified in settings')
                ErrorHandler.show_warning(self, error_msg, self.t['error'])
                return

            export_folder = settings.get('export_folder', 'export')

            if self._worker_busy('_extract_model_worker', 'extract_model_already_running',
                                 'Model extraction is already in progress. Please wait.'):
                return

            from src.services.extract_model_worker import ExtractModelWorker

            # Мультиклассовая шапка → экспортируем модели ВСЕХ классов, а не только
            # первого найденного.
            hat_class_models = None
            if self.mode == "hat" and hasattr(self, 'hats_panel'):
                hat_class_models = self.hats_panel.get_all_class_models()

            self._extract_model_worker = ExtractModelWorker(
                tf2_root_dir=tf2_root_dir,
                mode=self.mode,
                weapon_key=weapon_key,
                language=self.language,
                hat_class_models=hat_class_models,
                parent=self
            )
            self._extract_model_export_folder = export_folder

            self._extract_model_worker.finished.connect(self._on_extract_model_finished)
            self._extract_model_worker.progress.connect(self._on_extract_model_progress)
            self._extract_model_worker.error.connect(self._on_extract_model_error)

            progress_title = self.t.get('extract_model_progress_title', 'Extract Model')
            progress_text  = self.t.get('extract_model_progress_text', 'Extracting model...')

            self._launch_progress(
                '_extract_model_progress_dialog', self._extract_model_worker,
                self._cancel_extract_model,
                title=progress_title, text=progress_text,
                disable_button='extract_model_button',
            )
        except Exception as e:
            ErrorHandler.show_error(self, e, "Ошибка при запуске извлечения модели", self.t['error'])

    def _on_extract_model_finished(self, success: bool, message: str) -> None:
        self._close_progress('_extract_model_progress_dialog', 'extract_model_button')
        if success:
            from src.services.extract_model_service import ExtractModelService

            prepared_files = []
            temp_dir = None
            decompile_dir = None
            if hasattr(self, '_extract_model_worker'):
                prepared_files = getattr(self._extract_model_worker, 'prepared_files', []) or []
                temp_dir = getattr(self._extract_model_worker, 'prepared_temp_dir', None)
                decompile_dir = getattr(self._extract_model_worker, 'prepared_decompile_dir', None)

            if not prepared_files or not temp_dir or not decompile_dir:
                if temp_dir:
                    ExtractModelService.cleanup_temp_dir(temp_dir)
                ErrorHandler.show_warning(self, message, self.t['error'])
                return

            from src.ui.model_export_dialog import ModelExportDialog

            dialog = ModelExportDialog(
                self,
                self.t.get('extract_model_select_title', 'Model Export'),
                self.t.get('extract_model_select_desc', 'Select files to save into export:'),
                prepared_files
            )
            dialog.set_button_texts(
                self.t.get('select_all', 'Select all'),
                self.t.get('deselect_all', 'Select none'),
                self.t.get('cancel', 'Cancel'),
                self.t.get('export_btn', 'Export')
            )

            if dialog.exec() != QDialog.Accepted:
                ExtractModelService.cleanup_temp_dir(temp_dir)
                ErrorHandler.show_warning(self, self.t.get('extract_model_cancelled', 'Cancelled'), self.t['error'])
                return

            selected = dialog.selected_files() or []
            if not selected:
                ExtractModelService.cleanup_temp_dir(temp_dir)
                ErrorHandler.show_warning(self, self.t.get('extract_model_nothing_selected', 'Nothing selected, export cancelled'), self.t['error'])
                return

            if hasattr(self, '_export_model_worker') and self._export_model_worker.isRunning():
                ExtractModelService.cleanup_temp_dir(temp_dir)
                ErrorHandler.show_warning(self, self.t.get('extract_model_already_running', 'Model extraction is already in progress. Please wait.'), self.t['error'])
                return

            from src.services.export_model_files_worker import ExportModelFilesWorker
            self._export_model_worker = ExportModelFilesWorker(
                temp_dir=temp_dir,
                decompile_dir=decompile_dir,
                selected_files=selected,
                export_folder=getattr(self, '_extract_model_export_folder', 'export'),
                weapon_key=getattr(self, '_extract_model_worker', None).weapon_key if hasattr(self, '_extract_model_worker') else "",
                language=self.language,
                parent=self
            )

            self._export_model_worker.finished.connect(self._on_export_model_finished)
            self._export_model_worker.progress.connect(self._on_export_model_progress)
            self._export_model_worker.error.connect(self._on_export_model_error)

            progress_title = self.t.get('extract_model_select_title', 'Model Export')
            progress_text  = self.t.get('extract_model_exporting', 'Exporting model files...')

            self._launch_progress(
                '_export_model_progress_dialog', self._export_model_worker,
                title=progress_title, text=progress_text,
                disable_button='extract_model_button', cancellable=False,
            )
        else:
            ErrorHandler.show_warning(self, message, self.t['error'])

    def _on_extract_model_progress(self, percentage: int, status: str) -> None:
        self._update_progress('_extract_model_progress_dialog', percentage, status)

    def _on_extract_model_error(self, error_message: str) -> None:
        self._close_progress('_extract_model_progress_dialog', 'extract_model_button')
        ErrorHandler.show_error(self, Exception(error_message), "Ошибка извлечения модели", self.t['error'])

    def _cancel_extract_model(self) -> None:
        self._cancel_worker('_extract_model_worker')

    def _on_export_model_finished(self, success: bool, message: str) -> None:
        self._close_progress('_export_model_progress_dialog', 'extract_model_button')
        if success:
            success_title = self.t.get('success', 'Success')
            ErrorHandler.show_info(self, message, success_title)
        else:
            ErrorHandler.show_warning(self, message, self.t['error'])

    def _on_export_model_progress(self, percentage: int, status: str) -> None:
        self._update_progress('_export_model_progress_dialog', percentage, status)

    def _on_export_model_error(self, error_message: str) -> None:
        self._close_progress('_export_model_progress_dialog', 'extract_model_button')
        ErrorHandler.show_error(self, Exception(error_message), "Ошибка экспорта модели", self.t['error'])

    def extract_original_texture(self) -> None:
        """Запускает асинхронное извлечение оригинальной текстуры оружия/рук/шапки из игры"""
        try:
            if not hasattr(self, 'mode') or not self.mode:
                ErrorHandler.show_warning(self, self.t['select_weapon_error'], self.t['error'])
                return

            from src.data.weapons import SPECIAL_MODES
            if self.mode in SPECIAL_MODES.values():
                error_msg = self.t.get('extract_texture_special_mode_error', 'Cannot extract texture for special modes')
                ErrorHandler.show_warning(self, error_msg, self.t['error'])
                return

            from src.data.player_hands import HAND_MODE_KEYS
            from src.data.player_characters import PLAYER_BODY_MODE_KEYS
            if self.mode == "hat":
                self._extract_hat_texture()
            else:
                self._extract_weapon_or_body_texture(
                    is_hands=self.mode in HAND_MODE_KEYS,
                    is_player_body=self.mode in PLAYER_BODY_MODE_KEYS,
                )
        except Exception as e:
            ErrorHandler.show_error(self, e, "Ошибка при запуске извлечения текстуры", self.t['error'])

    def _extract_hat_texture(self) -> None:
        """Извлекает оригинальную текстуру шапки (отдельный воркер, как в 3D Preview)."""
        hat_mdl = getattr(self, '_hat_mdl_path', '')
        if not hat_mdl:
            ErrorHandler.show_warning(
                self, self.t.get('select_weapon_error', 'Select a hat first'), self.t['error']
            )
            return

        settings = self.settings_panel.get_settings()
        tf2_root_dir = settings.get('tf2_game_folder', '')
        if not tf2_root_dir:
            ErrorHandler.show_warning(
                self, self.t.get('tf2_path_not_specified', 'TF2 path not specified'), self.t['error']
            )
            return

        export_folder = settings.get('export_folder', 'export')
        from src.config.app_config import AppConfig
        export_format = AppConfig.load_config().get('export_image_format', 'PNG')

        if self._worker_busy('_extract_worker', 'extract_already_running',
                             'Extraction is already in progress.'):
            return

        from src.services.hat_texture_extract_worker import HatTextureExtractWorker
        self._extract_worker = HatTextureExtractWorker(
            hat_mdl_path=hat_mdl,
            tf2_root_dir=tf2_root_dir,
            export_folder=export_folder,
            export_format=export_format,
            language=self.language,
            parent=self,
        )
        self._extract_worker.finished.connect(self._on_extract_finished)
        self._extract_worker.progress.connect(self._on_extract_progress)
        self._extract_worker.error.connect(self._on_extract_error)

        self._launch_progress(
            '_extract_progress_dialog', self._extract_worker, self._cancel_extract,
            title=self.t.get('extract_progress_title', 'Extract Texture'),
            text=self.t.get('extract_progress_text', 'Extracting texture...'),
            disable_button='extract_texture_button',
        )

    def _extract_weapon_or_body_texture(self, is_hands: bool, is_player_body: bool) -> None:
        """Извлекает текстуру обычного оружия / рук / скина персонажа из игрового VPK."""
        from src.data.player_hands import get_hand_textures
        if is_hands:
            hand_textures = get_hand_textures(self.mode)
        elif is_player_body:
            hand_textures = None   # будет заполнено после диалога
        else:
            hand_textures = None

        # Для рук используем arm_model как weapon_key — именно под ним
        # хранится QC в кэше декомпила. Простой split даёт "hands" вместо "c_scout_arms".
        if is_hands:
            from src.data.player_hands import HAND_MODES as _HAND_MODES
            weapon_key = _HAND_MODES.get(self.mode, {}).get("arm_model", "") or (
                weapon_key_from_mode(self.mode)
            )
        else:
            weapon_key = weapon_key_from_mode(self.mode)

        # Получаем путь к TF2
        settings = self.settings_panel.get_settings()
        tf2_root_dir = settings.get('tf2_game_folder', '')

        if not tf2_root_dir:
            error_msg = self.t.get('tf2_path_not_specified', 'TF2 path not specified in settings')
            ErrorHandler.show_warning(self, error_msg, self.t['error'])
            return

        # Получаем путь к tf2_textures_dir.vpk
        from src.services.tf2_paths import TF2Paths
        textures_vpk = TF2Paths.resolve_textures_vpk(tf2_root_dir)

        if not textures_vpk:
            error_msg = self.t.get('textures_vpk_not_found', 'tf2_textures_dir.vpk not found')
            ErrorHandler.show_warning(self, error_msg, self.t['error'])
            return

        # Для персонажей — показываем диалог выбора текстур (нужен textures_vpk)
        if is_player_body:
            from src.ui.texture_select_dialog import TextureSelectDialog
            from PySide6.QtWidgets import QDialog as _QDialog
            dlg = TextureSelectDialog(
                mode=self.mode,
                textures_vpk_path=textures_vpk,
                language=self.language,
                parent=self,
            )
            if dlg.exec() != _QDialog.DialogCode.Accepted:
                return
            hand_textures = dlg.get_selected_textures()
            if not hand_textures:
                return

        # Получаем папку экспорта и формат
        export_folder = settings.get('export_folder', 'export')
        from src.config.app_config import AppConfig
        config = AppConfig.load_config()
        export_format = config.get('export_image_format', 'PNG')

        # Проверяем, не запущено ли уже извлечение
        if self._worker_busy('_extract_worker', 'extract_already_running',
                             'Extraction is already in progress. Please wait.'):
            return

        # Создаем и запускаем воркер для асинхронного извлечения
        from src.services.extract_texture_worker import ExtractTextureWorker

        self._extract_worker = ExtractTextureWorker(
            textures_vpk_path=textures_vpk,
            weapon_key=weapon_key,
            export_folder=export_folder,
            export_format=export_format,
            language=self.language,
            hand_textures=hand_textures,
            use_explicit_list=is_player_body or is_hands,
            parent=self
        )
            
        # Подключаем сигналы
        self._extract_worker.finished.connect(self._on_extract_finished)
        self._extract_worker.progress.connect(self._on_extract_progress)
        self._extract_worker.error.connect(self._on_extract_error)
            
        # Создаем и показываем прогресс-диалог
        self._launch_progress(
            '_extract_progress_dialog', self._extract_worker, self._cancel_extract,
            title=self.t.get('extract_progress_title', 'Extract Texture'),
            text=self.t.get('extract_progress_text', 'Extracting texture...'),
            disable_button='extract_texture_button',
        )

    def _on_extract_finished(self, success: bool, message: str) -> None:
        """Обработчик завершения извлечения текстуры"""
        self._close_progress('_extract_progress_dialog', 'extract_texture_button')
        if success:
            success_title = self.t.get('success', 'Success')
            ErrorHandler.show_info(self, message, success_title)
        else:
            ErrorHandler.show_warning(self, message, self.t['error'])

    def _on_extract_progress(self, percentage: int, status: str):
        """Обработчик прогресса извлечения текстуры"""
        self._update_progress('_extract_progress_dialog', percentage, status)

    def _on_extract_error(self, error_message: str):
        """Обработчик ошибки извлечения текстуры"""
        self._close_progress('_extract_progress_dialog', 'extract_texture_button')
        ErrorHandler.show_error(self, Exception(error_message), "Ошибка извлечения текстуры", self.t['error'])
    
    def _cancel_extract(self) -> None:
        """Отменяет извлечение текстуры"""
        self._cancel_worker('_extract_worker')
    
    def _ask_merge_filename(self) -> Optional[str]:
        """Стилизованный диалог ввода имени выходного VPK файла."""
        from src.ui.styled_dialog import StyledDialog
        from PySide6.QtWidgets import QVBoxLayout, QLabel, QLineEdit, QPushButton
        from src.shared.validators import validate_vpk_filename

        is_ru = self.language == 'ru'
        dlg = StyledDialog(self,
                           title=self.t.get('merge_vpk_title', 'Merge Mods'),
                           width=420)
        c = dlg._c
        root = QVBoxLayout(dlg)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(dlg.make_header(
            self.t.get('merge_vpk_title', 'Merge Mods'),
            subtitle=self.t.get('enter_output_filename', 'Enter output file name'),
        ))

        body = QVBoxLayout()
        body.setContentsMargins(20, 20, 20, 16)
        body.setSpacing(8)

        hint = QLabel(self.t.get('enter_output_filename', 'Output file name:'))
        hint.setStyleSheet(f"color:{c['text_sub']}; font-size:11px;")
        body.addWidget(hint)

        edit = QLineEdit("merged_mod")
        edit.setFixedHeight(34)
        edit.selectAll()
        edit.setStyleSheet(f"""
            QLineEdit {{
                background: rgba(255,255,255,0.04); color: {c['text']};
                border: 1px solid {c['border']}; border-radius: 4px;
                padding: 0 10px; font-size: 13px;
            }}
            QLineEdit:focus {{ border-color: {c['border_h']}; }}
        """)
        body.addWidget(edit)

        err_lbl = QLabel("")
        err_lbl.setStyleSheet(f"color:#c04040; font-size:10px;")
        body.addWidget(err_lbl)

        root.addLayout(body)
        root.addWidget(dlg.divider())

        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton(self.t.get('cancel', 'Cancel'))

        def _try_accept():
            name = edit.text().strip()
            if not name:
                err_lbl.setText("Введите имя файла" if is_ru else "Enter file name")
                return
            if not name.endswith('.vpk'):
                name += '.vpk'
            valid, msg = validate_vpk_filename(name)
            if not valid:
                err_lbl.setText(msg)
                return
            dlg._result_name = name
            dlg.accept()

        edit.returnPressed.connect(_try_accept)
        ok_btn.clicked.connect(_try_accept)
        cancel_btn.clicked.connect(dlg.reject)

        root.addWidget(dlg.make_footer([cancel_btn, ok_btn]))

        dlg._result_name = None
        if dlg.exec():
            return dlg._result_name
        return None

    def merge_vpk_files(self) -> None:
        """Открывает диалог объединения VPK файлов"""
        from src.ui.merge_vpk_dialog import MergeVPKDialog
        from src.services.merge_vpk_service import MergeVPKService
        from src.shared.validators import validate_vpk_filename
        
        # Открываем диалог выбора модов
        dialog = MergeVPKDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        
        # Получаем выбранные файлы
        selected_files = dialog.get_selected_files()
        if not selected_files:
            ErrorHandler.show_warning(self, self.t.get('no_vpk_files_selected', 'No VPK files selected'), self.t['error'])
            return
        
        # Запрашиваем имя выходного файла — стилизованный диалог
        filename = self._ask_merge_filename()
        if not filename:
            return

        # Получаем настройки
        settings = self.settings_panel.get_settings()
        export_folder = settings.get('export_folder', 'export')
        
        # Проверяем наличие дубликатов оружий
        duplicates = MergeVPKService.check_duplicate_weapons(selected_files)
        if duplicates:
            # Формируем сообщение о дубликатах
            duplicate_msg = self.t.get('duplicate_weapons_warning', 
                'Обнаружены дубликаты оружий:\n\n')
            
            for weapon_name, vpk_files in duplicates.items():
                duplicate_msg += f"• {weapon_name}: {', '.join(vpk_files)}\n"
            
            duplicate_msg += "\n" + self.t.get('duplicate_weapons_question', 
                'Вы пытаетесь соединить моды, которые влияют на одно оружие.\nПродолжить?')
            
            # Показываем диалог подтверждения
            reply = QMessageBox.question(
                self,
                self.t.get('duplicate_weapons_title', 'Дубликаты оружий'),
                duplicate_msg,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.No:
                return  # Останавливаем процесс
        
        # Проверяем, не запущено ли уже объединение
        if self._worker_busy('_merge_worker', 'merge_already_running',
                             'Объединение уже выполняется. Пожалуйста, подождите.'):
            return
        
        # Выполняем объединение в отдельном потоке
        from src.services.merge_vpk_worker import MergeVpkWorker
        self._merge_worker = MergeVpkWorker(selected_files, filename, export_folder, self.language)
        self._merge_worker.finished.connect(self._on_merge_finished)
        self._merge_worker.progress.connect(self._on_merge_progress)

        # Создаём диалог, запускаем воркер, показываем, блокируем кнопку
        self._launch_progress(
            '_merge_progress_dialog', self._merge_worker, self._cancel_merge,
            title=self.t.get('merge_vpk_title', 'Merge Mods'),
            text=self.t.get('merge_vpk_progress', 'Merging VPK files...'),
            disable_button='merge_vpk_button',
        )
    
    def _on_merge_finished(self, success: bool, message: str):
        """Обработчик завершения объединения VPK"""
        self._close_progress('_merge_progress_dialog', 'merge_vpk_button')
        if success:
            ErrorHandler.show_info(self, message, self.t.get('merge_vpk_title', 'Объединить моды'))
        else:
            cancelled_msg = self.t.get('merge_cancelled', 'Объединение отменено пользователем')
            if message == cancelled_msg:
                ErrorHandler.show_info(self, cancelled_msg, self.t.get('cancel', 'Cancel'))
            else:
                ErrorHandler.show_error(self, Exception(message), "Ошибка объединения VPK", self.t['error'])
    
    def _on_merge_progress(self, percentage: int, status: str):
        """Обработчик прогресса объединения VPK"""
        self._update_progress('_merge_progress_dialog', percentage, status)
    
    def _cancel_merge(self) -> None:
        """Отменяет объединение VPK"""
        self._cancel_worker('_merge_worker')
    
    def open_support_link(self) -> None:
        QDesktopServices.openUrl(QUrl("https://steamcommunity.com/tradeoffer/new/?partner=394814324&token=GNGCagXk"))
    
    def closeEvent(self, event) -> None:
        """Сохраняем геометрию окна перед закрытием."""
        from src.config.app_config import AppConfig
        geom_b64 = self.saveGeometry().toBase64().data().decode()
        AppConfig.set('window_geometry', geom_b64)
        super().closeEvent(event)

    def open_settings_dialog(self) -> None:
        """Открывает диалог настроек"""
        dialog = SettingsDialog(self)
        dialog.exec()

    def set_language(self, lang):
        self.language = lang
        self.t = TRANSLATIONS[lang]
        self.settings_panel.update_language(self.t)
        self.update_ui_text()
    
    def on_advanced_section_toggled(self, is_expanded):
        """Обработка сворачивания/разворачивания секции Дополнительно"""
        # Даём время на обновление layout
        from PySide6.QtCore import QTimer
        QTimer.singleShot(50, self._adjust_window_size)
    
    def _adjust_window_size(self) -> None:
        """Пересчитывает и применяет оптимальный размер окна"""
        if self.isMaximized() or self.isFullScreen():
            self.centralWidget().updateGeometry()
            self.centralWidget().layout().activate()
            return

        # Обновляем layout
        self.centralWidget().updateGeometry()
        self.centralWidget().layout().activate()
        
        # Учитываем minimumSizeHint, иначе высота окна может быть меньше блока Step 2: Export
        cw = self.centralWidget()
        hint = cw.sizeHint()
        min_hint = cw.minimumSizeHint()
        needed_h = max(hint.height(), min_hint.height()) + 20

        # Применяем новый размер с сохранением ширины
        current_width = self.width()
        new_height = max(needed_h, 600)

        screen = self.screen()
        if screen:
            available = screen.availableGeometry()
            new_height = min(new_height, available.height())
        
        self.resize(current_width, new_height)


# ── Иконка шестерёнки для кнопки настроек ────────────────────────────────── #

def _make_gear_icon(color: str = "#585858", size: int = 16):
    """
    Рисует заполненную шестерёнку с 6 зубьями и центральным отверстием.
    Стиль совпадает с остальными QPainter-иконками приложения.
    """
    import math
    from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QPainterPath
    from PySide6.QtCore import Qt, QRectF

    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)

    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))

    s  = float(size)
    cx = cy = s / 2.0

    n_teeth = 6
    r_outer = s * 0.455   # кончик зуба
    r_base  = s * 0.305   # основание зуба
    r_hole  = s * 0.150   # центральное отверстие
    half_tw = 0.285        # полуширина зуба (рад)

    step = 2.0 * math.pi / n_teeth
    path = QPainterPath()
    first = True

    for i in range(n_teeth):
        # Начинаем сверху (−π/2) для симметрии
        center = i * step - math.pi / 2.0
        for r, da in [
            (r_base,  -(half_tw + 0.18)),   # вход основания
            (r_outer, -half_tw * 0.52),     # начало зуба
            (r_outer,  half_tw * 0.52),     # конец зуба
            (r_base,   (half_tw + 0.18)),   # выход основания
        ]:
            x = cx + r * math.cos(center + da)
            y = cy + r * math.sin(center + da)
            if first:
                path.moveTo(x, y)
                first = False
            else:
                path.lineTo(x, y)

    path.closeSubpath()

    # Вырезаем центральное отверстие
    hole = QPainterPath()
    hole.addEllipse(QRectF(cx - r_hole, cy - r_hole, r_hole * 2, r_hole * 2))

    p.drawPath(path.subtracted(hole))
    p.end()
    return QIcon(pix)
    
