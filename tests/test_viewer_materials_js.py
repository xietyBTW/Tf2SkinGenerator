"""
Сборка материала во вьювере (viewer_materials.js) через Node.

Ошибка здесь не видна ни глазами в коде, ни тестами Python: стекло просто
снова станет серым пластиком, как было до того, как превью научили читать VMT.
Блика и отражений в материале нет намеренно — без маски из текстуры они
покрывают модель белёсой плёнкой (см. vmt_render.py).

Тест пропускается, если node недоступен.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

MODULE = Path("src/static/js/viewer_materials.js").resolve()

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not MODULE.exists(),
    reason="node недоступен или viewer_materials.js не найден")

# Заглушка THREE: материал просто запоминает, с чем его создали.
STUB = """
const THREE = {
  DoubleSide: 'double', FrontSide: 'front',
  AdditiveBlending: 'additive', MixOperation: 'mix',
  SRGBColorSpace: 'srgb',
  MeshLambertMaterial: class { constructor(p) { Object.assign(this, p); } },
};
"""


def _run(body: str) -> dict:
    script = f"""
import {{ makeMeshMaterial, materialParams, hintFor }} from {MODULE.as_uri()!r};
{STUB}
const out = (() => {{ {body} }})();
console.log(JSON.stringify(out));
"""
    proc = subprocess.run(["node", "--input-type=module", "-e", script],
                          capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr.strip())
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _material(hint, *, name="mat", with_map=True) -> dict:
    hints = json.dumps({"mat": hint} if hint else {})
    return _run(f"""
      const m = makeMeshMaterial(THREE, {{ map: {'"TEX"' if with_map else 'null'},
                                          name: {name!r} }}, {hints});
      return {{ side: m.side, transparent: !!m.transparent, blending: m.blending || '',
               depthWrite: m.depthWrite, opacity: m.opacity, alphaTest: m.alphaTest,
               name: m.name, hasMap: !!m.map,
               extra: Object.keys(m).filter(k => /shin|spec|reflect|emiss|env/i.test(k)) }};
    """)


def test_material_without_hints_is_the_plain_old_one():
    m = _material(None)
    assert m["side"] == "double"
    assert m["transparent"] is False
    assert m["hasMap"] is True
    assert m["extra"] == []


def test_additive_glass_blends_and_keeps_both_faces():
    """Стекло банки: $additive + $nocull."""
    m = _material({"blend": "add", "twoSided": True})
    assert m["blending"] == "additive"
    assert m["transparent"] is True
    assert m["depthWrite"] is False
    assert m["side"] == "double"          # $nocull 1


def test_no_shine_is_ever_added():
    """Блик без маски покрывал модель «серебряной оболочкой» — его нет."""
    for hint in ({"blend": "opaque"}, {"blend": "add"}, {"blend": "alpha"}):
        assert _material(hint)["extra"] == []


def test_transparent_without_nocull_is_single_sided():
    """Изнанка прозрачной грани смешивалась бы сама с собой дважды."""
    assert _material({"blend": "add"})["side"] == "front"
    assert _material({"blend": "alpha"})["side"] == "front"


def test_opaque_material_stays_double_sided():
    """У декомпилированных моделей встречаются вывернутые нормали."""
    assert _material({"blend": "opaque"})["side"] == "double"


def test_alpha_blend_carries_opacity():
    m = _material({"blend": "alpha", "opacity": 0.4})
    assert m["transparent"] is True
    assert m["opacity"] == 0.4
    assert m["depthWrite"] is False


def test_cutout_writes_depth():
    m = _material({"blend": "cutout", "alphaTest": 0.8})
    assert m["alphaTest"] == 0.8
    assert m["transparent"] is False
    assert "depthWrite" not in m          # не трогаем — three.js пишет глубину


def test_material_keeps_its_name():
    """По имени вьювер находит меш при следующей смене текстуры."""
    assert _material({"blend": "add"})["name"] == "mat"


def test_hint_lookup_is_case_insensitive():
    """Имена материалов в QC у Valve гуляют по регистру."""
    got = _run("""
      return { found: !!hintFor({'c_glass': {blend: 'add'}}, 'C_Glass'),
               missing: hintFor({'c_glass': {}}, 'other') };
    """)
    assert got["found"] is True
    assert got["missing"] is None


def test_params_are_a_pure_function():
    """materialParams не зависит от THREE — её можно проверять отдельно."""
    got = _run("""
      return { add:  materialParams({blend: 'add'}),
               none: materialParams(null) };
    """)
    assert got["add"]["additive"] is True
    assert got["add"]["doubleSide"] is False
    assert got["none"] == {"doubleSide": True}
