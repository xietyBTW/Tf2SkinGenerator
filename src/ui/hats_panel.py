"""
Панель выбора шапок/косметики TF2 с умным поиском.

Загружает данные из items_game.txt (через hats_parser), кэширует,
отображает список с live-поиском и фильтром по классу.
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal, QThread, QTimer, QRect, QSize
from PySide6.QtGui import QColor, QPainter, QFont, QFontMetrics
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem,
    QStyledItemDelegate, QStyle,
)

from src.data.hats_parser import HatItem, parse_hats, get_items_game_path
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# ── Классы TF2 ────────────────────────────────────────────────────────────── #

_CLASSES = [
    ("all",      "All"),
    ("scout",    "Scout"),
    ("soldier",  "Soldier"),
    ("pyro",     "Pyro"),
    ("demoman",  "Demo"),
    ("heavy",    "Heavy"),
    ("engineer", "Engi"),
    ("medic",    "Medic"),
    ("sniper",   "Sniper"),
    ("spy",      "Spy"),
]

_I18N = {
    "ru": {
        "title":       "КОСМЕТИКА",
        "subtitle":    "Выберите шапку или аксессуар",
        "search_hint": "Поиск по названию...",
        "loading":     "Загрузка предметов из TF2...",
        "no_tf2":      "Укажите путь к TF2 в настройках",
        "no_results":  "Ничего не найдено",
        "all_classes": "Все классы",
        "n_items":     "{n} предметов",
        "refresh":     "Обновить",
        "build_classes": "Классы для сборки:",
    },
    "en": {
        "title":       "COSMETICS",
        "subtitle":    "Select a hat or accessory",
        "search_hint": "Search by name...",
        "loading":     "Loading items from TF2...",
        "no_tf2":      "Set TF2 path in Settings",
        "no_results":  "No results found",
        "all_classes": "All classes",
        "n_items":     "{n} items",
        "refresh":     "Refresh",
        "build_classes": "Build for classes:",
    },
}


# ── Фоновая загрузка ──────────────────────────────────────────────────────── #

class _LoadWorker(QThread):
    """Фоновый поток для парсинга items_game.txt."""
    progress = Signal(int, str)
    finished = Signal(object)   # List[HatItem] — object безопаснее для Python объектов при cross-thread
    error    = Signal(str)

    def __init__(self, tf2_root: str, language: str, force: bool = False):
        super().__init__()
        self._root  = tf2_root
        self._lang  = language
        self._force = force

    def run(self) -> None:
        try:
            items = parse_hats(
                self._root,
                language=self._lang,
                force_reparse=self._force,
                progress_cb=self.progress.emit,
            )
            self.finished.emit(items)
        except Exception as e:
            logger.error(f"Ошибка загрузки шапок: {e}", exc_info=True)
            self.error.emit(str(e))


# ── Делегат отрисовки ─────────────────────────────────────────────────────── #

class _HatDelegate(QStyledItemDelegate):
    """Рисует каждый элемент шапки: название + классы."""

    def __init__(self, accent: str, parent=None):
        super().__init__(parent)
        self._accent = accent

    def paint(self, painter: QPainter, option, index) -> None:
        hat: Optional[HatItem] = index.data(Qt.ItemDataRole.UserRole)
        if hat is None:
            super().paint(painter, option, index)
            return

        painter.save()
        rect = option.rect

        # Фон
        is_selected = bool(option.state & QStyle.State_Selected)
        is_hover    = bool(option.state & QStyle.State_MouseOver)

        if is_selected:
            painter.fillRect(rect, QColor(self._accent + "22"))
        elif is_hover:
            painter.fillRect(rect, QColor("#ffffff10"))
        else:
            painter.fillRect(rect, QColor("#00000000"))

        # Левая акцентная полоска при выборе
        if is_selected:
            painter.fillRect(QRect(rect.x(), rect.y(), 3, rect.height()), QColor(self._accent))

        pad_l = 18 if is_selected else 14
        pad_t = 7

        # Название
        name_font = QFont()
        name_font.setPointSize(10)
        name_font.setWeight(QFont.Weight.Medium)
        painter.setFont(name_font)
        painter.setPen(QColor("#ffffff" if is_selected else "#cccccc"))
        name_rect = QRect(rect.x() + pad_l, rect.y() + pad_t, rect.width() - pad_l - 8, 20)
        elided = QFontMetrics(name_font).elidedText(hat.name, Qt.TextElideMode.ElideRight, name_rect.width())
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)

        # Классы
        cls_font = QFont()
        cls_font.setPointSize(9)
        painter.setFont(cls_font)
        painter.setPen(QColor(self._accent + "aa" if is_selected else "#555555"))
        cls_rect = QRect(rect.x() + pad_l, rect.y() + pad_t + 20, rect.width() - pad_l - 8, 16)
        painter.drawText(cls_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, hat.classes_str)

        # Разделитель
        painter.setPen(QColor("#1e1e1e"))
        painter.drawLine(rect.x(), rect.bottom(), rect.right(), rect.bottom())

        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(0, 52)


# ── Главная панель ────────────────────────────────────────────────────────── #

class HatsPanel(QWidget):
    """
    Панель выбора шапок с поиском и фильтром по классу.

    Сигналы:
        hat_selected(mdl_path, display_name)  — пользователь выбрал шапку
        hat_deselected()                      — выбор снят
    """

    hat_selected    = Signal(str, str)  # (mdl_path, display_name)
    hat_deselected  = Signal()

    def __init__(self, parent=None, language: str = "en"):
        super().__init__(parent)
        self._language      = language if language in _I18N else "en"
        self._t             = _I18N[self._language]
        self._accent        = self._get_accent()
        self._all_hats: List[HatItem] = []
        self._class_filter  = "all"
        self._load_worker: Optional[_LoadWorker] = None
        self._selected_hat: Optional[HatItem]    = None

        # Состояние выпадающего списка классов (мультиклассовые шапки).
        # Раскрыт максимум у одной шапки за раз.
        self._dropdown_item: Optional[QListWidgetItem] = None
        self._dropdown_hat: Optional[HatItem]          = None
        self._class_chip_btns: dict = {}      # класс → QPushButton-чип
        self._selected_classes: dict = {}     # класс → отмечен (bool)

        # Таймер debounce для поиска: 150 мс после последнего ввода
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(self._apply_filter)

        self._build_ui()

    # ── Стили ─────────────────────────────────────────────────────────────── #

    @staticmethod
    def _get_accent() -> str:
        try:
            from src.config.app_config import AppConfig
            return "#4a90e2" if AppConfig.load_config().get("theme") == "blue" else "#ff6b35"
        except Exception:
            return "#ff6b35"

    # ── Построение UI ─────────────────────────────────────────────────────── #

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.setContentsMargins(0, 4, 0, 0)

        # Заголовок
        title = QLabel(self._t["title"])
        title.setObjectName("hats_title")
        title.setStyleSheet(f"""
            QLabel#hats_title {{
                color: {self._accent};
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 3px;
                background: transparent;
                border: none;
                padding: 0;
            }}
        """)
        lay.addWidget(title)

        sub = QLabel(self._t["subtitle"])
        sub.setObjectName("hats_sub")
        sub.setStyleSheet("""
            QLabel#hats_sub {
                color: #444;
                font-size: 11px;
                background: transparent;
                border: none;
                padding: 0;
                margin-bottom: 4px;
            }
        """)
        lay.addWidget(sub)

        # Строка поиска
        search_row = QHBoxLayout()
        search_row.setSpacing(6)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText(self._t["search_hint"])
        self._search_input.setMinimumHeight(32)
        self._search_input.setObjectName("hats_search")
        self._search_input.setStyleSheet(f"""
            QLineEdit#hats_search {{
                background: rgba(255,255,255,0.03);
                border: 1px solid #252525;
                border-radius: 4px;
                color: #cccccc;
                font-size: 12px;
                font-family: 'Segoe UI', Arial;
                padding: 0 10px;
            }}
            QLineEdit#hats_search:focus {{
                border-color: {self._accent};
                background: rgba(255,255,255,0.05);
            }}
        """)
        # textEdited не срабатывает при setText из кода — только на реальный ввод пользователя
        # textChanged срабатывает всегда; оба подходят, textChanged надёжнее
        self._search_input.textChanged.connect(self._on_search_text_changed)
        search_row.addWidget(self._search_input)

        self._refresh_btn = QPushButton("↺")
        self._refresh_btn.setFixedSize(32, 32)
        self._refresh_btn.setToolTip(self._t["refresh"])
        self._refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_btn.setObjectName("hats_refresh")
        self._refresh_btn.setStyleSheet(f"""
            QPushButton#hats_refresh {{
                background: transparent;
                border: 1px solid #252525;
                border-radius: 4px;
                color: #444;
                font-size: 14px;
                padding: 0;
                text-transform: none;
                letter-spacing: 0;
            }}
            QPushButton#hats_refresh:hover {{
                border-color: {self._accent};
                color: {self._accent};
            }}
        """)
        self._refresh_btn.clicked.connect(self._force_reload)
        search_row.addWidget(self._refresh_btn)

        lay.addLayout(search_row)

        # Фильтр по классу — две строки по 5 кнопок (All+Scout+Soldier+Pyro+Demo / Heavy+Engi+Medic+Sniper+Spy)
        self._class_btns: dict = {}
        class_outer = QWidget()
        class_outer.setStyleSheet("background: transparent;")
        class_vlay = QVBoxLayout(class_outer)
        class_vlay.setContentsMargins(0, 0, 0, 0)
        class_vlay.setSpacing(4)

        for row_slice in (_CLASSES[:5], _CLASSES[5:]):
            row_hlay = QHBoxLayout()
            row_hlay.setContentsMargins(0, 0, 0, 0)
            row_hlay.setSpacing(4)
            for key, label in row_slice:
                btn = QPushButton(label)
                btn.setCheckable(True)
                btn.setChecked(key == "all")
                btn.setFixedHeight(26)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setStyleSheet(self._chip_style(active=(key == "all")))
                btn.clicked.connect(lambda checked, k=key: self._set_class_filter(k))
                self._class_btns[key] = btn
                row_hlay.addWidget(btn)
            row_hlay.addStretch()
            class_vlay.addLayout(row_hlay)

        lay.addWidget(class_outer)

        # Список шапок
        self._list = QListWidget()
        self._list.setMouseTracking(True)   # нужно для State_MouseOver в делегате
        self._list.setItemDelegate(_HatDelegate(self._accent, self._list))
        self._list.setStyleSheet("""
            QListWidget {
                background: transparent;
                border: 1px solid #1a1a1a;
                border-radius: 4px;
                outline: none;
            }
            QListWidget::item {
                background: transparent;
                border: none;
                padding: 0;
            }
            QListWidget::item:selected {
                background: transparent;
            }
            QListWidget::item:hover {
                background: transparent;
            }
        """)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.currentItemChanged.connect(self._on_item_changed)
        lay.addWidget(self._list, 1)

        # Статусная строка
        self._status_lbl = QLabel("")
        self._status_lbl.setObjectName("hats_status")
        self._status_lbl.setStyleSheet("""
            QLabel#hats_status {
                color: #333;
                font-size: 10px;
                background: transparent;
                border: none;
                padding: 0;
            }
        """)
        lay.addWidget(self._status_lbl)

        # Placeholder (загрузка / ошибка / нет результатов)
        self._placeholder = QLabel(self._t["loading"])
        self._placeholder.setObjectName("hats_placeholder")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("""
            QLabel#hats_placeholder {
                color: #333;
                font-size: 12px;
                background: transparent;
                border: none;
                padding: 20px;
            }
        """)
        self._placeholder.setWordWrap(True)
        lay.addWidget(self._placeholder)

        # Изначально — только placeholder; список скрыт
        self._list.hide()
        self._status_lbl.hide()

    def _chip_style(self, active: bool = False) -> str:
        if active:
            return f"""
                QPushButton {{
                    background: {self._accent}22;
                    border: 1px solid {self._accent};
                    border-radius: 3px;
                    color: {self._accent};
                    font-size: 10px;
                    font-weight: 600;
                    padding: 0 7px;
                    text-transform: none;
                    letter-spacing: 0;
                }}
            """
        return """
            QPushButton {
                background: transparent;
                border: 1px solid #252525;
                border-radius: 3px;
                color: #444;
                font-size: 10px;
                font-weight: 400;
                padding: 0 7px;
                text-transform: none;
                letter-spacing: 0;
            }
            QPushButton:hover {
                border-color: #444;
                color: #777;
            }
        """

    # ── Обработка ввода поиска ────────────────────────────────────────────── #

    def _on_search_text_changed(self, text: str) -> None:
        """Запускает таймер debounce при каждом изменении текста."""
        self._search_timer.start()

    # ── Загрузка данных ───────────────────────────────────────────────────── #

    def load_hats(self, tf2_root: str, force: bool = False) -> None:
        """Запускает загрузку шапок из items_game.txt (фоновый поток)."""
        if not tf2_root or not get_items_game_path(tf2_root):
            self._show_placeholder(self._t["no_tf2"])
            return

        # Если данные уже загружены и не требуется принудительная перезагрузка — не перезапускаем
        if self._all_hats and not force:
            return

        if self._load_worker and self._load_worker.isRunning():
            return

        self._show_placeholder(self._t["loading"])
        self._load_worker = _LoadWorker(tf2_root, self._language, force)
        self._load_worker.progress.connect(self._on_load_progress)
        self._load_worker.finished.connect(self._on_load_finished)
        self._load_worker.error.connect(self._on_load_error)
        self._load_worker.start()

    def _force_reload(self) -> None:
        """Принудительная перезагрузка (игнорирует кэш)."""
        from src.config.app_config import AppConfig
        tf2_root = AppConfig.load_config().get("tf2_game_folder", "")
        self.load_hats(tf2_root, force=True)

    def _on_load_progress(self, pct: int, msg: str) -> None:
        self._show_placeholder(f"{msg} ({pct}%)")

    def _on_load_finished(self, items: object) -> None:
        self._all_hats = list(items) if items else []
        logger.info(f"Шапки загружены: {len(self._all_hats)} предметов")
        self._show_list()
        self._apply_filter()

    def _on_load_error(self, msg: str) -> None:
        self._show_placeholder(f"Error: {msg}")

    # ── Фильтрация ────────────────────────────────────────────────────────── #

    def _apply_filter(self) -> None:
        query      = self._search_input.text().strip().lower()
        words      = query.split() if query else []
        cls_filter = self._class_filter

        # Блокируем сигналы списка во время перестройки, чтобы не слать hat_deselected
        # при каждом clear() во время набора текста в поиске
        self._list.blockSignals(True)
        # Выпадающий список классов уничтожается вместе с clear() — сбрасываем ссылки.
        self._dropdown_item = None
        self._dropdown_hat = None
        self._class_chip_btns = {}
        self._selected_classes = {}
        self._list.clear()

        matched = [h for h in self._all_hats if h.matches(words, cls_filter)]

        # Сортировка по релевантности когда есть запрос
        if words:
            matched.sort(key=lambda h: (h.relevance(words), h.name.lower()))

        for hat in matched:
            item = QListWidgetItem(hat.name)              # текст как fallback
            item.setData(Qt.ItemDataRole.UserRole, hat)   # основные данные для делегата
            item.setSizeHint(QSize(0, 52))
            self._list.addItem(item)

        self._list.blockSignals(False)

        count = len(matched)
        self._status_lbl.setText(self._t["n_items"].format(n=count))

        # Если нет результатов при активном поиске — показываем подсказку
        if count == 0 and (words or cls_filter != "all"):
            self._show_no_results()
        elif not self._list.isVisible():
            self._show_list()

    def _set_class_filter(self, class_key: str) -> None:
        self._class_filter = class_key
        for key, btn in self._class_btns.items():
            btn.setStyleSheet(self._chip_style(active=(key == class_key)))
            btn.setChecked(key == class_key)
        self._apply_filter()

    # ── Выбор предмета ────────────────────────────────────────────────────── #

    def _on_item_changed(self, current, _previous) -> None:
        # При любой смене выбора убираем прежний выпадающий список классов.
        self._remove_dropdown()

        if current is None:
            self._selected_hat = None
            self.hat_deselected.emit()
            return
        hat: HatItem = current.data(Qt.ItemDataRole.UserRole)
        if not hat:
            return  # служебный item (например, сам dropdown) — игнорируем
        self._selected_hat = hat
        self.hat_selected.emit(hat.mdl_path, hat.name)

        # Мультиклассовая шапка → раскрываем под ней список классов.
        if self._is_multiclass(hat):
            row = self._list.row(current)
            self._inject_dropdown(row, hat)

    # ── Выпадающий список классов (мультиклассовые шапки) ─────────────────── #

    @staticmethod
    def _is_multiclass(hat: HatItem) -> bool:
        """Шапка с разными моделями на класс (нужен выбор классов для сборки)."""
        return bool(hat) and len(getattr(hat, "per_class_models", {}) or {}) > 1

    def _remove_dropdown(self) -> None:
        """Удаляет инъецированный item-аккордеон с чекбоксами классов."""
        if self._dropdown_item is not None:
            row = self._list.row(self._dropdown_item)
            if row >= 0:
                self._list.blockSignals(True)
                self._list.takeItem(row)
                self._list.blockSignals(False)
        self._dropdown_item = None
        self._dropdown_hat = None
        self._class_chip_btns = {}
        self._selected_classes = {}

    def _inject_dropdown(self, row: int, hat: HatItem) -> None:
        """Вставляет под строкой row item с чекбоксами классов (все отмечены)."""
        self._dropdown_hat = hat
        self._selected_classes = {cls: True for cls in hat.per_class_models}

        widget = self._build_class_dropdown_widget(hat)

        # Высоту считаем явно: sizeHint() неактивированного layout занижает её,
        # из-за чего чипы обрезаются. 3 чипа в ряд.
        n = len(hat.per_class_models)
        rows = max(1, (n + 2) // 3)
        height = 6 + 16 + 6 + rows * 20 + max(0, rows - 1) * 4 + 9
        widget.setFixedHeight(height)

        item = QListWidgetItem()
        item.setFlags(Qt.ItemFlag.NoItemFlags)   # не выбирается, не реагирует на клик
        item.setSizeHint(QSize(self._list.viewport().width(), height))

        self._list.blockSignals(True)
        self._list.insertItem(row + 1, item)
        self._list.setItemWidget(item, widget)
        self._list.blockSignals(False)
        self._dropdown_item = item

    def _build_class_dropdown_widget(self, hat: HatItem) -> QWidget:
        """Виджет-контейнер: заголовок + сетка чипов-классов (3 в ряд)."""
        label_map = dict(_CLASSES)
        container = QWidget()
        container.setStyleSheet("background: #141414; border: none;")
        outer = QVBoxLayout(container)
        outer.setContentsMargins(18, 6, 10, 9)
        outer.setSpacing(6)

        title = QLabel(self._t["build_classes"])
        title.setStyleSheet(
            "color:#777; font-size:10px; background:transparent; border:none;"
        )
        outer.addWidget(title)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(4)
        self._class_chip_btns = {}
        # Порядок классов — канонический (как в фильтре), только присутствующие.
        ordered = [c for c, _ in _CLASSES if c != "all" and c in hat.per_class_models]
        for i, cls in enumerate(ordered):
            btn = QPushButton(label_map.get(cls, cls.title()))
            btn.setCheckable(True)
            btn.setChecked(True)
            btn.setFixedHeight(20)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(self._chip_style(active=True))
            btn.clicked.connect(lambda checked, c=cls: self._on_class_toggled(c, checked))
            self._class_chip_btns[cls] = btn
            grid.addWidget(btn, i // 3, i % 3)
        outer.addLayout(grid)

        container.adjustSize()
        return container

    def _on_class_toggled(self, cls: str, checked: bool) -> None:
        """Переключение класса. Не даём снять последний отмеченный."""
        if not checked and sum(self._selected_classes.values()) <= 1:
            self._class_chip_btns[cls].setChecked(True)
            return
        self._selected_classes[cls] = checked
        self._class_chip_btns[cls].setStyleSheet(self._chip_style(active=checked))

    def get_selected_class_models(self) -> Optional[dict]:
        """
        Для мультиклассовой шапки — {класс: mdl} только по отмеченным классам.
        Для обычной (≤1 модель на класс) — None.
        """
        hat = self._selected_hat
        if not self._is_multiclass(hat):
            return None
        # Если dropdown активен для текущей шапки — берём отмеченные;
        # иначе (на всякий случай) — все классы.
        if self._dropdown_hat is hat and self._selected_classes:
            sel = {c: hat.per_class_models[c]
                   for c, on in self._selected_classes.items()
                   if on and c in hat.per_class_models}
            return sel or dict(hat.per_class_models)
        return dict(hat.per_class_models)

    def get_all_class_models(self) -> Optional[dict]:
        """
        Все пер-классовые модели выбранной мультиклассовой шапки (для экспорта —
        показываем все классы). None — обычная шапка.
        """
        hat = self._selected_hat
        if not self._is_multiclass(hat):
            return None
        return dict(hat.per_class_models)

    def _show_placeholder(self, text: str) -> None:
        self._placeholder.setText(text)
        self._placeholder.show()
        self._list.hide()
        self._status_lbl.hide()

    def _show_list(self) -> None:
        self._placeholder.hide()
        self._list.show()
        self._status_lbl.show()

    def _show_no_results(self) -> None:
        """Показывает пустой список + статус 'ничего не найдено', убирает placeholder."""
        self._placeholder.hide()
        self._list.show()
        self._status_lbl.show()
        self._status_lbl.setText(self._t["no_results"])

    def update_language(self, language: str) -> None:
        self._language = language if language in _I18N else "en"
        self._t = _I18N[self._language]
        self._search_input.setPlaceholderText(self._t["search_hint"])
        self._refresh_btn.setToolTip(self._t["refresh"])
