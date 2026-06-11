"""
Пер-текстурные настройки (оверрайды поверх глобальных).

Модель «глобальное по умолчанию + разреженный оверрайд»:
  • для материала НЕТ записи  → используются глобальные настройки сборки;
  • для материала ЕСТЬ запись  → её поля переопределяют глобальные.

Важно по UX:
  • простое открытие настроек материала запись НЕ создаёт (UI читает текущее
    состояние, не мутирует);
  • запись появляется только при явном действии (тумблер «свои настройки» off /
    изменение поля);
  • возврат к глобальному — удаление записи (revert).

Запись (override) может быть частичной: какие ключи заданы, те и переопределяют.
Ключи: 'size' (tuple|list), 'format' (str), 'flags' (list), 'options' (dict).
"""

_OVERRIDABLE_KEYS = ('size', 'format', 'flags', 'options')


def effective_settings(global_settings: dict, override: dict = None) -> dict:
    """
    Возвращает эффективные настройки материала: глобальные, переопределённые
    полями оверрайда (если он есть). Глобальные не мутируются.
    """
    eff = dict(global_settings or {})
    if override:
        for k in _OVERRIDABLE_KEYS:
            if k in override and override[k] is not None:
                eff[k] = override[k]
    return eff


def override_badge(override: dict, global_settings: dict = None) -> str:
    """
    Короткая подпись бейджа для карточки с оверрайдом, напр. '1024 · DXT5'.
    Показывает РАЗРЕШЕНИЕ и ФОРМАТ из эффективных настроек. Пусто, если
    оверрайда нет.
    """
    if not override:
        return ''
    eff = effective_settings(global_settings or {}, override)
    size = eff.get('size')
    parts = []
    if isinstance(size, (tuple, list)) and len(size) == 2:
        parts.append(str(size[0]))
    fmt = eff.get('format')
    if fmt:
        parts.append(str(fmt))
    return ' · '.join(parts)
