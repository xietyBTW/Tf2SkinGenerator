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
import os
import shutil
from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    QByteArray, QLocale, QObject, QSize, Qt, QTimer, Signal, Slot,
)
from PySide6.QtGui import (
    QColor, QFontMetrics, QIcon, QKeySequence, QPixmap, QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QButtonGroup, QColorDialog, QComboBox,
    QDialog, QDoubleSpinBox, QFileDialog, QFrame, QSpinBox,
    QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPushButton, QRadioButton,
    QScrollArea, QSizePolicy, QSlider, QSplitter, QStackedWidget, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from src.data.translations import TRANSLATIONS
from src.data import particle_docs
from src.services import particle_lint, simple_params
from src.services.base_worker import StandardWorker
from src.services.particle_editor_service import (
    MAX_CONTROL_POINTS, MODULE_GROUPS, ParticleEditorService,
    referenced_control_points, system_hierarchy,
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

class _CatalogWarmWorker(StandardWorker):
    """Прогревает каталог параметров модулей в фоне.

    Сбор идёт по всем PCF игры (секунды) и нужен только когда пользователь
    полезет добавлять параметр — к этому моменту он уже готов, а после
    первого раза поднимается с диска мгновенно."""

    def __init__(self, tf2_root: str, parent=None):
        super().__init__(parent)
        self._tf2_root = tf2_root

    def work(self):
        try:
            ParticleEditorService.build_attr_catalog(self._tf2_root)
        except Exception as exc:      # прогрев не должен ломать работу
            logger.warning(f"Каталог параметров не собран: {exc}")
        return True, ""


#: Имя системы на узле дерева: текст показывать можно разный, адресуемся по роли
_ROLE_SYSTEM = Qt.ItemDataRole.UserRole + 11


def _sys_item(name: str) -> QTreeWidgetItem:
    item = QTreeWidgetItem([name])
    item.setData(0, _ROLE_SYSTEM, name)
    return item


def _sys_node(node) -> QTreeWidgetItem:
    """Узел с поддеревом: (имя, [дети]) из system_hierarchy."""
    name, kids = node
    item = _sys_item(name)
    for kid in kids:
        item.addChild(_sys_node(kid))
    return item


class _ParticleBridge(QObject):
    ready = Signal()
    gizmo_edit = Signal(str)   # JSON {system, edits: [...], final}
    support = Signal(str)      # JSON: какие модули движок умеет исполнять

    @Slot()
    def notifyReady(self) -> None:  # noqa: N802
        self.ready.emit()

    @Slot(str)
    def reportSupport(self, payload: str) -> None:  # noqa: N802
        """Список модулей, реализованных движком превью."""
        self.support.emit(payload)

    @Slot(str)
    def gizmoEdit(self, payload: str) -> None:  # noqa: N802
        """Драг ручки гизмо в 3D-превью — правка атрибутов из JS."""
        self.gizmo_edit.emit(payload)


# ── Виджет превью ────────────────────────────────────────────────────────── #

class ParticleViewWidget(QWidget):
    """QWebEngineView с particles3d.html (или заглушка без WebEngine)."""

    gizmo_edited = Signal(str)     # проброс _ParticleBridge.gizmo_edit
    support_reported = Signal(str)  # проброс _ParticleBridge.support

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
        from PySide6.QtWebEngineCore import QWebEngineProfile
        from PySide6.QtWebEngineWidgets import QWebEngineView

        self._view = QWebEngineView(self)
        # Без этого QtWebEngine кэширует engine.js как file://-модуль и после
        # обновления приложения может отдать старую версию движка — правки
        # симуляции «не применяются». Превью лёгкое, кэш ему не нужен.
        try:
            self._view.page().profile().setHttpCacheType(
                QWebEngineProfile.HttpCacheType.NoCache)
        except Exception:
            pass
        self._bridge = _ParticleBridge()
        self._bridge.ready.connect(self._on_ready)
        self._bridge.gizmo_edit.connect(self.gizmo_edited)
        self._bridge.support.connect(self.support_reported)
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

    def set_control_point(self, index: int, x: float, y: float, z: float) -> None:
        self._run(f"window.setControlPoint({int(index)}, {x}, {y}, {z})")

    def set_control_point_orientation(
            self, index: int, pitch: float, yaw: float, roll: float) -> None:
        """Углы Source (pitch/yaw/roll) — от них зависят локальные системы
        координат инициализаторов и плоскость спрайтов orientation_type 2/3."""
        self._run(
            f"window.setControlPointOrientation({int(index)}, {pitch}, {yaw}, {roll})")

    def clear_control_point_orientation(self, index: int) -> None:
        self._run(f"window.clearControlPointOrientation({int(index)})")

    def set_control_point_motion(
            self, index: int, kind: str, amp: float, period: float) -> None:
        self._run(
            f"window.setControlPointMotion({int(index)}, {json.dumps(kind)}, "
            f"{amp}, {period})")

    def load_model_obj(self, obj_text: str, textures: Optional[dict] = None) -> None:
        """Меш модели в сцену. OBJ уже в осях Source (keep_source_axes),
        textures — {имя материала: data URL PNG}."""
        self._run(f"window.loadModelObj({json.dumps(obj_text)}, "
                  f"{json.dumps(textures or {})})")

    def set_model_visible(self, visible: bool) -> None:
        self._run(f"window.setModelVisible({json.dumps(bool(visible))})")

    def clear_model(self) -> None:
        self._run("window.clearModel()")

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


def _is_animated(image_path: str) -> bool:
    """Гифка/APNG: замена НЕ убивает покадровую анимацию материала (свои кадры
    едут в многокадровый VTF), поэтому предупреждение про статику не нужно."""
    from src.services.texture_service import TextureService
    return TextureService.is_animated_image(image_path)


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

class _ElidingLabel(QLabel):
    """Подпись, которая при нехватке ширины сокращается многоточием.

    Панель узкая и меняет ширину вместе с окном. Обычный QLabel в этом
    случае либо распирает колонку (и появляется горизонтальная прокрутка),
    либо обрезается без всякого знака. Здесь текст всегда виден целиком в
    подсказке, а в строке — ровно столько, сколько поместилось.
    """

    #: До скольких пикселей подпись разрешено ужимать, прежде чем от неё
    #: останется одно многоточие.
    _MIN_WIDTH = 48
    #: Сколько подпись вправе занять максимум: длинное имя параметра иначе
    #: съедает ползунок, ради которого строка и существует.
    _MAX_WIDTH = 132

    def __init__(self, parent=None):
        super().__init__(parent)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Preferred)

    def setFullText(self, text: str) -> None:
        self._full = text
        self.updateGeometry()
        self._relayout()

    def sizeHint(self) -> QSize:
        """Желаемая ширина — под ПОЛНЫЙ текст: пока места хватает, подпись
        видна целиком, и колонка не растекается сверх нужного."""
        hint = super().sizeHint()
        width = QFontMetrics(self.font()).horizontalAdvance(self._full)
        return QSize(min(width, self._MAX_WIDTH), hint.height())

    def minimumSizeHint(self) -> QSize:
        """А сжаться подпись разрешает почти до нуля — иначе длинное имя
        параметра распирало бы панель и включало горизонтальную прокрутку."""
        return QSize(self._MIN_WIDTH, super().minimumSizeHint().height())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self) -> None:
        metrics = QFontMetrics(self.font())
        super().setText(metrics.elidedText(
            self._full, Qt.TextElideMode.ElideRight, max(0, self.width())))


class _ParamEditor:
    """
    Редакторы одной крутилки простого режима.

    Держит свои виджеты и умеет три вещи: собрать себя в ряд, показать
    значение из модели, перейти в режим заготовки. Про SimpleParam знает всё,
    про панель — ничего: правки уходят через колбэк. Новый вид крутилки =
    новый подкласс + строка в _EDITORS, остальной виджет не меняется.

    Заготовка — строка параметра, модуля под которым в эффекте ещё нет.
    Она не выключена: показывает умолчание бледным, а первая же правка
    создаёт модуль и записывает значение. Отдельной кнопки «Включить» нет
    намеренно — она съедала целую колонку и выдавливала подписи за край.
    """

    def __init__(self, param, style: dict, on_edit):
        self.param = param
        self._style = style
        self._on_edit = on_edit
        self._silent = False        # гасит эхо при программной установке
        self.widgets: list = []

    # ── Переопределяется подклассами ─────────────────────────────────────
    def build(self, box: QHBoxLayout) -> None:
        raise NotImplementedError

    def set_value(self, value) -> None:
        raise NotImplementedError

    # ── Общее ────────────────────────────────────────────────────────────
    def set_placeholder(self, on: bool) -> None:
        """Бледный вид «этого в эффекте пока нет» без потери интерактивности."""
        for w in self.widgets:
            w.setProperty("placeholder", on)
            # Смена свойства сама по себе стиль не пересчитывает
            w.style().unpolish(w)
            w.style().polish(w)

    def set_visible(self, on: bool) -> None:
        for w in self.widgets:
            w.setVisible(on)

    def _emit(self, value) -> None:
        if not self._silent:
            self._on_edit(self.param, value)

    def _make_spin(self) -> QDoubleSpinBox:
        """Числовое поле. Диапазон — ЖЁСТКИЙ (input_min/max), а не диапазон
        ползунка: в стоковых PCF есть emission_rate 999999 и «вечная» жизнь
        1e10, и показать их урезанными значит молча испортить чужой эффект."""
        spin = _NumSpin()
        spin.setRange(self.param.input_min, self.param.input_max)
        spin.setDecimals(self.param.decimals)
        spin.setStyleSheet(self._style["spin"])
        # Поле не должно съедать ползунок: у QAbstractSpinBox политика
        # Expanding, и без потолка он забирал всю свободную ширину строки
        spin.setMinimumWidth(56)
        spin.setMaximumWidth(88)
        spin.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Fixed)
        spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        # Без этого правка уходит в модель на КАЖДЫЙ символ: набор «12.5»
        # писал 1 → 12 → 125. Значение фиксируется по Enter/потере фокуса.
        spin.setKeyboardTracking(False)
        return spin


