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
};

function resolveFnName(name) {
    const lower = (name || '').toLowerCase();
    return FN_ALIASES[lower] || lower;
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
        const biasLocal = attr(mod, 'bias in local system', false);
        const cpNo = attr(mod, 'control_point_number', 0);
        const speedMin = attr(mod, 'speed_min', 0);
        const speedMax = attr(mod, 'speed_max', 0);
        const speedExp = attr(mod, 'speed_random_exponent', 1);
        const speedLocalMin = attr(mod, 'speed_in_local_coordinate_system_min', [0, 0, 0]);
        const speedLocalMax = attr(mod, 'speed_in_local_coordinate_system_max', [0, 0, 0]);

        let dir = vec3RandomUnit(sys.rand);
        if (distBias[0] !== 1 || distBias[1] !== 1 || distBias[2] !== 1) {
            dir = [dir[0] * distBias[0], dir[1] * distBias[1], dir[2] * distBias[2]];
            const len = Math.hypot(dir[0], dir[1], dir[2]) || 1;
            dir = [dir[0] / len, dir[1] / len, dir[2] / len];
        }
        let distance;
        if (distMin === distMax) {
            distance = distMin;
        } else {
            let d = sys.rand.nextF32();
            d = 1.0 - Math.pow(d, 3.0);
            distance = lerp(distMin, distMax, d);
        }
        const cp = sys.getControlPoint(cpNo);
        let px = dir[0] * distance, py = dir[1] * distance, pz = dir[2] * distance;
        // ponytail: контрол-пойнты — только позиция (без вращения), локальные оси = мировые
        px += cp[0]; py += cp[1]; pz += cp[2];
        p.pos[0] = px; p.pos[1] = py; p.pos[2] = pz;

        const speed = randRangeExp(sys.rand, speedMin, speedMax, speedExp);
        let vx = dir[0] * speed, vy = dir[1] * speed, vz = dir[2] * speed;
        vx += lerp(speedLocalMin[0], speedLocalMax[0], sys.rand.nextF32());
        vy += lerp(speedLocalMin[1], speedLocalMax[1], sys.rand.nextF32());
        vz += lerp(speedLocalMin[2], speedLocalMax[2], sys.rand.nextF32());
        p.prevPos[0] = px - vx * sys.deltaTime;
        p.prevPos[1] = py - vy * sys.deltaTime;
        p.prevPos[2] = pz - vz * sys.deltaTime;
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
        let ox = lerp(min[0], max[0], sys.rand.nextF32());
        let oy = lerp(min[1], max[1], sys.rand.nextF32());
        let oz = lerp(min[2], max[2], sys.rand.nextF32());
        if (propRadius) { ox *= p.radius; oy *= p.radius; oz *= p.radius; }
        p.pos[0] += ox; p.pos[1] += oy; p.pos[2] += oz;
        p.prevPos[0] += ox; p.prevPos[1] += oy; p.prevPos[2] += oz;
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
        const speedMin = attr(mod, 'speed_min', 0);
        const speedMax = attr(mod, 'speed_max', 0);
        const speedExp = attr(mod, 'speed_random_exponent', 1);
        const localMin = attr(mod, 'speed_in_local_coordinate_system_min', [0, 0, 0]);
        const localMax = attr(mod, 'speed_in_local_coordinate_system_max', [0, 0, 0]);
        const dir = vec3RandomUnit(sys.rand);
        const speed = randRangeExp(sys.rand, speedMin, speedMax, speedExp);
        for (let i = 0; i < 3; i++) {
            const v = dir[i] * speed + lerp(localMin[i], localMax[i], sys.rand.nextF32());
            p.prevPos[i] = p.pos[i] - v * sys.deltaTime;
        }
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
        for (let i = 0; i < 3; i++) {
            // смещение 49.7*i разносит компоненты по шумовому полю
            let n = valueNoise3(
                p.pos[0] * ss + i * 49.7 + (Array.isArray(so) ? so[0] : 0),
                p.pos[1] * ss + (Array.isArray(so) ? so[1] : 0),
                p.pos[2] * ss + t + (Array.isArray(so) ? so[2] : 0));
            if (absVal[i]) n = Math.abs(n);
            if (absInv[i]) n = 1.0 - Math.abs(n);
            const v = lerp(outMin[i], outMax[i], saturate(n * 0.5 + 0.5));
            p.prevPos[i] -= v * sys.deltaTime;
        }
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
        if (attr(mod, 'absolute value', false)) n = Math.abs(n);
        if (attr(mod, 'invert abs value', false)) n = 1.0 - Math.abs(n);
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
        const axis = attr(mod, 'input field', 0);
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
        const drag = 1.0 - attr(mod, 'drag', 0);
        const dt = sys.deltaTime;
        const dt2 = dt * dt;
        const accel = [0, 0, 0];
        for (const p of sys.particles) {
            accel[0] = gravity[0]; accel[1] = gravity[1]; accel[2] = gravity[2];
            for (const f of sys.forcesList) f(sys, p, accel);
            for (let i = 0; i < 3; i++) {
                const speed = p.pos[i] - p.prevPos[i];
                p.prevPos[i] = p.pos[i];
                p.pos[i] += (speed + accel[i] * dt2) * drag;
            }
        }
    },

    'rotation basic': (mod, sys) => {
        for (const p of sys.particles)
            p.rotation += p.rotSpeed * sys.deltaTime;
    },

    'rotation spin roll': (mod, sys) => {
        // ponytail: без замедления к spin_stop_time — постоянная скорость до стопа
        const rate = attr(mod, 'spin_rate_degrees', 0) * DEG_TO_RAD;
        const stopTime = attr(mod, 'spin_stop_time', 0);
        for (const p of sys.particles) {
            const age = sys.curTime - p.spawnTime;
            if (stopTime > 0 && age >= stopTime) continue;
            p.rotation += rate * sys.deltaTime;
        }
    },

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
        const min = attr(mod, 'fade out time min', 0.25);
        const max = attr(mod, 'fade out time max', 0.25);
        const exp = attr(mod, 'fade out time exponent', 1);
        const proportional = attr(mod, 'proportional 0/1', true);
        for (const p of sys.particles) {
            const fadeStart = randRangeExpOp(sys, p, 0, min, max, exp);
            let fadeEnd;
            let t = sys.curTime - p.spawnTime;
            if (proportional) { t /= p.lifetime; fadeEnd = 1; }
            else fadeEnd = p.lifetime;
            if (t <= fadeStart) continue;
            t = saturate(invlerp(fadeEnd, fadeStart, t));
            p.alpha = p.alphaInit * smoothstep(t);
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

    'movement lock to control point': (mod, sys) => {
        // Частицы следуют за CP: добавляем дельту его движения.
        // ponytail: без start/end fadeout по возрасту частицы
        const cpNo = attr(mod, 'control_point_number', 0);
        const cp = sys.getControlPoint(cpNo);
        const st = sys.getOpState(mod, () => ({ prev: [cp[0], cp[1], cp[2]] }));
        const dx = cp[0] - st.prev[0], dy = cp[1] - st.prev[1], dz = cp[2] - st.prev[2];
        st.prev[0] = cp[0]; st.prev[1] = cp[1]; st.prev[2] = cp[2];
        if (dx === 0 && dy === 0 && dz === 0) return;
        for (const p of sys.particles) {
            p.pos[0] += dx; p.pos[1] += dy; p.pos[2] += dz;
            p.prevPos[0] += dx; p.prevPos[1] += dy; p.prevPos[2] += dz;
        }
    },

    'movement rotate particle around axis': (mod, sys) => {
        const axis = attr(mod, 'rotation axis', [0, 0, 1]);
        const rate = attr(mod, 'rotation rate', 180) * DEG_TO_RAD;
        const cp = sys.getControlPoint(attr(mod, 'control point', 0));
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

    'oscillate scalar': (mod, sys) => {
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
            const osc = Math.sin((sys.curTime * freq * mult + phase) * Math.PI);
            setScalarField(p, field,
                getScalarField(p, field) + rate * osc * sys.deltaTime);
        }
    },

    'oscillate vector': (mod, sys) => {
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
                const osc = Math.sin((sys.curTime * freq * mult + phase) * Math.PI);
                setScalarField(p, field,
                    getScalarField(p, field) + rate * osc * sys.deltaTime);
                continue;
            }
            const target = field === 0 ? p.pos : p.color;
            for (let i = 0; i < 3; i++) {
                // слоты 5-10: не выходить за шаг 17 между операторами
                const rate = randRangeExpOp(sys, p, 5 + i, rateMin[i], rateMax[i], 1);
                const freq = randRangeExpOp(sys, p, 8 + i, freqMin[i], freqMax[i], 1);
                const osc = Math.sin((sys.curTime * freq * mult + phase) * Math.PI);
                target[i] += rate * osc * sys.deltaTime;
                if (field === 0) p.prevPos[i] += rate * osc * sys.deltaTime;
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

    'rotation spin yaw': (mod, sys) => {
        const rate = attr(mod, 'yaw_rate_degrees', 0) * DEG_TO_RAD;
        for (const p of sys.particles) p.yaw += rate * sys.deltaTime;
    },

    'set child control points from particle positions': (mod, sys) => {
        const first = attr(mod, 'first control point to set', 0);
        const count = attr(mod, '# of control points to set', 1);
        const n = Math.min(count, sys.particles.length);
        for (let i = 0; i < n; i++) {
            const pos = sys.particles[i].pos;
            for (const child of sys.children)
                child.cpOverrides[first + i] = [pos[0], pos[1], pos[2]];
        }
    },
};

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
            emitCounter: 0,
            emitNum: 0,
            isActive(sys) {
                return !(this.duration > 0 && sys.curTime >= this.startTime + this.duration);
            },
            emit(sys) {
                if (sys.curTime <= this.startTime || !this.isActive(sys)) return;
                const n = valueNoise3(sys.curTime * this.ts, 7.3, 11.9) * 0.5 + 0.5;
                const rate = lerp(this.min, this.max, saturate(n));
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
            emitCounter: 0,
            emitNum: 0,
            isActive(sys) {
                return !(this.duration > 0 && sys.curTime >= this.startTime + this.duration);
            },
            emit(sys) {
                if (this.rate <= 0 || sys.curTime <= this.startTime || !this.isActive(sys))
                    return;
                let prevTime = sys.curTime - sys.deltaTime;
                if (prevTime < this.startTime) prevTime = this.startTime;
                this.emitCounter += this.rate * (sys.curTime - prevTime);
                const newEmitNum = this.emitCounter | 0;
                const count = newEmitNum - this.emitNum;
                let spawnTime = prevTime;
                const step = 1.0 / this.rate;
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
            done: false,
            isActive(sys) { return !this.done; },
            emit(sys) {
                if (this.done || sys.curTime < this.startTime) return;
                this.done = true;
                for (let i = 0; i < this.num; i++)
                    sys.spawnParticle(Math.max(this.startTime, 0));
            },
            reset() { this.done = false; },
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
        this.constRadius = attr(def, 'radius', 5);
        this.constColor = colorF(attr(def, 'color', null), [1, 1, 1, 1]);
        this.constRotation = attr(def, 'rotation', 0) * DEG_TO_RAD;
        this.constSeq = attr(def, 'sequence_number', 0);
        this.constSeq2 = attr(def, 'sequence_number 1', 0);

        this.initializers = def.initializers
            .map(m => ({ mod: m, fn: INITIALIZERS[resolveFnName(m.functionName)] }))
            .filter(x => x.fn || (console.log('Unknown Initializer:', x.mod.functionName), false));
        this.operators = def.operators
            .map(m => ({ mod: m, fn: OPERATORS[resolveFnName(m.functionName)] }))
            .filter(x => x.fn || (console.log('Unknown Operator:', x.mod.functionName), false));
        this.emitters = def.emitters.map(makeEmitter).filter(e => e !== null);
        this.forcesList = (def.forces || [])
            .map(m => {
                const make = FORCES[resolveFnName(m.functionName)];
                if (!make) { console.log('Unknown Force:', m.functionName); return null; }
                return make(m);
            })
            .filter(f => f !== null);
        this.constraints = (def.constraints || [])
            .map(m => ({ mod: m, fn: CONSTRAINTS[resolveFnName(m.functionName)] }))
            .filter(x => x.fn || (console.log('Unknown Constraint:', x.mod.functionName), false));

        this.rendererMods = def.renderers || [];
        this.animationRate = 1.0;
        this.orientationType = 0;
        this.rendererType = 'sprites';
        for (const r of this.rendererMods) {
            const fn = (r.functionName || '').toLowerCase();
            if (fn === 'render_animated_sprites' || fn === 'render_sprite_trail') {
                this.animationRate = attr(r, 'animation rate', 1.0);
                this.orientationType = attr(r, 'orientation_type', 0);
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
        this.deltaTime = Math.min(dt, 0.3);
        if (this.deltaTime <= 0.001) return;
        this.curTime += this.deltaTime;
        if (this.curTime > 0) {
            for (const e of this.emitters) e.emit(this);
            this.randOpCounter = 0;
            for (const { mod, fn } of this.operators) {
                fn(mod, this);
                this.randOpCounter += 17;
            }
            for (const { mod, fn } of this.constraints) fn(mod, this);
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
                const time = this.animationRate * (this.curTime - p.spawnTime);
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
            out.push({
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
            });
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
        renderers: ['render_animated_sprites', 'render_sprite_trail', 'render_rope'],
        aliases: FN_ALIASES,
    };
}
