"""Сборка мода: запуск, отмена, ответы на вопросы сборки, проверка"""

from __future__ import annotations

from typing import Dict, List, Optional

from src.app.api._common import _lang, endpoint


@endpoint
def build(params: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    """Собирает VPK. Прогресс и результат приходят событиями"""
    from src.app.session import session
    return session().building.build(dict(params or {}))


@endpoint
def vtf_estimate(size: int = 512, format: str = 'DXT5',
                 flags: Optional[List[str]] = None) -> Dict[str, object]:
    """Сколько примерно займёт VTF при этих настройках

    Оценка, а не измерение: считать по-настоящему значит прогнать кодировщик,
    а число нужно на каждое движение переключателя. Единственное в сводке, что
    нельзя увидеть глазами: 2048 DXT5 весит 5.3 МБ, а 1024 DXT5 - 1.3 МБ, и
    это решает, влезет мод в раздачу или нет
    """
    from src.services.vtf_size import human_size, vtf_bytes

    side = max(1, int(size or 512))
    total = vtf_bytes(side, side, str(format or 'DXT5'), flags or ())
    return {'bytes': total, 'text': human_size(total)}


@endpoint
def cancel_build() -> Dict[str, object]:
    """Просит идущую сборку остановиться"""
    from src.app.session import session
    return session().building.cancel_build()


@endpoint
def diagnose(path: str = '', lang: str = '') -> Dict[str, object]:
    """Проверяет собранный мод, находки приходят событием diagnostics"""
    from src.app.session import session

    lang = _lang(lang)
    return session().diagnose(path, lang=lang)


@endpoint
def answer_model(path: str = '') -> Dict[str, object]:
    """Ответ на `need_model`: свой SMD для сменной части либо пусто - игровая"""
    from src.app.session import session
    return session().building.answer_model(path)


@endpoint
def answer_texture(choice: str = 'game', path: str = '',
                   apply_all: bool = False) -> Dict[str, object]:
    """Ответ на need_texture: игровой оригинал, главная текстура или своя"""
    from src.app.session import session
    return session().building.answer_texture(choice, path, apply_all)