class _ValueEditor(_ParamEditor):
    """Ползунок + поле. Ползунок ходит по МЯГКОМУ диапазону (99% эффектов)
    и по кривой параметра; поле принимает всё до жёсткой границы."""

    _STEPS = 1000

    def build(self, box: QHBoxLayout) -> None:
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, self._STEPS)
        self.spin = self._make_spin()
        self.slider.valueChanged.connect(self._on_slider)
        self.spin.valueChanged.connect(self._on_spin)
        box.addWidget(self.slider, 1)
        box.addWidget(self.spin)
        self.widgets = [self.slider, self.spin]

    def _on_slider(self, pos: int) -> None:
        if self._silent:
            return
        value = simple_params.curve_value(self.param, pos / self._STEPS)
        if self.param.decimals == 0:
            value = round(value)
        self._set_spin(value)
        self._emit(self.spin.value())

    def _on_spin(self, value: float) -> None:
        if self._silent:
            return
        self._set_slider(value)
        self._emit(value)

    def _set_spin(self, value: float) -> None:
        was, self._silent = self._silent, True
        self.spin.setValue(float(value))
        self._silent = was

    def _set_slider(self, value: float) -> None:
        was, self._silent = self._silent, True
        self.slider.setValue(
            round(simple_params.curve_fraction(self.param, value) * self._STEPS))
        self._silent = was

    def set_value(self, value) -> None:
        self._set_spin(value)
        self._set_slider(self.spin.value())


class _RangeEditor(_ParamEditor):
    """Пара «мин/макс» одним смыслом: два поля, правка любого шлёт обе."""

    def build(self, box: QHBoxLayout) -> None:
        self.spins = [self._make_spin(), self._make_spin()]
        for spin in self.spins:
            spin.valueChanged.connect(self._on_changed)
            box.addWidget(spin, 1)
        self.widgets = list(self.spins)

    def _on_changed(self, _value: float) -> None:
        self._emit(tuple(s.value() for s in self.spins))

    def set_value(self, value) -> None:
        was, self._silent = self._silent, True
        for spin, v in zip(self.spins, value):
            spin.setValue(float(v))
        self._silent = was


