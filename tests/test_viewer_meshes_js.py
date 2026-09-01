"""
Выбор меша под курсором (viewer_meshes.js) через Node.

Эта проверка появилась после настоящего бага: пользовательская текстура
ложилась и на руки класса. Python-тесты его не видят — решение принимается уже
в сцене, по тому, какой меш попал под луч.

Тест пропускается, если node недоступен.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

MODULE = Path("src/static/js/viewer_meshes.js").resolve()

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not MODULE.exists(),
    reason="node недоступен или viewer_meshes.js не найден")

# Сцена вида от первого лица: руки ближе к камере, оружие за ними.
SCENE = """
const weapon = { name: 'c_scattergun', material: { name: 'c_scattergun' } };
const hands  = { name: 'scout_hands',  material: { name: 'scout_hands' } };
const onlyWeapon = new Set(['c_scattergun']);
"""


def _run(body: str) -> dict:
    script = f"""
import {{ isEditableMesh, firstEditableHit }} from {MODULE.as_uri()!r};
{SCENE}
const out = (() => {{ {body} }})();
console.log(JSON.stringify(out));
"""
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_without_a_limit_everything_is_editable():
    """Обычное превью: вся модель принадлежит пользователю."""
    out = _run("""return {
        weapon: isEditableMesh(weapon, null),
        hands:  isEditableMesh(hands, null),
        empty:  isEditableMesh(hands, new Set()),
    };""")
    assert out == {"weapon": True, "hands": True, "empty": True}


def test_limit_lets_the_weapon_through_and_stops_the_hands():
    out = _run("""return {
        weapon: isEditableMesh(weapon, onlyWeapon),
        hands:  isEditableMesh(hands, onlyWeapon),
    };""")
    assert out == {"weapon": True, "hands": False}


def test_material_name_counts_when_the_mesh_is_named_otherwise():
    out = _run("""const odd = { name: 'Object_3', material: { name: 'c_scattergun' } };
        return isEditableMesh(odd, onlyWeapon);""")
    assert out is True


def test_multi_material_mesh_without_a_matching_name_is_refused():
    out = _run("""const multi = { name: 'mix', material: [{ name: 'c_scattergun' }] };
        return isEditableMesh(multi, onlyWeapon);""")
    assert out is False


def test_hands_in_front_do_not_block_the_weapon_behind_them():
    """Закрытая рукой часть ствола обязана принимать текстуру.

    Иначе половина оружия оказалась бы «мёртвой» для перетаскивания.
    """
    out = _run("""const hit = firstEditableHit(
        [{ object: hands }, { object: weapon }], onlyWeapon);
        return hit && hit.name;""")
    assert out == "c_scattergun"


def test_hit_on_the_hands_alone_gives_nothing():
    """Не «красим руки» и не «красим первое попавшееся» — просто мимо."""
    out = _run("""const hit = firstEditableHit([{ object: hands }], onlyWeapon);
        return hit === null;""")
    assert out is True


def test_first_hit_wins_when_nothing_is_limited():
    out = _run("""const hit = firstEditableHit(
        [{ object: hands }, { object: weapon }], null);
        return hit && hit.name;""")
    assert out == "scout_hands"


def test_empty_and_broken_input_is_survivable():
    out = _run("""return {
        none:   firstEditableHit([], onlyWeapon) === null,
        undef:  firstEditableHit(undefined, onlyWeapon) === null,
        holes:  firstEditableHit([null, { object: null }], onlyWeapon) === null,
        noMesh: isEditableMesh(null, onlyWeapon),
    };""")
    assert out == {"none": True, "undef": True, "holes": True, "noMesh": False}
