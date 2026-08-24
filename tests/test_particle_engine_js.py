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
      // Скорость задаётся в локальной системе CP (x*Forward - y*Right + z*Up
      // при базисе по умолчанию Forward=(0,1,0), Right=(1,0,0)), поэтому
      // мировой +X — это локальное (0,-200,0), а мировой +Y — (200,0,0)
      return {
        plusX: mk([0,-200,0], 0, 1),         // atan2(0,+)=0
        plusY: mk([200,0,0], 0, 1),          // atan2(+,0)=PI/2
        plusX_off90: mk([0,-200,0], 90, 1),  // 0 + 90°
        pureZ: mk([0,0,200], 0, 1),          // вертикально — XY вырожден
        zeroStrength: mk([0,-200,0], 90, 0), // strength 0 — не трогает
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
            // локальное (0,-200,0) = мировой +X (базис CP по умолчанию)
            speed_in_local_coordinate_system_min:{t:'vec3', v:[0,-200,0]},
            speed_in_local_coordinate_system_max:{t:'vec3', v:[0,-200,0]}}},
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


def test_oscillate_proportional_default_accelerates():
    """«proportional 0/1» по умолчанию ИСТИНА (как в Source и стоковых
    модулях): фаза синуса идёт от доли жизни, за жизнь проходит всего
    mult*freq — знак не меняется, и оператор гонит частицу в одну сторону.
    Раньше движок всегда считал фазу от абсолютного времени: в превью был
    аккуратный трепет, а в игре частицы разлетались."""
    res = _run_js("""
      const mk = (proportional) => {
        const osc = {functionName:'Oscillate Vector', attrs:{
          'oscillation field':{t:'integer', v:0},
          'oscillation frequency min':{t:'vec3', v:[0.9,0.9,0]},
          'oscillation frequency max':{t:'vec3', v:[0.9,0.9,0]},
          'oscillation rate min':{t:'vec3', v:[1,1,0]},
          'oscillation rate max':{t:'vec3', v:[1,1,0]},
          'oscillation multiplier':{t:'float', v:1},
          'oscillation start phase':{t:'float', v:0.5},
          'start time min':{t:'float', v:0}, 'start time max':{t:'float', v:0},
          'end time min':{t:'float', v:1}, 'end time max':{t:'float', v:1},
          'start/end proportional':{t:'bool', v:true}}};
        if (proportional !== null)
          osc.attrs['proportional 0/1'] = {t:'bool', v:proportional};
        return mkSystem([{functionName:'Movement Basic',
                          attrs:{drag:{t:'float',v:0}, gravity:{t:'vec3',v:[0,0,0]}}},
                         osc], 9);
      };
      const dist = (sys) => {
        for (let i = 0; i < 60 * 3; i++) sys.movement(1/60);
        const p = sys.particles[0];
        return Math.hypot(p.pos[0], p.pos[1]);
      };
      return { def: dist(mk(null)), off: dist(mk(false)) };
    """)
    # атрибут не задан → как в игре: снос на сотни юнитов за 3 с
    assert res["def"] > 100, res
    # proportional=0 — настоящее колебание вокруг старта
    assert res["off"] < res["def"] / 4, res


def test_movement_drag_is_framerate_independent():
    """drag в PCF — доля, теряемая за 1/30 c (ExponentialDecay в
    C_OP_BasicMovement), а не за кадр: за одинаковое время скорость должна
    падать одинаково при любом FPS."""
    res = _run_js("""
      const speedAfter = (fps) => {
        const sys = mkSystem([
          {functionName:'Movement Basic',
           attrs:{drag:{t:'float', v:0.2}, gravity:{t:'vec3', v:[0,0,0]}}}], 9);
        // начальная скорость 100 по Z
        sys.movement(1/fps);
        const p = sys.particles[0];
        p.prevPos[2] = p.pos[2] - 100 / fps;
        for (let i = 0; i < fps; i++) sys.movement(1/fps);
        return (p.pos[2] - p.prevPos[2]) * fps;
      };
      return { f60: speedAfter(60), f240: speedAfter(240) };
    """)
    assert abs(res["f60"] - res["f240"]) < 0.05 * res["f60"], res
    # (1-0.2)^30 за секунду ≈ 0.12 % от старта — скорость почти погашена
    assert res["f60"] < 1, res


