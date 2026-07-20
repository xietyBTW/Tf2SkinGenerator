"""
Декларативная схема «простого режима» редактора частиц.

Каждый SimpleParam — одна крутилка: что она показывает и в какие атрибуты
каких модулей пишет. Добавление новой крутилки = одна запись в SIMPLE_PARAMS
плюс переводы particles_sp_<key>; UI строится по схеме автоматически,
синхронизация с деревом экспертного режима бесплатна — оба пути пишут через
ParticleEditorService.set_attr/ensure_attr и читают один systems_json.

Модуль без Qt: логика чтения/записи тестируется напрямую.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class AttrRef:
    """Адрес атрибута: (группа, functionName модуля) либо group=None —
    атрибут самой системы."""
    group: Optional[str]
    function_name: str
    attr: str
    attr_type: str                    # DMX-тип для создания атрибута
    component: Optional[int] = None   # компонента vec3 (напр. 2 = Z гравитации)


@dataclass(frozen=True)
class SimpleParam:
    key: str            # ключ перевода particles_sp_<key>
    kind: str           # "value" | "range" | "color_pair"
    refs: Tuple[AttrRef, ...]
    minimum: float = 0.0
    maximum: float = 1.0
    decimals: int = 2
    default: float = 0.0     # значение-заглушка, если атрибута ещё нет
    creatable: bool = True   # недостающий модуль можно создать кнопкой


def _module_index(sys_json: dict, group: str, function_name: str) -> Optional[int]:
    for i, mod in enumerate(sys_json.get(group) or []):
        if mod.get("functionName", "").strip().lower() == function_name.lower():
            return i
    return None


def _read_ref(sys_json: dict, ref: AttrRef):
    """Значение атрибута по адресу; None — модуля/атрибута нет."""
    if ref.group is None:
        tv = sys_json["attrs"].get(ref.attr)
    else:
        idx = _module_index(sys_json, ref.group, ref.function_name)
        if idx is None:
            return None
        tv = sys_json[ref.group][idx]["attrs"].get(ref.attr)
    if tv is None:
        return None
    v = tv["v"]
    if ref.component is not None:
        try:
            return v[ref.component]
        except (TypeError, IndexError):
            return None
    return v


def read_param(sys_json: dict, param: SimpleParam):
    """
    Текущее значение крутилки из systems_json.

    Returns:
        "value" → скаляр; "range"/"color_pair" → кортеж по refs.
        None — модуль есть, но атрибут не найден нигде (или модуля нет);
        для частично отсутствующих атрибутов подставляется param.default.
    """
    vals = []
    any_found = False
    for ref in param.refs:
        if ref.group is not None and \
                _module_index(sys_json, ref.group, ref.function_name) is None:
            return None                       # нет модуля — крутилка выключена
        v = _read_ref(sys_json, ref)
        if v is None:
            v = param.default
        else:
            any_found = True
        vals.append(v)
    if not any_found and param.refs[0].group is None:
        return None                           # нет даже системного атрибута
    return vals[0] if param.kind == "value" else tuple(vals)


def missing_modules(sys_json: dict, param: SimpleParam) -> List[tuple]:
    """[(группа, functionName)] модулей, которых не хватает крутилке."""
    out = []
    for ref in param.refs:
        if ref.group is None:
            continue
        if _module_index(sys_json, ref.group, ref.function_name) is None:
            if (ref.group, ref.function_name) not in out:
                out.append((ref.group, ref.function_name))
    return out


def write_calls(sys_json: dict, param: SimpleParam, value) -> List[tuple]:
    """
    Значение крутилки → [(group|None, mod_idx, attr, attr_type, new_value)]
    для ParticleEditorService.ensure_attr. Пусто — нужного модуля нет.
    """
    vals = [value] if param.kind == "value" else list(value)
    calls = []
    for ref, v in zip(param.refs, vals):
        idx = 0
        if ref.group is not None:
            idx = _module_index(sys_json, ref.group, ref.function_name)
            if idx is None:
                return []
        if ref.component is not None:
            cur = _read_ref(sys_json, AttrRef(
                ref.group, ref.function_name, ref.attr, ref.attr_type))
            base = list(cur) if isinstance(cur, (list, tuple)) else [0.0, 0.0, 0.0]
            base[ref.component] = v
            v = base
        calls.append((ref.group, idx, ref.attr, ref.attr_type, v))
    return calls


def _r(group, fn, attr, attr_type="float", component=None) -> AttrRef:
    return AttrRef(group, fn, attr, attr_type, component)


#: Схема простого режима. Новая крутилка = одна запись здесь
#: + ключ перевода particles_sp_<key> в translations.py (ru и en).
SIMPLE_PARAMS: Tuple[SimpleParam, ...] = (
    # Эмиссия: параметры эмиттеров показываются только при их наличии —
    # автосоздание эмиттера может задвоить залп, поэтому creatable=False
    SimpleParam("spawn_rate", "value",
                (_r("emitters", "emit_continuously", "emission_rate"),),
                minimum=0, maximum=500, creatable=False),
    SimpleParam("spawn_burst", "value",
                (_r("emitters", "emit_instantaneously", "num_to_emit",
                    "integer"),),
                minimum=0, maximum=1000, decimals=0, creatable=False),
    SimpleParam("max_particles", "value",
                (_r(None, "", "max_particles", "integer"),),
                minimum=1, maximum=5000, decimals=0, default=100),
    # Область спавна и разлёт (сферическая — самая ходовая; бокс получит
    # гизмо на следующем этапе)
    SimpleParam("spawn_area", "range",
                (_r("initializers", "Position Within Sphere Random",
                    "distance_min"),
                 _r("initializers", "Position Within Sphere Random",
                    "distance_max")),
                minimum=0, maximum=500, creatable=False),
    SimpleParam("speed", "range",
                (_r("initializers", "Position Within Sphere Random",
                    "speed_min"),
                 _r("initializers", "Position Within Sphere Random",
                    "speed_max")),
                minimum=0, maximum=2000, creatable=False),
    SimpleParam("gravity", "value",
                (_r("operators", "Movement Basic", "gravity", "vec3",
                    component=2),),
                minimum=-800, maximum=800),
    # Размер
    SimpleParam("size", "value",
                (_r(None, "", "radius"),),
                minimum=0.1, maximum=200, default=5.0),
    SimpleParam("size_range", "range",
                (_r("initializers", "Radius Random", "radius_min"),
                 _r("initializers", "Radius Random", "radius_max")),
                minimum=0.1, maximum=200, default=5.0),
    # Жизнь и затухание
    SimpleParam("lifetime", "range",
                (_r("initializers", "Lifetime Random", "lifetime_min"),
                 _r("initializers", "Lifetime Random", "lifetime_max")),
                minimum=0.05, maximum=30, default=0.5),
    SimpleParam("fade_in", "range",
                (_r("operators", "Alpha Fade In Random", "fade in time min"),
                 _r("operators", "Alpha Fade In Random", "fade in time max")),
                minimum=0, maximum=10, default=0.25),
    SimpleParam("fade_out", "range",
                (_r("operators", "Alpha Fade Out Random", "fade out time min"),
                 _r("operators", "Alpha Fade Out Random", "fade out time max")),
                minimum=0, maximum=10, default=0.25),
    # Цвет и вращение
    SimpleParam("colors", "color_pair",
                (_r("initializers", "Color Random", "color1", "color"),
                 _r("initializers", "Color Random", "color2", "color"))),
    SimpleParam("spin", "value",
                (_r("operators", "Rotation Spin Roll", "spin_rate_degrees",
                    "integer"),),
                minimum=-1000, maximum=1000, decimals=0),
)
