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

from PySide6.QtCore import QByteArray, QObject, QSize, Qt, Signal, Slot
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QColorDialog, QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
    QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton, QSplitter,
    QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from src.data.translations import TRANSLATIONS
from src.services.base_worker import StandardWorker
from src.services.particle_editor_service import MODULE_GROUPS, ParticleEditorService
from src.shared.logging_config import get_logger
from src.ui.preview_3d_widget import is_webengine_available
from src.ui.styled_dialog import _colors
from src.ui.preview_3d_widget import _get_html_path  # dev/frozen пути к static

logger = get_logger(__name__)

_ROLE_ATTR = Qt.ItemDataRole.UserRole  # (group|None, module_idx, attr_name, type)


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

    @Slot()
    def notifyReady(self) -> None:  # noqa: N802
        self.ready.emit()


# ── Виджет превью ────────────────────────────────────────────────────────── #

class ParticleViewWidget(QWidget):
    """QWebEngineView с particles3d.html (или заглушка без WebEngine)."""

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
        self._worker: Optional[_PcfLoadWorker] = None
        self._queued_source: Optional[str] = None
        self._current_system: str = ""
        self._paused = False

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

        # ── Тулбар ───────────────────────────────────────────────────────── #
        bar = QWidget()
        bar_l = QHBoxLayout(bar)
        bar_l.setContentsMargins(0, 0, 0, 8)
        bar_l.setSpacing(8)

        self.pcf_combo = QComboBox()
        self.pcf_combo.setFixedWidth(340)
        # Родной стиль приложения + непрокручиваемый попап с ограничением высоты
        self.pcf_combo.setStyleSheet(
            styles['combo'] + "QComboBox { combobox-popup: 0; }")
        self.pcf_combo.setMaxVisibleItems(18)
        self.pcf_combo.activated.connect(self._on_pcf_selected)
        bar_l.addWidget(self.pcf_combo)

        for attr_name, key, slot in (
            ('open_btn', 'particles_open_file', self._on_open_file),
            ('texture_btn', 'particles_set_texture', self._on_set_texture),
            ('colors_btn', 'particles_natural_colors', self._on_natural_colors),
            ('save_btn', 'particles_save_as', self._on_save_as),
            ('vpk_btn', 'particles_build_vpk', self._on_export_vpk),
            ('restart_btn', 'particles_restart', self._on_restart),
            ('pause_btn', 'particles_pause', self._on_pause),
        ):
            btn = QPushButton(self.t[key])
            btn.setStyleSheet(styles['button_secondary'])
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(slot)
            setattr(self, attr_name, btn)
            bar_l.addWidget(btn)

        bar_l.addStretch(1)
        self.save_btn.setEnabled(False)
        self.vpk_btn.setEnabled(False)
        self.texture_btn.setEnabled(False)
        self.colors_btn.setEnabled(False)
        root.addWidget(bar)

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
        sys_box_l.addWidget(self.systems_list, 1)
        left.addWidget(sys_box)

        prop_box = QWidget()
        prop_box_l = QVBoxLayout(prop_box)
        prop_box_l.setContentsMargins(0, 4, 6, 0)
        prop_box_l.setSpacing(6)
        prop_lbl = QLabel(self.t['particles_properties'])
        prop_lbl.setStyleSheet(lbl_style)
        prop_box_l.addWidget(prop_lbl)

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
        prop_box_l.addWidget(self.attr_tree, 1)
        left.addWidget(prop_box)

        left.setSizes([240, 420])
        left.setCollapsible(0, False)
        left.setCollapsible(1, False)

        split.addWidget(left)

        # ── Правая часть: переключатель 3D/2D + стек превью/карточек ──────── #
        right = QWidget()
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(0, 0, 0, 0)
        right_l.setSpacing(4)

        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.addStretch(1)
        toggle_style = styles['button_secondary'] + """
            QPushButton { padding: 4px 16px; }
            QPushButton:checked {
                background-color: #ff6b35; color: #0a0a0a; border-color: #ff6b35;
            }
        """
        self.mode_3d_btn = QPushButton("3D")
        self.mode_2d_btn = QPushButton("2D")
        for btn, mode in ((self.mode_3d_btn, 0), (self.mode_2d_btn, 1)):
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(toggle_style)
            btn.clicked.connect(lambda _=False, m=mode: self._set_view_mode(m))
            mode_row.addWidget(btn)
        self.mode_3d_btn.setChecked(True)
        right_l.addLayout(mode_row)

        self.view = ParticleViewWidget(self, language=self.language)

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
        split.setSizes([380, 800])
        # Левая колонка держит свою ширину, всё лишнее место — 3D-превью
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        left.setMinimumWidth(300)
        left.setMaximumWidth(460)
        split.setCollapsible(0, False)
        split.setCollapsible(1, False)

        root.addWidget(split, 1)

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
        self.save_btn.setEnabled(False)
        self.vpk_btn.setEnabled(False)
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
        self.vpk_btn.setEnabled(True)

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
        self.mode_3d_btn.setChecked(mode == 0)
        self.mode_2d_btn.setChecked(mode == 1)
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
        """Контекстное меню карточки: заменить / вернуть текстуру игры."""
        item = self.texture_cards.itemAt(pos)
        if item is None or self.service is None:
            return
        mat = item.data(_ROLE_MATERIAL)
        menu = QMenu(self)
        act_replace = menu.addAction(self.t['particles_set_texture'])
        act_reset = menu.addAction(self.t['particles_reset_texture'])
        act_reset.setEnabled(self.service.is_custom_material(mat))
        chosen = menu.exec(self.texture_cards.mapToGlobal(pos))
        if chosen is act_replace:
            self._on_card_double_clicked(item)
        elif chosen is act_reset:
            self._reset_material_texture(mat)

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
        res = self.service.set_material_texture(
            material_name, image_path, self.tf2_root)
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

    def _fill_attr_tree(self, system_name: str) -> None:
        self.attr_tree.clear()
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

        sys_item = QTreeWidgetItem([system_name, ""])
        self.attr_tree.addTopLevelItem(sys_item)
        add_attr_items(sys_item, sys_json["attrs"], None, 0)
        sys_item.setExpanded(True)

        for group in MODULE_GROUPS:
            mods = sys_json.get(group) or []
            if not mods:
                continue
            group_item = QTreeWidgetItem([group, ""])
            self.attr_tree.addTopLevelItem(group_item)
            for idx, mod in enumerate(mods):
                mod_item = QTreeWidgetItem([mod["functionName"], ""])
                group_item.addChild(mod_item)
                add_attr_items(mod_item, mod["attrs"], group, idx)
            group_item.setExpanded(True)

        if sys_json["children"]:
            ch_item = QTreeWidgetItem(["children", ""])
            self.attr_tree.addTopLevelItem(ch_item)
            for ch in sys_json["children"]:
                ch_item.addChild(QTreeWidgetItem(
                    [ch["childName"], f"delay {ch['delay']:g}"]))

    # ── Правка атрибутов ─────────────────────────────────────────────────── #

    def _on_attr_double_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        meta = item.data(0, _ROLE_ATTR)
        if meta is None or self.service is None:
            return
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
        self._fill_attr_tree(sys_name)

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
        """Кнопка тулбара: замена текстуры материала выбранной системы."""
        if self.service is None or not self._current_system or self._payload is None:
            return
        cur_mat = (self._payload["systems"].get(self._current_system, {})
                   .get("attrs", {}).get("material", {}).get("v"))
        if not cur_mat:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, self.t['particles_set_texture'], "",
            "Images (*.png *.jpg *.jpeg *.tga *.bmp *.webp *.gif)")
        if path:
            self._replace_material_texture(cur_mat, path)

    def _on_natural_colors(self) -> None:
        """Убирает модули тинта у эффекта — текстуры в родных цветах."""
        if self.service is None or not self._current_system or self._payload is None:
            return
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
        """Сборка VPK-мода: правленый PCF + кастомные материалы."""
        if self.service is None:
            return
        t = self.t
        default_name = Path(self.service.pcf_vpk_path()).stem + "_mod.vpk"
        path, _ = QFileDialog.getSaveFileName(
            self, t['particles_build_vpk'], default_name, "VPK (*.vpk)")
        if not path:
            return
        try:
            out = self.service.export_vpk(path, language=self.language)
        except Exception as exc:
            logger.error(f"Сборка VPK частиц: {exc}", exc_info=True)
            QMessageBox.critical(self, t.get('error', 'Error'), str(exc))
            return
        QMessageBox.information(
            self, t['particles_build_vpk'],
            t['particles_vpk_done'].format(path=out))

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
        self.pause_btn.setText(
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
        self.open_btn.setText(t['particles_open_file'])
        self.texture_btn.setText(t['particles_set_texture'])
        self.colors_btn.setText(t['particles_natural_colors'])
        self.save_btn.setText(t['particles_save_as'])
        self.vpk_btn.setText(t['particles_build_vpk'])
        self.restart_btn.setText(t['particles_restart'])
        self.pause_btn.setText(
            t['particles_play'] if self._paused else t['particles_pause'])
        if self.pcf_combo.count() > 0:
            self.pcf_combo.setItemText(0, t['particles_pick_pcf'])
        self.cards_hint.setText(t['particles_2d_hint'])
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
