"""
Миксин главного окна: извлечение оригиналов и объединение VPK.

Извлечение оригинальной модели/текстуры из игры, экспорт файлов модели,
генерация UV-шаблона и объединение VPK — запуск воркеров и их колбэки
прогресса/финиша/ошибки/отмены. Вынесены из ``MainWindow`` без изменения
тел; состояние и виджеты остаются на окне и разрешаются через ``self``.
"""

from typing import Optional

from PySide6.QtWidgets import QDialog, QMessageBox

from src.data.weapons import weapon_key_from_mode
from src.shared.logging_config import get_logger
from src.shared.validators import validate_vpk_filename
from src.ui.error_handler import ErrorHandler

logger = get_logger(__name__)


class MainWindowExtractMixin:
    """Извлечение оригиналов и объединение VPK (см. модуль)."""

    def _resolve_extractable_weapon_key(self):
        """
        Резолвит weapon_key для извлечения модели / генерации UV (с показом
        предупреждений). Возвращает строку или None, если режим не подходит.
        """
        if not hasattr(self, 'mode') or not self.mode:
            ErrorHandler.show_warning(self, self.t['select_weapon_error'], self.t['error'])
            return None

        from src.data.weapons import SPECIAL_MODES
        if self.mode in SPECIAL_MODES:
            error_msg = self.t.get('extract_model_special_mode_error', 'Cannot extract model for special modes')
            ErrorHandler.show_warning(self, error_msg, self.t['error'])
            return None

        # Для режимов рук weapon_key — это ключ arm-модели (например "c_pyro_arms"),
        # для скинов персонажа — это ключ MDL модели (например "player_scout").
        from src.data.player_hands import HAND_MODE_KEYS, HAND_MODES
        from src.data.player_characters import PLAYER_BODY_MODE_KEYS, PLAYER_CHARACTERS
        if self.mode in HAND_MODE_KEYS:
            weapon_key = HAND_MODES[self.mode].get("arm_model", "")
            if not weapon_key:
                ErrorHandler.show_warning(self, self.t.get('extract_model_special_mode_error', 'Cannot extract model for this mode'), self.t['error'])
                return None
        elif self.mode in PLAYER_BODY_MODE_KEYS:
            # Для персонажей weapon_key = полный MDL путь (как в 3D preview)
            weapon_key = PLAYER_CHARACTERS[self.mode].get("mdl_path", "")
            if not weapon_key:
                ErrorHandler.show_warning(self, self.t.get('extract_model_special_mode_error', 'Cannot extract model for this mode'), self.t['error'])
                return None
        elif self.mode == "hat":
            weapon_key = getattr(self, '_hat_mdl_path', None)
            if not weapon_key:
                ErrorHandler.show_warning(self, self.t.get('select_weapon_error', 'Select a hat first'), self.t['error'])
                return None
        else:
            weapon_key = weapon_key_from_mode(self.mode)
        return weapon_key

    def extract_original_model(self) -> None:
        try:
            weapon_key = self._resolve_extractable_weapon_key()
            if not weapon_key:
                return

            settings = self.settings_panel.get_settings()
            tf2_root_dir = settings.get('tf2_game_folder', '')
            if not tf2_root_dir:
                error_msg = self.t.get('tf2_path_not_specified', 'TF2 path not specified in settings')
                ErrorHandler.show_warning(self, error_msg, self.t['error'])
                return

            export_folder = settings.get('export_folder', 'export')

            if self._worker_busy('_extract_model_worker', 'extract_model_already_running',
                                 'Model extraction is already in progress. Please wait.'):
                return

            from src.services.extract_model_worker import ExtractModelWorker

            # Мультиклассовая шапка → экспортируем модели ВСЕХ классов, а не только
            # первого найденного.
            hat_class_models = None
            if self.mode == "hat" and hasattr(self, 'hats_panel'):
                hat_class_models = self.hats_panel.get_all_class_models()

            self._extract_model_worker = ExtractModelWorker(
                tf2_root_dir=tf2_root_dir,
                mode=self.mode,
                weapon_key=weapon_key,
                language=self.language,
                hat_class_models=hat_class_models,
                parent=self
            )
            self._extract_model_export_folder = export_folder

            self._extract_model_worker.finished.connect(self._on_extract_model_finished)
            self._extract_model_worker.progress.connect(self._on_extract_model_progress)
            self._extract_model_worker.error.connect(self._on_extract_model_error)

            progress_title = self.t.get('extract_model_progress_title', 'Extract Model')
            progress_text  = self.t.get('extract_model_progress_text', 'Extracting model...')

            self._launch_progress(
                '_extract_model_progress_dialog', self._extract_model_worker,
                self._cancel_extract_model,
                title=progress_title, text=progress_text,
                disable_button='extract_model_button',
            )
        except Exception as e:
            ErrorHandler.show_error(self, e, "Ошибка при запуске извлечения модели")

    def _on_extract_model_finished(self, success: bool, message: str) -> None:
        self._close_progress('_extract_model_progress_dialog', 'extract_model_button')
        if success:
            from src.services.extract_model_service import ExtractModelService

            prepared_files = []
            temp_dir = None
            decompile_dir = None
            if hasattr(self, '_extract_model_worker'):
                prepared_files = getattr(self._extract_model_worker, 'prepared_files', []) or []
                temp_dir = getattr(self._extract_model_worker, 'prepared_temp_dir', None)
                decompile_dir = getattr(self._extract_model_worker, 'prepared_decompile_dir', None)

            if not prepared_files or not temp_dir or not decompile_dir:
                if temp_dir:
                    ExtractModelService.cleanup_temp_dir(temp_dir)
                ErrorHandler.show_warning(self, message, self.t['error'])
                return

            from src.ui.model_export_dialog import ModelExportDialog

            dialog = ModelExportDialog(
                self,
                self.t.get('extract_model_select_title', 'Model Export'),
                self.t.get('extract_model_select_desc', 'Select files to save into export:'),
                prepared_files
            )
            dialog.set_button_texts(
                self.t.get('select_all', 'Select all'),
                self.t.get('deselect_all', 'Select none'),
                self.t.get('cancel', 'Cancel'),
                self.t.get('export_btn', 'Export')
            )

            if dialog.exec() != QDialog.Accepted:
                ExtractModelService.cleanup_temp_dir(temp_dir)
                ErrorHandler.show_warning(self, self.t.get('extract_model_cancelled', 'Cancelled'), self.t['error'])
                return

            selected = dialog.selected_files() or []
            if not selected:
                ExtractModelService.cleanup_temp_dir(temp_dir)
                ErrorHandler.show_warning(self, self.t.get('extract_model_nothing_selected', 'Nothing selected, export cancelled'), self.t['error'])
                return

            if hasattr(self, '_export_model_worker') and self._export_model_worker.isRunning():
                ExtractModelService.cleanup_temp_dir(temp_dir)
                ErrorHandler.show_warning(self, self.t.get('extract_model_already_running', 'Model extraction is already in progress. Please wait.'), self.t['error'])
                return

            from src.services.export_model_files_worker import ExportModelFilesWorker
            self._export_model_worker = ExportModelFilesWorker(
                temp_dir=temp_dir,
                decompile_dir=decompile_dir,
                selected_files=selected,
                export_folder=getattr(self, '_extract_model_export_folder', 'export'),
                weapon_key=getattr(self, '_extract_model_worker', None).weapon_key if hasattr(self, '_extract_model_worker') else "",
                language=self.language,
                parent=self
            )

            self._export_model_worker.finished.connect(self._on_export_model_finished)
            self._export_model_worker.progress.connect(self._on_export_model_progress)
            self._export_model_worker.error.connect(self._on_export_model_error)

            progress_title = self.t.get('extract_model_select_title', 'Model Export')
            progress_text  = self.t.get('extract_model_exporting', 'Exporting model files...')

            self._launch_progress(
                '_export_model_progress_dialog', self._export_model_worker,
                title=progress_title, text=progress_text,
                disable_button='extract_model_button', cancellable=False,
            )
        else:
            ErrorHandler.show_warning(self, message, self.t['error'])

    def _on_extract_model_progress(self, percentage: int, status: str) -> None:
        self._update_progress('_extract_model_progress_dialog', percentage, status)

    def _on_extract_model_error(self, error_message: str) -> None:
        self._close_progress('_extract_model_progress_dialog', 'extract_model_button')
        ErrorHandler.show_error(self, Exception(error_message), "Ошибка извлечения модели")

    def _cancel_extract_model(self) -> None:
        self._cancel_worker('_extract_model_worker')

    def _on_export_model_finished(self, success: bool, message: str) -> None:
        self._close_progress('_export_model_progress_dialog', 'extract_model_button')
        if success:
            success_title = self.t.get('success', 'Success')
            ErrorHandler.show_info(self, message, success_title)
        else:
            ErrorHandler.show_warning(self, message, self.t['error'])

    def _on_export_model_progress(self, percentage: int, status: str) -> None:
        self._update_progress('_export_model_progress_dialog', percentage, status)

    def _on_export_model_error(self, error_message: str) -> None:
        self._close_progress('_export_model_progress_dialog', 'extract_model_button')
        ErrorHandler.show_error(self, Exception(error_message), "Ошибка экспорта модели")

    def export_uv_template(self) -> None:
        """По кнопке: декомпилирует модель и рисует UV-шаблон в папку экспорта
        (без полной сборки мода)."""
        try:
            weapon_key = self._resolve_extractable_weapon_key()
            if not weapon_key:
                return

            settings = self.settings_panel.get_settings()
            tf2_root_dir = settings.get('tf2_game_folder', '')
            if not tf2_root_dir:
                ErrorHandler.show_warning(self, self.t.get('tf2_path_not_specified', 'TF2 path not specified in settings'), self.t['error'])
                return

            export_folder = settings.get('export_folder', 'export')
            image_size = settings.get('size') or (1024, 1024)

            if self._worker_busy('_uv_template_worker', 'extract_model_already_running',
                                 'Operation is already in progress. Please wait.'):
                return

            from src.services.uv_template_worker import UVTemplateWorker
            self._uv_template_worker = UVTemplateWorker(
                tf2_root_dir=tf2_root_dir,
                mode=self.mode,
                weapon_key=weapon_key,
                image_size=image_size,
                export_folder=export_folder,
                language=self.language,
                parent=self,
            )
            self._uv_template_worker.finished.connect(self._on_uv_template_finished)
            self._uv_template_worker.progress.connect(self._on_uv_template_progress)
            self._uv_template_worker.error.connect(self._on_uv_template_error)

            self._launch_progress(
                '_uv_template_progress_dialog', self._uv_template_worker,
                self._cancel_uv_template,
                title=self.t.get('export_uv_progress_title', 'UV Template'),
                text=self.t.get('export_uv_progress_text', 'Generating UV template...'),
                disable_button='export_uv_button',
            )
        except Exception as e:
            ErrorHandler.show_error(self, e, "Ошибка при запуске генерации UV-шаблона")

    def _on_uv_template_finished(self, success: bool, message: str) -> None:
        self._close_progress('_uv_template_progress_dialog', 'export_uv_button')
        if success:
            text = self.t.get('export_uv_success', 'UV template saved:') + f"\n{message}"
            ErrorHandler.show_info(self, text, self.t.get('success', 'Success'))
        else:
            if message == 'no_smd':
                message = self.t.get('export_uv_no_smd', 'Reference SMD not found for UV template.')
            elif message == 'render_failed':
                message = self.t.get('export_uv_failed', 'Failed to render UV template.')
            ErrorHandler.show_warning(self, message, self.t['error'])

    def _on_uv_template_progress(self, percentage: int, status: str) -> None:
        self._update_progress('_uv_template_progress_dialog', percentage, status)

    def _on_uv_template_error(self, error_message: str) -> None:
        self._close_progress('_uv_template_progress_dialog', 'export_uv_button')
        ErrorHandler.show_error(self, Exception(error_message), "Ошибка генерации UV-шаблона")

    def _cancel_uv_template(self) -> None:
        self._cancel_worker('_uv_template_worker')

    def extract_original_texture(self) -> None:
        """Запускает асинхронное извлечение оригинальной текстуры оружия/рук/шапки из игры"""
        try:
            if not hasattr(self, 'mode') or not self.mode:
                ErrorHandler.show_warning(self, self.t['select_weapon_error'], self.t['error'])
                return

            from src.data.weapons import SPECIAL_MODES
            if self.mode in SPECIAL_MODES:
                error_msg = self.t.get('extract_texture_special_mode_error', 'Cannot extract texture for special modes')
                ErrorHandler.show_warning(self, error_msg, self.t['error'])
                return

            from src.data.player_hands import HAND_MODE_KEYS
            from src.data.player_characters import PLAYER_BODY_MODE_KEYS
            if self.mode == "hat":
                self._extract_hat_texture()
            else:
                self._extract_weapon_or_body_texture(
                    is_hands=self.mode in HAND_MODE_KEYS,
                    is_player_body=self.mode in PLAYER_BODY_MODE_KEYS,
                )
        except Exception as e:
            ErrorHandler.show_error(self, e, "Ошибка при запуске извлечения текстуры")

    def _extract_hat_texture(self) -> None:
        """Извлекает оригинальную текстуру шапки (отдельный воркер, как в 3D Preview)."""
        hat_mdl = getattr(self, '_hat_mdl_path', '')
        if not hat_mdl:
            ErrorHandler.show_warning(
                self, self.t.get('select_weapon_error', 'Select a hat first'), self.t['error']
            )
            return

        settings = self.settings_panel.get_settings()
        tf2_root_dir = settings.get('tf2_game_folder', '')
        if not tf2_root_dir:
            ErrorHandler.show_warning(
                self, self.t.get('tf2_path_not_specified', 'TF2 path not specified'), self.t['error']
            )
            return

        export_folder = settings.get('export_folder', 'export')
        from src.config.app_config import AppConfig
        export_format = AppConfig.load_config().get('export_image_format', 'PNG')

        if self._worker_busy('_extract_worker', 'extract_already_running',
                             'Extraction is already in progress.'):
            return

        from src.services.hat_texture_extract_worker import HatTextureExtractWorker
        self._extract_worker = HatTextureExtractWorker(
            hat_mdl_path=hat_mdl,
            tf2_root_dir=tf2_root_dir,
            export_folder=export_folder,
            export_format=export_format,
            language=self.language,
            parent=self,
        )
        self._extract_worker.finished.connect(self._on_extract_finished)
        self._extract_worker.progress.connect(self._on_extract_progress)
        self._extract_worker.error.connect(self._on_extract_error)

        self._launch_progress(
            '_extract_progress_dialog', self._extract_worker, self._cancel_extract,
            title=self.t.get('extract_progress_title', 'Extract Texture'),
            text=self.t.get('extract_progress_text', 'Extracting texture...'),
            disable_button='extract_texture_button',
        )

    def _extract_weapon_or_body_texture(self, is_hands: bool, is_player_body: bool) -> None:
        """Извлекает текстуру обычного оружия / рук / скина персонажа из игрового VPK."""
        from src.data.player_hands import get_hand_textures
        if is_hands:
            hand_textures = get_hand_textures(self.mode)
        elif is_player_body:
            hand_textures = None   # будет заполнено после диалога
        else:
            hand_textures = None

        # Для рук используем arm_model как weapon_key — именно под ним
        # хранится QC в кэше декомпила. Простой split даёт "hands" вместо "c_scout_arms".
        if is_hands:
            from src.data.player_hands import HAND_MODES as _HAND_MODES
            weapon_key = _HAND_MODES.get(self.mode, {}).get("arm_model", "") or (
                weapon_key_from_mode(self.mode)
            )
        else:
            weapon_key = weapon_key_from_mode(self.mode)

        # Получаем путь к TF2
        settings = self.settings_panel.get_settings()
        tf2_root_dir = settings.get('tf2_game_folder', '')

        if not tf2_root_dir:
            error_msg = self.t.get('tf2_path_not_specified', 'TF2 path not specified in settings')
            ErrorHandler.show_warning(self, error_msg, self.t['error'])
            return

        # Получаем путь к tf2_textures_dir.vpk
        from src.services.tf2_paths import TF2Paths
        textures_vpk = TF2Paths.resolve_textures_vpk(tf2_root_dir)

        if not textures_vpk:
            error_msg = self.t.get('textures_vpk_not_found', 'tf2_textures_dir.vpk not found')
            ErrorHandler.show_warning(self, error_msg, self.t['error'])
            return

        # Для персонажей — показываем диалог выбора текстур (нужен textures_vpk)
        if is_player_body:
            from src.ui.texture_select_dialog import TextureSelectDialog
            from PySide6.QtWidgets import QDialog as _QDialog
            dlg = TextureSelectDialog(
                mode=self.mode,
                textures_vpk_path=textures_vpk,
                language=self.language,
                parent=self,
            )
            if dlg.exec() != _QDialog.DialogCode.Accepted:
                return
            hand_textures = dlg.get_selected_textures()
            if not hand_textures:
                return

        # Получаем папку экспорта и формат
        export_folder = settings.get('export_folder', 'export')
        from src.config.app_config import AppConfig
        config = AppConfig.load_config()
        export_format = config.get('export_image_format', 'PNG')

        # Проверяем, не запущено ли уже извлечение
        if self._worker_busy('_extract_worker', 'extract_already_running',
                             'Extraction is already in progress. Please wait.'):
            return

        # Создаем и запускаем воркер для асинхронного извлечения
        from src.services.extract_texture_worker import ExtractTextureWorker

        self._extract_worker = ExtractTextureWorker(
            textures_vpk_path=textures_vpk,
            weapon_key=weapon_key,
            export_folder=export_folder,
            export_format=export_format,
            language=self.language,
            hand_textures=hand_textures,
            use_explicit_list=is_player_body or is_hands,
            parent=self
        )
            
        # Подключаем сигналы
        self._extract_worker.finished.connect(self._on_extract_finished)
        self._extract_worker.progress.connect(self._on_extract_progress)
        self._extract_worker.error.connect(self._on_extract_error)
            
        # Создаем и показываем прогресс-диалог
        self._launch_progress(
            '_extract_progress_dialog', self._extract_worker, self._cancel_extract,
            title=self.t.get('extract_progress_title', 'Extract Texture'),
            text=self.t.get('extract_progress_text', 'Extracting texture...'),
            disable_button='extract_texture_button',
        )

    def _on_extract_finished(self, success: bool, message: str) -> None:
        """Обработчик завершения извлечения текстуры"""
        self._close_progress('_extract_progress_dialog', 'extract_texture_button')
        if success:
            success_title = self.t.get('success', 'Success')
            ErrorHandler.show_info(self, message, success_title)
        else:
            ErrorHandler.show_warning(self, message, self.t['error'])

    def _on_extract_progress(self, percentage: int, status: str):
        """Обработчик прогресса извлечения текстуры"""
        self._update_progress('_extract_progress_dialog', percentage, status)

    def _on_extract_error(self, error_message: str):
        """Обработчик ошибки извлечения текстуры"""
        self._close_progress('_extract_progress_dialog', 'extract_texture_button')
        ErrorHandler.show_error(self, Exception(error_message), "Ошибка извлечения текстуры")
    
    def _cancel_extract(self) -> None:
        """Отменяет извлечение текстуры"""
        self._cancel_worker('_extract_worker')
    
    def _ask_merge_filename(self) -> Optional[str]:
        """Стилизованный диалог ввода имени выходного VPK файла."""
        from src.ui.styled_dialog import StyledDialog
        from PySide6.QtWidgets import QVBoxLayout, QLabel, QLineEdit, QPushButton

        is_ru = self.language == 'ru'
        dlg = StyledDialog(self,
                           title=self.t.get('merge_vpk_title', 'Merge Mods'),
                           width=420)
        c = dlg._c
        root = QVBoxLayout(dlg)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(dlg.make_header(
            self.t.get('merge_vpk_title', 'Merge Mods'),
            subtitle=self.t.get('enter_output_filename', 'Enter output file name'),
        ))

        body = QVBoxLayout()
        body.setContentsMargins(20, 20, 20, 16)
        body.setSpacing(8)

        hint = QLabel(self.t.get('enter_output_filename', 'Output file name:'))
        hint.setStyleSheet(f"color:{c['text_sub']}; font-size:11px;")
        body.addWidget(hint)

        edit = QLineEdit("merged_mod")
        edit.setFixedHeight(34)
        edit.selectAll()
        edit.setStyleSheet(f"""
            QLineEdit {{
                background: rgba(255,255,255,0.04); color: {c['text']};
                border: 1px solid {c['border']}; border-radius: 4px;
                padding: 0 10px; font-size: 13px;
            }}
            QLineEdit:focus {{ border-color: {c['border_h']}; }}
        """)
        body.addWidget(edit)

        err_lbl = QLabel("")
        err_lbl.setStyleSheet("color:#c04040; font-size:10px;")
        body.addWidget(err_lbl)

        root.addLayout(body)
        root.addWidget(dlg.divider())

        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton(self.t.get('cancel', 'Cancel'))

        def _try_accept():
            name = edit.text().strip()
            if not name:
                err_lbl.setText("Введите имя файла" if is_ru else "Enter file name")
                return
            if not name.endswith('.vpk'):
                name += '.vpk'
            valid, msg = validate_vpk_filename(name)
            if not valid:
                err_lbl.setText(msg)
                return
            dlg._result_name = name
            dlg.accept()

        edit.returnPressed.connect(_try_accept)
        ok_btn.clicked.connect(_try_accept)
        cancel_btn.clicked.connect(dlg.reject)

        root.addWidget(dlg.make_footer([cancel_btn, ok_btn]))

        dlg._result_name = None
        if dlg.exec():
            return dlg._result_name
        return None

    def merge_vpk_files(self) -> None:
        """Открывает диалог объединения VPK файлов"""
        from src.ui.merge_vpk_dialog import MergeVPKDialog
        from src.services.merge_vpk_service import MergeVPKService
        
        # Открываем диалог выбора модов
        dialog = MergeVPKDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        
        # Получаем выбранные файлы
        selected_files = dialog.get_selected_files()
        if not selected_files:
            ErrorHandler.show_warning(self, self.t.get('no_vpk_files_selected', 'No VPK files selected'), self.t['error'])
            return
        
        # Запрашиваем имя выходного файла — стилизованный диалог
        filename = self._ask_merge_filename()
        if not filename:
            return

        # Получаем настройки
        settings = self.settings_panel.get_settings()
        export_folder = settings.get('export_folder', 'export')
        
        # Проверяем наличие дубликатов оружий
        duplicates = MergeVPKService.check_duplicate_weapons(selected_files)
        if duplicates:
            # Формируем сообщение о дубликатах
            duplicate_msg = self.t.get('duplicate_weapons_warning', 
                'Обнаружены дубликаты оружий:\n\n')
            
            for weapon_name, vpk_files in duplicates.items():
                duplicate_msg += f"• {weapon_name}: {', '.join(vpk_files)}\n"
            
            duplicate_msg += "\n" + self.t.get('duplicate_weapons_question', 
                'Вы пытаетесь соединить моды, которые влияют на одно оружие.\nПродолжить?')
            
            # Показываем диалог подтверждения
            reply = QMessageBox.question(
                self,
                self.t.get('duplicate_weapons_title', 'Дубликаты оружий'),
                duplicate_msg,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.No:
                return  # Останавливаем процесс
        
        # Проверяем, не запущено ли уже объединение
        if self._worker_busy('_merge_worker', 'merge_already_running',
                             'Объединение уже выполняется. Пожалуйста, подождите.'):
            return
        
        # Выполняем объединение в отдельном потоке
        from src.services.merge_vpk_worker import MergeVpkWorker
        self._merge_worker = MergeVpkWorker(selected_files, filename, export_folder, self.language)
        self._merge_worker.finished.connect(self._on_merge_finished)
        self._merge_worker.progress.connect(self._on_merge_progress)

        # Создаём диалог, запускаем воркер, показываем, блокируем кнопку
        self._launch_progress(
            '_merge_progress_dialog', self._merge_worker, self._cancel_merge,
            title=self.t.get('merge_vpk_title', 'Merge Mods'),
            text=self.t.get('merge_vpk_progress', 'Merging VPK files...'),
            disable_button='merge_vpk_button',
        )
    
    def _on_merge_finished(self, success: bool, message: str):
        """Обработчик завершения объединения VPK"""
        self._close_progress('_merge_progress_dialog', 'merge_vpk_button')
        if success:
            ErrorHandler.show_info(self, message, self.t.get('merge_vpk_title', 'Объединить моды'))
        else:
            cancelled_msg = self.t.get('merge_cancelled', 'Объединение отменено пользователем')
            if message == cancelled_msg:
                ErrorHandler.show_info(self, cancelled_msg, self.t.get('cancel', 'Cancel'))
            else:
                ErrorHandler.show_error(self, Exception(message), "Ошибка объединения VPK")
    
    def _on_merge_progress(self, percentage: int, status: str):
        """Обработчик прогресса объединения VPK"""
        self._update_progress('_merge_progress_dialog', percentage, status)
    
    def _cancel_merge(self) -> None:
        """Отменяет объединение VPK"""
        self._cancel_worker('_merge_worker')
