from PySide6.QtCore import QThread, Signal, QTimer, QMutex, QWaitCondition
from typing import Optional, Dict, Any, Tuple
from pathlib import Path
from src.services.vpk_service import VPKService
from src.shared.logging_config import get_logger
from src.data.translations import TRANSLATIONS

logger = get_logger(__name__)


class BuildWorker(QThread):
    finished = Signal(bool, str)
    progress = Signal(int, str)
    error = Signal(str)
    request_model_file = Signal()
    
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
        draw_uv_layout: bool = False,
        language: str = "en",
        custom_vtf_path: Optional[str] = None,
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
        self.draw_uv_layout = draw_uv_layout
        self.language = language
        self.custom_vtf_path = custom_vtf_path
        self.parent_window = parent
        self._model_file_result = None
        self._model_file_mutex = QMutex()  # Мьютекс для синхронизации между потоками (UI и воркер)
        self._model_file_condition = QWaitCondition()  # Условие для ожидания выбора файла из UI
    
    def run(self) -> None:
        try:
            t = TRANSLATIONS.get(self.language, TRANSLATIONS['en'])
            success, message, cancelled = VPKService.build_with_progress(
                image_path=self.image_path,
                mode=self.mode,
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
                draw_uv_layout=self.draw_uv_layout,
                replace_model_path=None,
                model_file_callback=self._request_model_file_callback if self.replace_model_enabled else None,
                language=self.language,
                custom_vtf_path=self.custom_vtf_path,
                progress_callback=self.progress.emit,
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
    
    def _request_model_file_callback(self) -> Optional[str]:
        # Запрашиваем файл модели из UI потока (костыль для работы с Qt из воркера - Qt не любит UI из других потоков)
        self._model_file_mutex.lock()
        self._model_file_result = None
        self._model_file_requested = True
        self._model_file_mutex.unlock()
        
        self.request_model_file.emit()  # Эмитим сигнал в UI поток
        
        # Ждем пока UI поток выберет файл (таймаут 5 минут, на всякий случай - если юзер задумался)
        self._model_file_mutex.lock()
        if self._model_file_result is None:
            self._model_file_condition.wait(self._model_file_mutex, 300000)
        result = self._model_file_result
        self._model_file_requested = False
        self._model_file_mutex.unlock()
        
        return result
    
    def set_model_file_result(self, file_path: Optional[str]) -> None:
        self._model_file_mutex.lock()
        self._model_file_result = file_path
        self._model_file_condition.wakeAll()
        self._model_file_mutex.unlock()
