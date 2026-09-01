"""
Миксин панели превью: режим «Скайбокс».

Вход в режим (set_skybox_mode) останавливает модельные воркеры, извлекает
стоковые грани выбранного неба из VPK игры (SkyboxFacesWorker) и показывает
скайбокс фоном 3D-сцены. Пользовательские грани/панорама разрешаются через
PreviewTextureState.resolve_skybox_face (своя → нарезка панорамы → стоковая).

2D-карточки: панорама (SKY_PANO_KEY) + 6 граней. Загрузка панорамы режет её
на грани в фоне (SkyboxSplitWorker); нарезанные/стоковые грани показываются
в карточках как «игровые» (opaque, в сборку не идут), свои — как обычные.
"""

import os

from src.data.skyboxes import (
    SKY_FACE_LABELS, SKY_FACES, SKY_PANO_KEY, SKY_PREVIEW_DEFAULT,
)
from src.shared.constants import Team
from src.shared.logging_config import get_logger
from src.domain.preview.mode import PreviewMode

logger = get_logger(__name__)


class PreviewSkyboxMixin:
    """Режим «Скайбокс» (см. модуль)."""

    def set_skybox_mode(self, sky_name: str,
                        textures_vpk: str = '', misc_vpk: str = '') -> None:
        """Включает режим скайбокса для выбранного неба.

        sky_name — конкретное стоковое небо (для «Все карты» вызывающий код
        передаёт SKY_PREVIEW_DEFAULT). Без путей к VPK стоковые грани не
        извлекаются — превью появится после загрузки панорамы/граней.
        """
        # Снимок уходящего оружия — как у крита: переход идёт мимо set_3d_params.
        snap = self._snapshot_outgoing(self._weapon_mode)
        if snap:
            self._mem_mode = snap['mode']
            self._mem_data = snap

        # Текстуры оружия не должны протекать в скайбокс-сцену.
        self.image_path = None
        self.vtf_path = None
        self._cur_obj = None

        prev_sky = getattr(self, '_skybox_sky', None)
        self._skybox_sky = sky_name or SKY_PREVIEW_DEFAULT

        self._pstate.enter(PreviewMode.SKYBOX)
        self._sync_spy_mask_buttons()
        self._pending_3d_params = None
        self._last_3d_params = None
        self._stop_worker('_3d_worker')
        self._stop_worker('_vpk_mod_worker')
        self._stop_worker('_skybox_worker')
        self._reset_team_vpk_state()
        self._update_3d_buttons_visibility()

        # Смена неба меняет только стоковые грани; загрузки пользователя
        # (панорама/грани в textures) переживают переключение неба.
        if prev_sky != self._skybox_sky:
            self._state.skybox_stock_faces = {}

        if self._3d_widget:
            # Убираем модель прошлого режима из сцены: при <6 граней рендер
            # покажет только промпт, и оружие «просвечивало» бы за ним.
            self._3d_widget.reset()

        vpk_paths = [p for p in (textures_vpk, misc_vpk) if p]
        if vpk_paths and not self._state.skybox_stock_faces:
            from src.services.skybox_preview_worker import SkyboxFacesWorker
            if self._3d_widget:
                if self.is_3d_mode():
                    self._3d_widget.show_loading(
                        self.t.get('skybox_loading_stock', 'Загрузка неба...'))
                else:
                    self._3d_widget.show_prompt(self.t.get(
                        '3d_prompt_skybox',
                        'Switch to 3D tab — the skybox will appear automatically'))
            worker = SkyboxFacesWorker(self._skybox_sky, vpk_paths, parent=self)
            worker.ready.connect(self._on_stock_sky_faces)
            worker.failed.connect(
                lambda msg: logger.debug(f"[SKYBOX] стоковые грани: {msg}"))
            self._skybox_worker = worker
            worker.start()
        else:
            self._render_skybox_scene()

    def _on_stock_sky_faces(self, faces: dict) -> None:
        """Стоковые грани готовы → сохранить в состояние и перерисовать."""
        # Guard: режим мог смениться, а queued-сигнал остановленного воркера —
        # доехать уже после старта нового (у другого неба).
        if not self._pstate.is_skybox:
            return
        if self.sender() is not getattr(self, '_skybox_worker', None):
            return
        self._state.skybox_stock_faces = dict(faces or {})
        self._refresh_skybox_cards()
        self._render_skybox_scene()

    # ── 2D-карточки: панорама + 6 граней ─────────────────────────────────── #

    def update_extra_slots_skybox(self) -> None:
        """Строит карточки режима скайбокса: панорама + 6 граней."""
        weapon_key = '__skybox__'
        mode = 'skybox'
        if weapon_key == self._weapon_key and mode == self._weapon_mode:
            # Карточки уже стоят (смена неба) — обновляем только превью граней.
            self._refresh_skybox_cards()
            return

        self._begin_new_weapon(weapon_key, mode)

        lang = self._lang if self._lang in ('ru', 'en') else 'en'
        specs = [(SKY_PANO_KEY, self.t.get('skybox_pano', 'Панорама'))]
        specs += [(face, SKY_FACE_LABELS[face][lang]) for face in SKY_FACES]
        self._set_material_slots_with_display(specs)
        self._refresh_skybox_cards()

    def _refresh_skybox_cards(self) -> None:
        """Синхронизирует картинки карточек граней с состоянием.

        Своя текстура — обычное превью; нарезка из панорамы / стоковая грань —
        opaque («игровая», в сборку не идёт). Приоритет = resolve_skybox_face.
        """
        if not (self._pstate.is_skybox and self._card_widgets):
            return
        user_tex = self._state.textures.get(Team.RED, {})
        for face in SKY_FACES:
            card = self._card_widgets.get(face)
            if card is None:
                continue
            user = user_tex.get(face)
            if user and os.path.exists(user):
                card.set_image(user, opaque=False)
                continue
            derived = self._state.resolve_skybox_face(face)
            # Пустой путь → плейсхолдер (у карточки нет отдельного clear).
            card.set_image(derived or '', opaque=True)

    def _on_skybox_card_changed(self, key: str, path: str) -> None:
        """Пользователь сменил/сбросил текстуру в карточке скайбокса."""
        if key == SKY_PANO_KEY:
            self._state.set_texture(SKY_PANO_KEY, path or None)
            self._state.skybox_split_faces = {}
            # Срезы прошлой панорамы в карточках уже неактуальны.
            self._refresh_skybox_cards()
            if path:
                self._start_skybox_split(path)
            else:
                self._stop_worker('_skybox_split_worker')
                self._render_skybox_scene()
            return

        self._state.set_texture(key, path or None)
        self._refresh_skybox_cards()
        self._render_skybox_scene()

    def _start_skybox_split(self, pano_path: str) -> None:
        """Запускает фоновую нарезку панорамы на грани (для превью)."""
        from src.services.skybox_preview_worker import SkyboxSplitWorker
        self._stop_worker('_skybox_split_worker')
        if self._3d_widget:
            self._3d_widget.show_loading(
                self.t.get('skybox_splitting', 'Нарезка панорамы...'))
        worker = SkyboxSplitWorker(pano_path, parent=self)
        worker.ready.connect(self._on_skybox_split_ready)
        worker.failed.connect(self._on_skybox_split_failed)
        self._skybox_split_worker = worker
        worker.start()

    def _on_skybox_split_ready(self, faces: dict) -> None:
        # Guard: queued-сигнал остановленного воркера (старой панорамы) мог
        # доехать после старта новой нарезки — не перетираем свежие грани.
        if not self._pstate.is_skybox:
            return
        if self.sender() is not getattr(self, '_skybox_split_worker', None):
            return
        self._state.skybox_split_faces = dict(faces or {})
        self._refresh_skybox_cards()
        self._render_skybox_scene()

    def _on_skybox_split_failed(self, msg: str) -> None:
        if not self._pstate.is_skybox:
            return
        if self.sender() is not getattr(self, '_skybox_split_worker', None):
            return
        logger.warning(f"[SKYBOX] нарезка панорамы не удалась: {msg}")
        if self._3d_widget:
            self._3d_widget.show_error(
                self.t.get('skybox_split_error', 'Не удалось нарезать панораму'))

    def _render_skybox_scene(self) -> None:
        """Показывает текущий скайбокс (резолв граней из состояния) в 3D."""
        if not (self._pstate.is_skybox and self._3d_widget and self._3d_available):
            return
        if not self.is_3d_mode():
            # Рендер отложен до переключения в 3D (_switch_to_3d) — оставляем
            # осмысленный промпт вместо «выберите оружие» после reset().
            self._3d_widget.show_prompt(
                self.t.get('3d_prompt_skybox',
                           'Switch to 3D tab — the skybox will appear automatically'))
            return
        resolved = {}
        for face in SKY_FACES:
            p = self._state.resolve_skybox_face(face)
            if p:
                resolved[face] = p
        if len(resolved) == len(SKY_FACES):
            self._3d_widget.load_skybox(resolved)
        else:
            self._3d_widget.show_prompt(
                self.t.get('3d_prompt_skybox_empty',
                           'Load a panorama or face textures to preview the skybox')
            )

    def get_skybox_build_data(self) -> dict:
        """Данные скайбокса для сборки: {'equirect', 'face_overrides'}
        (см. PreviewTextureState.skybox_build_data)."""
        return self._state.skybox_build_data()

    def _exit_skybox_mode(self) -> None:
        """Общий выход из режима скайбокса (вызывается reset-путями панели)."""
        self._stop_worker('_skybox_worker')
        self._stop_worker('_skybox_split_worker')
        self._state.reset_skybox()
        if self._3d_widget:
            self._3d_widget.clear_skybox()
