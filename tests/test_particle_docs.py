"""Справочник параметров частиц: связность данных и подписи перечислений.

Справочник — просто данные, но по ним строятся подсказки и списки значений в
редакторе, поэтому опечатка в ключе тихо выключает пояснение. Здесь ловится
именно это: регистр ключей, полнота обоих языков и то, что параметры простого
режима описаны.
"""

from src.data import particle_docs as docs
from src.services.simple_params import SIMPLE_PARAMS


def test_keys_are_lowercase_and_stripped():
    """systems_json отдаёт имена атрибутов casefold-нутыми — ключи должны
    совпадать буквально, иначе поиск промахнётся."""
    for name in list(docs.ATTRS) + list(docs.ENUMS):
        assert name == name.strip().lower(), name
    for group, fn in docs.MODULES:
        assert group == group.strip().lower(), group
        assert fn == fn.strip().lower(), fn


def test_every_entry_has_both_languages():
    for name, pair in docs.ATTRS.items():
        assert len(pair) == 2 and all(pair), name
    for key, pair in docs.MODULES.items():
        assert len(pair) == 2 and all(pair), key
    for name, values in docs.ENUMS.items():
        for value, pair in values.items():
            assert len(pair) == 2 and all(pair), (name, value)


def test_module_groups_are_real():
    from src.services.particle_editor_service import MODULE_GROUPS
    for group, _fn in docs.MODULES:
        assert group in MODULE_GROUPS, group


def test_simple_mode_attributes_are_documented():
    """Всё, что вынесено в простой режим, объяснено и в экспертном дереве."""
    undocumented = sorted({
        ref.attr.lower()
        for p in SIMPLE_PARAMS for variant in p.variants for ref in variant
        if docs.attr_help(ref.attr) is None})
    assert undocumented == [], undocumented


def test_attr_help_language_switch():
    ru = docs.attr_help("max_particles", "ru")
    en = docs.attr_help("max_particles", "en")
    assert ru and en and ru != en
    assert docs.attr_help("no_such_attribute_at_all") is None
    # Регистр и пробелы из PCF не должны мешать
    assert docs.attr_help("  Max_Particles ", "ru") == ru


def test_enum_label_for_particle_fields():
    """Поле 7 — прозрачность: в дереве значение показывается подписью."""
    assert docs.enum_label("output field", 7, "en") == "alpha"
    assert docs.enum_label("oscillation field", 0, "ru") == "позиция XYZ"
    assert docs.enum_label("input field 0-2 x/y/z", 2, "en") == "Z"
    # Не перечисление либо значение вне набора
    assert docs.enum_label("radius", 5, "en") is None
    assert docs.enum_label("output field", 999, "en") is None


def test_enum_label_ignores_bools():
    """bool в Python — подкласс int: True не должен превратиться в «lifetime»."""
    assert docs.enum_label("output field", True, "en") is None


def test_module_help_lookup():
    assert docs.module_help("operators", "Lifespan Decay", "ru")
    assert docs.module_help("operators", "lifespan decay", "en")
    assert docs.module_help("operators", "no such module") is None