def test_fade_out_starts_near_end_of_life():
    """C_OP_FadeOut: «fade out time» — ДЛИТЕЛЬНОСТЬ угасания перед смертью,
    а не момент старта. При 0.25 частица должна быть полностью видимой на
    середине жизни и гаснуть только в последней четверти."""
    res = _run_js("""
      const op = {functionName:'Alpha Fade Out Random', attrs:{
        'fade out time min':{t:'float', v:0.25},
        'fade out time max':{t:'float', v:0.25},
        'proportional 0/1':{t:'bool', v:true}}};
      const sys = mkSystem([op], 10);
      const at = {};
      for (let i = 0; i < 60 * 10; i++) {
        sys.movement(1/10);
        const p = sys.particles[0];
        if (!p) break;
        const age = Math.round((sys.curTime - p.spawnTime) * 10) / 10;
        if (age === 5.0) at.mid = p.alpha;
        if (age === 7.0) at.beforeFade = p.alpha;
        if (age === 9.0) at.late = p.alpha;
      }
      return at;
    """)
    assert abs(res["mid"] - 1.0) < 1e-6, res          # 50% жизни — непрозрачна
    assert abs(res["beforeFade"] - 1.0) < 1e-6, res  # 70% — угасание ещё не началось
    assert 0.2 < res["late"] < 0.5, res               # 90% — примерно наполовину


def test_velocity_random_reads_random_speed_and_cp_axes():
    """C_INIT_VelocityRandom: параметры зовутся random_speed_*, а локальная
    скорость раскладывается по базису CP (x*Forward - y*Right + z*Up).
    Раньше движок читал несуществующие speed_* и клал локальные оси как мировые."""
    res = _run_js("""
      const mk = (attrs) => {
        const sys = mkSystem([{functionName:'Movement Basic',
                               attrs:{drag:{t:'float',v:0}}}], 9);
        sys.initializers.splice(2, 0, {
          mod: {functionName:'Velocity Random', attrs: attrs},
          fn: null});
        return sys;
      };
      const run = (attrs) => {
        const def = {
          name:'fx', attrs:{max_particles:{t:'integer', v:4}, radius:{t:'float', v:3},
                            material:{t:'string', v:'m'}},
          renderers:[{functionName:'render_animated_sprites', attrs:{}}],
          emitters:[{functionName:'emit_instantaneously',
                     attrs:{num_to_emit:{t:'integer', v:1}}}],
          initializers:[
            {functionName:'Position Within Sphere Random', attrs:{distance_max:{t:'float',v:0}}},
            {functionName:'Lifetime Random',
             attrs:{lifetime_min:{t:'float',v:9}, lifetime_max:{t:'float',v:9}}},
            {functionName:'Velocity Random', attrs: attrs}],
          operators:[{functionName:'Movement Basic', attrs:{drag:{t:'float',v:0}}}],
          forces:[], constraints:[], children:[]
        };
        const sys = new ParticleSystemInstance(def, {fx: def}, {m: {}},
                                               {controlPoints: [[0,0,0]]});
        for (let i = 0; i < 60; i++) sys.movement(1/60);
        return sys.particles[0].pos;
      };
      const local = run({
        speed_in_local_coordinate_system_min:{t:'vec3', v:[100,0,0]},
        speed_in_local_coordinate_system_max:{t:'vec3', v:[100,0,0]}});
      const randSpeed = run({
        random_speed_min:{t:'float', v:100}, random_speed_max:{t:'float', v:100}});
      const oldNames = run({
        speed_min:{t:'float', v:100}, speed_max:{t:'float', v:100}});
      return { local, randSpeed, oldNames };
    """)
    # локальный +X (Forward) = мировой +Y
    assert res["local"][1] > 90 and abs(res["local"][0]) < 1e-6, res
    # random_speed — покомпонентный вектор в кубе: при min=max=100 это (100,100,100)
    assert all(v > 90 for v in res["randSpeed"]), res
    # старые имена атрибутов у этого модуля не существуют — движения быть не должно
    assert all(abs(v) < 1e-6 for v in res["oldNames"]), res


def test_spin_roll_matches_engine_rate():
    """CGeneralSpin: drot = dt * |градусы * (PI/180) * 2PI| — реальная
    скорость в 2PI раз больше «градусов в секунду». Плюс spin_stop_time —
    доля жизни с линейным замедлением, а не секунды с обрывом."""
    res = _run_js("""
      const spin = (extra) => {
        const attrs = {'spin_rate_degrees':{t:'float', v:10}};
        Object.assign(attrs, extra || {});
        const sys = mkSystem([{functionName:'Rotation Spin Roll', attrs: attrs}], 10);
        let total = 0, prev = 0;
        for (let i = 0; i < 10; i++) {          // 1 секунда по 0.1 c
          sys.movement(0.1);
          const r = sys.particles[0].rotation;
          let d = r - prev;
          if (d < -3) d += Math.PI * 2;          // разворот на +-2PI
          total += d; prev = r;
        }
        return total;
      };
      return { plain: spin(), stopped: spin({'spin_stop_time':{t:'float', v:0.1}}) };
    """)
    # 10 град/с * 2PI = 62.8 град/с = 1.0966 рад за секунду
    assert abs(res["plain"] - 1.0966) < 0.01, res
    # stop_time 0.1 от жизни 10 c = 1 c линейного затухания -> примерно половина
    assert 0.4 < res["stopped"] / res["plain"] < 0.7, res


