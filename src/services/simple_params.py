"""
Декларативная схема «простого режима» редактора частиц.

Каждый SimpleParam — одна крутилка: что она показывает и в какие атрибуты
каких модулей пишет. Добавление новой крутилки = одна запись в SIMPLE_PARAMS
плюс переводы particles_sp_<key>; UI строится по схеме автоматически,
синхронизация с деревом экспертного режима бесплатна — оба пути пишут через
ParticleEditorService.set_attr/ensure_attr и читают один systems_json.

Три вещи, которые схема описывает явно, потому что данные игры этого требуют:

* ВАРИАНТЫ адресов (`variants`). Один и тот же смысл в разных эффектах
  живёт в разных модулях: скорость разлёта — либо в Position Within Sphere
  Random, либо в Velocity Random. Крутилка берёт первый вариант, все модули
  которого есть в системе.
* МЯГКИЕ и ЖЁСТКИЕ границы. minimum/maximum — диапазон ползунка (столько,
  сколько нужно в 99% эффектов), hard_min/hard_max — предел ручного ввода.
  Стоковые PCF содержат emission_rate до 999999 и lifetime до 1e10 («вечная»
  частица): если ограничить ввод мягкой границей, редактор молча испортит
  чужой эффект.
* КРИВАЯ ползунка. Половина стоковых значений гравитации лежит в ±50 при
  размахе ±800 — на линейном ползунке это 6% хода. Кривая «sqrt» отдаёт
  малым значениям половину дорожки.

Модуль без Qt: логика чтения/записи тестируется напрямую.
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple

#: Кривые ползунка: доля хода [0..1] ⇄ доля диапазона [0..1].
CURVE_LINEAR = "linear"
#: Квадратичная: мелкие значения занимают половину дорожки. Для диапазонов
#: «от нуля вверх» с длинным хвостом (скорость, область спавна, размер).
CURVE_SQRT = "sqrt"
#: То же, но симметрично относительно нуля — для знаковых (гравитация, спин).
CURVE_SIGNED_SQRT = "signed_sqrt"


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
    #: Адреса по приоритету: первый вариант, чьи модули есть в системе.
    #: Кнопка «Включить» создаёт модули ПЕРВОГО варианта.
    variants: Tuple[Tuple[AttrRef, ...], ...]
    minimum: float = 0.0     # мягкая граница — диапазон ползунка
    maximum: float = 1.0
    hard_min: Optional[float] = None   # предел ручного ввода; None = minimum
    hard_max: Optional[float] = None
    curve: str = CURVE_LINEAR
    decimals: int = 2
    default: float = 0.0     # значение-заглушка, если атрибута ещё нет
    creatable: bool = True   # недостающий модуль можно создать кнопкой

    @property
    def refs(self) -> Tuple[AttrRef, ...]:
        """Основной вариант адресов (тот, что создаёт кнопка «Включить»)."""
        return self.variants[0]

    @property
    def placeholder_value(self):
        """Что показывать в строке, под которой модуля ещё нет.

        Умолчание Source: строка-заготовка обязана врать как можно меньше —
        именно это значение эффект и получит, если правку не трогать.
        """
        if self.kind == "value":
            return self.default
        if self.kind == "color_pair":
            return ([255, 255, 255, 255], [255, 255, 255, 255])
        return tuple(self.default for _ in self.refs)

    @property
    def input_min(self) -> float:
        return self.minimum if self.hard_min is None else self.hard_min

    @property
    def input_max(self) -> float:
        return self.maximum if self.hard_max is None else self.hard_max


def curve_fraction(param: SimpleParam, value: float) -> float:
    """Значение → доля хода ползунка [0..1] (обратное к curve_value)."""
    lo, hi = param.minimum, param.maximum
    span = hi - lo
    if span <= 0:
        return 0.0
    t = min(1.0, max(0.0, (value - lo) / span))
    if param.curve == CURVE_SQRT:
        return t ** 0.5
    if param.curve == CURVE_SIGNED_SQRT:
        signed = t * 2.0 - 1.0                      # [-1..1] от середины
        return ((abs(signed) ** 0.5) * (1 if signed >= 0 else -1) + 1.0) / 2.0
    return t


def curve_value(param: SimpleParam, fraction: float) -> float:
    """Доля хода ползунка [0..1] → значение параметра."""
    f = min(1.0, max(0.0, fraction))
    if param.curve == CURVE_SQRT:
        t = f * f
    elif param.curve == CURVE_SIGNED_SQRT:
        signed = f * 2.0 - 1.0
        t = (signed * abs(signed) + 1.0) / 2.0
    else:
        t = f
    return param.minimum + (param.maximum - param.minimum) * t


def module_index(sys_json: dict, group: str,
                 function_name: str) -> Optional[int]:
    """Индекс первого модуля группы с таким functionName; None — нет такого.

    Регистр written-имени в PCF гуляет от файла к файлу (в стоке есть и
    «Radius Random», и «radius_random»), поэтому сравнение регистронезависимое.
    """
    for i, mod in enumerate(sys_json.get(group) or []):
        if mod.get("functionName", "").strip().lower() == function_name.lower():
            return i
    return None


def _refs_present(sys_json: dict, refs: Tuple[AttrRef, ...]) -> bool:
    """Все ли модули варианта есть в системе (системные атрибуты — всегда)."""
    return all(ref.group is None
               or module_index(sys_json, ref.group, ref.function_name) is not None
               for ref in refs)


def active_refs(sys_json: dict, param: SimpleParam) -> Tuple[AttrRef, ...]:
    """Вариант адресов, которым крутилка работает с ЭТОЙ системой.

    Первый вариант, все модули которого на месте; если ни один не подходит —
    основной (его и будет создавать кнопка «Включить»).
    """
    for refs in param.variants:
        if _refs_present(sys_json, refs):
            return refs
    return param.refs


def _read_ref(sys_json: dict, ref: AttrRef):
    """Значение атрибута по адресу; None — модуля/атрибута нет."""
    if ref.group is None:
        tv = sys_json["attrs"].get(ref.attr)
    else:
        idx = module_index(sys_json, ref.group, ref.function_name)
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
        None — нужного модуля в системе нет (крутилка выключена, показывается
        кнопка «Включить»). Отсутствующий АТРИБУТ существующего модуля — не
        причина выключать: игра держит его в дефолте, и правка его создаст.
    """
    refs = active_refs(sys_json, param)
    if not _refs_present(sys_json, refs):
        return None
    vals = [param.default if (v := _read_ref(sys_json, ref)) is None else v
            for ref in refs]
    return vals[0] if param.kind == "value" else tuple(vals)


