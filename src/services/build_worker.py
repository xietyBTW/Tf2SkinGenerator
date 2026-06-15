from PySide6.QtCore import Signal, QMutex, QWaitCondition
from typing import Optional, Tuple
from src.services.base_worker import StandardWorker
from src.services.vpk_service import VPKService
from src.services.build_request import BuildRequest
from src.shared.logging_config import get_logger
from src.data.translations import TRANSLATIONS

logger = get_logger(__name__)

# Специальный sentinel-объект: означает "ответ ещё не получен"
# None — допустимый ответ (пользователь отказался), поэтому нельзя использовать None как sentinel
_SENTINEL = object()


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

        self._model_file_mutex = QMutex()
        self._model_file_condition = QWaitCondition()
        self._model_file_result = _SENTINEL

        self._extra_texture_mutex = QMutex()
        self._extra_texture_condition = QWaitCondition()
        self._extra_texture_result = _SENTINEL

        self._extra_model_mutex = QMutex()
        self._extra_model_condition = QWaitCondition()
        self._extra_model_result = _SENTINEL

        self._texture_mismatch_mutex = QMutex()
        self._texture_mismatch_condition = QWaitCondition()
        self._texture_mismatch_result = _SENTINEL  # True = continue, False/None = cancel

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
    # Внутренний helper: emit сигнала → ждёт ответа от UI потока
    # -----------------------------------------------------------------------
    def _emit_and_wait(self, mutex: QMutex, condition: QWaitCondition,
                       result_attr: str, signal, *signal_args) -> Optional[str]:
        """
        Правильный thread-safe паттерн для запроса данных из UI потока:

        Воркер (фоновый поток):
          1. Берёт мьютекс
          2. Сбрасывает результат в _SENTINEL
          3. Атомарно отпускает мьютекс и ждёт (condition.wait)
             → в этот момент мьютекс свободен

        UI поток (обрабатывает сигнал через QueuedConnection):
          4. Показывает диалог пользователю
          5. Берёт мьютекс (теперь свободен, т.к. воркер ждёт)
          6. Записывает результат
          7. wakeAll() → воркер просыпается

        Воркер снова берёт мьютекс (после wait):
          8. Читает результат
          9. Отпускает мьютекс

        ВАЖНО: сигнал эмитируется ДО wait(), но ПОСЛЕ сброса sentinel.
        Это безопасно потому что:
        - Если UI успеет ответить до wait() → sentinel уже установлен,
          UI запишет результат и wakeAll() ничего не разбудит (ещё никто не ждёт).
          Воркер дойдёт до while — увидит что sentinel != _SENTINEL — и не войдёт в wait().
        - Если UI ответит после wait() → штатный путь, wakeAll() разбудит воркера.
        """
        mutex.lock()
        try:
            # Шаг 1: сбрасываем под мьютексом
            setattr(self, result_attr, _SENTINEL)
        finally:
            mutex.unlock()

        # Шаг 2: эмитим сигнал (UI получит его через QueuedConnection)
        # НЕ держим мьютекс при emit — это может вызвать дедлок если UI
        # попытается ответить пока мы ещё держим мьютекс
        signal.emit(*signal_args)

        # Шаг 3: берём мьютекс и ждём
        mutex.lock()
        try:
            # Проверяем: возможно UI уже успел ответить пока мы были между emit и lock
            while getattr(self, result_attr) is _SENTINEL:
                # Атомарно отпускает мьютекс и ждёт пробуждения.
                # False = таймаут (5 мин), True = разбужен wakeAll()
                if not condition.wait(mutex, 300000):
                    logger.warning(f"Таймаут ожидания ответа от UI для {result_attr}")
                    break
            result = getattr(self, result_attr)
            return result if result is not _SENTINEL else None
        finally:
            mutex.unlock()

    def _request_model_file_callback(self) -> Optional[str]:
        """Запрашивает файл модели из UI потока."""
        logger.debug("Запрос файла модели из UI")
        result = self._emit_and_wait(
            self._model_file_mutex,
            self._model_file_condition,
            '_model_file_result',
            self.request_model_file
        )
        logger.debug(f"Получен файл модели: {result}")
        return result

    def set_model_file_result(self, file_path: Optional[str]) -> None:
        logger.debug(f"set_model_file_result вызван: {file_path}")
        self._model_file_mutex.lock()
        self._model_file_result = file_path
        self._model_file_condition.wakeAll()
        self._model_file_mutex.unlock()

    def _request_extra_texture_callback(self, material_name: str, weapon_key: str) -> Optional[str]:
        """Запрашивает дополнительную текстуру из UI потока."""
        logger.debug(f"Запрос доп. текстуры из UI: material={material_name}, weapon={weapon_key}")
        result = self._emit_and_wait(
            self._extra_texture_mutex,
            self._extra_texture_condition,
            '_extra_texture_result',
            self.request_extra_texture,
            material_name,
            weapon_key
        )
        logger.debug(f"Получена доп. текстура: {result}")
        return result

    def set_extra_texture_result(self, file_path: Optional[str]) -> None:
        """Устанавливает результат выбора доп. текстуры из UI потока."""
        logger.debug(f"set_extra_texture_result вызван: {file_path}")
        self._extra_texture_mutex.lock()
        self._extra_texture_result = file_path
        self._extra_texture_condition.wakeAll()
        self._extra_texture_mutex.unlock()

    def _request_extra_model_callback(self, smd_name: str, weapon_key: str) -> Optional[str]:
        """Запрашивает дополнительный SMD файл для части модели из UI потока."""
        logger.debug(f"Запрос доп. модели из UI: smd={smd_name}, weapon={weapon_key}")
        result = self._emit_and_wait(
            self._extra_model_mutex,
            self._extra_model_condition,
            '_extra_model_result',
            self.request_extra_model,
            smd_name,
            weapon_key
        )
        logger.debug(f"Получена доп. модель: {result}")
        return result

    def set_extra_model_result(self, file_path: Optional[str]) -> None:
        """Устанавливает результат выбора доп. модели из UI потока."""
        logger.debug(f"set_extra_model_result вызван: {file_path}")
        self._extra_model_mutex.lock()
        self._extra_model_result = file_path
        self._extra_model_condition.wakeAll()
        self._extra_model_mutex.unlock()

    def _texture_mismatch_callback(self, warning_message: str) -> bool:
        """Показывает предупреждение о несовпадении текстур, ожидает решения пользователя."""
        logger.debug("Запрос подтверждения: несовпадение текстур")
        result = self._emit_and_wait(
            self._texture_mismatch_mutex,
            self._texture_mismatch_condition,
            '_texture_mismatch_result',
            self.texture_mismatch_warning,
            warning_message
        )
        # result: 'continue' = продолжить, всё остальное = отменить
        should_continue = (result == 'continue')
        logger.debug(f"Решение пользователя по несовпадению текстур: {result} → continue={should_continue}")
        return should_continue

    def set_texture_mismatch_result(self, decision: str) -> None:
        """Устанавливает решение пользователя: 'continue' или 'cancel'."""
        logger.debug(f"set_texture_mismatch_result вызван: {decision}")
        self._texture_mismatch_mutex.lock()
        self._texture_mismatch_result = decision
        self._texture_mismatch_condition.wakeAll()
        self._texture_mismatch_mutex.unlock()

