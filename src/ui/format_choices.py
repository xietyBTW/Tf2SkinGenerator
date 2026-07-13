"""Пер-режимный набор VTF-форматов и план перезаполнения комбобокса.

Чистая логика (без Qt): используется SettingsPanel и покрывается тестами без
импорта PySide6 (тестовая среда местами подменяет PySide6 заглушкой без QtWidgets).
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


def allowed_formats_for_mode(mode):
    """Разрешённые VTF-форматы для режима (источник истины — сервис/шейдер режима).

    None → ограничений нет, показываем полный список VTF_FORMATS.
    """
    if mode == SKYBOX_MODE:
        from src.services.skybox_service import SKYBOX_ALLOWED_FORMATS
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
