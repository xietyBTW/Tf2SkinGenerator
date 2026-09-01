"""
Кривая ползунка одинакова в Python и в браузере.

Расчёт продублирован намеренно: гонять каждое движение ползунка в Python —
десятки запросов в секунду. Но разъехавшиеся формулы дали бы разное значение
на одной и той же позиции ручки в окне приложения и на странице, и заметить
это глазами почти невозможно. Поэтому обе стороны считаются на одних числах
и сверяются.

Тест пропускается, если node недоступен.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.services import simple_params as sp

CURVE_JS = Path("frontend/mockup/curve.js").resolve()

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not CURVE_JS.exists(),
    reason="node недоступен или curve.js не найден")

#: Параметры со всеми тремя кривыми и разными границами, в т.ч. знаковыми.
_CASES = [
    {"curve": sp.CURVE_LINEAR, "min": 0.0, "max": 1.0},
    {"curve": sp.CURVE_SQRT, "min": 0.0, "max": 500.0},
    {"curve": sp.CURVE_SIGNED_SQRT, "min": -800.0, "max": 800.0},
    {"curve": sp.CURVE_SQRT, "min": 0.05, "max": 30.0},
]

_FRACTIONS = [0.0, 0.05, 0.25, 0.5, 0.73, 0.99, 1.0]


def _js(params, fractions) -> list:
    """Считает curveValue/curveFraction в Node на тех же входах."""
    script = f"""
import {{ curveFraction, curveValue }} from {CURVE_JS.as_uri()!r};
const params = {json.dumps(params)};
const fractions = {json.dumps(fractions)};
const out = [];
for (const p of params) {{
  for (const f of fractions) {{
    const v = curveValue(p, f);
    out.push([v, curveFraction(p, v)]);
  }}
}}
console.log(JSON.stringify(out));
"""
    tmp = Path("frontend/mockup/_curve_check.mjs")
    tmp.write_text(script, encoding="utf-8")
    try:
        res = subprocess.run(["node", str(tmp)], capture_output=True,
                             text=True, timeout=60)
    finally:
        tmp.unlink(missing_ok=True)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def _param(case):
    return sp.SimpleParam("x", "value", ((),), minimum=case["min"],
                          maximum=case["max"], curve=case["curve"])


def test_curve_matches_python():
    got = _js(_CASES, _FRACTIONS)
    i = 0
    for case in _CASES:
        p = _param(case)
        for f in _FRACTIONS:
            js_value, js_fraction = got[i]
            i += 1
            py_value = sp.curve_value(p, f)
            assert js_value == pytest.approx(py_value, abs=1e-9), (case, f)
            # И обратный ход: значение → та же доля хода.
            assert js_fraction == pytest.approx(
                sp.curve_fraction(p, py_value), abs=1e-9), (case, f)


def test_round_trip_returns_the_same_fraction():
    """Ползунок не должен «прыгать»: значение → доля → значение."""
    for case in _CASES:
        p = _param(case)
        for f in _FRACTIONS:
            v = sp.curve_value(p, f)
            assert sp.curve_fraction(p, v) == pytest.approx(f, abs=1e-9)