def test_position_lock_fades_out_with_age():
    """C_OP_PositionLock: привязка к CP ослабевает между start_fadeout и
    end_fadeout (доли жизни) и после end_fadeout исчезает совсем. По
    умолчанию (оба = 1) частица держится за CP всю жизнь."""
    res = _run_js("""
      const run = (extra) => {
        const attrs = {'control_point_number':{t:'integer', v:0}};
        Object.assign(attrs, extra || {});
        const sys = mkSystem([
          {functionName:'Movement Basic', attrs:{drag:{t:'float', v:0}}},
          {functionName:'Movement Lock to Control Point', attrs: attrs}], 10);
        const track = [];
        for (let i = 0; i < 100; i++) {        // 10 c шагами по 0.1
          sys.controller.controlPoints[0] = [i, 0, 0];   // CP уезжает по X
          sys.movement(0.1);
          const p = sys.particles[0];
          if (!p) break;
          track.push(p.pos[0]);
        }
        return track;
      };
      const locked = run();
      const faded = run({
        'start_fadeout_min':{t:'float', v:0.2}, 'start_fadeout_max':{t:'float', v:0.2},
        'end_fadeout_min':{t:'float', v:0.6}, 'end_fadeout_max':{t:'float', v:0.6}});
      return {
        lockedLast: locked[locked.length - 1],
        fadedLast: faded[faded.length - 1],
        fadedAt60: faded[59],
        cpLast: 99,
      };
    """)
    # по умолчанию частица едет вместе с CP (первый кадр пропущен: в Source
    # для только что рождённой частицы дельта берётся на момент рождения)
    assert abs(res["lockedLast"] - res["cpLast"]) < 2, res
    # с fadeout она отстаёт и после 60% жизни больше не двигается вовсе
    assert res["fadedLast"] < res["cpLast"] * 0.75, res
    assert abs(res["fadedLast"] - res["fadedAt60"]) < 1e-9, res


def test_operator_fade_envelope_gates_operator():
    """CheckIfOperatorShouldRun: при нулевой силе оператор не запускается
    вовсе. Movement Basic с «operator end fadeout» = 1 после первой секунды
    жизни системы перестаёт двигать частицы — позиция замирает."""
    res = _run_js("""
      const run = (extra) => {
        const attrs = {drag:{t:'float', v:0}, gravity:{t:'vec3', v:[0,0,0]}};
        Object.assign(attrs, extra || {});
        const def = {
          name:'fx', attrs:{max_particles:{t:'integer', v:2}, radius:{t:'float', v:3},
                            material:{t:'string', v:'m'}},
          renderers:[{functionName:'render_animated_sprites', attrs:{}}],
          emitters:[{functionName:'emit_instantaneously',
                     attrs:{num_to_emit:{t:'integer', v:1}}}],
          initializers:[
            {functionName:'Position Within Sphere Random', attrs:{distance_max:{t:'float',v:0}}},
            {functionName:'Lifetime Random',
             attrs:{lifetime_min:{t:'float',v:9}, lifetime_max:{t:'float',v:9}}},
            {functionName:'Velocity Random', attrs:{
              speed_in_local_coordinate_system_min:{t:'vec3', v:[100,0,0]},
              speed_in_local_coordinate_system_max:{t:'vec3', v:[100,0,0]}}}],
          operators:[{functionName:'Movement Basic', attrs: attrs}],
          forces:[], constraints:[], children:[]
        };
        const sys = new ParticleSystemInstance(def, {fx: def}, {m: {}},
                                               {controlPoints: [[0,0,0]]});
        const out = {};
        for (let i = 0; i < 300; i++) {
          sys.movement(1/60);
          const y = sys.particles[0].pos[1];      // локальный +X = мировой +Y
          if (i === 53) out.atStart = y;          // ~0.9 c
          if (i === 119) out.atOne = y;           // ~2.0 c
          out.last = y;
        }
        return out;
      };
      return { plain: run(), gated: run({
        'operator start fadeout':{t:'float', v:0},
        'operator end fadeout':{t:'float', v:1}}) };
    """)
    assert res["plain"]["last"] > 400, res            # 100 ед/с * 5 c
    # до секунды оператор ещё работает, дальше движение полностью замирает
    assert res["gated"]["atStart"] > 80, res
    assert abs(res["gated"]["last"] - res["gated"]["atOne"]) < 1e-9, res
    assert res["gated"]["last"] < res["plain"]["last"] / 4, res


