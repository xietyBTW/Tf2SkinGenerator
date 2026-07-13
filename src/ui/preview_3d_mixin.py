"""
Миксин панели превью: 3D-конвейер загрузки и колбэки готовности сцены.

Содержит методы запуска/остановки фоновых воркеров (обычная 3D-модель,
QC-карточки, мод из пользовательского VPK) и обработчики их сигналов
(``_on_3d_*`` / ``_on_vpk_mod_*``). Вынесены из ``PreviewPanel`` без
изменения тел: всё состояние и вспомогательные методы (карточки, команды,
скины, вариант Australium) остаются на ``PreviewPanel`` и разрешаются через
``self`` при наследовании ``PreviewPanel(Preview3DMixin, QWidget)``.
"""

import os

from src.shared.constants import Team
from src.shared.logging_config import get_logger
from src.ui.material_cards import editable_material_cards

logger = get_logger(__name__)


class Preview3DMixin:
    """3D-воркеры превью и колбэки готовности (см. модуль)."""

    def _on_load_3d_clicked(self) -> None:
        if self._custom_smd_mode:
            self._load_custom_smd_via_dialog()
            return
        if not self._pending_3d_params:
            return
        weapon_key, mode, misc_vpk, textures_vpk = self._pending_3d_params
        self._start_3d_worker(weapon_key, mode, misc_vpk, textures_vpk)

    # ═══════════════════════════════════════════════════════════════════════════
    # Управление воркерами
    # ═══════════════════════════════════════════════════════════════════════════

    def _stop_worker(self, attr: str) -> None:
        """Останавливает воркер по имени атрибута и зануляет его."""
        w = getattr(self, attr, None)
        if w is not None:
            w.stop(3000)  # BaseWorker: requestInterruption + wait
        setattr(self, attr, None)

    def _start_3d_worker(
        self,
        weapon_key: str,
        mode: str,
        misc_vpk: str,
        textures_vpk: str,
    ) -> None:
        if not self._3d_available or not self._3d_widget:
            return
        self._stop_worker('_3d_worker')
        # Новая загрузка модели: сбрасываем флаг авто-обновления 2D (его заново
        # поставит trigger_pending_load при смене стиля шапки).
        self._pending_2d_refresh = False
        # Возврат к ИГРОВОЙ модели: сбрасываем кастомное состояние, иначе
        # селекторы доп-стилей и их текстуры остаются от загруженной ранее
        # кастомной модели. Останавливаем и фоновый детектор стилей, чтобы
        # его поздний колбэк не пересоздал кнопки уже после сброса.
        self._stop_worker('_skin_worker')
        # Признак, что уходим ИМЕННО с кастомной модели (до сброса флагов).
        was_custom = bool(
            self._custom_smd_path or self._custom_keep_materials
            or self._original_skin_info or self._custom_smd_mode
        )
        self._reset_skin_state()
        self._custom_smd_path = None
        self._custom_keep_materials = False
        self._reset_team_vpk_state()
        # Новая модель — сбрасываем «Прочее» (его пересоберёт _on_3d_multi_material).
        self._misc_materials = []
        self._misc_mode = False
        self._main_material_name = None
        if hasattr(self, 'btn_misc'):
            self.btn_misc.setVisible(False)
        self._sync_variant_buttons()
        # Возврат от кастомной модели: сбрасываем её карточки/материалы. Иначе их
        # идентичность (напр. "material") остаётся, и у одно-текстурной игровой
        # модели (где multi_material не приходит) австралий/команда привяжутся к
        # чужой карточке. Для мульти-материальной модели карточки пересоберёт
        # _on_3d_multi_material. На обычной смене оружия (не кастом) не трогаем.
        if was_custom:
            self._set_material_slots([])
        self.btn_load_3d.setEnabled(False)
        self._3d_widget.show_loading(self.t.get('3d_preparing', 'Preparing 3D model...'))

        from src.services.preview_3d_worker import Preview3DWorker
        w = Preview3DWorker(
            weapon_key=weapon_key,
            mode=mode,
            misc_vpk_path=misc_vpk,
            textures_vpk_path=textures_vpk,
            lang=self._lang,
            parent=self,
        )
        w.progress.connect(lambda txt: self._3d_widget and self._3d_widget.show_loading(txt))
        w.ready.connect(self._on_3d_ready)
        w.animated.connect(self._on_3d_animated)
        w.multi_material.connect(self._on_3d_multi_material)
        w.blu_ready.connect(self._on_3d_blu_ready)
        w.blu_multi_material.connect(self._on_3d_blu_multi_material)
        w.australium_ready.connect(self._on_australium_ready)
        w.failed.connect(self._on_3d_failed)
        w.start()
        self._3d_worker = w

    def _start_qc_cards_worker(self) -> None:
        """Извлекает текстуры/карточки из QC игровой модели, НЕ трогая геометрию.

        Режим «No, geometry only»: в 3D остаётся геометрия пользователя, но
        карточки и текстуры берутся из игрового QC ($texturegroup). Сигнал
        ready (геометрия оригинала) НЕ подключаем — вместо него применяем
        главную игровую текстуру глобально к пользовательской модели.
        """
        if not self._3d_available or not self._3d_widget or not self._pending_3d_params:
            return
        weapon_key, mode, misc_vpk, textures_vpk = self._pending_3d_params
        self._stop_worker('_3d_worker')
        self._reset_team_vpk_state()

        from src.services.preview_3d_worker import Preview3DWorker
        w = Preview3DWorker(
            weapon_key=weapon_key,
            mode=mode,
            misc_vpk_path=misc_vpk,
            textures_vpk_path=textures_vpk,
            lang=self._lang,
            parent=self,
        )
        # НЕ подключаем ready → геометрия оригинала не загружается.
        # Главную текстуру применяем глобально к геометрии пользователя.
        w.ready.connect(self._on_qc_cards_ready)
        w.animated.connect(self._on_3d_animated)
        w.multi_material.connect(self._on_3d_multi_material)
        w.blu_ready.connect(self._on_3d_blu_ready)
        w.blu_multi_material.connect(self._on_3d_blu_multi_material)
        w.australium_ready.connect(self._on_australium_ready)
        w.failed.connect(lambda e: (self.btn_load_3d.setEnabled(True),
                                    logger.info(f"[QC CARDS] {e}")))
        w.start()
        self._3d_worker = w

    def _on_qc_cards_ready(self, obj_path: str, texture_path: str) -> None:
        """ready в режиме geometry-only: геометрию НЕ перезагружаем (она
        пользовательская), применяем игровую текстуру глобально."""
        self.btn_load_3d.setEnabled(True)
        if texture_path:
            self._red_frames = [texture_path]
            if self._3d_widget and not self._card_mode:
                # Одно-материальная модель: показываем игровую текстуру глобально.
                self._3d_widget.update_texture_file(texture_path)

    def _start_vpk_mod_worker(self, user_vpk: str) -> None:
        if not self._3d_available or not self._3d_widget:
            return

        misc_vpk, textures_vpk = '', ''
        if self._pending_3d_params and len(self._pending_3d_params) >= 4:
            misc_vpk = self._pending_3d_params[2]
            textures_vpk = self._pending_3d_params[3]
        elif hasattr(self, 'parent') and hasattr(self.parent, 'settings_panel'):
            try:
                from src.services.tf2_paths import TF2Paths
                settings = self.parent.settings_panel.get_settings()
                tf2 = settings.get('tf2_game_folder', '')
                if tf2:
                    _, misc_vpk, _ = TF2Paths.resolve(tf2)
                    textures_vpk = TF2Paths.resolve_textures_vpk(tf2)
            except Exception:
                pass

        self._stop_worker('_3d_worker')
        self._stop_worker('_vpk_mod_worker')
        self._reset_team_vpk_state()
        self._reset_skin_state()   # очищаем skin-бар прошлой модели
        # Входим в режим custom-VPK ПОСЛЕ сброса (reset гасит флаг).
        self._custom_vpk_mode = True

        self.btn_load_vpk.setEnabled(False)
        self.btn_load_3d.setEnabled(False)
        self._3d_widget.show_loading(self.t.get('3d_analyzing_vpk', 'Analyzing VPK mod...'))

        from src.services.preview_vpk_mod_worker import PreviewVpkModWorker
        w = PreviewVpkModWorker(
            user_vpk_path=user_vpk,
            misc_vpk_path=misc_vpk,
            textures_vpk_path=textures_vpk,
            lang=self._lang,
            parent=self,
        )
        w.progress.connect(lambda txt: self._3d_widget and self._3d_widget.show_loading(txt))
        w.ready.connect(self._on_vpk_mod_ready)
        w.animated.connect(self._on_3d_animated)
        w.blu_ready.connect(self._on_3d_blu_ready)
        w.cards_ready.connect(self._on_vpk_mod_cards_ready)
        w.materials_ready.connect(self._on_vpk_mod_materials_ready)
        w.skins_ready.connect(self._on_vpk_mod_skins_ready)
        w.failed.connect(self._on_vpk_mod_failed)
        w.start()
        self._vpk_mod_worker = w

    # ── Коллбэки воркеров ─────────────────────────────────────────────────────

    def _on_3d_ready(self, obj_path: str, texture_path: str) -> None:
        self.btn_load_3d.setEnabled(True)
        self._per_mesh_active = False
        self._per_mesh_base_image = None
        self._active_team = Team.RED   # всегда синхронизируем (кнопки уже сброшены)
        if texture_path:
            self._red_frames = [texture_path]
        # Запоминаем загруженную модель для мини-памяти (мгновенное восстановление)
        _loaded_mode = self._pending_3d_params[1] if self._pending_3d_params else self._weapon_mode
        self._cur_obj = (_loaded_mode, obj_path, texture_path)
        if self._3d_widget:
            self._3d_widget.load_model_files(obj_path, texture_path)
            # Применяем уже загруженную в 2D текстуру к свежей модели — по
            # подтверждению из JS (settle-пауза даёт _on_3d_multi_material
            # выставить _card_mode/_material_names); fallback 400мс — как раньше.
            self._run_after_model_load(
                lambda: self._reapply_textures_to_3d(delay_ms=0), fallback_ms=400)
        # Одно-материальное оружие сюда приходит без _on_3d_multi_material —
        # синхронизируем видимость кнопок (в т.ч. «+ Команда»).
        self._update_team_btn_visibility()
        # Память по стилям шапки: применяем отложенные правки стиля.
        self._apply_pending_edit_state()

    def _on_vpk_mod_ready(self, obj_path: str, texture_path: str) -> None:
        self.btn_load_vpk.setEnabled(True)
        self.btn_load_3d.setEnabled(bool(self._pending_3d_params or self._custom_smd_mode))
        self._active_team = Team.RED   # всегда синхронизируем (кнопки уже сброшены)
        if texture_path:
            self._red_frames = [texture_path]
        if self._3d_widget:
            self._3d_widget.load_model_files(obj_path, texture_path)

    def _on_vpk_mod_cards_ready(self, cards: list) -> None:
        """Показывает 2D-карточки всех текстур загруженного custom-VPK мода.

        Превью существующих текстур регистрируется как «оригинал из мода»
        (в _vpk_red_tex_map, opaque) — в сборку как пользовательская НЕ попадёт,
        поэтому нетронутые карточки сохраняют исходную текстуру мода. Если
        пользователь перетащит своё изображение на карточку, оно ляжет в
        _textures[Team.RED] и сборка подхватит его через get_uploaded_texture_for_mat.
        """
        if not cards:
            return
        names_display = [(c['name'], c.get('display_name') or c['name']) for c in cards]
        self._set_material_slots_with_display(names_display)
        for c in cards:
            png = c.get('preview_png')
            if png and os.path.exists(png):
                self._vpk_red_tex_map[c['name']] = png
                card = self._card_widgets.get(c['name'])
                if card:
                    card.set_image(png, opaque=True)

    def _on_vpk_mod_skins_ready(self, info: dict) -> None:
        """VPK-воркер определил стили модели (skinfamilies). Перестраивает 2D
        под мешевые материалы и поднимает существующий поток стилей (skin-бар +
        «+»). Базовый стиль (0) показывает текстуры мода по мешам; доп. стили
        редактируются через «+», как при замене модели.
        """
        skins = (info or {}).get('skins') or []
        if len(skins) < 2 or not self._custom_model_materials:
            return
        mats = list(self._custom_model_materials)

        # Перекладываем превью мода с ключей-VTF на точные мешевые материалы —
        # чтобы существующие методы стилей (_resolve_base_texture, _apply_skin_to_3d,
        # get_skin_build_data) работали по именам материалов модели.
        mesh_map: dict = {}
        for m in mats:
            p = self._lookup_ci(self._vpk_red_tex_map, m)
            if p and os.path.exists(p):
                mesh_map[m] = p
        self._vpk_red_tex_map = mesh_map

        # Базовые карточки = мешевые материалы (стилевые варианты уходят в skin-бар).
        self._set_material_slots_with_display([(m, m) for m in mats])
        for m, p in mesh_map.items():
            card = self._card_widgets.get(m)
            if card:
                card.set_image(p, opaque=True)

        # Поднимаем существующий UI стилей (skin-бар + «+»).
        self._on_skins_detected(info)

        # Предзаполняем доп. стили УЖЕ существующими текстурами мода — чтобы при
        # переключении стиля карточки показывали то, что в моде, а не пустоту.
        # (_on_skins_detected сбрасывает _skin_overrides/_skin_chosen, поэтому
        # заполняем после него.)
        skin_textures = (info or {}).get('skin_textures') or {}
        for ridx, matmap in skin_textures.items():
            if ridx == 0 or not matmap:
                continue
            chosen = self._skin_chosen.setdefault(ridx, set())
            ov = self._skin_overrides.setdefault(ridx, {})
            for base_mat, png in matmap.items():
                mm = self._custom_material_for_card(base_mat)  # → точный меш-материал
                if png and os.path.exists(png):
                    ov[mm] = png
                    chosen.add(mm)

    def _on_vpk_mod_materials_ready(self, materials: list) -> None:
        """VPK-воркер сообщил имена материалов модели → накладываем текстуры мода
        на правильные меши (с задержкой, чтобы 3D-модель успела загрузиться в JS)."""
        if not materials:
            return
        self._custom_model_materials = list(materials)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(450, self._apply_custom_vpk_textures_to_3d)

    @staticmethod
    def _lookup_ci(d: dict, key: str):
        """Значение по ключу с фолбэком на регистронезависимое совпадение."""
        if key in d:
            return d[key]
        kl = key.lower()
        for k, v in d.items():
            if k.lower() == kl:
                return v
        return None

    def _custom_material_for_card(self, card_name: str) -> str:
        """Точное имя материала модели для карточки (по совпадению без учёта
        регистра). Если совпадения нет — возвращает само имя карточки."""
        cl = card_name.lower()
        for m in self._custom_model_materials:
            if m.lower() == cl:
                return m
        return card_name

    def _apply_custom_vpk_textures_to_3d(self) -> None:
        """Накладывает текстуры мода (и пользовательские правки) на правильные
        меши 3D — по совпадению имени материала модели с именем карточки.

        Пользовательская правка (в _textures[Team.RED]) имеет приоритет над
        оригиналом мода (_vpk_red_tex_map)."""
        if not (self._custom_model_materials and self._3d_widget and self._3d_available):
            return
        user_tex = self._textures.get(Team.RED, {})
        apply: dict = {}
        for m in self._custom_model_materials:
            src = self._lookup_ci(user_tex, m) or self._lookup_ci(self._vpk_red_tex_map, m)
            if src and os.path.exists(src):
                apply[m] = src
        self._apply_3d_delta(apply, delay=120)

    def _apply_3d_delta(self, tex_map: dict, delay: int = 0) -> None:
        """Применяет к 3D только изменившиеся относительно текущего состояния
        текстуры — чтобы не перезагружать в webview всё подряд при переключении
        стилей (это и давало лаги)."""
        if not (self._3d_widget and self._3d_available):
            return
        changed = {m: p for m, p in tex_map.items() if self._applied_3d_tex.get(m) != p}
        self._applied_3d_tex.update(tex_map)
        if not changed:
            return
        from PySide6.QtCore import QTimer
        QTimer.singleShot(delay, lambda m=dict(changed): self._3d_widget.apply_material_map(m))

    def _on_vpk_mod_failed(self, error: str) -> None:
        logger.warning(f"VPK мод Preview: {error}")
        self.btn_load_vpk.setEnabled(True)
        self.btn_load_3d.setEnabled(bool(self._pending_3d_params or self._custom_smd_mode))
        if self._3d_widget:
            self._3d_widget.show_error(
                self.t.get('3d_error_prefix', 'Error: {error}').format(error=error)
            )

    def _on_3d_animated(self, frame_paths: list, framerate: float) -> None:
        """Воркер нашёл многокадровый VTF для RED команды."""
        if frame_paths:
            self._red_frames = frame_paths
            self._team_framerate = framerate
        if self._3d_widget and frame_paths:
            self._3d_widget.update_animated_texture_files(frame_paths, framerate)

    def _on_3d_blu_ready(self, frame_paths: list, framerate: float) -> None:
        """Воркер нашёл BLU текстуру — показываем переключатель команд."""
        if not frame_paths:
            return
        self._blu_frames = frame_paths
        if framerate > 0:
            self._team_framerate = framerate
        # Видимость — единым правилом (для рук учитывает реальный командный материал).
        self._update_team_btn_visibility()


    def _on_3d_blu_multi_material(self, payload) -> None:
        """Воркер нашёл BLU текстуры для многоматериальной модели (персонажи).

        payload — кортеж (tex_map, name_map):
            tex_map:  {red_mat_name: blu_png_path}
            name_map: {red_mat_name: blu_display_name}

        Сохраняем для восстановления 3D при переключении на BLU.
        Не применяем сразу — пользователь пока на RED.
        """
        if not payload:
            return
        if isinstance(payload, tuple) and len(payload) == 2:
            tex_map, name_map = payload
        else:
            tex_map, name_map = payload, {}

        # Маппинг имён обновляем всегда — он нужен для лейблов карточек
        # даже если BLU VTF-текстуры не были найдены в VPK.
        if name_map:
            self._vpk_blu_name_map = dict(name_map)

        if tex_map:
            self._vpk_blu_tex_map = dict(tex_map)

        logger.debug(
            f"[Panel] BLU multi-material: {len(tex_map)} текстур, "
            f"{len(name_map)} имён"
        )
        # Видимость кнопок RED/BLU — единым правилом (для рук учитывает, что
        # командным считается только материал с ОТЛИЧНЫМ синим именем).
        self._update_team_btn_visibility()

    def _on_3d_multi_material(self, tex_map: dict) -> None:
        """Модель многоматериальная — применяем и создаём карточки."""
        if not (self._3d_widget and tex_map):
            return
        # В 3D применяем ВСЕ текстуры (включая глаза/зубы), иначе служебные меши
        # останутся без текстуры.
        self._3d_widget.apply_material_map(tex_map)
        if self._active_team == Team.RED and not self._vpk_red_tex_map:
            self._vpk_red_tex_map = dict(tex_map)

        # Режим масок шпиона: карточки уже выставлены под 9 масок
        # (update_extra_slots_spy_masks). Материалы SMD (mask_spy + тело) НЕ должны
        # их перетирать — иначе в 2D останутся только маска и тело. Текстуры к 3D
        # выше уже применены, на этом выходим.
        if self._spy_mask_mode:
            return

        # Custom-VPK мод: карточки строятся из VTF мода (cards_ready) и НЕ должны
        # перетираться фильтром материалов модели. Здесь же накладываем текстуры
        # мода (и пользовательские правки) на ПРАВИЛЬНЫЕ меши — по совпадению
        # имени материала модели с именем карточки (без учёта регистра).
        if self._custom_vpk_mode:
            self._custom_model_materials = list(tex_map.keys())
            self._apply_custom_vpk_textures_to_3d()
            return

        # КАРТОЧКИ — только для редактируемых материалов (служебные глаза/зубы/
        # sheen отброшены единым правилом в material_cards; пустой результат сам
        # откатывается на «все», чтобы не было пустоты).
        mat_keys = [s.name for s in editable_material_cards(tex_map.keys())]

        # «Прочее»: служебные материалы модели, НЕ попавшие в основные карточки.
        # Пользовательский ЧС скрывает их и отсюда (но в мод они пишутся оригиналом).
        from src.data.material_filter import (
            is_editable_material as _is_ed_misc,
            is_user_blacklisted as _is_hidden_misc,
        )
        _seen_misc: set = set()
        self._misc_materials = []
        for _m in tex_map.keys():
            _ml = (_m or '').lower()
            if (_m and _ml not in _seen_misc and not _is_ed_misc(_m)
                    and not _is_hidden_misc(_m) and _m not in mat_keys):
                _seen_misc.add(_ml)
                self._misc_materials.append(_m)
        self._misc_mode = False
        self._sync_variant_buttons()

        current_all = (
            self._material_names if self._card_mode else []
        )
        if len(mat_keys) > 1:
            if mat_keys != current_all:
                self._set_material_slots(mat_keys)
            self._main_material_name = mat_keys[0]
            self._update_team_btn_visibility()
        elif mat_keys:
            self._material_names = mat_keys
            self._main_material_name = mat_keys[0]
            if self._card_mode:
                self._set_material_slots(mat_keys)
            self._update_team_btn_visibility()


        # Руки: говорим 3D вьюверу какие меши редактируемы
        if self._pending_3d_params:
            mode = self._pending_3d_params[1]
            from src.data.player_hands import HAND_MODES, HAND_MODE_KEYS
            if mode in HAND_MODE_KEYS:
                textures_list = HAND_MODES.get(mode, {}).get("textures", [])
                hand_vtf_lower = {vtf.lower() for (_, vtf) in textures_list}
                _OVERLAY = ("_sheen2", "_sheen", "_overlay", "_fresnel")

                def _is_editable(mat: str) -> bool:
                    m = mat.lower()
                    if m in hand_vtf_lower:
                        return True
                    return any(m.endswith(s) and m[:-len(s)] in hand_vtf_lower for s in _OVERLAY)

                editable = [m for m in tex_map if _is_editable(m)]
                if editable:
                    self._3d_widget.set_editable_mesh_names(editable)
                # Команды рук — через НАТИВНЫЙ цветной переключатель RED/BLU.
                # Видимость по единому правилу: только если есть реальный командный
                # материал (свой синий вариант) — чисто нейтральные руки (scout/spy/
                # heavy) переключателя не получают.
                self._update_team_btn_visibility()

        # Память по стилям шапки: применяем отложенные правки после карточек.
        self._apply_pending_edit_state()

    def _on_3d_failed(self, error: str) -> None:
        logger.warning(f"3D Preview: {error}")
        self.btn_load_3d.setEnabled(True)
        if self._3d_widget:
            self._3d_widget.show_error(
                self.t.get('3d_unavailable', 'Model unavailable: {error}').format(error=error)
            )

    def _on_3d_per_mesh_applied(self) -> None:
        self._per_mesh_active = True
        self._per_mesh_base_image = self.image_path
