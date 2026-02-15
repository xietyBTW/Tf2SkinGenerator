"""
Воркер для асинхронного извлечения текстуры из VPK в фоновом потоке
"""

from PySide6.QtCore import QThread, Signal
from typing import Optional
from src.services.tf2_vpk_extract_service import TF2VPKExtractService
from src.shared.logging_config import get_logger
from src.data.translations import TRANSLATIONS

logger = get_logger(__name__)


class ExtractTextureWorker(QThread):
    """
    Воркер для выполнения извлечения текстуры в фоновом потоке
    
    Предотвращает блокировку UI во время долгих операций извлечения
    """
    
    # Сигналы для связи с UI
    finished = Signal(bool, str)  # (success: bool, message: str)
    progress = Signal(int, str)  # (percentage: int, status: str)
    error = Signal(str)  # (error_message: str)
    
    def __init__(
        self,
        textures_vpk_path: str,
        weapon_key: str,
        export_folder: str,
        export_format: str = "PNG",
        language: str = "en",
        parent=None
    ):
        """
        Инициализирует воркер извлечения текстуры
        
        Args:
            textures_vpk_path: Путь к tf2_textures_dir.vpk
            weapon_key: Ключ оружия (например, c_scattergun)
            export_folder: Папка для экспорта
            export_format: Формат экспорта (VTF, PNG, TGA, JPG)
            language: Язык для сообщений
            parent: Родительский объект
        """
        super().__init__(parent)
        self.textures_vpk_path = textures_vpk_path
        self.weapon_key = weapon_key
        self.export_folder = export_folder
        self.export_format = export_format
        self.language = language
    
    def run(self) -> None:
        """
        Выполняет извлечение текстуры в фоновом потоке
        """
        try:
            success, message, cancelled = TF2VPKExtractService.extract_texture_with_progress(
                self.textures_vpk_path,
                self.weapon_key,
                self.export_folder,
                self.export_format,
                language=self.language,
                progress_callback=self.progress.emit,
                cancel_callback=self.isInterruptionRequested
            )
            
            if cancelled:
                self.finished.emit(False, message)
                return
            
            if success:
                logger.info(f"Текстура успешно извлечена: {message}")
                self.finished.emit(True, message)
            else:
                logger.error(f"Не удалось извлечь текстуру для {self.weapon_key}: {message}")
                self.finished.emit(False, message)
        except Exception as e:
            error_msg = str(e)
            logger.critical(f"Критическая ошибка при извлечении текстуры: {error_msg}", exc_info=True)
            self.error.emit(error_msg)
            self.finished.emit(False, error_msg)

