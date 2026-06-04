"""
Единый фильтр «служебных» материалов модели, которые пользователь НЕ
редактирует и для которых не нужны ни карточки в 2D, ни запрос текстуры
при сборке.

Используется и UI (preview_panel — карточки), и сборкой (vpk_service —
extra_materials / blu_row), чтобы поведение совпадало.

Категории:
  • анатомия персонажа: глаза, зубы и т.п.;
  • оверлеи: sheen / overlay / fresnel (блик поверх базовой текстуры).

Текстура таких материалов в 3D-превью применяется как есть (через
apply_material_map) — фильтр касается только редактируемости.
"""

# Сравнение по подстроке (lower). '_sheen' покрывает и '_sheen2'.
NON_EDITABLE_MAT_PATTERNS = (
    'eyeball', 'eye_l', 'eye_r', 'pupil', 'teeth', 'tongue',
    '_sheen', '_overlay', '_fresnel',
)


def is_editable_material(name: str) -> bool:
    """True, если материал предназначен для редактирования (не глаза/зубы/блик)."""
    n = (name or '').lower()
    return not any(p in n for p in NON_EDITABLE_MAT_PATTERNS)


def filter_editable(names) -> list:
    """Оставляет только редактируемые материалы из списка имён."""
    return [n for n in names if is_editable_material(n)]
