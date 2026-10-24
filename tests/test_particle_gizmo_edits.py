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


def test_edit_names_its_own_system():
    # Гизмо двигает весь эффект: правки дочерних приходят под именем корня
    svc = _svc()
    err = svc.apply_gizmo_edits("root_not_here", [
        {"system": "fx", "group": "initializers", "index": 0, "fn": "Color Random",
         "attr": "color1", "type": "color", "value": [4, 5, 6, 255]}])
    assert err is None
    assert _init(svc, "Color Random")["attrs"]["color1"]["v"] == [4, 5, 6, 255]


def _shared_kid():
    # Двое эффектов делят одного ребёнка, как gas_can_impact_red и _blue
    svc = _svc()
    for name in ("a", "b", "kid"):
        assert svc.duplicate_system("fx", name)
    assert svc.add_child("a", "kid")
    assert svc.add_child("b", "kid")
    return svc


def _color(svc, system):
    mods = svc.systems_json()[system]["initializers"]
    return next(m for m in mods if m["functionName"] == "Color Random")["attrs"]["color1"]["v"]


def test_shared_child_gets_its_own_copy():
    svc = _shared_kid()
    before = _color(svc, "kid")
    err = svc.apply_gizmo_edits("a", [
        {"system": "kid", "group": "initializers", "index": 0, "fn": "Color Random",
         "attr": "color1", "type": "color", "value": [7, 7, 7, 255]}])
    assert err is None
    systems = svc.systems_json()
    kids_a = [c["childName"] for c in systems["a"]["children"]]
    kids_b = [c["childName"] for c in systems["b"]["children"]]
    assert "kid_a" in kids_a and "kid" not in kids_a
    assert "kid" in kids_b
    assert _color(svc, "kid_a") == [7, 7, 7, 255]
    assert _color(svc, "kid") == before


def test_own_child_is_edited_in_place():
    svc = _svc()
    for name in ("a", "kid"):
        assert svc.duplicate_system("fx", name)
    assert svc.add_child("a", "kid")
    svc.apply_gizmo_edits("a", [
        {"system": "kid", "group": "initializers", "index": 0, "fn": "Color Random",
         "attr": "color1", "type": "color", "value": [8, 8, 8, 255]}])
    assert _color(svc, "kid") == [8, 8, 8, 255]
    assert "kid_a" not in svc.systems_json()


def test_shared_reference_element_is_not_relinked_for_the_neighbour():
    # У Valve эффекты делят и сам элемент-ссылку на ребёнка
    from src.services.particle_editor.pcf_format import Attribute, ValueType
    svc = _svc()
    for name in ("a", "b", "kid"):
        assert svc.duplicate_system("fx", name)
    assert svc.add_child("a", "kid")
    a, b = svc._find_definition("a"), svc._find_definition("b")
    ref = [r for r in a["children"].iter_elem() if r["child"].val_elem.name == "kid"][0]
    arr = Attribute.array(b["children"].name, ValueType.ELEMENT)
    arr.append(ref)
    b[b["children"].name] = arr
    svc.apply_gizmo_edits("a", [
        {"system": "kid", "group": "initializers", "index": 0, "fn": "Color Random",
         "attr": "color1", "type": "color", "value": [5, 5, 5, 255]}])
    systems = svc.systems_json()
    assert "kid_a" in [c["childName"] for c in systems["a"]["children"]]
    assert [c["childName"] for c in systems["b"]["children"]] == ["kid"]
    assert _color(svc, "kid") != [5, 5, 5, 255]
