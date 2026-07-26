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


def test_sheet_animation_fit_lifetime():
    """Sheet-анимация (много кадров в одной секвенции) с
    animation_fit_lifetime растягивается на всю жизнь частицы; без флага и
    при rate=1 длинная анимация почти стоит (кадр 0). Реальный кейс:
    workshop animated_vortex_energy — 30 кадров, particle живёт секунды."""
    build = """
      const frames = [];
      for (let i = 0; i < 30; i++)
        frames.push({ duration: 1.0, coords: [[i/30, 0, (i+1)/30, 1]] });
      const sheet = { sequences: { 1: { clamp: false, duration: 30, frames } } };
      const mk = (fit, rate, asFps) => {
        const def = {
          name: 'fx',
          attrs: { max_particles: {t:'integer', v:2}, radius: {t:'float', v:5},
                   material: {t:'string', v:'m'} },
          renderers: [{functionName:'render_animated_sprites', attrs:{
            'animation rate': {t:'float', v:rate},
            'use animation rate as fps': {t:'bool', v:!!asFps},
            'animation_fit_lifetime': {t:'bool', v:fit} }}],
          emitters: [{functionName:'emit_instantaneously',
                      attrs:{num_to_emit:{t:'integer', v:1}}}],
          initializers: [
            {functionName:'Position Within Sphere Random',
             attrs:{distance_max:{t:'float', v:0}}},
            {functionName:'Lifetime Random',
             attrs:{lifetime_min:{t:'float', v:2}, lifetime_max:{t:'float', v:2}}}],
          operators: [{functionName:'Lifespan Decay', attrs:{}}],
          forces: [], constraints: [], children: []
        };
        return new ParticleSystemInstance(def, {fx: def}, {m: {sheet}},
                                          {controlPoints: [[0,0,0]]});
      };
      const frameAt = (sys, t) => {
        while (sys.curTime < t - 1e-6) sys.movement(1/60);
        const out = []; sys.collectSprites(out, []);
        return out.length ? Math.round(out[0].uv0[2] * 30) : -1;
      };
    """
    res = _run_js(build + """
      const fit = mk(true, 1, false);
      const loops = mk(false, 1, false);   // rate = ЦИКЛОВ/сек
      const fps1 = mk(false, 1, true);     // rate = КАДРОВ/сек
      return {
        fit_start: frameAt(fit, 0.1), fit_mid: frameAt(fit, 1.0),
        fit_end: frameAt(fit, 1.9),
        loops_mid: frameAt(loops, 0.5),
        fps1_end: frameAt(fps1, 1.9),
      };
    """)
    # С fit_lifetime кадр растёт от начала к концу жизни
    assert res["fit_start"] < 5, res
    assert res["fit_mid"] > 10, res
    assert res["fit_end"] > 25, res
    # rate=1 без флага fps — ЦИКЛ в секунду: за 0.5 c уже середина листа
    assert res["loops_mid"] > 10, res
    # rate=1 С флагом fps — 1 КАДР в секунду: за 1.9 c почти стоит
    assert res["fps1_end"] <= 2, res


def test_rotation_orient_to_2d_direction_world_plane():
    """Оператор ориентирует в ГОРИЗОНТАЛЬНОЙ ПЛОСКОСТИ МИРА (стороны света),
    без камеры — подтверждено вики Valve и официальным редактором. Реальный
    инцидент: бабочки с ним летали «боком» в игре, а превью (экранная
    версия) показывало красиво — превью врало."""
    res = _run_js("""
      const mk = (vel, offsetDeg, strength) => {
        const def = {
          name: 'fx',
          attrs: { max_particles: {t:'integer', v:2}, radius: {t:'float', v:3},
                   material: {t:'string', v:'m'} },
          renderers: [{functionName:'render_animated_sprites', attrs:{}}],
          emitters: [{functionName:'emit_instantaneously',
                      attrs:{num_to_emit:{t:'integer', v:1}}}],
          initializers: [
            {functionName:'Position Within Sphere Random',
             attrs:{distance_max:{t:'float', v:0}}},
            {functionName:'Velocity Random', attrs:{
              speed_in_local_coordinate_system_min:{t:'vec3', v:vel},
              speed_in_local_coordinate_system_max:{t:'vec3', v:vel}}},
            {functionName:'Lifetime Random',
             attrs:{lifetime_min:{t:'float', v:9}, lifetime_max:{t:'float', v:9}}}],
          operators: [
            {functionName:'Movement Basic', attrs:{}},
            {functionName:'Rotation Orient to 2D Direction',
             attrs:{'rotation offset':{t:'float', v:offsetDeg},
                    'spin strength':{t:'float', v:strength}}}],
          forces: [], constraints: [], children: []
        };
        const sys = new ParticleSystemInstance(def, {fx: def}, {m: {}},
                                               {controlPoints: [[0,0,0]]});
        for (let i = 0; i < 20; i++) sys.movement(1/60);
        return sys.particles[0].rotation;
      };
      return {
        plusX: mk([200,0,0], 0, 1),          // atan2(0,+)=0
        plusY: mk([0,200,0], 0, 1),          // atan2(+,0)=PI/2
        plusX_off90: mk([200,0,0], 90, 1),   // 0 + 90°
        pureZ: mk([0,0,200], 0, 1),          // вертикально — XY вырожден
        zeroStrength: mk([200,0,0], 90, 0),  // strength 0 — не трогает
      };
    """)
    PI = 3.14159265
    assert abs(res["plusX"]) < 1e-3, res
    assert abs(res["plusY"] - PI / 2) < 1e-3, res
    assert abs(res["plusX_off90"] - PI / 2) < 1e-3, res
    # вертикальный полёт и нулевая сила не меняют исходное вращение (0)
    assert abs(res["pureZ"]) < 1e-6, res
    assert abs(res["zeroStrength"]) < 1e-6, res


