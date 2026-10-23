"""Свой материал: карты материала, настройки текстур, правка VMT"""

from __future__ import annotations

from typing import Dict, List, Optional

from src.app.api._common import _lang, _t, endpoint, logger


@endpoint
def material_map_schema(lang: str = '') -> Dict[str, object]:
    """Какие карты материала бывают и что у них настраивается"""
    from src.data.material_maps import MAP_DISPLAY_ORDER, MATERIAL_MAPS
    from src.services import lightwarp

    lang = _lang(lang)
    t = _t(lang)

    def numeric_fields(cfg: dict) -> List[dict]:
        out = []
        for param in cfg.get('numeric', ()):
            field = {
                'param': param,
                'label': t.get('map_' + param.lstrip('$').lower(), param.lstrip('$')),
                'default': str(cfg.get('extra_vmt', {}).get(param, '')),
                'choices': None,
            }
            # Режим смешивания detail - не число, а именованные варианты;
            # какие допустимы, решает MATERIAL_MAPS (номера по вики Valve)
            allowed = cfg.get('choices', {}).get(param)
            if allowed:
                field['choices'] = [{'value': v, 'label': t.get(f'map_blend_{v}', v)}
                                    for v in allowed]
            out.append(field)
        return out

    def settings_fields(cfg: dict) -> List[dict]:
        """Свои настройки карты (не параметры VMT) - поля со всем, что нужно
        странице: вид, варианты, пределы, когда поле видно"""
        out = []
        for key, rule in cfg.get('settings', {}).items():
            field = {'key': key, 'label': t.get(f'set_{key}_label', t.get(f'set_{key}', key)),
                     'tip': t.get(f'set_{key}_tip', ''),
                     'note': t.get(f'set_{key}_note', ''),
                     'default': rule.get('default', ''), 'show_if': rule.get('show_if')}
            if 'choices' in rule:
                field['kind'] = 'choice'
                field['choices'] = [{'value': v, 'label': t.get(f'set_{key}_{v}', v)}
                                    for v in rule['choices']]
            elif rule.get('color'):
                field['kind'] = 'color'
            elif rule.get('file'):
                field['kind'] = 'file'
            else:
                field.update(kind='number', min=rule['min'], max=rule['max'],
                             step=rule.get('step', 1), slider=bool(rule.get('slider')))
            field['display'] = rule.get('display', rule.get('default', ''))
            out.append(field)
        return out

    from src.services import phongwarp

    return {
        'title': t.get('material_maps_title', 'Material Maps'),
        'intro': t.get('material_maps_intro', ''),
        'auto_label': t.get('map_auto', 'Auto from texture (no file)'),
        'auto_tip': t.get('map_auto_tip', ''),
        'threshold_label': t.get('map_threshold', 'Threshold'),
        'maps': [
            {
                'id': map_id,
                'title': t.get(f'map_{map_id}', map_id.capitalize()),
                'tip': t.get(f'map_{map_id}_tip', ''),
                'badge': MATERIAL_MAPS[map_id]['format'],
                'vmt_only': bool(MATERIAL_MAPS[map_id].get('vmt_only')),
                'derive': bool(MATERIAL_MAPS[map_id].get('derive_kind')),
                'numeric': numeric_fields(MATERIAL_MAPS[map_id]),
                'generator': MATERIAL_MAPS[map_id].get('generator'),
                'settings': settings_fields(MATERIAL_MAPS[map_id]),
                'preview': MATERIAL_MAPS[map_id].get('preview'),
            }
            for map_id in MAP_DISPLAY_ORDER
        ],
        # Конструктор градиента блика (services/phongwarp.py)
        'phongwarp': {
            'defaults': dict(phongwarp.DEFAULTS),
            'custom': 'custom',
            'max_bands': phongwarp.MAX_BANDS,
            'max_stops': lightwarp.MAX_STOPS,
            'presets': [{'id': key, 'label': t.get(f'phongwarp_{key}', key)}
                        for key in phongwarp.PRESETS],
            'labels': {
                **{key: t.get(f'phongwarp_{key}', key) for key in (
                    'preset', 'strength', 'bands', 'shift', 'edge', 'before', 'after',
                    'texture', 'hint', 'points', 'angle', 'angle_hint', 'edge_row',
                    'row_main', 'row_edge')},
                # Редактор точек общий с lightwarp - и подписи к нему те же
                **{key: t.get(f'lightwarp_{key}', key) for key in (
                    'point', 'position', 'remove_point', 'gradient_hint')},
            },
            'tips': {key: t.get(f'phongwarp_tip_{key}', '') for key in (
                'preset', 'strength', 'bands', 'shift', 'edge', 'texture', 'before', 'after',
                'angle', 'edge_row')},
        },
        'from_mod': t.get('map_from_mod', 'From the mod'),
        'ui': {key: t.get(f'maps_{key}', key) for key in (
            'source', 'src_file', 'src_auto', 'src_gen', 'on', 'off', 'no_file',
            'drop', 'auto_text', 'params', 'preview', 'preview_tip', 'glow_lit',
            'glow_dark', 'glow_fade', 'glow_tip', 'glow_none', 'view_gloss', 'view_gloss_tip', 'view_gloss_only', 'view_gloss_only_tip',
            'view_rim', 'view_rim_tip', 'view_mask', 'view_mask_tip', 'view_env',
            'view_env_tip', 'view_env_tex', 'view_env_tex_tip', 'view_stand_in',
            'view_no_game', 'view_detail', 'view_detail_tip', 'view_none', 'view_no_texture')},
        # Конструктор полоски lightwarp: основы - полоски самой игры
        'lightwarp': {
            'defaults': dict(lightwarp.DEFAULTS),
            'max_steps': lightwarp.MAX_STEPS,
            'custom': lightwarp.CUSTOM,
            'max_stops': lightwarp.MAX_STOPS,
            'presets': [{'id': key, 'label': t.get(f'lightwarp_{key}', key)}
                        for key in (*lightwarp.PRESETS, lightwarp.CUSTOM)],
            'labels': {key: t.get(f'lightwarp_{key}', key) for key in (
                'make', 'preset', 'steps', 'smooth', 'shadow', 'light',
                'brightness', 'preview', 'hint', 'to_points', 'gradient_hint',
                'point', 'position', 'remove_point', 'graph_hint', 'before', 'after')},
            # Подсказки при наведении - что делает каждое поле
            'tips': {key: t.get(f'lightwarp_tip_{key}', '') for key in (
                'preset', 'steps', 'brightness', 'shadow', 'light', 'strip', 'graph',
                'before', 'after')},
        },
    }


