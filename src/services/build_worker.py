from PySide6.QtCore import QThread, Signal, QMutex, QWaitCondition
from typing import Optional, Dict, Any, Tuple
from src.services.vpk_service import VPKService
from src.shared.logging_config import get_logger
from src.data.translations import TRANSLATIONS

logger = get_logger(__name__)

# Специальный sentinel-объект: означает "ответ ещё не получен"
# None — допустимый ответ (пользователь отказался), поэтому нельзя использовать None как sentinel
_SENTINEL = object()


class BuildWorker(QThread):
    finished = Signal(bool, str)
    progress = Signal(int, str)
    sub_progress = Signal(int, str)   # (pct 0-100 или -1=indeterminate, label)
    error = Signal(str)
    request_model_file = Signal()
    request_extra_texture = Signal(str, str)  # (material_name, weapon_key) — запрос одной доп. текстуры
    request_extra_model = Signal(str, str)    # (smd_name, weapon_key) - запрос доп. модели (shell и т.д.)
    texture_mismatch_warning = Signal(str)    # (warning_message) — предупреждение о несовпадении текстур

    def __init__(
        self,
        image_path: Optional[str],
        mode: str,
        filename: str,
        size: Tuple[int, int],
        format_type: str = "DXT1",
        flags: Optional[list] = None,
        vtf_options: Optional[Dict[str, Any]] = None,
        tf2_root_dir: str = "",
        export_folder: str = "export",
        keep_temp_on_error: bool = False,
        debug_mode: bool = False,
        replace_model_enabled: bool = False,
        replace_model_path: Optional[str] = None,
        model_ready_path: Optional[str] = None,
        draw_uv_layout: bool = False,
        language: str = "en",
        custom_vtf_path: Optional[str] = None,
        blu_mode: str = "none",
        blu_image_path: Optional[str] = None,
        custom_vpk_source_path: Optional[str] = None,
        hat_mdl_path: Optional[str] = None,
        hat_apply_game_paints: bool = True,
        panel_extra_textures: Optional[Dict[str, Any]] = None,
        material_maps: Optional[Dict[str, Any]] = None,
        skin_build_data: Optional[Dict[str, Any]] = None,
        replace_keep_materials: bool = False,
        parent=None
    ):
        super().__init__(parent)
        self.image_path = image_path
        self.mode = mode
        self.filename = filename
        self.size = size
        self.format_type = format_type
        self.flags = flags or []
        self.vtf_options = vtf_options or {}
        self.tf2_root_dir = tf2_root_dir
        self.export_folder = export_folder
        self.keep_temp_on_error = keep_temp_on_error
        self.debug_mode = debug_mode
        self.replace_model_enabled = replace_model_enabled
        self.replace_model_path = replace_model_path
        self.model_ready_path = model_ready_path
        self.draw_uv_layout = draw_uv_layout
        self.language = language
        self.custom_vtf_path = custom_vtf_path
        self.blu_mode = blu_mode
        self.blu_image_path = blu_image_path
        self.custom_vpk_source_path = custom_vpk_source_path
        self.hat_mdl_path = hat_mdl_path
        self.hat_apply_game_paints = hat_apply_game_paints
        self.panel_extra_textures = panel_extra_textures or {}
        self.material_maps = material_maps or {}
        self.skin_build_data = skin_build_data
        self.replace_keep_materials = replace_keep_materials
        self.parent_window = parent

        self._model_file_mutex = QMutex()
        self._model_file_condition = QWaitCondition()
        self._model_file_result = _SENTINEL

        self._extra_texture_mutex = QMutex()
        self._extra_texture_condition = QWaitCondition()
        self._extra_texture_result = _SENTINEL

        self._extra_model_mutex = QMutex()
        self._extra_model_condition = QWaitCondition()
        self._extra_model_result = _SENTINEL

        self._texture_mismatch_mutex = QMutex()
        self._texture_mismatch_condition = QWaitCondition()
        self._texture_mismatch_result = _SENTINEL  # True = continue, False/None = cancel

    def run(self) -> None:
        try:
            t = TRANSLATIONS.get(self.language, TRANSLATIONS['en'])
            success, message, cancelled = VPKService.build_with_progress(
                custom_vpk_source_path=self.custom_vpk_source_path,
                image_path=self.image_path,
                mode=self.mode,
                hat_mdl_path=self.hat_mdl_path,
                filename=self.filename,
                size=self.size,
                format_type=self.format_type,
                flags=self.flags,
                vtf_options=self.vtf_options,
                tf2_root_dir=self.tf2_root_dir,
                export_folder=self.export_folder,
                keep_temp_on_error=self.keep_temp_on_error,
                debug_mode=self.debug_mode,
                replace_model_enabled=self.replace_model_enabled,
                model_ready_path=self.model_ready_path,
                draw_uv_layout=self.draw_uv_layout,
                replace_model_path=self.replace_model_path,
                model_file_callback=self._request_model_file_callback if (self.replace_model_enabled and not self.replace_model_path) else None,
                extra_texture_callback=self._request_extra_texture_callback,
                extra_model_callback=self._request_extra_model_callback if self.replace_model_enabled else None,
                texture_mismatch_callback=self._texture_mismatch_callback if self.model_ready_path else None,
                language=self.language,
                custom_vtf_path=self.custom_vtf_path,
                blu_mode=self.blu_mode,
                blu_image_path=self.blu_image_path,
                hat_apply_game_paints=self.hat_apply_game_paints,
                panel_extra_textures=self.panel_extra_textures,
                material_maps=self.material_maps,
                skin_build_data=self.skin_build_data,
                replace_keep_materials=self.replace_keep_materials,
                progress_callback=self.progress.emit,
                sub_progress_callback=self.sub_progress.emit,
                cancel_callback=self.isInterruptionRequested
            )

            if cancelled:
                self.finished.emit(False, t.get('build_cancelled', 'Build cancelled by user'))
                return

            if success:
                logger.info(f"Сборка успешно завершена: {message}")
                self.finished.emit(True, message)
            else:
                logger.error(f"Ошибка сборки: {message}")
                self.finished.emit(False, message)

        except Exception as e:
            error_msg = str(e)
            logger.critical(f"Критическая ошибка при сборке: {error_msg}", exc_info=True)
            self.error.emit(error_msg)
            self.finished.emit(False, error_msg)

    # -----------------------------------------------------------------------
    # Внутренний helper: emit сигнала → ждёт ответа от UI потока
    # -----------------------------------------------------------------------
    def _emit_and_wait(self, mutex: QMutex, condition: QWaitCondition,
                       result_attr: str, signal, *signal_args) -> Optional[str]:
        """
        Правильный thread-safe паттерн для запроса данных из UI потока:

        Воркер (фоновый поток):
          1. Берёт мьютекс
          2. Сбрасывает результат в _SENTINEL
          3. Атомарно отпускает мьютекс и ждёт (condition.wait)
             → в этот момент мьютекс свободен

        UI поток (обрабатывает сигнал через QueuedConnection):
          4. Показывает диалог пользователю
          5. Берёт мьютекс (теперь свободен, т.к. воркер ждёт)
          6. Записывает результат
          7. wakeAll() → воркер просыпается

        Воркер снова берёт мьютекс (после wait):
          8. Читает результат
          9. Отпускает мьютекс

        ВАЖНО: сигнал эмитируется ДО wait(), но ПОСЛЕ сброса sentinel.
        Это безопасно потому что:
        - Если UI успеет ответить до wait() → sentinel уже установлен,
          UI запишет результат и wakeAll() ничего не разбудит (ещё никто не ждёт).
          Воркер дойдёт до while — увидит что sentinel != _SENTINEL — и не войдёт в wait().
        - Если UI ответит после wait() → штатный путь, wakeAll() разбудит воркера.
        """
        mutex.lock()
        try:
            # Шаг 1: сбрасываем под мьютексом
            setattr(self, result_attr, _SENTINEL)
        finally:
            mutex.unlock()

        # Шаг 2: эмитим сигнал (UI получит его через QueuedConnection)
        # НЕ держим мьютекс при emit — это может вызвать дедлок если UI
        # попытается ответить пока мы ещё держим мьютекс
        signal.emit(*signal_args)

        # Шаг 3: берём мьютекс и ждём
        mutex.lock()
        try:
            # Проверяем: возможно UI уже успел ответить пока мы были между emit и lock
            while getattr(self, result_attr) is _SENTINEL:
                # Атомарно отпускает мьютекс и ждёт пробуждения.
                # False = таймаут (5 мин), True = разбужен wakeAll()
                if not condition.wait(mutex, 300000):
                    logger.warning(f"Таймаут ожидания ответа от UI для {result_attr}")
                    break
            result = getattr(self, result_attr)
            return result if result is not _SENTINEL else None
        finally:
            mutex.unlock()

    def _request_model_file_callback(self) -> Optional[str]:
        """Запрашивает файл модели из UI потока."""
        logger.debug("Запрос файла модели из UI")
        result = self._emit_and_wait(
            self._model_file_mutex,
            self._model_file_condition,
            '_model_file_result',
            self.request_model_file
        )
        logger.debug(f"Получен файл модели: {result}")
        return result

    def set_model_file_result(self, file_path: Optional[str]) -> None:
        logger.debug(f"set_model_file_result вызван: {file_path}")
        self._model_file_mutex.lock()
        self._model_file_result = file_path
        self._model_file_condition.wakeAll()
        self._model_file_mutex.unlock()

    def _request_extra_texture_callback(self, material_name: str, weapon_key: str) -> Optional[str]:
        """Запрашивает дополнительную текстуру из UI потока."""
        logger.debug(f"Запрос доп. текстуры из UI: material={material_name}, weapon={weapon_key}")
        result = self._emit_and_wait(
            self._extra_texture_mutex,
            self._extra_texture_condition,
            '_extra_texture_result',
            self.request_extra_texture,
            material_name,
            weapon_key
        )
        logger.debug(f"Получена доп. текстура: {result}")
        return result

    def set_extra_texture_result(self, file_path: Optional[str]) -> None:
        """Устанавливает результат выбора доп. текстуры из UI потока."""
        logger.debug(f"set_extra_texture_result вызван: {file_path}")
        self._extra_texture_mutex.lock()
        self._extra_texture_result = file_path
        self._extra_texture_condition.wakeAll()
        self._extra_texture_mutex.unlock()

    def _request_extra_model_callback(self, smd_name: str, weapon_key: str) -> Optional[str]:
        """Запрашивает дополнительный SMD файл для части модели из UI потока."""
        logger.debug(f"Запрос доп. модели из UI: smd={smd_name}, weapon={weapon_key}")
        result = self._emit_and_wait(
            self._extra_model_mutex,
            self._extra_model_condition,
            '_extra_model_result',
            self.request_extra_model,
            smd_name,
            weapon_key
        )
        logger.debug(f"Получена доп. модель: {result}")
        return result

    def set_extra_model_result(self, file_path: Optional[str]) -> None:
        """Устанавливает результат выбора доп. модели из UI потока."""
        logger.debug(f"set_extra_model_result вызван: {file_path}")
        self._extra_model_mutex.lock()
        self._extra_model_result = file_path
        self._extra_model_condition.wakeAll()
        self._extra_model_mutex.unlock()

    def _texture_mismatch_callback(self, warning_message: str) -> bool:
        """Показывает предупреждение о несовпадении текстур, ожидает решения пользователя."""
        logger.debug(f"Запрос подтверждения: несовпадение текстур")
        result = self._emit_and_wait(
            self._texture_mismatch_mutex,
            self._texture_mismatch_condition,
            '_texture_mismatch_result',
            self.texture_mismatch_warning,
            warning_message
        )
        # result: 'continue' = продолжить, всё остальное = отменить
        should_continue = (result == 'continue')
        logger.debug(f"Решение пользователя по несовпадению текстур: {result} → continue={should_continue}")
        return should_continue

    def set_texture_mismatch_result(self, decision: str) -> None:
        """Устанавливает решение пользователя: 'continue' или 'cancel'."""
        logger.debug(f"set_texture_mismatch_result вызван: {decision}")
        self._texture_mismatch_mutex.lock()
        self._texture_mismatch_result = decision
        self._texture_mismatch_condition.wakeAll()
        self._texture_mismatch_mutex.unlock()

