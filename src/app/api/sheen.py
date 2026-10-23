"""Конструктор блеска"""

from __future__ import annotations

from typing import Dict, Optional

from src.app.api._common import _lang, endpoint


# Конструктор узора блеска (src/services/sheen_builder.py)

@endpoint
def sheen_builder_schema(lang: str = '') -> Dict[str, object]:
    """Слои конструктора и их поля, готовые узоры для начала - на языке
    интерфейса. Поля формы страница строит отсюда"""
    from src.services import sheen_builder as sb
    from src.services import sheen_patterns as sp

    i = 1 if _lang(lang) != 'ru' else 0

    def field(key, view, default, lo, hi, step, label):
        out = {'key': key, 'view': view, 'default': default, 'label': label[i]}
        if view == 'choice':
            out['choices'] = [{'value': c, 'label': sb.CHOICE_LABELS.get(c, (c, c))[i]}
                              for c in lo]
        elif view in ('range', 'seed', 'angle'):
            out.update(min=lo, max=hi, step=step)
        elif view == 'stops':
            out['max_stops'] = sb.MAX_STOPS
        return out

    return {
        'types': [{'id': kind, 'label': d['label'][i],
                   'fields': [field(*f) for f in d['fields']],
                   'defaults': sb.new_layer(kind)}
                  for kind, d in sb.LAYER_TYPES.items()],
        'common': [field(*f) for f in sb._COMMON],
        'presets': [{'id': k, 'label': p['label'][i], 'spec': sb.clean_spec(p['spec'])}
                    for k, p in sb.PRESETS.items()],
        'max_layers': sb.MAX_LAYERS,
        # Размер маски страница считает сама, сразу при выборе качества,
        # а не после расчёта кадров (sheen_builder.mask_shape)
        'quality': dict(sb.QUALITY),
        'default_aspect': sb.DEFAULT_ASPECT,
        'frames': {'min': sp.MIN_FRAMES, 'max': sp.MAX_FRAMES, 'fps': sp.FPS},
        'fps': 25,
    }


@endpoint
def sheen_preset_thumbs() -> Dict[str, object]:
    """Карточки шаблонов «Начать с»: по картинке на шаблон"""
    from src.app.session import session
    return session().sheen.sheen_preset_thumbs()


@endpoint
def sheen_patterns_list() -> Dict[str, object]:
    """Свои узоры блеска: [{id, name, length}]"""
    from src.services import sheen_library
    return {'patterns': sheen_library.list_patterns()}


@endpoint
def sheen_pattern_load(pattern_id: str = '') -> Dict[str, object]:
    from src.services import sheen_library
    data = sheen_library.load(pattern_id)
    return data if data else {'error': 'Узор не найден'}


@endpoint
def sheen_pattern_preview(spec: Optional[Dict[str, object]] = None,
                          length: float = 2.5,
                          full: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    """Кадры узора сеткой (те же, что уйдут в мод) и пропорция оружия.
    `full` - весь узор, когда в превью один слой «соло»: гамму решает он"""
    from src.app.session import session
    return session().sheen.sheen_pattern_preview(spec or {}, length, full)


@endpoint
def sheen_pattern_save(pattern_id: str = '', name: str = '',
                       spec: Optional[Dict[str, object]] = None,
                       length: float = 2.5) -> Dict[str, object]:
    from src.services import sheen_library
    try:
        return {'id': sheen_library.save(pattern_id, name, spec or {}, length)}
    except (OSError, ValueError) as exc:
        return {'error': f'Узор не сохранился: {exc}'}


@endpoint
def sheen_pattern_delete(pattern_id: str = '') -> Dict[str, object]:
    from src.services import sheen_library
    return {'deleted': sheen_library.delete(pattern_id)}
