from typing import Tuple

from src.services.base_worker import StandardWorker
from src.services.extract_model_service import ExtractModelService


class ExtractModelWorker(StandardWorker):
    """Фоновое извлечение + декомпиляция модели (cache-aware) через сервис."""

    def __init__(
        self,
        tf2_root_dir: str,
        mode: str,
        weapon_key: str,
        language: str = "en",
        hat_class_models=None,
        parent=None,
    ):
        super().__init__(parent)
        self.tf2_root_dir = tf2_root_dir
        self.mode = mode
        self.weapon_key = weapon_key
        self.language = language
        self.hat_class_models = hat_class_models
        self.prepared_temp_dir = None
        self.prepared_decompile_dir = None
        self.prepared_files = None

    def work(self) -> Tuple[bool, str]:
        success, message, cancelled, data = ExtractModelService.prepare_decompiled_model_files_with_progress(
            tf2_root_dir=self.tf2_root_dir,
            mode=self.mode,
            weapon_key=self.weapon_key,
            language=self.language,
            progress_callback=self.progress.emit,
            cancel_callback=self.isInterruptionRequested,
            hat_class_models=self.hat_class_models,
        )
        if cancelled:
            return False, message
        if success and data:
            self.prepared_temp_dir = data.get("temp_dir")
            self.prepared_decompile_dir = data.get("decompile_dir")
            self.prepared_files = data.get("files") or []
        return success, message