def test_emitter_fade_envelope_scales_rate():
    """Эмиттер получает ту же силу: flEmissionRate *= strength. При линейном
    fadein за 2 c за первую секунду должно родиться примерно вчетверо меньше
    частиц (площадь под треугольником)."""
    res = _run_js("""
      const run = (extra) => {
        const attrs = {emission_rate:{t:'float', v:100}};
        Object.assign(attrs, extra || {});
        const def = {
          name:'fx', attrs:{max_particles:{t:'integer', v:500}, radius:{t:'float', v:3},
                            material:{t:'string', v:'m'}},
          renderers:[{functionName:'render_animated_sprites', attrs:{}}],
          emitters:[{functionName:'emit_continuously', attrs: attrs}],
          initializers:[
            {functionName:'Position Within Sphere Random', attrs:{distance_max:{t:'float',v:0}}},
            {functionName:'Lifetime Random',
             attrs:{lifetime_min:{t:'float',v:30}, lifetime_max:{t:'float',v:30}}}],
          operators:[], forces:[], constraints:[], children:[]
        };
        const sys = new ParticleSystemInstance(def, {fx: def}, {m: {}},
                                               {controlPoints: [[0,0,0]]});
        for (let i = 0; i < 60; i++) sys.movement(1/60);
        return sys.particles.length;
      };
      return { plain: run(), faded: run({
        'operator start fadein':{t:'float', v:0},
        'operator end fadein':{t:'float', v:2}}) };
    """)
    assert 95 <= res["plain"] <= 101, res
    assert 20 <= res["faded"] <= 30, res


def test_control_point_orientation_drives_local_axes():
    """Локальные системы координат берут базис CP: скорость Velocity Random
    ложится по Forward, а «bias in local system» разворачивает и позицию.
    Базис приходит снаружи (controlPointBases) — туда же будет писать
    привязка к attachment модели."""
    res = _run_js("""
      // CP повёрнут: Forward=+Z, Right=+X, Up=-Y
      const basis = {fwd:[0,0,1], right:[1,0,0], up:[0,-1,0]};
      const run = (bases, initAttrs, initFn) => {
        const def = {
          name:'fx', attrs:{max_particles:{t:'integer', v:2}, radius:{t:'float', v:3},
                            material:{t:'string', v:'m'}},
          renderers:[{functionName:'render_animated_sprites', attrs:{}}],
          emitters:[{functionName:'emit_instantaneously',
                     attrs:{num_to_emit:{t:'integer', v:1}}}],
          initializers:[
            {functionName:'Position Within Sphere Random',
             attrs:{distance_max:{t:'float', v:0}}},
            {functionName:'Lifetime Random',
             attrs:{lifetime_min:{t:'float', v:9}, lifetime_max:{t:'float', v:9}}},
            {functionName: initFn, attrs: initAttrs}],
          operators:[{functionName:'Movement Basic', attrs:{drag:{t:'float', v:0}}}],
          forces:[], constraints:[], children:[]
        };
        const sys = new ParticleSystemInstance(def, {fx: def}, {m: {}},
          {controlPoints: [[0,0,0]], controlPointBases: bases});
        for (let i = 0; i < 60; i++) sys.movement(1/60);
        return sys.particles[0].pos;
      };
      const vel = {
        speed_in_local_coordinate_system_min:{t:'vec3', v:[100,0,0]},
        speed_in_local_coordinate_system_max:{t:'vec3', v:[100,0,0]}};
      // сфера радиуса 50 со смещением строго по локальному X и включённым
      // локальным биасом: distance_bias обязан быть не единичным, иначе
      // Source локальную систему не включает
      const sphere = {
        distance_min:{t:'float', v:50}, distance_max:{t:'float', v:50},
        distance_bias:{t:'vec3', v:[1,0,0]},
        'bias in local system':{t:'bool', v:true}};
      return {
        velDefault: run({}, vel, 'Velocity Random'),
        velRotated: run({0: basis}, vel, 'Velocity Random'),
        posDefault: run({}, sphere, 'Position Within Sphere Random'),
        posRotated: run({0: basis}, sphere, 'Position Within Sphere Random'),
      };
    """)
    # дефолтный базис: локальный +X = Forward = мировой +Y
    assert res["velDefault"][1] > 90 and abs(res["velDefault"][0]) < 1e-6, res
    # повёрнутый: тот же локальный +X теперь мировой +Z
    assert res["velRotated"][2] > 90 and abs(res["velRotated"][1]) < 1e-6, res
    # позиция с локальным биасом: |смещение| = 50 вдоль Forward своего базиса
    assert abs(abs(res["posDefault"][1]) - 50) < 1e-4, res
    assert abs(abs(res["posRotated"][2]) - 50) < 1e-4, res


