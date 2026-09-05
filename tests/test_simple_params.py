"""Тесты схемы простого режима: чтение/запись крутилок поверх systems_json."""

import pytest

from src.services.simple_params import (
    SIMPLE_PARAMS, missing_modules, read_param, write_calls,
)

PARAMS = {p.key: p for p in SIMPLE_PARAMS}


def _sys_json():
    """Снимок системы в формате systems_json."""
    return {
        "attrs": {
            "radius": {"t": "float", "v": 5.0},
            "max_particles": {"t": "integer", "v": 100},
        },
        "renderers": [], "emitters": [
            {"functionName": "emit_continuously",
             "attrs": {"emission_rate": {"t": "float", "v": 12.0}}},
        ],
        "initializers": [
            {"functionName": "Radius Random",
             "attrs": {"radius_min": {"t": "float", "v": 3.0},
                       "radius_max": {"t": "float", "v": 6.0}}},
            {"functionName": "Color Random",
             "attrs": {"color1": {"t": "color", "v": [255, 0, 0, 255]},
                       "color2": {"t": "color", "v": [0, 0, 255, 255]}}},
        ],
        "operators": [
            {"functionName": "Movement Basic",
             "attrs": {"gravity": {"t": "vec3", "v": [0.0, 0.0, -200.0]}}},
        ],
        "forces": [], "constraints": [], "children": [],
    }


def test_read_param():
    s = _sys_json()
    assert read_param(s, PARAMS["size"]) == 5.0
    assert read_param(s, PARAMS["max_particles"]) == 100
    assert read_param(s, PARAMS["spawn_rate"]) == 12.0
    assert read_param(s, PARAMS["size_range"]) == (3.0, 6.0)
    assert read_param(s, PARAMS["gravity"]) == -200.0          # компонента Z
    assert read_param(s, PARAMS["colors"]) == (
        [255, 0, 0, 255], [0, 0, 255, 255])
    # нет модуля → None (и его перечисляет missing_modules)
    assert read_param(s, PARAMS["lifetime"]) is None
    assert missing_modules(s, PARAMS["lifetime"]) == [
        ("initializers", "Lifetime Random")]
    assert missing_modules(s, PARAMS["size"]) == []


def test_read_param_partial_attrs_use_default():
    """Модуль есть, атрибута нет — подставляется default (запись его создаст)."""
    s = _sys_json()
    del s["initializers"][0]["attrs"]["radius_max"]
    assert read_param(s, PARAMS["size_range"]) == (3.0, PARAMS["size_range"].default)


def test_write_calls():
    s = _sys_json()
    assert write_calls(s, PARAMS["size"], 8.0) == [
        (None, 0, "radius", "float", 8.0)]
    assert write_calls(s, PARAMS["size_range"], (2.0, 9.0)) == [
        ("initializers", 0, "radius_min", "float", 2.0),
        ("initializers", 0, "radius_max", "float", 9.0)]
    # компонента vec3: собирается полный вектор с заменой Z
    assert write_calls(s, PARAMS["gravity"], 300.0) == [
        ("operators", 0, "gravity", "vec3", [0.0, 0.0, 300.0])]
    # нет модуля → писать некуда
    assert write_calls(s, PARAMS["lifetime"], (0.2, 0.6)) == []


def test_write_calls_component_without_attr():
    """Нет самого атрибута gravity — компонента ложится в нулевой вектор."""
    s = _sys_json()
    s["operators"][0]["attrs"] = {}
    assert write_calls(s, PARAMS["gravity"], -50.0) == [
        ("operators", 0, "gravity", "vec3", [0.0, 0.0, -50.0])]


def test_ensure_attr_creates_missing():
    """ensure_attr: правит существующий атрибут либо создаёт новый."""
    pytest.importorskip("srctools.dmx")
    from tests.test_particle_editor_service import _make_pcf_bytes
    from src.services.particle_editor_service import ParticleEditorService

    svc = ParticleEditorService()
    svc.load_bytes(_make_pcf_bytes())
    # существующий — обычный set
    assert svc.ensure_attr("fx", None, 0, "radius", "float", 9.5)
    assert svc.systems_json()["fx"]["attrs"]["radius"]["v"] == 9.5
    # отсутствующий системный — создаётся
    assert svc.ensure_attr("fx", None, 0, "rotation_speed", "float", 45.0)
    assert svc.systems_json()["fx"]["attrs"]["rotation_speed"]["v"] == 45.0
    # отсутствующий у модуля — создаётся
    assert svc.ensure_attr("fx", "initializers", 0, "tint_perc", "float", 0.5)
    assert svc.systems_json()["fx"]["initializers"][0]["attrs"]["tint_perc"]["v"] == 0.5
    # несуществующая система/модуль → False
    assert not svc.ensure_attr("nope", None, 0, "radius", "float", 1.0)
    assert not svc.ensure_attr("fx", "operators", 5, "drag", "float", 1.0)


