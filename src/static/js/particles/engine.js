/**
 * Движок частиц Source (TF2) — порт логики noclip.website ParticleSystem.ts
 * (MIT) на упрощённое AoS-хранение для редактора.
 *
 * Вход: JSON от particle_editor_service.py —
 *   systems:   {имя: {attrs, initializers, operators, emitters, renderers,
 *                     children: [{delay, childName}]}}
 *   materials: {путь: {dataUrl, sheet, additive, shader, width, height}}
 * Все имена атрибутов — в нижнем регистре (так хранит srctools).
 *
 * Рендеринг здесь не выполняется: ParticleSystemInstance только симулирует,
 * particles3d.html снимает состояние через collectSprites().
 */

// ── Утилиты ──────────────────────────────────────────────────────────────── //

const DEG_TO_RAD = Math.PI / 180;
const TWO_PI = Math.PI * 2;

function lerp(a, b, t) { return a + (b - a) * t; }
function invlerp(a, b, v) { return (v - a) / (b - a); }
function saturate(v) { return Math.min(Math.max(v, 0), 1); }
function smoothstep(t) { return t * t * (3 - 2 * t); }
function schlickBias(t, bias) {
    return t / ((((1.0 / bias) - 2.0) * (1.0 - t)) + 1.0);
}

/** Генератор случайных Numerical Recipes — как в noclip (детерминизм рестарта). */
class SeededRNG {
    constructor(seed) { this.state = (seed >>> 0) || ((Math.random() * 0xFFFFFFFF) >>> 0); }
    nextU32() {
        this.state = (Math.imul(this.state, 0x19660d) + 0x3c6ef35f) >>> 0;
        return this.state;
    }
    nextF32() { return this.nextU32() / 0xFFFFFFFF; }
}

/** Чтение атрибута модуля/системы: attr(mod, 'lifetime_min', 0). */
function attr(el, name, def) {
    const a = el.attrs[name.toLowerCase()];
    if (a === undefined || a.v === null || a.v === undefined) return def;
    return a.v;
}

/** Цвет [r,g,b,a] 0–255 → [r,g,b,a] 0–1. */
function colorF(c, def) {
    if (!Array.isArray(c) || c.length < 3) return def;
    return [c[0] / 255, c[1] / 255, c[2] / 255, (c.length > 3 ? c[3] : 255) / 255];
}

function randRangeExp(rand, min, max, exp) {
    if (min === max) return min;
    let v = rand.nextF32();
    v = Math.pow(v, exp);
    return lerp(min, max, v);
}

// ── Шум ──────────────────────────────────────────────────────────────────── //
// ponytail: value-noise вместо SparseConvolutionNoise Valve — гладкий [-1,1],
// формы траекторий близки, побайтового совпадения с игрой нет

function _hash3(x, y, z) {
    let h = (x * 374761393 + y * 668265263 + z * 2147483647) | 0;
    h = Math.imul(h ^ (h >>> 13), 1274126177);
    return (((h ^ (h >>> 16)) >>> 0) / 4294967295) * 2 - 1;
}

function valueNoise3(x, y, z) {
    const xi = Math.floor(x), yi = Math.floor(y), zi = Math.floor(z);
    const xf = x - xi, yf = y - yi, zf = z - zi;
    const u = smoothstep(xf), v = smoothstep(yf), w = smoothstep(zf);
    let n = 0;
    for (let dx = 0; dx <= 1; dx++)
        for (let dy = 0; dy <= 1; dy++)
            for (let dz = 0; dz <= 1; dz++) {
                const weight = (dx ? u : 1 - u) * (dy ? v : 1 - v) * (dz ? w : 1 - w);
                n += weight * _hash3(xi + dx, yi + dy, zi + dz);
            }
    return n;
}

// ── Поля частицы по индексам Source (particles.h) ────────────────────────── //

const SCALAR_FIELDS = {
    1: 'lifetime', 3: 'radius', 4: 'rotation', 5: 'rotSpeed',
    7: 'alpha', 9: 'seq', 10: 'trailLength', 12: 'yaw', 16: 'alpha',
};

function getScalarField(p, field) {
    const k = SCALAR_FIELDS[field];
    return k === undefined ? 0 : p[k];
}

function setScalarField(p, field, val) {
    const k = SCALAR_FIELDS[field];
    if (k !== undefined) p[k] = val;
}

/**
 * Активен ли осциллятор для частицы сейчас.
 *
 * Окно задаётся парами «start/end time min..max» (на частицу выбирается
 * случайное значение в диапазоне). Трактовка времени — по флагу
 * «start/end proportional» (доля жизни vs секунды); отдельный флаг
 * «proportional 0/1» к окну НЕ относится, и раньше окно считалось по нему —
 * из-за этого у эффектов вроде halloween_ghosts (proportional 0/1 = false,
 * start/end proportional = true) осцилляция обрывалась почти сразу.
 */
function oscActive(mod, sys, p, slot) {
    const proportional = attr(mod, 'start/end proportional',
                              attr(mod, 'proportional 0/1', true));
    let age = sys.curTime - p.spawnTime;
    if (proportional) age /= (p.lifetime || 1);
    const sMin = attr(mod, 'start time min', 0);
    const eMin = attr(mod, 'end time min', 1);
    const start = randRangeExpOp(sys, p, slot,
        sMin, attr(mod, 'start time max', sMin), 1);
    const end = randRangeExpOp(sys, p, slot + 1,
        eMin, attr(mod, 'end time max', eMin), 1);
    return age >= Math.min(start, end) && age <= Math.max(start, end);
}

/**
 * Аргумент синуса осцилляторов (Oscillate Scalar/Vector), в единицах
 * SinEst01SIMD: 1.0 = π. По умолчанию «proportional 0/1» = ИСТИНА (так в
 * Source и во всех стоковых модулях) — фаза считается от ДОЛИ ЖИЗНИ частицы,
 * а не от абсолютного времени. За жизнь аргумент проходит всего mult*freq,
 * поэтому знак синуса обычно не меняется: оператор работает не как колебание,
 * а как постоянный снос в свою сторону у каждой частицы.
 */
function oscPhase(mod, sys, p, freq, mult, phase) {
    if (attr(mod, 'proportional 0/1', true)) {
        const age = (sys.curTime - p.spawnTime) / (p.lifetime || 1);
        return mult * age * freq + phase;
    }
    return (mult * sys.curTime + phase) * freq;
}

/**
 * Огибающая силы оператора (flStrength в Source). У КАЖДОГО модуля есть
 * «operator start/end fadein», «operator start/end fadeout» и
 * «operator fade oscillate»: по ним движок считает силу от ВРЕМЕНИ СИСТЕМЫ и
 * при нуле не запускает оператор вовсе (CheckIfOperatorShouldRun).
 * Инициализаторы силу НЕ получают — в Source это прямо прокомментировано
 * («initializers don't support it»), поэтому их огибающая ни на что не влияет.
 *
 * Возвращает null, когда все параметры нулевые (подавляющее большинство
 * модулей) — тогда сила всегда 1 и лишней работы в кадре нет.
 */
function opEnvelope(mod) {
    const inStart = attr(mod, 'operator start fadein', 0);
    const inEnd = attr(mod, 'operator end fadein', 0);
    const outStart = attr(mod, 'operator start fadeout', 0);
    const outEnd = attr(mod, 'operator end fadeout', 0);
    const period = attr(mod, 'operator fade oscillate', 0);
    if (!inStart && !inEnd && !outStart && !outEnd && !period) return null;
    return { inStart, inEnd, outStart, outEnd, period };
}

/** FadeInOut из particles.cpp: сила оператора в момент времени системы. */
function opStrength(env, curTime) {
    if (env === null) return 1;
    let t = curTime;
    if (env.period > 0) t = (t / env.period) % 1;
    if (env.inStart > t) return 0;
    if (env.outEnd > 0 && env.outEnd < t) return 0;
    // порядок границ может быть нарушен автором — Source их выправляет
    const inEnd = Math.max(env.inEnd, env.inStart);
    const outStart = Math.max(env.outStart, inEnd);
    const outEnd = Math.max(env.outEnd, outStart);
    let strength = 1;
    if (inEnd > t && inEnd > env.inStart)
        strength = Math.min(strength, invlerp(env.inStart, inEnd, t));
    if (t > outStart && outEnd > outStart)
        strength = Math.min(strength, invlerp(outEnd, outStart, t));
    return strength;
}

/** Обёртка силы под огибающую: масштабируется её вклад в ускорение. */
function withForceStrength(fn, env) {
    if (env === null) return fn;
    const contrib = [0, 0, 0];
    return (sys, p, accel) => {
        const strength = opStrength(env, sys.curTime);
        if (strength <= 0) return;
        contrib[0] = contrib[1] = contrib[2] = 0;
        fn(sys, p, contrib);
        for (let i = 0; i < 3; i++) accel[i] += contrib[i] * strength;
    };
}

/** SimpleSplineRemapValClamped из mathlib: линейный remap + сглаживание. */
function splineRemapClamped(val, a, b, c, d) {
    if (a === b) return val >= b ? d : c;
    return lerp(c, d, smoothstep(saturate(invlerp(a, b, val))));
}

/**
 * Bias() из mathlib — СТЕПЕННАЯ форма: x^(log(amt)/log(0.5)).
 * Это не тот bias, что в schlickBias (та форма — BiasSIMD, у Alpha Fade Out
 * и Radius Scale); в Source обе живут рядом под похожими именами.
 */
function valveBias(x, amt) {
    return Math.pow(x, Math.log(amt) * -1.4427);
}

function remapValClamped(val, inMin, inMax, outMin, outMax) {
    if (inMin === inMax) return val >= inMax ? outMax : outMin;
    return lerp(outMin, outMax, saturate(invlerp(inMin, inMax, val)));
}

// ── Алиасы старых имён (DMX v1 PCF) и вариантов написания ────────────────── //

