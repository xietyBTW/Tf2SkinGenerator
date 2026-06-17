"""
Диалог «Карты материала» (Фаза 2).

Пользователь по галочке включает карту (detail / самосвечение / phong-exp),
грузит картинку ИЛИ выбирает авто-вывод из базовой текстуры. Приложение при
сборке само сгенерит VTF с правильным форматом и впишет путь+параметры в VMT.
"""

import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QCheckBox,
    QPushButton, QLineEdit, QComboBox, QWidget, QFileDialog, QFrame,
    QGraphicsDropShadowEffect,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QDoubleValidator, QColor

from src.data.material_maps import MATERIAL_MAPS, MAP_DISPLAY_ORDER

_IMG_FILTER = "Images (*.png *.jpg *.jpeg *.bmp *.tga *.tiff *.webp);;All Files (*)"

_ACCENT = "#ff6b35"

_DIALOG_QSS = f"""
    QDialog {{ background: transparent; }}
    QFrame#root {{ background: #1b1b1b; border: 1px solid #383838; border-radius: 10px; }}
    QLabel {{ color: #cfcfcf; background: transparent; }}
    QLineEdit {{
        background: #141414; color: #e6e6e6; border: 1px solid #3a3a3a;
        border-radius: 5px; padding: 5px 8px; selection-background-color: {_ACCENT};
    }}
    QLineEdit:focus {{ border-color: {_ACCENT}; }}
    QLineEdit:disabled {{ color: #666; background: #181818; border-color: #2a2a2a; }}
    QComboBox {{
        background: #141414; color: #e6e6e6; border: 1px solid #3a3a3a;
        border-radius: 5px; padding: 4px 8px; min-height: 18px;
    }}
    QComboBox:disabled {{ color: #666; border-color: #2a2a2a; }}
    QComboBox QAbstractItemView {{
        background: #1c1c1c; color: #e6e6e6; border: 1px solid #3a3a3a;
        selection-background-color: {_ACCENT}; outline: 0;
    }}
    QCheckBox {{ color: #e9e9e9; spacing: 8px; }}
    QCheckBox:disabled {{ color: #5a5a5a; }}
    QCheckBox::indicator {{
        width: 16px; height: 16px; border: 1px solid #4a4a4a;
        border-radius: 4px; background: #161616;
    }}
    QCheckBox::indicator:hover {{ border-color: {_ACCENT}; }}
    QCheckBox::indicator:checked {{ background: {_ACCENT}; border-color: {_ACCENT}; }}
    QPushButton {{
        background: #2a2a2a; color: #ddd; border: 1px solid #3a3a3a;
        border-radius: 5px; padding: 6px 12px;
    }}
    QPushButton:hover {{ background: #323232; border-color: {_ACCENT}; }}
    QPushButton:disabled {{ color: #5a5a5a; background: #1d1d1d; border-color: #2a2a2a; }}
"""

# Рамка карточки: акцентная левая граница, когда карта включена.
_CARD_ON = (
    "QFrame#card { background: #212121; border: 1px solid #343434;"
    f" border-left: 3px solid {_ACCENT}; border-radius: 8px; }}"
)
_CARD_OFF = (
    "QFrame#card { background: #1f1f1f; border: 1px solid #2b2b2b;"
    " border-left: 3px solid #2b2b2b; border-radius: 8px; }"
)


class _TitleBar(QWidget):
    """Перетаскиваемая шапка безрамочного окна: заголовок + кнопка закрытия."""

    def __init__(self, win, title: str, close_tip: str = 'Close'):
        super().__init__(win)
        self._win = win
        self._press = None
        self.setFixedHeight(40)

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 0, 10, 0)
        row.setSpacing(8)

        lbl = QLabel(title)
        lbl.setStyleSheet("color:#fff; font-size:14px; font-weight:600; background:transparent;")
        row.addWidget(lbl)
        row.addStretch()

        close = QPushButton('✕')
        close.setFixedSize(28, 28)
        close.setCursor(Qt.PointingHandCursor)
        close.setToolTip(close_tip)
        close.setStyleSheet(
            "QPushButton { background:transparent; color:#aaa; border:none;"
            " border-radius:5px; font-size:14px; }"
            " QPushButton:hover { background:#c0392b; color:#fff; }"
        )
        close.clicked.connect(win.reject)
        row.addWidget(close)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = e.globalPosition().toPoint() - self._win.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._press is not None and (e.buttons() & Qt.LeftButton):
            self._win.move(e.globalPosition().toPoint() - self._press)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._press = None


