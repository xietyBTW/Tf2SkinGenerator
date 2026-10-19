"""Общее для модулей API: журнал, язык ответа и реестр вызовов страницы."""

from __future__ import annotations

from typing import Callable, Dict

from src.shared.logging_config import get_logger

#: Имя журнала прежнее, как у модуля до нарезки на пакет.
logger = get_logger('src.app.api')

#: Что страница вправе вызвать: имя → функция. Мост (dev-сервер, окно
#: приложения) зовёт только отсюда. Функция без `@endpoint` наружу не видна.
ENDPOINTS: Dict[str, Callable] = {}


def endpoint(fn: Callable) -> Callable:
    """Открывает функцию странице под её собственным именем."""
    ENDPOINTS[fn.__name__] = fn
    return fn


def _lang(lang: str = '') -> str:
    """
    Язык ответа: тот, что назвали, иначе — из настроек.

    Раньше умолчанием стояло 'ru', и страница его ни разу не переопределяла:
    настройка «Язык приложения» писалась в конфиг и не значила ничего.
    Спрашивать конфиг здесь, а не на странице, потому что отвечает на языке
    Python: знать о выборе должен один, и это он.
    """
    if lang:
        return lang
    from src.config.app_config import AppConfig
    return AppConfig.load_config().get('language') or 'en'


def _t(lang: str) -> dict:
    from src.data.translations import TRANSLATIONS
    return TRANSLATIONS.get(lang, TRANSLATIONS['en'])
