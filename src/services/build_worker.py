from PySide6.QtCore import QThread, Signal, QTimer, QMutex, QWaitCondition
import time
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
        t = TRANSLATIONS.get(self.language, TRANSLATIONS['en'])
        
        try:
            logger.info(f"Начало асинхронной сборки VPK: {self.filename}")
            self.progress.emit(5, t.get('build_init', 'Initializing build...'))
            time.sleep(0.1)
            
            from src.data.weapons import SPECIAL_MODES
            is_special_mode = self.mode in SPECIAL_MODES.values()
            
            if is_special_mode:
                self.progress.emit(20, t.get('build_processing', 'Processing texture...'))
                time.sleep(0.1)
                
                success, message = VPKService.build_vpk(
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
                    parent_window=None,  # Не используем напрямую (работаем в отдельном потоке, Qt не любит UI из воркера)
                    model_file_callback=self._request_model_file_callback if self.replace_model_enabled else None,
                    language=self.language,
                    custom_vtf_path=self.custom_vtf_path
                )
                
                if not self.isInterruptionRequested():
                    self.progress.emit(60, t.get('build_packing', 'Creating VPK file...'))
                    time.sleep(0.1)
            else:
                self.progress.emit(10, t.get('build_extracting', 'Extracting model...'))
                time.sleep(0.1)
                
                success, message = self._build_with_progress(t)
            
            if self.isInterruptionRequested():
                logger.info("Сборка прервана пользователем")
                return
            
            if success:
                logger.info(f"Сборка успешно завершена: {message}")
                self.progress.emit(100, t.get('build_completed', 'Build completed'))
                self.finished.emit(True, message)
            else:
                logger.error(f"Ошибка сборки: {message}")
                self.progress.emit(0, t.get('build_error_status', 'Build error'))
                self.finished.emit(False, message)
                
        except Exception as e:
            error_msg = str(e)
            logger.critical(f"Критическая ошибка при сборке: {error_msg}", exc_info=True)
            self.progress.emit(0, t.get('build_critical_error', 'Critical error'))
            self.error.emit(error_msg)
            self.finished.emit(False, error_msg)
    
    def _build_with_progress(self, t: dict) -> Tuple[bool, str]:
        # Для обычного оружия показываем прогресс по этапам (распаковка, декомпил, компил, упаковка)
        import threading
        
        build_complete = threading.Event()
        build_result = [None, None]
        
        def update_progress():
            # Этапы сборки с примерными процентами (примерные, потому что реальный прогресс сложно отследить - это не точная наука)
            stages = [
                (25, t.get('build_decompiling', 'Decompiling model...')),
                (40, t.get('build_processing', 'Processing texture...')),
                (60, t.get('build_compiling', 'Compiling model...')),
                (80, t.get('build_packing', 'Creating VPK file...')),
            ]
            
            for progress, status in stages:
                if build_complete.is_set():
                    break
                time.sleep(0.5)  # Задержка между обновлениями (чтобы прогресс не дергался слишком быстро)
                if not self.isInterruptionRequested():
                    self.progress.emit(progress, status)
        
        progress_thread = threading.Thread(target=update_progress, daemon=True)  # Демон-поток, чтобы не блокировать выход
        progress_thread.start()
        
        try:
            success, message = VPKService.build_vpk(
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
                    parent_window=None,  # Не используем напрямую (работаем в отдельном потоке, Qt не любит UI из воркера - упадет)
                    model_file_callback=self._request_model_file_callback if self.replace_model_enabled else None,
                language=self.language,
                custom_vtf_path=self.custom_vtf_path
            )
            
            build_result[0] = success
            build_result[1] = message
        finally:
            build_complete.set()
            progress_thread.join(timeout=1.0)
        
        return build_result[0], build_result[1]
    
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

