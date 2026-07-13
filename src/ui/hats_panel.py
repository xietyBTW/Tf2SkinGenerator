"""
Панель выбора шапок/косметики TF2 с умным поиском.

Загружает данные из items_game.txt (через hats_parser), кэширует,
отображает список с live-поиском и фильтром по классу.
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal, QThread, QTimer, QRect, QSize, QPoint, QPointF
from PySide6.QtGui import (
    QColor, QPainter, QFont, QFontMetrics, QAction, QIcon, QPixmap, QPolygonF,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem,
    QStyledItemDelegate, QStyle, QLayout, QToolButton, QMenu, QSizePolicy,
)


class FlowLayout(QLayout):
    """Раскладка-поток: виджеты идут в ряд и переносятся на новую строку по
    доступной ширине (стандартный приём Qt). Используем для чипов классов —
    чтобы они адаптировались к ширине панели, а не висели фиксированными рядами."""

    def __init__(self, parent=None, hspacing=4, vspacing=4):
        super().__init__(parent)
        self._items: list = []
        self._hspace = hspacing
        self._vspace = vspacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect, test_only):
        x, y = rect.x(), rect.y()
        line_height = 0
        for item in self._items:
            w = item.sizeHint().width()
            h = item.sizeHint().height()
            next_x = x + w + self._hspace
            if next_x - self._hspace > rect.right() and line_height > 0:
                x = rect.x()
                y = y + line_height + self._vspace
                next_x = x + w + self._hspace
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x = next_x
            line_height = max(line_height, h)
        return y + line_height - rect.y()

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
        "search_hint": "Поиск по названию...",
        "loading":     "Загрузка предметов из TF2...",
        "no_tf2":      "Укажите путь к TF2 в настройках",
        "no_results":  "Ничего не найдено",
        "all_classes": "Все классы",
        "n_classes":   "{n} классов",
        "n_items":     "{n} предметов",
        "refresh":     "Обновить",
        "build_classes": "Классы для сборки:",
        "build_styles":  "Стили для сборки:",
        "filter":         "Фильтр",
        "filter_tip":     "Скрыть категории предметов",
        "hide_medals":    "Скрыть медали",
        "hide_halloween": "Скрыть Halloween",
        "hide_holiday":   "Скрыть сезонные (Christmas и др.)",
    },
    "en": {
        "title":       "COSMETICS",
        "search_hint": "Search by name...",
        "loading":     "Loading items from TF2...",
        "no_tf2":      "Set TF2 path in Settings",
        "no_results":  "No results found",
        "all_classes": "All classes",
        "n_classes":   "{n} classes",
        "n_items":     "{n} items",
        "refresh":     "Refresh",
        "build_classes": "Build for classes:",
        "build_styles":  "Build for styles:",
        "filter":         "Filter",
        "filter_tip":     "Hide item categories",
        "hide_medals":    "Hide medals",
        "hide_halloween": "Hide Halloween",
        "hide_holiday":   "Hide seasonal (Christmas etc.)",
    },
}

# Категории для фильтра «скрыть».
_FILTER_TAGS = ("medals", "halloween", "holiday")


def _funnel_icon(color: str, size: int = 16) -> QIcon:
    """Рисует минималистичную иконку-воронку (фильтр) заданного цвета."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    m = 2.0
    s = float(size)
    cx = s / 2.0
    sh = 1.6           # половина ширины «ножки»
    mid_y = s * 0.52   # где широкая часть переходит в ножку
    poly = QPolygonF([
        QPointF(m, m), QPointF(s - m, m),
        QPointF(cx + sh, mid_y), QPointF(cx + sh, s - m),
        QPointF(cx - sh, s - m), QPointF(cx - sh, mid_y),
    ])
    p.drawPolygon(poly)
    p.end()
    return QIcon(pm)


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

    def __init__(self, accent: str, t: dict, parent=None):
        super().__init__(parent)
        self._accent = accent
        self._t = t

    def set_translations(self, t: dict) -> None:
        self._t = t

    def paint(self, painter: QPainter, option, index) -> None:
        hat: Optional[HatItem] = index.data(Qt.ItemDataRole.UserRole)
        if hat is None:
            super().paint(painter, option, index)
            return

        painter.save()
        rect = option.rect

        is_selected = bool(option.state & QStyle.State_Selected)
        is_hover    = bool(option.state & QStyle.State_MouseOver)

        # Фон: мягкая подсветка выбранного (не плотная заливка) + левый акцент.
        if is_selected:
            painter.fillRect(rect, QColor(self._accent + "18"))
            painter.fillRect(QRect(rect.x(), rect.y(), 3, rect.height()), QColor(self._accent))
        elif is_hover:
            painter.fillRect(rect, QColor("#ffffff0d"))

        pad_l = 18 if is_selected else 14
        pad_r = 12
        has_styles = len(getattr(hat, "styles", None) or []) > 1

        # ── Класс — приглушённым тегом справа (одна строка вместо второй).
        # Название в приоритете: тег класса ограничен по ширине, а длинный список
        # классов сворачивается в «N классов», чтобы не сжимать имя до «M…». ──
        cls_font = QFont()
        cls_font.setPointSize(9)
        cfm = QFontMetrics(cls_font)
        inner_w = rect.width() - pad_l - pad_r
        max_cls_w = max(40, int(inner_w * 0.42))
        cls_text = "All" if hat.classes_str == "All classes" else hat.classes_str
        cls_w = cfm.horizontalAdvance(cls_text)
        if cls_w > max_cls_w and len(hat.classes) > 1:
            cls_text = self._t.get("n_classes", "{n} classes").format(n=len(hat.classes))
            cls_w = cfm.horizontalAdvance(cls_text)
        if cls_w > max_cls_w:
            cls_text = cfm.elidedText(cls_text, Qt.TextElideMode.ElideRight, max_cls_w)
            cls_w = cfm.horizontalAdvance(cls_text)
        painter.setFont(cls_font)
        painter.setPen(QColor(self._accent + "bb" if is_selected else "#565656"))
        cls_rect = QRect(rect.right() - pad_r - cls_w, rect.y(), cls_w, rect.height())
        painter.drawText(cls_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, cls_text)

        # ── Маркер модельных стилей — точка слева от тега класса ──
        marker_reserve = 14 if has_styles else 0
        if has_styles:
            dot_d = 6
            dot_x = cls_rect.left() - 8 - dot_d
            dot_y = rect.y() + (rect.height() - dot_d) // 2
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self._accent))
            painter.drawEllipse(dot_x, dot_y, dot_d, dot_d)
            painter.setBrush(Qt.BrushStyle.NoBrush)

        # ── Название (по центру строки) ──
        name_font = QFont()
        name_font.setPointSize(10)
        name_font.setWeight(QFont.Weight.Medium)
        painter.setFont(name_font)
        painter.setPen(QColor("#f2f2f2" if is_selected else "#cfcfcf"))
        name_left = rect.x() + pad_l
        name_right = cls_rect.left() - 8 - marker_reserve
        name_rect = QRect(name_left, rect.y(), max(10, name_right - name_left), rect.height())
        elided = QFontMetrics(name_font).elidedText(hat.name, Qt.TextElideMode.ElideRight, name_rect.width())
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, elided)

        # Разделитель
        painter.setPen(QColor("#191919"))
        painter.drawLine(rect.x(), rect.bottom(), rect.right(), rect.bottom())

        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(0, 38)


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
    # Пользователь выбрал другой СТИЛЬ-модель у текущей шапки: (style_index, mdl_path).
    # main_window авто-сохраняет правки прошлого стиля и грузит превью нового.
    hat_style_selected = Signal(int, str)

    def __init__(self, parent=None, language: str = "en"):
        super().__init__(parent)
        self._language      = language if language in _I18N else "en"
        self._t             = _I18N[self._language]
        self._accent        = self._get_accent()
        self._all_hats: List[HatItem] = []
        self._class_filter  = "all"
        self._load_worker: Optional[_LoadWorker] = None
        self._selected_hat: Optional[HatItem]    = None

        # Скрытые категории (медали/сезонное). По умолчанию ничего не скрыто;
        # выбор сохраняется в конфиге и переживает перезапуск.
        self._hidden_tags: set = self._load_hidden_tags()

        # Состояние панели выбора стилей/классов (мультиклассовые/styled шапки).
        # Показывается максимум для одной шапки за раз, в отдельной панели под
        # списком (не инъекцией item'а в QListWidget — та «съезжала» при
        # ресайзе/скролле; см. _show_selector).
        self._dropdown_hat: Optional[HatItem]          = None
        self._class_chip_btns: dict = {}      # класс → QPushButton-чип
        self._selected_classes: dict = {}     # класс → отмечен (bool)
        self._style_chip_btns: dict = {}      # индекс стиля → QPushButton-чип
        self._active_style: int = 0           # текущий редактируемый стиль (одиночный выбор)
        self._edited_styles: set = set()      # стили с накопленными правками (для маркера)

        # Таймер debounce для поиска: 150 мс после последнего ввода
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(self._apply_filter)

        self._build_ui()

    # ── Стили ─────────────────────────────────────────────────────────────── #

    @staticmethod
    def _get_accent() -> str:
        from src.utils.themes import get_accent_color
        return get_accent_color()

    # ── Построение UI ─────────────────────────────────────────────────────── #

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.setContentsMargins(0, 4, 0, 0)

        # Заголовок-секция + счётчик справа (подзаголовок убран как избыточный:
        # активная вкладка «HATS» и так объясняет назначение; счётчик перенесён
        # сюда из нижней статусной строки, освобождая место под список).
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 4)
        header_row.setSpacing(6)

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
        header_row.addWidget(title)
        header_row.addStretch()

        self._count_lbl = QLabel("")
        self._count_lbl.setObjectName("hats_count")
        self._count_lbl.setStyleSheet("""
            QLabel#hats_count {
                color: #5a5a5a;
                font-size: 11px;
                background: transparent;
                border: none;
                padding: 0;
            }
        """)
        header_row.addWidget(self._count_lbl)
        lay.addLayout(header_row)

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

        # Кнопка «Фильтр» — меню категорий для скрытия (медали/сезонное).
        self._filter_btn = QToolButton()
        self._filter_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._filter_btn.setObjectName("hats_filter")
        self._filter_btn.setPopupMode(QToolButton.InstantPopup)
        self._filter_btn.setToolTip(self._t.get("filter_tip", "Hide item categories"))
        self._build_filter_menu()
        search_row.addWidget(self._filter_btn)
        search_row.addWidget(self._refresh_btn)

        self._update_filter_btn_style()
        lay.addLayout(search_row)

        # Фильтр по классу — чипы в flow-раскладке: переносятся по ширине панели.
        self._class_btns: dict = {}
        class_outer = QWidget()
        class_outer.setStyleSheet("background: transparent;")
        class_flow = FlowLayout(class_outer, hspacing=4, vspacing=4)

        for key, label in _CLASSES:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(key == "all")
            btn.setFixedHeight(26)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(self._chip_style(active=(key == "all")))
            btn.clicked.connect(lambda checked, k=key: self._set_class_filter(k))
            self._class_btns[key] = btn
            class_flow.addWidget(btn)

        lay.addWidget(class_outer)

        # Список шапок
        self._list = QListWidget()
        self._list.setMouseTracking(True)   # нужно для State_MouseOver в делегате
        self._delegate = _HatDelegate(self._accent, self._t, self._list)
        self._list.setItemDelegate(self._delegate)
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

        # Панель выбора стилей/классов — стабильная замена инъекции item'а в список.
        # Живёт в общем layout'е под списком: её геометрия управляется Qt-layout'ом,
        # поэтому она не «съезжает» при ресайзе окна/появлении скроллбара.
        self._selector_container = QWidget()
        self._selector_container.setObjectName("hats_selector")
        self._selector_container.setStyleSheet(
            "QWidget#hats_selector { background: #141414; border: none;"
            " border-top: 1px solid #1e1e1e; }"
        )
        self._selector_layout = QVBoxLayout(self._selector_container)
        self._selector_layout.setContentsMargins(0, 0, 0, 0)
        self._selector_layout.setSpacing(0)
        self._selector_container.hide()
        lay.addWidget(self._selector_container)

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
        # Placeholder занимает ту же область контента, что и список (stretch=1 +
        # Expanding): при скрытом списке сообщение центрируется под чипами, а
        # шапка/поиск/чипы остаются на месте — без «разъезда» пустого состояния.
        self._placeholder.setSizePolicy(QSizePolicy.Policy.Expanding,
                                        QSizePolicy.Policy.Expanding)
        lay.addWidget(self._placeholder, 1)

        # Изначально — только placeholder; список скрыт
        self._list.hide()

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
        # Панель выбора относится к прежнему выбору — прячем и сбрасываем ссылки
        # (выбор всё равно теряется при clear()).
        self._clear_selector_widgets()
        self._dropdown_hat = None
        self._class_chip_btns = {}
        self._selected_classes = {}
        self._style_chip_btns = {}
        self._list.clear()

        matched = [h for h in self._all_hats
                   if h.matches(words, cls_filter) and not self._is_hidden(h)]

        # Сортировка по релевантности когда есть запрос
        if words:
            matched.sort(key=lambda h: (h.relevance(words), h.name.lower()))

        for hat in matched:
            item = QListWidgetItem(hat.name)              # текст как fallback
            item.setData(Qt.ItemDataRole.UserRole, hat)   # основные данные для делегата
            item.setSizeHint(QSize(0, 38))
            self._list.addItem(item)

        self._list.blockSignals(False)

        # Выбранная шапка отфильтрована/скрыта → снимаем выбор и уведомляем
        # (иначе _selected_hat и сборка держались бы за невидимый предмет).
        if self._selected_hat is not None and not any(
                h is self._selected_hat for h in matched):
            self._selected_hat = None
            self._remove_dropdown()
            self.hat_deselected.emit()

        count = len(matched)
        self._count_lbl.setText(self._t["n_items"].format(n=count))

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

    # ── Фильтр категорий (медали/сезонное) ────────────────────────────────── #

    @staticmethod
    def _load_hidden_tags() -> set:
        """Читает сохранённые в конфиге скрытые категории (пусто по умолчанию)."""
        try:
            from src.config.app_config import AppConfig
            saved = AppConfig.get("hats_hidden_tags", []) or []
            return {t for t in saved if t in _FILTER_TAGS}
        except Exception:
            return set()

    def _build_filter_menu(self) -> None:
        """Строит меню кнопки «Фильтр»: чекбоксы категорий для скрытия."""
        old = self._filter_btn.menu()
        if old is not None:
            old.deleteLater()
        menu = QMenu(self)
        self._filter_actions: dict = {}
        for key in _FILTER_TAGS:
            act = QAction(self._t.get(f"hide_{key}", key), self)
            act.setCheckable(True)
            act.setChecked(key in self._hidden_tags)
            act.toggled.connect(lambda on, k=key: self._on_filter_toggled(k, on))
            menu.addAction(act)
            self._filter_actions[key] = act
        self._filter_btn.setMenu(menu)

    def _on_filter_toggled(self, key: str, on: bool) -> None:
        if on:
            self._hidden_tags.add(key)
        else:
            self._hidden_tags.discard(key)
        try:
            from src.config.app_config import AppConfig
            AppConfig.set("hats_hidden_tags", sorted(self._hidden_tags))
        except Exception as e:
            logger.warning(f"Не удалось сохранить фильтр шапок: {e}")
        self._update_filter_btn_style()
        self._apply_filter()

    def _update_filter_btn_style(self) -> None:
        """Компактная кнопка-иконка: воронка акцентного цвета + акцентная рамка,
        когда активна хотя бы одна категория; иначе приглушённая."""
        active = bool(self._hidden_tags)
        self._filter_btn.setIcon(_funnel_icon(self._accent if active else "#888"))
        self._filter_btn.setIconSize(QSize(15, 15))
        border = self._accent if active else "#252525"
        self._filter_btn.setStyleSheet(f"""
            QToolButton#hats_filter {{
                background: transparent;
                border: 1px solid {border};
                border-radius: 4px;
                padding: 0;
            }}
            QToolButton#hats_filter:hover {{ border-color: {self._accent}; }}
            QToolButton#hats_filter::menu-indicator {{ image: none; width: 0; }}
        """)
        self._filter_btn.setFixedSize(32, 32)

    def _is_hidden(self, hat: HatItem) -> bool:
        """True, если предмет попадает под активную категорию-фильтр."""
        if "medals" in self._hidden_tags and hat.is_medal:
            return True
        if "halloween" in self._hidden_tags and hat.is_halloween:
            return True
        # «Сезонные» = прочие праздники (Christmas/birthday), Halloween — своя галка.
        if "holiday" in self._hidden_tags and hat.is_holiday and not hat.is_halloween:
            return True
        return False

    # ── Выбор предмета ────────────────────────────────────────────────────── #

    def _on_item_changed(self, current, _previous) -> None:
        # При любой смене выбора убираем прежнюю панель выбора стилей/классов.
        self._remove_dropdown()

        if current is None:
            self._selected_hat = None
            self.hat_deselected.emit()
            return
        hat: HatItem = current.data(Qt.ItemDataRole.UserRole)
        if not hat:
            return  # служебный item — игнорируем
        self._selected_hat = hat
        self.hat_selected.emit(hat.mdl_path, hat.name)

        # Мультикласс ИЛИ модельные стили → показываем панель выбора под списком.
        if self._is_multiclass(hat) or self._has_styles(hat):
            self._show_selector(hat)

    # ── Выпадающий список (классы / стили) ────────────────────────────────── #

    @staticmethod
    def _is_multiclass(hat: HatItem) -> bool:
        """Шапка с разными моделями на класс (нужен выбор классов для сборки)."""
        return bool(hat) and len(getattr(hat, "per_class_models", {}) or {}) > 1

    @staticmethod
    def _has_styles(hat: HatItem) -> bool:
        """Шапка с модельными стилями (есть выбор стиля)."""
        return bool(hat) and len(getattr(hat, "styles", None) or []) > 1

    @staticmethod
    def _style_classes(hat: HatItem) -> List[str]:
        """Объединение классов по всем стилям (для чипов классов у styled-шапки)."""
        out: List[str] = []
        for s in (getattr(hat, "styles", None) or []):
            for c in (s.get("per_class_models") or {}):
                if c not in out:
                    out.append(c)
        return out

    @staticmethod
    def _styled_per_class(hat: HatItem) -> bool:
        """True, если у хотя бы одного стиля модели РАЗНЫЕ по классам (нужны чипы
        классов). У all-class стиля (одна модель на все классы) чипы не нужны."""
        for s in (getattr(hat, "styles", None) or []):
            pcm = s.get("per_class_models") or {}
            if len(set(pcm.values())) > 1:
                return True
        return False

    def _clear_selector_widgets(self) -> None:
        """Убирает виджеты панели выбора и прячет её (без сброса полей-состояния)."""
        lay = getattr(self, "_selector_layout", None)
        if lay is not None:
            while lay.count():
                it = lay.takeAt(0)
                w = it.widget()
                if w is not None:
                    w.setParent(None)
                    w.deleteLater()
        cont = getattr(self, "_selector_container", None)
        if cont is not None:
            cont.hide()

    def _remove_dropdown(self) -> None:
        """Скрывает панель выбора стилей/классов и сбрасывает её состояние."""
        self._clear_selector_widgets()
        self._dropdown_hat = None
        self._class_chip_btns = {}
        self._selected_classes = {}
        self._style_chip_btns = {}
        self._active_style = 0
        self._edited_styles = set()

    def _show_selector(self, hat: HatItem) -> None:
        """Показывает под списком панель выбора: стили (если есть) + классы (если
        мультикласс). По умолчанию отмечены: первый стиль (style 0) и все классы.

        Виджет живёт в обычном layout'е (не item в QListWidget), поэтому Qt сам
        отвечает за его размер/позицию — ничего не «съезжает»."""
        self._dropdown_hat = hat
        # Классы: для styled-шапки — объединение по стилям, иначе per_class_models.
        styled = self._has_styles(hat)
        _classes = self._style_classes(hat) if styled else list(hat.per_class_models)
        self._selected_classes = {cls: True for cls in _classes}
        # Стиль — одиночный выбор; по умолчанию активен стиль 0. Маркеры
        # «изменён» (_edited_styles) сбрасывает main_window при смене шапки.
        self._active_style = 0

        self._clear_selector_widgets()
        widget = self._build_dropdown_widget(hat)
        self._selector_layout.addWidget(widget)
        self._selector_container.show()

    def _build_dropdown_widget(self, hat: HatItem) -> QWidget:
        """Виджет-аккордеон: секция стилей (если есть) + секция классов (если
        мультикласс/styled с >1 классом). Чипы — мультивыбор."""
        label_map = dict(_CLASSES)
        styled = self._has_styles(hat)
        multiclass = self._is_multiclass(hat)
        _classes = self._style_classes(hat) if styled else list(hat.per_class_models)

        container = QWidget()
        container.setStyleSheet("background: #141414; border: none;")
        outer = QVBoxLayout(container)
        outer.setContentsMargins(18, 6, 10, 9)
        outer.setSpacing(6)

        def _title(text: str) -> QLabel:
            lb = QLabel(text)
            lb.setStyleSheet("color:#777; font-size:10px; background:transparent; border:none;")
            return lb

        # ── Секция стилей (2 чипа в ряд) — ОДИНОЧНЫЙ выбор (редактируем по одному).
        # Маркер «●» у стилей с накопленными правками. ──
        if styled:
            outer.addWidget(_title(self._t.get("build_styles", "Стиль модели")))
            sgrid = QGridLayout()
            sgrid.setContentsMargins(0, 0, 0, 0)
            sgrid.setHorizontalSpacing(4)
            sgrid.setVerticalSpacing(4)
            self._style_chip_btns = {}
            for i, st in enumerate(hat.styles):
                btn = QPushButton(self._style_label(i, st))
                btn.setCheckable(True)
                active = (i == self._active_style)
                btn.setChecked(active)
                btn.setFixedHeight(20)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setStyleSheet(self._chip_style(active=active))
                btn.clicked.connect(lambda _=False, idx=i: self._on_style_clicked(idx))
                self._style_chip_btns[i] = btn
                sgrid.addWidget(btn, i // 2, i % 2)
            outer.addLayout(sgrid)

        # ── Секция классов (3 чипа в ряд) — только если модели различаются по классам ──
        if multiclass or (styled and self._styled_per_class(hat)):
            outer.addWidget(_title(self._t["build_classes"]))
            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(4)
            grid.setVerticalSpacing(4)
            self._class_chip_btns = {}
            ordered = [c for c, _ in _CLASSES if c != "all" and c in _classes]
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
        # Защита от отложенного сигнала уже удалённой кнопки (панель могла быть
        # очищена _remove_dropdown между кликом и доставкой) — как в _on_style_clicked.
        if cls not in self._class_chip_btns:
            return
        if not checked and sum(self._selected_classes.values()) <= 1:
            self._class_chip_btns[cls].setChecked(True)
            return
        self._selected_classes[cls] = checked
        self._class_chip_btns[cls].setStyleSheet(self._chip_style(active=checked))

    def _style_label(self, idx: int, st: dict) -> str:
        """Подпись чипа стиля: «● Имя» если стиль уже редактировался."""
        name = st.get("name") or f"Style {idx}"
        return ("● " + name) if idx in self._edited_styles else name

    def _on_style_clicked(self, idx: int) -> None:
        """Одиночный выбор стиля. Подсвечиваем активный, сообщаем наружу
        (main_window авто-сохранит прошлый стиль и загрузит превью нового)."""
        hat = self._dropdown_hat
        if not hat or idx == self._active_style:
            # Повторный клик по активному — просто держим его отмеченным.
            if idx in self._style_chip_btns:
                self._style_chip_btns[idx].setChecked(True)
            return
        self._active_style = idx
        for i, b in self._style_chip_btns.items():
            b.setChecked(i == idx)
            b.setStyleSheet(self._chip_style(active=(i == idx)))
        # Модель стиля (первая по классам — для превью).
        pcm = hat.styles[idx].get("per_class_models") or {}
        model = next(iter(pcm.values()), hat.mdl_path)
        self.hat_style_selected.emit(idx, model)

    def set_style_edited(self, idx: int, edited: bool = True) -> None:
        """Помечает стиль как изменённый (●) — вызывает main_window при правках."""
        if edited:
            self._edited_styles.add(idx)
        else:
            self._edited_styles.discard(idx)
        hat = self._dropdown_hat
        if hat and idx in self._style_chip_btns and idx < len(hat.styles):
            self._style_chip_btns[idx].setText(self._style_label(idx, hat.styles[idx]))

    def clear_style_edits(self) -> None:
        """Сбрасывает маркеры всех стилей (при смене шапки/очистке памяти)."""
        self._edited_styles = set()
        hat = self._dropdown_hat
        if hat:
            for i, b in self._style_chip_btns.items():
                if i < len(hat.styles):
                    b.setText(self._style_label(i, hat.styles[i]))

    def active_style(self) -> int:
        return self._active_style

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

    def get_selected_models(self) -> Optional[dict]:
        """
        Полный набор моделей для сборки: {уникальный_ключ: mdl_path} по выбранным
        СТИЛЯМ × КЛАССАМ (дедуп по пути). Покрывает все варианты:
          • styled+multiclass — отмеченные стили × отмеченные классы;
          • только styled — отмеченные стили (по их классам/одной модели);
          • только multiclass — отмеченные классы;
          • обычная шапка — None (одна модель, отдельный набор не нужен).
        """
        hat = self._selected_hat
        if not hat:
            return None
        styled = self._has_styles(hat)
        multiclass = self._is_multiclass(hat)
        if not styled and not multiclass:
            return None

        active = (self._dropdown_hat is hat)   # активен ли аккордеон выбора

        def _class_on(c: str) -> bool:
            return self._selected_classes.get(c, True) if active else True

        raw: list = []   # [(key, path)]
        if styled:
            # Одиночный режим: модели АКТИВНОГО стиля (для текущей сборки/превью).
            # Накопление по нескольким стилям делает main_window через per-style
            # память (build_extra_targets), не панель.
            i = self._active_style if active else 0
            i = i if 0 <= i < len(hat.styles) else 0
            pcm = hat.styles[i].get("per_class_models") or {}
            cls_list = [c for c in pcm if _class_on(c)] or list(pcm)
            for c in cls_list:
                raw.append((f"s{i}_{c}", pcm[c]))
        else:
            for c, p in hat.per_class_models.items():
                if _class_on(c):
                    raw.append((c, p))

        out: dict = {}
        seen: set = set()
        for k, p in raw:
            np = (p or "").replace("\\", "/").lower()
            if not np or np in seen:
                continue
            seen.add(np)
            out[k] = p
        return out or None

    def get_style_models(self, idx: int) -> Optional[dict]:
        """Модели КОНКРЕТНОГО стиля (по выбранным классам) — {ключ: mdl_path}.

        Нужно main_window для сборки доп. изменённых стилей (Этап 3): активный
        стиль идёт основным пайплайном, а остальные изменённые — каждый своей
        моделью+текстурой через этот набор. None — у шапки нет такого стиля.
        """
        hat = self._selected_hat
        if not hat or not self._has_styles(hat):
            return None
        if not (0 <= idx < len(hat.styles)):
            return None
        active = (self._dropdown_hat is hat)

        def _class_on(c: str) -> bool:
            return self._selected_classes.get(c, True) if active else True

        pcm = hat.styles[idx].get("per_class_models") or {}
        cls_list = [c for c in pcm if _class_on(c)] or list(pcm)
        out: dict = {}
        seen: set = set()
        for c in cls_list:
            p = pcm.get(c)
            np = (p or "").replace("\\", "/").lower()
            if not np or np in seen:
                continue
            seen.add(np)
            out[f"s{idx}_{c}"] = p
        return out or None

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

    def _show_list(self) -> None:
        self._placeholder.hide()
        self._list.show()

    def _show_no_results(self) -> None:
        """Нет совпадений: прячем список и показываем подсказку в placeholder
        (раньше была отдельная нижняя статусная строка — убрана)."""
        self._list.hide()
        self._placeholder.setText(self._t["no_results"])
        self._placeholder.show()

    def update_language(self, language: str) -> None:
        self._language = language if language in _I18N else "en"
        self._t = _I18N[self._language]
        self._search_input.setPlaceholderText(self._t["search_hint"])
        self._refresh_btn.setToolTip(self._t["refresh"])
        # Фильтр — перестраиваем подписи меню под новый язык.
        self._filter_btn.setToolTip(self._t.get("filter_tip", "Hide item categories"))
        self._build_filter_menu()
        self._update_filter_btn_style()
        # Делегат использует _t для «N классов» — обновляем и перерисовываем.
        if hasattr(self, "_delegate"):
            self._delegate.set_translations(self._t)
            self._list.viewport().update()