class _ColorPairEditor(_ParamEditor):
    """Две кнопки-плашки цвета (color1/color2 у Color Random)."""

    _WHITE = [255, 255, 255, 255]

    def build(self, box: QHBoxLayout) -> None:
        self.buttons = []
        for i in (0, 1):
            btn = QPushButton()
            btn.setFixedSize(44, 22)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, n=i: self._pick(n))
            box.addWidget(btn)
            self.buttons.append(btn)
        box.addStretch(1)
        self.widgets = list(self.buttons)

    def _colors(self) -> list:
        return [list(b.property("_rgba") or self._WHITE) for b in self.buttons]

    def _pick(self, index: int) -> None:
        cur = self._colors()[index]
        initial = QColor(cur[0], cur[1], cur[2],
                         cur[3] if len(cur) > 3 else 255)
        color = QColorDialog.getColor(
            initial, self.buttons[index], "",
            QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if not color.isValid():
            return
        vals = self._colors()
        vals[index] = [color.red(), color.green(), color.blue(), color.alpha()]
        self.set_value(vals)
        self._emit(tuple(vals))

    def set_value(self, value) -> None:
        for btn, col in zip(self.buttons, value):
            btn.setProperty("_rgba", list(col))
            btn.setStyleSheet(
                f"background: rgb({col[0]},{col[1]},{col[2]});"
                "border: 1px solid #444; border-radius: 3px;")


#: kind из схемы → класс редактора.
_EDITORS = {
    "value": _ValueEditor,
    "range": _RangeEditor,
    "color_pair": _ColorPairEditor,
}


class _SimpleParamsWidget(QWidget):
    """Крутилки простого режима. Строится из SIMPLE_PARAMS: новая крутилка в
    схеме появляется здесь сама. Значения читает из systems_json, правки
    шлёт сигналом edited — панель применяет их через сервис (единый источник
    правды, дерево экспертного режима обновляется тем же путём).

    Две колонки, подпись и редактор: третья («Включить») отсюда убрана —
    при ширине панели в 330 пикселей она выдавливала и подписи, и поля за
    край, а вернуться к ним можно было только горизонтальной прокруткой.
    Вместо кнопки — заготовка: параметр, модуля под который в эффекте нет,
    показывается бледным умолчанием, и первая же правка создаёт модуль.
    """

    edited = Signal(object, object)      # (SimpleParam, значение)

    def __init__(self, t: dict, colors: dict, parent=None):
        super().__init__(parent)
        self._c = colors
        self._rows: dict = {}            # key -> {param, label, editor}
        self._sys_json: Optional[dict] = None

        c = colors
        # Заготовка отличается от обычного поля только бледностью: она
        # рабочая, поэтому не :disabled, а собственное свойство
        self._style = {"spin": f"""
            QDoubleSpinBox {{
                background: {c['surface']}; color: {c['text']};
                border: 1px solid {c['border']}; border-radius: 3px;
                padding: 2px 4px; font-size: 12px;
            }}
            QDoubleSpinBox[placeholder="true"] {{
                color: #666; border-style: dashed;
            }}
        """}
        self._label_style = f"color: {c['text']}; font-size: 12px;"

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
        # Свободная ширина достаётся полям: подпись берёт себе ровно
        # столько, сколько нужно её тексту, и ужимается только когда места
        # не хватает даже полям
        self._grid.setColumnStretch(0, 0)
        self._grid.setColumnStretch(1, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        # Горизонтальной прокрутки быть не должно: подписи сокращаются
        # многоточием, а поля сжимаются до своего минимума
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        body.setStyleSheet("background: transparent;")
        scroll.setWidget(body)
        outer.addWidget(scroll)
        self.update_language(t)

    # ── Построение строк ─────────────────────────────────────────────────── #

    def _build_row(self, row: int, param) -> None:
        label = _ElidingLabel()
        label.setStyleSheet(self._label_style)
        self._grid.addWidget(label, row, 0)

        editors_box = QHBoxLayout()
        editors_box.setSpacing(6)
        editor = _EDITORS[param.kind](param, self._style, self.edited.emit)
        editor.build(editors_box)
        self._grid.addLayout(editors_box, row, 1)

        self._rows[param.key] = {
            "param": param, "label": label, "editor": editor,
            "placeholder": False,
        }

    # ── Обновление из systems_json ───────────────────────────────────────── #

    def set_system(self, sys_json: Optional[dict]) -> None:
        """Перечитывает все крутилки. None — система не выбрана."""
        self._sys_json = sys_json
        for entry in self._rows.values():
            param, editor = entry["param"], entry["editor"]
            value = None if sys_json is None else \
                simple_params.read_param(sys_json, param)
            # Прячем строку, только когда создавать модуль нельзя (эмиттер):
            # предлагать «частиц в секунду» там, где эмиттера нет, значит
            # предлагать задвоить залп
            if sys_json is None or (value is None and not param.creatable):
                entry["label"].hide()
                editor.set_visible(False)
                continue
            entry["label"].show()
            editor.set_visible(True)
            entry["placeholder"] = value is None
            editor.set_placeholder(value is None)
            editor.set_value(param.placeholder_value if value is None else value)
        self._apply_tooltips()

    def _apply_tooltips(self) -> None:
        """Подсказка строки: смысл параметра, а у заготовки — ещё и то,
        какой модуль появится при первой правке."""
        t = self.t
        for entry in self._rows.values():
            param = entry["param"]
            tip = t.get(f"particles_sp_{param.key}_tip", "")
            if entry["placeholder"]:
                modules = ", ".join(sorted({
                    ref.function_name for ref in param.refs if ref.group}))
                if modules:
                    hint = t.get("particles_sp_placeholder",
                                 "Editing creates: {module}").format(
                        module=modules)
                    tip = f"{tip}\n\n{hint}" if tip else hint
            entry["label"].setToolTip(tip)
            for w in entry["editor"].widgets:
                w.setToolTip(tip)

    def update_language(self, t: dict) -> None:
        self.t = t
        for entry in self._rows.values():
            key = entry["param"].key
            entry["label"].setFullText(t.get(f"particles_sp_{key}", key))
        self._apply_tooltips()


class _SearchablePicker(QDialog):
    """Диалог выбора из длинного списка с живым поиском по подстроке.

    QInputDialog.getItem не фильтрует список при вводе — при 896 материалах
    найти «animated», не зная точного пути, невозможно. Здесь ввод фильтрует
    список сразу, совпадение — в любом месте строки."""

    def __init__(self, title: str, prompt: str, items: list, colors: dict,
                 current: str = "", cancel_text: str = "Cancel",
                 allow_custom: bool = False, parent=None,
                 notes: Optional[dict] = None, tips: Optional[dict] = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(560, 480)
        self._items = items
        #: {элемент: приписка} — короткая пометка справа (например «не в
        #: превью»). В выбор возвращается ЧИСТОЕ имя, а не строка с припиской.
        self._notes = notes or {}
        #: {элемент: подсказка} — что этот пункт делает.
        self._tips = tips or {}
        self._allow_custom = allow_custom   # принять вписанное имя вне списка
        self._chosen: Optional[str] = None
        c = colors

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)
        lbl = QLabel(prompt)
        lbl.setStyleSheet(f"color: {c['text']}; font-size: 12px;")
        lay.addWidget(lbl)

        self._search = QLineEdit()
        self._search.setPlaceholderText("…")
        self._search.setClearButtonEnabled(True)
        self._search.setStyleSheet(f"""
            QLineEdit {{ background: {c['surface']}; color: {c['text']};
                border: 1px solid {c['border']}; border-radius: 4px;
                padding: 5px 8px; font-size: 13px; }}
            QLineEdit:focus {{ border-color: {c['border_h']}; }}
        """)
        self._search.textChanged.connect(self._apply_filter)
        lay.addWidget(self._search)

        self._count = QLabel("")
        self._count.setStyleSheet(f"color: {c['text_sub']}; font-size: 11px;")
        lay.addWidget(self._count)

        self._list = QListWidget()
        self._list.setStyleSheet(f"""
            QListWidget {{ background: {c['surface']}; color: {c['text']};
                border: 1px solid {c['border']}; border-radius: 4px;
                font-size: 12px; outline: none; }}
            QListWidget::item {{ padding: 3px 6px; }}
            QListWidget::item:selected {{ background: {c['border_h']}; color: #fff; }}
        """)
        self._list.itemDoubleClicked.connect(lambda _it: self._accept())
        lay.addWidget(self._list, 1)

        from src.utils.themes import get_modern_styles
        styles = get_modern_styles()
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel = QPushButton(cancel_text)
        cancel.setStyleSheet(styles['button_secondary'])
        cancel.clicked.connect(self.reject)
        ok = QPushButton("OK")
        ok.setStyleSheet(styles['button_primary'])
        ok.clicked.connect(self._accept)
        btn_row.addWidget(cancel)
        btn_row.addWidget(ok)
        lay.addLayout(btn_row)

        # Enter в поиске — выбрать первый/выделенный; список стартует с текущего
        self._search.returnPressed.connect(self._accept)
        self._apply_filter("")
        if current:
            for i in range(self._list.count()):
                if self._list.item(i).data(Qt.ItemDataRole.UserRole) == current:
                    self._list.setCurrentRow(i)
                    self._list.scrollToItem(self._list.item(i))
                    break
        self._search.setFocus()

    def _apply_filter(self, text: str) -> None:
        needle = (text or "").strip().lower()
        self._list.clear()
        shown = [s for s in self._items if needle in s.lower()] if needle \
            else self._items
        for name in shown:
            note = self._notes.get(name)
            item = QListWidgetItem(f"{name}   ·   {note}" if note else name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            tip = self._tips.get(name)
            if tip:
                item.setToolTip(tip)
            if note:
                item.setForeground(QColor("#7a6a3a"))
            self._list.addItem(item)
        if self._list.count():
            self._list.setCurrentRow(0)
        self._count.setText(f"{len(shown)} / {len(self._items)}")

    def _accept(self) -> None:
        it = self._list.currentItem()
        if it is not None:
            self._chosen = it.data(Qt.ItemDataRole.UserRole) or it.text()
            self.accept()
        elif self._allow_custom:
            # Список пуст (ничего не совпало) — берём вписанный текст как есть
            typed = self._search.text().strip()
            if typed:
                self._chosen = typed
                self.accept()

    @staticmethod
    def pick(title: str, prompt: str, items: list, colors: dict,
             current: str = "", cancel_text: str = "Cancel",
             allow_custom: bool = False, parent=None,
             notes: Optional[dict] = None,
             tips: Optional[dict] = None) -> Optional[str]:
        dlg = _SearchablePicker(title, prompt, items, colors, current,
                                cancel_text, allow_custom, parent,
                                notes=notes, tips=tips)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            return dlg._chosen
        return None


# ── Контрол-пойнты: позиция, ориентация, движение ───────────────────── #

#: Пресеты движения CP: ключ для JS + ключ перевода. В игре эффект висит на
#: движущемся игроке, и только движение CP проявляет Movement Lock to Control
#: Point, drag и инерцию Верле — на неподвижной точке этого не видно.
_CP_MOTIONS = (
    ('none', 'particles_cp_motion_none'),
    ('bob', 'particles_cp_motion_bob'),
    ('sway', 'particles_cp_motion_sway'),
    ('orbit', 'particles_cp_motion_orbit'),
    ('spin', 'particles_cp_motion_spin'),
)


class _CpControlsWidget(QWidget):
    """Полоса под вьюпортом: позиция и углы контрол-пойнта плюс пресет движения.

    Ориентация CP — не украшение: по ней раскладываются локальные системы
    координат инициализаторов скорости и плоскость спрайтов orientation_type
    2/3. Значения хранятся на каждый CP отдельно.
    """

    def __init__(self, view, t: dict, colors: dict, tf2_root=None,
                 parent=None):
        super().__init__(parent)
        self._view = view
        # Путь к игре читаем колбэком: в настройках его могут сменить уже
        # после сборки виджета
        self._tf2_root = tf2_root if callable(tf2_root) else (lambda: tf2_root)
        self.t = t
        self._state: dict = {}
        self._used_points: list = []   # какие CP нужны выбранному эффекту
        # Пока строим ряды, setValue уже дёргает _push, а полей ещё нет
        self._loading = True

        c = colors
        #: Все контролы полосы одной высоты — иначе ряды «пляшут»
        H = 24
        spin_css = f"""
            QDoubleSpinBox, QSpinBox {{
                background: {c['surface']}; color: {c['text']};
                border: 1px solid {c['border']}; border-radius: 3px;
                padding: 1px 6px; font-size: 11px;
            }}
            QDoubleSpinBox:hover, QSpinBox:hover {{ border-color: {c['border_h']}; }}
            QDoubleSpinBox:focus, QSpinBox:focus {{ border-color: {c['accent']}; }}
        """
        self._lbl_css = f"color: {c['text_sub']}; font-size: 11px;"

        def sep(row):
            """Волосяная линия между смысловыми группами одного ряда."""
            line = QFrame()
            line.setFrameShape(QFrame.Shape.VLine)
            line.setFixedWidth(1)
            line.setFixedHeight(H - 6)
            line.setStyleSheet(f"background: {c['border']}; border: none;")
            row.addSpacing(4)
            row.addWidget(line)
            row.addSpacing(4)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 6, 10, 8)
        root.setSpacing(6)
        row1 = QHBoxLayout()
        row1.setSpacing(5)
        row2 = QHBoxLayout()
        row2.setSpacing(5)
        row3 = QHBoxLayout()
        row3.setSpacing(5)
        root.addLayout(row1)
        root.addLayout(row2)
        root.addLayout(row3)

        def add_label(row, key):
            lbl = QLabel(self.t.get(key, key))
            lbl.setStyleSheet(self._lbl_css)
            row.addWidget(lbl)
            return lbl

        def add_spin(row, rng, step, width, prefix=""):
            """Поле числа. prefix подписывает ось прямо внутри: три одинаковых
            поля подряд иначе не различить."""
            sp = _NumSpin()
            sp.setRange(-rng, rng)
            sp.setDecimals(1)
            sp.setSingleStep(step)
            sp.setFixedSize(width, H)
            sp.setStyleSheet(spin_css)
            sp.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            if prefix:
                sp.setPrefix(f"{prefix} ")
            sp.valueChanged.connect(self._push)
            row.addWidget(sp)
            return sp

        self.cp_label = add_label(row1, 'particles_cp_index')
        self.cp_index = QSpinBox()
        # Столько же точек, сколько у движка (MAX_PARTICLE_CONTROL_POINTS):
        # эффекты Valve адресуют CP вплоть до 15, но чужой мод вправе взять
        # любую, и не дать её выставить значит не дать увидеть эффект
        self.cp_index.setRange(0, MAX_CONTROL_POINTS - 1)
        self.cp_index.setFixedSize(52, H)
        self.cp_index.setStyleSheet(spin_css)
        # Как у остальных полей: стандартные стрелки Qt рисуются обрубком
        self.cp_index.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.cp_index.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cp_index.valueChanged.connect(self._on_cp_changed)
        row1.addWidget(self.cp_index)
        sep(row1)

        self.pos_label = add_label(row1, 'particles_cp_pos')
        self.pos_spins = [add_spin(row1, 4096.0, 1.0, 72, ax)
                          for ax in ("X", "Y", "Z")]
        sep(row1)
        self.ang_label = add_label(row1, 'particles_cp_angles')
        # P/Y/R — pitch, yaw, roll: порядок QAngle в Source
        self.ang_spins = [add_spin(row1, 360.0, 5.0, 68, ax)
                          for ax in ("P", "Y", "R")]
        row1.addStretch(1)

        self.motion_label = add_label(row2, 'particles_cp_motion')
        self.motion_combo = QComboBox()
        self.motion_combo.setFixedSize(190, H)
        self.motion_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.motion_combo.setStyleSheet(f"""
            QComboBox {{
                background: {c['surface']}; color: {c['text']};
                border: 1px solid {c['border']}; border-radius: 3px;
                padding: 1px 6px; font-size: 11px;
            }}
            QComboBox:hover {{ border-color: {c['border_h']}; }}
            QComboBox::drop-down {{ border: none; width: 16px; }}
            QComboBox QAbstractItemView {{
                background: {c['surface']}; color: {c['text']};
                border: 1px solid {c['border_h']};
                selection-background-color: {c['border_h']};
            }}
        """)
        for kind, key in _CP_MOTIONS:
            self.motion_combo.addItem(self.t.get(key, kind), kind)
        self.motion_combo.currentIndexChanged.connect(self._push)
        row2.addWidget(self.motion_combo)

        sep(row2)
        self.amp_label = add_label(row2, 'particles_cp_amp')
        self.amp_spin = add_spin(row2, 4096.0, 5.0, 66)
        self.amp_spin.setValue(24.0)
        self.period_label = add_label(row2, 'particles_cp_period')
        self.period_spin = add_spin(row2, 120.0, 0.5, 62)
        self.period_spin.setValue(2.0)
        sep(row2)

        self.reset_btn = QPushButton(self.t.get('particles_cp_reset', 'Reset'))
        self.reset_btn.setFixedHeight(H)
        self.reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_btn.setStyleSheet(
            "QPushButton { background:transparent; color:#888;"
            " border:1px solid #2a2a2a; padding:2px 12px; font-size:11px;"
            " border-radius:3px; }"
            " QPushButton:hover { background:rgba(255,255,255,0.05); color:#ccc; }")
        self.reset_btn.clicked.connect(self._on_reset)
        row2.addWidget(self.reset_btn)

        row2.addStretch(1)

        # Подсказка про углы: у своей группы и приглушённая — это сноска,
        # а не элемент управления, ярким цветом ей здесь делать нечего
        self.hint = QLabel(self.t.get('particles_cp_hint', ''))
        self.hint.setStyleSheet(f"color: {c['text_dim']}; font-size: 10px;")
        row1.addWidget(self.hint)

        # Ряд модели: CP садится на реальную точку крепления (в игре анюжуал
        # висит именно на attachment, а не в произвольной точке)
        self._colors = colors
        self._attachments: list = []
        self._model_loaded = False

        self.model_btn = QPushButton(
            self.t.get('particles_cp_model', 'Model...'))
        self.model_btn.setFixedHeight(H)
        self.model_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.model_btn.setStyleSheet(self.reset_btn.styleSheet())
        self.model_btn.clicked.connect(self._on_pick_model)
        row3.addWidget(self.model_btn)

        self.model_name = QLabel("")
        self.model_name.setStyleSheet(self._lbl_css)
        row3.addWidget(self.model_name)

        # Переключатель сцены: пустое пространство или модель под эффектом
        self._scene_chip_active = (
            "QPushButton { background:#2a2a2a; color:#ccc; border:1px solid #444;"
            " padding:3px 12px; font-size:11px; font-weight:600;"
            " border-radius:3px; }")
        self._scene_chip_idle = (
            "QPushButton { background:transparent; color:#555;"
            " border:1px solid #2a2a2a; padding:3px 12px; font-size:11px;"
            " border-radius:3px; }"
            " QPushButton:hover { background:rgba(255,255,255,0.04);"
            " color:#888; border-color:#383838; }")
        self.world_btn = QPushButton(self.t.get('particles_cp_scene_world', 'World'))
        self.model_view_btn = QPushButton(
            self.t.get('particles_cp_scene_model', 'On model'))
        sep(row3)
        chips = QHBoxLayout()
        chips.setSpacing(0)          # пара кнопок читается как один переключатель
        for btn, on_model in ((self.world_btn, False), (self.model_view_btn, True)):
            btn.setFixedHeight(H)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(
                lambda _=False, m=on_model: self._set_scene_mode(m))
            chips.addWidget(btn)
        row3.addLayout(chips)
        self._model_mode = False
        self.world_btn.setStyleSheet(self._scene_chip_active)
        self.model_view_btn.setStyleSheet(self._scene_chip_idle)

        sep(row3)
        self.att_label = add_label(row3, 'particles_cp_attachment')
        self.attach_combo = QComboBox()
        self.attach_combo.setFixedSize(220, H)
        self.attach_combo.setStyleSheet(
            self.motion_combo.styleSheet()
            + f" QComboBox:disabled {{ color: {c['text_dim']};"
              f" border-color: {c['border']}; }}")
        self.attach_combo.setEnabled(False)
        self.attach_combo.currentIndexChanged.connect(self._on_attachment)
        row3.addWidget(self.attach_combo)

        row3.addStretch(1)

        self._loading = False

    # ── Внутреннее ── #

    def _values(self) -> dict:
        return {
            'pos': [sp.value() for sp in self.pos_spins],
            'ang': [sp.value() for sp in self.ang_spins],
            'motion': self.motion_combo.currentData(),
            'amp': self.amp_spin.value(),
            'period': self.period_spin.value(),
        }

    def _on_cp_changed(self, index: int) -> None:
        st = self._state.get(index, {
            'pos': [0.0, 0.0, 0.0], 'ang': [0.0, 0.0, 0.0],
            'motion': 'none', 'amp': 24.0, 'period': 2.0})
        self._loading = True
        try:
            for sp, v in zip(self.pos_spins, st['pos']):
                sp.setValue(v)
            for sp, v in zip(self.ang_spins, st['ang']):
                sp.setValue(v)
            pos = self.motion_combo.findData(st['motion'])
            self.motion_combo.setCurrentIndex(max(0, pos))
            self.amp_spin.setValue(st['amp'])
            self.period_spin.setValue(st['period'])
        finally:
            self._loading = False

    def _push(self) -> None:
        """Отправляет значения выбранного CP в превью."""
        if self._loading or self._view is None:
            return
        i = self.cp_index.value()
        v = self._values()
        self._state[i] = v
        self._view.set_control_point(i, *v['pos'])
        # Нули в углах — это ориентация «смотрим по +X», а НЕ дефолтный базис
        # движка, поэтому пустые поля означают именно сброс ориентации
        if any(v['ang']):
            self._view.set_control_point_orientation(i, *v['ang'])
        else:
            self._view.clear_control_point_orientation(i)
        self._view.set_control_point_motion(i, v['motion'], v['amp'], v['period'])

    def _on_reset(self) -> None:
        i = self.cp_index.value()
        self._state.pop(i, None)
        self._on_cp_changed(i)
        self._push()

    def _set_scene_mode(self, on_model: bool) -> None:
        """«На модели» без выбранной модели сначала спрашивает модель."""
        if on_model and not self._model_loaded:
            self._on_pick_model()
            if not self._model_loaded:
                return
        self._model_mode = on_model
        self.world_btn.setStyleSheet(
            self._scene_chip_idle if on_model else self._scene_chip_active)
        self.model_view_btn.setStyleSheet(
            self._scene_chip_active if on_model else self._scene_chip_idle)
        if self._view is not None:
            self._view.set_model_visible(on_model)

    def _load_model_mesh(self, qc_path: str) -> bool:
        """Reference-SMD → OBJ в осях Source → меш с текстурами в превью."""
        import tempfile
        from src.services.model_attachments import reference_smd_for_qc
        from src.services.model_materials import resolve_model_textures
        from src.services.smd_to_obj_service import SmdToObjService

        smd = reference_smd_for_qc(qc_path)
        if not smd:
            return False
        tmp = tempfile.mkdtemp(prefix="tf2sg_cpmodel_")
        try:
            obj_path = os.path.join(tmp, "model.obj")
            ok, mat_names = SmdToObjService.convert(
                smd, obj_path, keep_source_axes=True)
            if not ok or not os.path.isfile(obj_path):
                return False
            with open(obj_path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception as exc:
            logger.warning(f"Меш модели для превью не построен: {exc}")
            return False
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        # Текстуры не критичны: без них модель просто серая
        try:
            textures = resolve_model_textures(
                qc_path, mat_names, self._tf2_root() or "")
        except Exception as exc:
            logger.warning(f"Текстуры модели не получены: {exc}")
            textures = {}
        if self._view is not None:
            self._view.load_model_obj(text, textures)
        return True

    def _on_pick_model(self) -> None:
        """Модель берётся из кэша декомпиляции — своей распаковки VPK тут нет."""
        from src.services.model_attachments import (
            attachments_from_qc, list_decompiled_models,
        )
        models = list_decompiled_models()
        if not models:
            QMessageBox.information(
                self, self.t.get('particles_cp_model', 'Model'),
                self.t.get('particles_cp_no_models', ''))
            return
        labels = [label for label, _ in models]
        chosen = _SearchablePicker.pick(
            self.t.get('particles_cp_model', 'Model'),
            self.t.get('particles_cp_pick_model', ''), labels, self._colors,
            cancel_text=self.t.get('cancel', 'Cancel'), parent=self)
        if not chosen:
            return
        qc_path = dict((label, qc) for label, qc in models)[chosen]
        self._attachments = attachments_from_qc(qc_path)
        self.model_name.setText(chosen)
        self._model_loaded = self._load_model_mesh(qc_path)
        if self._model_loaded and not self._model_mode:
            self._set_scene_mode(True)
        self._loading = True
        try:
            self.attach_combo.clear()
            # unusual_* вперёд: именно на них игра вешает эффекты
            order = sorted(
                range(len(self._attachments)),
                key=lambda i: (not self._attachments[i].name.lower()
                               .startswith('unusual'),
                               self._attachments[i].name.lower()))
            for i in order:
                a = self._attachments[i]
                self.attach_combo.addItem(f"{a.name}  ({a.bone})", i)
        finally:
            self._loading = False
        self.attach_combo.setEnabled(bool(self._attachments))
        if self._attachments:
            self._on_attachment(0)
        else:
            QMessageBox.information(
                self, self.t.get('particles_cp_model', 'Model'),
                self.t.get('particles_cp_no_attachments', ''))

    def _on_attachment(self, _index: int) -> None:
        """Кладёт позицию и углы точки в поля — дальше обычный путь _push."""
        if self._loading:
            return
        idx = self.attach_combo.currentData()
        if idx is None or idx >= len(self._attachments):
            return
        a = self._attachments[idx]
        self._loading = True
        try:
            for sp, v in zip(self.pos_spins, a.pos):
                sp.setValue(round(v, 1))
            for sp, v in zip(self.ang_spins, a.angles):
                sp.setValue(round(v, 1))
        finally:
            self._loading = False
        self._push()

    # ── Публичное ── #

    def set_used_points(self, points: list) -> None:
        """Показывает, какие контрольные точки нужны выбранному эффекту.

        В игре их выставляет код (положение оружия, цвет килстрика), в
        превью — пользователь. Без подсказки узнать, что эффекту важна CP 9,
        можно только вычитав это в дереве свойств."""
        self._used_points = list(points)
        if points:
            names = ", ".join(str(i) for i in points)
            self.cp_index.setToolTip(
                self.t.get('particles_cp_used', 'Used: {points}').format(
                    points=names))
        else:
            self.cp_index.setToolTip(self.t.get('particles_cp_index', 'CP'))

    def update_language(self, t: dict) -> None:
        self.t = t
        self.set_used_points(getattr(self, '_used_points', []))
        self.cp_label.setText(t.get('particles_cp_index', 'CP'))
        self.pos_label.setText(t.get('particles_cp_pos', 'Pos'))
        self.ang_label.setText(t.get('particles_cp_angles', 'Angles'))
        self.motion_label.setText(t.get('particles_cp_motion', 'Motion'))
        self.amp_label.setText(t.get('particles_cp_amp', 'Amp'))
        self.period_label.setText(t.get('particles_cp_period', 'Period'))
        self.reset_btn.setText(t.get('particles_cp_reset', 'Reset'))
        self.hint.setText(t.get('particles_cp_hint', ''))
        self.model_btn.setText(t.get('particles_cp_model', 'Model...'))
        self.world_btn.setText(t.get('particles_cp_scene_world', 'World'))
        self.model_view_btn.setText(t.get('particles_cp_scene_model', 'On model'))
        self.att_label.setText(t.get('particles_cp_attachment', 'Attachment'))
        self._loading = True
        try:
            for idx, (kind, key) in enumerate(_CP_MOTIONS):
                self.motion_combo.setItemText(idx, t.get(key, kind))
        finally:
            self._loading = False


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
        self._sys_items: dict = {}    # имя системы → узел дерева систем
        #: Что умеет движок превью: {группа: set(functionName)} + алиасы имён.
        #: Пусто, пока страница не отчиталась — до этого ничего не помечаем.
        self._supported: dict = {}
        self._fn_aliases: dict = {}
        self._worker: Optional[_PcfLoadWorker] = None
        self._catalog_worker: Optional[_CatalogWarmWorker] = None
        self._queued_source: Optional[str] = None
        self._current_system: str = ""
        self._paused = False

        # История для Ctrl+Z / Ctrl+Y: список снимков и позиция в нём
        self._history: list = []
        self._history_pos = -1
        self._restoring = False       # гасит запись истории во время отката

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
            _make_collapse_icon, _make_droplet_icon, _make_expand_icon,
            _make_folder_icon, _make_image_icon, _make_pause_icon,
            _make_play_icon, _make_restart_icon, _make_save_icon,
        )
        self._icon_pause = _make_pause_icon("#666666")
        self._icon_play = _make_play_icon("#666666")
        self._icon_expand = _make_expand_icon("#666666")
        self._icon_collapse = _make_collapse_icon("#666666")

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
            ('expand_btn', self._icon_expand,
             'particles_expand', self._toggle_expanded),
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

        # Чип контрол-пойнтов: полоса позиции/углов/движения CP под вьюпортом
        self.cp_btn = QPushButton("CP")
        self.cp_btn.setFixedHeight(26)
        self.cp_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cp_btn.setToolTip(self.t.get('particles_cp_toggle', 'Control point'))
        self.cp_btn.setStyleSheet(self._chip_inactive)
        self.cp_btn.clicked.connect(self._toggle_cp_controls)
        icons_row.addWidget(self.cp_btn)

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

        # Поиск: у больших эффектов (explosion.pcf — 66 систем) список
        # иначе не обозреть
        self.sys_search = QLineEdit()
        self.sys_search.setPlaceholderText(self.t['particles_search'])
        self.sys_search.setClearButtonEnabled(True)
        self.sys_search.setStyleSheet(f"""
            QLineEdit {{
                background: {c['surface']}; color: {c['text']};
                border: 1px solid {c['border']}; border-radius: 4px;
                padding: 3px 6px; font-size: 12px;
            }}
            QLineEdit:focus {{ border-color: {c['border_h']}; }}
        """)
        self.sys_search.textChanged.connect(self._filter_systems)
        sys_box_l.addWidget(self.sys_search)

        # Дерево, а не список: в стоковом PCF сотни определений, но почти
        # все они — дети (держатели, спавнеры). Вершин в разы меньше.
        self.systems_list = QTreeWidget()
        self.systems_list.setHeaderHidden(True)
        self.systems_list.setColumnCount(1)
        self.systems_list.setIndentation(14)
        self.systems_list.setStyleSheet(f"""
            QTreeWidget {{
                background: {c['surface']}; color: {c['text']};
                border: 1px solid {c['border']}; border-radius: 4px;
                font-size: 12px; outline: none;
            }}
            QTreeWidget::item {{ padding: 3px 4px; }}
            QTreeWidget::item:selected {{
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
        left_wrap = self._left_wrap = QWidget()
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
        self.view.support_reported.connect(self._on_support_reported)

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

        self.cp_controls = _CpControlsWidget(
            self.view, self.t, c,
            tf2_root=lambda: self.tf2_root)
        self.cp_controls.setVisible(False)
        right_l.addWidget(self.cp_controls)

        split.addWidget(right)

        # ── Экспорт-колонка (стиль вкладки оружия) ─────────────────────────── #
        export_col = self._export_col = QWidget()
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

        # F11 — развернуть/свернуть превью, Esc — только свернуть
        sc_expand = QShortcut(QKeySequence("F11"), self)
        sc_expand.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc_expand.activated.connect(self._toggle_expanded)
        sc_esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        sc_esc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        sc_esc.activated.connect(
            lambda: self._toggle_expanded() if getattr(self, "_expanded", False)
            else None)

        # Ctrl+Z / Ctrl+Y (и Ctrl+Shift+Z) — история правок эффекта
        for seq, delta in (
            (QKeySequence.StandardKey.Undo, -1),
            (QKeySequence.StandardKey.Redo, 1),
            (QKeySequence("Ctrl+Shift+Z"), 1),
        ):
            sc = QShortcut(seq, self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(lambda d=delta: self._on_history_shortcut(d))

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
        self._history_reset()
        self._warm_catalog()
        self.save_btn.setEnabled(True)
        self.build_btn.setEnabled(True)
        self.filename_input.setPlaceholderText(
            Path(self.service.pcf_vpk_path()).stem + "_particles")

        self._populate_systems()
        self.view.load_data(self._payload)
        first = self.service.system_names()
        if first:
            self._select_system(first[0])

    # ── Выбор системы / дерево свойств ───────────────────────────────────── #

    #: Настройка «группировать по родителям» — читаем каждый раз, чтобы
    #: переключение в настройках подхватывалось без перезапуска
    @staticmethod
    def _group_by_parent() -> bool:
        from src.config.app_config import AppConfig
        return bool(AppConfig.get('particles_group_tree', True))

    def _populate_systems(self, keep: str = "") -> None:
        """Перестраивает дерево систем и возвращает выделение на keep.

        Во время поиска и при выключенной группировке — плоский список: в
        дереве совпадение может лежать под свёрнутой веткой, и человек решит,
        что ничего не нашлось.
        """
        names = self.service.system_names() if self.service else []
        needle = self.sys_search.text().strip().lower()
        flat = bool(needle) or not self._group_by_parent()

        # Адреса узлов запоминаем при сборке: обходить дерево итератором
        # здесь нельзя, он держит сырые указатели (см. _refresh_tree_attr).
        # Общий ребёнок висит под несколькими родителями — храним первый.
        self._sys_items = {}

        def remember(item):
            name = item.data(0, _ROLE_SYSTEM)
            self._sys_items.setdefault(name, item)
            for i in range(item.childCount()):
                remember(item.child(i))

        self.systems_list.blockSignals(True)
        self.systems_list.clear()
        if flat:
            for name in names:
                if needle and needle not in name.lower() and name != keep:
                    continue
                item = _sys_item(name)
                self.systems_list.addTopLevelItem(item)
                remember(item)
        else:
            systems = (self._payload or {}).get("systems") or {}
            for node in system_hierarchy(systems, order=names):
                item = _sys_node(node)
                self.systems_list.addTopLevelItem(item)
                remember(item)
        self.systems_list.blockSignals(False)

        if keep:
            self._select_system(keep)

    def _select_system(self, name: str) -> None:
        item = self._sys_items.get(name)
        if item is None:
            return
        parent = item.parent()
        while parent is not None:          # раскрываем путь до находки
            parent.setExpanded(True)
            parent = parent.parent()
        self.systems_list.setCurrentItem(item)
        self.systems_list.scrollToItem(item)

    def _filter_systems(self, text: str) -> None:
        """Поиск перестраивает дерево: см. _populate_systems."""
        self._populate_systems(self._current_system)

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
        name = current.data(0, _ROLE_SYSTEM)
        if not name:
            return
        self._current_system = name
        self.texture_btn.setEnabled(True)
        self.colors_btn.setEnabled(True)
        self.view.set_root(name)
        self._fill_attr_tree(name)
        self._refresh_texture_cards()

    # ── 2D-карточки текстур ──────────────────────────────────────────────── #

    def _toggle_expanded(self) -> None:
        """Разворачивает превью на всю вкладку, пряча боковые колонки.

        Не полноэкранный режим окна: в редакторе постоянно скачешь между
        «покрутить параметр» и «посмотреть» — быстрый тумблер удобнее, а
        тулбар с паузой/рестартом остаётся под рукой."""
        self._expanded = not getattr(self, "_expanded", False)
        self._left_wrap.setVisible(not self._expanded)
        self._export_col.setVisible(not self._expanded)
        self.expand_btn.setIcon(
            self._icon_collapse if self._expanded else self._icon_expand)
        self.expand_btn.setToolTip(
            self.t['particles_collapse'] if self._expanded
            else self.t['particles_expand'])

    def _toggle_cp_controls(self) -> None:
        """Полоса CP: позиция, углы и пресет движения контрол-пойнта."""
        visible = not self.cp_controls.isVisible()
        self.cp_controls.setVisible(visible)
        self.cp_btn.setStyleSheet(
            self._chip_active if visible else self._chip_inactive)

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
        act_rename = menu.addAction(self.t['particles_menu_rename_material'])
        menu.addSeparator()
        act_reset = menu.addAction(self.t['particles_reset_texture'])
        act_reset.setEnabled(self.service.is_custom_material(mat))
        chosen = menu.exec(self.texture_cards.mapToGlobal(pos))
        if chosen is act_game:
            self._pick_game_material(mat)
        elif chosen is act_replace:
            self._on_card_double_clicked(item)
        elif chosen is act_rename:
            self._rename_material(mat)
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
        chosen = _SearchablePicker.pick(
            t['particles_pick_game_tex'], t['particles_pick_game_prompt'],
            mats, self._c, current=card_material,
            cancel_text=t.get('cancel', 'Cancel'), parent=self)
        chosen = (chosen or "").strip()
        if not chosen:
            return
        if not self.service.set_material_to_game(card_material, chosen):
            return
        self._history_commit()
        self._payload["systems"] = self.service.systems_json()
        self._payload["materials"] = self.service.materials_json(self.tf2_root)
        self.view.load_data(self._payload, root_name=self._current_system)
        self._fill_attr_tree(self._current_system)
        self._refresh_texture_cards()

    def _rename_material(self, material_name: str) -> None:
        """Свой путь материала вместо перезаписи стокового: замена текстуры
        перестаёт менять её у других эффектов игры."""
        if self.service is None or self._payload is None:
            return
        t = self.t
        new_name, ok = QInputDialog.getText(
            self, t['particles_menu_rename_material'],
            t['particles_new_material_prompt'], text=material_name)
        new_name = (new_name or "").strip()
        if not ok or not new_name or new_name == material_name:
            return
        if not self.service.rename_material(material_name, new_name):
            return
        self._history_commit()
        self._payload["systems"] = self.service.systems_json()
        if self.tf2_root:
            self._payload["materials"] = self.service.materials_json(
                self.tf2_root)
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
        self._history_commit()
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
        if info0 and info0.get("sheet") and not _is_animated(image_path):
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
        self._history_commit()
        self._payload["systems"] = self.service.systems_json()
        self._payload["materials"][new_mat] = info
        self.view.load_data(self._payload, root_name=self._current_system)
        self._fill_attr_tree(self._current_system)
        self._refresh_texture_cards()

    def _on_support_reported(self, payload: str) -> None:
        """Движок сообщил, что умеет исполнять."""
        try:
            data = json.loads(payload)
        except Exception:
            return
        self._supported = {
            g: {str(fn).strip().lower() for fn in (data.get(g) or [])}
            for g in MODULE_GROUPS
        }
        self._fn_aliases = {str(k).lower(): str(v).lower()
                            for k, v in (data.get("aliases") or {}).items()}
        if self._current_system:
            self._fill_attr_tree(self._current_system)

    def _module_unsupported(self, group: str, function_name: str) -> bool:
        """True — превью этот модуль не симулирует (в игре эффект будет иным)."""
        if not self._supported:
            return False        # страница ещё не отчиталась
        fn = (function_name or "").strip().lower()
        fn = self._fn_aliases.get(fn, fn)
        return fn not in self._supported.get(group, set())

    def _fill_attr_tree(self, system_name: str,
                        refresh_simple: bool = True) -> None:
        self.attr_tree.clear()
        # Карта (группа, индекс модуля, атрибут) → строка дерева: точечное
        # обновление без обхода (см. _refresh_tree_attr)
        self._attr_items = {}
        sys_json = self._payload["systems"].get(system_name)
        if sys_json is None:
            return

        def add_attr_items(parent_item, attrs: dict, group, mod_idx, fn=""):
            for attr_name, tv in sorted(attrs.items()):
                if attr_name in ("functionname", "name", "id"):
                    continue
                item = QTreeWidgetItem([attr_name, ""])
                item.setToolTip(0, self._attr_tooltip(attr_name, group, fn))
                item.setData(0, _ROLE_ATTR, (group, mod_idx, attr_name, tv["t"]))
                self._paint_attr_item(item, attr_name, tv)
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
                doc = particle_docs.module_help(group, mod["functionName"],
                                                self.language)
                if doc:
                    mod_item.setToolTip(0, doc)
                if self._module_unsupported(group, mod["functionName"]):
                    # Честно показываем: правки здесь на превью не влияют,
                    # но в игре работают
                    mod_item.setText(1, self.t['particles_not_previewed'])
                    mod_item.setForeground(0, QColor("#7a6a3a"))
                    mod_item.setForeground(1, QColor("#7a6a3a"))
                    tip = self.t['particles_not_previewed_tip']
                    mod_item.setToolTip(0, tip)
                    mod_item.setToolTip(1, tip)
                group_item.addChild(mod_item)
                add_attr_items(mod_item, mod["attrs"], group, idx,
                               mod["functionName"])
            group_item.setExpanded(True)

        ch_item = QTreeWidgetItem(["children", ""])
        ch_item.setData(0, _ROLE_GROUP, "children")
        self.attr_tree.addTopLevelItem(ch_item)
        for idx, ch in enumerate(sys_json["children"]):
            child_item = QTreeWidgetItem(
                [ch["childName"], f"delay {ch['delay']:g}"])
            child_item.setData(0, _ROLE_CHILD, idx)
            ch_item.addChild(child_item)

        # Полоса контрол-пойнтов подсказывает, какие CP важны этому эффекту
        self.cp_controls.set_used_points(referenced_control_points(
            sys_json, self._payload["systems"]))

        # Крутилки простого режима смотрят на тот же systems_json
        if refresh_simple:
            self._refresh_simple()

    # ── Структурное редактирование ───────────────────────────────────────── #

    def _structure_changed(self, keep_system: Optional[str] = None) -> None:
        """Обновляет payload/превью/дерево/список после структурной правки.

        Заодно единая точка истории для всех структурных операций
        (добавление/удаление модулей и систем, дочерние, слои)."""
        if self.service is None or self._payload is None:
            return
        self._history_commit()
        self._payload["systems"] = self.service.systems_json()
        current = keep_system or self._current_system
        names = self.service.system_names()
        self._populate_systems()
        if current in names:
            self._select_system(current)
            self._current_system = current
            self.view.update_systems(self._payload["systems"], current)
            self._fill_attr_tree(current)
            self._refresh_texture_cards()
        elif names:
            # Текущую систему удалили — движку нужен новый набор ДО set_root
            self.view.update_systems(self._payload["systems"], names[0])
            self._select_system(names[0])
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
        name = item.data(0, _ROLE_SYSTEM)
        t = self.t
        menu = QMenu(self)
        act_layer = menu.addAction(t['particles_menu_add_layer'])
        menu.addSeparator()
        act_rename = menu.addAction(t['particles_menu_rename'])
        act_dup = menu.addAction(t['particles_menu_duplicate'])
        act_child = menu.addAction(t['particles_menu_add_child'])
        act_del = menu.addAction(t['particles_menu_remove_system'])
        menu.addSeparator()
        act_ref = menu.addAction(t['particles_menu_param_reference'])
        chosen = menu.exec(self.systems_list.mapToGlobal(pos))
        if chosen is act_layer:
            self._on_add_layer(name)
        elif chosen is act_rename:
            new_name, ok = QInputDialog.getText(
                self, t['particles_menu_rename'],
                t['particles_new_name_prompt'], text=name)
            new_name = (new_name or "").strip()
            if not ok or not new_name or new_name == name:
                return
            if not self.service.rename_system(name, new_name):
                QMessageBox.warning(self, t['particles_menu_rename'],
                                    t['particles_name_taken'])
                return
            self._structure_changed(keep_system=new_name)
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
        elif chosen is act_ref:
            self._export_param_reference()
        elif chosen is act_del:
            answer = QMessageBox.question(
                self, t['particles_menu_remove_system'],
                t['particles_remove_system_confirm'].format(name=name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.Yes \
                    and self.service.remove_system(name):
                self._structure_changed()

    def _export_param_reference(self) -> None:
        """Сохраняет справочник параметров: с ним внешний инструмент может
        собрать набор, который вставляется сюда через Ctrl+V."""
        t = self.t
        # Для чего справочник: просто данные или сразу с заданием для ИИ
        box = QMessageBox(self)
        box.setWindowTitle(t['particles_menu_param_reference'])
        box.setText(t['particles_reference_purpose'])
        btn_ai = box.addButton(t['particles_reference_for_ai'],
                               QMessageBox.ButtonRole.AcceptRole)
        btn_plain = box.addButton(t['particles_reference_plain'],
                                  QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked not in (btn_ai, btn_plain):
            return
        with_prompt = clicked is btn_ai

        path, _ = QFileDialog.getSaveFileName(
            self, t['particles_menu_param_reference'],
            "tf2_particle_prompt.json" if with_prompt
            else "tf2_particle_params.json", "JSON (*.json)")
        if not path:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            # Список игровых текстур частиц: без него ассистент выдумывает
            # несуществующие пути, и эффект остаётся без текстуры
            materials = (ParticleEditorService.game_effect_materials(
                self.tf2_root) if self.tf2_root else None)
            data = ParticleEditorService.param_reference(
                self.tf2_root, supported=self._supported or None,
                with_prompt=with_prompt, materials=materials)
            Path(path).write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception as exc:
            logger.error(f"Справочник параметров: {exc}", exc_info=True)
            QMessageBox.critical(self, t.get('error', 'Error'), str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
        QMessageBox.information(
            self, t['particles_menu_param_reference'],
            (t['particles_reference_saved_ai'] if with_prompt
             else t['particles_reference_saved']).format(path=path))

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

        meta = item.data(0, _ROLE_ATTR)
        act_add_child = act_add_module = act_del_module = act_del_child = None
        act_add_attr = act_del_attr = None
        if group == "children":
            act_add_child = menu.addAction(t['particles_menu_add_child'])
        elif group in MODULE_GROUPS:
            act_add_module = menu.addAction(t['particles_menu_add_module'])
        elif module is not None:
            act_add_attr = menu.addAction(t['particles_menu_add_attr'])
            act_del_module = menu.addAction(t['particles_menu_remove_module'])
        elif child_idx is not None:
            act_del_child = menu.addAction(t['particles_menu_remove_child'])
        elif meta is not None:
            # Параметр: добавить соседний в тот же модуль либо убрать этот
            act_add_attr = menu.addAction(t['particles_menu_add_attr'])
            act_del_attr = menu.addAction(t['particles_menu_remove_attr'])
        elif item.parent() is None:
            act_add_attr = menu.addAction(t['particles_menu_add_attr'])

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
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                catalog = ParticleEditorService.group_module_catalog(
                    group, self.tf2_root)
            finally:
                QApplication.restoreOverrideCursor()
            if not catalog:
                return
            # Список длинный (все модули игры) — даём поиск с фильтром,
            # пояснение к каждому модулю и честную пометку у тех, что
            # превью не симулирует: в игре они работают, в окне — нет
            notes = {name: t['particles_not_previewed'] for name in catalog
                     if self._module_unsupported(group, name)}
            tips = {}
            for name in catalog:
                doc = particle_docs.module_help(group, name, self.language)
                if doc:
                    tips[name] = doc
            fn = _SearchablePicker.pick(
                t['particles_menu_add_module'], t['particles_pick_module'],
                catalog, self._c, cancel_text=t.get('cancel', 'Cancel'),
                allow_custom=True, parent=self, notes=notes, tips=tips)
            fn = (fn or "").strip()
            if fn:
                # Поиск шаблона может сканировать стоковые PCF (один раз)
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
        elif chosen is act_add_attr:
            # Адрес: модуль под курсором либо модуль выбранного параметра
            if module is not None:
                self._add_attr(sys_name, module[0], module[1])
            elif meta is not None:
                self._add_attr(sys_name, meta[0], meta[1])
            else:
                self._add_attr(sys_name, None, 0)
        elif chosen is act_del_attr:
            g, mi, attr_name, _type = meta
            if self.service.remove_attr(sys_name, g, mi, attr_name):
                self._attrs_changed(sys_name)

    def _warm_catalog(self) -> None:
        """Готовит каталог параметров заранее, чтобы меню не подвисало."""
        if not self.tf2_root or ParticleEditorService._attr_catalog:
            return
        if self._catalog_worker is not None and self._catalog_worker.isRunning():
            return
        self._catalog_worker = _CatalogWarmWorker(self.tf2_root, self)
        self._catalog_worker.finished.connect(
            lambda *_: self._catalog_worker.deleteLater())
        self._catalog_worker.start()

    def _attrs_changed(self, sys_name: str) -> None:
        """Обновляет всё после добавления/удаления параметра."""
        self._history_commit()
        self._payload["systems"] = self.service.systems_json()
        self.view.update_systems(self._payload["systems"], sys_name)
        self._fill_attr_tree(sys_name)

    def _add_attr(self, sys_name: str, group: Optional[str],
                  mod_idx: int) -> None:
        """
        Добавляет модулю (или самой системе) параметр, которого в нём нет.

        Список берётся из эффектов игры: набор полей нигде не задекларирован,
        поэтому каталог собирается сканом стоковых PCF (первый раз — секунды,
        дальше из кэша).
        """
        if self.service is None or self._payload is None:
            return
        t = self.t
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            missing = self.service.missing_attrs(
                sys_name, group, mod_idx, self.tf2_root)
        finally:
            QApplication.restoreOverrideCursor()
        if not missing:
            QMessageBox.information(self, t['particles_menu_add_attr'],
                                    t['particles_attr_all_set'])
            return
        names = sorted(missing)
        items = [f"{n}   ·   {_fmt_value(missing[n])}" for n in names]
        chosen, ok = QInputDialog.getItem(
            self, t['particles_menu_add_attr'], t['particles_pick_attr'],
            items, 0, False)
        if not ok or not chosen:
            return
        name = names[items.index(chosen)]
        tv = missing[name]
        if self.service.ensure_attr(sys_name, group, mod_idx, name,
                                    tv["t"], tv["v"]):
            self._attrs_changed(sys_name)

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

    def _clipboard_payload(self, reason: Optional[list] = None) -> Optional[dict]:
        """
        Скопированные параметры из буфера обмена (None — там не наше).

        Буфер — внешний ввод (в том числе сгенерированный нейросетью),
        поэтому разбираем по шагам и складываем причину отказа в reason:
        молчаливое «ничего не произошло» — худший вид ошибки.
        """
        text = (QApplication.clipboard().text() or "").strip()
        if not text:
            if reason is not None:
                reason.append(("particles_paste_empty", {}))
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            if reason is not None:
                reason.append(("particles_paste_not_json",
                               {"detail": f"{exc.msg} (строка {exc.lineno})"}))
            return None
        if not isinstance(data, dict) or "tf2sgParticleParams" not in data:
            if reason is not None:
                reason.append(("particles_paste_no_key", {}))
            return None
        payload = data.get("tf2sgParticleParams")
        if not isinstance(payload, dict):
            if reason is not None:
                reason.append(("particles_paste_bad_root", {}))
            return None
        if not isinstance(payload.get("attrs") or {}, dict):
            if reason is not None:
                reason.append(("particles_paste_bad_attrs", {"where": "attrs"}))
            return None
        if not isinstance(payload.get("modules") or {}, dict):
            if reason is not None:
                reason.append(("particles_paste_bad_modules", {}))
            return None
        if not (payload.get("attrs") or payload.get("modules")):
            if reason is not None:
                reason.append(("particles_paste_nothing", {}))
            return None
        return payload

    def _on_paste_params(self) -> None:
        """Вставляет параметры из буфера в выбранную систему: совпадающие
        перезаписываются молча, недостающие модули/атрибуты добавляются."""
        if self.service is None or self._payload is None \
                or not self._current_system:
            return
        reason: list = []
        payload = self._clipboard_payload(reason)
        if payload is None:
            self._show_paste_problems(reason, applied=False)
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
        report: list = []
        try:
            changed = self.service.paste_params(sys_name, payload, mode,
                                                report=report)
        except Exception as exc:
            logger.warning(f"Вставка параметров: {exc}", exc_info=True)
            self._show_paste_problems(
                [("particles_paste_failed", {"detail": str(exc)})],
                applied=False)
            return
        if not changed:
            self._show_paste_problems(
                report or [("particles_paste_nothing_applied", {})],
                applied=False)
            return
        self._history_commit()
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
        if report:
            # Часть вставилась, часть нет — сказать, что именно пропущено
            self._show_paste_problems(report, applied=True)

    def _show_paste_problems(self, problems: list, applied: bool) -> None:
        """
        Показывает, почему вставка не сработала (или что пропущено).

        Текст можно выделить мышью, а кнопка кладёт в буфер и описание
        проблем, и сам разбираемый JSON — такую пару удобно отдать обратно
        нейросети, которая его сгенерировала.
        """
        if not problems:
            return
        t = self.t
        lines = []
        for key, params in problems[:10]:
            msg = t.get(key, key)
            try:
                msg = msg.format(**params)
            except (KeyError, IndexError):
                pass
            lines.append(f"  - {msg}")
        if len(problems) > 10:
            lines.append(t['particles_lint_more'].format(
                count=len(problems) - 10))
        details = "\n".join(lines)

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning if not applied
                    else QMessageBox.Icon.Information)
        box.setWindowTitle(t['particles_menu_paste'])
        box.setText(t['particles_paste_partial'] if applied
                    else t['particles_paste_rejected'])
        box.setInformativeText(details)
        box.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        btn_copy = box.addButton(t['particles_copy_problem'],
                                 QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() is not btn_copy:
            return
        source = (QApplication.clipboard().text() or "").strip()
        report = f"{box.text()}\n{details}"
        if source:
            report += f"\n\n{t['particles_copy_problem_json']}\n{source}"
        QApplication.clipboard().setText(report)

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

    # ── История правок (Ctrl+Z / Ctrl+Y) ─────────────────────────────────── #

    #: Сколько шагов помним. PCF весит десятки килобайт — сотни мегабайт
    #: истории никому не нужны, а 30 шагов покрывают любую сессию правок.
    _HISTORY_LIMIT = 30

    def _on_history_shortcut(self, delta: int) -> None:
        """Ctrl+Z/Ctrl+Y. В полях ввода отдаём штатную отмену текста."""
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QAbstractSpinBox)):
            return
        self._history_go(delta)

    def _history_reset(self) -> None:
        """Начальное состояние после загрузки PCF."""
        self._history = []
        self._history_pos = -1
        if self.service is not None:
            snap = self.service.snapshot()
            if snap is not None:
                self._history = [snap]
                self._history_pos = 0

    def _history_commit(self) -> None:
        """Фиксирует состояние ПОСЛЕ правки. Вызывается из точек, которые
        меняют модель; во время отката игнорируется."""
        if self._restoring or self.service is None or self._history_pos < 0:
            return
        snap = self.service.snapshot()
        if snap is None:
            return
        # Ветка redo после новой правки теряет смысл
        del self._history[self._history_pos + 1:]
        self._history.append(snap)
        if len(self._history) > self._HISTORY_LIMIT:
            self._history.pop(0)
        self._history_pos = len(self._history) - 1

    def _history_go(self, delta: int) -> None:
        """Откат (-1) или возврат (+1) на шаг."""
        if self.service is None or self._payload is None:
            return
        self._flush_pending()      # незакоммиченные правки — часть текущего шага
        pos = self._history_pos + delta
        if pos < 0 or pos >= len(self._history):
            return
        prev_files = set(self.service.custom_files)
        self._restoring = True
        try:
            if not self.service.restore(self._history[pos]):
                return
            self._history_pos = pos
            self._payload["systems"] = self.service.systems_json()
            # Текстуры перерезолвим только если менялся набор оверрайдов —
            # это VTF→PNG на каждый материал, дорого
            if self.tf2_root and set(self.service.custom_files) != prev_files:
                self._payload["materials"] = self.service.materials_json(
                    self.tf2_root)
                reload_textures = True
            else:
                reload_textures = False
            self._reload_after_restore(reload_textures)
        finally:
            self._restoring = False

    def _reload_after_restore(self, reload_textures: bool) -> None:
        """Пересобирает UI под восстановленное состояние."""
        names = self.service.system_names()
        keep = self._current_system if self._current_system in names else (
            names[0] if names else "")
        self._populate_systems(keep)
        self._current_system = keep
        if not keep:
            self.attr_tree.clear()
            self._attr_items = {}
            self.texture_cards.clear()
            self.simple_widget.set_system(None)
            self.view.reset()
            return
        if reload_textures:
            self.view.load_data(self._payload, root_name=keep)
        else:
            self.view.update_systems(self._payload["systems"], keep)
        self._fill_attr_tree(keep)
        self._refresh_texture_cards()

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
        # Строка-заготовка: модуля под параметром ещё нет, и правка его
        # создаёт. Отдельной кнопки «Включить» нет — правка И ЕСТЬ включение
        if simple_params.read_param(sys_json, param) is None:
            sys_json = self._create_param_modules(sys_name, param)
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
        self._history_commit()
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

    def _create_param_modules(self, sys_name: str, param) -> Optional[dict]:
        """Создаёт модули, которых не хватает крутилке, и отдаёт свежий
        снимок системы. None — создать не удалось.

        Вызывается из правки строки-заготовки, поэтому дерево свойств здесь
        НЕ пересобирается: это сделает отложенный сброс правки, иначе
        пересборка дёргала бы виджет прямо под курсором пользователя.
        """
        sys_json = self._payload["systems"].get(sys_name)
        if sys_json is None:
            return None
        missing = simple_params.missing_modules(sys_json, param)
        if not missing:
            return sys_json
        # Поиск шаблона модуля может однократно просканировать стоковые PCF
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for group, fn in missing:
                if not self.service.add_module(sys_name, group, fn,
                                               self.tf2_root):
                    return None
        finally:
            QApplication.restoreOverrideCursor()
        self._payload["systems"] = self.service.systems_json()
        # Появились строки новых модулей — дереву нужна полная пересборка
        self._simple_pending_rebuild = True
        return self._payload["systems"].get(sys_name)

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
            idx = simple_params.module_index(sys_json, group, fn)
            if idx is None:
                if not final:
                    continue      # модуль создаём один раз, по отпусканию
                if not self.service.add_module(sys_name, group, fn,
                                               self.tf2_root):
                    continue
                created = True
                self._payload["systems"] = self.service.systems_json()
                sys_json = self._payload["systems"][sys_name]
                idx = simple_params.module_index(sys_json, group, fn)
                if idx is None:
                    continue
            self.service.ensure_attr(sys_name, group, idx, attr, atype, value)
            self._gizmo_pending.add((group, idx, attr))
        if final:
            self._gizmo_timer.stop()
            self._flush_gizmo_edit()
            self._history_commit()
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
        try:
            self._paint_attr_item(item, attr_name, tv)
        except RuntimeError:
            # Строку удалили пересборкой дерева — карта устарела
            self._attr_items.pop((group, mod_idx, attr_name), None)

    # ── Показ значения атрибута ──────────────────────────────────────────── #

    def _attr_tooltip(self, attr_name: str, group=None,
                      function_name: str = "") -> str:
        """Подсказка к имени параметра: пояснение из справочника плюс
        разброс значений этого параметра по эффектам игры.

        Диапазон отвечает на вопрос, на который не отвечает ни имя, ни
        пояснение: 0.1 здесь — норма или экзотика. Берётся из уже собранного
        каталога, сканирование не запускает (иначе тултип вешал бы UI)."""
        parts = [attr_name]
        doc = particle_docs.attr_help(attr_name, self.language)
        if doc:
            parts.append(doc)
        stats = ParticleEditorService.attr_stats(group, function_name,
                                                 attr_name)
        if stats:
            parts.append(self.t['particles_attr_stock_range'].format(
                lo=f"{stats['lo']:g}", hi=f"{stats['hi']:g}", n=stats['n']))
        return _NL2.join(parts)

    def _paint_attr_item(self, item: QTreeWidgetItem, attr_name: str,
                         tv: dict) -> None:
        """Текст, тултип и цвет колонки значения — одним местом для
        первичной сборки дерева и для точечного обновления строки."""
        value_text = _fmt_value(tv)
        # Перечисление: голое число ни о чём не говорит («output field 7»)
        label = particle_docs.enum_label(attr_name, tv["v"], self.language)
        if label:
            value_text = f"{value_text} — {label}"
        warn = particle_lint.attr_warning(attr_name, tv["v"])
        item.setText(1, f"{value_text}  ?" if warn else value_text)
        item.setToolTip(1, self.t.get(warn, warn) if warn else value_text)
        if warn:
            item.setForeground(1, QColor("#c9a227"))
        elif tv["t"] == "color":
            v = tv["v"]
            item.setForeground(1, QColor(v[0], v[1], v[2]))
        else:
            item.setForeground(1, QColor(self._c['text']))

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

        self._history_commit()
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
        enum = particle_docs.enum_values(attr_name)
        if enum and attr_type in ("integer", "string"):
            return self._ask_enum(attr_name, enum, cur, attr_type)
        if attr_type == "integer":
            val, ok = QInputDialog.getInt(
                self, attr_name, t['particles_val_prompt'], int(cur),
                -2147483648, 2147483647)
            return val if ok else None
        if attr_type in ("float", "time"):
            # Число знаков — по самому значению: с фиксированными четырьмя
            # диалог обрезал мелочь ещё при ОТКРЫТИИ (animation rate 1e-5,
            # drag -0.0004), и «ОК» записывал огрызок. Границы шире стоковых
            # крайностей (lifetime до 1e10 — «вечная» частица).
            val, ok = QInputDialog.getDouble(
                self, attr_name, t['particles_val_prompt'], float(cur),
                -1e12, 1e12, _float_decimals(cur))
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

    def _ask_enum(self, attr_name: str, enum: dict, cur, attr_type: str):
        """Выбор значения из списка вместо ввода голого числа.

        Список редактируемый: набор значений в справочнике покрывает то, что
        встречается в игре, но чужой мод вправе записать своё — ручной ввод
        должен остаться возможен.
        """
        labels, values = [], []
        for value, pair in enum.items():
            labels.append(f"{value} — {particle_docs.enum_label(attr_name, value, self.language)}")
            values.append(value)
        current = 0
        if cur in values:
            current = values.index(cur)
        else:                                  # значения нет в справочнике
            labels.insert(0, str(cur))
            values.insert(0, cur)
        chosen, ok = QInputDialog.getItem(
            self, attr_name, self.t['particles_val_prompt'], labels, current,
            True)
        if not ok or not chosen:
            return None
        if chosen in labels:
            return values[labels.index(chosen)]
        # Вписали своё: для числового атрибута — только если это число
        if attr_type == "integer":
            try:
                return int(str(chosen).split()[0])
            except ValueError:
                return None
        return chosen

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
        if cur_info and cur_info.get("sheet") and not _is_animated(path):
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
        self._history_commit()
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
        self._history_commit()
        self._payload["systems"] = self.service.systems_json()
        self.view.update_systems(self._payload["systems"], sys_name)
        self._fill_attr_tree(sys_name)
        QMessageBox.information(
            self, t['particles_natural_colors'],
            t['particles_colors_done'].format(count=removed))

    def _lint_findings(self) -> list:
        """Проверки эффекта + конфликты установленных модов."""
        if self.service is None or self._payload is None:
            return []
        baseline = None
        if self._history:
            # Сравниваем с состоянием на момент загрузки: особенности
            # стоковых эффектов — не забота пользователя
            snap = self._history[0]
            probe = ParticleEditorService()
            if probe.restore(snap):
                baseline = probe.systems_json()
        found = particle_lint.check_systems(
            self._payload["systems"],
            materials=self._payload.get("materials"),
            baseline=baseline)
        # Что движок превью не исполняет: список берём у него самого
        found += particle_lint.check_preview_support(
            self._payload["systems"], self._supported, self._fn_aliases)
        found += particle_lint.check_game_conflicts(
            self.tf2_root, self.service.pcf_vpk_path())
        return found

    def _lint_text(self, findings: list) -> str:
        """Человеческий список находок для диалога."""
        t = self.t
        lines = []
        for f in findings[:12]:
            msg = t.get(f.message_key, f.message_key)
            try:
                msg = msg.format(**f.params)
            except (KeyError, IndexError):
                pass
            prefix = f"[{f.system}] " if f.system else ""
            lines.append(f"  - {prefix}{msg}")
        if len(findings) > 12:
            lines.append(t['particles_lint_more'].format(
                count=len(findings) - 12))
        return "\n".join(lines)

    def _confirm_lint(self) -> Optional[bool]:
        """
        Показывает найденные проблемы перед сборкой.

        Returns:
            True — исправить и собрать, False — собрать как есть,
            None — отменить сборку.
        """
        findings = self._lint_findings()
        if not findings:
            return False
        t = self.t
        fixable = [f for f in findings if f.fixable]
        box = QMessageBox(self)
        box.setWindowTitle(t['particles_lint_title'])
        box.setText(t['particles_lint_intro'].format(count=len(findings)))
        box.setInformativeText(self._lint_text(findings))
        btn_fix = None
        if fixable:
            btn_fix = box.addButton(
                t['particles_lint_fix'].format(count=len(fixable)),
                QMessageBox.ButtonRole.AcceptRole)
        btn_as_is = box.addButton(t['particles_lint_as_is'],
                                  QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is btn_fix:
            return True
        if clicked is btn_as_is:
            return False
        return None

    def _on_export_vpk(self) -> None:
        """Сборка VPK-мода в папку экспорта из настроек (как оружие)."""
        if self.service is None:
            return
        t = self.t
        self._flush_pending()
        decision = self._confirm_lint()
        if decision is None:
            return
        if decision:
            fixed = particle_lint.apply_fixes(
                self.service, [f for f in self._lint_findings() if f.fixable])
            if fixed:
                self._history_commit()
                self._payload["systems"] = self.service.systems_json()
                if self._current_system:
                    self.view.update_systems(
                        self._payload["systems"], self._current_system)
                    self._fill_attr_tree(self._current_system)
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
        self.expand_btn.setToolTip(
            t['particles_collapse'] if getattr(self, "_expanded", False)
            else t['particles_expand'])
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
        self.sys_search.setPlaceholderText(t['particles_search'])
        self.level_simple_btn.setText(t['particles_level_simple'])
        self.level_expert_btn.setText(t['particles_level_expert'])
        self.simple_widget.update_language(t)
        self.cp_controls.update_language(t)
        self.cp_btn.setToolTip(t.get('particles_cp_toggle', 'Control point'))
        self.view.set_language(language)

    # ── Завершение ───────────────────────────────────────────────────────── #

    def shutdown(self) -> None:
        """Останавливает фоновые воркеры — вызывается при закрытии приложения."""
        if self._worker is not None:
            self._worker.stop()
        if self._catalog_worker is not None:
            self._catalog_worker.stop()


#: Разделитель «имя параметра / пояснение» в подсказке дерева свойств.
_NL2 = "\n\n"


def _float_decimals(value: float, minimum: int = 4, maximum: int = 12) -> int:
    """Сколько знаков после запятой нужно, чтобы не потерять значение.

    В стоковых PCF есть drag -0.0004 и animation rate 1e-5: диалог с
    фиксированными четырьмя знаками показывал их нулями и записывал нули.
    """
    try:
        v = abs(float(value))
    except (TypeError, ValueError):
        return minimum
    if v == 0 or v >= 1:
        return minimum
    import math
    return max(minimum, min(maximum, int(math.ceil(-math.log10(v))) + 4))


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
