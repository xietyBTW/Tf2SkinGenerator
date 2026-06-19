"""
Чистая (без Qt) логика «какие 2D-карточки материалов показать».

Раньше выбор материалов под карточки был размазан по нескольким точкам
(_on_3d_multi_material, update_extra_slots_spy_masks, кастомная модель) с
разной фильтрацией. Здесь — единый, тестируемый источник: режим/входные данные
→ список MaterialCardSpec. Рендер (Qt) остаётся в preview_panel и просто
потребляет эти спеки.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List


@dataclass(frozen=True)
class MaterialCardSpec:
    """Описание одной карточки материала."""
    name: str          # имя материала (ключ слота, lowercase-совместимое)
    display_name: str  # подпись в UI


def _dedup_keep_order(names: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for n in names:
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def editable_material_cards(material_names: Iterable[str]) -> List[MaterialCardSpec]:
    """
    Карточки для материалов геометрии (оружие/шапки/персонажи): служебные
    (глаза/зубы/sheen-оверлеи и т.п.) отбрасываются единым блэклистом. Если
    после фильтра пусто (вся модель «служебная») — возвращаем все имена, чтобы
    в 2D не было пустоты. Порядок сохранён, дубли убраны.
    """
    from src.data.material_filter import is_editable_material, is_user_blacklisted
    names = _dedup_keep_order(material_names)
    # Пользовательский ЧС скрывает карточку полностью (даже если материал основной).
    visible = [n for n in names if not is_user_blacklisted(n)]
    editable = [n for n in visible if is_editable_material(n)]
    chosen = editable if editable else (visible or names)
    return [MaterialCardSpec(n, n) for n in chosen]


def spy_mask_cards(vtf_names: Iterable[str], lang: str = "en") -> List[MaterialCardSpec]:
    """
    Фиксированные карточки масок маскировки шпиона: имя = VTF-файл маски,
    подпись = название класса (локализованное).
    """
    from src.data.player_characters import SPY_DISGUISE_MASKS
    disp = {m[1]: (m[3] if lang == "ru" else m[2]) for m in SPY_DISGUISE_MASKS}
    return [MaterialCardSpec(n, disp.get(n, n)) for n in _dedup_keep_order(vtf_names)]
