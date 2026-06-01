"""
Воркер для асинхронного объединения нескольких VPK-модов в один (фоновый поток).
"""

from PySide6.QtCore import QThread, Signal

from src.services.merge_vpk_service import MergeVPKService
from src.shared.logging_config import get_logger
from src.data.translations import TRANSLATIONS

logger = get_logger(__name__)


class MergeVpkWorker(QThread):
    """
    Фоновое объединение VPK-файлов через MergeVPKService.

    Сигналы:
        finished(bool, str) — (успех, сообщение)
        progress(int, str)  — (процент, статус)
    """

    finished = Signal(bool, str)
    progress = Signal(int, str)

    def __init__(self, vpk_files, filename, export_folder, language: str = "en", parent=None):
        super().__init__(parent)
        self.vpk_files = vpk_files
        self.filename = filename
        self.export_folder = export_folder
        self.language = language
        self.t = TRANSLATIONS.get(language, TRANSLATIONS["en"])

    def run(self) -> None:
        try:
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
            self.finished.emit(success, message)
        except Exception as e:
            logger.error(f"Ошибка в MergeVpkWorker: {e}", exc_info=True)
            self.finished.emit(False, str(e))
