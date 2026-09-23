"""
Изгиб гирлянды: вьювер (viewer_bend.js) и сборка (festive_decor) считают одно.

Разойдись формулы — в игре гирлянда оказалась бы не там, где её согнули в
превью. Здесь один и тот же набор вершин гнётся обеими реализациями, и
результат сравнивается по числам. JS считает в осях сцены, Python — в осях
SMD, так что заодно проверяется и перевод осей.

Тест пропускается, если node недоступен.
"""

import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from src.services import festive_decor

MODULE = Path("src/static/js/viewer_bend.js").resolve()

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not MODULE.exists(),
    reason="node недоступен или viewer_bend.js не найден")


def _run_js(parts_scene, bends):
    script = f"""
import {{ applyBends }} from {json.dumps(MODULE.as_uri())};
const parts = {json.dumps(parts_scene)};
applyBends(parts, {json.dumps(bends)});
console.log(JSON.stringify(parts.map(p => p.positions)));
"""
    out = subprocess.run(["node", "--input-type=module", "-e", script],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_js_and_python_bend_the_same():
    rnd = random.Random(7)
    # Провод (свои вершины) и две «лампочки» по три вершины: одна жёсткая
    # группа тянется через оба меша, как лампочка с патроном.
    smd = [[rnd.uniform(-5, 5), rnd.uniform(-5, 5), rnd.uniform(0, 20)] for _ in range(24)]
    groups = [-1] * 18 + [0, 0, 0, 1, 1, 1]
    bends = [{"c": [0, 0, 8], "r": 6, "d": [0, 2, 1]},
             {"c": [1, -1, 12], "r": 4, "d": [-1, 0, 3]}]

    expected = [list(p) for p in smd]
    festive_decor.apply_bends(expected, groups, bends)

    to_scene = lambda p: [p[0], p[2], -p[1]]   # noqa: E731
    split = 21                                  # второй меш — с вершины 21
    parts = [{"positions": [c for p in smd[:split] for c in to_scene(p)],
              "groups": groups[:split]},
             {"positions": [c for p in smd[split:] for c in to_scene(p)],
              "groups": groups[split:]}]
    got = _run_js(parts, bends)
    flat = got[0] + got[1]
    got_smd = [[flat[3 * i], -flat[3 * i + 2], flat[3 * i + 1]] for i in range(len(smd))]

    for a, b in zip(expected, got_smd):
        assert a == pytest.approx(b, abs=1e-6)
    # И изгиб правда что-то сдвинул.
    assert any(a != pytest.approx(s, abs=1e-6) for a, s in zip(expected, smd))
