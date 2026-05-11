"""
Централизованный обработчик ошибок для UI
"""

from typing import Optional, TYPE_CHECKING, Union
from PySide6.QtWidgets import QMessageBox, QWidget
from src.shared.logging_config import get_logger
from src.shared.exceptions import ErrorPayload
from src.shared.error_classifier import classify

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

logger = get_logger(__name__)


class ErrorHandler:
    """Централизованный обработчик ошибок для UI компонентов"""

    @staticmethod
    def show_error(
        parent: Optional['QWidget'],
        error: Union[Exception, ErrorPayload, str],
        context: str = "",
        title: Optional[str] = None,
        language: str = "ru",
    ) -> None:
        """
        Показывает ошибку с понятным объяснением для пользователя
        и разворачиваемыми техническими деталями.

        Args:
            parent:   Родительский виджет для диалога.
            error:    Исключение, ErrorPayload или строка с описанием ошибки.
            context:  Дополнительный контекст (используется в логе и тех. деталях).
            title:    Заголовок окна (если None — используется «Ошибка» / «Error»).
            language: Язык интерфейса ('ru' или 'en').
        """
        from src.ui.error_dialog import ErrorDialog

        # ── Извлекаем техническое сообщение ──────────────────────────────
        if isinstance(error, ErrorPayload):
            raw_msg = error.to_text()
            error_type = error.code
        elif isinstance(error, Exception):
            raw_msg = str(error)
            error_type = type(error).__name__
        else:
            raw_msg = str(error)
            error_type = "Error"

        # ── Лог ──────────────────────────────────────────────────────────
        logger.error(
            f"Ошибка в UI{': ' + context if context else ''}: {error_type}: {raw_msg}",
            exc_info=True,
        )

        # ── Технические детали для раздела «Развернуть» ───────────────────
        parts = []
        if context:
            parts.append(context)
        if error_type not in ("Error", "Exception", "str"):
            parts.append(f"{error_type}: {raw_msg}")
        else:
            parts.append(raw_msg)
        technical_details = "\n\n".join(parts)

        # ── Классификация → понятный заголовок + описание ─────────────────
        full_lookup = f"{context} {raw_msg}"
        friendly_title, friendly_desc = classify(full_lookup, language)

        # ── Диалог ───────────────────────────────────────────────────────
        try:
            ErrorDialog.show(
                parent,
                friendly_title=friendly_title,
                description=friendly_desc,
                technical_details=technical_details,
                language=language,
            )
        except Exception as _dlg_err:
            logger.error(f"Не удалось показать ErrorDialog: {_dlg_err}", exc_info=True)
            QMessageBox.critical(parent, title or ("Ошибка" if language == "ru" else "Error"), technical_details)

    @staticmethod
    def show_warning(
        parent: Optional['QWidget'],
        message: str,
        title: Optional[str] = None,
    ) -> None:
        logger.warning(f"Предупреждение в UI: {message}")
        if title is None:
            title = "Предупреждение"
        QMessageBox.warning(parent, title, message)

    @staticmethod
    def show_info(
        parent: Optional['QWidget'],
        message: str,
        title: Optional[str] = None,
    ) -> None:
        logger.info(f"Информация для пользователя: {message}")
        if title is None:
            title = "Информация"
        QMessageBox.information(parent, title, message)

    @staticmethod
    def show_question(
        parent: Optional['QWidget'],
        message: str,
        title: Optional[str] = None,
    ) -> bool:
        if title is None:
            title = "Вопрос"
        reply = QMessageBox.question(
            parent, title, message, QMessageBox.Yes | QMessageBox.No
        )
        return reply == QMessageBox.Yes