const FN_ALIASES = {
    'lifetime_random': 'lifetime random',
    'radius_random': 'radius random',
    'alpha_random': 'alpha random',
    'color_random': 'color random',
    'rotation_random': 'rotation random',
    'position_within_sphere': 'position within sphere random',
    'position_within_box': 'position within box random',
    'initial velocity noise': 'velocity noise',
    'velocity random': 'velocity random',
    'radius_scale': 'radius scale',
    'basic_movement': 'movement basic',
    'lifespan_decay': 'lifespan decay',
    'color_fade': 'color fade',
    'alpha_fade': 'alpha fade and decay',
    'oscillate_scalar': 'oscillate scalar',
    'oscillate_vector': 'oscillate vector',
    'postion_lock_to_controlpoint': 'movement lock to control point',
    'position_lock_to_controlpoint': 'movement lock to control point',
    // Найдено аудитом стоковых PCF: те же модули, но через подчёркивания —
    // без алиасов превью считало их нереализованными и не отыгрывало
    'alpha_fade_in_random': 'alpha fade in random',
    'alpha_fade_out_random': 'alpha fade out random',
    'rotation_spin yaw': 'rotation spin yaw',
    'rotation_spin': 'rotation spin roll',
    'trail_length_random': 'trail length random',
};

function resolveFnName(name) {
    const lower = (name || '').toLowerCase();
    return FN_ALIASES[lower] || lower;
}

/**
 * Базис контрол-пойнта по умолчанию (particles.cpp): Forward=(0,1,0),
 * Right=(1,0,0), Up=(0,0,1) — он НЕ совпадает с мировыми осями. Свой базис
 * задаётся через controller.controlPointBases (см. setControlPointOrientation
 * в particles3d.html); отсюда же будет питаться привязка к attachment модели.
 */
const CP_DEFAULT_BASIS = { fwd: [0, 1, 0], right: [1, 0, 0], up: [0, 0, 1] };

/**
 * Локальные координаты CP → мир по МАТРИЦЕ CP: x*Forward - y*Right + z*Up.
 * Так Source строит matrix3x4 Init(Forward, -Right, Up, позиция) — по ней идут
 * и позиции («bias in local system»), и скорость в Velocity Random.
 */
function cpLocalToWorld(b, v, out) {
    const x = v[0], y = v[1], z = v[2];   // out может быть тем же массивом, что v
    for (let i = 0; i < 3; i++)
        out[i] = x * b.fwd[i] - y * b.right[i] + z * b.up[i];
    return out;
}

/**
 * Порт TransformAxis (particles.h): x*Right + y*Forward + z*Up.
 * Да, это ТРЕТЬЕ сопоставление осей в Source — у матрицы CP минус по Y,
 * у скорости в Position Within Sphere Random плюс, здесь переставлены X и Y.
 * Каждое перенесено как есть: иначе эффект развернёт.
 */
function cpTransformAxis(b, v, out) {
    const x = v[0], y = v[1], z = v[2];
    for (let i = 0; i < 3; i++)
        out[i] = x * b.right[i] + y * b.fwd[i] + z * b.up[i];
    return out;
}

/**
 * Переход от одного базиса контрольной точки к другому — то есть поворот,
 * который CP совершила между кадрами. null, если она не поворачивалась.
 *
 * Знаки осей здесь не важны: одна и та же тройка используется и для
 * разложения, и для сборки, поэтому договорённость сокращается.
 */
function basisDelta(from, to) {
    if (from === to) return null;
    for (const axis of ['fwd', 'right', 'up'])
        for (let i = 0; i < 3; i++)
            if (Math.abs(from[axis][i] - to[axis][i]) > 1e-9)
                return { from, to };
    return null;
}

/** Поворачивает точку v вокруг center по basisDelta; k — сила (0..1). */
function applyBasisDelta(delta, v, center, k) {
    const { from, to } = delta;
    const rx = v[0] - center[0], ry = v[1] - center[1], rz = v[2] - center[2];
    // Раскладываем по осям прошлого базиса и собираем по осям нынешнего
    const lf = rx * from.fwd[0] + ry * from.fwd[1] + rz * from.fwd[2];
    const lr = rx * from.right[0] + ry * from.right[1] + rz * from.right[2];
    const lu = rx * from.up[0] + ry * from.up[1] + rz * from.up[2];
    for (let i = 0; i < 3; i++) {
        const rotated = lf * to.fwd[i] + lr * to.right[i] + lu * to.up[i];
        v[i] = center[i] + lerp(v[i] - center[i], rotated, k);
    }
}

/** Поворот вектора v вокруг оси axis (единичной) на angle — формула Родрига. */
function rotateAboutAxis(v, axis, angle, out) {
    const c = Math.cos(angle), sn = Math.sin(angle);
    const x = v[0], y = v[1], z = v[2];   // out может быть тем же массивом, что v
    const dot = axis[0] * x + axis[1] * y + axis[2] * z;
    const cross = [
        axis[1] * z - axis[2] * y,
        axis[2] * x - axis[0] * z,
        axis[0] * y - axis[1] * x];
    const src = [x, y, z];
    for (let i = 0; i < 3; i++)
        out[i] = src[i] * c + cross[i] * sn + axis[i] * dot * (1 - c);
    return out;
}

/**
 * dt для перевода стартовой скорости в prevPos. В Source это m_flPreviousDt:
 * Movement Basic домножает (xyz-prev) на dt/prevDt, и только с прошлым dt
 * частица стартует ровно с заданной скоростью.
 */
function spawnDt(sys) {
    return sys.prevDeltaTime || sys.deltaTime;
}

function vec3RandomUnit(rand) {
    // Равномерная точка на сфере
    const z = rand.nextF32() * 2 - 1;
    const a = rand.nextF32() * Math.PI * 2;
    const r = Math.sqrt(Math.max(0, 1 - z * z));
    return [r * Math.cos(a), r * Math.sin(a), z];
}

// ── Sheet (спрайт-лист из VTF-ресурса) ───────────────────────────────────── //

class Sheet {
    /** @param {object} json — {sequences: {no: {clamp, duration, frames}}} */
    constructor(json) {
        this.sequences = {};
        for (const [no, seq] of Object.entries(json.sequences || {}))
            this.sequences[no] = seq;
        this.firstSeq = Object.keys(this.sequences)[0];
    }

    getSequence(no) {
        return this.sequences[no | 0] ?? this.sequences[this.firstSeq] ?? null;
    }

    /**
     * UV-преобразования кадра и следующего кадра для момента времени.
     * out0/out1: [scaleU, scaleV, biasU, biasV]. Возвращает blend 0..1.
     * Порт Sheet.calcScaleBias из noclip.
     */
    calcScaleBias(out0, out1, sequenceNo, coord, time) {
        const seq = this.getSequence(sequenceNo);
        if (seq === null || !seq.frames.length) {
            out0[0] = out0[1] = 1; out0[2] = out0[3] = 0;
            out1.set ? out1.set(out0) : (out1[0] = 1, out1[1] = 1, out1[2] = 0, out1[3] = 0);
            return 0;
        }
        time = time % seq.duration;
        if (time < 0 || !isFinite(time)) time = 0;
        let t0 = 0;
        for (let i = 0; i < seq.frames.length; i++) {
            let f0 = seq.frames[i], f1 = seq.frames[i + 1];
            if (f1 === undefined) {
                if (seq.clamp) {
                    setScaleBias(out0, f0.coords[coord]);
                    out1[0] = out0[0]; out1[1] = out0[1]; out1[2] = out0[2]; out1[3] = out0[3];
                    return 0;
                }
                f1 = seq.frames[0];
            } else {
                const t1 = t0 + f0.duration;
                if (time >= t1) { t0 = t1; continue; }
            }
            setScaleBias(out0, f0.coords[coord]);
            setScaleBias(out1, f1.coords[coord]);
            return (time - t0) / f0.duration;
        }
        // время за пределами суммы кадров (погрешность float) — последний кадр
        setScaleBias(out0, seq.frames[seq.frames.length - 1].coords[coord]);
        out1[0] = out0[0]; out1[1] = out0[1]; out1[2] = out0[2]; out1[3] = out0[3];
        return 0;
    }
}

function setScaleBias(dst, c) {
    dst[0] = c[2] - c[0];
    dst[1] = c[3] - c[1];
    dst[2] = c[0];
    dst[3] = c[1];
}

// ── Инициализаторы ───────────────────────────────────────────────────────── //

