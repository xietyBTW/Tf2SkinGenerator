"""Итог перетаскивания ручек гизмо доходит до документа PCF"""

import pytest

pytest.importorskip("srctools.dmx")

from src.services.particle_editor_service import ParticleEditorService  # noqa: E402
from tests.test_particle_editor_service import _make_pcf_bytes  # noqa: E402


def _svc():
    svc = ParticleEditorService()
    svc.load_bytes(_make_pcf_bytes())
    return svc


def _init(svc, fn):
    mods = svc.systems_json()["fx"]["initializers"]
    return next(m for m in mods if m["functionName"].lower() == fn.lower())


def test_existing_module_gets_the_value():
    svc = _svc()
    err = svc.apply_gizmo_edits("fx", [
        {"group": "initializers", "index": 0, "fn": "Color Random",
         "attr": "color1", "type": "color", "value": [1, 2, 3, 255]}])
    assert err is None
    assert _init(svc, "Color Random")["attrs"]["color1"]["v"] == [1, 2, 3, 255]


def test_module_made_by_the_preview_is_created_here():
    # Превью дописывает модуль смещения в начале протяжки, у документа его нет
    svc = _svc()
    err = svc.apply_gizmo_edits("fx", [
        {"group": "initializers", "index": 1, "fn": "Position Modify Offset Random",
         "attr": "offset min", "type": "vec3", "value": [1, 2, 3]},
        {"group": "initializers", "index": 1, "fn": "Position Modify Offset Random",
         "attr": "offset max", "type": "vec3", "value": [4, 5, 6]}])
    assert err is None
    mods = svc.systems_json()["fx"]["initializers"]
    assert [m["functionName"] for m in mods].count("Position Modify Offset Random") == 1
    attrs = _init(svc, "Position Modify Offset Random")["attrs"]
    assert attrs["offset min"]["v"] == [1, 2, 3]
    assert attrs["offset max"]["v"] == [4, 5, 6]


def test_wrong_index_falls_back_to_the_function_name():
    svc = _svc()
    err = svc.apply_gizmo_edits("fx", [
        {"group": "initializers", "index": 7, "fn": "Color Random",
         "attr": "color1", "type": "color", "value": [9, 9, 9, 255]}])
    assert err is None
    assert len(svc.systems_json()["fx"]["initializers"]) == 1


def test_unknown_system_is_an_error():
    assert _svc().apply_gizmo_edits("nope", [
        {"group": "initializers", "index": 0, "fn": "Color Random",
         "attr": "color1", "type": "color", "value": [0, 0, 0, 255]}])