def test_oriented_sprites_get_plane_axes_from_cp():
    """orientation_type 2/3 с «orientation control point» кладут спрайт в
    плоскость базиса CP: ось right спрайта — это Forward контрол-пойнта,
    ось up — его Right (в Source имена перепутаны). Без CP осей нет — рендер
    рисует прежнюю плоскость мира."""
    res = _run_js("""
      const run = (orientType, orientCP) => {
        const def = {
          name:'fx', attrs:{max_particles:{t:'integer', v:2}, radius:{t:'float', v:3},
                            material:{t:'string', v:'m'}},
          renderers:[{functionName:'render_animated_sprites', attrs:{
            'orientation_type':{t:'integer', v:orientType},
            'orientation control point':{t:'integer', v:orientCP}}}],
          emitters:[{functionName:'emit_instantaneously',
                     attrs:{num_to_emit:{t:'integer', v:1}}}],
          initializers:[
            {functionName:'Position Within Sphere Random', attrs:{distance_max:{t:'float',v:0}}},
            {functionName:'Lifetime Random',
             attrs:{lifetime_min:{t:'float',v:9}, lifetime_max:{t:'float',v:9}}}],
          operators:[], forces:[], constraints:[], children:[]
        };
        const sys = new ParticleSystemInstance(def, {fx: def}, {m: {}},
          {controlPoints: [[0,0,0]],
           controlPointBases: {1: {fwd:[0,0,1], right:[1,0,0], up:[0,-1,0]}}});
        sys.movement(1/60);
        const out = []; sys.collectSprites(out, []);
        return out[0];
      };
      const withCP = run(2, 1);
      return {
        right: withCP.right, up: withCP.up,
        noCP: run(2, -1).right === undefined,
        cameraFacing: run(0, 1).right === undefined,
      };
    """)
    assert res["right"] == [0, 0, 1], res     # Forward контрол-пойнта
    assert res["up"] == [1, 0, 0], res        # Right контрол-пойнта
    assert res["noCP"], res
    assert res["cameraFacing"], res


def test_position_offset_respects_local_space_flag():
    """«offset in local space 0/1» поворачивает смещение матрицей CP. Флаг
    игнорировался, и точка спавна в превью уезжала относительно игры —
    у эффектов на оружии это сразу видно."""
    res = _run_js("""
      const run = (local, bases) => {
        const def = {
          name:'fx', attrs:{max_particles:{t:'integer', v:2}, radius:{t:'float', v:3},
                            material:{t:'string', v:'m'}},
          renderers:[{functionName:'render_animated_sprites', attrs:{}}],
          emitters:[{functionName:'emit_instantaneously',
                     attrs:{num_to_emit:{t:'integer', v:1}}}],
          initializers:[
            {functionName:'Position Within Sphere Random', attrs:{distance_max:{t:'float',v:0}}},
            {functionName:'Lifetime Random',
             attrs:{lifetime_min:{t:'float',v:9}, lifetime_max:{t:'float',v:9}}},
            {functionName:'Position Modify Offset Random', attrs:{
              'offset min':{t:'vec3', v:[10,0,0]},
              'offset max':{t:'vec3', v:[10,0,0]},
              'offset in local space 0/1':{t:'bool', v:local}}}],
          operators:[], forces:[], constraints:[], children:[]
        };
        const sys = new ParticleSystemInstance(def, {fx: def}, {m: {}},
          {controlPoints: [[0,0,0]], controlPointBases: bases});
        sys.movement(1/60);
        return sys.particles[0].pos.map(v => Math.round(v * 1000) / 1000);
      };
      return {
        world: run(false, {}),
        localDefault: run(true, {}),
        localRotated: run(true, {0: {fwd:[0,0,1], right:[1,0,0], up:[0,-1,0]}}),
      };
    """)
    assert res["world"] == [10, 0, 0], res
    # базис CP по умолчанию: локальный +X = Forward = мировой +Y
    assert res["localDefault"] == [0, 10, 0], res
    # повёрнутый CP уводит то же смещение в мировой +Z
    assert res["localRotated"] == [0, 0, 10], res


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


