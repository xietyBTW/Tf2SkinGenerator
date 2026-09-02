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
from src.domain.preview.material_cards import editable_material_cards

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

    def _connect_preview3d(self) -> None:
        """Подписывает панель на события контроллера загрузки игровой модели.

        Обработчики ниже занимаются ТОЛЬКО показом: состояние сеанса контроллер
        меняет до того, как эмитит событие.
        """
        c = self._preview3d
        c.progress.connect(
            lambda txt: self._3d_widget and self._3d_widget.show_loading(txt))
        c.model_ready.connect(self._on_3d_ready)
        c.animated.connect(self._on_3d_animated)
        c.materials.connect(self._on_3d_multi_material)
        c.blu_ready.connect(self._on_3d_blu_ready)
        c.blu_materials.connect(self._on_3d_blu_multi_material)
        c.blu_same_as_red.connect(self._on_blu_same_as_red)
        c.australium_ready.connect(self._on_australium_ready)
        c.render_hints.connect(self._on_3d_render_hints)
        c.scene_extra.connect(self._on_3d_scene_extra)
        c.failed.connect(self._on_3d_failed)

    def _stop_worker(self, attr: str) -> None:
        """Останавливает воркер по имени атрибута и зануляет его.

        Загрузку обычной игровой модели ведёт контроллер и воркер держит он;
        режим QC-карточек пока кладёт свой на панель. Поэтому под именем
        `_3d_worker` гасятся оба — иначе остановка зависела бы от того, каким
        путём модель загружали.
        """
        if attr == '_3d_worker':
            self._preview3d.stop()
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
        # Останавливаем фоновый детектор стилей, чтобы его поздний колбэк не
        # пересоздал кнопки уже после сброса.
        self._stop_worker('_skin_worker')

        # Что помним — чистит сессия (правила перехода и порядок сбросов там,
        # см. PreviewSession.begin_game_model). Здесь остаётся только то, что
        # рисуем.
        was_custom = self._session.begin_game_model()
        self._clear_skin_buttons()
        self._sync_team_widgets()
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

        self._preview3d.load_game_model(
            weapon_key, mode, misc_vpk, textures_vpk, lang=self._lang)

    # ── Вид от первого лица ──────────────────────────────────────────────── #

    def _start_fp_worker(
        self,
        weapon_key: str,
        mode: str,
        misc_vpk: str,
        textures_vpk: str,
    ) -> None:
        """Собирает сцену «руки класса с оружием» и показывает её в 3D-виджете.

        Модель ставится БЕЗ вписывания в кадр: сцена уже стоит там, где надо
        относительно глаза, и центрирование развалило бы вид.
        """
        if not self._3d_available or not self._3d_widget:
            return
        self._stop_worker('_3d_worker')
        self._stop_worker('_fp_worker')

        from src.data import viewmodel_anims
        from src.services.viewmodel_worker import ViewmodelPreviewWorker

        self.btn_load_3d.setEnabled(False)
        # Копим сцену по кусочкам: сигналы приходят порознь, а в кэш она
        # должна попасть целиком (см. remember_scene).
        self._fp_scene = {'obj_path': '', 'animated': None,
                          'textures': {}, 'editable': []}
        self._3d_widget.show_loading(
            self.t.get('3d_preparing', 'Preparing 3D model...'))

        from src.services.weapon_anim_catalog import Action
        w = ViewmodelPreviewWorker(
            weapon_key=weapon_key,
            misc_vpk_path=misc_vpk,
            textures_vpk_path=textures_vpk,
            tf2_root=self._tf2_root_for_fp(misc_vpk),
            # Класс берём из режима: всеклассовое оружие принадлежит сразу
            # девяти классам, и в руках его надо показать у выбранного.
            tf2_class=viewmodel_anims.class_from_mode(mode),
            action=Action[self._fp_action_name()],
            # Подменённая модель едет в сцену тем же слиянием, что и в мод:
            # иначе в руках оказался бы сток вместо пользовательской геометрии.
            custom_smd_path=self._custom_smd_path or "",
            custom_keep_materials=bool(self._custom_keep_materials),
            # Рукава и перчатки у семи классов командные: на синей стороне
            # оружие красит панель, а руки — воркер, больше их красить некому.
            team=self._active_team,
            lang=self._lang,
            parent=self,
        )
        w.progress.connect(lambda txt: self._3d_widget and self._3d_widget.show_loading(txt))
        w.ready.connect(self._on_fp_ready)
        w.animated_ready.connect(self._on_fp_animated_ready)
        w.actions_available.connect(self._on_fp_actions_available)
        w.editable_materials.connect(self._on_fp_editable_materials)
        w.multi_material.connect(self._on_fp_multi_material)
        w.render_hints.connect(self._on_3d_render_hints)
        w.failed.connect(self._on_fp_failed)
        w.start()
        self._fp_worker = w

    def _start_fp_clip_worker(
        self,
        weapon_key: str,
        mode: str,
        misc_vpk: str,
        textures_vpk: str,
    ) -> None:
        """Догружает ТОЛЬКО дорожки новой анимации к уже показанной сцене.

        Меш, скелет, материалы и текстуры у одного оружия одни и те же, так что
        трогать их при смене анимации незачем.
        """
        if not self._3d_available or not self._3d_widget:
            return
        self._stop_worker('_fp_worker')

        from src.data import viewmodel_anims
        from src.services.viewmodel_worker import ViewmodelPreviewWorker
        from src.services.weapon_anim_catalog import Action

        w = ViewmodelPreviewWorker(
            weapon_key=weapon_key,
            misc_vpk_path=misc_vpk,
            textures_vpk_path=textures_vpk,
            tf2_root=self._tf2_root_for_fp(misc_vpk),
            tf2_class=viewmodel_anims.class_from_mode(mode),
            action=Action[self._fp_action_name()],
            clip_only=True,
            lang=self._lang,
            parent=self,
        )
        w.clip_ready.connect(self._on_fp_clip_ready)
        w.actions_available.connect(self._on_fp_actions_available)
        w.failed.connect(self._on_fp_failed)
        w.start()
        self._fp_worker = w

    def _on_fp_clip_ready(self, clip: dict) -> None:
        """Новая анимация легла на уже собранную сцену."""
        if not self._3d_widget or not clip:
            return
        if not self._3d_widget.set_viewmodel_clip(clip):
            # Сцены на экране почему-то нет — собираем целиком.
            if self._pending_3d_params:
                self._start_fp_worker(*self._pending_3d_params)

    @staticmethod
    def _tf2_root_for_fp(misc_vpk: str) -> str:
        from src.data.weapon_model_index import tf2_root_from_misc_vpk
        return tf2_root_from_misc_vpk(misc_vpk) or ""

    def _on_fp_ready(self, obj_path: str, _texture_path: str) -> None:
        self.btn_load_3d.setEnabled(True)
        if not self._3d_widget:
            return
        self._3d_widget.load_model_files(obj_path, "", normalize=False)
        self._remember_fp_scene(obj_path=obj_path)
        # Материалы оружия в сцене названы так же, как в обычном превью, а
        # пользовательские текстуры хранятся по именам материалов. Значит вид
        # от первого лица обязан показывать ТУ ЖЕ текстуру, что и 3D: без
        # этого переход сбрасывал модель на сток. Порядок — как в _on_3d_ready:
        # по подтверждению из JS, чтобы стоковые текстуры воркера успели лечь
        # первыми и пользовательские легли поверх.
        self._run_after_model_load(
            lambda: self._reapply_textures_to_3d(delay_ms=0), fallback_ms=400)

    def _on_fp_animated_ready(self, scene: dict) -> None:
        """Анимированная сцена: меш один раз, движение — дорожками костей.

        Дальше она ведёт себя как обычная модель: меши названы по материалам,
        поэтому и текстуры, и фильтр редактируемых работают тем же путём.
        """
        self.btn_load_3d.setEnabled(True)
        if not self._3d_widget or not scene:
            return
        self._3d_widget.load_viewmodel_animated(scene)
        self._remember_fp_scene(animated=scene)
        self._run_after_model_load(
            lambda: self._reapply_textures_to_3d(delay_ms=0), fallback_ms=400)

    def _on_fp_editable_materials(self, mat_names: list) -> None:
        """Правится только оружие: руки в сцене стоковые и чужие.

        Без этого пользовательская текстура легла бы и на кисти.
        """
        if self._3d_widget:
            self._3d_widget.set_editable_mesh_names(list(mat_names or []))
        self._remember_fp_scene(editable=list(mat_names or []))

    def _on_3d_scene_extra(self, tex_map: dict, own_names) -> None:
        """Чужая геометрия кадра: красим её, но карточек не заводим.

        Праздничное оружие — гирлянда, надетая на обычную пушку: пушка в кадре
        нужна, иначе огоньки висят в пустоте, но предмету она не принадлежит.

        Имена мешей ПРЕДМЕТА обязательны: одноматериальную текстуру вьювер
        кладёт глобально, и без этого списка пользовательская картинка легла бы
        и на пушку-носитель. Тот же приём, что у рук в виде от первого лица.
        """
        if not self._3d_widget:
            return
        if own_names:
            self._3d_widget.set_editable_mesh_names(list(own_names))
        if tex_map:
            self._3d_widget.apply_material_map(dict(tex_map))

    def _on_fp_multi_material(self, tex_map: dict) -> None:
        if self._3d_widget and tex_map:
            self._3d_widget.apply_material_map(tex_map)
        self._remember_fp_scene(textures=dict(tex_map or {}))

    def _remember_fp_scene(self, **fields) -> None:
        """Копит части сцены и кладёт её в кэш видов.

        Сигналы воркера приходят порознь (модель, материалы, текстуры), а
        запомнить надо целую сцену — иначе при возврате она восстановится
        без текстур.
        """
        scene = getattr(self, '_fp_scene', None)
        if scene is None:
            scene = self._fp_scene = {'obj_path': '', 'animated': None,
                                      'textures': {}, 'editable': []}
        scene.update(fields)
        if scene['obj_path'] or scene['animated']:
            self.remember_scene(scene['obj_path'], scene['textures'],
                                scene['editable'], animated=scene['animated'],
                                action=self._fp_action_name())

    def _on_fp_failed(self, error: str) -> None:
        self.btn_load_3d.setEnabled(True)
        # Сцены нет — предлагать выбор анимации не из чего. Забываем выученное
        # для этого предмета, иначе список остался бы висеть над ошибкой.
        self._fp_actions.pop(self._fp_mode_key(), None)
        self._update_fp_action_combo()
        if self._3d_widget:
            self._3d_widget.show_error(error)

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
        w.blu_same_as_red.connect(self._on_blu_same_as_red)
        w.render_hints.connect(self._on_3d_render_hints)
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
        # Состояние (команда, кадры, _cur_obj, per-mesh) контроллер уже applied
        # — здесь только показ.
        self.btn_load_3d.setEnabled(True)
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
        if self._3d_widget and frame_paths:
            self._3d_widget.update_animated_texture_files(frame_paths, framerate)

    def _on_3d_blu_ready(self, frame_paths: list, framerate: float) -> None:
        """Воркер нашёл BLU текстуру — показываем переключатель команд."""
        if not frame_paths:
            return
        # Видимость — единым правилом (для рук учитывает реальный командный материал).
        self._update_team_btn_visibility()


    def _on_blu_same_as_red(self) -> None:
        """BLU-скин у модели есть, но в стоке он не отличается от RED.

        Переключатель не прячем: своя BLU-текстура собирается и для такой
        модели (сборка пишет отдельный VMT с новым $basetexture). Но подпись
        должна честно говорить, что сейчас команды выглядят одинаково —
        иначе пользователь ищет разницу, которой нет.
        """
        hint = self.t.get('3d_team_blu_same_tip')
        if hint:
            self.btn_blu.setToolTip(hint)

    def _on_3d_blu_multi_material(self, tex_map: dict, name_map: dict) -> None:
        """У многоматериальной модели (персонажи) есть BLU-вариант.

        Текстуры и маппинг имён контроллер уже положил в сессию — здесь только
        видимость кнопок RED/BLU, по единому правилу (для рук командным
        считается лишь материал с ОТЛИЧНЫМ синим именем).

        Сразу не применяем: пользователь пока на RED.
        """
        self._update_team_btn_visibility()

    def _on_3d_render_hints(self, hints: dict) -> None:
        """Свойства рисования материалов (прозрачность, блик) → во вьювер.

        Пустой набор тоже передаём: он сбрасывает свойства прошлой модели.
        """
        if self._3d_widget is not None:
            self._3d_widget.set_material_hints(hints or {})

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
        # Правило в домене — то же множество показывает веб-представление.
        from src.domain.preview.material_cards import misc_material_names
        self._misc_materials = misc_material_names(tex_map.keys(), mat_keys)
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
