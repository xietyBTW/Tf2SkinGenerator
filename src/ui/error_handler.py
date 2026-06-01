"""
Централизованный обработчик ошибок для UI.
Все диалоги используют StyledDialog вместо системного QMessageBox.
"""

from typing import Optional, TYPE_CHECKING, Union
from PySide6.QtWidgets import QMessageBox, QWidget, QVBoxLayout, QLabel, QPushButton
from src.shared.logging_config import get_logger
from src.shared.exceptions import ErrorPayload
from src.shared.error_classifier import classify

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

logger = get_logger(__name__)


def _simple_dialog(parent, title: str, message: str,
                   buttons: list, icon: str = "") -> str:
    """
    Показывает простой стилизованный диалог с одной кнопкой или несколькими.

    Returns:
        Текст нажатой кнопки.
    """
    from src.ui.styled_dialog import StyledDialog

    dlg = StyledDialog(parent, title=title, width=440)
    c = dlg._c
    root = QVBoxLayout(dlg)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    root.addWidget(dlg.make_header(title))

    body = QVBoxLayout()
    body.setContentsMargins(20, 16, 20, 16)
    msg_lbl = QLabel(message)
    msg_lbl.setWordWrap(True)
    msg_lbl.setStyleSheet(f"color: {c['text']}; font-size: 12px; line-height: 1.5;")
    body.addWidget(msg_lbl)
    root.addLayout(body)
    root.addWidget(dlg.divider())

    result = [buttons[-1]]   # дефолт — последняя (primary)

    btns = []
    for label in buttons:
        btn = QPushButton(label)
        btn.clicked.connect(lambda _, l=label, d=dlg: (result.__setitem__(0, l), d.accept()))
        btns.append(btn)

    root.addWidget(dlg.make_footer(btns))
    dlg.exec()
    return result[0]


class ErrorHandler:
    """Централизованный обработчик ошибок для UI компонентов."""

    @staticmethod
    def show_error(
        parent: Optional['QWidget'],
        error: Union[Exception, ErrorPayload, str],
        context: str = "",
        title: Optional[str] = None,
        language: str = "ru",
    ) -> None:
        from src.ui.error_dialog import ErrorDialog

        if isinstance(error, ErrorPayload):
            raw_msg = error.to_text()
            error_type = error.code
        elif isinstance(error, Exception):
            raw_msg = str(error)
            error_type = type(error).__name__
        else:
            raw_msg = str(error)
            error_type = "Error"

        logger.error(
            f"Ошибка в UI{': ' + context if context else ''}: {error_type}: {raw_msg}",
            exc_info=True,
        )

        parts = []
        if context:
            parts.append(context)
        if error_type not in ("Error", "Exception", "str"):
            parts.append(f"{error_type}: {raw_msg}")
        else:
            parts.append(raw_msg)
        technical_details = "\n\n".join(parts)

        full_lookup = f"{context} {raw_msg}"
        friendly_title, friendly_desc = classify(full_lookup, language)

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
            QMessageBox.critical(
                parent,
                title or ("Ошибка" if language == "ru" else "Error"),
                technical_details,
            )

    @staticmethod
    def show_warning(
        parent: Optional['QWidget'],
        message: str,
        title: Optional[str] = None,
    ) -> None:
        logger.warning(f"Предупреждение в UI: {message}")
        t = title or "Предупреждение"
        try:
            _simple_dialog(parent, t, message, ["OK"])
        except Exception:
            QMessageBox.warning(parent, t, message)

    @staticmethod
    def show_info(
        parent: Optional['QWidget'],
        message: str,
        title: Optional[str] = None,
    ) -> None:
        logger.info(f"Информация для пользователя: {message}")
        t = title or "Информация"
        try:
            _simple_dialog(parent, t, message, ["OK"])
        except Exception:
            QMessageBox.information(parent, t, message)

