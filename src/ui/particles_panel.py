"""
Окно редактора частиц: PCF из игры или файла → дерево свойств → живое превью.

Архитектура:
    • ParticleEditorService (srctools) держит Element-дерево PCF — источник
      правды; загрузка PCF + резолв материалов (VTF→PNG) идут в фоновом
      воркере (может занимать секунды на больших эффектах).
    • Превью — отдельный QWebEngineView с particles3d.html: JS-движок
      симулирует частицы по JSON от сервиса (порт noclip, см. engine.js).
    • Правка атрибута: set_attr в Element-дерево → пересборка JSON систем
      (материалы кэшированы) → перезагрузка эффекта в превью.
"""

import json
from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    QByteArray, QLocale, QObject, QSize, Qt, QTimer, Signal, Slot,
)
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog,
    QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPushButton, QRadioButton,
    QScrollArea, QSlider, QSplitter, QStackedWidget, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from src.data.translations import TRANSLATIONS
from src.services import simple_params
from src.services.base_worker import StandardWorker
from src.services.particle_editor_service import (
    MODULE_CATALOG, MODULE_GROUPS, ParticleEditorService,
)
from src.shared.logging_config import get_logger
from src.ui.preview_3d_widget import is_webengine_available
from src.ui.styled_dialog import _colors
from src.ui.preview_3d_widget import _get_html_path  # dev/frozen пути к static

logger = get_logger(__name__)

_ROLE_ATTR = Qt.ItemDataRole.UserRole  # (group|None, module_idx, attr_name, type)
_ROLE_GROUP = Qt.ItemDataRole.UserRole + 2   # имя группы модулей (заголовок)
_ROLE_MODULE = Qt.ItemDataRole.UserRole + 3  # (group, index) — модуль
_ROLE_CHILD = Qt.ItemDataRole.UserRole + 4   # индекс ребёнка


def _particles_html_path() -> str:
    """particles3d.html лежит рядом с viewer3d.html — переиспользуем резолв путей."""
    import os
    return os.path.join(os.path.dirname(_get_html_path()), "particles3d.html")


# ── Фоновая загрузка PCF ─────────────────────────────────────────────────── #

class _PcfLoadWorker(StandardWorker):
    """Загружает PCF и резолвит материалы (VTF→PNG data URL) в фоне."""

    def __init__(self, tf2_root: str, source: str, parent=None):
        """source: 'vpk:<путь внутри VPK>' либо путь к файлу на диске."""
        super().__init__(parent)
        self._tf2_root = tf2_root
        self._source = source
        self.service: Optional[ParticleEditorService] = None
        self.payload: Optional[dict] = None   # {"systems": ..., "materials": ...}

    def work(self):
        svc = ParticleEditorService()
        if self._source.startswith("vpk:"):
            svc.load_from_game(self._tf2_root, self._source[4:])
        else:
            svc.load_file(self._source)
        if self.isInterruptionRequested():
            return False, "cancelled"
        systems = svc.systems_json()
        materials = (
            svc.materials_json(self._tf2_root,
                               cancel_check=self.isInterruptionRequested)
            if self._tf2_root else {}
        )
        if self.isInterruptionRequested():
            return False, "cancelled"
        self.service = svc
        self.payload = {"systems": systems, "materials": materials}
        return True, ""


# ── JS-мост ──────────────────────────────────────────────────────────────── #

class _ParticleBridge(QObject):
    ready = Signal()
    gizmo_edit = Signal(str)   # JSON {system, edits: [...], final}

    @Slot()
    def notifyReady(self) -> None:  # noqa: N802
        self.ready.emit()

    @Slot(str)
    def gizmoEdit(self, payload: str) -> None:  # noqa: N802
        """Драг ручки гизмо в 3D-превью — правка атрибутов из JS."""
        self.gizmo_edit.emit(payload)


# ── Виджет превью ────────────────────────────────────────────────────────── #

class ParticleViewWidget(QWidget):
    """QWebEngineView с particles3d.html (или заглушка без WebEngine)."""

    gizmo_edited = Signal(str)   # проброс _ParticleBridge.gizmo_edit

    def __init__(self, parent=None, language: str = 'en'):
        super().__init__(parent)
        self._ready = False
        self._pending: list = []
        self._lang = language

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if not is_webengine_available():
            lbl = QLabel(
                "3D Preview недоступен.\nУстановите PySide6-Addons:\n"
                "pip install PySide6-Addons"
            )
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color: #555; font-size: 13px; background: #1a1a1a;")
            layout.addWidget(lbl)
            self._view = None
            return

        from PySide6.QtCore import QUrl
        from PySide6.QtWebChannel import QWebChannel
        from PySide6.QtWebEngineWidgets import QWebEngineView

        self._view = QWebEngineView(self)
        self._bridge = _ParticleBridge()
        self._bridge.ready.connect(self._on_ready)
        self._bridge.gizmo_edit.connect(self.gizmo_edited)
        self._channel = QWebChannel()
        self._channel.registerObject("pyBridge", self._bridge)
        self._view.page().setWebChannel(self._channel)
        self._view.page().javaScriptConsoleMessage = (
            lambda level, msg, line, src: logger.info(f"[particlesJS] {msg}")
        )
        self._view.setUrl(QUrl.fromLocalFile(_particles_html_path()))
        layout.addWidget(self._view)

    def _on_ready(self) -> None:
        self._ready = True
        self._run(f"window.setLanguage({json.dumps(self._lang)})")
        for js in self._pending:
            self._run(js)
        self._pending.clear()

    def _run(self, js: str) -> None:
        if self._view is None:
            return
        if not self._ready:
            self._pending.append(js)
            return
        self._view.page().runJavaScript(js)

    # ── Публичный API ────────────────────────────────────────────────────── #

    def set_language(self, lang: str) -> None:
        self._lang = lang
        self._run(f"window.setLanguage({json.dumps(lang)})")

    def load_data(self, payload: dict, root_name: str = "") -> None:
        data = dict(payload)
        data["rootName"] = root_name
        self._run(f"window.loadParticleData({json.dumps(data)})")

    def update_systems(self, systems: dict, root_name: str) -> None:
        """Обновляет только определения систем — текстуры не перегружаются."""
        self._run(
            f"window.updateSystems({json.dumps(systems)}, {json.dumps(root_name)})"
        )

    def set_root(self, name: str) -> None:
        self._run(f"window.setRootSystem({json.dumps(name)})")

    def set_gizmo_visible(self, visible: bool) -> None:
        """Каркас области спавна (сфера/бокс инициализаторов позиции)."""
        self._run(f"window.setGizmoVisible({json.dumps(bool(visible))})")

    def restart(self) -> None:
        self._run("window.restartEffect()")

    def set_paused(self, paused: bool) -> None:
        self._run(f"window.setPaused({json.dumps(bool(paused))})")

    def show_loading(self, text: str = "") -> None:
        self._run(f"window.showLoading({json.dumps(text)})")

    def show_error(self, text: str) -> None:
        self._run(f"window.showError({json.dumps(text)})")

    def reset(self) -> None:
        self._run("window.resetViewer()")


# ── 2D-карточки текстур ──────────────────────────────────────────────────── #

_ROLE_MATERIAL = Qt.ItemDataRole.UserRole + 1
_IMAGE_EXTS = ('.png', '.jpg', '.jpeg', '.tga', '.bmp', '.webp', '.gif')


class _TextureCardsList(QListWidget):
    """Сетка карточек текстур эффекта: двойной клик или drop картинки на
    карточку → замена (как 2D-режим у оружия)."""

    texture_dropped = Signal(str, str)   # (имя материала, путь картинки)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setIconSize(QSize(112, 112))
        self.setGridSize(QSize(150, 165))
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setWordWrap(True)
        self.setAcceptDrops(True)

    def _drop_image_path(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1:
            path = urls[0].toLocalFile()
            if path.lower().endswith(_IMAGE_EXTS):
                return path
        return None

    def dragEnterEvent(self, event) -> None:
        if self._drop_image_path(event):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if self._drop_image_path(event):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        path = self._drop_image_path(event)
        item = self.itemAt(event.position().toPoint()) if path else None
        if path and item is not None:
            event.acceptProposedAction()
            self.texture_dropped.emit(item.data(_ROLE_MATERIAL), path)
        else:
            event.ignore()


def _pixmap_from_data_url(data_url, size: int = 112) -> QPixmap:
    """PNG data URL → QPixmap; None/ошибка → серый плейсхолдер."""
    pix = QPixmap()
    if data_url:
        try:
            b64 = data_url.split(",", 1)[1]
            pix.loadFromData(QByteArray.fromBase64(b64.encode("ascii")))
        except Exception:
            pix = QPixmap()
    if pix.isNull():
        pix = QPixmap(size, size)
        pix.fill(QColor(40, 40, 40))
        return pix
    return pix.scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation)


# ── Простой режим: панель крутилок по схеме SIMPLE_PARAMS ────────────────── #

