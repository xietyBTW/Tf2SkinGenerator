"""Предупреждение о модулях, которые движок превью не исполняет.

Незнакомый модуль движок молча выбрасывает: эффект в превью ведёт себя
иначе, чем в игре, и понять почему невозможно. Проверка должна поймать это
до сборки — и не шуметь, пока страница ещё не отчиталась о своих
возможностях.
"""

from src.services.particle_lint import check_preview_support

#: Что «умеет» движок в этих тестах
SUPPORTED = {
    "operators": {"movement basic", "lifespan decay"},
    "initializers": {"lifetime random"},
    "renderers": {"render_animated_sprites"},
}
ALIASES = {"basic_movement": "movement basic"}


def _sys(**groups):
    out = {"attrs": {}, "children": []}
    for group, names in groups.items():
        out[group] = [{"functionName": n, "attrs": {}} for n in names]
    return out


def test_silent_until_engine_reports():
    """Пустой supported — страница ещё грузится, обвинять не в чем."""
    systems = {"a": _sys(operators=["Position on Model Random"])}
    assert check_preview_support(systems, {}, {}) == []


def test_reports_unknown_operator():
    systems = {"a": _sys(operators=["Movement Basic", "Movement Lock to Bone"])}
    found = check_preview_support(systems, SUPPORTED, ALIASES)
    assert len(found) == 1
    assert found[0].rule == "not_previewed"
    assert found[0].system == "a"
    assert found[0].params["modules"] == "Movement Lock to Bone"


def test_alias_counts_as_supported():
    """basic_movement — то же, что Movement Basic: жаловаться не на что."""
    systems = {"a": _sys(operators=["basic_movement"])}
    assert check_preview_support(systems, SUPPORTED, ALIASES) == []


def test_case_and_spaces_ignored():
    systems = {"a": _sys(operators=["  MOVEMENT BASIC  "])}
    assert check_preview_support(systems, SUPPORTED, ALIASES) == []


def test_duplicates_collapse_and_sort():
    systems = {"a": _sys(
        operators=["Zeta Op", "Alpha Op", "Zeta Op"],
        initializers=["Position on Model Random"])}
    found = check_preview_support(systems, SUPPORTED, ALIASES)
    assert found[0].params["modules"] == "Alpha Op, Position on Model Random, Zeta Op"


def test_groups_the_engine_never_mentioned_are_not_checked():
    """Движок не отчитался про forces — значит и судить о них не можем."""
    systems = {"a": _sys(forces=["Some Exotic Force"])}
    assert check_preview_support(systems, SUPPORTED, ALIASES) == []


def test_walks_only_the_requested_effect():
    systems = {
        "root": {"attrs": {}, "operators": [], "children": [{"childName": "kid"}]},
        "kid": _sys(operators=["Movement Lock to Bone"]),
        "unrelated": _sys(operators=["Position on Model Random"]),
    }
    names = {f.system for f in check_preview_support(
        systems, SUPPORTED, ALIASES, root_name="root")}
    assert names == {"kid"}


def test_cycle_does_not_hang():
    systems = {
        "a": {"attrs": {}, "operators": [], "children": [{"childName": "b"}]},
        "b": {"attrs": {}, "operators": [], "children": [{"childName": "a"}]},
    }
    assert check_preview_support(systems, SUPPORTED, ALIASES, root_name="a") == []


def test_empty_function_name_is_skipped():
    systems = {"a": _sys(operators=[""])}
    assert check_preview_support(systems, SUPPORTED, ALIASES) == []