#: Голое определение системы: только то, что задаёт тест. Нужен там, где
#: mkSystem не подходит — свои атрибуты системы или свой набор модулей.
_BARE = """
  const bare = (over = {}) => {
    const def = {
      name: 'fx',
      attrs: Object.assign({ max_particles: {t:'integer', v:512},
                             radius: {t:'float', v:5},
                             material: {t:'string', v:'m'} }, over.attrs || {}),
      renderers: [{functionName:'render_animated_sprites', attrs:{}}],
      emitters: over.emitters || [{functionName:'emit_instantaneously',
                                   attrs:{num_to_emit:{t:'integer', v:200}}}],
      initializers: over.initializers || [],
      operators: [], forces: [], constraints: [], children: []
    };
    return new ParticleSystemInstance(def, {fx: def}, {},
      {controlPoints: over.cps || [[0,0,0]],
       controlPointBases: over.bases || undefined});
  };
  const lifetime = (v) => ({functionName:'Lifetime Random',
    attrs:{lifetime_min:{t:'float',v:v}, lifetime_max:{t:'float',v:v}}});
"""


def test_sphere_distance_bias_absolute_value():
    """distance_bias_absolute_value складывает полусферу (fabs у Valve).
    В стоке так сделаны 195 систем — раньше они разлетались полным шаром."""
    res = _run_js(_BARE + """
      const run = (abs) => {
        const s = bare({initializers: [
          {functionName:'Position Within Sphere Random',
           attrs:{ distance_min:{t:'float',v:100}, distance_max:{t:'float',v:100},
                   distance_bias_absolute_value:{t:'vec3', v:abs} }},
          lifetime(10)]});
        s.movement(1/60);
        return s.particles.map(p => p.pos[2]);
      };
      const zAbs = run([0,0,1]), zPlain = run([0,0,0]);
      return {
        negAbs: zAbs.filter(z => z < -1e-6).length,
        negPlain: zPlain.filter(z => z < -1e-6).length,
        n: zAbs.length,
      };
    """)
    assert res["n"] > 100, res
    assert res["negAbs"] == 0, "с fabs по Z ниже плоскости CP частиц быть не должно"
    assert res["negPlain"] > res["n"] * 0.3, "без флага должна быть полная сфера"


def test_sphere_distance_distribution_matches_unit_sphere():
    """Дистанция — длина точки, равномерной по объёму шара (CDF r³):
    внутри половины радиуса должно оказаться ~12.5% частиц."""
    res = _run_js(_BARE + """
      const s = bare({initializers: [
        {functionName:'Position Within Sphere Random',
         attrs:{ distance_min:{t:'float',v:0}, distance_max:{t:'float',v:100} }},
        lifetime(10)],
        emitters: [{functionName:'emit_instantaneously',
                    attrs:{num_to_emit:{t:'integer', v:2000}}}],
        attrs: { max_particles: {t:'integer', v:2000} }});
      s.movement(1/60);
      const d = s.particles.map(p => Math.hypot(p.pos[0], p.pos[1], p.pos[2]));
      return { n: d.length, inner: d.filter(v => v < 50).length / d.length };
    """)
    assert res["n"] == 2000, res
    assert 0.09 < res["inner"] < 0.17, res["inner"]


def test_remap_control_point_to_scalar_axis_name():
    """Ось берётся из 'input field 0-2 X/Y/Z' — короткого 'input field'
    у этого модуля в файлах игры нет, и ось всегда читалась как X."""
    res = _run_js(_BARE + """
      const s = bare({
        cps: [[0,0,0],[0,0,50]],
        initializers: [
          {functionName:'Position Within Sphere Random', attrs:{}},
          lifetime(10),
          {functionName:'Remap Control Point to Scalar',
           attrs:{ 'input control point number':{t:'integer',v:1},
                   'input field 0-2 x/y/z':{t:'integer',v:2},
                   'input minimum':{t:'float',v:0}, 'input maximum':{t:'float',v:50},
                   'output field':{t:'integer',v:3},
                   'output minimum':{t:'float',v:1}, 'output maximum':{t:'float',v:10} }}]});
      s.movement(1/60);
      return { radius: s.particles[0].radius };
    """)
    assert abs(res["radius"] - 10) < 1e-6, res


def test_remap_noise_to_scalar_invert_absolute_value():
    """Флаг называется 'invert absolute value' (сокращённое имя — у
    векторного Velocity Noise), иначе переключатель ничего не делал."""
    res = _run_js(_BARE + """
      const run = (inv) => {
        const s = bare({initializers: [
          {functionName:'Position Within Sphere Random', attrs:{}},
          lifetime(10),
          {functionName:'Remap Noise to Scalar',
           attrs:{ 'spatial noise coordinate scale':{t:'float',v:0},
                   'time noise coordinate scale':{t:'float',v:0},
                   'invert absolute value':{t:'bool',v:inv},
                   'output field':{t:'integer',v:3},
                   'output minimum':{t:'float',v:0},
                   'output maximum':{t:'float',v:100} }}]});
        s.movement(1/60);
        return s.particles[0].radius;
      };
      return { plain: run(false), inverted: run(true) };
    """)
    assert abs(res["plain"] - res["inverted"]) > 1.0, res