@endpoint
def map_preview(material: str = '', map_id: str = 'selfillum',
                spec: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    """Текстура, её альфа и карта (у отражения - и кубмапа) для превью карты"""
    from src.app.session import session
    return session().materials.map_preview(material, map_id, spec)


@endpoint
def phongwarp_preview(params: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    """Градиент блика конструктора phongwarp для живого превью"""
    from src.app.session import session
    return session().materials.phongwarp_preview(params)


@endpoint
def lightwarp_ramp(params: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    """Полоска конструктора lightwarp для живого превью"""
    from src.app.session import session
    return session().materials.lightwarp_ramp(params)


@endpoint
def texture_maps(material: str = '') -> Dict[str, object]:
    """Карты, назначенные материалу"""
    from src.app.session import session
    return session().materials.texture_maps(material)


@endpoint
def set_texture_maps(material: str = '',
                     maps: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    """Записывает карты материала (пустой набор - снять)"""
    from src.app.session import session
    return session().materials.set_texture_maps(material, maps)


@endpoint
def add_to_style(material: str = '') -> Dict[str, object]:
    """Добавляет материал в активный вариантный стиль"""
    from src.app.session import session
    return session().materials.add_to_style(material)


@endpoint
def drop_from_style(material: str = '') -> Dict[str, object]:
    """Убирает материал из стиля - он вернётся к базовой текстуре"""
    from src.app.session import session
    return session().materials.drop_from_style(material)


@endpoint
def texture_settings(material: str = '') -> Dict[str, object]:
    """Свои настройки сборки у материала"""
    from src.app.session import session
    return session().materials.texture_settings(material)


@endpoint
def set_texture_settings(material: str = '',
                         settings: Optional[Dict[str, object]] = None
                         ) -> Dict[str, object]:
    """Задаёт материалу свои настройки (пустые - вернуть глобальные)"""
    from src.app.session import session
    return session().materials.set_texture_settings(material, settings)


@endpoint
def texture_badges() -> Dict[str, object]:
    """У каких материалов свои настройки - для пометок на карточках"""
    from src.app.session import session
    return session().materials.texture_badges()


@endpoint
def vmt_snippets(lang: str = '') -> Dict[str, object]:
    """Что предлагает меню «Готовые эффекты» в редакторе VMT

    Категории -> пункты. `key` - русская подпись пункта: по ней ищутся шаблон
    и список гасимых ключей, а `label`/`hint` - на языке интерфейса. Пустой
    `snippet` означает ПОЛНЫЙ шаблон: он заменяет весь документ, и страница
    обязана спросить. Тексты живут в `src/data/vmt_snippets.py`
    """
    from src.data.vmt_snippets import (
        VMT_FULL_TEMPLATES, VMT_MERGE_REMOVES, VMT_SNIPPETS, VMT_SNIPPETS_EN,
    )
    from src.services import vmt_effects

    en = _lang(lang) != 'ru'

    def label(key, hint=''):
        tr = VMT_SNIPPETS_EN.get(key) if en else None
        if isinstance(tr, tuple):
            return tr
        return (tr or key), hint

    groups = []
    for category, items in VMT_SNIPPETS.items():
        entries = []
        for key, snippet, hint in items:
            shown, shown_hint = label(key, hint or '')
            entries.append({'key': key, 'label': shown, 'hint': shown_hint,
                            'snippet': snippet or '',
                            'template': bool(snippet is None),
                            # Слияние: значения перекрывают одноимённые ключи
                            # документа, `remove` гасятся (VMT_MERGE_REMOVES)
                            'merge': key in VMT_MERGE_REMOVES,
                            'remove': list(VMT_MERGE_REMOVES.get(key, ())),
                            # Эффект с настройками: страница показывает форму,
                            # текст собирает vmt_apply_effect
                            'fields': vmt_effects.fields(key, en),
                            'replace': bool(vmt_effects.EFFECTS.get(key, {})
                                            .get('replace'))})
        groups.append({'name': label(category)[0], 'items': entries})
    return {'groups': groups, 'templates': dict(VMT_FULL_TEMPLATES)}


@endpoint
def vmt_effect_values(key: str = '', text: str = '') -> Dict[str, object]:
    """Значения формы эффекта: из материала, если эффект уже стоит"""
    from src.services import vmt_effects
    if key not in vmt_effects.EFFECTS:
        return {'error': 'Такого эффекта нет'}
    return {'values': vmt_effects.values(key, text or '')}


@endpoint
def vmt_apply_effect(key: str = '', values: Optional[Dict[str, object]] = None,
                     text: str = '', game: str = '') -> Dict[str, object]:
    """Материал с эффектом по выбранным значениям: {text, replace}. Не
    сохраняет - текст ложится в редактор, сохраняет человек. `game` -
    игровой оригинал материала (родная текстура для эффекта)"""
    from src.services import vmt_effects
    values = dict(values or {})
    bounds = _sheen_bounds() if key == vmt_effects.SHEEN and (
        values.get('when') == 'always'
        or str(values.get('pattern') or 'game') != 'game') else None
    return vmt_effects.apply(key, values, text or '', game or '', bounds)


def _sheen_bounds() -> Optional[Dict[str, object]]:
    """Габариты модели для полосы блеска

    Полоса блеска «всегда» и любой узор (свой или готовый) кладутся по
    габаритам модели: раскладка игры у оружия, длинного по Z (кунай), сводит
    узор в тонкую линию. Не прочиталась модель - узор возьмёт обычную
    пропорцию ствола, «всегда» скажет об ошибке сам
    """
    from src.app.session import session
    try:
        return session().sheen.sheen_mask_params()
    except Exception as exc:                                 # noqa: BLE001
        logger.warning(f'[sheen] габариты модели не прочитались: {exc}')
        return None


@endpoint
def vmt_params(lang: str = '') -> List[dict]:
    """
    Справочник $-параметров VMT по группам - для подсказок при наведении и
    списка «Справочник» в редакторе: [{'group', 'params': [{'param','doc'}]}]

    Словарь один (``vmt_snippets.VMT_PARAM_GROUPS``): второго списка заводить
    нельзя, иначе подсказки разойдутся с тем, что редактор действительно знает
    """
    from src.data.vmt_snippets import param_reference

    return param_reference(_lang(lang))


@endpoint
def open_vmt(material: str = '', lang: str = '') -> Dict[str, object]:
    """Текст VMT материала: сохранённая правка либо игровой оригинал"""
    from src.app.session import session

    lang = _lang(lang)
    return session().materials.open_vmt(material, lang=lang)


@endpoint
def save_vmt(material: str = '', content: str = '',
             original: str = '') -> Dict[str, object]:
    """Сохраняет правку VMT"""
    from src.app.session import session
    return session().materials.save_vmt(material, content, original, _lang())


@endpoint
def save_vmt_all(material: str = '', content: str = '', before: str = '',
                 original: str = '', materials: Optional[List[str]] = None) -> Dict[str, object]:
    """Правка VMT без шестерёнки: в этот материал и во все остальные
    материалы предмета (эффекты - заново в каждом, ключи - без путей
    текстур). `before` - текст материала до правки"""
    from src.app.session import session
    from src.services import vmt_effects
    bounds = _sheen_bounds() if vmt_effects.present(vmt_effects.SHEEN, content) else None
    return session().materials.save_vmt_all(
        material, content, before, original, list(materials or []), bounds, _lang())


@endpoint
def reset_vmt_all(materials: Optional[List[str]] = None) -> Dict[str, object]:
    """«Как в игре» без шестерёнки: снимает правки VMT у всех материалов"""
    from src.app.session import session
    return session().materials.reset_vmt_all(list(materials or []))


@endpoint
def reset_vmt(material: str = '') -> Dict[str, object]:
    """Удаляет правку VMT - материал вернётся к игровому оригиналу"""
    from src.app.session import session
    return session().materials.reset_vmt(material)


@endpoint
def normal_preview(screen: Optional[Dict[str, object]] = None,
                   global_options: Optional[Dict[str, object]] = None,
                   editing: Optional[str] = None) -> Dict[str, object]:
    """Карта нормалей главной текстуры для 3D-превью: {png, material, stock} или {off}"""
    from src.app.session import session
    return session().normal_preview(screen, global_options, editing)
