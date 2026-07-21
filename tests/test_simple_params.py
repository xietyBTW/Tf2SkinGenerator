"""Тесты схемы простого режима: чтение/запись крутилок поверх systems_json."""

import pytest

from src.services.simple_params import (
    SIMPLE_PARAMS, AttrRef, SimpleParam, missing_modules, read_param,
    write_calls,
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
    srctools_dmx = pytest.importorskip("srctools.dmx")
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


def test_num_spin_accepts_both_decimal_separators():
    """Под русской локалью штатный QDoubleSpinBox глотает точку («12.5» → 125).
    _NumSpin принимает оба разделителя."""
    qtwidgets = pytest.importorskip("PySide6.QtWidgets")
    if not hasattr(qtwidgets, "QDoubleSpinBox"):
        pytest.skip("PySide6 подменён заглушкой соседним тестом")
    from PySide6.QtCore import QLocale
    QLocale.setDefault(QLocale(QLocale.Language.Russian,
                               QLocale.Country.Russia))
    app = qtwidgets.QApplication.instance() or qtwidgets.QApplication([])
    from src.ui.particles_panel import _NumSpin

    spin = _NumSpin()
    spin.setRange(0, 1000)
    spin.setDecimals(2)
    for typed, expected in (("12.5", 12.5), ("3,25", 3.25), ("48", 48.0)):
        spin.lineEdit().setText("")
        for ch in typed:
            spin.lineEdit().insert(ch)
        spin.interpretText()
        assert spin.value() == expected, typed
    del app


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
