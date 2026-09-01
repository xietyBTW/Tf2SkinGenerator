"""Пер-режимный набор VTF-форматов и план перезаполнения комбобокса.

Чистая логика (без Qt): используется SettingsPanel и покрывается тестами без
импорта Qt: правила формата к виджетам отношения не имеют.
"""

from src.data.skyboxes import SKYBOX_MODE
from src.shared.constants import VTF_FORMATS  # re-export: settings_panel импортит отсюда

# CritHIT: анимированная translucent-текстура (шейдер UnlitGeneric + $translucent) —
# обязателен альфа-канал. DXT5 — лучший дефолт (сжатый, плавная интерполированная
# альфа, идеальна для градиента свечения); RGBA8888 — без потерь (максимум
# качества, больше размер); DXT3 — сжатый с чёткой 4-битной альфой (хуже для
# плавных градиентов, но валиден). Форматы без альфы (DXT1/RGB888) сломали бы
# полупрозрачность. Порядок = приоритет: DXT5 первым остаётся дефолтом.
CRIT_ALLOWED_FORMATS = ("DXT5", "RGBA8888", "DXT3")

# Skybox: остальные галки флагов/опций к граням неба не относятся вообще.
# CLAMPS/CLAMPT/NOLOD и отсутствие мипов SkyboxService выставляет сам (без
# CLAMP видны швы на стыках), фильтрация мипов без мипов бессмысленна,
# normal map/reflectivity/gamma — не про шейдер sky. Осмысленный выбор один:
# POINTSAMPLE — отключает билинейное сглаживание, из-за которого при
# растягивании грани на 90° обзора звёзды выглядят мягкими пятнами.
SKYBOX_ALLOWED_FLAGS = ("POINTSAMPLE",)


#: Скайбокс склеивается из граней без альфы — форматы с ней дали бы швы.
SKYBOX_ALLOWED_FORMATS = ("DXT1", "BGR888")


def allowed_flags_for_mode(mode):
    """Галки флагов/опций VTF, осмысленные для режима (имена флагов).

    None → ограничений нет, показываем весь набор.
    """
    if mode == SKYBOX_MODE:
        return list(SKYBOX_ALLOWED_FLAGS)
    return None


def allowed_formats_for_mode(mode):
    """Разрешённые VTF-форматы для режима (источник истины — сервис/шейдер режима).

    None → ограничений нет, показываем полный список VTF_FORMATS.
    """
    if mode == SKYBOX_MODE:
        return list(SKYBOX_ALLOWED_FORMATS)
    if mode == "critHIT":
        return list(CRIT_ALLOWED_FORMATS)
    return None


def plan_format_choices(current_items, current_text, allowed):
    """План перезаполнения списка форматов.

    Возвращает (target_items, target_index) либо None, если список уже совпадает.
    Текущий выбор сохраняется, если остаётся допустимым, иначе берётся первый.
    """
    target = list(allowed) if allowed else list(VTF_FORMATS)
    if list(current_items) == target:
        return None
    idx = target.index(current_text) if current_text in target else 0
    return target, idx
