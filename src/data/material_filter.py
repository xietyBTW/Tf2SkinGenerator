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

def _user_patterns() -> list:
    """Пользовательские паттерны блэклиста из конфига (могут отсутствовать)."""
    try:
        from src.config.app_config import AppConfig
        raw = AppConfig.load_config().get('material_blacklist', []) or []
    except Exception:
        return []
    return [p.strip().lower() for p in raw if isinstance(p, str) and p.strip()]


def get_blacklist_patterns() -> list:
    """Встроенный классификатор «служебных» материалов (для is_editable_material).

    ВАЖНО: тут ТОЛЬКО дефолтные паттерны. Они решают, основная это текстура или
    «Прочее». Пользовательский ЧС (настройки) сюда НЕ входит — он лишь скрывает
    карточку, не меняя класс материала (см. is_user_blacklisted)."""
    return list(DEFAULT_NON_EDITABLE_PATTERNS)


def _matches(name_lower: str, pattern: str) -> bool:
    if pattern.startswith('='):
        return name_lower == pattern[1:]
    return pattern in name_lower


def is_editable_material(name: str, patterns: list = None) -> bool:
    """
    True — основная (редактируемая) текстура; False — служебная («Прочее»).

    Классификатор использует ТОЛЬКО встроенные дефолтные паттерны (глаза/убер/
    зомби/оверлеи). Пользовательский ЧС из настроек сюда НЕ входит: он не меняет
    класс материала, а лишь скрывает его карточку (is_user_blacklisted).

    Args:
        patterns: Готовый список паттернов (по умолчанию — дефолтные).
    """
    if patterns is None:
        patterns = DEFAULT_NON_EDITABLE_PATTERNS
    n = (name or '').lower()
    return not any(_matches(n, p) for p in patterns)


def is_user_blacklisted(name: str) -> bool:
    """True — материал в пользовательском ЧС (настройки → «Блэклист материалов»).

    Такой материал НЕ показываем карточкой (ни в основных, ни в «Прочем»), но в
    мод он пишется оригинальной игровой текстурой (как и прочие служебные)."""
    n = (name or '').lower()
    return any(_matches(n, p) for p in _user_patterns())


def filter_editable(names) -> list:
    """Оставляет только редактируемые (не служебные) материалы из списка имён."""
    return [n for n in names if is_editable_material(n)]
