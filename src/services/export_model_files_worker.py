from typing import Tuple

from src.data.translations import TRANSLATIONS
from src.services.base_worker import StandardWorker
from src.services.extract_model_service import ExtractModelService


class ExportModelFilesWorker(StandardWorker):
    def __init__(
        self,
        temp_dir: str,
        decompile_dir: str,
        selected_files: list[str],
        export_folder: str,
        weapon_key: str,
        language: str = "en",
        parent=None,
    ):
        super().__init__(parent)
        self.temp_dir = temp_dir
        self.decompile_dir = decompile_dir
        self.selected_files = selected_files
        self.export_folder = export_folder
        self.weapon_key = weapon_key
        self.language = language

    def work(self) -> Tuple[bool, str]:
        t = TRANSLATIONS.get(self.language, TRANSLATIONS["en"])
        try:
            self.progress.emit(10, t.get("extract_model_exporting", "Exporting model files..."))
            out_path = ExtractModelService.export_selected_files(
                decompile_dir=self.decompile_dir,
                selected_files=self.selected_files,
                export_folder=self.export_folder,
                weapon_key=self.weapon_key,
            )
            self.progress.emit(100, t.get("extract_model_completed", "Extraction completed"))
            return True, t.get("extract_model_export_success", "Export completed: {path}").format(path=out_path)
        finally:
            ExtractModelService.cleanup_temp_dir(self.temp_dir)