def test_schema_sanity():
    """Каждая запись схемы согласована: kind ↔ количество refs."""
    for p in SIMPLE_PARAMS:
        assert p.kind in ("value", "range", "color_pair"), p.key
        if p.kind == "value":
            assert len(p.refs) == 1, p.key
        else:
            assert len(p.refs) == 2, p.key
        for r in p.refs:
            assert (r.group is None) == (r.function_name == ""), p.key


def test_system_attr_without_value_falls_back_to_default():
    """Системного атрибута нет — крутилка всё равно рабочая: игра держит
    дефолт, и первая же правка его запишет. Раньше read_param отдавал None,
    поле выключалось, а кнопка «Включить» ничего не создавала (модулей-то
    нет) — крутилка оказывалась мёртвой."""
    s = _sys_json()
    del s["attrs"]["radius"]
    del s["attrs"]["max_particles"]
    assert read_param(s, PARAMS["size"]) == PARAMS["size"].default
    assert read_param(s, PARAMS["max_particles"]) == PARAMS["max_particles"].default
    assert missing_modules(s, PARAMS["size"]) == []
    assert write_calls(s, PARAMS["size"], 7.0) == [(None, 0, "radius", "float", 7.0)]


def test_max_particles_default_matches_source():
    """Дефолт Source для max_particles — 1000 (CParticleSystemDefinition);
    подстановка меньшего значения молча урезала бы систему при первой правке."""
    assert PARAMS["max_particles"].default == 1000


def test_variant_fallback_picks_present_module():
    """Скорость разлёта живёт либо в сферическом инициализаторе, либо в
    Velocity Random — крутилка берёт тот вариант, который есть в системе."""
    s = _sys_json()
    s["initializers"].append(
        {"functionName": "Velocity Random",
         "attrs": {"speed_min": {"t": "float", "v": 10.0},
                   "speed_max": {"t": "float", "v": 20.0}}})
    assert read_param(s, PARAMS["speed"]) == (10.0, 20.0)
    assert write_calls(s, PARAMS["speed"], (1.0, 2.0)) == [
        ("initializers", 2, "speed_min", "float", 1.0),
        ("initializers", 2, "speed_max", "float", 2.0)]

    # Появился сферический инициализатор — он приоритетнее (вариант первый)
    s["initializers"].insert(0, {
        "functionName": "Position Within Sphere Random",
        "attrs": {"speed_min": {"t": "float", "v": 5.0},
                  "speed_max": {"t": "float", "v": 6.0}}})
    assert read_param(s, PARAMS["speed"]) == (5.0, 6.0)


def test_variant_missing_everywhere_reports_primary():
    """Ни одного варианта нет — «Включить» создаёт модули основного."""
    s = _sys_json()
    assert read_param(s, PARAMS["speed"]) is None
    assert missing_modules(s, PARAMS["speed"]) == [
        ("initializers", "Position Within Sphere Random")]


def test_curve_round_trip():
    """Кривая ползунка обратима и монотонна на всём мягком диапазоне."""
    from src.services.simple_params import curve_fraction, curve_value
    for p in SIMPLE_PARAMS:
        if p.kind == "color_pair":
            continue
        span = p.maximum - p.minimum
        for step in range(11):
            value = p.minimum + span * step / 10
            back = curve_value(p, curve_fraction(p, value))
            assert abs(back - value) < span * 1e-6, (p.key, value, back)


def test_sqrt_curve_gives_small_values_half_the_track():
    """Смысл кривой: на диапазоне 0..2000 середина ползунка = 500, иначе
    типовые значения (медиана скорости в стоке — десятки) неразличимы."""
    from src.services.simple_params import curve_value
    speed = PARAMS["speed"]
    assert speed.curve == "sqrt"
    assert abs(curve_value(speed, 0.5) - 500) < 1e-6


def test_signed_sqrt_curve_is_symmetric():
    """Гравитация знаковая: середина ползунка — ноль, половина хода в
    каждую сторону приходится на четверть размаха."""
    from src.services.simple_params import curve_value
    g = PARAMS["gravity"]
    assert abs(curve_value(g, 0.5)) < 1e-6
    assert abs(curve_value(g, 0.75) - 200) < 1e-6
    assert abs(curve_value(g, 0.25) + 200) < 1e-6


def test_hard_bounds_cover_stock_extremes():
    """Жёсткие границы не режут стоковые значения: emission_rate доходит до
    999999, lifetime — до 1e10 («вечная» частица)."""
    assert PARAMS["spawn_rate"].input_max >= 999999
    assert PARAMS["lifetime"].input_max >= 1e10
    assert PARAMS["max_particles"].input_max >= 1e6
    for p in SIMPLE_PARAMS:
        assert p.input_min <= p.minimum, p.key
        assert p.input_max >= p.maximum, p.key
