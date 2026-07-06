"""
Миксин панели превью: материальные карточки и пер-текстурные настройки.

Построение и обновление ряда карточек текстур (слоты материалов, маски
шпиона), их проводка к сигналам и обработка изменений, а также пер-
текстурные оверрайды (разрешение/формат/флаги, material-maps) и сбор
оверрайдов для сборки. Вынесены из ``PreviewPanel`` без изменения тел;
состояние остаётся на панели и разрешается через ``self``.
"""

import os
from typing import Dict, List, Optional

from src.shared.constants import Team
from src.shared.logging_config import get_logger
from src.ui.material_cards import spy_mask_cards
from src.ui.preview_widgets import _ExtraSlotCard, _SpyMaskVtfWorker

logger = get_logger(__name__)


class PreviewMaterialCardsMixin:
    """Материальные карточки и пер-текстурные настройки (см. модуль)."""

    def update_extra_slots(self, weapon_key: str, mode: str = '') -> None:
        """
        Сбрасывает и перенастраивает слоты при смене оружия/шапки.

        Сброс происходит ТОЛЬКО если weapon_key или mode изменились.
        Для оружий карточки появятся позже через _on_3d_multi_material.
        Для рук карточки определяются сразу из HAND_MODES (без 3D).
        """
        # Восстановление из мини-памяти уже выставило _weapon_key/_weapon_mode
        # (см. _restore_from_memory) — попадаем в ранний выход и не затираем его.
        if weapon_key == self._weapon_key and mode == self._weapon_mode:
            return   # то же самое — ничего не сбрасываем

        self._begin_new_weapon(weapon_key, mode)

        from src.data.player_hands import HAND_MODE_KEYS, HAND_MODES

        if mode in HAND_MODE_KEYS:
            # Руки — слоты известны статически
            textures = HAND_MODES.get(mode, {}).get('textures', [])
            all_names = [vtf_name for _, vtf_name in textures]
            self._set_material_slots(all_names)
        else:
            # Сбрасываем до одного слота. Карточки появятся через _on_3d_multi_material
            self._set_material_slots([])

    def update_extra_slots_spy_masks(self, mask_vtf_names: list) -> None:
        """Настраивает карточки для режима масок шпиона.

        Создаёт 9 карточек — по одной на маску каждого класса.
        Имена карточек соответствуют именам VTF файлов (mask_scout и т.д.).
        """
        weapon_key = '__spy_masks__'
        mode = 'spy_masks'

        if weapon_key == self._weapon_key and mode == self._weapon_mode:
            return

        self._weapon_key = weapon_key
        self._weapon_mode = mode

        # Сброс состояния
        self._textures = {Team.RED: {}, Team.BLU: {}}
        self._material_names = []
        self._has_blu = False
        self._active_team = Team.RED
        self.image_path = None
        self.vtf_path = None
        self._gif_cache = {}
        self._per_mesh_active = False
        self._per_mesh_base_image = None
        self.btn_red.setVisible(False)
        self.btn_blu.setVisible(False)
        self._stop_gif()

        # Спеки карточек (имя VTF + локализованная подпись класса) — единый
        # источник в material_cards.
        specs = spy_mask_cards(mask_vtf_names, self._lang)
        self._set_material_slots_with_display([(s.name, s.display_name) for s in specs])

        # Подгружаем игровые превью каждой маски в карточки (как у обычного оружия) —
        # чтобы заранее было видно оригинальные текстуры, а не пустые слоты.
        self._load_spy_mask_previews()

    def _clear_cards(self) -> None:
        """Удаляет все карточки из ряда и сбрасывает ссылки. Общий примитив
        для всех рендереров карточек (раньше дублировался)."""
        lay = self._cards_layout
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._card_widgets.clear()
        self._main_card = None
        self._aus_card = None

    def _make_card(self, name: str, display_name: str, image, opaque: bool, on_change):
        """Создаёт одну карточку материала, ставит текстуру (если есть), подключает
        сигналы и добавляет в ряд. Возвращает карточку (хранение — за вызывающим).
        Общий примитив: раскладку (главный/доп./австралий) решает вызывающий."""
        card = _ExtraSlotCard(name, display_name=display_name, parent=self._cards_bar)
        if image and os.path.exists(image):
            card.set_image(image, opaque=opaque)
        card.image_changed.connect(on_change)
        self._wire_card(card)
        self._cards_layout.addWidget(card)
        return card

    def _set_material_slots_with_display(self, names_display: list) -> None:
        """Показывает карточки для пар (mat_name, display_name).
        Используется для масок шпиона где display_name = имя класса.
        """
        self._clear_cards()

        if not names_display:
            self._card_mode = False
            self._material_names = []
            self._cards_scroll.hide()
            self.preview.hide()
            self.empty_state.show()
            return

        self._card_mode = True
        self._material_names = [n for n, _ in names_display]

        for mat_name, disp_name in names_display:
            card = self._make_card(
                mat_name, disp_name, self._textures[Team.RED].get(mat_name),
                opaque=False, on_change=self._on_extra_card_changed,
            )
            self._card_widgets[mat_name] = card

        self._cards_layout.addStretch()
        self.empty_state.hide()
        self.preview.hide()
        self._cards_scroll.show()

    def _load_spy_mask_previews(self) -> None:
        """
        Извлекает игровые VTF всех масок в фоне и проставляет их превью в карточки
        2D — чтобы заранее были видны оригинальные текстуры (как у обычного оружия).

        Превью регистрируется в _vpk_red_tex_map (как ИГРОВАЯ текстура), а НЕ в
        _textures[Team.RED], поэтому в сборку как пользовательская не попадёт —
        некастомизированные маски берут оригинал из игры.
        """
        if not self._spy_mask_mode or not self._card_widgets:
            return
        misc = getattr(self, '_current_misc_vpk', None)
        tex = getattr(self, '_current_textures_vpk', None)
        if not (misc or tex):
            return
        # Только маски без пользовательской текстуры — для них показываем оригинал.
        names = [n for n in self._material_names
                 if not (self._textures[Team.RED].get(n)
                         and os.path.exists(self._textures[Team.RED][n]))]
        if not names:
            return
        out_dir = os.path.join('tools', 'temp', 'spy_mask_preview')
        w = _SpyMaskVtfWorker(names, [tex, misc], out_dir, parent=self)
        w.one.connect(self._on_spy_mask_preview)
        w.start()
        if not hasattr(self, '_mask_workers'):
            self._mask_workers = []
        self._mask_workers.append(w)

    def _on_spy_mask_preview(self, vtf_name: str, png: str) -> None:
        """Проставляет извлечённое игровое превью маски в её карточку."""
        if not png or not os.path.exists(png):
            return
        # Регистрируем как игровую текстуру (распознаётся _is_game_texture),
        # не как пользовательскую — поэтому показываем opaque и в сборку не тащим.
        self._vpk_red_tex_map[vtf_name] = png
        card = self._card_widgets.get(vtf_name)
        if card:
            card.set_image(png, opaque=True)

    def _set_material_slots(self, names: List[str], force_cards: bool = False) -> None:
        """Показывает карточки для списка материалов (или большое превью если < 2).

        force_cards=True строит карточку даже для одного материала — нужно для
        кастомных моделей со стилями: чтобы у единственной текстуры была карточка
        с плюсиком, которую можно очистить/переопределить под каждый стиль.
        """
        self._clear_cards()

        if len(names) < 1 or (len(names) < 2 and not force_cards):
            # ── Одиночный режим ─────────────────────────────────────────────── #
            self._card_mode = False
            self._material_names = names
            self._cards_scroll.hide()
            if self.image_path and os.path.exists(self.image_path):
                self.empty_state.hide()
                self.preview.show()
            else:
                self.preview.hide()
                self.empty_state.show()
            return

        # ── Режим карточек ──────────────────────────────────────────────────── #
        self._card_mode = True
        self._material_names = list(names)

        # Для BLU команды лейбл карточки показывает BLU-имя текстуры (из QC skinfamilies),
        # а не RED-имя из SMD. Так пользователь видит реальное имя заменяемой текстуры.
        def _display(mat_name: str) -> str:
            if self._active_team == Team.BLU and self._vpk_blu_name_map:
                return self._vpk_blu_name_map.get(mat_name, mat_name)
            return mat_name

        # Главная текстура: восстановленная (резолв) → иначе текущая image_path.
        main_name = names[0]
        saved = self._resolve_card_texture(main_name)
        if saved and os.path.exists(saved):
            main_img, main_opaque = saved, self._is_game_texture(saved)
        elif self.image_path and os.path.exists(self.image_path) and not self._misc_mode:
            # В режиме «Прочее» первая карточка — служебный материал, а не главная
            # текстура: не подставляем сюда self.image_path (иначе главная «прилетит»
            # на misc-слот).
            main_img, main_opaque = self.image_path, False
        else:
            main_img, main_opaque = None, False
        self._main_card = self._make_card(
            main_name, _display(main_name), main_img, main_opaque,
            on_change=self._on_main_card_changed,
        )

        for name in names[1:]:
            saved = self._resolve_card_texture(name)
            img = saved if (saved and os.path.exists(saved)) else None
            card = self._make_card(
                name, _display(name), img,
                opaque=self._is_game_texture(saved) if img else False,
                on_change=self._on_extra_card_changed,
            )
            self._card_widgets[name] = card

        # Australium — отдельный тип текстуры в конце ряда (если вариант найден)
        self._append_australium_card(self._cards_layout)

        self._cards_layout.addStretch()

        self.empty_state.hide()
        self.preview.hide()
        self._cards_scroll.show()

    # ═══════════════════════════════════════════════════════════════════════════
    # Пер-текстурные настройки (разрешение/формат/флаги на материал)
    # ═══════════════════════════════════════════════════════════════════════════

    def _global_build_settings(self) -> dict:
        """Глобальные настройки сборки (size/format/flags/options) из settings_panel."""
        try:
            s = self.parent.settings_panel.get_settings()
            return {
                'size': s.get('size', (512, 512)),
                'format': s.get('format', 'DXT1'),
                'flags': list(s.get('flags', []) or []),
                'options': dict(s.get('vtf_options', {}) or {}),
            }
        except Exception:
            return {'size': (512, 512), 'format': 'DXT1', 'flags': [], 'options': {}}

    def _wire_card(self, card) -> None:
        """Подключает кнопку-шестерёнку карточки и выставляет бейдж оверрайда."""
        card.settings_requested.connect(self._on_card_settings_requested)
        ov = self._tex_overrides.get(card.material_name)
        if ov:
            from src.data.texture_overrides import override_badge
            card.set_override_badge(override_badge(ov, self._global_build_settings()))

    def _card_for_material(self, mat: str):
        if self._main_card is not None and self._main_card.material_name == mat:
            return self._main_card
        return self._card_widgets.get(mat)

    def _ensure_tex_edit_signals(self, sp) -> None:
        """Однократно подключает сигналы режима «настройки текстуры» панели Step 2."""
        if getattr(self, '_tex_edit_connected', False):
            return
        sp.texture_setting_changed.connect(self._on_tex_override_changed)
        sp.texture_edit_reset.connect(lambda m: self._on_tex_override_changed(m, None))
        self._tex_edit_connected = True

    def _effective_for_material(self, mat: str) -> dict:
        from src.data.texture_overrides import effective_settings
        return effective_settings(self._global_build_settings(), self._tex_overrides.get(mat))

    def _on_card_settings_requested(self, mat: str) -> None:
        """Переводит панель Step 2 в режим редактирования настроек материала.

        Простое открытие статус НЕ меняет: панель лишь показывает текущие
        (оверрайд или глобальные) значения. Оверрайд создаётся только при
        реальном изменении контрола (сигнал texture_setting_changed).
        """
        sp = getattr(self.parent, 'settings_panel', None)
        if sp is None or not hasattr(sp, 'enter_texture_edit'):
            return
        self._ensure_tex_edit_signals(sp)
        sp.enter_texture_edit(mat, self._effective_for_material(mat))

    def _on_tex_override_changed(self, mat: str, override) -> None:
        """Из Step 2: dict — записать оверрайд материала; None — вернуть глобальное."""
        from src.data.texture_overrides import override_badge
        card = self._card_for_material(mat)
        if override:
            self._tex_overrides[mat] = override
            if card is not None:
                card.set_override_badge(override_badge(override, self._global_build_settings()))
        else:
            self._tex_overrides.pop(mat, None)
            if card is not None:
                card.set_override_badge('')

    def get_texture_overrides(self) -> Dict[str, dict]:
        """Для сборки: {material: {size,format,flags,options}} — только кастомные."""
        return {m: dict(s) for m, s in self._tex_overrides.items() if s}

    def open_material_maps(self, material: str = '') -> None:
        """Открывает диалог файловых карт для МАТЕРИАЛА (пер-текстурно).

        material == '' → главный материал (material_names[0]). Карты сохраняются
        в self._tex_maps[material] и применяются именно к этой текстуре при сборке.
        """
        # '' = главный материал (в сборке мапится на texture_filename надёжно,
        # даже если UI не знает его точное имя).
        mat = material or (self._material_names[0] if self._material_names else '')
        from src.ui.material_maps_dialog import MaterialMapsDialog
        dlg = MaterialMapsDialog(self.t, current=self._tex_maps.get(mat), parent=self)
        if dlg.exec():
            maps = dlg.get_maps()
            if maps:
                self._tex_maps[mat] = maps
            else:
                self._tex_maps.pop(mat, None)

    def get_texture_maps(self) -> Dict[str, dict]:
        """Для сборки: {material: {map_id: spec}} — пер-текстурные карты."""
        return {m: dict(v) for m, v in self._tex_maps.items() if v}

    def _on_main_card_changed(self, mat_name: str, path: str) -> None:
        """Пользователь сменил или сбросил текстуру в главной карточке."""
        # Просмотр «Прочее»: первая карточка — служебный материал, а НЕ главная
        # текстура мода. Не трогаем глобальную image_path (она ушла бы в from_path
        # как главная), ведём себя как обычная доп-карточка (хранение по имени).
        if self._misc_mode:
            self._on_extra_card_changed(mat_name, path)
            return
        # Если активен Australium — текстура идёт в его отдельный слот,
        # не затирая обычную/командную.
        if self._australium_active:
            self._set_australium_user_tex(path or None)
            return
        self._stop_gif()
        self._per_mesh_active = False
        self._per_mesh_base_image = None
        self.vtf_path = None

        if path:
            # Загрузка новой текстуры
            self.image_path = path
            self._store_texture(mat_name, path)
            self.update_info_summary()
            self._apply_tex_to_3d_later(mat_name, path)
        else:
            # Сброс текстуры (нажат ×) — удаляем и восстанавливаем оригинал в 3D.
            # Вызываем restore независимо от текущего режима (2D или 3D) — иначе
            # при переключении обратно в 3D старая текстура остаётся на модели.
            self.image_path = None
            self._store_texture(mat_name, None)
            self.update_info_summary()
            if self._3d_widget and self._3d_available:
                self._schedule_3d(lambda: self._restore_team_textures_3d(self._active_team))

    def _is_neutral_texture(self, mat_name: str) -> bool:
        """True если текстура не относится к конкретной команде (см. модель)."""
        return self._state.is_neutral(mat_name)

    def _store_texture(self, mat_name: str, path: Optional[str]) -> None:
        """Сохраняет пользовательскую текстуру (маршрутизация — в модели:
        вариантный стиль → skin_overrides, нейтральная → обе команды)."""
        self._state.set_texture(mat_name, path)
        logger.debug(f"[store tex] '{mat_name}' team={self._active_team} "
                     f"skin={self._active_skin}: {path}")

    def _on_extra_card_changed(self, mat_name: str, path: str) -> None:
        """Пользователь сменил или сбросил текстуру в карточке доп. слота."""
        if path:
            self._store_texture(mat_name, path)
            # В custom-VPK режиме имя карточки (стебель VTF) переводим в точное
            # имя материала модели, чтобы текстура легла на правильный меш.
            apply_key = (self._custom_material_for_card(mat_name)
                         if self._custom_vpk_mode else mat_name)
            self._apply_tex_to_3d_later(apply_key, path)
        else:
            # Сброс — удаляем из обеих команд если нейтральная.
            self._store_texture(mat_name, None)
            if self._3d_widget and self._3d_available:
                if self._custom_vpk_mode:
                    # Вернуть оригинал мода на правильный меш.
                    self._schedule_3d(self._apply_custom_vpk_textures_to_3d)
                else:
                    self._schedule_3d(lambda: self._restore_team_textures_3d(self._active_team))
