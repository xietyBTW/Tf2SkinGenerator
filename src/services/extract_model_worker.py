from PySide6.QtCore import QThread, Signal

from src.services.extract_model_service import ExtractModelService
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class ExtractModelWorker(QThread):
    finished = Signal(bool, str)
    progress = Signal(int, str)
    error = Signal(str)

    def __init__(
        self,
        tf2_root_dir: str,
        mode: str,
        weapon_key: str,
        language: str = "en",
        parent=None,
    ):
        super().__init__(parent)
        self.tf2_root_dir = tf2_root_dir
        self.mode = mode
        self.weapon_key = weapon_key
        self.language = language
        self.prepared_temp_dir = None
        self.prepared_decompile_dir = None
        self.prepared_files = None

    def run(self) -> None:
        try:
            success, message, cancelled, data = ExtractModelService.prepare_decompiled_model_files_with_progress(
                tf2_root_dir=self.tf2_root_dir,
                mode=self.mode,
                weapon_key=self.weapon_key,
                language=self.language,
                progress_callback=self.progress.emit,
                cancel_callback=self.isInterruptionRequested,
            )

            if cancelled:
                self.finished.emit(False, message)
                return

            if success and data:
                self.prepared_temp_dir = data.get("temp_dir")
                self.prepared_decompile_dir = data.get("decompile_dir")
                self.prepared_files = data.get("files") or []

            self.finished.emit(success, message)
        except Exception as e:
            error_msg = str(e)
            logger.critical(f"Критическая ошибка при извлечении модели: {error_msg}", exc_info=True)
            self.error.emit(error_msg)
            self.finished.emit(False, error_msg)