const INITIALIZERS = {
    'position within sphere random': (mod, sys, p) => {
        const distMin = attr(mod, 'distance_min', 0);
        const distMax = attr(mod, 'distance_max', 0);
        const distBias = attr(mod, 'distance_bias', [1, 1, 1]);
        const distBiasAbs = attr(mod, 'distance_bias_absolute_value', [0, 0, 0]);
        const biasLocal = attr(mod, 'bias in local system', false);
        const cpNo = attr(mod, 'control_point_number', 0);
        const speedMin = attr(mod, 'speed_min', 0);
        const speedMax = attr(mod, 'speed_max', 0);
        const speedExp = attr(mod, 'speed_random_exponent', 1);
        const speedLocalMin = attr(mod, 'speed_in_local_coordinate_system_min', [0, 0, 0]);
        const speedLocalMax = attr(mod, 'speed_in_local_coordinate_system_max', [0, 0, 0]);

        // C_INIT_CreateWithinSphere: направление и дистанция — из ОДНОГО
        // броска (RandomVectorInUnitSphere возвращает точку и её длину).
        // У точки, равномерной по объёму шара, CDF длины = r³, то есть
        // cbrt(random) — это и есть доля для лерпа distance_min..max.
        let dir = vec3RandomUnit(sys.rand);
        const unitLen = Math.cbrt(sys.rand.nextF32());
        // distance_bias_absolute_value: ненулевая компонента складывает
        // соответствующую полусферу в другую (fabs у Valve) — в стоке так
        // сделаны 195 «полусферических» систем
        for (let i = 0; i < 3; i++)
            if (distBiasAbs[i] !== 0) dir[i] = Math.abs(dir[i]);
        if (distBias[0] !== 1 || distBias[1] !== 1 || distBias[2] !== 1) {
            dir = [dir[0] * distBias[0], dir[1] * distBias[1], dir[2] * distBias[2]];
            const len = Math.hypot(dir[0], dir[1], dir[2]) || 1;
            dir = [dir[0] / len, dir[1] / len, dir[2] / len];
        }
        const distance = lerp(distMin, distMax, unitLen);
        const cp = sys.getControlPoint(cpNo);
        const basis = sys.getControlPointBasis(cpNo);
        const off = [dir[0] * distance, dir[1] * distance, dir[2] * distance];
        // Source: локальную систему включает ТОЛЬКО сочетание «есть distance_bias»
        // и «bias in local system» — иначе точка просто смещается на позицию CP
        const hasBias = distBias[0] !== 1 || distBias[1] !== 1 || distBias[2] !== 1;
        if (hasBias && biasLocal) cpLocalToWorld(basis, off, off);
        const px = off[0] + cp[0], py = off[1] + cp[1], pz = off[2] + cp[2];
        p.pos[0] = px; p.pos[1] = py; p.pos[2] = pz;

        // Source применяет случайную скорость только при speed_max > 0
        const speed = speedMax > 0
            ? randRangeExp(sys.rand, speedMin, speedMax, speedExp) : 0;
        // Локальные оси CP: x*Forward + y*Right + z*Up. Здесь, в отличие от
        // матрицы CP и Velocity Random, знак Y НЕ инвертируется (так в Source)
        const l = [0, 0, 0];
        for (let i = 0; i < 3; i++)
            l[i] = lerp(speedLocalMin[i], speedLocalMax[i], sys.rand.nextF32());
        const sdt = spawnDt(sys);
        const pos = [px, py, pz];
        for (let i = 0; i < 3; i++) {
            const v = dir[i] * speed +
                l[0] * basis.fwd[i] + l[1] * basis.right[i] + l[2] * basis.up[i];
            p.prevPos[i] = pos[i] - v * sdt;
        }
    },

    'lifetime random': (mod, sys, p) => {
        p.lifetime = randRangeExp(
            sys.rand,
            attr(mod, 'lifetime_min', 0),
            attr(mod, 'lifetime_max', 0),
            attr(mod, 'lifetime_random_exponent', 1));
    },

    'alpha random': (mod, sys, p) => {
        p.alpha = randRangeExp(
            sys.rand,
            attr(mod, 'alpha_min', 255) / 255,
            attr(mod, 'alpha_max', 255) / 255,
            attr(mod, 'alpha_random_exponent', 1));
    },

    'color random': (mod, sys, p) => {
        const c1 = colorF(attr(mod, 'color1', null), [1, 1, 1, 1]);
        const c2 = colorF(attr(mod, 'color2', null), [1, 1, 1, 1]);
        const t = sys.rand.nextF32();
        p.color[0] = lerp(c1[0], c2[0], t);
        p.color[1] = lerp(c1[1], c2[1], t);
        p.color[2] = lerp(c1[2], c2[2], t);
    },

    'radius random': (mod, sys, p) => {
        p.radius = randRangeExp(
            sys.rand,
            attr(mod, 'radius_min', 1),
            attr(mod, 'radius_max', 1),
            attr(mod, 'radius_random_exponent', 1));
    },

    'trail length random': (mod, sys, p) => {
        p.trailLength = randRangeExp(
            sys.rand,
            attr(mod, 'length_min', 0.1),
            attr(mod, 'length_max', 0.1),
            attr(mod, 'length_random_exponent', 1));
    },

    'position modify offset random': (mod, sys, p) => {
        const min = attr(mod, 'offset min', [0, 0, 0]);
        const max = attr(mod, 'offset max', [0, 0, 0]);
        const propRadius = attr(mod, 'offset proportional to radius 0/1', false);
        const off = [0, 0, 0];
        for (let i = 0; i < 3; i++) {
            off[i] = lerp(min[i], max[i], sys.rand.nextF32());
            if (propRadius) off[i] *= p.radius;
        }
        // «offset in local space 0/1»: смещение поворачивается матрицей CP
        // (VectorRotate, без переноса). Раньше флаг игнорировался, и точка
        // спавна в превью уезжала относительно игры на всю длину смещения —
        // особенно заметно у эффектов, привязанных к оружию
        if (attr(mod, 'offset in local space 0/1', false)) {
            const cpNo = attr(mod, 'control_point_number', 0);
            cpLocalToWorld(sys.getControlPointBasis(cpNo), off, off);
        }
        for (let i = 0; i < 3; i++) {
            p.pos[i] += off[i];
            p.prevPos[i] += off[i];
        }
    },

    'rotation random': (mod, sys, p) => {
        p.rotation = attr(mod, 'rotation_initial', 0) * DEG_TO_RAD +
            randRangeExp(
                sys.rand,
                attr(mod, 'rotation_offset_min', 0) * DEG_TO_RAD,
                attr(mod, 'rotation_offset_max', 360) * DEG_TO_RAD,
                attr(mod, 'rotation_random_exponent', 1));
    },

    'rotation speed random': (mod, sys, p) => {
        // C_INIT_RandomRotationSpeed: скорость в град/с, случайный знак
        let speed = attr(mod, 'rotation_speed_constant', 0) +
            randRangeExp(
                sys.rand,
                attr(mod, 'rotation_speed_random_min', 0),
                attr(mod, 'rotation_speed_random_max', 0),
                attr(mod, 'rotation_speed_random_exponent', 1));
        if (attr(mod, 'randomly_flip_direction', true) && sys.rand.nextF32() > 0.5)
            speed = -speed;
        p.rotSpeed = speed * DEG_TO_RAD;
    },

    'sequence random': (mod, sys, p) => {
        const min = attr(mod, 'sequence_min', 0);
        const max = attr(mod, 'sequence_max', 0);
        p.seq = Math.floor(lerp(min, max + 1, sys.rand.nextF32()));
    },

    'sequence two random': (mod, sys, p) => {
        const min = attr(mod, 'sequence_min', 0);
        const max = attr(mod, 'sequence_max', 0);
        p.seq2 = Math.floor(lerp(min, max + 1, sys.rand.nextF32()));
    },

    'lifetime from sequence': (mod, sys, p) => {
        const fps = attr(mod, 'frames per second', 30);
        const sheet = sys.getSheet();
        if (sheet === null) return;
        const seq = sheet.getSequence(p.seq);
        if (seq) p.lifetime = seq.frames.length / fps;
    },

    'position within box random': (mod, sys, p) => {
        const min = attr(mod, 'min', [0, 0, 0]);
        const max = attr(mod, 'max', [0, 0, 0]);
        const cp = sys.getControlPoint(attr(mod, 'control point number', 0));
        for (let i = 0; i < 3; i++) {
            const v = cp[i] + lerp(min[i], max[i], sys.rand.nextF32());
            p.pos[i] = v;
            p.prevPos[i] = v;
        }
    },

    'velocity random': (mod, sys, p) => {
        // C_INIT_VelocityRandom. Параметры называются random_speed_*, а НЕ
        // speed_* (те есть только у Position Within Sphere Random) — раньше
        // движок читал несуществующие имена и терял всю случайную скорость.
        const cpNo = attr(mod, 'control_point_number', 0);
        let speedMin = attr(mod, 'random_speed_min', 0);
        let speedMax = attr(mod, 'random_speed_max', 0);
        if (speedMax < speedMin) { const t = speedMin; speedMin = speedMax; speedMax = t; }
        const localMin = attr(mod, 'speed_in_local_coordinate_system_min', [0, 0, 0]);
        const localMax = attr(mod, 'speed_in_local_coordinate_system_max', [0, 0, 0]);
        const vel = [0, 0, 0];
        if (localMin.some(v => v !== 0) || localMax.some(v => v !== 0)) {
            const local = [0, 0, 0];
            for (let i = 0; i < 3; i++)
                local[i] = lerp(localMin[i], localMax[i], sys.rand.nextF32());
            cpLocalToWorld(sys.getControlPointBasis(cpNo), local, vel);
        }
        // RandomVector: покомпонентно в КУБЕ [min..max], а не направление на
        // сфере × скорость. При min=0 игра толкает частицы в один октант.
        if (speedMax > 0)
            for (let i = 0; i < 3; i++)
                vel[i] += lerp(speedMin, speedMax, sys.rand.nextF32());
        const dt = spawnDt(sys);
        for (let i = 0; i < 3; i++) p.prevPos[i] = p.pos[i] - vel[i] * dt;
    },

    'velocity noise': (mod, sys, p) => {
        // C_INIT_InitialVelocityNoise: скорость из шумового поля по позиции/времени
        const ss = attr(mod, 'spatial noise coordinate scale', 0.01);
        const ts = attr(mod, 'time noise coordinate scale', 1);
        const so = attr(mod, 'spatial coordinate offset', [0, 0, 0]);
        const to = attr(mod, 'time coordinate offset', 0);
        const absVal = attr(mod, 'absolute value', [0, 0, 0]);
        const absInv = attr(mod, 'invert abs value', [0, 0, 0]);
        const outMin = attr(mod, 'output minimum', [0, 0, 0]);
        const outMax = attr(mod, 'output maximum', [1, 1, 1]);
        const t = (sys.curTime + to) * ts;
        const vel = [0, 0, 0];
        for (let i = 0; i < 3; i++) {
            // смещение 49.7*i разносит компоненты по шумовому полю
            let n = valueNoise3(
                p.pos[0] * ss + i * 49.7 + (Array.isArray(so) ? so[0] : 0),
                p.pos[1] * ss + (Array.isArray(so) ? so[1] : 0),
                p.pos[2] * ss + t + (Array.isArray(so) ? so[2] : 0));
            if (absVal[i]) n = Math.abs(n);
            if (absInv[i]) n = 1.0 - Math.abs(n);
            vel[i] = lerp(outMin[i], outMax[i], saturate(n * 0.5 + 0.5));
        }
        // Шум задан в осях CP, а не мира (в стоке 164 модуля): без этого
        // «взлетающие» эффекты на повёрнутом CP летели не туда
        if (attr(mod, 'apply velocity in local space (0/1)', false))
            cpLocalToWorld(sys.getControlPointBasis(
                attr(mod, 'control point number', 0)), vel, vel);
        const sdt = spawnDt(sys);
        for (let i = 0; i < 3; i++) p.prevPos[i] -= vel[i] * sdt;
    },

    'rotation yaw flip random': (mod, sys, p) => {
        // Зеркалит спрайт по горизонтали с заданной вероятностью
        if (sys.rand.nextF32() < attr(mod, 'flip percentage', 0.5))
            p.yawFlip = true;
    },

    'rotation yaw random': (mod, sys, p) => {
        p.yaw = attr(mod, 'yaw_initial', 0) * DEG_TO_RAD +
            randRangeExp(
                sys.rand,
                attr(mod, 'yaw_offset_min', 0) * DEG_TO_RAD,
                attr(mod, 'yaw_offset_max', 360) * DEG_TO_RAD,
                attr(mod, 'yaw_random_exponent', 1));
    },

    'position from parent particles': (mod, sys, p) => {
        // Спавн на позициях частиц родительской системы (искры/следы)
        const velScale = attr(mod, 'inherited velocity scale', 0);
        const inc = Math.max(1, attr(mod, 'particle increment amount', 1) | 0);
        const parent = sys.parent;
        if (!parent || parent.particles.length === 0) {
            p.dead = true;  // некуда спавниться — не оставлять мусор в (0,0,0)
            return;
        }
        const src = parent.particles[(sys.spawnSeq * inc) % parent.particles.length];
        for (let i = 0; i < 3; i++) {
            p.pos[i] = src.pos[i];
            const vel = (src.pos[i] - src.prevPos[i]) * velScale;
            p.prevPos[i] = p.pos[i] - vel;
        }
    },

    'remap initial scalar': (mod, sys, p) => {
        const inField = attr(mod, 'input field', 8);
        const outField = attr(mod, 'output field', 3);
        const inMin = attr(mod, 'input minimum', 0);
        const inMax = attr(mod, 'input maximum', 1);
        const outMin = attr(mod, 'output minimum', 0);
        const outMax = attr(mod, 'output maximum', 1);
        const scale = attr(mod, 'output is scalar of initial random range', false);
        // field 8 = creation time (АБСОЛЮТНОЕ время спавна, как в Source)
        const inVal = inField === 8 ? p.spawnTime : getScalarField(p, inField);
        const out = remapValClamped(inVal, inMin, inMax, outMin, outMax);
        setScalarField(p, outField,
            scale ? getScalarField(p, outField) * out : out);
    },

    'remap initial distance to control point to scalar': (mod, sys, p) => {
        const cp = sys.getControlPoint(attr(mod, 'control point', 0));
        const dist = Math.hypot(
            p.pos[0] - cp[0], p.pos[1] - cp[1], p.pos[2] - cp[2]);
        setScalarField(p, attr(mod, 'output field', 3), remapValClamped(
            dist,
            attr(mod, 'distance minimum', 0), attr(mod, 'distance maximum', 128),
            attr(mod, 'output minimum', 0), attr(mod, 'output maximum', 1)));
    },

    'remap noise to scalar': (mod, sys, p) => {
        const ss = attr(mod, 'spatial noise coordinate scale', 0.01);
        const ts = attr(mod, 'time noise coordinate scale', 1);
        const to = attr(mod, 'time coordinate offset', 0);
        let n = valueNoise3(
            p.pos[0] * ss, p.pos[1] * ss,
            p.pos[2] * ss + (sys.curTime + to) * ts);
        // Скалярный вариант пишет имена целиком ('invert absolute value'),
        // сокращённые 'invert abs value' — у ВЕКТОРНОГО Velocity Noise
        if (attr(mod, 'absolute value', false)) n = Math.abs(n);
        if (attr(mod, 'invert absolute value', false)) n = 1.0 - Math.abs(n);
        setScalarField(p, attr(mod, 'output field', 3), lerp(
            attr(mod, 'output minimum', 0), attr(mod, 'output maximum', 1),
            saturate(n * 0.5 + 0.5)));
    },

    'remap control point to vector': (mod, sys, p) => {
        const cpNo = attr(mod, 'input control point number', 0);
        // CP задаёт код игры (напр. CP9 = цвет шина килстрика). Пока он не
        // выставлен в превью — не затирать цвет/поля нулями
        if (!sys.isControlPointDefined(cpNo)) return;
        const cp = sys.getControlPoint(cpNo);
        const inMin = attr(mod, 'input minimum', [0, 0, 0]);
        const inMax = attr(mod, 'input maximum', [0, 0, 0]);
        const outMin = attr(mod, 'output minimum', [0, 0, 0]);
        const outMax = attr(mod, 'output maximum', [0, 0, 0]);
        const outField = attr(mod, 'output field', 6);
        const target = outField === 0 ? p.pos : (outField === 6 ? p.color : null);
        if (target === null) return;
        for (let i = 0; i < 3; i++)
            target[i] = remapValClamped(cp[i], inMin[i], inMax[i], outMin[i], outMax[i]);
    },

    'remap control point to scalar': (mod, sys, p) => {
        const cpNo = attr(mod, 'input control point number', 0);
        if (!sys.isControlPointDefined(cpNo)) return;
        const cp = sys.getControlPoint(cpNo);
        // Имя поля тут именно такое: у скалярного remap-а от CP игра пишет
        // 'input field 0-2 X/Y/Z' (короткое 'input field' — у remap initial scalar)
        const axis = attr(mod, 'input field 0-2 x/y/z', 0);
        setScalarField(p, attr(mod, 'output field', 3), remapValClamped(
            cp[Math.min(2, Math.max(0, axis))],
            attr(mod, 'input minimum', 0), attr(mod, 'input maximum', 1),
            attr(mod, 'output minimum', 0), attr(mod, 'output maximum', 1)));
    },

    'position modify warp random': (mod, sys, p) => {
        // Случайное масштабирование позиции относительно CP (warp)
        const min = attr(mod, 'warp min', [1, 1, 1]);
        const max = attr(mod, 'warp max', [1, 1, 1]);
        const cp = sys.getControlPoint(attr(mod, 'control point number', 0));
        for (let i = 0; i < 3; i++) {
            const k = lerp(min[i], max[i], sys.rand.nextF32());
            p.pos[i] = cp[i] + (p.pos[i] - cp[i]) * k;
            p.prevPos[i] = cp[i] + (p.prevPos[i] - cp[i]) * k;
        }
    },

    // Контрол-пойнты в превью статичны — скорость CP всегда нулевая
    'velocity inherit from control point': () => {},
};

