"""
Воркер для асинхронного объединения нескольких VPK-модов в один (фоновый поток).
"""

from typing import Tuple

from src.services.base_worker import StandardWorker
from src.services.merge_vpk_service import MergeVPKService
from src.data.translations import TRANSLATIONS


class MergeVpkWorker(StandardWorker):
    """
    Фоновое объединение VPK-файлов через MergeVPKService.

    Сигналы (наследуются от StandardWorker): finished(bool, str),
    progress(int, str), error(str).
    """

    def __init__(self, vpk_files, filename, export_folder, language: str = "en", parent=None):
        super().__init__(parent)
        self.vpk_files = vpk_files
        self.filename = filename
        self.export_folder = export_folder
        self.language = language
        self.t = TRANSLATIONS.get(language, TRANSLATIONS["en"])

    def work(self) -> Tuple[bool, str]:
        self.progress.emit(10, self.t.get("merge_vpk_extracting", "Извлечение файлов..."))
        success, message = MergeVPKService.merge_vpk_files(
            self.vpk_files,
            self.filename,
            self.export_folder,
            self.language,
            should_cancel=self.isInterruptionRequested,
        )
        if self.isInterruptionRequested():
            success = False
            message = self.t.get("merge_cancelled", "Объединение отменено пользователем")
        self.progress.emit(100, self.t.get("merge_vpk_completed", "Завершено"))
        return success, message
