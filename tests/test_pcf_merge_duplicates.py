"""Одинаковые модули разных систем пишутся в PCF один раз"""

import pytest

dmx = pytest.importorskip("srctools.dmx")
from srctools.dmx import Attribute, Element, ValueType  # noqa: E402

from src.services.particle_editor.export import merge_duplicate_elements  # noqa: E402


def _op(name, drag):
    op = Element(name, "DmeParticleOperator")
    op["functionName"] = Attribute.string("functionName", "Movement Basic")
    op["drag"] = Attribute.float("drag", drag)
    return op


def _system(name, ops, child=None):
    s = Element(name, "DmeParticleSystemDefinition")
    s["operators"] = Attribute.array("operators", ValueType.ELEMENT, ops)
    kids = []
    if child is not None:
        link = Element(child.name, "DmeParticleChild")
        link["child"] = Attribute("child", ValueType.ELEMENT, child)
        kids.append(link)
    s["children"] = Attribute.array("children", ValueType.ELEMENT, kids)
    return s


def _root(*systems):
    root = Element("root", "DmElement")
    root["particleSystemDefinitions"] = Attribute.array(
        "particleSystemDefinitions", ValueType.ELEMENT, list(systems))
    return root


def test_same_modules_become_one_element():
    a = _system("a", [_op("Movement Basic", 0.1), _op("other", 0.5)])
    b = _system("b", [_op("renamed in editor", 0.1)])
    merge_duplicate_elements(_root(a, b))
    assert b["operators"].iter_elem().__next__() is a["operators"].iter_elem().__next__()
    # Разное значение - разные элементы
    assert list(a["operators"].iter_elem())[1] is not list(b["operators"].iter_elem())[0]


def test_systems_and_child_links_are_kept_apart():
    leaf = _system("leaf", [])
    twin = _system("leaf", [])                    # та же начинка, другая система
    p1 = _system("p1", [], child=leaf)
    p2 = _system("p2", [], child=leaf)
    root = _root(leaf, twin, p1, p2)
    merge_duplicate_elements(root)
    systems = list(root["particleSystemDefinitions"].iter_elem())
    assert systems[0] is not systems[1]
    link1 = next(p1["children"].iter_elem())
    link2 = next(p2["children"].iter_elem())
    assert link1 is not link2
