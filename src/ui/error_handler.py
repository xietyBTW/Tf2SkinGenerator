"""
Централизованный обработчик ошибок для UI
"""

from typing import Optional, TYPE_CHECKING
from PySide6.QtWidgets import QMessageBox, QWidget
from src.shared.logging_config import get_logger

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

logger = get_logger(__name__)


class ErrorHandler:
    """Централизованный обработчик ошибок для UI компонентов"""
    
    @staticmethod
    def show_error(
        parent: Optional['QWidget'],
        error: Exception,
        context: str = "",
        title: Optional[str] = None
    ) -> None:
        """
        Показывает ошибку пользователю с детальной информацией
        
        Args:
            parent: Родительский виджет для диалога
            error: Исключение для отображения
            context: Дополнительный контекст ошибки
            title: Заголовок диалога (если None, используется стандартный)
        """
        error_msg = str(error)
        error_type = type(error).__name__
        
        # Логируем ошибку
        logger.error(
            f"Ошибка в UI{': ' + context if context else ''}: {error_type}: {error_msg}",
            exc_info=True
        )
        
        # Формируем сообщение для пользователя
        if context:
            user_message = f"{context}\n\n{error_type}: {error_msg}"
        else:
            user_message = f"{error_type}: {error_msg}"
        
        # Показываем диалог
        if title is None:
            title = "Ошибка"
        
        QMessageBox.critical(parent, title, user_message)
    
    @staticmethod
    def show_warning(
        parent: Optional['QWidget'],
        message: str,
        title: Optional[str] = None
    ) -> None:
        """
        Показывает предупреждение пользователю
        
        Args:
            parent: Родительский виджет для диалога
            message: Текст предупреждения
            title: Заголовок диалога (если None, используется стандартный)
        """
        logger.warning(f"Предупреждение в UI: {message}")
        
        if title is None:
            title = "Предупреждение"
        
        QMessageBox.warning(parent, title, message)
    
    @staticmethod
    def show_info(
        parent: Optional['QWidget'],
        message: str,
        title: Optional[str] = None
    ) -> None:
        """
        Показывает информационное сообщение пользователю
        
        Args:
            parent: Родительский виджет для диалога
            message: Текст сообщения
            title: Заголовок диалога (если None, используется стандартный)
        """
        logger.info(f"Информация для пользователя: {message}")
        
        if title is None:
            title = "Информация"
        
        QMessageBox.information(parent, title, message)
    
    @staticmethod
    def show_question(
        parent: Optional['QWidget'],
        message: str,
        title: Optional[str] = None
    ) -> bool:
        """
        Показывает вопрос пользователю
        
        Args:
            parent: Родительский виджет для диалога
            message: Текст вопроса
            title: Заголовок диалога (если None, используется стандартный)
            
        Returns:
            True если пользователь нажал "Да", False если "Нет"
        """
        if title is None:
            title = "Вопрос"
        
        reply = QMessageBox.question(parent, title, message, 
                                     QMessageBox.Yes | QMessageBox.No)
        return reply == QMessageBox.Yes

