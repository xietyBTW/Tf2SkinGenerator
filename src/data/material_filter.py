"""
Единый фильтр «служебных» материалов модели, которые пользователь НЕ
редактирует: для них не нужны ни карточки в 2D, ни запрос/замена текстуры
при сборке. Один источник правды для UI (preview_panel) и сборки (vpk_service).

Состав:
  • анатомия персонажа: глаза, зубы, язык;
  • системные/эффектные: invulnfx, _invuln, _zombie (движок берёт оригинал сам);
  • оверлеи: sheen / overlay / fresnel (блик поверх базовой текстуры).

Плюс ПОЛЬЗОВАТЕЛЬСКИЕ паттерны из конфига (ключ "material_blacklist") —
добавляются к дефолтным. Формат паттерна:
  • "name"   — совпадение по подстроке (как дефолты, '_sheen' покроет '_sheen2');
  • "=name"  — точное совпадение имени материала (без ложных срабатываний).
"""

# Дефолтные паттерны (подстрока, lower). Их нельзя отключить из UI —
# это материалы, замена которых ломает/не имеет смысла.
DEFAULT_NON_EDITABLE_PATTERNS = (
    # анатомия
    'eyeball', 'eye_l', 'eye_r', 'pupil', 'teeth', 'tongue',
    # системные / эффектные (движок подставит оригинал)
    'invulnfx', '_invuln', '_invun', '_zombie',
    # оверлеи поверх базовой текстуры
    '_sheen', '_overlay', '_fresnel',
)

# Обратная совместимость со старым именем константы.
NON_EDITABLE_MAT_PATTERNS = DEFAULT_NON_EDITABLE_PATTERNS


def _user_patterns() -> list:
    """Пользовательские паттерны блэклиста из конфига (могут отсутствовать)."""
    try:
        from src.config.app_config import AppConfig
        raw = AppConfig.load_config().get('material_blacklist', []) or []
    except Exception:
        return []
    return [p.strip().lower() for p in raw if isinstance(p, str) and p.strip()]


def get_blacklist_patterns() -> list:
    """Полный список паттернов: дефолтные + пользовательские."""
    return list(DEFAULT_NON_EDITABLE_PATTERNS) + _user_patterns()


def _matches(name_lower: str, pattern: str) -> bool:
    if pattern.startswith('='):
        return name_lower == pattern[1:]
    return pattern in name_lower


def is_editable_material(name: str) -> bool:
    """True, если материал предназначен для редактирования (не в блэклисте)."""
    n = (name or '').lower()
    return not any(_matches(n, p) for p in get_blacklist_patterns())


def filter_editable(names) -> list:
    """Оставляет только редактируемые материалы из списка имён."""
    return [n for n in names if is_editable_material(n)]
