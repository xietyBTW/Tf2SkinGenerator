"""Свёртка списка систем PCF в дерево «родитель → дети».

В большом файле определений сотни, а осмысленных эффектов — десятки:
остальное служебные держатели и спавнеры, висящие детьми. Дерево должно
показывать вершины, переживать ссылки на несуществующие системы, повторное
использование одного ребёнка несколькими родителями и циклы.
"""

from src.services.particle_editor_service import (
    flatten_hierarchy, system_hierarchy,
)


def _mk(**parents):
    """{'a': ['b', 'c']} → словарь систем в формате systems_json."""
    return {name: {"attrs": {},
                   "children": [{"childName": c} for c in kids]}
            for name, kids in parents.items()}


def test_flat_file_is_all_roots():
    systems = _mk(a=[], b=[], c=[])
    assert [n for n, _ in system_hierarchy(systems)] == ["a", "b", "c"]


def test_child_is_not_a_root():
    systems = _mk(parent=["kid"], kid=[])
    tree = system_hierarchy(systems)
    assert [n for n, _ in tree] == ["parent"]
    assert tree[0][1] == [("kid", [])]


def test_depth_is_kept():
    systems = _mk(root=["mid"], mid=["leaf"], leaf=[])
    (name, kids), = system_hierarchy(systems)
    assert name == "root"
    assert kids == [("mid", [("leaf", [])])]


def test_shared_child_appears_under_every_parent():
    """В PCF ребёнок — ссылка по имени, а не владение: дублирование честное."""
    systems = _mk(one=["shared"], two=["shared"], shared=[])
    tree = dict(system_hierarchy(systems))
    assert sorted(tree) == ["one", "two"]
    assert tree["one"] == [("shared", [])]
    assert tree["two"] == [("shared", [])]


def test_cycle_keeps_both_visible():
    """Взаимный цикл: корня нет, но из списка ничего пропасть не должно."""
    systems = _mk(a=["b"], b=["a"])
    tree = system_hierarchy(systems)
    assert set(flatten_hierarchy(tree)) == {"a", "b"}


def test_self_reference_is_not_expanded():
    systems = _mk(a=["a", "b"], b=[])
    (name, kids), = system_hierarchy(systems)
    assert name == "a"
    assert kids == [("b", [])]      # сам себя вторым уровнем не показываем


def test_missing_child_is_ignored():
    systems = _mk(parent=["ghost"])
    assert system_hierarchy(systems) == [("parent", [])]


def test_order_argument_controls_roots_order():
    systems = _mk(b=[], a=[])
    assert [n for n, _ in system_hierarchy(systems, order=["a", "b"])] == ["a", "b"]
    # Имена не из файла молча пропускаются
    assert [n for n, _ in system_hierarchy(systems, order=["a", "zzz"])] == ["a"]


def test_flatten_lists_each_name_once():
    systems = _mk(one=["shared"], two=["shared"], shared=[])
    flat = flatten_hierarchy(system_hierarchy(systems))
    assert flat.count("shared") == 1
    assert set(flat) == {"one", "two", "shared"}
    assert flat.index("one") < flat.index("shared")