class MaterialMapsDialog(QDialog):
    """Диалог настройки файловых карт материала. get_maps() → словарь для сборки."""

    def __init__(self, t, current: dict = None, parent=None):
        super().__init__(parent)
        self.t = t or {}
        self._rows = {}
        current = current or {}

        self.setWindowTitle(self.t.get('material_maps_title', 'Material Maps'))
        self.setMinimumWidth(780)   # два столбца карточек
        self.setStyleSheet(_DIALOG_QSS)
        # Безрамочное окно со скруглением + тенью
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)  # место под тень
        outer.setSpacing(0)

        container = QFrame()
        container.setObjectName("root")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setColor(QColor(0, 0, 0, 180))
        shadow.setOffset(0, 4)
        container.setGraphicsEffect(shadow)
        outer.addWidget(container)

        root = QVBoxLayout(container)
        root.setContentsMargins(0, 0, 0, 16)
        root.setSpacing(14)

        # Кастомная шапка (перетаскивание + закрытие)
        root.addWidget(_TitleBar(
            self, self.t.get('material_maps_title', 'Material Maps'),
            self.t.get('close', 'Close')))

        # Отступы для контента под шапкой
        content = QVBoxLayout()
        content.setContentsMargins(20, 4, 20, 0)
        content.setSpacing(14)
        root.addLayout(content)

        intro = QLabel(self.t.get(
            'material_maps_intro',
            'Enable a map, pick an image — the app generates the VTF with the right '
            'format and wires the path into the VMT automatically.'))
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#8c8c8c; font-size:11px;")
        content.addWidget(intro)

        # Карточки в сетку 2 столбца — чтобы окно не было слишком длинным.
        # AlignTop: карта не растягивается по высоте под более «высокого» соседа
        # по ряду — иначе у коротких карт (detail/phongwarp) появлялась пустота.
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        order = MAP_DISPLAY_ORDER
        for i, map_id in enumerate(order):
            card = self._build_card(map_id, current.get(map_id))
            # Нечётная последняя карта растягивается на оба столбца (без «дыры»).
            if i == len(order) - 1 and len(order) % 2 == 1:
                grid.addWidget(card, i // 2, 0, 1, 2, Qt.AlignTop)
            else:
                grid.addWidget(card, i // 2, i % 2, Qt.AlignTop)
        content.addLayout(grid)

        content.addSpacing(2)

        # Кнопки
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()
        cancel = QPushButton(self.t.get('cancel', 'Cancel'))
        cancel.setMinimumWidth(90)
        cancel.clicked.connect(self.reject)
        ok = QPushButton(self.t.get('save', 'Save'))
        ok.setMinimumWidth(110)
        ok.setStyleSheet(
            f"QPushButton {{ background:{_ACCENT}; color:#fff; border:none;"
            " border-radius:5px; padding:7px 18px; font-weight:600; }"
            " QPushButton:hover { background:#ff7d4d; }"
        )
        ok.clicked.connect(self.accept)
        btn_row.addWidget(cancel)
        btn_row.addWidget(ok)
        content.addLayout(btn_row)

    # ── маленькие хелперы оформления ───────────────────────────────────────── #
    @staticmethod
    def _field_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color:#9a9a9a; font-size:11px;")
        return lbl

    # ── карточка одной карты ───────────────────────────────────────────────── #
    def _build_card(self, map_id: str, saved: dict) -> QWidget:
        saved = saved or {}
        cfg = MATERIAL_MAPS[map_id]
        vmt_only = bool(cfg.get('vmt_only'))  # параметрическая карта без текстуры (rim)

        card = QFrame()
        card.setObjectName("card")
        outer = QVBoxLayout(card)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(8)

        # Заголовок: галочка-имя + бейдж формата справа
        head = QHBoxLayout()
        head.setSpacing(8)
        cb = QCheckBox(self.t.get(f'map_{map_id}', map_id.capitalize()))
        cb.setStyleSheet("QCheckBox { color:#fff; font-size:13px; font-weight:600; }")
        cb.setChecked(bool(saved.get('image')) or bool(saved.get('derive'))
                      or (vmt_only and bool(saved.get('enabled'))))
        head.addWidget(cb, 0, Qt.AlignVCenter)
        head.addStretch()
        badge = QLabel(cfg['format'])
        badge.setSizePolicy(badge.sizePolicy().Policy.Fixed, badge.sizePolicy().Policy.Fixed)
        badge.setStyleSheet(
            "color:#9a9a9a; font-size:10px; font-weight:600; background:#161616;"
            " border:1px solid #333; border-radius:4px; padding:2px 7px;")
        # AlignVCenter — иначе бейдж уезжает к верхнему краю и торчит над карточкой
        head.addWidget(badge, 0, Qt.AlignRight | Qt.AlignVCenter)
        outer.addLayout(head)

        # Тело карты (всё, что гаснет при выключенной галочке).
        # Фон прозрачный — иначе Qt красит вложенный контейнер дефолтным чёрным.
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        outer.addWidget(body)

        # Короткое описание
        desc = QLabel(self.t.get(f'map_{map_id}_tip', ''))
        desc.setWordWrap(True)
        desc.setStyleSheet("color:#888; font-size:11px;")
        if desc.text():
            lay.addWidget(desc)

        # Авто-режим (только для поддерживающих карт)
        auto_cb = None
        threshold_edit = None
        if cfg.get('derive_kind'):
            auto_cb = QCheckBox(self.t.get('map_auto', 'Auto from texture (no file)'))
            auto_cb.setToolTip(self.t.get('map_auto_tip', ''))
            auto_cb.setStyleSheet("QCheckBox { color:#ffae8a; font-size:12px; font-weight:500; }")
            auto_cb.setChecked(bool(saved.get('derive')))
            lay.addWidget(auto_cb)

        # Строка файла (у параметрических карт вроде rim light её нет)
        file_row = None
        path_edit = None
        if not vmt_only:
            file_row = QHBoxLayout()
            file_row.setSpacing(6)
            path_edit = QLineEdit(saved.get('image', ''))
            path_edit.setReadOnly(True)
            path_edit.setMinimumHeight(30)
            path_edit.setPlaceholderText(self.t.get('map_no_file', 'No file selected'))
            browse = QPushButton(self.t.get('map_browse', 'Browse'))
            browse.setMinimumHeight(30)
            clear = QPushButton('×')
            clear.setFixedSize(30, 30)
            clear.setToolTip(self.t.get('map_clear', 'Clear'))
            browse.clicked.connect(lambda _, e=path_edit: self._browse(e))
            clear.clicked.connect(lambda _, e=path_edit: e.clear())
            file_row.addWidget(path_edit, 1)
            file_row.addWidget(browse)
            file_row.addWidget(clear)
            lay.addLayout(file_row)

        # Ряд параметров: порог (derive) + числовые ($detailscale и т.п.) в одну линию
        numeric = {}
        params_row = QHBoxLayout()
        params_row.setSpacing(12)

        if cfg.get('derive_kind'):
            cell = QHBoxLayout()
            cell.setSpacing(6)
            cell.addWidget(self._field_label(self.t.get('map_threshold', 'Threshold')))
            threshold_edit = QLineEdit(str(saved.get('threshold', '')))
            threshold_edit.setPlaceholderText('0–255')
            threshold_edit.setValidator(QDoubleValidator(0, 255, 0, threshold_edit))
            threshold_edit.setFixedWidth(64)
            threshold_edit.setMinimumHeight(28)
            cell.addWidget(threshold_edit)
            params_row.addLayout(cell)

        for param in cfg.get('numeric', ()):
            label_key = 'map_' + param.lstrip('$').lower()
            cell = QHBoxLayout()
            cell.setSpacing(6)
            cell.addWidget(self._field_label(self.t.get(label_key, param.lstrip('$'))))
            if param == '$detailblendmode':
                w = QComboBox()
                w.addItem(self.t.get('map_blend_additive', 'Additive'), '1')
                w.addItem(self.t.get('map_blend_multiply', 'Multiply'), '7')
                w.addItem(self.t.get('map_blend_overlay', 'Overlay'), '5')
                w.setMinimumWidth(110)
                saved_val = str(saved.get(param, cfg['extra_vmt'].get(param, '1')))
                w.setCurrentIndex(max(0, w.findData(saved_val)))
            else:
                w = QLineEdit(str(saved.get(param, cfg['extra_vmt'].get(param, ''))))
                w.setValidator(QDoubleValidator(0.0, 999.0, 3, w))
                w.setFixedWidth(64)
                w.setMinimumHeight(28)
            numeric[param] = w
            cell.addWidget(w)
            params_row.addLayout(cell)

        params_row.addStretch()
        if cfg.get('derive_kind') or cfg.get('numeric'):
            lay.addLayout(params_row)

        # Доступность тела + режим auto/file
        def _sync():
            on = cb.isChecked()
            # Выключили карту → выключаем и «Авто из текстуры»
            if not on and auto_cb and auto_cb.isChecked():
                auto_cb.blockSignals(True)
                auto_cb.setChecked(False)
                auto_cb.blockSignals(False)
            auto = bool(auto_cb and auto_cb.isChecked())
            body.setEnabled(on)
            card.setStyleSheet(_CARD_ON if on else _CARD_OFF)
            if file_row is not None:
                for i in range(file_row.count()):
                    wdg = file_row.itemAt(i).widget()
                    if wdg:
                        wdg.setEnabled(on and not auto)
            if threshold_edit is not None:
                threshold_edit.setEnabled(on and auto)

        cb.toggled.connect(lambda _=None: _sync())
        if auto_cb:
            auto_cb.toggled.connect(lambda _=None: _sync())
        _sync()

        self._rows[map_id] = {
            'cb': cb, 'auto': auto_cb, 'path': path_edit,
            'threshold': threshold_edit, 'numeric': numeric,
        }
        return card

    def _browse(self, edit: QLineEdit) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self.t.get('map_select', 'Select map image'), '', _IMG_FILTER)
        if path:
            edit.setText(path)

    # ── результат ──────────────────────────────────────────────────────────── #
    def get_maps(self) -> dict:
        """
        {map_id: {...}} — только включённые карты.
        Запись: {"derive": True[, "threshold": N]} для авто-режима, либо
        {"image": path} для файла. Плюс числовые $param-переопределения.
        """
        result = {}
        for map_id, row in self._rows.items():
            if not row['cb'].isChecked():
                continue

            if MATERIAL_MAPS[map_id].get('vmt_only'):
                # Параметрическая карта (rim light) — текстуры нет, только флаг + числа.
                entry = {'enabled': True}
            else:
                auto = bool(row['auto'] and row['auto'].isChecked())
                if auto:
                    entry = {'derive': True}
                    thr = row['threshold'].text().strip() if row['threshold'] else ''
                    if thr:
                        entry['threshold'] = thr
                else:
                    img = row['path'].text().strip() if row['path'] else ''
                    if not img or not os.path.isfile(img):
                        continue
                    entry = {'image': img}

            for param, w in row['numeric'].items():
                val = w.currentData() if isinstance(w, QComboBox) else w.text().strip()
                if val:
                    entry[param] = val
            result[map_id] = entry
        return result