// ── Операторы ────────────────────────────────────────────────────────────── //

const OPERATORS = {
    'lifespan decay': (mod, sys) => {
        for (const p of sys.particles)
            if (sys.curTime >= p.spawnTime + p.lifetime) p.dead = true;
        sys.killDead();
    },

    'movement basic': (mod, sys) => {
        const gravity = attr(mod, 'gravity', [0, 0, 0]);
        const dt = sys.deltaTime;
        const dt2 = dt * dt;
        // C_OP_BasicMovement: adj_dt = (dt/prevDt) * ExponentialDecay(1-drag,
        // 1/30, dt). «drag» в PCF — доля, теряемая за 1/30 с, а НЕ за кадр:
        // без нормировки превью тормозило частицы вдвое сильнее игры (и по-
        // разному при разном FPS). Ускорение на drag не умножается — как в Source.
        const dragF = Math.pow(Math.max(0, 1 - attr(mod, 'drag', 0)), 30 * dt) *
            (dt / (sys.prevDeltaTime || dt));
        const accel = [0, 0, 0];
        for (const p of sys.particles) {
            accel[0] = gravity[0]; accel[1] = gravity[1]; accel[2] = gravity[2];
            for (const f of sys.forcesList) f(sys, p, accel);
            for (let i = 0; i < 3; i++) {
                const speed = p.pos[i] - p.prevPos[i];
                p.prevPos[i] = p.pos[i];
                p.pos[i] += speed * dragF + accel[i] * dt2;
            }
        }
    },

    'rotation basic': (mod, sys, strength) => {
        for (const p of sys.particles)
            p.rotation += p.rotSpeed * sys.deltaTime * strength;
    },

    'rotation orient to 2d direction': (mod, sys) => {
        // «2D» здесь — горизонтальная плоскость МИРА (стороны света,
        // вид сверху), НЕ экран: подтверждено вики Valve («particles always
        // face east; +90 makes north») и официальным редактором. Камера не
        // участвует — поэтому у камеро-ориентированных спрайтов (бабочки)
        // в игре это выглядит «боком/задом». Для разворота по движению НА
        // ЭКРАНЕ игра использует рендерер render_screen_velocity_rotate.
        const offset = attr(mod, 'rotation offset', 0) * DEG_TO_RAD;
        const strength = attr(mod, 'spin strength', 1);
        for (const p of sys.particles) {
            const vx = p.pos[0] - p.prevPos[0];
            const vy = p.pos[1] - p.prevPos[1];
            if (vx * vx + vy * vy < 1e-12) continue;   // вертикальный полёт
            const target = Math.atan2(vy, vx) + offset;
            let d = target - p.rotation;
            while (d > Math.PI) d -= 2 * Math.PI;
            while (d < -Math.PI) d += 2 * Math.PI;
            p.rotation += strength >= 1 ? d : d * strength;
        }
    },

    'rotation spin roll': (mod, sys, strength) => generalSpin(
        mod, sys, strength, 'rotation',
        'spin_rate_degrees', 'spin_stop_time', 'spin_rate_min'),

    'alpha fade in random': (mod, sys) => {
        const min = attr(mod, 'fade in time min', 0.25);
        const max = attr(mod, 'fade in time max', 0.25);
        const exp = attr(mod, 'fade in time exponent', 1);
        const proportional = attr(mod, 'proportional 0/1', true);
        for (const p of sys.particles) {
            const fadeEnd = randRangeExpOp(sys, p, 0, min, max, exp);
            let t = sys.curTime - p.spawnTime;
            if (proportional) t /= p.lifetime;
            if (t >= fadeEnd) continue;
            t /= fadeEnd;
            p.alpha = p.alphaInit * saturate(smoothstep(t));
        }
    },

    'alpha fade out random': (mod, sys) => {
        // C_OP_FadeOut: значение — ДЛИТЕЛЬНОСТЬ угасания перед смертью, а не
        // момент его начала. Гаснуть начинают с (1 - value) доли жизни; раньше
        // движок брал value как момент старта и гасил частицы сильно раньше игры.
        let min = attr(mod, 'fade out time min', 0.25);
        let max = attr(mod, 'fade out time max', 0.25);
        if (min === 0 && max === 0) min = max = 1e-7;   // как InitParams: FLT_EPSILON
        const exp = attr(mod, 'fade out time exponent', 1);
        const proportional = attr(mod, 'proportional 0/1', true);
        const ease = attr(mod, 'ease in and out', true);
        const bias = attr(mod, 'fade bias', 0.5) || 0.5;
        for (const p of sys.particles) {
            const span = randRangeExpOp(sys, p, 0, min, max, exp);
            let t = sys.curTime - p.spawnTime;
            let start;
            if (proportional) { t /= (p.lifetime || 1); start = 1 - span; }
            else start = p.lifetime - span;
            if (t <= start || span <= 0) continue;
            const frac = saturate((t - start) / span);
            p.alpha = p.alphaInit *
                (1 - (ease ? smoothstep(frac) : schlickBias(frac, bias)));
        }
    },

    'alpha fade in simple': (mod, sys) => {
        const fadeEnd = attr(mod, 'proportional fade in time', 0.25);
        for (const p of sys.particles) {
            let t = (sys.curTime - p.spawnTime) / p.lifetime;
            if (t >= fadeEnd) continue;
            t /= fadeEnd;
            p.alpha = p.alphaInit * saturate(smoothstep(t));
        }
    },

    'alpha fade out simple': (mod, sys) => {
        const dur = 1.0 - attr(mod, 'proportional fade out time', 0.25);
        const fadeStart = 1.0 - dur;
        for (const p of sys.particles) {
            let t = (sys.curTime - p.spawnTime) / p.lifetime;
            if (t <= fadeStart) continue;
            t = (t - fadeStart) / dur;
            p.alpha = p.alphaInit * saturate(smoothstep(1.0 - t));
        }
    },

    'alpha fade and decay': (mod, sys) => {
        const startAlpha = attr(mod, 'start_alpha', 1);
        const endAlpha = attr(mod, 'end_alpha', 0);
        const startFadeIn = attr(mod, 'start_fade_in_time', 0);
        const endFadeIn = attr(mod, 'end_fade_in_time', 0.5);
        const startFadeOut = attr(mod, 'start_fade_out_time', 0.5);
        const endFadeOut = attr(mod, 'end_fade_out_time', 1);
        for (const p of sys.particles) {
            let t = sys.curTime - p.spawnTime;
            if (t >= p.lifetime) { p.dead = true; continue; }
            t /= p.lifetime;
            // saturate ДО smoothstep: при равных границах invlerp даёт ±Inf
            let alpha = p.alphaInit;
            if (t <= endFadeIn)
                alpha *= lerp(startAlpha, 1.0, smoothstep(saturate(invlerp(startFadeIn, endFadeIn, t))));
            if (t >= startFadeOut)
                alpha *= lerp(1.0, endAlpha, smoothstep(saturate(invlerp(startFadeOut, endFadeOut, t))));
            p.alpha = alpha;
        }
        sys.killDead();
    },

    'radius scale': (mod, sys) => {
        const startTime = attr(mod, 'start_time', 0);
        const endTime = attr(mod, 'end_time', 1);
        const startScale = attr(mod, 'radius_start_scale', 1);
        const endScale = attr(mod, 'radius_end_scale', 1);
        const ease = attr(mod, 'ease_in_and_out', false);
        const bias = attr(mod, 'scale_bias', 0.5);
        for (const p of sys.particles) {
            let t = (sys.curTime - p.spawnTime) / p.lifetime;
            t = saturate(invlerp(startTime, endTime, t));
            if (ease) t = smoothstep(t);
            else if (bias !== 0.5) t = schlickBias(t, bias);
            p.radius = lerp(startScale, endScale, t) * p.radiusInit;
        }
    },

    'color fade': (mod, sys) => {
        const fade = colorF(attr(mod, 'color_fade', null), [1, 1, 1, 1]);
        const startTime = attr(mod, 'fade_start_time', 0);
        const endTime = attr(mod, 'fade_end_time', 1);
        const ease = attr(mod, 'ease_in_and_out', true);
        for (const p of sys.particles) {
            let t = (sys.curTime - p.spawnTime) / p.lifetime;
            t = saturate(invlerp(startTime, endTime, t));
            if (ease) t = smoothstep(t);
            p.color[0] = lerp(p.colorInit[0], fade[0], t);
            p.color[1] = lerp(p.colorInit[1], fade[1], t);
            p.color[2] = lerp(p.colorInit[2], fade[2], t);
        }
    },

    'movement lock to control point': (mod, sys, strength) => {
        // C_OP_PositionLock: частицы следуют за CP, но привязка ОСЛАБЕВАЕТ с
        // возрастом (start_fadeout..end_fadeout по доле жизни, у каждой частицы
        // свой момент из диапазона) и по удалению от CP (distance fade range).
        // Раньше привязка была вечной и полной — шлейфы, которые в игре
        // отстают и растягиваются, в превью жёстко висели на точке.
        const cpNo = attr(mod, 'control_point_number', 0);
        const cp = sys.getControlPoint(cpNo);
        const basis = sys.getControlPointBasis(cpNo);
        const st = sys.getOpState(mod, () => ({
            prev: [cp[0], cp[1], cp[2]], basis: basis,
        }));
        const prevCp = [st.prev[0], st.prev[1], st.prev[2]];
        const d = [(cp[0] - prevCp[0]) * strength,
                   (cp[1] - prevCp[1]) * strength,
                   (cp[2] - prevCp[2]) * strength];
        st.prev[0] = cp[0]; st.prev[1] = cp[1]; st.prev[2] = cp[2];
        // «lock rotation»: частицы едут не только за позицией точки, но и за
        // её поворотом (1645 стоковых модулей — вихри и ауры на вращающемся
        // CP). Поворот берём как переход от прошлого базиса к нынешнему.
        const spin = attr(mod, 'lock rotation', false)
            ? basisDelta(st.basis, basis) : null;
        st.basis = basis;
        if (spin === null && d[0] === 0 && d[1] === 0 && d[2] === 0) return;
        const sMin = attr(mod, 'start_fadeout_min', 1);
        const sMax = attr(mod, 'start_fadeout_max', 1);
        const sExp = attr(mod, 'start_fadeout_exponent', 1);
        const eMin = attr(mod, 'end_fadeout_min', 1);
        const eMax = attr(mod, 'end_fadeout_max', 1);
        const eExp = attr(mod, 'end_fadeout_exponent', 1);
        const range = attr(mod, 'distance fade range', 0);
        for (const p of sys.particles) {
            // Родилась в этом кадре: в Source берётся позиция CP на момент
            // рождения. Истории CP в превью нет — значит дельта нулевая
            if (p.spawnTime >= sys.curTime - sys.deltaTime) continue;
            const life = p.lifetime > 0
                ? saturate((sys.curTime - p.spawnTime) / p.lifetime) : 0;
            const lock = splineRemapClamped(
                life,
                randRangeExpOp(sys, p, 9, sMin, sMax, sExp),
                randRangeExpOp(sys, p, 10, eMin, eMax, eExp), 1, 0);
            if (lock <= 0) continue;
            let k = lock;
            if (range !== 0) {
                const dist = Math.hypot(
                    p.pos[0] + d[0] * lock - cp[0],
                    p.pos[1] + d[1] * lock - cp[1],
                    p.pos[2] + d[2] * lock - cp[2]);
                k *= valveBias(splineRemapClamped(dist, 0, range, 1, 0), 0.2);
            }
            if (spin !== null) {
                // Вокруг ПРОШЛОГО положения точки: сдвиг за её движением
                // добавляется отдельно, ниже
                applyBasisDelta(spin, p.pos, prevCp, k);
                applyBasisDelta(spin, p.prevPos, prevCp, k);
            }
            for (let i = 0; i < 3; i++) {
                p.pos[i] += d[i] * k;
                p.prevPos[i] += d[i] * k;
            }
        }
    },

    'movement rotate particle around axis': (mod, sys) => {
        let axis = attr(mod, 'rotation axis', [0, 0, 1]);
        const rate = attr(mod, 'rotation rate', 180) * DEG_TO_RAD;
        const cpNo = attr(mod, 'control point', 0);
        const cp = sys.getControlPoint(cpNo);
        // «Use Local Space»: ось задана в системе CP (порт TransformAxis)
        if (attr(mod, 'use local space', false))
            axis = cpTransformAxis(sys.getControlPointBasis(cpNo), axis, [0, 0, 0]);
        const angle = rate * sys.deltaTime;
        const al = Math.hypot(axis[0], axis[1], axis[2]) || 1;
        const ax = axis[0] / al, ay = axis[1] / al, az = axis[2] / al;
        const c = Math.cos(angle), s = Math.sin(angle);
        const rot = (v) => {
            const px = v[0] - cp[0], py = v[1] - cp[1], pz = v[2] - cp[2];
            const dot = ax * px + ay * py + az * pz;
            // Формула Родрига
            v[0] = cp[0] + px * c + (ay * pz - az * py) * s + ax * dot * (1 - c);
            v[1] = cp[1] + py * c + (az * px - ax * pz) * s + ay * dot * (1 - c);
            v[2] = cp[2] + pz * c + (ax * py - ay * px) * s + az * dot * (1 - c);
        };
        for (const p of sys.particles) { rot(p.pos); rot(p.prevPos); }
    },

    'oscillate scalar': (mod, sys, strength) => {
        const field = attr(mod, 'oscillation field', 7);
        const rateMin = attr(mod, 'oscillation rate min', 0);
        const rateMax = attr(mod, 'oscillation rate max', 0);
        const freqMin = attr(mod, 'oscillation frequency min', 1);
        const freqMax = attr(mod, 'oscillation frequency max', 1);
        const mult = attr(mod, 'oscillation multiplier', 2);
        const phase = attr(mod, 'oscillation start phase', 0.5);
        for (const p of sys.particles) {
            if (!oscActive(mod, sys, p, 3)) continue;
            const rate = randRangeExpOp(sys, p, 5, rateMin, rateMax, 1);
            const freq = randRangeExpOp(sys, p, 6, freqMin, freqMax, 1);
            const osc = Math.sin(oscPhase(mod, sys, p, freq, mult, phase) * Math.PI);
            setScalarField(p, field,
                getScalarField(p, field) + rate * osc * sys.deltaTime * strength);
        }
    },

    'oscillate vector': (mod, sys, strength) => {
        const field = attr(mod, 'oscillation field', 0);
        const rateMin = attr(mod, 'oscillation rate min', [0, 0, 0]);
        const rateMax = attr(mod, 'oscillation rate max', [0, 0, 0]);
        const freqMin = attr(mod, 'oscillation frequency min', [1, 1, 1]);
        const freqMax = attr(mod, 'oscillation frequency max', [1, 1, 1]);
        const mult = attr(mod, 'oscillation multiplier', 2);
        const phase = attr(mod, 'oscillation start phase', 0.5);
        // Векторные поля Source: XYZ и tint. На скалярное поле (в стоке это
        // 285 модулей с полем 4 — вращение) кладём первую компоненту:
        // раньше такой модуль молча не делал НИЧЕГО.
        const vectorField = field === 0 || field === 6;
        for (const p of sys.particles) {
            if (!oscActive(mod, sys, p, 3)) continue;
            if (!vectorField) {
                const rate = randRangeExpOp(sys, p, 5, rateMin[0], rateMax[0], 1);
                const freq = randRangeExpOp(sys, p, 8, freqMin[0], freqMax[0], 1);
                const osc = Math.sin(oscPhase(mod, sys, p, freq, mult, phase) * Math.PI);
                setScalarField(p, field,
                    getScalarField(p, field) + rate * osc * sys.deltaTime * strength);
                continue;
            }
            const target = field === 0 ? p.pos : p.color;
            for (let i = 0; i < 3; i++) {
                // слоты 5-10: не выходить за шаг 17 между операторами
                const rate = randRangeExpOp(sys, p, 5 + i, rateMin[i], rateMax[i], 1);
                const freq = randRangeExpOp(sys, p, 8 + i, freqMin[i], freqMax[i], 1);
                const osc = Math.sin(oscPhase(mod, sys, p, freq, mult, phase) * Math.PI);
                // prevPos НЕ компенсируем: в интеграторе Верле сдвиг позиции
                // подмешивается в скорость — это и есть дёрганый трепет
                // (бабочки, искры), как в игре. Раньше компенсация делала
                // осцилляцию гладким дрейфом — расходилось с игрой.
                target[i] += rate * osc * sys.deltaTime * strength;
            }
        }
    },

    'movement max velocity': (mod, sys) => {
        const maxVel = attr(mod, 'maximum velocity', 0);
        if (maxVel <= 0) return;
        const maxStep = maxVel * sys.deltaTime;
        for (const p of sys.particles) {
            const vx = p.pos[0] - p.prevPos[0], vy = p.pos[1] - p.prevPos[1],
                  vz = p.pos[2] - p.prevPos[2];
            const len = Math.hypot(vx, vy, vz);
            if (len > maxStep && len > 0) {
                const k = maxStep / len;
                p.prevPos[0] = p.pos[0] - vx * k;
                p.prevPos[1] = p.pos[1] - vy * k;
                p.prevPos[2] = p.pos[2] - vz * k;
            }
        }
    },

    'remap scalar': (mod, sys) => {
        const inField = attr(mod, 'input field', 8);
        const outField = attr(mod, 'output field', 3);
        const inMin = attr(mod, 'input minimum', 0);
        const inMax = attr(mod, 'input maximum', 1);
        const outMin = attr(mod, 'output minimum', 0);
        const outMax = attr(mod, 'output maximum', 1);
        for (const p of sys.particles) {
            // field 8 = creation time (абсолютное время спавна, как в Source)
            const inVal = inField === 8 ? p.spawnTime : getScalarField(p, inField);
            setScalarField(p, outField,
                remapValClamped(inVal, inMin, inMax, outMin, outMax));
        }
    },

    'remap distance to control point to scalar': (mod, sys) => {
        const cp = sys.getControlPoint(attr(mod, 'control point', 0));
        const dMin = attr(mod, 'distance minimum', 0);
        const dMax = attr(mod, 'distance maximum', 128);
        const outMin = attr(mod, 'output minimum', 0);
        const outMax = attr(mod, 'output maximum', 1);
        const outField = attr(mod, 'output field', 3);
        for (const p of sys.particles) {
            const dist = Math.hypot(
                p.pos[0] - cp[0], p.pos[1] - cp[1], p.pos[2] - cp[2]);
            setScalarField(p, outField,
                remapValClamped(dist, dMin, dMax, outMin, outMax));
        }
    },

    'rotation spin yaw': (mod, sys, strength) => generalSpin(
        mod, sys, strength, 'yaw',
        'yaw_rate_degrees', 'yaw_stop_time', 'yaw_rate_min'),

    'set child control points from particle positions': (mod, sys) => {
        const first = attr(mod, 'first control point to set', 0);
        const count = attr(mod, '# of control points to set', 1);
        // Оператор адресует не всех детей, а группу: у Valve так разведены
        // несколько наборов держателей внутри одного эффекта
        const groupId = attr(mod, 'group id to affect', 0);
        const targets = sys.children.filter(
            c => attr(c.def, 'group id', 0) === groupId);
        const n = Math.min(count, sys.particles.length);
        for (let i = 0; i < n; i++) {
            const pos = sys.particles[i].pos;
            for (const child of targets)
                child.cpOverrides[first + i] = [pos[0], pos[1], pos[2]];
        }
    },
};

