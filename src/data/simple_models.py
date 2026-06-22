"""
Реестр «простых» категорий моделей: снаряды (w_models), пикапы (аптечки/патроны),
реквизит насмешек.

У всех трёх одинаковая форма данных (``key -> {ru, en, mdl_path}``) и один и тот же
pipeline (MDL из VPK → Crowbar → QC → текстуры/команды). Раньше каждая категория
дублировала: таблицу, геттер имени, populate-метод в UI и блок построения ``mode``.
Здесь — единый геттер имени и реестр «категория → таблица + префикс mode», по
которому UI и сборка работают ОДНОЙ параметризованной логикой вместо трёх копий.

Добавить новую такую категорию = добавить таблицу-модуль и одну строку в реестр.
"""

from typing import Dict, NamedTuple

from src.data.pickups import PICKUPS, PICKUP_MODE_PREFIX
from src.data.projectiles import PROJECTILES, PROJECTILE_MODE_PREFIX
from src.data.taunt_props import TAUNT_PROPS, TAUNT_PROP_MODE_PREFIX


def model_display_name(table: Dict[str, dict], key: str, language: str = "ru") -> str:
    """Локализованное имя модели из таблицы ``{key: {ru, en, ...}}``.

    Fallback: запрошенный язык → ru → сам ключ. Единый геттер для всех простых
    категорий (заменил get_projectile_name / get_pickup_name / get_taunt_prop_name).
    """
    data = table.get(key, {})
    return data.get(language, data.get("ru", key))


class SimpleModelCategory(NamedTuple):
    """Описание простой категории: таблица моделей + префикс её ``mode``."""
    table: Dict[str, dict]
    mode_prefix: str


#: Имя категории (как в UI-комбо) → таблица + префикс mode (``mode = f"{prefix}{key}"``).
SIMPLE_MODEL_CATEGORIES: Dict[str, SimpleModelCategory] = {
    "projectile": SimpleModelCategory(PROJECTILES, PROJECTILE_MODE_PREFIX),
    "pickup": SimpleModelCategory(PICKUPS, PICKUP_MODE_PREFIX),
    "taunt": SimpleModelCategory(TAUNT_PROPS, TAUNT_PROP_MODE_PREFIX),
}
