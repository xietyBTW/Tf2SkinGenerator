from typing import Optional, Tuple

from src.services.base_worker import StandardWorker
from src.services.extract_model_service import ExtractModelService


class UVTemplateWorker(StandardWorker):
    """
    По запросу (кнопкой) декомпилирует модель (cache-aware) и рисует UV-шаблон
    в папку экспорта — без полной сборки мода. Путь готового PNG доступен в
    self.output_path после успешного finished.

    Сигналы (наследуются от StandardWorker): finished(bool, str),
    progress(int, str), error(str).
    """

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

    def work(self) -> Tuple[bool, str]:
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

            if cancelled or not success or not data:
                return False, message

            temp_dir = data.get("temp_dir")
            decompile_dir = data.get("decompile_dir")
            if not decompile_dir:
                return False, message

            ok, result = ExtractModelService.generate_uv_template(
                decompile_dir=decompile_dir,
                weapon_key=self.weapon_key,
                image_size=self.image_size,
                export_folder=self.export_folder,
            )
            if ok:
                self.output_path = result
            return ok, result
        finally:
            if temp_dir:
                ExtractModelService.cleanup_temp_dir(temp_dir)