class _NumSpin(QDoubleSpinBox):
    """Числовое поле, не зависящее от локали: и «12.5», и «12,5» дают 12.5.

    Под русской локалью штатный QDoubleSpinBox отбрасывает точку — набранное
    «12.5» превращалось в 125. Запятая заменяется точкой прямо при вводе.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLocale(QLocale.c())

    def validate(self, text: str, pos: int):
        return super().validate(text.replace(",", "."), pos)

    def valueFromText(self, text: str) -> float:
        return super().valueFromText(text.replace(",", "."))

class _SimpleParamsWidget(QWidget):
    """Крутилки простого режима. Строится из SIMPLE_PARAMS: новая крутилка в
    схеме появляется здесь сама. Значения читает из systems_json, правки
    шлёт сигналом edited — панель применяет их через сервис (единый источник
    правды, дерево экспертного режима обновляется тем же путём)."""

    edited = Signal(object, object)      # (SimpleParam, значение)
    enable_module = Signal(object)       # (SimpleParam) — создать модуль

    def __init__(self, t: dict, colors: dict, parent=None):
        super().__init__(parent)
        self._c = colors
        self._rows: dict = {}            # key -> {label, editors, enable, row}
        self._sys_json: Optional[dict] = None

        c = colors
        self._spin_style = f"""
            QDoubleSpinBox {{
                background: {c['surface']}; color: {c['text']};
                border: 1px solid {c['border']}; border-radius: 3px;
                padding: 2px 4px; font-size: 12px;
            }}
            QDoubleSpinBox:disabled {{ color: #555; }}
        """
        self._label_style = f"color: {c['text']}; font-size: 12px;"
        self._enable_style = f"""
            QPushButton {{
                background: transparent; color: {c['text_sub']};
                border: 1px solid {c['border']}; border-radius: 3px;
                padding: 2px 10px; font-size: 11px;
            }}
            QPushButton:hover {{ color: {c['text']}; border-color: #555; }}
        """

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        body = QWidget()
        self._grid = QGridLayout(body)
        self._grid.setContentsMargins(2, 2, 6, 2)
        self._grid.setHorizontalSpacing(8)
        self._grid.setVerticalSpacing(6)
        for row, param in enumerate(simple_params.SIMPLE_PARAMS):
            self._build_row(row, param)
        self._grid.setRowStretch(len(simple_params.SIMPLE_PARAMS), 1)
        self._grid.setColumnStretch(1, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        body.setStyleSheet("background: transparent;")
        scroll.setWidget(body)
        outer.addWidget(scroll)
        self.update_language(t)

    # ── Построение строк ─────────────────────────────────────────────────── #

    def _make_spin(self, param) -> QDoubleSpinBox:
        spin = _NumSpin()
        spin.setRange(param.minimum, param.maximum)
        spin.setDecimals(param.decimals)
        spin.setStyleSheet(self._spin_style)
        spin.setMinimumWidth(64)
        spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        # Без этого правка уходит в модель на КАЖДЫЙ символ: набор «12.5»
        # писал 1 → 12 → 125. Значение фиксируется по Enter/потере фокуса.
        spin.setKeyboardTracking(False)
        return spin

    def _build_row(self, row: int, param) -> None:
        label = QLabel()
        label.setStyleSheet(self._label_style)
        self._grid.addWidget(label, row, 0)

        editors_box = QHBoxLayout()
        editors_box.setSpacing(6)
        editors: list = []

        if param.kind == "value":
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 1000)
            spin = self._make_spin(param)
            span = param.maximum - param.minimum

            def to_slider(v, span=span, p=param):
                return round((v - p.minimum) / span * 1000) if span else 0

            def from_slider(x, span=span, p=param):
                return p.minimum + span * x / 1000

            def on_slider(x, s=None):
                spin.blockSignals(True)
                spin.setValue(from_slider(x))
                spin.blockSignals(False)
                self.edited.emit(param, spin.value())

            def on_spin(v):
                slider.blockSignals(True)
                slider.setValue(to_slider(v))
                slider.blockSignals(False)
                self.edited.emit(param, v)

            slider.valueChanged.connect(on_slider)
            spin.valueChanged.connect(on_spin)
            editors_box.addWidget(slider, 1)
            editors_box.addWidget(spin)
            editors = [slider, spin]
            self._rows[param.key] = {"set": lambda v, s=slider, sp=spin, f=to_slider: (
                s.blockSignals(True), s.setValue(f(v)), s.blockSignals(False),
                sp.blockSignals(True), sp.setValue(float(v)), sp.blockSignals(False))}
        elif param.kind == "range":
            spin_min, spin_max = self._make_spin(param), self._make_spin(param)
            for sp in (spin_min, spin_max):
                sp.valueChanged.connect(
                    lambda _v, a=spin_min, b=spin_max:
                        self.edited.emit(param, (a.value(), b.value())))
                editors_box.addWidget(sp, 1)
            editors = [spin_min, spin_max]
            self._rows[param.key] = {"set": lambda v, a=spin_min, b=spin_max: (
                a.blockSignals(True), a.setValue(float(v[0])), a.blockSignals(False),
                b.blockSignals(True), b.setValue(float(v[1])), b.blockSignals(False))}
        else:  # color_pair
            btns = []
            for i in (0, 1):
                btn = QPushButton()
                btn.setFixedSize(44, 22)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(lambda _=False, n=i: self._pick_color(param, n))
                editors_box.addWidget(btn)
                btns.append(btn)
            editors_box.addStretch(1)
            editors = btns

            def set_colors(v, btns=btns):
                for btn, col in zip(btns, v):
                    btn.setProperty("_rgba", list(col))
                    btn.setStyleSheet(
                        f"background: rgb({col[0]},{col[1]},{col[2]});"
                        "border: 1px solid #444; border-radius: 3px;")
            self._rows[param.key] = {"set": set_colors}

        self._grid.addLayout(editors_box, row, 1)

        enable_btn = QPushButton()
        enable_btn.setStyleSheet(self._enable_style)
        enable_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        enable_btn.clicked.connect(lambda _=False, p=param: self.enable_module.emit(p))
        enable_btn.hide()
        self._grid.addWidget(enable_btn, row, 2)

        self._rows[param.key].update({
            "param": param, "label": label, "editors": editors,
            "enable": enable_btn,
        })

    def _pick_color(self, param, index: int) -> None:
        btns = self._rows[param.key]["editors"]
        cur = btns[index].property("_rgba") or [255, 255, 255, 255]
        initial = QColor(cur[0], cur[1], cur[2], cur[3] if len(cur) > 3 else 255)
        color = QColorDialog.getColor(
            initial, self, "", QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if not color.isValid():
            return
        vals = []
        for i, btn in enumerate(btns):
            if i == index:
                vals.append([color.red(), color.green(), color.blue(),
                             color.alpha()])
            else:
                vals.append(btn.property("_rgba") or [255, 255, 255, 255])
        self._rows[param.key]["set"](vals)
        self.edited.emit(param, tuple(vals))

    # ── Обновление из systems_json ───────────────────────────────────────── #

    def set_system(self, sys_json: Optional[dict]) -> None:
        """Перечитывает все крутилки. None — система не выбрана."""
        self._sys_json = sys_json
        for entry in self._rows.values():
            param = entry["param"]
            widgets = [entry["label"], entry["enable"], *entry["editors"]]
            if sys_json is None:
                for w in widgets:
                    w.hide()
                continue
            value = simple_params.read_param(sys_json, param)
            missing = simple_params.missing_modules(sys_json, param)
            if value is None and missing and not param.creatable:
                for w in widgets:
                    w.hide()               # эмиттера такого типа нет — не к чему
                continue
            entry["label"].show()
            for w in entry["editors"]:
                w.show()
                w.setEnabled(value is not None)
            entry["enable"].setVisible(value is None)
            if value is not None:
                entry["set"](value)

    def update_language(self, t: dict) -> None:
        for entry in self._rows.values():
            entry["label"].setText(t.get(f"particles_sp_{entry['param'].key}",
                                         entry["param"].key))
            entry["enable"].setText(t.get("particles_simple_enable", "Enable"))


# ── Панель редактора (вкладка главного окна) ─────────────────────────────── #

class ParticlesPanel(QWidget):
    """Вкладка редактора частиц — встроена в главное окно, как Диагностика."""

    def __init__(self, parent=None, language: str = 'en', tf2_root: str = ''):
        super().__init__(parent)
        self._c = _colors()
        self.t = TRANSLATIONS.get(language, TRANSLATIONS['en'])
        self.language = language
        self.tf2_root = tf2_root

        self.service: Optional[ParticleEditorService] = None
        self._payload: Optional[dict] = None
        self._attr_items: dict = {}   # (группа, индекс, атрибут) → строка дерева
        self._worker: Optional[_PcfLoadWorker] = None
        self._queued_source: Optional[str] = None
        self._current_system: str = ""
        self._paused = False

        # Отложенное применение правок крутилок (см. _on_simple_edit)
        self._simple_pending_attrs: set = set()
        self._simple_pending_rebuild = False
        self._simple_timer = QTimer(self)
        self._simple_timer.setInterval(60)
        self._simple_timer.setSingleShot(True)
        self._simple_timer.timeout.connect(self._flush_simple_edit)

        # Отложенная синхронизация правок из 3D-гизмо (см. _on_gizmo_edit)
        self._gizmo_pending: set = set()
        self._gizmo_timer = QTimer(self)
        self._gizmo_timer.setInterval(150)
        self._gizmo_timer.setSingleShot(True)
        self._gizmo_timer.timeout.connect(self._flush_gizmo_edit)

        self._build_ui()
        self._populate_game_pcfs()

    # ── UI ───────────────────────────────────────────────────────────────── #

    def _build_ui(self) -> None:
        from src.utils.themes import get_modern_styles
        styles = get_modern_styles()
        c = self._c
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 0)
        root.setSpacing(0)

        # ── Тулбар: комбо + иконки + чипы 3D/2D — один компактный ряд ─────── #
        from src.ui.preview_icons import (
            _make_droplet_icon, _make_folder_icon, _make_image_icon,
            _make_pause_icon, _make_play_icon, _make_restart_icon,
            _make_save_icon,
        )
        self._icon_pause = _make_pause_icon("#666666")
        self._icon_play = _make_play_icon("#666666")

        # Комбо живёт в левой колонке (край = начало 3D-окна), иконки — над 3D
        icons_row = QHBoxLayout()
        icons_row.setContentsMargins(6, 0, 0, 6)
        icons_row.setSpacing(6)

        self.pcf_combo = QComboBox()
        # Родной стиль приложения + непрокручиваемый попап с ограничением высоты
        self.pcf_combo.setStyleSheet(
            styles['combo'] + "QComboBox { combobox-popup: 0; }")
        self.pcf_combo.setMaxVisibleItems(18)
        self.pcf_combo.activated.connect(self._on_pcf_selected)

        # Иконки-кнопки — как в тулбаре превью оружия (26×26, тонкая рамка)
        self._icon_btn_style = """
            QPushButton { background:transparent; border:1px solid #2a2a2a; border-radius:3px; padding:0; }
            QPushButton:hover { background:rgba(255,255,255,0.05); border-color:#555; }
            QPushButton:pressed { background:rgba(255,255,255,0.08); }
            QPushButton:disabled { border-color:#222; }
        """
        for attr_name, icon, tip_key, slot in (
            ('open_btn', _make_folder_icon("#666666"),
             'particles_open_file', self._on_open_file),
            ('texture_btn', _make_image_icon("#666666"),
             'particles_set_texture', self._on_set_texture),
            ('colors_btn', _make_droplet_icon("#666666"),
             'particles_natural_colors', self._on_natural_colors),
            ('save_btn', _make_save_icon("#666666"),
             'particles_save_as', self._on_save_as),
            ('restart_btn', _make_restart_icon("#666666"),
             'particles_restart', self._on_restart),
            ('pause_btn', self._icon_pause,
             'particles_pause', self._on_pause),
        ):
            btn = QPushButton()
            btn.setFixedSize(26, 26)
            btn.setIcon(icon)
            btn.setStyleSheet(self._icon_btn_style)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(self.t[tip_key])
            btn.clicked.connect(slot)
            setattr(self, attr_name, btn)
            icons_row.addWidget(btn)

        icons_row.addStretch(1)

        # Чипы 3D/2D — стиль тулбара превью оружия
        def _chip_style(active: bool) -> str:
            if active:
                return (
                    "QPushButton { background:#2a2a2a; color:#ccc; border:1px solid #444;"
                    " padding:4px 16px; font-size:11px; font-weight:600; border-radius:3px; }"
                )
            return (
                "QPushButton { background:transparent; color:#555; border:1px solid #2a2a2a;"
                " padding:4px 16px; font-size:11px; border-radius:3px; }"
                " QPushButton:hover { background:rgba(255,255,255,0.04); color:#888; border-color:#383838; }"
            )
        self._chip_active = _chip_style(True)
        self._chip_inactive = _chip_style(False)

        self.mode_3d_btn = QPushButton("3D")
        self.mode_2d_btn = QPushButton("2D")
        for btn, mode in ((self.mode_3d_btn, 0), (self.mode_2d_btn, 1)):
            btn.setFixedHeight(26)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, m=mode: self._set_view_mode(m))
            icons_row.addWidget(btn)
        self.mode_3d_btn.setStyleSheet(self._chip_active)
        self.mode_2d_btn.setStyleSheet(self._chip_inactive)

        self.save_btn.setEnabled(False)
        self.texture_btn.setEnabled(False)
        self.colors_btn.setEnabled(False)
        self._icons_row = icons_row

        # ── Сплиттер: список систем | свойства | превью ──────────────────── #
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setStyleSheet(f"QSplitter::handle {{ background: {c['border']}; }}")

        left = QSplitter(Qt.Orientation.Vertical)
        left.setStyleSheet(f"QSplitter::handle {{ background: {c['border']}; }}")

        lbl_style = (f"color: {c['text_sub']}; font-size: 11px; "
                     "font-weight: 600; letter-spacing: 1px;")

        sys_box = QWidget()
        sys_box_l = QVBoxLayout(sys_box)
        sys_box_l.setContentsMargins(0, 4, 6, 4)
        sys_box_l.setSpacing(6)
        sys_lbl = QLabel(self.t['particles_systems'])
        sys_lbl.setStyleSheet(lbl_style)
        sys_box_l.addWidget(sys_lbl)

        self.systems_list = QListWidget()
        self.systems_list.setStyleSheet(f"""
            QListWidget {{
                background: {c['surface']}; color: {c['text']};
                border: 1px solid {c['border']}; border-radius: 4px;
                font-size: 12px; outline: none;
            }}
            QListWidget::item {{ padding: 4px 8px; }}
            QListWidget::item:selected {{
                background: {c['border_h']}; color: #fff;
            }}
        """)
        self.systems_list.currentItemChanged.connect(self._on_system_selected)
        self.systems_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.systems_list.customContextMenuRequested.connect(
            self._on_systems_menu)
        sys_box_l.addWidget(self.systems_list, 1)
        left.addWidget(sys_box)

        prop_box = QWidget()
        prop_box_l = QVBoxLayout(prop_box)
        prop_box_l.setContentsMargins(0, 4, 6, 0)
        prop_box_l.setSpacing(6)
        prop_head = QHBoxLayout()
        prop_head.setSpacing(6)
        self.prop_lbl = QLabel(self.t['particles_properties'])
        self.prop_lbl.setStyleSheet(lbl_style)
        prop_head.addWidget(self.prop_lbl)
        prop_head.addStretch(1)
        # Чипы уровня: Просто (крутилки) / Экспертно (дерево атрибутов)
        self.level_simple_btn = QPushButton(self.t['particles_level_simple'])
        self.level_expert_btn = QPushButton(self.t['particles_level_expert'])
        for btn, level in ((self.level_simple_btn, 0),
                           (self.level_expert_btn, 1)):
            btn.setFixedHeight(22)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, lv=level: self._set_level(lv))
            prop_head.addWidget(btn)
        prop_box_l.addLayout(prop_head)

        self.attr_tree = QTreeWidget()
        self.attr_tree.setHeaderLabels(["", ""])
        self.attr_tree.setHeaderHidden(True)
        self.attr_tree.setColumnCount(2)
        # Имена — фиксированная (перетаскиваемая) колонка, значения занимают
        # остаток и не уезжают за край при ресайзе панели
        self.attr_tree.header().setStretchLastSection(True)
        self.attr_tree.setColumnWidth(0, 220)
        self.attr_tree.setStyleSheet(f"""
            QTreeWidget {{
                background: {c['surface']}; color: {c['text']};
                border: 1px solid {c['border']}; border-radius: 4px;
                font-size: 12px; outline: none;
            }}
            QTreeWidget::item {{ padding: 2px 4px; }}
            QTreeWidget::item:selected {{
                background: {c['border_h']}; color: #fff;
            }}
        """)
        self.attr_tree.itemDoubleClicked.connect(self._on_attr_double_clicked)
        self.attr_tree.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.attr_tree.customContextMenuRequested.connect(self._on_tree_menu)
        # Копи-паста параметров: мультивыделение + Ctrl+C/Ctrl+V (только
        # когда фокус в дереве — не перехватываем буфер у полей ввода)
        self.attr_tree.setSelectionMode(
            QTreeWidget.SelectionMode.ExtendedSelection)
        for seq, slot in (
            (QKeySequence.StandardKey.Copy, self._on_copy_params),
            (QKeySequence.StandardKey.Paste, self._on_paste_params),
        ):
            sc = QShortcut(seq, self.attr_tree)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(slot)

        self.simple_widget = _SimpleParamsWidget(self.t, c)
        self.simple_widget.edited.connect(self._on_simple_edit)
        self.simple_widget.enable_module.connect(self._on_simple_enable)
        self.simple_widget.set_system(None)

        self.prop_stack = QStackedWidget()
        self.prop_stack.addWidget(self.simple_widget)   # 0 = просто
        self.prop_stack.addWidget(self.attr_tree)       # 1 = экспертно
        prop_box_l.addWidget(self.prop_stack, 1)
        left.addWidget(prop_box)

        left.setSizes([240, 420])
        left.setCollapsible(0, False)
        left.setCollapsible(1, False)

        # Обёртка левой колонки: комбо сверху, его правый край = начало 3D
        left_wrap = QWidget()
        left_wrap_l = QVBoxLayout(left_wrap)
        left_wrap_l.setContentsMargins(0, 0, 6, 0)
        left_wrap_l.setSpacing(6)
        left_wrap_l.addWidget(self.pcf_combo)
        left_wrap_l.addWidget(left, 1)

        split.addWidget(left_wrap)

        # ── Правая часть: иконки над вьюпортом + стек превью/карточек ─────── #
        right = QWidget()
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(0)
        right_l.addLayout(self._icons_row)

        self.view = ParticleViewWidget(self, language=self.language)
        self.view.gizmo_edited.connect(self._on_gizmo_edit)

        cards_page = QWidget()
        cards_l = QVBoxLayout(cards_page)
        cards_l.setContentsMargins(0, 0, 0, 0)
        cards_l.setSpacing(6)
        self.cards_hint = QLabel(self.t['particles_2d_hint'])
        self.cards_hint.setStyleSheet(lbl_style)
        cards_l.addWidget(self.cards_hint)
        self.texture_cards = _TextureCardsList()
        self.texture_cards.setStyleSheet(f"""
            QListWidget {{
                background: {c['surface']}; color: {c['text']};
                border: 1px solid {c['border']}; border-radius: 4px;
                font-size: 11px; outline: none;
            }}
            QListWidget::item {{ padding: 6px; border-radius: 4px; }}
            QListWidget::item:selected {{ background: {c['border_h']}; }}
        """)
        self.texture_cards.itemDoubleClicked.connect(self._on_card_double_clicked)
        self.texture_cards.texture_dropped.connect(self._replace_material_texture)
        self.texture_cards.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.texture_cards.customContextMenuRequested.connect(self._on_card_menu)
        cards_l.addWidget(self.texture_cards, 1)

        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self.view)      # 0 = 3D
        self.view_stack.addWidget(cards_page)     # 1 = 2D
        right_l.addWidget(self.view_stack, 1)

        split.addWidget(right)

        # ── Экспорт-колонка (стиль вкладки оружия) ─────────────────────────── #
        export_col = QWidget()
        export_col.setFixedWidth(240)
        export_l = QVBoxLayout(export_col)
        export_l.setContentsMargins(14, 4, 0, 0)
        export_l.setSpacing(12)

        # Тот же заголовок-«шаг», что у оружейной панели экспорта
        self.export_title = QLabel(self.t.get('step_2_export', 'Export'))
        self.export_title.setStyleSheet("""
            font-size: 12px;
            font-weight: 600;
            color: #888;
            text-transform: uppercase;
            letter-spacing: 1px;
            padding-bottom: 4px;
        """)
        export_l.addWidget(self.export_title)

        _field_lbl = "font-weight: 500; font-size: 13px; color: #ccc;"

        # Максимальный размер кастомных текстур (применяется при замене)
        self.res_label = QLabel(self.t['resolution'])
        self.res_label.setStyleSheet(_field_lbl)
        export_l.addWidget(self.res_label)

        self.size_group = QButtonGroup(self)
        size_grid = QGridLayout()
        size_grid.setHorizontalSpacing(8)
        size_grid.setVerticalSpacing(6)
        self._size_radios = {}
        for i, size in enumerate((128, 256, 512, 1024)):
            radio = QRadioButton(f"{size}x{size}")
            if size == 512:
                radio.setChecked(True)
            self.size_group.addButton(radio)
            self._size_radios[size] = radio
            size_grid.addWidget(radio, i // 2, i % 2)
        export_l.addLayout(size_grid)

        # Формат VTF: для частиц осмысленны только форматы с альфой
        self.format_label = QLabel(self.t['format_vtf'])
        self.format_label.setStyleSheet(_field_lbl)
        export_l.addWidget(self.format_label)

        self.format_combo = QComboBox()
        self.format_combo.addItem("DXT5", False)
        self.format_combo.addItem("RGBA8888", True)   # data = uncompressed
        self.format_combo.setStyleSheet(styles['combo'])
        export_l.addWidget(self.format_combo)

        # Имя VPK
        self.filename_label = QLabel(self.t['filename_vpk'])
        self.filename_label.setStyleSheet(_field_lbl)
        export_l.addWidget(self.filename_label)

        self.filename_input = QLineEdit()
        self.filename_input.setPlaceholderText(self.t['placeholder'])
        self.filename_input.setStyleSheet(styles['line_edit'])
        self.filename_input.setMinimumHeight(40)
        export_l.addWidget(self.filename_input)

        self.filename_error = QLabel("")
        self.filename_error.setStyleSheet(
            "color: #ff4757; font-size: 11px; padding-top: 2px;")
        self.filename_error.setWordWrap(True)
        self.filename_error.hide()
        export_l.addWidget(self.filename_error)

        self.build_btn = QPushButton(self.t['build'])
        self.build_btn.setStyleSheet(styles['button_primary'])
        self.build_btn.setMinimumHeight(48)
        self.build_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.build_btn.setEnabled(False)
        self.build_btn.clicked.connect(self._on_export_vpk)
        export_l.addWidget(self.build_btn)

        export_l.addStretch(1)

        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(0)
        content_row.addWidget(split, 1)
        content_row.addWidget(export_col)
        split.setSizes([380, 800])
        # Левая колонка держит свою ширину, всё лишнее место — 3D-превью
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        left.setMinimumWidth(300)
        left.setMaximumWidth(460)
        split.setCollapsible(0, False)
        split.setCollapsible(1, False)

        root.addLayout(content_row, 1)

        # После создания превью: чипы уровня + гизмо области спавна
        self._set_level(0)

    # ── Загрузка PCF ─────────────────────────────────────────────────────── #

    def _populate_game_pcfs(self) -> None:
        self.pcf_combo.clear()
        self.pcf_combo.addItem(self.t['particles_pick_pcf'], None)
        if not self.tf2_root:
            self.view.show_error(self.t['particles_no_tf2'])
            return
        for path in ParticleEditorService.list_game_pcfs(self.tf2_root):
            self.pcf_combo.addItem(path.replace("particles/", ""), f"vpk:{path}")

    def _on_pcf_selected(self, index: int) -> None:
        source = self.pcf_combo.itemData(index)
        if source:
            self._load_source(source)

    def _on_open_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self.t['particles_pick_pcf'], "", "PCF (*.pcf)")
        if path:
            self._load_source(path)

    def _load_source(self, source: str) -> None:
        if self._worker is not None and self._worker.isRunning():
            # Загрузка уже идёт — запомним выбор и подхватим по завершении
            self._queued_source = source
            return
        self.view.show_loading(self.t['particles_loading'])
        self.systems_list.clear()
        self.attr_tree.clear()
        self.simple_widget.set_system(None)
        self.save_btn.setEnabled(False)
        self.build_btn.setEnabled(False)
        self.texture_btn.setEnabled(False)
        self.colors_btn.setEnabled(False)
        self._current_system = ""
        self._worker = _PcfLoadWorker(self.tf2_root, source, self)
        self._worker.finished.connect(self._on_load_finished)
        self._worker.start()

    def _on_load_finished(self, success: bool, message: str) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()  # иначе мёртвые QThread копятся детьми панели
        if self._queued_source is not None:
            # Пока грузились — пользователь выбрал другой PCF
            queued, self._queued_source = self._queued_source, None
            self._load_source(queued)
            return
        if not success or worker is None or worker.payload is None:
            logger.error(f"Загрузка PCF: {message}")
            self.view.show_error(f"{self.t['particles_load_error']}: {message}")
            return
        self.service = worker.service
        self._payload = worker.payload
        self.save_btn.setEnabled(True)
        self.build_btn.setEnabled(True)
        self.filename_input.setPlaceholderText(
            Path(self.service.pcf_vpk_path()).stem + "_particles")

        self.systems_list.clear()
        # Показываем только корневые определения (children достижимы из них)
        for name in self.service.system_names():
            self.systems_list.addItem(QListWidgetItem(name))
        self.view.load_data(self._payload)
        if self.systems_list.count() > 0:
            self.systems_list.setCurrentRow(0)

    # ── Выбор системы / дерево свойств ───────────────────────────────────── #

    def _on_system_selected(self, current, _previous) -> None:
        if current is None or self._payload is None:
            return
        # Недоприменённые правки крутилок/гизмо относятся к прежней системе:
        # их адреса (группа, индекс) в новой указывают на другие модули
        if self._simple_timer.isActive():
            self._simple_timer.stop()
            self._flush_simple_edit()
        if self._gizmo_timer.isActive():
            self._gizmo_timer.stop()
            self._flush_gizmo_edit()
        name = current.text()
        self._current_system = name
        self.texture_btn.setEnabled(True)
        self.colors_btn.setEnabled(True)
        self.view.set_root(name)
        self._fill_attr_tree(name)
        self._refresh_texture_cards()

    # ── 2D-карточки текстур ──────────────────────────────────────────────── #

    def _set_view_mode(self, mode: int) -> None:
        """0 = 3D-превью, 1 = 2D-карточки текстур."""
        self.mode_3d_btn.setStyleSheet(
            self._chip_active if mode == 0 else self._chip_inactive)
        self.mode_2d_btn.setStyleSheet(
            self._chip_active if mode == 1 else self._chip_inactive)
        self.view_stack.setCurrentIndex(mode)
        # Симуляция в фоне не нужна, пока смотрим карточки
        self.view.set_paused(mode == 1 or self._paused)

    def _effect_materials(self) -> list:
        """Материалы выбранного эффекта: корень + все дочерние системы,
        уникальные, в порядке обхода."""
        if self._payload is None or not self._current_system:
            return []
        systems = self._payload["systems"]
        out, seen, pending = [], set(), [self._current_system]
        visited = set()
        while pending:
            name = pending.pop(0)
            if name in visited:
                continue
            visited.add(name)
            s = systems.get(name)
            if s is None:
                continue
            mat = s["attrs"].get("material", {}).get("v")
            if mat and mat not in seen:
                seen.add(mat)
                out.append((mat, name))
            pending.extend(ch["childName"] for ch in s.get("children", []))
        return out

    def _refresh_texture_cards(self) -> None:
        self.texture_cards.clear()
        materials = self._payload.get("materials", {}) if self._payload else {}
        for mat, _first_system in self._effect_materials():
            info = materials.get(mat)
            data_url = info.get("dataUrl") if info else None
            stem = mat.replace("\\", "/").rsplit("/", 1)[-1]
            if stem.lower().endswith(".vmt"):
                stem = stem[:-4]
            item = QListWidgetItem(QIcon(_pixmap_from_data_url(data_url)), stem)
            item.setData(_ROLE_MATERIAL, mat)
            item.setToolTip(mat)
            self.texture_cards.addItem(item)

    def _on_card_menu(self, pos) -> None:
        """Контекстное меню карточки: игровая текстура / своя картинка / сброс."""
        item = self.texture_cards.itemAt(pos)
        if item is None or self.service is None:
            return
        self._flush_pending()
        mat = item.data(_ROLE_MATERIAL)
        menu = QMenu(self)
        act_game = menu.addAction(self.t['particles_pick_game_tex'])
        act_replace = menu.addAction(self.t['particles_set_texture'])
        menu.addSeparator()
        act_reset = menu.addAction(self.t['particles_reset_texture'])
        act_reset.setEnabled(self.service.is_custom_material(mat))
        chosen = menu.exec(self.texture_cards.mapToGlobal(pos))
        if chosen is act_game:
            self._pick_game_material(mat)
        elif chosen is act_replace:
            self._on_card_double_clicked(item)
        elif chosen is act_reset:
            self._reset_material_texture(mat)

    def _pick_game_material(self, card_material: str) -> None:
        """Выбор существующей игровой текстуры (работает в казуале — файл уже
        в игре, новый не создаётся)."""
        if self.service is None or self._payload is None:
            return
        t = self.t
        if not self.tf2_root:
            QMessageBox.information(
                self, t['particles_pick_game_tex'], t['particles_no_tf2'])
            return
        from PySide6.QtWidgets import QApplication
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            mats = self.service.game_effect_materials(self.tf2_root)
        finally:
            QApplication.restoreOverrideCursor()
        if not mats:
            return
        start = mats.index(card_material) if card_material in mats else 0
        chosen, ok = QInputDialog.getItem(
            self, t['particles_pick_game_tex'],
            t['particles_pick_game_prompt'], mats, start, True)
        chosen = (chosen or "").strip()
        if not ok or not chosen:
            return
        if not self.service.set_material_to_game(card_material, chosen):
            return
        self._payload["systems"] = self.service.systems_json()
        self._payload["materials"] = self.service.materials_json(self.tf2_root)
        self.view.load_data(self._payload, root_name=self._current_system)
        self._fill_attr_tree(self._current_system)
        self._refresh_texture_cards()

    def _reset_material_texture(self, material_name: str) -> None:
        """Возврат материала к исходной текстуре игры."""
        if self.service is None or self._payload is None:
            return
        orig = self.service.reset_material_texture(material_name)
        if orig is None:
            return
        self._payload["systems"] = self.service.systems_json()
        self._payload["materials"].pop(material_name, None)
        self.view.load_data(self._payload, root_name=self._current_system)
        self._fill_attr_tree(self._current_system)
        self._refresh_texture_cards()

    def _on_card_double_clicked(self, item: QListWidgetItem) -> None:
        self._flush_pending()
        mat = item.data(_ROLE_MATERIAL)
        path, _ = QFileDialog.getOpenFileName(
            self, self.t['particles_set_texture'], "",
            "Images (*.png *.jpg *.jpeg *.tga *.bmp *.webp *.gif)")
        if path:
            self._replace_material_texture(mat, path)

    def _replace_material_texture(self, material_name: str, image_path: str) -> None:
        """Замена текстуры материала (карточка 2D или кнопка тулбара)."""
        if self.service is None or self._payload is None:
            return
        t = self.t
        info0 = (self._payload.get("materials") or {}).get(material_name)
        if info0 and info0.get("sheet"):
            answer = QMessageBox.question(
                self, t['particles_set_texture'], t['particles_sheet_warning'],
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        max_size = next(
            (s for s, r in self._size_radios.items() if r.isChecked()), 512)
        res = self.service.set_material_texture(
            material_name, image_path, self.tf2_root,
            max_size=max_size,
            uncompressed=bool(self.format_combo.currentData()))
        if res is None:
            QMessageBox.warning(
                self, t['particles_set_texture'], t['particles_texture_error'])
            return
        new_mat, info = res
        self._payload["systems"] = self.service.systems_json()
        self._payload["materials"][new_mat] = info
        self.view.load_data(self._payload, root_name=self._current_system)
        self._fill_attr_tree(self._current_system)
        self._refresh_texture_cards()

    def _fill_attr_tree(self, system_name: str,
                        refresh_simple: bool = True) -> None:
        self.attr_tree.clear()
        # Карта (группа, индекс модуля, атрибут) → строка дерева: точечное
        # обновление без обхода (см. _refresh_tree_attr)
        self._attr_items = {}
        sys_json = self._payload["systems"].get(system_name)
        if sys_json is None:
            return

        def add_attr_items(parent_item, attrs: dict, group, mod_idx):
            for attr_name, tv in sorted(attrs.items()):
                if attr_name in ("functionname", "name", "id"):
                    continue
                value_text = _fmt_value(tv)
                item = QTreeWidgetItem([attr_name, value_text])
                # Длинные имена/значения обрезаются в колонке — полный текст в тултипе
                item.setToolTip(0, attr_name)
                item.setToolTip(1, value_text)
                item.setData(0, _ROLE_ATTR, (group, mod_idx, attr_name, tv["t"]))
                if tv["t"] == "color":
                    v = tv["v"]
                    item.setForeground(1, QColor(v[0], v[1], v[2]))
                parent_item.addChild(item)
                self._attr_items[(group, mod_idx, attr_name)] = item

        sys_item = QTreeWidgetItem([system_name, ""])
        self.attr_tree.addTopLevelItem(sys_item)
        add_attr_items(sys_item, sys_json["attrs"], None, 0)
        sys_item.setExpanded(True)

        for group in MODULE_GROUPS:
            mods = sys_json.get(group) or []
            # Пустые forces/constraints прячем; основные группы видны всегда —
            # иначе после удаления последнего модуля их не вернуть
            if not mods and group in ("forces", "constraints"):
                continue
            group_item = QTreeWidgetItem([group, ""])
            group_item.setData(0, _ROLE_GROUP, group)
            self.attr_tree.addTopLevelItem(group_item)
            for idx, mod in enumerate(mods):
                mod_item = QTreeWidgetItem([mod["functionName"], ""])
                mod_item.setData(0, _ROLE_MODULE, (group, idx))
                group_item.addChild(mod_item)
                add_attr_items(mod_item, mod["attrs"], group, idx)
            group_item.setExpanded(True)

        ch_item = QTreeWidgetItem(["children", ""])
        ch_item.setData(0, _ROLE_GROUP, "children")
        self.attr_tree.addTopLevelItem(ch_item)
        for idx, ch in enumerate(sys_json["children"]):
            child_item = QTreeWidgetItem(
                [ch["childName"], f"delay {ch['delay']:g}"])
            child_item.setData(0, _ROLE_CHILD, idx)
            ch_item.addChild(child_item)

        # Крутилки простого режима смотрят на тот же systems_json
        if refresh_simple:
            self._refresh_simple()

    # ── Структурное редактирование ───────────────────────────────────────── #

    def _structure_changed(self, keep_system: Optional[str] = None) -> None:
        """Обновляет payload/превью/дерево/список после структурной правки."""
        if self.service is None or self._payload is None:
            return
        self._payload["systems"] = self.service.systems_json()
        current = keep_system or self._current_system
        names = self.service.system_names()
        self.systems_list.blockSignals(True)
        self.systems_list.clear()
        for name in names:
            self.systems_list.addItem(QListWidgetItem(name))
        self.systems_list.blockSignals(False)
        if current in names:
            self.systems_list.setCurrentRow(names.index(current))
            self._current_system = current
            self.view.update_systems(self._payload["systems"], current)
            self._fill_attr_tree(current)
            self._refresh_texture_cards()
        elif names:
            # Текущую систему удалили — движку нужен новый набор ДО set_root
            self.view.update_systems(self._payload["systems"], names[0])
            self.systems_list.setCurrentRow(0)
        else:
            self._current_system = ""
            self.attr_tree.clear()
            self.texture_cards.clear()
            self.simple_widget.set_system(None)
            self.view.reset()

    def _on_systems_menu(self, pos) -> None:
        """Контекстное меню списка систем: дублировать / удалить / ребёнок."""
        item = self.systems_list.itemAt(pos)
        if item is None or self.service is None:
            return
        self._flush_pending()
        name = item.text()
        t = self.t
        menu = QMenu(self)
        act_layer = menu.addAction(t['particles_menu_add_layer'])
        menu.addSeparator()
        act_dup = menu.addAction(t['particles_menu_duplicate'])
        act_child = menu.addAction(t['particles_menu_add_child'])
        act_del = menu.addAction(t['particles_menu_remove_system'])
        chosen = menu.exec(self.systems_list.mapToGlobal(pos))
        if chosen is act_layer:
            self._on_add_layer(name)
        elif chosen is act_dup:
            new_name, ok = QInputDialog.getText(
                self, t['particles_menu_duplicate'],
                t['particles_new_name_prompt'], text=f"{name}_copy")
            new_name = new_name.strip()
            if ok and new_name and self.service.duplicate_system(name, new_name):
                self._structure_changed(keep_system=new_name)
        elif chosen is act_child:
            others = [n for n in self.service.system_names() if n != name]
            if not others:
                return
            child, ok = QInputDialog.getItem(
                self, t['particles_menu_add_child'],
                t['particles_pick_child'], others, 0, False)
            if ok and child and self.service.add_child(name, child):
                self._structure_changed(keep_system=name)
        elif chosen is act_del:
            answer = QMessageBox.question(
                self, t['particles_menu_remove_system'],
                t['particles_remove_system_confirm'].format(name=name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.Yes \
                    and self.service.remove_system(name):
                self._structure_changed()

    def _on_add_layer(self, parent_name: str) -> None:
        """Создаёт слой-залп с игровой текстурой по умолчанию и цепляет
        ребёнком. Текстуру потом меняют через 2D-карточку (игровую из списка
        или свою картинку)."""
        if self.service is None or self._payload is None:
            return
        t = self.t
        layer = self.service.add_layer(parent_name)
        if layer is None:
            QMessageBox.warning(
                self, t['particles_menu_add_layer'], t['particles_texture_error'])
            return
        # Слой выбран, его параметры сразу в дереве; переключаемся в 2D, чтобы
        # пользователь задал текстуру карточкой
        self._structure_changed(keep_system=layer)
        self._set_view_mode(1)
        QMessageBox.information(
            self, t['particles_menu_add_layer'], t['particles_layer_added'])

    def _on_tree_menu(self, pos) -> None:
        """Контекстное меню дерева: копи-паста параметров + структурные правки."""
        item = self.attr_tree.itemAt(pos)
        if item is None or self.service is None or not self._current_system:
            return
        self._flush_pending()
        t = self.t
        sys_name = self._current_system
        group = item.data(0, _ROLE_GROUP)
        module = item.data(0, _ROLE_MODULE)
        child_idx = item.data(0, _ROLE_CHILD)
        menu = QMenu(self)

        # Копи-паста — для всего, кроме children (там ссылки, не параметры)
        act_copy = act_copy_all = act_paste = None
        if child_idx is None and group != "children":
            act_copy = menu.addAction(t['particles_menu_copy'])
            act_copy_all = menu.addAction(t['particles_menu_copy_all'])
            act_paste = menu.addAction(t['particles_menu_paste'])
            act_paste.setEnabled(self._clipboard_payload() is not None)
            menu.addSeparator()

        act_add_child = act_add_module = act_del_module = act_del_child = None
        if group == "children":
            act_add_child = menu.addAction(t['particles_menu_add_child'])
        elif group in MODULE_GROUPS:
            act_add_module = menu.addAction(t['particles_menu_add_module'])
        elif module is not None:
            act_del_module = menu.addAction(t['particles_menu_remove_module'])
        elif child_idx is not None:
            act_del_child = menu.addAction(t['particles_menu_remove_child'])

        chosen = menu.exec(self.attr_tree.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is act_copy:
            self._on_copy_params()
        elif chosen is act_copy_all:
            self._on_copy_params(copy_all=True)
        elif chosen is act_paste:
            self._on_paste_params()
        elif chosen is act_add_child:
            others = [n for n in self.service.system_names() if n != sys_name]
            if not others:
                return
            child, ok = QInputDialog.getItem(
                self, t['particles_menu_add_child'],
                t['particles_pick_child'], others, 0, False)
            if ok and child and self.service.add_child(sys_name, child):
                self._structure_changed()
        elif chosen is act_add_module:
            catalog = MODULE_CATALOG.get(group, [])
            if not catalog:
                return
            fn, ok = QInputDialog.getItem(
                self, t['particles_menu_add_module'],
                t['particles_pick_module'], catalog, 0, True)
            fn = fn.strip()
            if ok and fn:
                # Поиск шаблона может сканировать стоковые PCF (один раз)
                from PySide6.QtWidgets import QApplication
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                try:
                    added = self.service.add_module(
                        sys_name, group, fn, self.tf2_root)
                finally:
                    QApplication.restoreOverrideCursor()
                if added:
                    self._structure_changed()
        elif chosen is act_del_module:
            mod_group, idx = module
            if self.service.remove_module(sys_name, mod_group, idx):
                self._structure_changed()
        elif chosen is act_del_child:
            if self.service.remove_child(sys_name, child_idx):
                self._structure_changed()

    # ── Копирование / вставка параметров ─────────────────────────────────── #

    def _on_copy_params(self, copy_all: bool = False) -> None:
        """Копирует выделенные строки дерева (или все параметры системы)
        в буфер обмена JSON-ом — вставляется в любую другую систему/PCF."""
        if self._payload is None or not self._current_system:
            return
        sys_json = self._payload["systems"].get(self._current_system)
        if not sys_json:
            return
        payload = {"attrs": {}, "modules": {}}
        # Модули копятся по (группа, индекс): дубли модулей (два одинаковых
        # functionName) сохраняются как отдельные записи в порядке источника
        mod_entries: dict = {}

        def add_module_attrs(g, mi, only_attr=None):
            mod = sys_json[g][mi]
            entry = mod_entries.setdefault(
                (g, mi), {"fn": mod["functionName"], "attrs": {}})
            for k, tv in mod["attrs"].items():
                if k in ("functionname", "name", "id"):
                    continue
                if only_attr is None or k == only_attr:
                    entry["attrs"][k] = tv

        def add_all():
            payload["full"] = True   # полный набор → выбор режима при вставке
            for k, tv in sys_json["attrs"].items():
                if k not in ("functionname", "name", "id"):
                    payload["attrs"][k] = tv
            for g in MODULE_GROUPS:
                for mi in range(len(sys_json.get(g) or [])):
                    add_module_attrs(g, mi)

        if copy_all:
            add_all()
        else:
            for item in self.attr_tree.selectedItems():
                meta = item.data(0, _ROLE_ATTR)
                module = item.data(0, _ROLE_MODULE)
                group = item.data(0, _ROLE_GROUP)
                if meta is not None:
                    g, mi, attr_name, _t = meta
                    if g is None:
                        tv = sys_json["attrs"].get(attr_name)
                        if tv is not None:
                            payload["attrs"][attr_name] = tv
                    else:
                        add_module_attrs(g, mi, only_attr=attr_name)
                elif module is not None:
                    g, mi = module
                    add_module_attrs(g, mi)
                elif group in MODULE_GROUPS:
                    for mi in range(len(sys_json.get(group) or [])):
                        add_module_attrs(group, mi)
                elif group is None and item.parent() is None:
                    add_all()   # строка самой системы = копировать всё
        for (g, _mi) in sorted(mod_entries):
            e = mod_entries[(g, _mi)]
            payload["modules"].setdefault(g, []).append([e["fn"], e["attrs"]])
        if not payload["attrs"] and not payload["modules"]:
            return
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(
            json.dumps({"tf2sgParticleParams": payload}))

    def _clipboard_payload(self) -> Optional[dict]:
        """Скопированные параметры из буфера обмена (None — там не наше).
        Буфер — внешний ввод: проверяем форму, чтобы вставка не падала."""
        from PySide6.QtWidgets import QApplication
        try:
            payload = json.loads(
                QApplication.clipboard().text()).get("tf2sgParticleParams")
            if not isinstance(payload, dict) \
                    or not isinstance(payload.get("attrs") or {}, dict) \
                    or not isinstance(payload.get("modules") or {}, dict):
                return None
        except Exception:
            return None
        return payload

    def _on_paste_params(self) -> None:
        """Вставляет параметры из буфера в выбранную систему: совпадающие
        перезаписываются молча, недостающие модули/атрибуты добавляются."""
        if self.service is None or self._payload is None \
                or not self._current_system:
            return
        payload = self._clipboard_payload()
        if payload is None \
                or not (payload.get("attrs") or payload.get("modules")):
            return
        mode = "overwrite"
        if payload.get("full"):
            # Полный набор: спросить, сохранять ли существующие параметры цели
            t = self.t
            box = QMessageBox(self)
            box.setWindowTitle(t['particles_menu_paste'])
            box.setText(t['particles_paste_full_prompt'])
            btn_keep = box.addButton(
                t['particles_paste_keep'], QMessageBox.ButtonRole.AcceptRole)
            btn_replace = box.addButton(
                t['particles_paste_replace'],
                QMessageBox.ButtonRole.DestructiveRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.exec()
            if box.clickedButton() is btn_keep:
                mode = "keep"
            elif box.clickedButton() is btn_replace:
                mode = "replace"
            else:
                return
        sys_name = self._current_system
        try:
            changed = self.service.paste_params(sys_name, payload, mode)
        except Exception as exc:
            # Глубже вложенный мусор из чужого буфера — не падаем
            logger.warning(f"Вставка параметров: {exc}")
            return
        if not changed:
            return
        self._payload["systems"] = self.service.systems_json()
        if self.tf2_root and (mode == "replace"
                              or "material" in (payload.get("attrs") or {})):
            # Материал мог смениться/удалиться — перерезолвить текстуры
            self._payload["materials"] = self.service.materials_json(
                self.tf2_root)
            self.view.load_data(self._payload, root_name=sys_name)
        else:
            self.view.update_systems(self._payload["systems"], sys_name)
        self._fill_attr_tree(sys_name)
        self._refresh_texture_cards()

    # ── Простой режим ────────────────────────────────────────────────────── #

    def _set_level(self, level: int) -> None:
        """0 = простой режим (крутилки), 1 = экспертный (дерево)."""
        self.level_simple_btn.setStyleSheet(
            self._chip_active if level == 0 else self._chip_inactive)
        self.level_expert_btn.setStyleSheet(
            self._chip_active if level == 1 else self._chip_inactive)
        self.prop_stack.setCurrentIndex(level)
        # Каркас области спавна — часть простого режима: в экспертном
        # позиция правится числами, лишняя графика там только мешает
        self.view.set_gizmo_visible(level == 0)

    def _flush_pending(self) -> None:
        """Применяет отложенные правки крутилок/гизмо прямо сейчас.

        Обязательно ПЕРЕД любым модальным диалогом: он крутит вложенный цикл
        событий, где таймеры продолжают тикать и могут пересобрать дерево —
        строки, с которыми работает вызвавший код, при этом умирают.
        """
        if self._simple_timer.isActive():
            self._simple_timer.stop()
            self._flush_simple_edit()
        if self._gizmo_timer.isActive():
            self._gizmo_timer.stop()
            self._flush_gizmo_edit()

    def _refresh_simple(self) -> None:
        """Перечитывает крутилки из payload (после любой правки/выбора)."""
        sys_json = None
        if self._payload is not None and self._current_system:
            sys_json = self._payload["systems"].get(self._current_system)
        self.simple_widget.set_system(sys_json)

    def _on_simple_edit(self, param, value) -> None:
        """Крутилка изменена → пишем те же атрибуты, что видит дерево.

        В Element-дерево пишем сразу (модель всегда актуальна), а пересборку
        systems_json + перезалив превью откладываем: у больших PCF это ~20 мс,
        а перетаскивание ползунка даёт десятки событий в секунду.
        """
        if self.service is None or self._payload is None \
                or not self._current_system:
            return
        sys_name = self._current_system
        sys_json = self._payload["systems"].get(sys_name)
        if sys_json is None:
            return
        calls = simple_params.write_calls(sys_json, param, value)
        if not calls:
            return
        for group, idx, attr, attr_type, val in calls:
            attrs = (sys_json["attrs"] if group is None
                     else sys_json[group][idx]["attrs"])
            if attr not in attrs:
                # Атрибут появится впервые — дереву нужна новая строка
                self._simple_pending_rebuild = True
            self.service.ensure_attr(sys_name, group, idx, attr, attr_type, val)
            self._simple_pending_attrs.add((group, idx, attr))
        self._simple_timer.start()

    def _flush_simple_edit(self) -> None:
        """Отложенное применение правок крутилок: превью + строки дерева."""
        if self.service is None or self._payload is None \
                or not self._current_system:
            return
        sys_name = self._current_system
        self._payload["systems"] = self.service.systems_json()
        self.view.update_systems(self._payload["systems"], sys_name)
        # Пока правим крутилками, обратный рефреш их же значений не нужен —
        # иначе программная установка дёргает виджет прямо под курсором
        if self._simple_pending_rebuild:
            self._fill_attr_tree(sys_name, refresh_simple=False)
        else:
            for group, idx, attr in self._simple_pending_attrs:
                self._refresh_tree_attr(group, idx, attr)
        self._simple_pending_rebuild = False
        self._simple_pending_attrs.clear()

    def _on_simple_enable(self, param) -> None:
        """Кнопка «Включить»: создаёт недостающие модули крутилки."""
        if self.service is None or self._payload is None \
                or not self._current_system:
            return
        sys_name = self._current_system
        sys_json = self._payload["systems"].get(sys_name)
        if sys_json is None:
            return
        self._flush_pending()
        from PySide6.QtWidgets import QApplication
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for group, fn in simple_params.missing_modules(sys_json, param):
                self.service.add_module(sys_name, group, fn, self.tf2_root)
        finally:
            QApplication.restoreOverrideCursor()
        self._structure_changed(keep_system=sys_name)

    def _on_gizmo_edit(self, payload_json: str) -> None:
        """Правка из драга ручки 3D-гизмо.

        JS уже мутировал свою копию systemsJson и показал результат — во
        время драга в превью НИЧЕГО не пушим (пуш пересоздаёт систему и
        эффект мигает). Здесь только Element-дерево + отложенно дерево/крутилки.
        Единственный пуш — по отпусканию кнопки, если пришлось создать модуль
        (его JS-заготовка не в списке инициализаторов живого инстанса).
        """
        if self.service is None or self._payload is None:
            return
        try:
            data = json.loads(payload_json)
            edits = list(data.get("edits") or [])
        except Exception:
            return
        sys_name = data.get("system")
        if not sys_name or sys_name != self._current_system:
            return
        sys_json = self._payload["systems"].get(sys_name)
        if sys_json is None:
            return
        final = bool(data.get("final"))
        created = False
        for e in edits:
            try:
                group, fn = e["group"], (e["fn"] or "").strip()
                attr, atype, value = e["attr"], e["type"], e["value"]
            except (KeyError, TypeError, AttributeError):
                continue
            if group not in MODULE_GROUPS or not fn or not attr:
                continue
            idx = simple_params._module_index(sys_json, group, fn)
            if idx is None:
                if not final:
                    continue      # модуль создаём один раз, по отпусканию
                if not self.service.add_module(sys_name, group, fn,
                                               self.tf2_root):
                    continue
                created = True
                self._payload["systems"] = self.service.systems_json()
                sys_json = self._payload["systems"][sys_name]
                idx = simple_params._module_index(sys_json, group, fn)
                if idx is None:
                    continue
            self.service.ensure_attr(sys_name, group, idx, attr, atype, value)
            self._gizmo_pending.add((group, idx, attr))
        if final:
            self._gizmo_timer.stop()
            self._flush_gizmo_edit()
            if created:
                self._payload["systems"] = self.service.systems_json()
                self.view.update_systems(self._payload["systems"], sys_name)
                self._fill_attr_tree(sys_name)
        else:
            self._gizmo_timer.start()

    def _flush_gizmo_edit(self) -> None:
        """Синхронизация модели/дерева/крутилок по правкам гизмо (без превью)."""
        if self.service is None or self._payload is None \
                or not self._current_system:
            return
        self._payload["systems"] = self.service.systems_json()
        for group, idx, attr in self._gizmo_pending:
            self._refresh_tree_attr(group, idx, attr)
        self._gizmo_pending.clear()
        self._refresh_simple()

    def _refresh_tree_attr(self, group, mod_idx: int, attr_name: str) -> None:
        """Обновляет одну строку дерева по адресу атрибута (без пересборки —
        она сворачивает ветки и сбрасывает прокрутку).

        Строка берётся из _attr_items, а не поиском по дереву:
        QTreeWidgetItemIterator держит СЫРЫЕ указатели, и пересборка дерева
        (её могут запустить таймеры прямо из-под модального диалога)
        превращала обход в access violation.
        """
        sys_json = self._payload["systems"].get(self._current_system)
        if sys_json is None:
            return
        try:
            # Адрес мог устареть (структурная правка при взведённом таймере)
            attrs = (sys_json["attrs"] if group is None
                     else sys_json[group][mod_idx]["attrs"])
        except (IndexError, KeyError):
            return
        tv = attrs.get(attr_name)
        item = self._attr_items.get((group, mod_idx, attr_name))
        if tv is None or item is None:
            return
        value_text = _fmt_value(tv)
        try:
            item.setText(1, value_text)
            item.setToolTip(1, value_text)
            if tv["t"] == "color":
                v = tv["v"]
                item.setForeground(1, QColor(v[0], v[1], v[2]))
        except RuntimeError:
            # Строку удалили пересборкой дерева — карта устарела
            self._attr_items.pop((group, mod_idx, attr_name), None)

    # ── Правка атрибутов ─────────────────────────────────────────────────── #

    def _on_attr_double_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        meta = item.data(0, _ROLE_ATTR)
        if meta is None or self.service is None:
            return
        self._flush_pending()   # диалог ниже крутит вложенный цикл событий
        group, mod_idx, attr_name, attr_type = meta
        sys_name = self._current_system
        sys_json = self._payload["systems"][sys_name]
        attrs = (sys_json["attrs"] if group is None
                 else sys_json[group][mod_idx]["attrs"])
        cur = attrs[attr_name]["v"]

        new_val = self._ask_value(attr_name, attr_type, cur)
        if new_val is None:
            return
        if not self.service.set_attr(sys_name, group, mod_idx, attr_name, new_val):
            QMessageBox.warning(self, "Error", f"set_attr failed: {attr_name}")
            return

        self._payload["systems"] = self.service.systems_json()
        if attr_name == "material" and self.tf2_root:
            # Материал сменили — перерезолвить текстуры и перезалить всё
            self._payload["materials"] = self.service.materials_json(self.tf2_root)
            self.view.load_data(self._payload, root_name=sys_name)
            self._refresh_texture_cards()
        else:
            # Обычная правка: только определения, текстуры остаются в GPU
            self.view.update_systems(self._payload["systems"], sys_name)

        # Обновляем ТОЛЬКО изменённую строку — пересборка дерева сворачивала
        # ветки и сбрасывала прокрутку наверх. Через карту строк, а не через
        # item: за время диалога дерево могло пересобраться
        self._refresh_tree_attr(group, mod_idx, attr_name)
        self._refresh_simple()   # та же правка видна крутилкам простого режима

    def _ask_value(self, attr_name: str, attr_type: str, cur):
        """Диалог правки по типу атрибута. None — отмена."""
        t = self.t
        if attr_type == "color":
            initial = QColor(cur[0], cur[1], cur[2], cur[3] if len(cur) > 3 else 255)
            color = QColorDialog.getColor(
                initial, self, attr_name,
                QColorDialog.ColorDialogOption.ShowAlphaChannel)
            if not color.isValid():
                return None
            return [color.red(), color.green(), color.blue(), color.alpha()]
        if attr_type == "bool":
            return not cur  # двойной клик — переключение
        if attr_type == "integer":
            val, ok = QInputDialog.getInt(
                self, attr_name, t['particles_val_prompt'], int(cur),
                -2147483648, 2147483647)
            return val if ok else None
        if attr_type in ("float", "time"):
            val, ok = QInputDialog.getDouble(
                self, attr_name, t['particles_val_prompt'], float(cur),
                -1e9, 1e9, 4)
            return val if ok else None
        if attr_type == "vec3":
            text, ok = QInputDialog.getText(
                self, attr_name, t['particles_vec3_prompt'],
                text=" ".join(f"{v:g}" for v in cur))
            if not ok:
                return None
            try:
                parts = [float(p) for p in text.replace(",", " ").split()]
                if len(parts) != 3:
                    return None
                return parts
            except ValueError:
                return None
        if attr_type == "string":
            text, ok = QInputDialog.getText(
                self, attr_name, t['particles_val_prompt'], text=str(cur))
            return text if ok else None
        return None

    # ── Тулбар ───────────────────────────────────────────────────────────── #

    def _on_set_texture(self) -> None:
        """Кнопка тулбара: замена текстуры ТОЛЬКО выбранной системы
        (другие системы с тем же материалом не трогаются; карточки в 2D
        меняют материал целиком)."""
        if self.service is None or not self._current_system or self._payload is None:
            return
        self._flush_pending()
        t = self.t
        sys_name = self._current_system
        cur_mat = (self._payload["systems"].get(sys_name, {})
                   .get("attrs", {}).get("material", {}).get("v"))
        if not cur_mat:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, t['particles_set_texture'], "",
            "Images (*.png *.jpg *.jpeg *.tga *.bmp *.webp *.gif)")
        if not path:
            return
        cur_info = (self._payload.get("materials") or {}).get(cur_mat)
        if cur_info and cur_info.get("sheet"):
            answer = QMessageBox.question(
                self, t['particles_set_texture'], t['particles_sheet_warning'],
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        max_size = next(
            (s for s, r in self._size_radios.items() if r.isChecked()), 512)
        res = self.service.set_system_texture(
            sys_name, path, self.tf2_root, max_size=max_size,
            uncompressed=bool(self.format_combo.currentData()))
        if res is None:
            QMessageBox.warning(
                self, t['particles_set_texture'], t['particles_texture_error'])
            return
        new_mat, info = res
        self._payload["systems"] = self.service.systems_json()
        self._payload["materials"][new_mat] = info
        self.view.load_data(self._payload, root_name=sys_name)
        self._fill_attr_tree(sys_name)
        self._refresh_texture_cards()

    def _on_natural_colors(self) -> None:
        """Убирает модули тинта у эффекта — текстуры в родных цветах."""
        if self.service is None or not self._current_system or self._payload is None:
            return
        self._flush_pending()
        t = self.t
        answer = QMessageBox.question(
            self, t['particles_natural_colors'], t['particles_colors_confirm'],
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        removed = self.service.use_texture_colors(self._current_system)
        if removed == 0:
            QMessageBox.information(
                self, t['particles_natural_colors'], t['particles_colors_none'])
            return
        sys_name = self._current_system
        self._payload["systems"] = self.service.systems_json()
        self.view.update_systems(self._payload["systems"], sys_name)
        self._fill_attr_tree(sys_name)
        QMessageBox.information(
            self, t['particles_natural_colors'],
            t['particles_colors_done'].format(count=removed))

    def _on_export_vpk(self) -> None:
        """Сборка VPK-мода в папку экспорта из настроек (как оружие)."""
        if self.service is None:
            return
        t = self.t
        name = self.filename_input.text().strip()
        if not name:
            name = self.filename_input.placeholderText() or "particles_mod"
        if name.lower().endswith(".vpk"):
            name = name[:-4]
        # Та же валидация, что у сборки оружия (settings_panel)
        for char in ('<', '>', ':', '"', '/', '\\', '|', '?', '*'):
            if char in name:
                self.filename_error.setText(
                    t.get('invalid_char_error',
                          'Invalid character: {char}').format(char=char))
                self.filename_error.show()
                return
        if len(name) > 50:
            self.filename_error.setText(
                t.get('filename_too_long_error',
                      'Filename is too long (max 50 characters)'))
            self.filename_error.show()
            return
        self.filename_error.hide()

        from src.config.app_config import AppConfig
        export_folder = AppConfig.load_config().get("export_folder", "export")
        dest = str(Path(export_folder) / f"{name}.vpk")
        try:
            out = self.service.export_vpk(dest, language=self.language)
        except Exception as exc:
            logger.error(f"Сборка VPK частиц: {exc}", exc_info=True)
            QMessageBox.critical(self, t.get('error', 'Error'), str(exc))
            return
        msg = t['particles_vpk_done'].format(path=out)
        if self.service.last_textures_vpk:
            msg += "\n\n" + t.get(
                'particles_textures_vpk_done', 'Textures VPK: {path}',
            ).format(path=self.service.last_textures_vpk)
        # Казуал-бай-пасс не грузит PCF больше оригинала — предупреждаем
        overflow = self.service.casual_size_overflow()
        if overflow is not None and overflow > 0:
            msg += "\n\n" + t['particles_casual_overflow'].format(bytes=overflow)
        QMessageBox.information(self, t['particles_build_vpk'], msg)

    def _on_save_as(self) -> None:
        if self.service is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, self.t['particles_save_as'], "", "PCF (*.pcf)")
        if not path:
            return
        try:
            self.service.save(path)
        except Exception as exc:
            QMessageBox.critical(self, self.t.get('error', 'Error'), str(exc))
            return
        QMessageBox.information(
            self, self.t['particles_title'],
            self.t['particles_saved'].format(path=path))

    def _on_restart(self) -> None:
        self.view.restart()

    def _on_pause(self) -> None:
        self._paused = not self._paused
        # В 2D-режиме симуляция остаётся на паузе независимо от кнопки
        self.view.set_paused(
            self._paused or self.view_stack.currentIndex() == 1)
        self.pause_btn.setIcon(
            self._icon_play if self._paused else self._icon_pause)
        self.pause_btn.setToolTip(
            self.t['particles_play'] if self._paused else self.t['particles_pause'])

    def set_tf2_root(self, tf2_root: str) -> None:
        """Подхватывает смену пути TF2 из настроек без перезапуска приложения."""
        if tf2_root == self.tf2_root:
            return
        self.tf2_root = tf2_root
        self._populate_game_pcfs()

    # ── Язык ─────────────────────────────────────────────────────────────── #

    def update_language(self, language: str) -> None:
        """Перевод открытого окна при смене языка приложения."""
        self.language = language
        self.t = TRANSLATIONS.get(language, TRANSLATIONS['en'])
        t = self.t
        self.open_btn.setToolTip(t['particles_open_file'])
        self.texture_btn.setToolTip(t['particles_set_texture'])
        self.colors_btn.setToolTip(t['particles_natural_colors'])
        self.save_btn.setToolTip(t['particles_save_as'])
        self.restart_btn.setToolTip(t['particles_restart'])
        self.pause_btn.setToolTip(
            t['particles_play'] if self._paused else t['particles_pause'])
        self.export_title.setText(t.get('step_2_export', 'Export'))
        self.res_label.setText(t['resolution'])
        self.format_label.setText(t['format_vtf'])
        self.filename_label.setText(t['filename_vpk'])
        if not self.filename_input.text() and self.service is None:
            self.filename_input.setPlaceholderText(t['placeholder'])
        self.build_btn.setText(t['build'])
        self.pause_btn.setText(
            t['particles_play'] if self._paused else t['particles_pause'])
        if self.pcf_combo.count() > 0:
            self.pcf_combo.setItemText(0, t['particles_pick_pcf'])
        self.cards_hint.setText(t['particles_2d_hint'])
        self.prop_lbl.setText(t['particles_properties'])
        self.level_simple_btn.setText(t['particles_level_simple'])
        self.level_expert_btn.setText(t['particles_level_expert'])
        self.simple_widget.update_language(t)
        self.view.set_language(language)

    # ── Завершение ───────────────────────────────────────────────────────── #

    def shutdown(self) -> None:
        """Останавливает фоновый воркер — вызывается при закрытии приложения."""
        if self._worker is not None:
            self._worker.stop()


def _fmt_value(tv: dict) -> str:
    """Отображаемое значение атрибута в дереве."""
    t, v = tv["t"], tv["v"]
    if t == "color":
        return f"[{v[0]}, {v[1]}, {v[2]}, {v[3] if len(v) > 3 else 255}]"
    if t == "vec3":
        return " ".join(f"{x:g}" for x in v)
    if t in ("float", "time"):
        return f"{v:g}"
    if t == "bool":
        return "true" if v else "false"
    return str(v)