def test_render_screen_velocity_rotate_marks_sprites():
    """Разворот по скорости НА ЭКРАНЕ — отдельный РЕНДЕРЕР (так делают
    стоковые пауки/призраки: он ставится вторым рядом с
    render_animated_sprites). Движок помечает спрайты: vel + forward_angle;
    экранный угол досчитывает рендер."""
    res = _run_js("""
      const def = {
        name: 'fx',
        attrs: { max_particles: {t:'integer', v:2}, radius: {t:'float', v:3},
                 material: {t:'string', v:'m'} },
        renderers: [
          {functionName:'render_animated_sprites', attrs:{}},
          {functionName:'render_screen_velocity_rotate',
           attrs:{'forward_angle':{t:'float', v:-90},
                  'rotate_rate(dps)':{t:'float', v:0}}}],
        emitters: [{functionName:'emit_instantaneously',
                    attrs:{num_to_emit:{t:'integer', v:1}}}],
        initializers: [
          {functionName:'Position Within Sphere Random',
           attrs:{distance_max:{t:'float', v:0}}},
          {functionName:'Velocity Random', attrs:{
            speed_in_local_coordinate_system_min:{t:'vec3', v:[200,0,0]},
            speed_in_local_coordinate_system_max:{t:'vec3', v:[200,0,0]}}},
          {functionName:'Lifetime Random',
           attrs:{lifetime_min:{t:'float', v:9}, lifetime_max:{t:'float', v:9}}}],
        operators: [{functionName:'Movement Basic', attrs:{}}],
        forces: [], constraints: [], children: []
      };
      const sys = new ParticleSystemInstance(def, {fx: def}, {m: {}},
                                             {controlPoints: [[0,0,0]]});
      for (let i = 0; i < 20; i++) sys.movement(1/60);
      const out = []; sys.collectSprites(out, []);
      const s = out[0];
      return {
        rendererType: sys.rendererType,           // остаётся sprites
        forward: sys.screenVelRotate.forward,
        hasVel: Array.isArray(s.vel),
        velX: s.vel ? s.vel[0] : null,
        hasMeta: !!s.screenVel,
        hasAge: typeof s.age === 'number',
      };
    """)
    assert res["rendererType"] == "sprites"
    assert abs(res["forward"] + 3.14159265 / 2) < 1e-4    # -90° в радианах
    assert res["hasVel"] and res["hasMeta"] and res["hasAge"]
    assert res["velX"] > 0