/**
 * Порт CGeneralSpin::Operate — общий код Rotation Spin Roll / Spin Yaw.
 *
 * Скорость: градусы переводятся в радианы и ЕЩЁ РАЗ умножаются на 2π
 * (`drot = dt * |rate * 2π|`), то есть реальное вращение в 2π раз быстрее,
 * чем «градусы в секунду» из названия параметра. Раньше движок крутил
 * спрайты в 6.28 раза медленнее игры (медиана spin_rate_degrees в стоке — 10,
 * то есть в превью вращения не было видно вовсе).
 */
function generalSpin(mod, sys, strength, field, rateKey, stopKey, minKey) {
    const rate = attr(mod, rateKey, 0) * DEG_TO_RAD * strength;
    if (rate === 0) return;
    const stopTime = attr(mod, stopKey, 0);
    const dt = sys.deltaTime;
    let drot = dt * Math.abs(rate * TWO_PI);
    if (stopTime === 0) drot = drot % TWO_PI;
    if (rate < 0) drot = -drot;
    const minStep = dt * Math.abs(attr(mod, minKey, 0) * DEG_TO_RAD * TWO_PI);
    for (const p of sys.particles) {
        // stop time — ДОЛЯ жизни, а не секунды (в Source это помечено «HACK»),
        // и скорость падает до нуля линейно, а не обрывается
        let step = drot;
        if (stopTime !== 0)
            step *= Math.max(0, 1 - (sys.curTime - p.spawnTime) /
                                    (p.lifetime * stopTime));
        // Порт как есть, вместе с багом Valve (рядом стоит «FIXME: This is
        // wrong»): сравнение знаковое, поэтому отрицательная скорость всегда
        // подменяется на spin_rate_min — в игре такие модули не вращаются
        if (step <= minStep) step = minStep;
        let v = p[field] + step;
        if (v >= TWO_PI) v -= TWO_PI;
        else if (v <= -TWO_PI) v += TWO_PI;
        p[field] = v;
    }
}