def missing_modules(sys_json: dict, param: SimpleParam) -> List[tuple]:
    """[(группа, functionName)] модулей, которых не хватает крутилке."""
    out = []
    for ref in active_refs(sys_json, param):
        if ref.group is None:
            continue
        if module_index(sys_json, ref.group, ref.function_name) is None:
            if (ref.group, ref.function_name) not in out:
                out.append((ref.group, ref.function_name))
    return out


def write_calls(sys_json: dict, param: SimpleParam, value) -> List[tuple]:
    """
    Значение крутилки → [(group|None, mod_idx, attr, attr_type, new_value)]
    для ParticleEditorService.ensure_attr. Пусто — нужного модуля нет.
    """
    refs = active_refs(sys_json, param)
    vals = [value] if param.kind == "value" else list(value)
    calls = []
    for ref, v in zip(refs, vals):
        idx = 0
        if ref.group is not None:
            idx = module_index(sys_json, ref.group, ref.function_name)
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


def _v(*refs: AttrRef) -> Tuple[AttrRef, ...]:
    """Один вариант адресов."""
    return refs


#: Схема простого режима. Новая крутилка = одна запись здесь
#: + ключ перевода particles_sp_<key> в translations.py (ru и en).
#:
#: Мягкие границы и дефолты выставлены по срезу стоковых PCF игры
#: (134 файла, 10426 систем): мягкая граница ≈ 99-й процентиль, жёсткая —
#: с запасом над максимумом, дефолт — как в Source.
SIMPLE_PARAMS: Tuple[SimpleParam, ...] = (
    # ── Эмиссия ───────────────────────────────────────────────────────────
    # Параметры эмиттеров показываются только при их наличии: автосоздание
    # эмиттера может задвоить залп, поэтому creatable=False
    SimpleParam("spawn_rate", "value",
                (_v(_r("emitters", "emit_continuously", "emission_rate")),),
                minimum=0, maximum=500, hard_max=1e6, curve=CURVE_SQRT,
                default=100, creatable=False),
    SimpleParam("spawn_burst", "value",
                (_v(_r("emitters", "emit_instantaneously", "num_to_emit",
                       "integer")),),
                minimum=0, maximum=1000, hard_max=1e6, curve=CURVE_SQRT,
                decimals=0, default=100, creatable=False),
    # Задержка старта эмиссии — есть у обоих эмиттеров, имя атрибута одно
    SimpleParam("emit_delay", "value",
                (_v(_r("emitters", "emit_continuously", "emission_start_time")),
                 _v(_r("emitters", "emit_instantaneously",
                       "emission_start_time"))),
                minimum=0, maximum=10, hard_max=1e5, curve=CURVE_SQRT,
                creatable=False),
    # Длительность эмиссии; 0 = бесконечно (так в игре)
    SimpleParam("emit_duration", "value",
                (_v(_r("emitters", "emit_continuously", "emission_duration")),),
                minimum=0, maximum=10, hard_max=1e5, curve=CURVE_SQRT,
                creatable=False),
    SimpleParam("max_particles", "value",
                (_v(_r(None, "", "max_particles", "integer")),),
                minimum=1, maximum=5000, hard_max=1e6, curve=CURVE_SQRT,
                decimals=0, default=1000),
    # ── Область спавна и разлёт ───────────────────────────────────────────
    # Сферическая область — самая ходовая (7032 модуля в стоке), бокс —
    # запасной вариант (273); у обоих гизмо в 3D-превью
    SimpleParam("spawn_area", "range",
                (_v(_r("initializers", "Position Within Sphere Random",
                       "distance_min"),
                    _r("initializers", "Position Within Sphere Random",
                       "distance_max")),),
                minimum=0, maximum=500, hard_max=1e5, curve=CURVE_SQRT,
                creatable=False),
    # Скорость: в сферическом инициализаторе либо в отдельном Velocity Random
    SimpleParam("speed", "range",
                (_v(_r("initializers", "Position Within Sphere Random",
                       "speed_min"),
                    _r("initializers", "Position Within Sphere Random",
                       "speed_max")),
                 _v(_r("initializers", "Velocity Random", "speed_min"),
                    _r("initializers", "Velocity Random", "speed_max"))),
                minimum=0, maximum=2000, hard_max=1e5, curve=CURVE_SQRT,
                creatable=False),
    SimpleParam("gravity", "value",
                (_v(_r("operators", "Movement Basic", "gravity", "vec3",
                       component=2)),),
                minimum=-800, maximum=800, hard_min=-1e6, hard_max=1e6,
                curve=CURVE_SIGNED_SQRT),
    # Сопротивление среды: 0 — движение по инерции, 1 — мгновенная остановка
    SimpleParam("drag", "value",
                (_v(_r("operators", "Movement Basic", "drag")),),
                minimum=0, maximum=1, hard_min=-10, hard_max=10, decimals=3),
    # ── Размер ────────────────────────────────────────────────────────────
    SimpleParam("size", "value",
                (_v(_r(None, "", "radius")),),
                minimum=0.1, maximum=200, hard_min=0, hard_max=1e5,
                curve=CURVE_SQRT, default=5.0),
    SimpleParam("size_range", "range",
                (_v(_r("initializers", "Radius Random", "radius_min"),
                    _r("initializers", "Radius Random", "radius_max")),),
                minimum=0.1, maximum=200, hard_min=0, hard_max=1e5,
                curve=CURVE_SQRT, default=5.0),
    # Рост/усадка за жизнь частицы: 7262 модуля в стоке
    SimpleParam("size_scale", "range",
                (_v(_r("operators", "Radius Scale", "radius_start_scale"),
                    _r("operators", "Radius Scale", "radius_end_scale")),),
                minimum=0, maximum=10, hard_max=1e4, curve=CURVE_SQRT,
                default=1.0),
    # ── Жизнь, прозрачность, затухание ────────────────────────────────────
    SimpleParam("lifetime", "range",
                (_v(_r("initializers", "Lifetime Random", "lifetime_min"),
                    _r("initializers", "Lifetime Random", "lifetime_max")),),
                minimum=0.05, maximum=30, hard_min=0, hard_max=1e10,
                curve=CURVE_SQRT, default=0.5),
    # Стартовая прозрачность 0-255: 7449 модулей в стоке
    SimpleParam("alpha", "range",
                (_v(_r("initializers", "Alpha Random", "alpha_min", "integer"),
                    _r("initializers", "Alpha Random", "alpha_max", "integer")),),
                minimum=0, maximum=255, decimals=0, default=255),
    SimpleParam("fade_in", "range",
                (_v(_r("operators", "Alpha Fade In Random", "fade in time min"),
                    _r("operators", "Alpha Fade In Random", "fade in time max")),),
                minimum=0, maximum=10, hard_max=1e4, default=0.25),
    SimpleParam("fade_out", "range",
                (_v(_r("operators", "Alpha Fade Out Random", "fade out time min"),
                    _r("operators", "Alpha Fade Out Random",
                       "fade out time max")),),
                minimum=0, maximum=10, hard_max=1e4, default=0.25),
    # ── Цвет и вращение ───────────────────────────────────────────────────
    SimpleParam("colors", "color_pair",
                (_v(_r("initializers", "Color Random", "color1", "color"),
                    _r("initializers", "Color Random", "color2", "color")),)),
    SimpleParam("spin", "value",
                (_v(_r("operators", "Rotation Spin Roll", "spin_rate_degrees",
                       "integer")),),
                minimum=-1000, maximum=1000, hard_min=-1e6, hard_max=1e6,
                curve=CURVE_SIGNED_SQRT, decimals=0),
)
