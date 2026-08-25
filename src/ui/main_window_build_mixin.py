"""
Миксин главного окна: конвейер сборки VPK.

Валидация входов, разрешение основной текстуры / опций модели / опций
шапки, сбор BuildRequest, запуск сборки и её колбэки прогресса/финиша,
а также интерактивные запросы воркера (доп. текстура/модель, предупреждение
о несовпадении текстур). Вынесены из ``MainWindow`` без изменения тел;
состояние и виджеты остаются на окне и разрешаются через ``self``.
"""

from typing import Optional

from PySide6.QtWidgets import QFileDialog, QMessageBox

from src.shared.logging_config import get_logger
from src.shared.validators import validate_vpk_filename
from src.ui.error_handler import ErrorHandler

logger = get_logger(__name__)


class MainWindowBuildMixin:
    """Конвейер сборки VPK (см. модуль)."""

    def _dispose_build_worker(self) -> None:
        """
        Отключает сигналы и удаляет предыдущий BuildWorker (если был).

        Нужно перед повторной сборкой, иначе старые соединения вызовут
        колбэки повторно. Отключение всех сигналов обёрнуто в try/except —
        безопасно, даже если что-то уже отключено.
        """
        worker = getattr(self, '_build_worker', None)
        if worker is None:
            return
        for sig in (
            'finished', 'progress', 'sub_progress', 'error',
            'request_extra_texture', 'request_extra_model',
            'texture_mismatch_warning',
        ):
            try:
                getattr(worker, sig).disconnect()
            except Exception:
                pass
        # Безопасно завершаем поток ПЕРЕД удалением (иначе Qt: «Destroyed while
        # thread is still running»). На штатном пути воркер уже не выполняется.
        worker.stop()
        worker.deleteLater()
        self._build_worker = None

    # ------------------------------------------------------------------
    # Фазы подготовки сборки (вызываются из build_vpk по порядку)
    # ------------------------------------------------------------------

    def _validate_build_inputs(self, settings: dict) -> Optional[tuple]:
        """Проверяет входные данные сборки (имя, размер, конфликты опций).

        Returns:
            (name, size, format, flags, vtf_options, is_crit_hit) или None,
            если запускать нельзя (предупреждение уже показано).
        """
        name = settings['filename']
        if not name:
            ErrorHandler.show_warning(self, self.t['enter_name'], self.t['error'])
            return None
        is_valid, error_msg = validate_vpk_filename(name)
        if not is_valid:
            ErrorHandler.show_warning(self, error_msg, self.t['error'])
            return None

        size = settings['size']
        # Спрей поддерживает максимум 256×256 — предупреждаем и принудительно уменьшаем
        if self.mode == "spray" and (size[0] > 256 or size[1] > 256):
            if self.language == 'ru':
                msg = (f"Спрей поддерживает максимум 256×256.\n"
                       f"Выбранное разрешение {size[0]}×{size[1]} будет уменьшено до 256×256.\n\n"
                       f"Совет: выберите «256×256 (Спрей)» в разделе Разрешение.")
            else:
                msg = (f"Spray supports a maximum of 256×256.\n"
                       f"The selected resolution {size[0]}×{size[1]} will be downscaled to 256×256.\n\n"
                       f"Tip: select '256×256 (Spray)' in the Resolution section.")
            QMessageBox.warning(self, self.t['error'], msg)
            size = (256, 256)

        # Для critHIT используем настройки пользователя (формат, флаги, опции)
        selected_format = settings['format']
        flags = settings['flags']
        vtf_options = settings.get('vtf_options', {})
        is_crit_hit = (hasattr(self, 'crit_hit_checkbox') and
                       self.crit_hit_checkbox.isChecked())
        if is_crit_hit and vtf_options.get('normal'):
            ErrorHandler.show_warning(
                self,
                self.t.get(
                    'crit_hit_conflict_error',
                    'Дополнительные настройки (Normal Map) конфликтуют с CritHIT. Сборка не запущена.'
                ),
                self.t['error']
            )
            return None
        return name, size, selected_format, flags, vtf_options, is_crit_hit

    def _resolve_main_texture(self) -> Optional[tuple]:
        """Определяет главную текстуру сборки (пользовательская / sentinel).

        Returns:
            (from_path, custom_vtf_path) или None — собирать не из чего
            (предупреждение уже показано).
        """
        from src.data.skyboxes import SKYBOX_MODE as _SKYBOX_MODE
        if self.mode == _SKYBOX_MODE:
            # Скайбокс: «главная текстура» — панорама (может отсутствовать,
            # если пользователь задал все 6 граней вручную).
            data = self.preview_panel.get_skybox_build_data()
            from src.data.skyboxes import SKY_FACES
            if not data['equirect'] and len(data['face_overrides']) < len(SKY_FACES):
                ErrorHandler.show_warning(
                    self,
                    self.t.get('error_skybox_no_input',
                               'Load a panorama or all 6 face textures.'),
                    self.t['error'])
                return None
            return data['equirect'], None

        custom_vtf_path = self.preview_panel.get_vtf_path()
        from_path = None

        if not custom_vtf_path:
            from src.shared.constants import EXTRA_TEX_USE_GAME_ORIGINAL
            from src.data.player_characters import SPY_MASK_MODE_KEY as _SPY_MASK_MODE
            if self.mode == _SPY_MASK_MODE:
                # Маски маскировки: нет «главной» текстуры — все маски через callback.
                # Передаём sentinel как placeholder, vpk_service обработает маски отдельно.
                from_path = EXTRA_TEX_USE_GAME_ORIGINAL
            else:
                # get_red_image_path() не делает fallback на BLU — возвращает
                # None если RED не загружен.
                from_path = self.preview_panel.get_red_image_path()
                # В custom режиме изображение необязательно
                if not from_path and self.mode != "custom":
                    # Главный слот пуст, но мод всё равно можно собрать, если
                    # пользователь загрузил текстуры в другие слоты (доп. карточки,
                    # 3D-дроп на не-главный меш) или BLU-команду. В этом случае
                    # главную текстуру берём оригинальную из игры (sentinel),
                    # а загруженные слоты применяются поверх.
                    has_other_textures = bool(
                        self.preview_panel.get_blu_image_path()
                        or self.preview_panel.get_slot_image_paths()
                    )
                    if has_other_textures:
                        from_path = EXTRA_TEX_USE_GAME_ORIGINAL
                    else:
                        ErrorHandler.show_warning(self, self.t['load_image_error'], self.t['error'])
                        return None
        return from_path, custom_vtf_path

    def _resolve_model_options(self, is_crit_hit: bool) -> Optional[tuple]:
        """Опции замены/готовой модели (+ диалоги выбора файлов).

        Returns:
            (replace_model_enabled, model_ready_enabled,
             replace_model_smd_path, model_ready_path)
            или None — пользователь отменил диалог выбора файла.
        """
        # Читаем опции замены/готовой модели из меню шестерёнки
        replace_model_enabled = (
            hasattr(self, 'settings_panel') and
            self.settings_panel.is_replace_model_checked()
        )
        model_ready_enabled = (
            hasattr(self, 'settings_panel') and
            self.settings_panel.is_model_ready_checked()
        )
        # Кнопка 🔄: если в превью загружена кастомная модель — включаем замену
        # автоматически (без галочки в настройках). Развязывает кнопку и настройки.
        if (not model_ready_enabled and hasattr(self, 'preview_panel')
                and self.preview_panel.get_custom_smd_path()):
            replace_model_enabled = True

        # Замену модели НЕ поддерживаем для тела персонажа (сложный скелет/flex/
        # bodygroups — подмена геометрией ломает модель). Принудительно выключаем.
        from src.data.player_characters import PLAYER_BODY_MODE_KEYS
        if self.mode in PLAYER_BODY_MODE_KEYS and replace_model_enabled:
            logger.info("Замена модели недоступна для тела персонажа — выключаем.")
            replace_model_enabled = False

        # Взаимоисключение с CritHIT — сбрасываем оба флага если активен CritHIT
        if is_crit_hit and (replace_model_enabled or model_ready_enabled):
            logger.warning("CritHIT + model options conflict — resetting model options.")
            if hasattr(self, 'settings_panel'):
                self.settings_panel.reset_build_options(emit=False)
            replace_model_enabled = False
            model_ready_enabled   = False

        # Если "Замена модели" — берём путь к SMD. Сначала пробуем модель,
        # уже загруженную в 3D-превью (чтобы не просить выбрать файл повторно).
        # Если её нет — показываем диалог выбора ДО запуска воркера.
        replace_model_smd_path: Optional[str] = None
        if replace_model_enabled and not model_ready_enabled:
            if hasattr(self, 'preview_panel'):
                replace_model_smd_path = self.preview_panel.get_custom_smd_path()
            if replace_model_smd_path:
                logger.info(f"Замена модели: используем загруженную в превью SMD: {replace_model_smd_path}")
            else:
                smd_file, _ = QFileDialog.getOpenFileName(
                    self,
                    self.t.get(
                        'replace_model_select_title',
                        'Select SMD file for model replacement'
                    ),
                    "",
                    "SMD Files (*.smd);;All Files (*)"
                )
                if not smd_file:
                    return None  # Пользователь отменил
                replace_model_smd_path = smd_file

        # Если "Модель уже готова" — запрашиваем путь к .mdl файлу ДО запуска воркера
        model_ready_path: Optional[str] = None
        if model_ready_enabled:
            mdl_file, _ = QFileDialog.getOpenFileName(
                self,
                self.t.get(
                    'model_ready_select_title',
                    'Select pre-compiled model file (.mdl)'
                ),
                "",
                "Model Files (*.mdl *.smd);;MDL Files (*.mdl);;SMD Files (*.smd);;All Files (*)"
            )
            if not mdl_file:
                return None  # Пользователь отменил
            model_ready_path = mdl_file

        return (replace_model_enabled, model_ready_enabled,
                replace_model_smd_path, model_ready_path)

    def _resolve_hat_options(self) -> tuple:
        """Опции сборки шапки: краски, набор моделей классов, доп. стили.

        Returns:
            (hat_apply_game_paints, hat_mdl_path_for_build,
             hat_class_models, hat_style_builds)
        """
        # Для шапок — спрашиваем, нужны ли краски из игры
        hat_apply_game_paints = True
        if self.mode == "hat":
            paints_title = self.t.get('hat_game_paints_title', 'Game Paints')
            paints_question = self.t.get(
                'hat_game_paints_question',
                'Do you want game paints to apply to your texture?\n\n'
                'If "Yes" — the VMT file will be loaded with original paint settings.\n'
                'If "No" — paints will be disabled, your texture will display without game coloring.'
            )
            reply = QMessageBox.question(
                self,
                paints_title,
                paints_question,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            hat_apply_game_paints = (reply == QMessageBox.Yes)

        # Мультиклассовая шапка: какие классы собирать (выбор в списке шапок).
        # None — обычная шапка (одна общая модель) или не режим шапки.
        hat_class_models = None
        hat_mdl_path_for_build = getattr(self, '_hat_mdl_path', None)
        if self.mode == "hat" and hasattr(self, 'hats_panel'):
            # Полный набор моделей: стили × классы (или только классы / только
            # стили). None — обычная шапка с одной моделью.
            hat_class_models = self.hats_panel.get_selected_models()
            if hat_class_models:
                # Primary-сборка по ПЕРВОЙ модели набора; остальные дособираются
                # в тот же VPK (vpk_service._build_extra_class_hat_models).
                hat_mdl_path_for_build = next(iter(hat_class_models.values()))
                logger.info(
                    f"[HAT build] моделей в наборе: {len(hat_class_models)} "
                    f"({list(hat_class_models.keys())})"
                )

        # Этап 3: доп. ИЗМЕНЁННЫЕ стили-модели (кроме активного — он идёт
        # основным пайплайном). Каждый собирается своей моделью + своей
        # текстурой в ТОТ ЖЕ мод. Источник — пер-стилевая память.
        hat_style_builds = None
        if (self.mode == "hat" and hasattr(self, 'hats_panel')
                and getattr(self, '_hat_style_memory', None)):
            _builds = []
            for _idx, _st in self._hat_style_memory.items():
                if _idx == self._active_hat_style or not _st:
                    continue
                if not self.preview_panel.edit_state_has_content(_st):
                    continue
                _models = self.hats_panel.get_style_models(_idx)
                if not _models:
                    continue
                _builds.append({
                    'mdl_paths': list(_models.values()),
                    'replace_smd': _st.get('custom_smd'),
                    'keep_materials': bool(_st.get('custom_keep')),
                    'image_path': _st.get('image_path'),
                    'vtf_path': _st.get('vtf_path'),
                    # Пер-материальные и командные правки стиля: без них в мод
                    # уходила только главная текстура, а остальные карточки
                    # (и BLU) пользователь терял молча
                    'textures': _st.get('textures') or {},
                })
            hat_style_builds = _builds or None
            if hat_style_builds:
                logger.info(
                    f"[HAT build] доп. изменённых стилей: {len(hat_style_builds)}"
                )

        return (hat_apply_game_paints, hat_mdl_path_for_build,
                hat_class_models, hat_style_builds)

    def _collect_build_request(
        self, *,
        name: str,
        size: tuple,
        format_type: str,
        flags: list,
        vtf_options: dict,
        settings: dict,
        from_path: Optional[str],
        custom_vtf_path: Optional[str],
        replace_model_enabled: bool,
        replace_model_smd_path: Optional[str],
        model_ready_path: Optional[str],
        draw_uv_layout: bool,
        hat_apply_game_paints: bool,
        hat_mdl_path: Optional[str],
        hat_class_models: Optional[dict],
        hat_style_builds: Optional[list],
    ):
        """ЧИСТЫЙ сбор BuildRequest из состояния панелей — без диалогов и
        side-effect'ов, тестируется с заглушкой preview_panel."""
        from src.services.build_request import BuildRequest

        # Если пользователь загрузил BLU-текстуру в 2D панели — используем её
        # автоматически, без лишних вопросов.
        _blu_image = None
        if hasattr(self, 'preview_panel'):
            _blu_image = self.preview_panel.get_blu_image_path()
        _blu_mode = 'upload' if _blu_image else 'none'

        # ── Скайбокс: свои поля; карточки панорамы/граней НЕ должны утекать в
        # panel_extra_textures (это слоты модельного пайплайна).
        from src.data.skyboxes import SKY_ALL_MAPS_KEY, SKYBOX_MODE
        _is_skybox = (self.mode == SKYBOX_MODE)
        _skybox_sky_names = None
        _skybox_face_overrides = None
        if _is_skybox and hasattr(self, 'preview_panel'):
            _sky_data = self.preview_panel.get_skybox_build_data()
            _skybox_face_overrides = _sky_data['face_overrides']
            _sel = getattr(self, '_skybox_sky_name', None) or SKY_ALL_MAPS_KEY
            if _sel == SKY_ALL_MAPS_KEY:
                from src.services.skybox_service import SkyboxService
                _skybox_sky_names = SkyboxService.enumerate_sky_names(
                    settings.get('tf2_game_folder', ''))
            else:
                _skybox_sky_names = [_sel]

        # Собираем все загруженные пользователем текстуры из 2D карточек.
        # Некоторые материалы (c_arrow, sniper_lens и т.п.) есть в 3D модели
        # но НЕ в QC skinfamilies → extra_texture_callback их не покрывает.
        # Передаём эти текстуры напрямую чтобы они попали в VPK.
        _panel_extra_textures: dict = {}
        if not _is_skybox and hasattr(self, 'preview_panel'):
            _panel_extra_textures = dict(
                self.preview_panel.get_slot_image_paths()
            )
            # Убираем главную текстуру (col 0) — она уже в from_path.
            # get_main_material() даёт стабильный главный материал даже когда в
            # 2D открыт просмотр «Прочее» (там _material_names временно служебные).
            main_key = (
                self.preview_panel.get_main_material()
                if hasattr(self.preview_panel, 'get_main_material')
                else (self.preview_panel._material_names[0]
                      if self.preview_panel._material_names else None)
            )
            if main_key and main_key in _panel_extra_textures:
                _panel_extra_textures.pop(main_key)

        # Стили (skinfamilies) кастомной модели: пользователь определил
        # доп-стили в полосе стилей → генерируем $texturegroup и варианты.
        # None, если стилей нет (обычная одно-скиновая сборка).
        _skin_build_data = None
        _replace_keep_materials = False
        if replace_model_enabled and hasattr(self, 'preview_panel'):
            _skin_build_data = self.preview_panel.get_skin_build_data()
            if _skin_build_data:
                logger.info(
                    f"[SKIN BUILD] стили: {_skin_build_data['tg_overrides']}"
                )
            # «Готовая» модель со своими материалами → не схлопывать в один.
            if hasattr(self.preview_panel, 'get_custom_keep_materials'):
                _replace_keep_materials = self.preview_panel.get_custom_keep_materials()

        # Отредактированный пользователем QC (только для «готовой» модели).
        _custom_qc_text = None
        if _replace_keep_materials and hasattr(self, 'preview_panel') \
                and hasattr(self.preview_panel, 'get_custom_qc_text'):
            _custom_qc_text = self.preview_panel.get_custom_qc_text()

        return BuildRequest(
            image_path=from_path,
            mode=self.mode,
            filename=name,
            size=size,
            format_type=format_type,
            flags=flags,
            vtf_options=vtf_options,
            tf2_root_dir=settings.get('tf2_game_folder', ''),
            export_folder=settings.get('export_folder', 'export'),
            keep_temp_on_error=settings.get('keep_temp_on_error', False),
            debug_mode=settings.get('debug_mode', False),
            replace_model_enabled=replace_model_enabled,
            replace_model_path=replace_model_smd_path,
            model_ready_path=model_ready_path,
            draw_uv_layout=draw_uv_layout,
            language=self.language,
            custom_vtf_path=custom_vtf_path,
            blu_mode=_blu_mode,
            blu_image_path=_blu_image,
            custom_vpk_source_path=getattr(self, '_custom_vpk_path', None),
            hat_mdl_path=hat_mdl_path,
            hat_apply_game_paints=hat_apply_game_paints,
            hat_class_models=hat_class_models,
            hat_style_builds=hat_style_builds,
            panel_extra_textures=_panel_extra_textures,
            material_maps=(self.preview_panel.get_texture_maps()
                           if hasattr(self, 'preview_panel') else {}),
            material_settings=(self.preview_panel.get_texture_overrides()
                               if hasattr(self, 'preview_panel') else {}),
            skin_build_data=_skin_build_data,
            replace_keep_materials=_replace_keep_materials,
            custom_qc_text=_custom_qc_text,
            isolate_shoulders=(
                self.settings_panel.is_isolate_shoulders_checked()
                if hasattr(self, 'settings_panel') else False
            ),
            panel_blu_textures=(
                self.preview_panel.get_blu_slot_image_paths()
                if hasattr(self, 'preview_panel') else None
            ),
            force_team=(
                self.preview_panel.get_force_team()
                if hasattr(self, 'preview_panel') else False
            ),
            bypass_method=settings.get('bypass_method', 'console'),
            skybox_sky_names=_skybox_sky_names,
            skybox_face_overrides=_skybox_face_overrides,
        )

    def build_vpk(self):
        """Запускает асинхронную сборку VPK"""
        try:
            if not hasattr(self, 'mode') or not self.mode:
                ErrorHandler.show_warning(self, self.t['select_weapon_error'], self.t['error'])
                return
                
            settings = self.settings_panel.get_settings()
            inputs = self._validate_build_inputs(settings)
            if inputs is None:
                return
            name, size, selected_format, flags, vtf_options, is_crit_hit = inputs
            draw_uv_layout = False

            tex = self._resolve_main_texture()
            if tex is None:
                return
            from_path, custom_vtf_path = tex

            model_opts = self._resolve_model_options(is_crit_hit)
            if model_opts is None:
                return  # пользователь отменил диалог выбора файла
            (replace_model_enabled, model_ready_enabled,
             replace_model_smd_path, model_ready_path) = model_opts

            (hat_apply_game_paints, hat_mdl_path_for_build,
             hat_class_models, hat_style_builds) = self._resolve_hat_options()

            # Сбрасываем запомненный выбор «применить ко всем» — каждая новая
            # сборка начинается без предыдущих предпочтений пользователя.
            self._extra_texture_apply_all: Optional[str] = None

            # Проверяем, не запущена ли уже сборка
            if self._worker_busy('_build_worker', 'build_already_running',
                                 'Build is already in progress. Please wait.'):
                return
            
            # Очищаем старый воркер: отключаем сигналы и удаляем
            self._dispose_build_worker()

            # Создаем и запускаем воркер для асинхронной сборки
            from src.services.build_worker import BuildWorker

            _request = self._collect_build_request(
                name=name,
                size=size,
                format_type=selected_format,
                flags=flags,
                vtf_options=vtf_options,
                settings=settings,
                from_path=from_path,
                custom_vtf_path=custom_vtf_path,
                replace_model_enabled=replace_model_enabled,
                replace_model_smd_path=replace_model_smd_path,
                model_ready_path=model_ready_path,
                draw_uv_layout=draw_uv_layout,
                hat_apply_game_paints=hat_apply_game_paints,
                hat_mdl_path=hat_mdl_path_for_build,
                hat_class_models=hat_class_models,
                hat_style_builds=hat_style_builds,
            )
            # Без parent=self ! Если дать parent=self, Qt станет владельцем
            # и не удалит старый воркер при замене, и сигналы будут дублироваться.
            self._build_worker = BuildWorker(request=_request)
            
            # Подключаем сигналы
            self._build_worker.finished.connect(self._on_build_finished)
            self._build_worker.progress.connect(self._on_build_progress)
            self._build_worker.sub_progress.connect(self._on_build_sub_progress)
            self._build_worker.error.connect(self._on_build_error)
            self._build_worker.request_extra_texture.connect(self._on_request_extra_texture)
            # Запрос доп. частей модели (shell, scope и т.п.) остаётся через callback
            if replace_model_enabled and not model_ready_path:
                self._build_worker.request_extra_model.connect(self._on_request_extra_model)
            # Предупреждение о несовпадении текстур в SMD (режим «Модель уже готова»)
            if model_ready_enabled:
                self._build_worker.texture_mismatch_warning.connect(self._on_texture_mismatch_warning)
            
            # Создаём диалог, запускаем воркер, показываем, блокируем кнопку
            self._launch_progress(
                '_progress_dialog', self._build_worker, self._cancel_build,
                disable_button='button',
            )

        except Exception as e:
            ErrorHandler.show_error(self, e, self.t.get('build_error', 'Build error'), language=self.language)
    
    def _on_build_finished(self, success: bool, message: str):
        """Обработчик завершения сборки"""
        self._close_progress('_progress_dialog', 'button')
        if success:
            success_title = self.t.get('build_success', 'Success')
            ErrorHandler.show_info(self, message, success_title)
        else:
            ErrorHandler.show_error(self, Exception(message), self.t.get('build_error', 'Build error'), language=self.language)
    
    def _on_build_progress(self, percentage: int, status: str):
        """Обработчик прогресса сборки"""
        self._update_progress('_progress_dialog', percentage, status)

    def _on_build_sub_progress(self, percentage: int, label: str):
        """Обработчик детального прогресса текущего шага сборки"""
        if hasattr(self, '_progress_dialog') and self._progress_dialog:
            self._progress_dialog.set_sub_progress(percentage, label)

    def _on_build_error(self, error_message: str):
        """Обработчик ошибки сборки"""
        self._close_progress('_progress_dialog', 'button')
        ErrorHandler.show_error(self, Exception(error_message), self.t.get('build_error', 'Build error'), language=self.language)
    
    def _cancel_build(self) -> None:
        """Отменяет сборку"""
        self._cancel_worker('_build_worker', '_progress_dialog')
    
    def _ask_extra_texture_choice(self, parent, display_name: str, weapon_key: str):
        """
        Показывает диалог выбора текстуры доп. материала (своя / из игры / основная).

        Returns:
            (choice, apply_to_all): choice ∈ {'custom','game','main'},
            apply_to_all — была ли отмечена галочка «применить ко всем».
        """
        from PySide6.QtWidgets import QMessageBox, QCheckBox as _QCheckBox
        from src.data.player_characters import PLAYER_BODY_MODE_KEYS
        is_ru = (getattr(self, 'language', 'en') == 'ru')

        if weapon_key in PLAYER_BODY_MODE_KEYS:
            msg_text = self.t.get(
                'extra_player_texture_question',
                'Apply your skin to the "{material}" texture as well?\n\n'
                'If you click "No", the main texture will be copied for this slot.'
            ).format(material=display_name)
        else:
            msg_text = self.t.get(
                'extra_texture_question',
                'The weapon model has an additional material: "{material}".\n'
                'Do you want to provide a separate image for it?\n\n'
                'If you click "No", the main texture will be used for this material.'
            ).format(material=display_name)

        msg_box = QMessageBox(parent)
        msg_box.setWindowTitle(self.t.get('extra_texture_title', 'Additional Texture'))
        msg_box.setText(msg_text)
        msg_box.setIcon(QMessageBox.Question)

        btn_custom = msg_box.addButton(
            self.t.get('extra_tex_btn_upload', 'Загрузить свою' if is_ru else 'Upload mine'),
            QMessageBox.AcceptRole,
        )
        btn_game = msg_box.addButton(
            self.t.get('extra_tex_btn_game', 'Использовать обычную' if is_ru else 'Use game original'),
            QMessageBox.ActionRole,
        )
        btn_main = msg_box.addButton(
            self.t.get('extra_tex_btn_main', 'Использовать основную' if is_ru else 'Use main texture'),
            QMessageBox.RejectRole,
        )
        msg_box.setDefaultButton(btn_main)

        apply_all_cb = _QCheckBox(
            self.t.get('extra_tex_apply_all', 'Применить ко всем оставшимся' if is_ru else 'Apply to all remaining')
        )
        msg_box.setCheckBox(apply_all_cb)
        msg_box.exec()

        clicked = msg_box.clickedButton()
        if clicked is btn_custom:
            choice = 'custom'
        elif clicked is btn_game:
            choice = 'game'
        else:
            choice = 'main'
        return choice, apply_all_cb.isChecked()

    def _on_request_extra_texture(self, material_name: str, weapon_key: str) -> None:
        """
        Обрабатывает запрос дополнительного изображения для материала модели.

        Сначала проверяет, загружено ли уже изображение для этого слота через
        карточку доп. слота в 2D превью (drag-drop или Browse). Если да — использует его
        без диалога. Иначе — показывает диалог с тремя вариантами:
          • «Загрузить свою» — выбрать файл изображения
          • «Использовать обычную» — взять текстуру прямо из игры (не добавлять в мод)
          • «Использовать основную» — скопировать основную текстуру для этого слота

        Галочка «Применить ко всем» запоминает выбор и применяет его ко всем
        последующим вопросам без повторных диалогов.
        """
        if not hasattr(self, '_build_worker'):
            return

        from src.shared.constants import EXTRA_TEX_USE_GAME_ORIGINAL

        # ── Проверяем уже загруженную текстуру из 2D-карточек ────────────────
        # get_uploaded_texture_for_mat проверяет оба словаря (_textures['red'] и
        # _textures['blu']) и делает обратный поиск через _vpk_blu_name_map для
        # случая когда build спрашивает BLU-имя ('medic_head_blue'), а карточка
        # хранит под RED-ключом ('medic_head_red') в _textures['blu'].
        pre_loaded: Optional[str] = None
        if hasattr(self, 'preview_panel'):
            pre_loaded = self.preview_panel.get_uploaded_texture_for_mat(material_name)
            if pre_loaded:
                logger.info(
                    f"extra_texture: уже загружена '{material_name}': {pre_loaded}"
                )

        if pre_loaded:
            if hasattr(self._build_worker, 'set_extra_texture_result'):
                self._build_worker.set_extra_texture_result(pre_loaded)
            return

        # ── Диалог должен появляться поверх окна прогресса ───────────────────
        _dialog_parent = (
            self._progress_dialog
            if hasattr(self, '_progress_dialog') and self._progress_dialog
            else self
        )

        # ── Человекочитаемое имя материала ────────────────────────────────────
        display_name = material_name

        # ── Apply-to-all: если уже есть запомненный выбор — применяем сразу ──
        _apply_all = getattr(self, '_extra_texture_apply_all', None)
        if _apply_all == 'game':
            logger.info(f"Apply-to-all (game): пропускаем '{material_name}'")
            if hasattr(self._build_worker, 'set_extra_texture_result'):
                self._build_worker.set_extra_texture_result(EXTRA_TEX_USE_GAME_ORIGINAL)
            return
        elif _apply_all == 'main':
            logger.info(f"Apply-to-all (main): '{material_name}' → основная текстура")
            if hasattr(self._build_worker, 'set_extra_texture_result'):
                self._build_worker.set_extra_texture_result(None)
            return
        elif _apply_all == 'custom':
            # Пропускаем вопрос — сразу открываем файловый диалог
            logger.info(f"Apply-to-all (custom): сразу выбираем файл для '{material_name}'")
            file_path = self._pick_extra_texture_file(_dialog_parent, display_name)
            if hasattr(self._build_worker, 'set_extra_texture_result'):
                self._build_worker.set_extra_texture_result(file_path)
            return

        # ── Спрашиваем пользователя через диалог ─────────────────────────────
        choice, apply_to_all = self._ask_extra_texture_choice(_dialog_parent, display_name, weapon_key)

        if apply_to_all:
            self._extra_texture_apply_all = choice
            logger.info(f"Apply-to-all установлен: '{choice}'")

        # ── Выполняем выбранное действие ──────────────────────────────────────
        if choice == 'custom':
            file_path = self._pick_extra_texture_file(_dialog_parent, display_name)
        elif choice == 'game':
            file_path = EXTRA_TEX_USE_GAME_ORIGINAL
        else:
            file_path = None

        if hasattr(self._build_worker, 'set_extra_texture_result'):
            self._build_worker.set_extra_texture_result(file_path)

    def _pick_extra_texture_file(self, parent, display_name: str) -> Optional[str]:
        """Открывает диалог выбора файла изображения для дополнительной текстуры."""
        dialog_title = self.t.get(
            'extra_texture_select',
            'Select image for "{material}"'
        ).format(material=display_name)

        file_path, _ = QFileDialog.getOpenFileName(
            parent,
            dialog_title,
            "",
            self.t.get('images_filter', 'Images') + " (*.png *.jpg *.jpeg *.bmp *.gif *.tga *.vtf);;All Files (*)"
        )
        return file_path if file_path else None

    def _on_request_extra_model(self, smd_name: str, weapon_key: str) -> None:
        """
        Обрабатывает запрос дополнительного SMD файла для части модели.
        Показывает диалог: хочет ли пользователь загрузить отдельную модель
        для дополнительной части (shell, scope и т.д.)
        """
        if not hasattr(self, '_build_worker'):
            return
        
        from PySide6.QtWidgets import QMessageBox
        
        msg_title = self.t.get('extra_model_title', 'Additional Model Part')
        msg_text = self.t.get(
            'extra_model_question',
            'The weapon has an additional model part: "{smd_name}".\n'
            'Do you want to provide a replacement SMD file for it?\n\n'
            'If you click "No", the original game model will be used for this part.'
        ).format(smd_name=smd_name)
        
        reply = QMessageBox.question(
            self,
            msg_title,
            msg_text,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        file_path = None
        if reply == QMessageBox.Yes:
            dialog_title = self.t.get(
                'extra_model_select',
                'Select SMD file for "{smd_name}"'
            ).format(smd_name=smd_name)
            
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                dialog_title,
                "",
                "SMD Files (*.smd);;All Files (*)"
            )
            if not file_path:
                file_path = None
        
        if hasattr(self._build_worker, 'set_extra_model_result'):
            self._build_worker.set_extra_model_result(file_path)

    def _on_texture_mismatch_warning(self, warning_message: str) -> None:
        """
        Обрабатывает предупреждение о несовпадении текстур в пользовательском SMD.
        Показывает диалог с подробностями, позволяет продолжить или отменить сборку.
        """
        if not hasattr(self, '_build_worker'):
            return

        from PySide6.QtWidgets import QMessageBox

        title = self.t.get('texture_mismatch_title', 'Texture Mismatch Warning')

        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Warning)
        msg_box.setWindowTitle(title)
        msg_box.setText(warning_message)

        btn_continue = msg_box.addButton(
            self.t.get('texture_mismatch_continue', 'Continue anyway'),
            QMessageBox.AcceptRole
        )
        btn_cancel = msg_box.addButton(
            self.t.get('texture_mismatch_cancel', 'Cancel build'),
            QMessageBox.RejectRole
        )
        msg_box.setDefaultButton(btn_cancel)
        msg_box.exec()

        decision = 'continue' if msg_box.clickedButton() == btn_continue else 'cancel'

        if hasattr(self._build_worker, 'set_texture_mismatch_result'):
            self._build_worker.set_texture_mismatch_result(decision)