/** Пер-частичный «случайный» из пула — порт randF32Op (стабилен между кадрами). */
function randRangeExpOp(sys, p, o, min, max, exp) {
    if (min === max) return min;
    let v = sys.randOpPool[(sys.randOpCounter + p.id + o) & 0x7FF];
    v = Math.pow(v, exp);
    return lerp(min, max, v);
}

// ── Форсы (ускорения, применяются в Movement Basic) ──────────────────────── //

const FORCES = {
    'random force': (mod) => {
        const min = attr(mod, 'min force', [0, 0, 0]);
        const max = attr(mod, 'max force', [0, 0, 0]);
        return (sys, p, accel) => {
            for (let i = 0; i < 3; i++)
                accel[i] += lerp(min[i], max[i], sys.rand.nextF32());
        };
    },
    'pull towards control point': (mod) => {
        const amount = attr(mod, 'amount of force', 0);
        const falloff = attr(mod, 'falloff power', 2);
        const cpNo = attr(mod, 'control point number', 0);
        return (sys, p, accel) => {
            const cp = sys.getControlPoint(cpNo);
            const dx = cp[0] - p.pos[0], dy = cp[1] - p.pos[1], dz = cp[2] - p.pos[2];
            const dist = Math.hypot(dx, dy, dz);
            if (dist < 1e-3) return;
            const k = amount / Math.pow(dist, falloff) / dist;
            accel[0] += dx * k; accel[1] += dy * k; accel[2] += dz * k;
        };
    },
    'twist around axis': (mod) => {
        const amount = attr(mod, 'amount of force', 0);
        const axis = attr(mod, 'twist axis', [0, 0, 1]);
        const cpNo = attr(mod, 'control point number', 0);
        const al = Math.hypot(axis[0], axis[1], axis[2]) || 1;
        const ax = axis[0] / al, ay = axis[1] / al, az = axis[2] / al;
        return (sys, p, accel) => {
            const cp = sys.getControlPoint(cpNo);
            const px = p.pos[0] - cp[0], py = p.pos[1] - cp[1], pz = p.pos[2] - cp[2];
            // Тангенциальное ускорение: axis × r
            let tx = ay * pz - az * py, ty = az * px - ax * pz, tz = ax * py - ay * px;
            const tl = Math.hypot(tx, ty, tz);
            if (tl < 1e-3) return;
            accel[0] += tx / tl * amount;
            accel[1] += ty / tl * amount;
            accel[2] += tz / tl * amount;
        };
    },
};

// ── Констрейнты (применяются после операторов) ───────────────────────────── //

const CONSTRAINTS = {
    'constrain distance to control point': (mod, sys) => {
        const minD = attr(mod, 'minimum distance', 0);
        const maxD = attr(mod, 'maximum distance', 100);
        const cp = sys.getControlPoint(attr(mod, 'control point number', 0));
        for (const p of sys.particles) {
            const dx = p.pos[0] - cp[0], dy = p.pos[1] - cp[1], dz = p.pos[2] - cp[2];
            const dist = Math.hypot(dx, dy, dz);
            if (dist < 1e-6) continue;
            const clamped = Math.min(Math.max(dist, minD), maxD);
            if (clamped !== dist) {
                const k = clamped / dist;
                p.pos[0] = cp[0] + dx * k;
                p.pos[1] = cp[1] + dy * k;
                p.pos[2] = cp[2] + dz * k;
            }
        }
    },

    'collision via traces': (mod, sys) => {
        // ponytail: в превью нет геометрии карты — коллизия только с полом z=0,
        // отскок по bounce, гашение горизонтали по slide
        const bounce = attr(mod, 'amount of bounce', 0);
        const slide = attr(mod, 'amount of slide', 0);
        for (const p of sys.particles) {
            if (p.pos[2] >= 0) continue;
            p.pos[2] = 0;
            const vz = p.pos[2] - p.prevPos[2];
            p.prevPos[2] = p.pos[2] + vz * bounce;
            if (slide > 0) {
                p.prevPos[0] = p.pos[0] - (p.pos[0] - p.prevPos[0]) * slide;
                p.prevPos[1] = p.pos[1] - (p.pos[1] - p.prevPos[1]) * slide;
            }
        }
    },
};