def test_initial_particles_spawn_without_emitter():
    """initial_particles — стартовый залп самой системы (591 стоковая
    система); эмиттера при этом может не быть вовсе."""
    res = _run_js(_BARE + """
      const s = bare({emitters: [], initializers: [lifetime(10)],
                      attrs: { initial_particles: {t:'integer', v:7} }});
      s.movement(1/60);
      const after = s.particles.length;
      s.movement(1/60); s.movement(1/60);
      return { after: after, later: s.particles.length };
    """)
    assert res["after"] == 7, res
    assert res["later"] == 7, "залп разовый"


def test_maximum_time_step_clamps_simulation():
    """Шаг симуляции клампится по 'maximum time step' системы (в игре
    дефолт 0.1): иначе при просадке FPS превью считает шагами, которых в
    игре не бывает."""
    res = _run_js(_BARE + """
      const s = bare({attrs: { 'maximum time step': {t:'float', v:0.05} }});
      s.movement(1.0);
      const d = bare({attrs: { 'maximum time step': {t:'float', v:0.0} }});
      d.movement(1.0);
      return { slow: s.curTime, unlimited: d.curTime };
    """)
    assert abs(res["slow"] - 0.05) < 1e-9, res
    # 0 в файле = «без ограничения», остаётся защитный потолок движка
    assert abs(res["unlimited"] - 0.3) < 1e-9, res


def test_velocity_noise_local_space():
    """'apply velocity in local space' раскладывает скорость по осям CP
    (164 стоковых модуля): на повёрнутом CP тот же шум толкает в другую
    сторону мира."""
    res = _run_js(_BARE + """
      const noise = (local) => ({functionName:'Velocity Noise', attrs:{
        'output minimum':{t:'vec3', v:[0,0,50]},
        'output maximum':{t:'vec3', v:[0,0,50]},
        'apply velocity in local space (0/1)':{t:'bool', v:local}}});
      const run = (local, bases) => {
        const s = bare({initializers: [
          {functionName:'Position Within Sphere Random', attrs:{}},
          lifetime(10), noise(local)], bases: bases});
        s.movement(1/60); s.movement(1/60);
        const p = s.particles[0];
        return [0,1,2].map(i => Math.round((p.pos[i] - p.prevPos[i]) * 6000) / 100);
      };
      return {
        world: run(false),
        localDefault: run(true),
        localRotated: run(true, {0: {fwd:[0,0,1], right:[1,0,0], up:[0,-1,0]}}),
      };
    """)
    # мировые оси: скорость по +Z
    assert res["world"][2] > 40 and abs(res["world"][0]) < 1e-6, res
    # базис по умолчанию: локальный +Z = мировой +Z, направление то же
    assert res["localDefault"][2] > 40, res
    # повёрнутый CP: up = мировой -Y
    assert res["localRotated"][1] < -40, res


def test_lock_rotation_carries_particles_around_cp():
    """«lock rotation» тянет частицы и за поворотом контрольной точки
    (1645 стоковых модулей): без него аура на вращающемся CP стояла."""
    res = _run_js(_BARE + """
      const run = (lock) => {
        const s = bare({
          initializers: [
            {functionName:'Position Within Sphere Random',
             attrs:{ distance_min:{t:'float',v:100}, distance_max:{t:'float',v:100} }},
            lifetime(10)],
          emitters: [{functionName:'emit_instantaneously',
                      attrs:{num_to_emit:{t:'integer', v:1}}}],
          bases: {0: {fwd:[1,0,0], right:[0,1,0], up:[0,0,1]}}});
        s.def.operators = [{functionName:'Movement Lock to Control Point',
          attrs:{ 'lock rotation': {t:'bool', v:lock},
                  start_fadeout_min:{t:'float',v:1}, start_fadeout_max:{t:'float',v:1},
                  end_fadeout_min:{t:'float',v:1}, end_fadeout_max:{t:'float',v:1} }}];
        const sys = new ParticleSystemInstance(s.def, {fx: s.def}, {},
          {controlPoints: [[0,0,0]],
           controlPointBases: {0: {fwd:[1,0,0], right:[0,1,0], up:[0,0,1]}}});
        sys.movement(1/60);
        sys.movement(1/60);
        const before = sys.particles[0].pos.slice();
        // CP развернулась на 90° вокруг Z
        sys.controller.controlPointBases[0] = {fwd:[0,1,0], right:[-1,0,0], up:[0,0,1]};
        sys.movement(1/60);
        const after = sys.particles[0].pos.slice();
        return { before: before, after: after };
      };
      return { locked: run(true), free: run(false) };
    """)
    bx, by = res["locked"]["before"][0], res["locked"]["before"][1]
    ax, ay = res["locked"]["after"][0], res["locked"]["after"][1]
    # Поворот на 90° вокруг Z: (x, y) → (-y, x)
    assert abs(ax + by) < 1e-6 and abs(ay - bx) < 1e-6, res["locked"]
    # Без флага частица остаётся на месте
    assert res["free"]["before"] == res["free"]["after"], res["free"]


