"""Своя модель, модели гирлянды и её QC"""

from __future__ import annotations

from typing import Dict, Optional

from src.app.api._common import _lang, endpoint


@endpoint
def load_custom_model(path: str = '', keep: Optional[bool] = None,
                      lang: str = '') -> Dict[str, object]:
    """Подставляет свою геометрию (SMD) вместо игровой"""
    from src.app.session import session

    lang = _lang(lang)
    return session().custom_model.load_custom_model(path, keep, lang=lang)


@endpoint
def set_custom_fit(fit: Optional[dict] = None) -> Dict[str, object]:
    """Подгонка импортированной модели (масштаб, поворот, сдвиг) - в SMD"""
    from src.app.session import session
    return session().custom_model.set_custom_fit(fit)


@endpoint
def drop_custom_model(lang: str = '') -> Dict[str, object]:
    """Забывает свою модель и возвращает игровую"""
    from src.app.session import session
    return session().custom_model.drop_custom_model(lang=_lang(lang))


@endpoint
def load_decor_model(kind: str = '', path: str = '', lang: str = '') -> Dict[str, object]:
    """Своя модель гирлянды вида `kind` вместо стоковой"""
    from src.app.session import session
    return session().decor.load_decor_model(kind, path, lang=_lang(lang))


@endpoint
def drop_decor_model(kind: str = '', lang: str = '') -> Dict[str, object]:
    """Возвращает стоковую модель гирлянды вида `kind`"""
    from src.app.session import session
    return session().decor.drop_decor_model(kind, lang=_lang(lang))


@endpoint
def qc_text() -> Dict[str, object]:
    """QC своей модели для правки"""
    from src.app.session import session
    return session().custom_model.qc_text()


@endpoint
def save_qc(text: str = '') -> Dict[str, object]:
    """Сохраняет правку QC (пустой текст - вернуть авто-QC)"""
    from src.app.session import session
    return session().custom_model.save_qc(text)
