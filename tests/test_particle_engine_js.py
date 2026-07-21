"""
Регрессия JS-движка превью (engine.js) через Node.

Движок — ~1200 строк портированной логики Source; ошибки в нём не видны
глазами (эффект просто выглядит «не так, как в игре»). Здесь проверяются
инварианты операторов, на которых мы уже обжигались.

Тест пропускается, если node недоступен.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ENGINE = Path("src/static/js/particles/engine.js").resolve()

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not ENGINE.exists(),
    reason="node недоступен или engine.js не найден")


def _run_js(body: str) -> dict:
    """Выполняет фрагмент в Node с импортом движка, возвращает JSON-результат."""
    script = f"""
import {{ ParticleSystemInstance }} from {ENGINE.as_uri()!r};

const mkSystem = (operators, lifetime = 8) => {{
  const def = {{
    name: 'fx',
    attrs: {{ max_particles: {{t:'integer', v:16}}, radius: {{t:'float', v:5}},
             material: {{t:'string', v:'m'}} }},
    renderers: [{{functionName:'render_animated_sprites', attrs:{{}}}}],
    emitters: [{{functionName:'emit_instantaneously',
                attrs:{{num_to_emit:{{t:'integer', v:4}}}}}}],
    initializers: [
      {{functionName:'Position Within Sphere Random',
        attrs:{{ distance_min:{{t:'float',v:0}}, distance_max:{{t:'float',v:0}} }}}},
      {{functionName:'Lifetime Random',
        attrs:{{ lifetime_min:{{t:'float',v:lifetime}},
                lifetime_max:{{t:'float',v:lifetime}} }}}}],
    operators: [{{functionName:'Lifespan Decay', attrs:{{}}}}, ...operators],
    forces: [], constraints: [], children: []
  }};
  return new ParticleSystemInstance(def, {{fx: def}}, {{}},
                                    {{controlPoints: [[0,0,0]]}});
}};

/** Диапазон значения поля частицы за n секунд симуляции. */
const spanOf = (sys, pick, seconds = 8) => {{
  let lo = Infinity, hi = -Infinity, first = null;
  for (let i = 0; i < 60 * seconds; i++) {{
    sys.movement(1 / 60);
    const p = sys.particles[0];
    if (!p) break;
    const v = pick(p);
    if (first === null) first = v;
    lo = Math.min(lo, v); hi = Math.max(hi, v);
  }}
  return {{ lo, hi, span: hi - lo }};
}};

/** Момент, когда значение впервые отклонилось от стартового. */
const firstChangeTime = (sys, pick, seconds = 8) => {{
  const start = sys.particles.length ? pick(sys.particles[0]) : 0;
  for (let i = 0; i < 60 * seconds; i++) {{
    sys.movement(1 / 60);
    const p = sys.particles[0];
    if (!p) break;
    if (Math.abs(pick(p) - start) > 1e-4) return sys.curTime;
  }}
  return null;
}};

const result = (() => {{ {body} }})();
console.log(JSON.stringify(result));
"""
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, f"node упал:\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


#: Осциллятор с параметрами, как в стоковых эффектах Valve: окно задано
#: долей жизни через «start/end proportional», а «proportional 0/1» = false.
_OSC = """
  const osc = (field, rate) => ({
    functionName: 'Oscillate Vector',
    attrs: {
      'oscillation start phase': {t:'float', v:0.5},
      'oscillation multiplier': {t:'float', v:2.0},
      'start/end proportional': {t:'bool', v:true},
      'proportional 0/1': {t:'bool', v:false},
      'start time min': {t:'float', v:0.2}, 'start time max': {t:'float', v:0.2},
      'end time min': {t:'float', v:1.0}, 'end time max': {t:'float', v:1.0},
      'oscillation frequency min': {t:'vec3', v:[1,1,0]},
      'oscillation frequency max': {t:'vec3', v:[1,1,0]},
      // min == max: движок не тянет случайное значение из диапазона,
      // иначе для конкретной частицы могло выпасть ~0 и тест флейкал
      'oscillation rate min': {t:'vec3', v:[rate,rate,0]},
      'oscillation rate max': {t:'vec3', v:[rate,rate,0]},
      'oscillation field': {t:'integer', v:field},
    }});
"""


def test_oscillate_vector_moves_position():
    """Поле 0 — позиция; окно берётся из «start/end proportional» (доля
    жизни), а не из «proportional 0/1» (иначе осцилляция обрывалась через
    секунду и в превью выглядела как отсутствующая)."""
    res = _run_js(_OSC + """
      const s = spanOf(mkSystem([osc(0, 25)]), p => p.pos[0]);
      const t0 = firstChangeTime(mkSystem([osc(0, 25)]), p => p.pos[0]);
      return { span: s.span, firstChange: t0 };
    """)
    assert res["span"] > 0.5, "позиция должна заметно колебаться"
    # 20% жизни (8 c) = 1.6 c; в секундах это было бы 0.2 c
    assert 1.4 < res["firstChange"] < 2.0, res["firstChange"]


def test_oscillate_vector_scalar_field():
    """Поле 4 (вращение) — 285 стоковых модулей; раньше такой оператор
    молча не делал ничего."""
    res = _run_js(_OSC + """
      const s = spanOf(mkSystem([osc(4, 6)]), p => p.rotation);
      return { span: s.span };
    """)
    assert res["span"] > 0.1, "вращение должно колебаться"


def test_oscillate_vector_respects_window_end():
    """За пределами окна оператор молчит: с end=0.5 доли жизни движение
    во второй половине жизни прекращается."""
    res = _run_js(_OSC + """
      const half = osc(0, 25);
      half.attrs['end time min'] = {t:'float', v:0.5};
      half.attrs['end time max'] = {t:'float', v:0.5};
      const sys = mkSystem([half]);
      for (let i = 0; i < 60 * 5; i++) sys.movement(1/60);   // 5 c из 8
      const at5 = sys.particles[0].pos[0];
      for (let i = 0; i < 60 * 2; i++) sys.movement(1/60);
      return { at5, at7: sys.particles[0].pos[0] };
    """)
    assert abs(res["at7"] - res["at5"]) < 1e-6, "после окна движения быть не должно"
