"""
Воркер для асинхронного извлечения текстуры из VPK в фоновом потоке
"""

from PySide6.QtCore import QThread, Signal
import time
from typing import Optional
from src.services.tf2_vpk_extract_service import TF2VPKExtractService
from src.shared.logging_config import get_logger
from src.shared.file_utils import ensure_directory_exists
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
        t = TRANSLATIONS.get(self.language, TRANSLATIONS['en'])
        
        try:
            logger.info(f"Начало извлечения текстуры: {self.weapon_key}")
            self.progress.emit(10, t.get('extract_init', 'Initializing extraction...'))
            time.sleep(0.1)
            
            # Проверяем существование VPK файла
            self.progress.emit(20, t.get('extract_checking', 'Checking VPK file...'))
            time.sleep(0.1)
            
            # Создаем директорию экспорта
            ensure_directory_exists(self.export_folder)
            self.progress.emit(30, t.get('extract_searching', 'Searching for texture...'))
            time.sleep(0.1)
            
            # Извлекаем текстуру
            self.progress.emit(50, t.get('extract_extracting', 'Extracting texture...'))
            
            vtf_path = TF2VPKExtractService.extract_texture(
                self.textures_vpk_path,
                self.weapon_key,
                self.export_folder,
                self.export_format
            )
            
            if self.isInterruptionRequested():
                logger.info("Извлечение текстуры прервано пользователем")
                return
            
            if vtf_path:
                self.progress.emit(80, t.get('extract_converting', 'Converting texture...'))
                time.sleep(0.1)
                
                self.progress.emit(100, t.get('extract_completed', 'Extraction completed'))
                
                # Формируем сообщение об успехе
                success_msg = t.get('texture_extracted_success', 'Texture extracted successfully: {path}').format(path=vtf_path)
                logger.info(f"Текстура успешно извлечена: {vtf_path}")
                self.finished.emit(True, success_msg)
            else:
                error_msg = t.get('texture_extract_failed', 'Failed to extract texture').format(weapon=self.weapon_key)
                logger.error(f"Не удалось извлечь текстуру для {self.weapon_key}")
                self.progress.emit(0, t.get('extract_error', 'Extraction error'))
                self.finished.emit(False, error_msg)
                
        except Exception as e:
            error_msg = str(e)
            logger.critical(f"Критическая ошибка при извлечении текстуры: {error_msg}", exc_info=True)
            self.progress.emit(0, t.get('extract_critical_error', 'Critical error'))
            self.error.emit(error_msg)
            self.finished.emit(False, error_msg)