// ── Эмиттеры ─────────────────────────────────────────────────────────────── //

function makeEmitter(mod) {
    const fn = resolveFnName(mod.functionName);
    if (fn === 'emit noise') {
        // ponytail: шумовая эмиссия ≈ continuous с шумовым rate между min/max
        return {
            min: attr(mod, 'emission minimum', 0),
            max: attr(mod, 'emission maximum', 100),
            duration: attr(mod, 'emission_duration', 0),
            startTime: attr(mod, 'emission_start_time', 0),
            ts: attr(mod, 'time noise coordinate scale', 0.1),
            env: opEnvelope(mod),
            emitCounter: 0,
            emitNum: 0,
            isActive(sys) {
                return !(this.duration > 0 && sys.curTime >= this.startTime + this.duration);
            },
            emit(sys) {
                if (sys.curTime <= this.startTime || !this.isActive(sys)) return;
                const strength = opStrength(this.env, sys.curTime);
                if (strength <= 0) return;
                const n = valueNoise3(sys.curTime * this.ts, 7.3, 11.9) * 0.5 + 0.5;
                const rate = lerp(this.min, this.max, saturate(n)) * strength;
                if (rate <= 0) return;
                this.emitCounter += rate * sys.deltaTime;
                const newEmitNum = this.emitCounter | 0;
                const count = newEmitNum - this.emitNum;
                let created = 0;
                for (let i = 0; i < count; i++)
                    if (sys.spawnParticle(sys.curTime)) created++;
                if (created > 0 || count === 0) this.emitNum = newEmitNum;
            },
            reset() { this.emitCounter = 0; this.emitNum = 0; },
        };
    }
    if (fn === 'emit_continuously') {
        return {
            rate: attr(mod, 'emission_rate', 100),
            duration: attr(mod, 'emission_duration', 0),
            startTime: attr(mod, 'emission_start_time', 0),
            env: opEnvelope(mod),
            emitCounter: 0,
            emitNum: 0,
            isActive(sys) {
                return !(this.duration > 0 && sys.curTime >= this.startTime + this.duration);
            },
            emit(sys) {
                if (this.rate <= 0 || sys.curTime <= this.startTime || !this.isActive(sys))
                    return;
                // Огибающая масштабирует темп эмиссии (flEmissionRate *= strength)
                const rate = this.rate * opStrength(this.env, sys.curTime);
                if (rate <= 0) return;
                let prevTime = sys.curTime - sys.deltaTime;
                if (prevTime < this.startTime) prevTime = this.startTime;
                this.emitCounter += rate * (sys.curTime - prevTime);
                const newEmitNum = this.emitCounter | 0;
                const count = newEmitNum - this.emitNum;
                let spawnTime = prevTime;
                const step = 1.0 / rate;
                let created = 0;
                for (let i = 0; i < count; i++) {
                    if (sys.spawnParticle(spawnTime)) created++;
                    spawnTime += step;
                }
                // Как в эталоне: если max_particles забит и не создали ничего —
                // счётчик не двигаем, burst догонит после смертей частиц
                if (created > 0 || count === 0)
                    this.emitNum = newEmitNum;
            },
            reset() { this.emitCounter = 0; this.emitNum = 0; },
        };
    }
    if (fn === 'emit_instantaneously') {
        return {
            num: attr(mod, 'num_to_emit', 100),
            startTime: attr(mod, 'emission_start_time', 0),
            // Потолок на кадр: залп размазывается на несколько кадров
            // (у Valve так сделаны 452 эмиттера). -1 — без ограничения
            perFrame: attr(mod, 'maximum emission per frame', -1),
            env: opEnvelope(mod),
            left: 0,
            started: false,
            isActive(sys) { return !this.started || this.left > 0; },
            emit(sys) {
                if (sys.curTime < this.startTime) return;
                // Мгновенный эмиттер силу не масштабирует — только гасится ею
                if (opStrength(this.env, sys.curTime) <= 0) return;
                if (!this.started) {
                    this.started = true;
                    this.left = this.num;
                }
                const batch = this.perFrame > 0
                    ? Math.min(this.left, this.perFrame) : this.left;
                // Первая порция рождается в свой заявленный момент, хвост —
                // тогда, когда до него дошла очередь
                const spawnTime = this.left === this.num
                    ? Math.max(this.startTime, 0) : Math.max(sys.curTime, 0);
                for (let i = 0; i < batch; i++)
                    sys.spawnParticle(spawnTime);
                this.left -= batch;
            },
            reset() { this.started = false; this.left = 0; },
        };
    }
    console.log('Unknown Emitter:', mod.functionName);
    return null;
}

// ── Система частиц (инстанс) ─────────────────────────────────────────────── //

export class ParticleSystemInstance {
    /**
     * @param {object} def        JSON-определение системы
     * @param {object} systems    все определения {имя: def}
     * @param {object} materials  {путь: {dataUrl, sheet, additive, ...}}
     * @param {object} controller {controlPoints: [[x,y,z], ...]}
     */
    constructor(def, systems, materials, controller, depth = 0, parent = null) {
        this.def = def;
        this.name = def.name;
        this.controller = controller;
        this.parent = parent;
        this.cpOverrides = {};   // CP, выставленные операторами (per-instance)
        this.materialName = attr(def, 'material', '');
        this.material = materials[this.materialName] || null;
        this.sheet = (this.material && this.material.sheet)
            ? new Sheet(this.material.sheet) : null;

        this.maxParticles = attr(def, 'max_particles', 1000);
        // Кламп шага симуляции — как в игре (m_flMaximumTimeStep, дефолт 0.1):
        // при просадке FPS превью не должно интегрировать шагами, которых в
        // игре не бывает. 0 в файле означает «без ограничения» — тогда 0.3.
        this.maxTimeStep = attr(def, 'maximum time step', 0.1) || 0.3;
        // Частицы, которые система создаёт в момент старта, помимо эмиттеров
        this.initialParticles = attr(def, 'initial_particles', 0);
        this.constRadius = attr(def, 'radius', 5);
        this.constColor = colorF(attr(def, 'color', null), [1, 1, 1, 1]);
        this.constRotation = attr(def, 'rotation', 0) * DEG_TO_RAD;
        this.constSeq = attr(def, 'sequence_number', 0);
        this.constSeq2 = attr(def, 'sequence_number 1', 0);

        this.initializers = def.initializers
            .map(m => ({ mod: m, fn: INITIALIZERS[resolveFnName(m.functionName)] }))
            .filter(x => x.fn || (console.log('Unknown Initializer:', x.mod.functionName), false));
        this.operators = def.operators
            .map(m => ({ mod: m, fn: OPERATORS[resolveFnName(m.functionName)],
                         env: opEnvelope(m) }))
            .filter(x => x.fn || (console.log('Unknown Operator:', x.mod.functionName), false));
        this.emitters = def.emitters.map(makeEmitter).filter(e => e !== null);
        this.forcesList = (def.forces || [])
            .map(m => {
                const make = FORCES[resolveFnName(m.functionName)];
                if (!make) { console.log('Unknown Force:', m.functionName); return null; }
                return withForceStrength(make(m), opEnvelope(m));
            })
            .filter(f => f !== null);
        this.constraints = (def.constraints || [])
            .map(m => ({ mod: m, fn: CONSTRAINTS[resolveFnName(m.functionName)],
                         env: opEnvelope(m) }))
            .filter(x => x.fn || (console.log('Unknown Constraint:', x.mod.functionName), false));

        this.rendererMods = def.renderers || [];
        // Огибающая ПЕРВОГО рендерера: гейт на отрисовку системы целиком
        this.rendererEnv = this.rendererMods.length
            ? opEnvelope(this.rendererMods[0]) : null;
        this.animationRate = 1.0;
        this.animationRateAsFps = false;
        this.animationFitLifetime = false;
        this.orientationType = 0;
        this.orientationCP = -1;
        this.rendererType = 'sprites';
        this.screenVelRotate = null;
        for (const r of this.rendererMods) {
            const fn = (r.functionName || '').toLowerCase();
            if (fn === 'render_animated_sprites' || fn === 'render_sprite_trail') {
                this.animationRate = attr(r, 'animation rate', 1.0);
                // Смысл 'animation rate' зависит от флага (проверено по
                // стоковым PCF: при FPS=true медиана 30 — это кадры/сек;
                // при FPS=false самое частое 0.1 — это ЦИКЛЫ/сек)
                this.animationRateAsFps = !!attr(r, 'use animation rate as fps', false);
                // Растянуть весь sheet-цикл ровно на время жизни частицы:
                // многие мастерские-анимации (30 кадров) без этого флага
                // за короткую жизнь показывают лишь первый кадр
                this.animationFitLifetime = !!attr(r, 'animation_fit_lifetime', false);
                this.orientationType = attr(r, 'orientation_type', 0);
                // orientation_type 2/3 берут плоскость спрайта из базиса этого CP
                this.orientationCP = attr(r, 'orientation control point', -1);
            } else if (fn === 'render_screen_velocity_rotate') {
                // Разворот спрайта по его скорости НА ЭКРАНЕ (бабочки,
                // пауки, призраки анюжуалов). Ставится ВТОРЫМ рендерером
                // рядом с render_animated_sprites. Угол зависит от камеры —
                // досчитывается в рендере (particles3d.html)
                this.screenVelRotate = {
                    forward: attr(r, 'forward_angle', 0) * DEG_TO_RAD,
                    rate: attr(r, 'rotate_rate(dps)', 0) * DEG_TO_RAD,
                };
            } else if (fn === 'render_rope') {
                // Лента по цепочке частиц (кровь/лучи). ponytail: без
                // subdivision-сглаживания и скролла текстуры
                this.rendererType = 'rope';
            } else {
                console.log('Unknown Renderer (rendered as sprites):', r.functionName);
            }
        }

        this.children = [];
        const maxDepth = 8; // защита от циклических ссылок в PCF
        if (depth < maxDepth) {
            for (const ch of (def.children || [])) {
                const childDef = systems[ch.childName];
                if (!childDef) continue;
                const child = new ParticleSystemInstance(
                    childDef, systems, materials, controller, depth + 1, this);
                child.delay = ch.delay || 0;
                this.children.push(child);
            }
        }

        this.delay = 0;
        this.rand = new SeededRNG();
        this.randOpPool = new Float32Array(0x800);
        this.randOpCounter = 0;
        this.reset();
    }

