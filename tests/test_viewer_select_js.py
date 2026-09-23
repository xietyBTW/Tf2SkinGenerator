"""
Выделение ножницами (viewer_select.js): детали по острым рёбрам, кисть,
острова развёртки.

Тест пропускается, если node недоступен.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

MODULE = Path("src/static/js/viewer_select.js").resolve()

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not MODULE.exists(),
    reason="node недоступен или viewer_select.js не найден")

#: Куб 2×2×2: 6 граней по 2 треугольника, углы между гранями — 90°.
_CORNERS = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
            (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
_FACES = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4),
          (2, 3, 7, 6), (1, 2, 6, 5), (0, 3, 7, 4)]


def _cube():
    positions, uvs = [], []
    for n, (a, b, c, d) in enumerate(_FACES):
        # Каждой грани — свой квадрат на развёртке: шесть островов.
        u0 = n * 0.15
        quad = {a: (u0, 0), b: (u0 + 0.1, 0), c: (u0 + 0.1, 0.1), d: (u0, 0.1)}
        for tri in ((a, b, c), (a, c, d)):
            for v in tri:
                positions += _CORNERS[v]
                uvs += quad[v]
    return positions, uvs


def _run(body):
    positions, uvs = _cube()
    script = f"""
import * as sel from {json.dumps(MODULE.as_uri())};
const topo = sel.topology(new Float32Array({json.dumps(positions)}),
                          new Float32Array({json.dumps(uvs)}));
const out = (() => {{ {body} }})();
console.log(JSON.stringify(out));
"""
    done = subprocess.run(["node", "--input-type=module", "-e", script],
                          capture_output=True, text=True, check=True)
    return json.loads(done.stdout)


def test_a_detail_stops_at_sharp_edges():
    """Порог 30°: у куба каждая грань — своя деталь (два треугольника)."""
    got = _run("return sel.withLabel(sel.detailLabels(topo, 30), 0);")
    assert sorted(got) == [0, 1]


def test_a_blunt_threshold_takes_the_whole_piece():
    got = _run("return sel.withLabel(sel.detailLabels(topo, 100), 0);")
    assert sorted(got) == list(range(12))


def test_the_brush_stays_within_its_radius():
    # Центр грани z = -1; радиус меньше расстояния до соседних граней.
    got = _run("return sel.brushTriangles(topo, 0, [0, 0, -1], 0.9);")
    assert sorted(got) == [0, 1]
    everything = _run("return sel.brushTriangles(topo, 0, [0, 0, -1], 5);")
    assert sorted(everything) == list(range(12))


def test_islands_follow_the_uv_layout():
    got = _run("return sel.withLabel(topo.islands, 4);")
    assert sorted(got) == [4, 5]


def test_the_brush_takes_long_triangles_it_touches():
    """Бока ствола у моделей TF2 — длинные узкие треугольники: их центр далеко
    от кисти, а край — под ней. Мерить надо до треугольника, не до центра."""
    script = f"""
import * as sel from {json.dumps(MODULE.as_uri())};
// Полоса 20×1 из двух длинных треугольников, кисть у левого конца.
const topo = sel.topology(new Float32Array([0,0,0, 20,0,0, 20,1,0,  0,0,0, 20,1,0, 0,1,0]), null);
console.log(JSON.stringify(sel.brushTriangles(topo, 1, [0.5, 0.5, 0], 1)));
"""
    done = subprocess.run(["node", "--input-type=module", "-e", script],
                          capture_output=True, text=True, check=True)
    assert sorted(json.loads(done.stdout)) == [0, 1]
