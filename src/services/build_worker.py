from PySide6.QtCore import Signal
from typing import Optional, Tuple
from src.services.base_worker import StandardWorker, UiRequest
from src.services.vpk_service import VPKService
from src.services.build_request import BuildRequest
from src.shared.logging_config import get_logger
from src.data.translations import TRANSLATIONS

logger = get_logger(__name__)


class BuildWorker(StandardWorker):
    # finished/progress/error наследуются от StandardWorker; добавляем свои:
    sub_progress = Signal(int, str)   # (pct 0-100 или -1=indeterminate, label)
    request_model_file = Signal()
    request_extra_texture = Signal(str, str)  # (material_name, weapon_key) — запрос одной доп. текстуры
    request_extra_model = Signal(str, str)    # (smd_name, weapon_key) - запрос доп. модели (shell и т.д.)
    texture_mismatch_warning = Signal(str)    # (warning_message) — предупреждение о несовпадении текстур

    def __init__(self, request: Optional[BuildRequest] = None, parent=None, **legacy_kwargs):
        """
        request — все параметры сборки (см. BuildRequest). Для совместимости
        со старым стилем вызова по kwargs (BuildWorker(image_path=..., mode=...))
        request можно не передавать — тогда он соберётся из kwargs.
        """
        super().__init__(parent)
        if request is None:
            request = BuildRequest(**legacy_kwargs)
        self.request = request
        self.language = request.language
        self.parent_window = parent

        # Синхронные запросы в UI-поток (диалоги выбора файла/подтверждения).
        # Протокол emit→wait→answer — в UiRequest (base_worker).
        self._model_file_req = UiRequest(self.request_model_file)
        self._extra_texture_req = UiRequest(self.request_extra_texture)
        self._extra_model_req = UiRequest(self.request_extra_model)
        self._texture_mismatch_req = UiRequest(self.texture_mismatch_warning)

    def work(self) -> Tuple[bool, str]:
        r = self.request
        t = TRANSLATIONS.get(r.language, TRANSLATIONS['en'])
        success, message, cancelled = VPKService.build_with_progress(
            r,
            model_file_callback=self._request_model_file_callback if (r.replace_model_enabled and not r.replace_model_path) else None,
            extra_texture_callback=self._request_extra_texture_callback,
            extra_model_callback=self._request_extra_model_callback if r.replace_model_enabled else None,
            texture_mismatch_callback=self._texture_mismatch_callback if r.model_ready_path else None,
            progress_callback=self.progress.emit,
            sub_progress_callback=self.sub_progress.emit,
            cancel_callback=self.isInterruptionRequested,
        )

        if cancelled:
            return False, t.get('build_cancelled', 'Build cancelled by user')
        if success:
            logger.info(f"Сборка успешно завершена: {message}")
        else:
            logger.error(f"Ошибка сборки: {message}")
        return success, message

    # -----------------------------------------------------------------------
    # Запросы в UI-поток: callback для VPKService + set-метод для main_window
    # -----------------------------------------------------------------------
    def _request_model_file_callback(self) -> Optional[str]:
        """Запрашивает файл модели из UI потока."""
        result = self._model_file_req.ask()
        logger.debug(f"Получен файл модели: {result}")
        return result

    def set_model_file_result(self, file_path: Optional[str]) -> None:
        self._model_file_req.answer(file_path)

    def _request_extra_texture_callback(self, material_name: str, weapon_key: str) -> Optional[str]:
        """Запрашивает дополнительную текстуру из UI потока."""
        result = self._extra_texture_req.ask(material_name, weapon_key)
        logger.debug(f"Получена доп. текстура: {result}")
        return result

    def set_extra_texture_result(self, file_path: Optional[str]) -> None:
        """Устанавливает результат выбора доп. текстуры из UI потока."""
        self._extra_texture_req.answer(file_path)

    def _request_extra_model_callback(self, smd_name: str, weapon_key: str) -> Optional[str]:
        """Запрашивает дополнительный SMD файл для части модели из UI потока."""
        result = self._extra_model_req.ask(smd_name, weapon_key)
        logger.debug(f"Получена доп. модель: {result}")
        return result

    def set_extra_model_result(self, file_path: Optional[str]) -> None:
        """Устанавливает результат выбора доп. модели из UI потока."""
        self._extra_model_req.answer(file_path)

    def _texture_mismatch_callback(self, warning_message: str) -> bool:
        """Показывает предупреждение о несовпадении текстур, ожидает решения пользователя."""
        result = self._texture_mismatch_req.ask(warning_message)
        # result: 'continue' = продолжить, всё остальное (включая таймаут) = отменить
        should_continue = (result == 'continue')
        logger.debug(f"Решение пользователя по несовпадению текстур: {result} → continue={should_continue}")
        return should_continue

    def set_texture_mismatch_result(self, decision: str) -> None:
        """Устанавливает решение пользователя: 'continue' или 'cancel'."""
        self._texture_mismatch_req.answer(decision)

