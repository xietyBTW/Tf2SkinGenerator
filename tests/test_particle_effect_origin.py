"""Точка «начало эффекта»: ссылки на место точки 0 уходят на новую точку"""

import pytest

pytest.importorskip("srctools.dmx")

from src.services.particle_editor.origin import ORIGIN_OFFSET, ORIGIN_OP  # noqa: E402
from src.services.particle_editor.pcf_format import (  # noqa: E402
    Attribute, Element, ValueType)
from src.services.particle_editor_service import ParticleEditorService  # noqa: E402
from tests.test_particle_editor_service import _make_pcf_bytes  # noqa: E402


def _module(fn, **attrs):
    """Модуль с атрибутами: двойное подчёркивание в имени - пробел"""
    el = Element(fn, "DmeParticleOperator")
    el["functionName"] = Attribute.string("functionName", fn)
    for name, value in attrs.items():
        key = name.replace("__", " ")
        if isinstance(value, bool):
            el[key] = Attribute.bool(key, value)
        elif isinstance(value, int):
            el[key] = Attribute.int(key, value)
        else:
            el[key] = Attribute.vec3(key, [float(v) for v in value])
    return el


def _append(svc, system, group, mod):
    d = svc._find_definition(system)
    if group not in d:
        d[group] = Attribute.array(group, ValueType.ELEMENT)
    d[group].append(mod)


def _svc():
    svc = ParticleEditorService()
    svc.load_bytes(_make_pcf_bytes())
    return svc


def _mods(svc, system, group):
    return svc.systems_json()[system].get(group) or []


def _cp(mod, name="control_point_number"):
    return mod["attrs"][name]["v"]


def test_root_gets_origin_and_place_refs_move_to_it():
    svc = _svc()
    _append(svc, "fx", "initializers", _module("Position Within Sphere Random", control_point_number=0))
    _append(svc, "fx", "operators", _module("Movement Rotate Particle Around Axis", **{"control__point": 0}))
    _append(svc, "fx_child", "initializers", _module("Position Within Sphere Random", control_point_number=2))
    res = svc.ensure_effect_origin("fx")
    cp = res["cp"]
    assert cp == 3                                   # старшая упомянутая точка 2
    ops = _mods(svc, "fx", "operators")
    assert ops[0]["name"] == ORIGIN_OP
    assert ops[0]["attrs"]["first control point number"]["v"] == cp
    assert ops[0]["attrs"]["control point to offset positions from"]["v"] == 0
    sphere = next(m for m in _mods(svc, "fx", "initializers")
                  if m["functionName"] == "Position Within Sphere Random")
    assert _cp(sphere) == cp
    rotate = next(m for m in ops if m["functionName"] == "Movement Rotate Particle Around Axis")
    assert rotate["attrs"]["control point"]["v"] == cp
    # Чужая точка остаётся своей
    kid = _mods(svc, "fx_child", "initializers")[-1]
    assert _cp(kid) == 2


def test_second_call_reuses_the_origin():
    svc = _svc()
    first = svc.ensure_effect_origin("fx")
    again = svc.ensure_effect_origin("fx")
    assert first == again
    assert [m["name"] for m in _mods(svc, "fx", "operators")].count(ORIGIN_OP) == 1


def test_axes_dependent_spawn_stays_and_gets_local_offset():
    svc = _svc()
    _append(svc, "fx", "initializers", _module(
        "Position Within Sphere Random", control_point_number=0,
        speed_in_local_coordinate_system_min=[0, 0, 50],
        speed_in_local_coordinate_system_max=[0, 0, 50]))
    svc.ensure_effect_origin("fx")
    inits = _mods(svc, "fx", "initializers")
    sphere = next(m for m in inits if m["functionName"] == "Position Within Sphere Random")
    assert _cp(sphere) == 0
    off = next(m for m in inits if m["name"] == ORIGIN_OFFSET)
    assert off["attrs"]["offset in local space 0/1"]["v"] is True
    assert _cp(off) == 0


def test_child_placed_by_parent_particles_is_left_alone():
    svc = _svc()
    _append(svc, "fx", "operators", _module(
        "Set child control points from particle positions",
        **{"first__control__point__to__set": 0, "#__of__control__points__to__set": 1}))
    _append(svc, "fx_child", "initializers", _module("Position Within Sphere Random", control_point_number=0))
    svc.ensure_effect_origin("fx")
    assert _cp(_mods(svc, "fx_child", "initializers")[-1]) == 0


def test_effect_that_counts_points_gets_no_origin():
    # Новая точка изменила бы число частиц у эмиттера, считающего точки
    svc = _svc()
    em = Element("emit_continuously", "DmeParticleOperator")
    em["functionName"] = Attribute.string("functionName", "emit_continuously")
    em["scale emission to used control points"] = Attribute.float(
        "scale emission to used control points", 1.0)
    _append(svc, "fx", "emitters", em)
    res = svc.ensure_effect_origin("fx")
    assert res.get("noOrigin")
    assert not [m for m in _mods(svc, "fx", "operators") if m["name"] == ORIGIN_OP]


def test_rotation_and_model_users_stay_on_point_zero():
    # Поворот и хитбоксы новой точке не передаются
    svc = _svc()
    _append(svc, "fx", "operators", _module(
        "Movement Lock to Control Point", control_point_number=0, **{"lock__rotation": True}))
    _append(svc, "fx", "initializers", _module("Position On Model Random", control_point_number=0))
    svc.ensure_effect_origin("fx")
    lock = next(m for m in _mods(svc, "fx", "operators")
                if m["functionName"] == "Movement Lock to Control Point")
    model = next(m for m in _mods(svc, "fx", "initializers")
                 if m["functionName"] == "Position On Model Random")
    assert _cp(lock) == 0 and _cp(model) == 0


def test_point_named_cp_counts_as_taken():
    svc = _svc()
    _append(svc, "fx", "operators", _module("Position Along Ring", **{"override__cp": 4}))
    assert svc.ensure_effect_origin("fx")["cp"] == 5