def test_instantaneous_emitter_respects_max_per_frame():
    """«maximum emission per frame» размазывает залп по кадрам (452 стоковых
    эмиттера); -1 означает «весь залп сразу»."""
    res = _run_js(_BARE + """
      const run = (perFrame) => {
        const s = bare({
          initializers: [lifetime(10)],
          emitters: [{functionName:'emit_instantaneously', attrs:{
            num_to_emit:{t:'integer', v:50},
            'maximum emission per frame':{t:'integer', v:perFrame}}}]});
        const counts = [];
        for (let i = 0; i < 4; i++) { s.movement(1/60); counts.push(s.particles.length); }
        return counts;
      };
      return { spread: run(20), atOnce: run(-1) };
    """)
    assert res["spread"] == [20, 40, 50, 50], res["spread"]
    assert res["atOnce"] == [50, 50, 50, 50], res["atOnce"]


def test_child_control_points_respect_group_id():
    """Оператор адресует детей своей группы, а не всех подряд."""
    res = _run_js("""
      const child = (name, groupId) => ({
        name: name,
        attrs: { max_particles: {t:'integer', v:4}, 'group id': {t:'integer', v:groupId},
                 material: {t:'string', v:'m'} },
        renderers: [], emitters: [], initializers: [], operators: [],
        forces: [], constraints: [], children: []
      });
      const a = child('a', 0), b = child('b', 1);
      const def = {
        name: 'fx',
        attrs: { max_particles: {t:'integer', v:4}, material: {t:'string', v:'m'} },
        renderers: [], initializers: [
          {functionName:'Position Within Sphere Random',
           attrs:{ distance_min:{t:'float',v:50}, distance_max:{t:'float',v:50} }},
          {functionName:'Lifetime Random',
           attrs:{lifetime_min:{t:'float',v:9}, lifetime_max:{t:'float',v:9}}}],
        emitters: [{functionName:'emit_instantaneously',
                    attrs:{num_to_emit:{t:'integer', v:2}}}],
        operators: [{functionName:'Set child control points from particle positions',
                     attrs:{ 'first control point to set':{t:'integer', v:1},
                             '# of control points to set':{t:'integer', v:2},
                             'group id to affect':{t:'integer', v:1} }}],
        forces: [], constraints: [],
        children: [{childName:'a', delay:0}, {childName:'b', delay:0}]
      };
      const sys = new ParticleSystemInstance(def, {fx: def, a: a, b: b}, {},
                                             {controlPoints: [[0,0,0]]});
      sys.movement(1/60); sys.movement(1/60);
      const byName = {};
      for (const c of sys.children) byName[c.name] = Object.keys(c.cpOverrides).length;
      return byName;
    """)
    assert res["b"] == 2, res      # группа 1 — адресована
    assert res["a"] == 0, res      # группа 0 — не тронута


def test_renderer_envelope_gates_drawing():
    """У рендерера та же огибающая, что у операторов: при нулевой силе
    Source его не запускает и частицы не рисуются."""
    res = _run_js(_BARE + """
      const s = bare({initializers: [
        {functionName:'Position Within Sphere Random', attrs:{}}, lifetime(10)]});
      s.def.renderers = [{functionName:'render_animated_sprites', attrs:{
        'operator start fadein': {t:'float', v:0.5},
        'operator end fadein': {t:'float', v:0.5}}}];
      const sys = new ParticleSystemInstance(s.def, {fx: s.def}, {},
                                             {controlPoints: [[0,0,0]]});
      const count = () => { const out = []; sys.collectSprites(out, []); return out.length; };
      sys.movement(1/60);
      const early = count();
      while (sys.curTime < 1.0) sys.movement(1/60);
      return { early: early, later: count() };
    """)
    assert res["early"] == 0, res
    assert res["later"] > 0, res