def test_oscillate_position_feeds_velocity():
    """Oscillate Vector на поле позиции (field 0) в интеграторе Верле
    подмешивается в скорость — частица разгоняется и дёргается, как в
    игре (бабочки). Раньше компенсация prevPos гасила это в гладкий дрейф."""
    res = _run_js("""
      const mk = (osc) => {
        const ops = [{functionName:'Movement Basic',
                      attrs:{drag:{t:'float',v:0}, gravity:{t:'vec3',v:[0,0,0]}}}];
        if (osc) ops.push({functionName:'Oscillate Vector', attrs:{
          'oscillation field':{t:'integer', v:0},
          'oscillation frequency min':{t:'vec3', v:[2,2,2]},
          'oscillation frequency max':{t:'vec3', v:[2,2,2]},
          'oscillation rate min':{t:'vec3', v:[8,8,8]},
          'oscillation rate max':{t:'vec3', v:[8,8,8]},
          'proportional 0/1':{t:'bool', v:false},
          'start time min':{t:'float', v:0}, 'start time max':{t:'float', v:0},
          'end time min':{t:'float', v:1}, 'end time max':{t:'float', v:1},
          'start/end proportional':{t:'bool', v:true}}});
        const def = {
          name:'fx', attrs:{max_particles:{t:'integer', v:2}, radius:{t:'float', v:3},
                            material:{t:'string', v:'m'}},
          renderers:[{functionName:'render_animated_sprites', attrs:{}}],
          emitters:[{functionName:'emit_instantaneously',
                     attrs:{num_to_emit:{t:'integer', v:1}}}],
          initializers:[
            {functionName:'Position Within Sphere Random', attrs:{distance_max:{t:'float', v:0}}},
            {functionName:'Lifetime Random',
             attrs:{lifetime_min:{t:'float', v:9}, lifetime_max:{t:'float', v:9}}}],
          operators: ops, forces:[], constraints:[], children:[]
        };
        return new ParticleSystemInstance(def, {fx: def}, {m: {}},
                                          {controlPoints: [[0,0,0]]});
      };
      const maxSpeed = (sys) => {
        let mx = 0;
        for (let i = 0; i < 120; i++) {
          sys.movement(1/60);
          const p = sys.particles[0];
          mx = Math.max(mx, Math.hypot(p.pos[0]-p.prevPos[0], p.pos[1]-p.prevPos[1],
                                       p.pos[2]-p.prevPos[2]) * 60);
        }
        return mx;
      };
      return { withOsc: maxSpeed(mk(true)), noOsc: maxSpeed(mk(false)) };
    """)
    # без осциллятора частица стоит (нет начальной скорости) → ~0
    assert res["noOsc"] < 1, res
    # осциллятор позиции разгоняет — скорость заметно ненулевая
    assert res["withOsc"] > 20, res


def test_gif_sheet_animates_without_animated_sprites(tmp_path):
    """Гифка, положенная как текстура партикла, анимируется в превью даже у
    системы с обычным render_sprites: sheet-данные из _gif_to_sheet движок
    крутит на дефолтном rate (1 цикл/сек). Проверяется именно тот JSON,
    который отдаёт Python — формат листа легко разъехаться с движком."""
    pytest.importorskip("PIL")
    from PIL import Image

    from src.services.particle_editor_service import ParticleEditorService

    gif = tmp_path / "anim.gif"
    frames = [Image.new("RGB", (32, 32), c)
              for c in ((255, 0, 0), (0, 255, 0), (0, 0, 255))]
    frames[0].save(gif, save_all=True, append_images=frames[1:],
                   duration=100, loop=0)
    _, sheet = ParticleEditorService._gif_to_sheet(str(gif), 256)

    res = _run_js("""
      const sheet = """ + json.dumps(sheet) + """;
      const def = {
        name: 'fx',
        attrs: { max_particles: {t:'integer', v:2}, radius: {t:'float', v:5},
                 material: {t:'string', v:'m'} },
        renderers: [{functionName:'render_sprites', attrs:{}}],
        emitters: [{functionName:'emit_instantaneously',
                    attrs:{num_to_emit:{t:'integer', v:1}}}],
        initializers: [
          {functionName:'Position Within Sphere Random',
           attrs:{distance_max:{t:'float', v:0}}},
          {functionName:'Lifetime Random',
           attrs:{lifetime_min:{t:'float', v:5}, lifetime_max:{t:'float', v:5}}}],
        operators: [], forces: [], constraints: [], children: []
      };
      const sys = new ParticleSystemInstance(def, {fx: def}, {m: {sheet}},
                                             {controlPoints: [[0,0,0]]});
      const cellAt = (t) => {
        while (sys.curTime < t - 1e-6) sys.movement(1/60);
        const out = []; sys.collectSprites(out, []);
        const uv = out[0].uv0;             // [scaleU, scaleV, biasU, biasV]
        return [uv[0], uv[1], uv[2], uv[3]];
      };
      return { f0: cellAt(0.05), f1: cellAt(0.5), f2: cellAt(0.9) };
    """)

    # Кадр занимает четверть листа (сетка 2x2) — масштаб UV 0.5 на кадре
    assert res["f0"][:2] == [0.5, 0.5], res
    # Смещение кадра меняется во времени: (0,0) → (0.5,0) → (0,0.5)
    assert res["f0"][2:] == [0.0, 0.0], res
    assert res["f1"][2:] == [0.5, 0.0], res
    assert res["f2"][2:] == [0.0, 0.5], res