    reset() {
        this.curTime = -this.delay;
        this.deltaTime = 0;
        this.prevDeltaTime = 0;
        this.particles = [];
        this.nextID = 0;
        this.spawnSeq = 0;
        this.cpOverrides = {};
        this._opState = new Map();
        for (let i = 0; i < 0x800; i++) this.randOpPool[i] = this.rand.nextF32();
        for (const e of this.emitters) e.reset();
        for (const c of this.children) c.reset();
    }

    getControlPoint(i) {
        if (this.cpOverrides[i] !== undefined) return this.cpOverrides[i];
        if (this.parent !== null) return this.parent.getControlPoint(i);
        const cps = this.controller.controlPoints;
        return cps[i] || cps[0] || [0, 0, 0];
    }

    /** Базис CP: свой, если задан ориентацией снаружи, иначе дефолт движка. */
    getControlPointBasis(i) {
        if (this.parent !== null) return this.parent.getControlPointBasis(i);
        const bases = this.controller.controlPointBases;
        return (bases && bases[i]) || CP_DEFAULT_BASIS;
    }

    /** Задан ли CP явно (оператором, родителем или извне через setControlPoint).
        Незаданные CP в игре выставляет код (цвет килстрика и т.п.) —
        remap-модули по ним в превью пропускаются. */
    isControlPointDefined(i) {
        if (this.cpOverrides[i] !== undefined) return true;
        if (this.parent !== null) return this.parent.isControlPointDefined(i);
        return this.controller.controlPoints[i] !== undefined;
    }

    /** Состояние оператора между кадрами (например prev-позиция CP). */
    getOpState(mod, init) {
        let st = this._opState.get(mod);
        if (st === undefined) {
            st = init();
            this._opState.set(mod, st);
        }
        return st;
    }

    getSheet() { return this.sheet; }

    spawnParticle(spawnTime) {
        if (this.particles.length >= this.maxParticles) return false;
        const p = {
            pos: [0, 0, 0],
            prevPos: [0, 0, 0],
            lifetime: 1,
            radius: this.constRadius,
            rotation: this.constRotation,
            rotSpeed: 0,
            yaw: 0,
            yawFlip: false,
            color: [this.constColor[0], this.constColor[1], this.constColor[2]],
            alpha: this.constColor[3],
            spawnTime: spawnTime,
            seq: this.constSeq,
            seq2: this.constSeq2,
            trailLength: 0.1,
            id: this.nextID++,
            dead: false,
        };
        for (const { mod, fn } of this.initializers) fn(mod, this, p);
        this.spawnSeq++;
        // Инициализатор отбраковал частицу (нет родителя и т.п.) — не добавляем,
        // но для счётчиков эмиттера она «создана»
        if (p.dead) return true;
        // Снимок стартовых значений для fade/scale-операторов
        p.alphaInit = p.alpha;
        p.radiusInit = p.radius;
        p.colorInit = [p.color[0], p.color[1], p.color[2]];
        this.particles.push(p);
        return true;
    }

    killDead() {
        if (this.particles.some(p => p.dead))
            this.particles = this.particles.filter(p => !p.dead);
    }

    isEmitActive() {
        return this.emitters.some(e => e.isActive(this));
    }

    isFinished() {
        if (this.isEmitActive() && this.emitters.length > 0) return false;
        if (this.particles.length > 0) return false;
        return this.children.every(c => c.isFinished());
    }

    movement(dt) {
        this.prevDeltaTime = this.deltaTime;
        this.deltaTime = Math.min(dt, this.maxTimeStep);
        if (this.deltaTime <= 0.001) return;
        const wasBeforeStart = this.curTime <= 0;
        this.curTime += this.deltaTime;
        if (this.curTime > 0) {
            // initial_particles: разовый залп на первом же шаге после старта
            if (wasBeforeStart && this.initialParticles > 0)
                for (let i = 0; i < this.initialParticles; i++)
                    this.spawnParticle(this.curTime);
            for (const e of this.emitters) e.emit(this);
            this.randOpCounter = 0;
            for (const { mod, fn, env } of this.operators) {
                const strength = opStrength(env, this.curTime);
                if (strength <= 0) continue;   // как в Source: оператор не запускается
                fn(mod, this, strength);
                // Смещение пула случайных двигается только у запущенных операторов
                this.randOpCounter += 17;
            }
            for (const { mod, fn, env } of this.constraints)
                if (opStrength(env, this.curTime) > 0) fn(mod, this);
        }
        for (const c of this.children) c.movement(dt);
    }

    /**
     * Снимает состояние для рендера (см. particles3d.html).
     * out — массив спрайтов; ropesOut (опционально) — массив лент:
     * {material, additive, points: [{pos, radius, color, alpha}]} —
     * частицы rope-систем соединяются в порядке создания.
     */
    collectSprites(out, ropesOut) {
        // Рендерер — такой же модуль с огибающей: при нулевой силе Source его
        // не запускает, и частицы просто не рисуются (в стоке так сделана
        // одна система, но выглядит это как «эффект пропал без причины»)
        if (opStrength(this.rendererEnv, this.curTime) <= 0) {
            for (const c of this.children) c.collectSprites(out, ropesOut);
            return;
        }
        if (this.rendererType === 'rope' && ropesOut !== undefined) {
            if (this.particles.length >= 2) {
                ropesOut.push({
                    material: this.materialName,
                    additive: this.material ? this.material.additive : false,
                    points: this.particles.map(p => ({
                        pos: [p.pos[0], p.pos[1], p.pos[2]],
                        radius: p.radius,
                        color: [p.color[0], p.color[1], p.color[2]],
                        alpha: p.alpha,
                    })),
                });
            }
            for (const c of this.children) c.collectSprites(out, ropesOut);
            return;
        }
        const uv0 = [1, 1, 0, 0], uv1 = [1, 1, 0, 0];
        for (const p of this.particles) {
            let blend = 0;
            if (this.sheet !== null) {
                let time;
                const age = this.curTime - p.spawnTime;
                if (this.animationFitLifetime) {
                    // Весь цикл кадров ровно за одну жизнь частицы
                    const seq = this.sheet.getSequence(p.seq);
                    const dur = seq ? seq.duration : 1;
                    time = (age / (p.lifetime || 1)) * dur;
                } else if (this.animationRateAsFps) {
                    // rate = КАДРОВ в секунду (длительности кадров = 1.0)
                    time = this.animationRate * age;
                } else {
                    // rate = ЦИКЛОВ в секунду: 1.0 = один полный проход
                    // листа за секунду (в игре это «нормальная» скорость)
                    const seq = this.sheet.getSequence(p.seq);
                    const dur = seq ? seq.duration : 1;
                    time = this.animationRate * age * dur;
                }
                blend = this.sheet.calcScaleBias(uv0, uv1, p.seq, 0, time);
            } else {
                uv0[0] = 1; uv0[1] = 1; uv0[2] = 0; uv0[3] = 0;
                uv1[0] = 1; uv1[1] = 1; uv1[2] = 0; uv1[3] = 0;
            }
            if (p.yawFlip) {
                // Зеркалирование по горизонтали через scale/bias UV
                uv0[2] += uv0[0]; uv0[0] = -uv0[0];
                uv1[2] += uv1[0]; uv1[0] = -uv1[0];
            }
            const s = {
                system: this.name,
                material: this.materialName,
                additive: this.material ? this.material.additive : true,
                orientation: this.orientationType,
                pos: [p.pos[0], p.pos[1], p.pos[2]],
                radius: p.radius,
                rotation: p.rotation,
                color: [p.color[0], p.color[1], p.color[2]],
                alpha: p.alpha,
                uv0: [uv0[0], uv0[1], uv0[2], uv0[3]],
                uv1: [uv1[0], uv1[1], uv1[2], uv1[3]],
                blend: blend,
            };
            if (this.orientationType >= 2 && this.orientationCP >= 0) {
                // Source путает имена: в RenderNonSpriteCardOriented «right»
                // спрайта — это Forward контрол-пойнта, а «up» — его Right
                const b = this.getControlPointBasis(this.orientationCP);
                s.right = [b.fwd[0], b.fwd[1], b.fwd[2]];
                s.up = [b.right[0], b.right[1], b.right[2]];
                // orientation_type 3 = тот же режим, но ось right доворачивается
                // на yaw частицы вокруг оси up
                if (this.orientationType === 3 && p.yaw !== 0)
                    rotateAboutAxis(s.right, s.up, p.yaw, s.right);
            }
            if (this.screenVelRotate) {
                // Мировая скорость + параметры — экранный угол досчитает рендер
                s.vel = [p.pos[0] - p.prevPos[0], p.pos[1] - p.prevPos[1],
                         p.pos[2] - p.prevPos[2]];
                s.screenVel = this.screenVelRotate;
                s.age = this.curTime - p.spawnTime;
            }
            out.push(s);
        }
        for (const c of this.children) c.collectSprites(out, ropesOut);
    }
}

/** Списки реализованных модулей — для диагностики покрытия. */
export function implementedModules() {
    return {
        initializers: Object.keys(INITIALIZERS),
        operators: Object.keys(OPERATORS),
        forces: Object.keys(FORCES),
        constraints: Object.keys(CONSTRAINTS),
        emitters: ['emit_continuously', 'emit_instantaneously', 'emit noise'],
        renderers: ['render_animated_sprites', 'render_sprite_trail',
                    'render_rope', 'render_screen_velocity_rotate'],
        aliases: FN_ALIASES,
    };
}
