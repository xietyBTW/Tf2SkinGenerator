"""Части модели: острова, области, текстуры и материалы частей"""

from __future__ import annotations

from typing import Dict, List, Optional

from src.app.api._common import _lang, endpoint


@endpoint
def set_part_detail(material: str = '', detail: float = 0.0) -> Dict[str, object]:
    """Раздробить все куски одинаково (0 - геометрия, 1 - швы развёртки)"""
    from src.app.session import session
    return session().parts.set_part_detail(material, detail)


@endpoint
def toggle_part_island(material: str = '', group: int = 0,
                       island: int = 0) -> Dict[str, object]:
    """Отрезать названный остров развёртки или прирастить его обратно"""
    from src.app.session import session
    return session().parts.toggle_part_island(material, group, island)


@endpoint
def part_mask(material: str = '', part: int = 0) -> Dict[str, object]:
    """Картинка-подсветка части: её форма на развёртке"""
    from src.app.session import session
    return session().parts.part_mask(material, part)


@endpoint
def part_shape(material: str = '', part: int = 0,
               layer: Optional[int] = None) -> Dict[str, object]:
    """Развёртка одной части - для окна посадки картинки.
    `layer` - какую из её картинок правят; None - кладут новую"""
    from src.app.session import session
    return session().parts.part_shape(material, part, layer)


@endpoint
def add_part_region(material: str = '',
                    triangles: Optional[List[int]] = None) -> Dict[str, object]:
    """Выделенное ножницами - в отдельную часть (номера треугольников меша)"""
    from src.app.session import session
    return session().parts.add_part_region(material, triangles)


@endpoint
def remove_part_region(material: str = '', region: int = 0) -> Dict[str, object]:
    """Вернуть область, выделенную ножницами, туда, откуда её вырезали"""
    from src.app.session import session
    return session().parts.remove_part_region(material, region)


@endpoint
def parts(material: str = '', known_shape: str = '') -> Dict[str, object]:
    """Части модели: список кусков и номер части для каждого треугольника

    ``known_shape`` - отпечаток разбиения, который уже есть у страницы. Совпал -
    карты треугольников не отдаются: они занимают почти весь ответ, а меняются
    только от резки
    """
    from src.app.session import session
    return session().parts.describe(material, known_shape)


@endpoint
def set_part_texture(material: str = '', part: int = 0,
                     path: Optional[str] = None,
                     options: Optional[Dict[str, object]] = None,
                     layer: Optional[int] = None) -> Dict[str, object]:
    """Картинки одной части - слоями: новая ложится поверх, `layer` называет
    слой для правки посадки, замены или снятия (без него снимаются все)

    options - посадка: вписать/заполнить/растянуть, поворот, масштаб, сдвиг.
    Без пути, но с настройкой, - правка уже положенной картинки
    """
    from src.app.session import session
    return session().parts.set_part_texture(material, part, path, options, layer)


@endpoint
def move_part_texture(material: str = '', part: int = 0,
                      layer: int = 0, to: int = 0) -> Dict[str, object]:
    """Переставляет картинку части в стопке: слой `layer` на место `to`
    (индексы снизу вверх). Выше в стопке - поверх"""
    from src.app.session import session
    return session().parts.move_part_texture(material, part, layer, to)


@endpoint
def set_part_colors(material: str = '',
                    colors: Optional[Dict[str, str]] = None,
                    strength: Optional[float] = None,
                    exact: Optional[bool] = None) -> Dict[str, object]:
    """Красит части: {часть: '#rrggbb'}; значение None снимает цвет

    `exact` - красить ровно выбранным цветом, а не смешивать его с оригиналом
    """
    from src.app.session import session
    return session().parts.set_part_colors(material, colors, strength, exact)


@endpoint
def set_part_edge(material: str = '', width: float = 0.0,
                  color: str = '') -> Dict[str, object]:
    """Окантовка частей: ширина полосы по краю (в долях стороны) и её цвет"""
    from src.app.session import session
    return session().parts.set_part_edge(material, width, color)


@endpoint
def clear_parts(material: str = '') -> Dict[str, object]:
    """Снимает с частей все картинки и цвета"""
    from src.app.session import session
    return session().parts.clear_parts(material)


@endpoint
def set_part_material(material: str = '', parts: Optional[list] = None,
                      target: str = '') -> Dict[str, object]:
    """Части - в свой материал ('' - новый, имя - в этот, '-' - обратно в общий)"""
    from src.app.session import session
    return session().parts.set_part_material(material, parts, target)


@endpoint
def drop_part_material(name: str = '', material: str = '') -> Dict[str, object]:
    """Возвращает все части материала в общий, его карточка исчезает.
    `material` - только части этого материала (родной материал модели
    получает их от разных)"""
    from src.app.session import session
    return session().parts.drop_part_material(name, material)


@endpoint
def load_part_model(group: str = '', path: str = '', lang: str = '') -> Dict[str, object]:
    """Своя модель снаряда, заряженного в оружие (группа-снаряд `group`)"""
    from src.app.session import session
    return session().load_part_model(group, path, lang=_lang(lang))


@endpoint
def drop_part_model(group: str = '', lang: str = '') -> Dict[str, object]:
    """Возвращает снаряду группы `group` игровую модель"""
    from src.app.session import session
    return session().drop_part_model(group, lang=_lang(lang))
