"""
Воркер для асинхронного извлечения текстуры из VPK в фоновом потоке
"""

from PySide6.QtCore import QThread, Signal
from typing import List, Optional, Tuple
from src.services.tf2_vpk_extract_service import TF2VPKExtractService
from src.shared.logging_config import get_logger
from src.data.translations import TRANSLATIONS

logger = get_logger(__name__)


class ExtractTextureWorker(QThread):
    """
    Воркер для выполнения извлечения текстуры в фоновом потоке.

    Поддерживает два режима:
      • weapon_key задан, hand_textures=None → извлечение текстуры оружия
      • hand_textures задан → извлечение текстур рук (materials/models/player/...)
    """

    # Сигналы для связи с UI
    finished = Signal(bool, str)  # (success: bool, message: str)
    progress = Signal(int, str)   # (percentage: int, status: str)
    error = Signal(str)           # (error_message: str)

    def __init__(
        self,
        textures_vpk_path: str,
        weapon_key: str,
        export_folder: str,
        export_format: str = "PNG",
        language: str = "en",
        hand_textures: Optional[List[Tuple[str, str]]] = None,
        parent=None,
    ):
        """
        Args:
            textures_vpk_path: Путь к tf2_textures_dir.vpk
            weapon_key:        Ключ оружия (например, c_scattergun) — используется
                               только при hand_textures=None
            export_folder:     Папка для экспорта
            export_format:     Формат экспорта (VTF, PNG, TGA, JPG)
            language:          Язык для сообщений
            hand_textures:     Если задан — список (folder, vtf_name) для рук;
                               тогда weapon_key игнорируется
            parent:            Родительский объект Qt
        """
        super().__init__(parent)
        self.textures_vpk_path = textures_vpk_path
        self.weapon_key = weapon_key
        self.export_folder = export_folder
        self.export_format = export_format
        self.language = language
        self.hand_textures = hand_textures

    def run(self) -> None:
        """Выполняет извлечение текстуры в фоновом потоке."""
        try:
            if self.hand_textures is not None:
                # ── Режим рук ──────────────────────────────────────────────── #
                success, message, cancelled = TF2VPKExtractService.extract_hand_textures_with_progress(
                    self.textures_vpk_path,
                    self.hand_textures,
                    self.export_folder,
                    self.export_format,
                    language=self.language,
                    progress_callback=self.progress.emit,
                    cancel_callback=self.isInterruptionRequested,
                )
            else:
                # ── Режим оружия ───────────────────────────────────────────── #
                success, message, cancelled = TF2VPKExtractService.extract_texture_with_progress(
                    self.textures_vpk_path,
                    self.weapon_key,
                    self.export_folder,
                    self.export_format,
                    language=self.language,
                    progress_callback=self.progress.emit,
                    cancel_callback=self.isInterruptionRequested,
                )

            if cancelled:
                self.finished.emit(False, message)
                return

            if success:
                label = self.weapon_key if not self.hand_textures else "hands"
                logger.info(f"Текстура успешно извлечена [{label}]: {message}")
                self.finished.emit(True, message)
            else:
                logger.error(f"Не удалось извлечь текстуру для {self.weapon_key}: {message}")
                self.finished.emit(False, message)

        except Exception as exc:
            error_msg = str(exc)
            logger.critical(f"Критическая ошибка при извлечении текстуры: {error_msg}", exc_info=True)
            self.error.emit(error_msg)
            self.finished.emit(False, error_msg)

