"""
Миксин панели превью: 2D-изображение и разрешение путей текстур.

Загрузка изображения/VTF в 2D-превью, показ в лейбле, а также геттеры и
резолверы путей текстур слотов (``get_slot_image_paths`` / ``load_image`` /
``load_vtf`` / ``_resolve_*_texture`` / ``_show_image_in_preview`` …).
Вынесены из ``PreviewPanel`` без изменения тел; состояние остаётся на
панели и разрешается через ``self``.
"""

import os
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

from src.shared.constants import Team
from src.shared.file_utils import get_temp_file_path
from src.shared.logging_config import get_logger
from src.ui.preview_widgets import _load_pixmap
from src.domain.preview.texture_state import SINGLE_TEX_KEY

logger = get_logger(__name__)


class Preview2DImageMixin:
    """2D-изображение и разрешение путей текстур (см. модуль)."""

    def get_slot_image_paths(self) -> dict:
        """{material_name: path} всех заполненных слотов (для сборки).
        Порядок команд и пропуск SINGLE_TEX_KEY — в модели."""
        return self._state.uploaded_slot_paths()

    def get_blu_slot_image_paths(self) -> dict:
        """{material_name: path} только BLU-слотов (командность рук при сборке)."""
        return self._state.blu_uploaded_paths()

    def load_image(self, path: str) -> None:
        """Загружает изображение (или GIF) в 2D Preview."""
        # Australium активен — грузим в его отдельный слот, не трогая обычную.
        if self._australium_active:
            self._set_australium_user_tex(path or None)
            return
        # Скайбокс: любое «загрузить изображение» (дроп в 3D-окно, дроп в 2D,
        # диалог) — это панорама. Роутим в карточку панорамы и единый
        # обработчик (нарезка на грани + перерисовка неба); общий путь ниже
        # загрязнил бы image_path и никогда не запустил бы нарезку.
        if self._pstate.is_skybox:
            from src.data.skyboxes import SKY_PANO_KEY
            card = self._card_widgets.get(SKY_PANO_KEY)
            if card:
                card.set_image(path)
            self._on_skybox_card_changed(SKY_PANO_KEY, path)
            self.update_info_summary()
            return
        self._stop_gif()
        if path != self._per_mesh_base_image:
            self._per_mesh_active = False
            self._per_mesh_base_image = None

        self.image_path = path
        self.vtf_path = None

        # Через _store_texture — как карточки: нейтральные текстуры попадают в
        # обе команды, на вариантном стиле (skin > 0) — в _skin_overrides.
        # Раньше писали в _textures напрямую, и стиль/команда рассинхранивались
        # с загрузкой через 2D-окно.
        key = self._material_names[0] if self._material_names else SINGLE_TEX_KEY
        self._store_texture(key, path)

        if self._card_mode and self._main_card is not None:
            self._main_card.set_image(path)
        else:
            self._show_image_in_preview(path)

        # Обновляем 3D если видно
        if self.is_3d_mode() and self._3d_available and self._3d_widget \
                and not self._from_3d_drop:
            if self._card_mode and self._material_names and not self._crithit_mode:
                self._apply_tex_to_3d_later(self._material_names[0], path)
            elif self._crithit_mode:
                self._schedule_3d(lambda p=path: self._update_scene_texture(p))
            else:
                self._schedule_3d(lambda p=path: self._apply_image_to_3d(p))

        self.update_info_summary()

    def load_vtf(self, path: str) -> None:
        """Загружает VTF файл и отображает первый кадр."""
        if not os.path.exists(path):
            return
        self.vtf_path = path
        self.image_path = None
        png_for_3d: Optional[str] = None
        rendered = False

        try:
            from src.services.vtflib_wrapper import VTFLib
            from PIL import Image
            from PySide6.QtGui import QImage

            rgba, w, h = VTFLib.read_vtf_as_rgba(path)
            qimg = QImage(rgba, w, h, w * 4, QImage.Format_RGBA8888)
            if not qimg.isNull():
                rendered = True
                png_for_3d = str(get_temp_file_path(prefix='tf2_3d_', suffix='.png'))
                Image.frombytes("RGBA", (w, h), rgba).save(png_for_3d)
                self.image_path = png_for_3d

                # Через _store_texture — та же маршрутизация (команды/стили),
                # что и у карточек/load_image.
                key = self._material_names[0] if self._material_names else SINGLE_TEX_KEY
                self._store_texture(key, png_for_3d)

                if self._card_mode and self._main_card:
                    self._main_card.set_image(png_for_3d)
                else:
                    self.empty_state.hide()
                    self.preview.show()
                    self.preview.clear()
                    self.preview.setStyleSheet(self._preview_style)
                    self.preview.setPixmap(QPixmap.fromImage(qimg).scaled(
                        *self._preview_box(600),
                        Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception as e:
            logger.warning(f"VTF рендер: {e}")

        if not rendered and not (self._card_mode and self._main_card):
            self.empty_state.hide()
            self.preview.show()
            self.preview.clear()
            self.preview.setStyleSheet(self._preview_style)
            self.preview.setText(f"VTF: {os.path.basename(path)}")
            self.preview.setStyleSheet(
                self._preview_style + "QLabel { color:#ccc; font-size:14px; }"
            )
            self.preview.setAlignment(Qt.AlignCenter)

        if png_for_3d and self._3d_available and self._3d_widget and self.is_3d_mode():
            if self._crithit_mode:
                self._update_scene_texture(png_for_3d)
            elif self._card_mode and self._material_names:
                self._3d_widget.apply_material_map({self._material_names[0]: png_for_3d})
            else:
                self._3d_widget.update_texture_file(png_for_3d)

        self.update_info_summary()

    def get_vtf_path(self) -> Optional[str]:
        return self.vtf_path

    def get_red_image_path(self) -> Optional[str]:
        """Возвращает путь к RED текстуре для сборки.

        НЕ делает fallback на BLU — чтобы не подставлять BLU-текстуру как
        основную (RED) в BuildWorker.

        self.image_path используется как fallback только когда активна RED
        команда: в BLU-режиме он уже содержит BLU-текстуру (обновляется в
        _restore_team_textures_2d при переключении команды).

        Возвращает None если RED не загружена → build_vpk поставит sentinel
        и покажет диалог выбора.
        """
        p = self._state.red_main()
        if p:
            return p
        # image_path как fallback только в RED-режиме (в BLU он содержит BLU-текстуру)
        if self._active_team != Team.BLU and self.image_path and os.path.exists(self.image_path):
            return self.image_path
        return None

    def _is_game_texture(self, path: Optional[str]) -> bool:
        """
        True, если path — извлечённая из игры текстура (VPK-кадр команды /
        вариант Australium), а не пользовательская. Для таких в 2D-превью
        отбрасываем альфу (она у VTF — маска бликов, а не прозрачность).
        """
        if not path:
            return False
        if path == self._australium_frame:
            return True
        if path in self._red_frames or path in self._blu_frames:
            return True
        if (path in self._vpk_red_tex_map.values()
                or path in self._vpk_blu_tex_map.values()):
            return True
        return False

    def _resolve_card_texture(self, mat_name: str) -> Optional[str]:
        """Текстура для карточки при текущей команде/стиле (правила — в модели)."""
        from src.data.player_hands import HAND_MODE_KEYS as _HMK_card
        hands_blu_view = (self._weapon_mode in _HMK_card
                          and self._active_team == Team.BLU)
        return self._state.resolve_card(mat_name, hands_blu_view=hands_blu_view)

    def _resolve_base_texture(self, mat_name: str) -> Optional[str]:
        """Базовая (skin 0) текстура: пользовательская → другая команда для
        нейтральных → VPK-оригинал → командный кадр (приоритеты — в модели)."""
        return self._state.resolve_base(mat_name)

    def get_uploaded_texture_for_mat(self, mat_name: str) -> Optional[str]:
        """Возвращает путь к уже загруженной пользователем текстуре для данного
        материала, или None если не загружена.

        Логика (важно — не смешиваем RED и BLU):

        1. Если mat_name — RED-имя (ключ в _vpk_blu_name_map, напр. 'medic_head_red'):
           → смотрим ТОЛЬКО в _textures[Team.RED]. Не fallback-аем на BLU.
           Это гарантирует, что build спросит диалог когда RED не загружена,
           а не молча подставит BLU-текстуру.

        2. Если mat_name — BLU-имя (значение в _vpk_blu_name_map, напр. 'medic_head_blue'):
           → обратный поиск: BLU-имя → RED-ключ → _textures[Team.BLU][RED-ключ].
           (Карточки хранят BLU-текстуры под RED-ключами.)

        3. Иначе (оружие/шапка без явного маппинга, руки):
           → прямой поиск в обеих командах.
        """
        return self._state.uploaded_for_mat(mat_name)

    def get_blu_image_path(self) -> Optional[str]:
        """Возвращает путь к пользовательской BLU текстуре (главный слот) или None."""
        return self._state.blu_main()

    # ── Вспомогательные методы 2D ─────────────────────────────────────────────

    def _show_image_in_preview(self, path: str) -> None:
        """Показывает изображение в большом превью (не card_mode)."""
        from PySide6.QtCore import QTimer
        self.empty_state.hide()
        self.preview.show()
        self.preview.clear()
        self.preview.setStyleSheet(self._preview_style)
        self.preview.updateGeometry()

        opaque = self._is_game_texture(path)
        if path.lower().endswith('.gif'):
            def _try_gif():
                if self._gif_movie is not None:
                    return
                w = max(self.preview.width(), self.width(), 600)
                if not self._start_gif(path, w):
                    self.preview.setPixmap(_load_pixmap(path, opaque).scaled(
                        *self._preview_box(w),
                        Qt.KeepAspectRatio, Qt.SmoothTransformation))
            QTimer.singleShot(50, _try_gif)
        else:
            def _scale():
                w = max(self.preview.width(), self.width(), 600)
                self.preview.setPixmap(_load_pixmap(path, opaque).scaled(
                    *self._preview_box(w),
                    Qt.KeepAspectRatio, Qt.SmoothTransformation))
            QTimer.singleShot(50, _scale)

    def _clear_preview_label(self) -> None:
        self.preview.clear()
        self.preview.hide()
        self.empty_state.show()
