"""
Миксин панели превью: скины и стили (skinfamilies) оригинальной модели.

Детект скинов оружия/шапки в фоне, полоса переключения скинов, а также
пер-стилевые оверрайды материалов и сбор данных о скинах для сборки
(``get_skin_overrides`` / ``get_skin_build_data``). Вынесены из
``PreviewPanel`` без изменения тел — состояние и общие хелперы
(``_global_build_settings``, карточки, команды) остаются на панели и
разрешаются через ``self``.
"""

import os
from typing import Dict, Optional

from PySide6.QtCore import Qt

from src.shared.logging_config import get_logger
from src.ui.preview_widgets import _ExtraSlotCard

logger = get_logger(__name__)


class PreviewSkinsMixin:
    """Скины и стили оригинальной модели (см. модуль)."""

    def _clear_skin_buttons(self) -> None:
        """Виджетная половина сброса стилей: убирает кнопки."""
        for b in self._skin_buttons:
            b.setParent(None)
            b.deleteLater()
        self._skin_buttons = []
        self._skin_button_indices = []

    def _reset_skin_state(self) -> None:
        """Забывает вариантные стили и убирает их кнопки.

        Половинки разделены намеренно: сессия чистит память, панель — виджеты.
        Переход к игровой модели зовёт их порознь (см. _start_3d_worker), потому
        что память там сбрасывается разом в PreviewSession.begin_game_model.
        """
        self._session.reset_skins()
        self._clear_skin_buttons()

    def _start_skin_detection(self) -> None:
        """Запускает фоновое определение стилей оригинальной модели.

        Вызывается ТОЛЬКО при загрузке кастомной модели — дефолтный путь
        (обычная игровая модель) этот код не трогает.
        """
        if not self._weapon_key or self._weapon_key == '\x00':
            return
        params = self._pending_3d_params
        misc_vpk = params[2] if params else ''
        mode = params[1] if params else (self._weapon_mode or '')
        try:
            from src.services.skin_detect_worker import SkinDetectWorker
        except Exception as exc:
            logger.debug(f"[SKIN] worker import failed: {exc}")
            return
        self._stop_worker('_skin_worker')
        w = SkinDetectWorker(
            weapon_key=self._weapon_key,
            mode=mode,
            misc_vpk_path=misc_vpk,
            lang=self._lang,
            parent=self,
        )
        w.detected.connect(self._on_skins_detected)
        w.failed.connect(lambda _e: logger.info(f"[SKIN] стили не определены: {_e}"))
        w.start()
        self._skin_worker = w

    def _on_skins_detected(self, info: dict) -> None:
        """Получили skin-info оригинала — строим полосу стилей."""
        # Считаем по полному списку скинов (база + команда + варианты).
        skins = (info or {}).get('skins') or []
        if len(skins) < 2:
            # Один скин — полоса не нужна, кастом собирается как одно-скиновый.
            self._reset_skin_state()
            return
        self._original_skin_info = info
        self._active_skin = 0
        self._skin_overrides = {0: {}}
        self._skin_chosen = {}
        # Единственная текстура → принудительно карточка, чтобы базовый стиль
        # тоже был карточкой (для единообразия переключения стилей).
        if not self._card_mode and self._material_names:
            self._set_material_slots(list(self._material_names), force_cards=True)
        self._populate_skin_bar(info)

    def _populate_skin_bar(self, info: dict) -> None:
        """Создаёт кнопки скинов в тулбаре (все группы: база/команда/варианты)."""
        from PySide6.QtWidgets import QPushButton
        for b in self._skin_buttons:
            b.setParent(None)
            b.deleteLater()
        self._skin_buttons = []
        self._skin_button_indices = []   # сырой индекс скина для каждой кнопки

        skins = info.get('skins') or []
        # Вставляем перед анкером — кнопки держатся правее Australium.
        anchor_idx = self._toolbar_layout.indexOf(self._skin_anchor)
        for pos, sk in enumerate(skins):
            raw_idx = sk.get('index', pos)
            label = sk.get('role') or f"Skin {raw_idx}"
            btn = QPushButton(label)
            btn.setFixedHeight(26)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(self.t.get('skin_style_tip', 'Model style (skinfamilies)'))
            btn.setStyleSheet(
                self._skin_btn_style_on if raw_idx == self._active_skin
                else self._skin_btn_style_off
            )
            btn.clicked.connect(lambda _=False, idx=raw_idx: self._switch_skin(idx))
            self._toolbar_layout.insertWidget(anchor_idx + pos, btn)
            self._skin_buttons.append(btn)
            self._skin_button_indices.append(raw_idx)

    def _switch_skin(self, idx: int) -> None:
        """Переключает активный стиль и перестраивает карточки под него."""
        if idx == self._active_skin:
            return
        if not self._original_skin_info:
            return
        self._active_skin = idx
        self._skin_overrides.setdefault(idx, {})
        indices = getattr(self, '_skin_button_indices', [])
        for i, b in enumerate(self._skin_buttons):
            b_idx = indices[i] if i < len(indices) else i
            b.setStyleSheet(
                self._skin_btn_style_on if b_idx == idx else self._skin_btn_style_off
            )
        self._rebuild_cards_for_skin(idx)
        self._apply_skin_to_3d(idx)

    def _apply_skin_to_3d(self, idx: int) -> None:
        """Применяет текстуры активного стиля к 3D-модели.

        Для каждого материала: переопределённая текстура стиля (если задана),
        иначе — базовая (skin 0). Так стиль меняет в 3D только те материалы,
        которым пользователь дал свою текстуру; остальные показывают базу.
        """
        if not (self.is_3d_mode() and self._3d_available and self._3d_widget):
            return
        overrides = self._skin_overrides.get(idx, {})
        tex_map: dict = {}
        for mat in self._material_names:
            p = overrides.get(mat) if idx != 0 else None
            if not (p and os.path.exists(p)):
                p = self._resolve_base_texture(mat)
            if p and os.path.exists(p):
                tex_map[mat] = p
        if tex_map:
            if self._custom_vpk_mode:
                # Только изменившиеся текстуры — переключение стиля не лагает.
                self._apply_3d_delta(tex_map)
            else:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(0, lambda m=dict(tex_map): self._3d_widget.apply_material_map(m))

    def _rebuild_cards_for_skin(self, idx: int) -> None:
        """Полностью пересобирает полосу карточек под активный стиль.

        • Базовый стиль (0): обычные карточки всех материалов модели.
        • Доп. стиль (K>0): карточек НЕ видно. Показана кнопка «+ Добавить
          стиль» — по ней пользователь сам выбирает, какие материалы базы
          переопределить. Выбранный материал появляется отдельной карточкой
          и попадает в $texturegroup; невыбранные наследуют базу.
        """
        if idx == 0:
            # Базовый стиль — стандартная раскладка карточек.
            self._set_material_slots(list(self._material_names), force_cards=True)
            # В custom-VPK режиме вернём превью мода (они в _vpk_red_tex_map по
            # мешевым материалам, а не в _textures[Team.RED]).
            if self._custom_vpk_mode:
                for m, p in self._vpk_red_tex_map.items():
                    card = self._card_widgets.get(m)
                    if card and p and os.path.exists(p):
                        card.set_image(p, opaque=True)
            return

        # ── Вариантный стиль ────────────────────────────────────────────── #
        lay = self._cards_layout
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._card_widgets.clear()
        self._main_card = None
        self._card_mode = True

        chosen = self._skin_chosen.setdefault(idx, set())
        overrides = self._skin_overrides.setdefault(idx, {})
        for mat in self._material_names:
            if mat not in chosen:
                continue
            card = _ExtraSlotCard(mat, display_name=mat, parent=self._cards_bar)
            ov = overrides.get(mat)
            if ov and os.path.exists(ov):
                card.set_image(ov)
            card.image_changed.connect(self._on_extra_card_changed)
            self._wire_card(card)
            lay.addWidget(card)
            self._card_widgets[mat] = card

        # Кнопка «+ Добавить стиль» — если ещё есть материалы для добавления.
        if any(m not in chosen for m in self._material_names):
            from PySide6.QtWidgets import QPushButton
            add_btn = QPushButton(self.t.get('skin_add_style', '+ Add style'))
            add_btn.setObjectName('skin_add_btn')
            add_btn.setCursor(Qt.PointingHandCursor)
            add_btn.setFixedHeight(40)
            add_btn.setStyleSheet(
                "QPushButton#skin_add_btn { background:transparent; border:1px dashed #555;"
                " border-radius:6px; padding:10px 18px; color:#aaa; font-size:13px; }"
                " QPushButton#skin_add_btn:hover { border-color:#888; color:#ddd;"
                " background:rgba(255,255,255,0.04); }"
            )
            add_btn.clicked.connect(self._show_add_style_menu)
            lay.addWidget(add_btn)
            self._skin_add_btn = add_btn

        lay.addStretch()
        self.empty_state.hide()
        self.preview.hide()
        self._cards_scroll.show()

    def _show_add_style_menu(self) -> None:
        """Меню выбора базового материала для переопределения в текущем стиле."""
        from PySide6.QtWidgets import QMenu
        idx = self._active_skin
        if idx == 0:
            return
        chosen = self._skin_chosen.setdefault(idx, set())
        available = [m for m in self._material_names if m not in chosen]
        if not available:
            return
        menu = QMenu(self)
        for mat in available:
            menu.addAction(mat, lambda _=False, m=mat: self._add_material_to_style(m))
        btn = getattr(self, '_skin_add_btn', None)
        if btn is not None:
            menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))
        else:
            menu.exec()

    def _add_material_to_style(self, mat: str) -> None:
        """Добавляет материал в текущий вариантный стиль (пустая карточка)."""
        idx = self._active_skin
        if idx == 0:
            return
        self._skin_chosen.setdefault(idx, set()).add(mat)
        self._rebuild_cards_for_skin(idx)

    def get_skin_overrides(self) -> Dict[int, Dict[str, str]]:
        """Для сборки: {skin_idx: {mat_name: texture_path}} (без скина 0).

        Скин 0 — база, в результат не входит. Возвращаем только доп. стили с
        реально заполненными текстурами. Пустой dict → одно-скиновая сборка.
        """
        if not self._original_skin_info:
            return {}
        result: Dict[int, Dict[str, str]] = {}
        for skin_idx, mats in self._skin_overrides.items():
            if skin_idx == 0:
                continue
            cleaned = {m: p for m, p in mats.items() if p and os.path.exists(p)}
            if cleaned:
                result[skin_idx] = cleaned
        return result

    def get_skin_build_data(self) -> Optional[dict]:
        """Данные для сборки $texturegroup кастомной модели.

        Returns None, если стилей нет (одно-скиновая сборка — генерация группы
        не нужна). Иначе:
            {
              'mesh_materials': [имена материалов меша, порядок = skin 0],
              'tg_overrides':   {skin_idx: {mat: variant_name}},  # для группы
              'variant_files':  {variant_name: texture_path},     # для VTF/VMT
            }
        Имя варианта = <материал>_<суффикс роли> (bloody/clean/… или skinN).
        Регистр имён сохраняется как в карточках/SMD — чтобы $texturegroup,
        имена VTF и материал модели совпадали.
        """
        import re as _re
        ov = self.get_skin_overrides()   # {skin: {mat: path}}
        if not ov:
            return None
        # Роль по СЫРОМУ индексу скина (из полного списка skins).
        _skins = (self._original_skin_info or {}).get('skins', [])
        role_by_idx = {s.get('index'): s.get('role', '') for s in _skins}

        def _suffix(idx: int) -> str:
            label = role_by_idx.get(idx, '')
            s = _re.sub(r'[^a-z0-9]+', '_', label.strip().lower()).strip('_')
            return s or f'skin{idx}'

        tg_overrides: Dict[int, Dict[str, str]] = {}
        variant_files: Dict[str, str] = {}
        for skin_idx, mats in ov.items():
            suf = _suffix(skin_idx)
            for mat, path in mats.items():
                vname = f"{mat}_{suf}"
                tg_overrides.setdefault(skin_idx, {})[mat] = vname
                variant_files[vname] = path
        if not tg_overrides:
            return None
        return {
            'mesh_materials': list(self._material_names),
            'tg_overrides': tg_overrides,
            'variant_files': variant_files,
        }
