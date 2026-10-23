"""War Paint"""

from __future__ import annotations

from typing import Dict, List, Optional

from src.app.api._common import _lang, endpoint


@endpoint
def paintkits(lang: str = '') -> Dict[str, object]:
    """War Paint игры для показанного оружия: [{id, name, item, wears, team}]"""
    from src.app.session import session
    return session().paintkits.paintkits(_lang(lang))


def _cards(materials) -> Optional[List[str]]:
    """Отмеченные материалы War Paint: None - как по умолчанию"""
    if materials is None:
        return None
    return [str(m) for m in materials if isinstance(m, str) and m][:64]


@endpoint
def paintkit_materials(item: int = 0) -> Dict[str, object]:
    """Материалы оружия для War Paint: {materials: [{card, game}]}"""
    from src.app.session import session
    return session().paintkits.paintkit_materials(int(item))


@endpoint
def apply_paintkit(kit: int, item: int, wear: int = 1, seed: int = 0,
                   size: int = 1024, layout: int = 0,
                   materials: Optional[List[str]] = None) -> Dict[str, object]:
    """Накладывает War Paint на отмеченные материалы. Готовность придёт событием"""
    from src.app.session import session
    return session().paintkits.apply_paintkit(int(kit), int(item), int(wear), int(seed),
                                              int(size), int(layout), _cards(materials))


@endpoint
def preview_paintkit(kit: int, item: int, wear: int = 1, seed: int = 0,
                     layout: int = 0, materials: Optional[List[str]] = None
                     ) -> Dict[str, object]:
    """Предпросмотр War Paint (512 px): {images: {карточка: png}} - на модель временно"""
    from src.app.session import session
    return session().paintkits.preview_paintkit(int(kit), int(item), int(wear), int(seed),
                                                int(layout), _cards(materials))


@endpoint
def paintkit_layout(kit: int, item: int, layout: int = 0) -> Dict[str, object]:
    """Раскладка War Paint по деталям: слои, детали и карта треугольников"""
    from src.app.session import session
    return session().paintkits.paintkit_layout(int(kit), int(item), int(layout))


@endpoint
def set_paintkit_layout(kit: int, assign: Optional[Dict[str, int]] = None) -> Dict[str, object]:
    """Раскладка человека {деталь: слой}; пусто - вернуть автомат"""
    from src.app.session import session
    return session().paintkits.set_paintkit_layout(int(kit), assign)
