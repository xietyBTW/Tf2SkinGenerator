from typing import Optional, Tuple

from PySide6.QtCore import QThread, Signal

from src.services.extract_model_service import ExtractModelService
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class UVTemplateWorker(QThread):
    """
    По запросу (кнопкой) декомпилирует модель (cache-aware) и рисует UV-шаблон
    в папку экспорта — без полной сборки мода. Путь готового PNG доступен в
    self.output_path после успешного finished.
    """
    finished = Signal(bool, str)
    progress = Signal(int, str)
    error = Signal(str)

    def __init__(
        self,
        tf2_root_dir: str,
        mode: str,
        weapon_key: str,
        image_size: Tuple[int, int],
        export_folder: str = "export",
        language: str = "en",
        parent=None,
    ):
        super().__init__(parent)
        self.tf2_root_dir = tf2_root_dir
        self.mode = mode
        self.weapon_key = weapon_key
        self.image_size = image_size
        self.export_folder = export_folder
        self.language = language
        self.output_path: Optional[str] = None

    def run(self) -> None:
        temp_dir = None
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
            if not success or not data:
                self.finished.emit(False, message)
                return

            temp_dir = data.get("temp_dir")
            decompile_dir = data.get("decompile_dir")
            if not decompile_dir:
                self.finished.emit(False, message)
                return

            ok, result = ExtractModelService.generate_uv_template(
                decompile_dir=decompile_dir,
                weapon_key=self.weapon_key,
                image_size=self.image_size,
                export_folder=self.export_folder,
            )
            if ok:
                self.output_path = result
                self.finished.emit(True, result)
            else:
                self.finished.emit(False, result)
        except Exception as e:
            error_msg = str(e)
            logger.critical(f"Критическая ошибка при генерации UV-шаблона: {error_msg}", exc_info=True)
            self.error.emit(error_msg)
            self.finished.emit(False, error_msg)
        finally:
            if temp_dir:
                ExtractModelService.cleanup_temp_dir(temp_dir)
