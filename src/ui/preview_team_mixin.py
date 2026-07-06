"""
Миксин панели превью: команды RED / BLU.

Переключение активной команды и восстановление её текстур в 2D и 3D,
перестройка командных карточек рук и применение VPK-кадров команды.
Вынесены из ``PreviewPanel`` без изменения тел; состояние (``_state``,
карточки, VPK-карты команд) остаётся на панели и разрешается через ``self``.
"""

import os
from typing import List

from PySide6.QtCore import Qt

from src.shared.constants import Team
from src.shared.logging_config import get_logger
from src.ui.texture_state import SINGLE_TEX_KEY

logger = get_logger(__name__)


class PreviewTeamMixin:
    """Команды RED / BLU: переключение и восстановление текстур (см. модуль)."""

    def _switch_team(self, team: str) -> None:
        """Переключает активную команду и восстанавливает её текстуры.

        RED / BLU / Australium взаимоисключающие: если активен Australium —
        выбор команды его отменяет (гасим кнопку и возвращаем текстуры команды).
        """
        # Переключение команды выходит из просмотра «Прочее» (возвращаем обычные
        # карточки), иначе команда применялась бы к служебным карточкам.
        if self._misc_mode:
            self._misc_mode = False
            restore = self._cards_before_misc or [self._main_material_name or '']
            self._set_material_slots([m for m in restore if m])
        aus_was_active = self._australium_active
        self._australium_active = False
        # Если уже на этой команде и австралий не был активен — делать нечего.
        if self._active_team == team and not aus_was_active:
            self._sync_variant_buttons()
            return
        self._active_team = team
        self._sync_variant_buttons()
        # Руки И force-team мульти-материал: на BLU показываем выбранные карточки +
        # «+» для добавления (та же логика). Хранение нативное (_textures[Team.BLU]).
        from src.data.player_hands import HAND_MODE_KEYS as _HMK_sw
        if ((self._weapon_mode in _HMK_sw or self._force_team)
                and self._card_mode and self._material_names):
            self._rebuild_hand_team_cards(team)
            if self._3d_available and self._3d_widget:
                self._restore_team_textures_3d(team)
            return
        self._restore_team_textures_2d(team)
        if self._3d_available and self._3d_widget:
            self._restore_team_textures_3d(team)


    def _is_team_material(self, mat: str) -> bool:
        """True если у материала есть СВОЙ синий вариант (см. модель)."""
        return self._state.is_team_material(mat)

    def _rebuild_hand_team_cards(self, team: str) -> None:
        """Перестраивает карточки рук под команду.

        • RED — все материалы (база).
        • BLU — только командные (свой синий) + нейтральные, которым задана синяя
          или добавленные через «+». Остальные нейтральные скрыты (общие).
        """
        if team == Team.RED:
            self._set_material_slots(list(self._material_names))
            return

        self._clear_cards()
        self._card_mode = True
        chosen = getattr(self, '_hand_blu_chosen', set())
        blu = self._textures.get(Team.BLU, {})
        show = [
            m for m in self._material_names
            if self._is_team_material(m) or (blu.get(m) and os.path.exists(blu[m])) or m in chosen
        ]
        for m in show:
            disp = self._vpk_blu_name_map.get(m, m) if self._vpk_blu_name_map else m
            img = self._resolve_card_texture(m)
            card = self._make_card(
                m, disp, img,
                opaque=self._is_game_texture(img) if img else False,
                on_change=self._on_extra_card_changed,
            )
            self._card_widgets[m] = card

        # «+» — если есть нейтральные, ещё не показанные (можно сделать командными).
        _hideable = [m for m in self._material_names
                     if m not in show and not self._is_team_material(m)]
        if _hideable:
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
            add_btn.clicked.connect(self._show_hand_add_blu_menu)
            self._cards_layout.addWidget(add_btn)

        self._cards_layout.addStretch()
        self.empty_state.hide()
        self.preview.hide()
        self._cards_scroll.show()

    def _show_hand_add_blu_menu(self) -> None:
        """Меню: какой нейтральный материал сделать командным (добавить на BLU)."""
        from PySide6.QtWidgets import QMenu
        chosen = self.__dict__.setdefault('_hand_blu_chosen', set())
        blu = self._textures.get(Team.BLU, {})
        avail = [
            m for m in self._material_names
            if not self._is_team_material(m) and m not in chosen
            and not (blu.get(m) and os.path.exists(blu[m]))
        ]
        if not avail:
            return
        menu = QMenu(self)
        for m in avail:
            menu.addAction(m, lambda _=False, mat=m: self._add_hand_blu_material(mat))
        # Показываем под кнопкой «+ Add style», по которой кликнули (а не под
        # верхним BLU-тумблером). sender() — это та самая кнопка.
        from PySide6.QtWidgets import QPushButton as _QPB_menu
        _src = self.sender()
        _anchor = _src if isinstance(_src, _QPB_menu) else self.btn_blu
        menu.exec(_anchor.mapToGlobal(_anchor.rect().bottomLeft()))

    def _add_hand_blu_material(self, mat: str) -> None:
        self.__dict__.setdefault('_hand_blu_chosen', set()).add(mat)
        self._rebuild_hand_team_cards(Team.BLU)

    def _restore_team_textures_2d(self, team: str) -> None:
        """Показывает в 2D карточках/большом превью текстуры выбранной команды."""
        paths = self._textures.get(team, {})

        if self._card_mode and self._material_names:
            main_key = self._material_names[0]
            main_path = paths.get(main_key)
            self.image_path = main_path if (main_path and os.path.exists(main_path)) else None

            # Обновляем изображения в существующих карточках напрямую
            # (без полного пересоздания — чтобы нейтральные текстуры оставались).
            if self._card_widgets or self._main_card:
                self._update_card_images_for_team(team)
            else:
                # Карточки ещё не созданы — создаём
                self._set_material_slots(self._material_names)
        else:
            key = self._material_names[0] if self._material_names else SINGLE_TEX_KEY
            path = paths.get(key)
            self._stop_gif()
            if path and os.path.exists(path):
                self.image_path = path
                self._show_image_in_preview(path)
            else:
                # Своей текстуры для команды нет — показываем игровой кадр команды
                # (display-only, как делает 3D через _apply_vpk_frames). image_path
                # оставляем None: сборка не должна считать это пользовательской текстурой.
                self.image_path = None
                # force_team на BLU без своей синей → дефолт «как RED» (display-only).
                # У force_team нет игрового оригинала, поэтому без этого превью было
                # бы пустым (раньше RED показывался за счёт дубля в set_texture).
                _ft_red = (self._textures.get(Team.RED, {}).get(key)
                           if (self._force_team and team == Team.BLU) else None)
                # Командный одно-материальный материал (spy_hands_red): синяя в
                # _vpk_blu_tex_map, а не в _blu_frames — берём её.
                _gp = (self._vpk_blu_tex_map if team == Team.BLU
                       else self._vpk_red_tex_map).get(key)
                vpk_frames = self._blu_frames if team == Team.BLU else self._red_frames
                if _ft_red and os.path.exists(_ft_red):
                    self._show_image_in_preview(_ft_red)
                elif _gp and os.path.exists(_gp):
                    self._show_image_in_preview(_gp)
                elif vpk_frames and os.path.exists(vpk_frames[0]):
                    self._show_image_in_preview(vpk_frames[0])
                else:
                    self._clear_preview_label()

        self.vtf_path = None
        self.update_info_summary()

    def _update_card_images_for_team(self, team: str) -> None:
        """Обновляет изображения в существующих карточках для выбранной команды.

        Вместо полного пересоздания (deleteLater + new cards) просто обновляем
        изображение каждой карточки. Для нейтральных текстур (sniper_lens и т.п.)
        берём из любой команды где она есть.
        """
        # Для BLU обновляем label карточки если есть маппинг имён
        def _display(mat_name: str) -> str:
            if team == Team.BLU and self._vpk_blu_name_map:
                return self._vpk_blu_name_map.get(mat_name, mat_name)
            return mat_name

        # Главная карточка
        if self._main_card and self._material_names:
            main_name = self._material_names[0]
            self._main_card.set_display_name(_display(main_name))
            tex = self._resolve_card_texture(main_name)
            if tex and os.path.exists(tex):
                self._main_card.set_image(tex, opaque=self._is_game_texture(tex))
            elif self._original_skin_info and self._active_skin != 0:
                # Вариантный стиль без переопределения — карточка должна быть пустой.
                self._main_card.reset()
            elif not self._main_card.get_image():
                pass  # оставляем как есть

        # Дополнительные карточки
        for mat_name, card in self._card_widgets.items():
            card.set_display_name(_display(mat_name))
            tex = self._resolve_card_texture(mat_name)
            logger.debug(f"[restore 2D] team={team} mat={mat_name!r} tex={tex!r}")
            if tex and os.path.exists(tex):
                card.set_image(tex, opaque=self._is_game_texture(tex))
            else:
                # Нет текстуры для этой команды — сбрасываем карточку
                if not self._is_neutral_texture(mat_name):
                    card.reset()
                # Нейтральные оставляем как есть (уже показывают нужную текстуру)

    def _restore_team_textures_3d(self, team: str) -> None:
        """Применяет текстуры команды к 3D модели.

        Строит полную карту: VPK-оригиналы для всех слотов + пользовательские
        текстуры поверх. Это гарантирует что очищенные (×) слоты корректно
        возвращаются к игровому оригиналу, а не остаются с кастомной текстурой.
        """
        from PySide6.QtCore import QTimer
        paths = self._textures.get(team, {})
        vpk_frames = self._red_frames if team == Team.RED else self._blu_frames
        vpk_map = self._vpk_red_tex_map if team == Team.RED else self._vpk_blu_tex_map

        if self._card_mode and self._material_names:
            # Начинаем с VPK-оригиналов (база для всех слотов)
            full_map: dict = dict(vpk_map) if vpk_map else {}

            # Поверх накладываем пользовательские текстуры (только загруженные)
            for mat in self._material_names:
                p = paths.get(mat)
                # Руки на BLU: нейтральный материал без СВОЕЙ синей наследует
                # RED-правку (а не игровой синий кадр).
                if not (p and os.path.exists(p)) and team == Team.BLU:
                    _bn = self._vpk_blu_name_map.get(mat, mat) if self._vpk_blu_name_map else mat
                    if _bn.lower() == mat.lower():   # нейтральный
                        _rp = self._textures.get(Team.RED, {}).get(mat)
                        if _rp and os.path.exists(_rp):
                            p = _rp
                if p and os.path.exists(p):
                    full_map[mat] = p
                elif mat in full_map:
                    pass   # Слот очищен — оставляем VPK-оригинал из базы

            if full_map:
                static: dict = {}
                for mat, p in full_map.items():
                    if p.lower().endswith('.gif'):
                        QTimer.singleShot(50, lambda _p=p, _m=mat: self._apply_gif_to_3d(_p, _m))
                    else:
                        static[mat] = p
                if static:
                    QTimer.singleShot(50, lambda m=static: self._3d_widget.apply_material_map(m))
            else:
                # VPK-карта пустая (оружие/шапка без мульти-материала) → кадры
                self._apply_vpk_frames(vpk_frames)
        else:
            key = self._material_names[0] if self._material_names else SINGLE_TEX_KEY
            path = paths.get(key)
            if not (path and os.path.exists(path)):
                # Командный одно-материальный (spy_hands_red): синяя в _vpk_blu_tex_map.
                _gp = vpk_map.get(key) if vpk_map else None
                if _gp and os.path.exists(_gp):
                    path = _gp
                elif self._force_team and team == Team.BLU:
                    # force_team на BLU без своей синей → дефолт «как RED»
                    # (у force_team нет игрового оригинала).
                    _rp = self._textures.get(Team.RED, {}).get(key)
                    if _rp and os.path.exists(_rp):
                        path = _rp
            if path and os.path.exists(path):
                QTimer.singleShot(50, lambda p=path: self._apply_image_to_3d(p))
            else:
                self._apply_vpk_frames(vpk_frames)

    def _apply_vpk_frames(self, frames: List[str]) -> None:
        """Применяет VPK-кадры к 3D модели."""
        if not frames or not self._3d_widget:
            return
        if len(frames) > 1 and self._team_framerate > 0:
            self._3d_widget.update_animated_texture_files(frames, self._team_framerate)
        else:
            self._3d_widget.update_texture_file(frames[0])
