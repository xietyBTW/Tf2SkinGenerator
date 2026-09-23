// Выделение треугольников ножницами: что отрезать в отдельную часть.
//
// Раньше ножницы резали только по островам развёртки, а острова почти никогда
// не совпадают с тем, что человек видит деталью: у обреза приклад вместе с
// корпусом — один остров, и ножницы отвечали «резать нечего». Часть же для
// склейки — просто набор треугольников (маска строится по их UV), поэтому
// выделять можно как удобно глазу:
//
//   деталь — гладкая поверхность до острых рёбер (торец ствола отделяется от
//            ствола, приклад — от корпуса);
//   кисть  — треугольники в радиусе от точки под курсором;
//   остров — остров развёртки целиком, как раньше.
//
// Здесь только геометрия и обходы: без three.js, чтобы проверять из node
// (tests/test_viewer_select_js.py). Треугольник — номер в порядке OBJ, тот же,
// что `faceIndex` у луча и номера у разбора частей в Python.

/** Точность сварки вершин — как `_WELD` в mesh_parts_service (4 знака). */
const WELD = 1e4;

/**
 * Связи треугольников одного меша.
 *
 * @param positions  плоский массив xyz, по 9 чисел на треугольник
 * @param uvs        плоский массив uv, по 6 чисел на треугольник (или null)
 * @returns {count, neighbors, normals, positions, islands}
 *   neighbors — соседи через общее РЕБРО (вершины сварены по позиции);
 *   islands   — номер острова развёртки у каждого треугольника: треугольники
 *               с общей вершиной UV — один остров, как в Python.
 */
export function topology(positions, uvs) {
  const count = Math.floor(positions.length / 9);
  const ids = new Map();
  const vid = (i) => {
    const k = Math.round(positions[i] * WELD) + ',' + Math.round(positions[i + 1] * WELD)
      + ',' + Math.round(positions[i + 2] * WELD);
    let id = ids.get(k);
    if (id === undefined) { id = ids.size; ids.set(k, id); }
    return id;
  };

  const edges = new Map();
  const normals = new Float32Array(count * 3);
  for (let t = 0; t < count; t++) {
    const o = t * 9;
    const v = [vid(o), vid(o + 3), vid(o + 6)];
    for (let c = 0; c < 3; c++) {
      const a = v[c], b = v[(c + 1) % 3];
      if (a === b) continue;
      const k = a < b ? a + '|' + b : b + '|' + a;
      const list = edges.get(k);
      if (list) list.push(t); else edges.set(k, [t]);
    }
    const ax = positions[o + 3] - positions[o], ay = positions[o + 4] - positions[o + 1],
          az = positions[o + 5] - positions[o + 2];
    const bx = positions[o + 6] - positions[o], by = positions[o + 7] - positions[o + 1],
          bz = positions[o + 8] - positions[o + 2];
    let nx = ay * bz - az * by, ny = az * bx - ax * bz, nz = ax * by - ay * bx;
    const len = Math.hypot(nx, ny, nz);
    if (len > 0) { nx /= len; ny /= len; nz /= len; }
    normals.set([nx, ny, nz], t * 3);
  }

  const neighbors = Array.from({ length: count }, () => []);
  for (const list of edges.values()) {
    for (const a of list) for (const b of list) if (a !== b) neighbors[a].push(b);
  }
  return { count, neighbors, normals, positions,
           islands: uvIslands(uvs, count) };
}

/** Острова развёртки: треугольники с общей КООРДИНАТОЙ UV — один остров. */
function uvIslands(uvs, count) {
  const labels = new Int32Array(count).fill(-1);
  if (!uvs) return labels;
  const parent = new Int32Array(count).map((_, i) => i);
  const find = (x) => { while (parent[x] !== x) { parent[x] = parent[parent[x]]; x = parent[x]; } return x; };
  const owner = new Map();
  for (let t = 0; t < count; t++) {
    for (let c = 0; c < 3; c++) {
      const i = t * 6 + c * 2;
      const k = uvs[i] + ',' + uvs[i + 1];
      const had = owner.get(k);
      if (had === undefined) owner.set(k, t);
      else parent[find(t)] = find(had);
    }
  }
  for (let t = 0; t < count; t++) labels[t] = find(t);
  return labels;
}

/**
 * Детали при данном пороге: номер области у каждого треугольника.
 *
 * Соседи — одна деталь, если угол между их нормалями меньше порога. Модуль
 * скалярного произведения, а не само оно: у одежды часть треугольников
 * намотана «изнанкой» наружу, и честный угол там вышел бы под 180°.
 */
export function detailLabels(topo, angleDeg) {
  const labels = new Int32Array(topo.count).fill(-1);
  const limit = Math.cos((Math.max(0, Math.min(180, angleDeg)) * Math.PI) / 180);
  const n = topo.normals;
  for (let seed = 0; seed < topo.count; seed++) {
    if (labels[seed] !== -1) continue;
    labels[seed] = seed;
    const stack = [seed];
    while (stack.length) {
      const t = stack.pop();
      for (const s of topo.neighbors[t]) {
        if (labels[s] !== -1) continue;
        const dot = Math.abs(n[t * 3] * n[s * 3] + n[t * 3 + 1] * n[s * 3 + 1]
                             + n[t * 3 + 2] * n[s * 3 + 2]);
        // Вырожденный треугольник нормали не имеет — он деталь не делит.
        const flat = (n[s * 3] === 0 && n[s * 3 + 1] === 0 && n[s * 3 + 2] === 0)
          || (n[t * 3] === 0 && n[t * 3 + 1] === 0 && n[t * 3 + 2] === 0);
        if (flat || dot >= limit - 1e-6) { labels[s] = seed; stack.push(s); }
      }
    }
  }
  return labels;
}

/** Все треугольники с той же меткой, что у `tri`. */
export function withLabel(labels, tri) {
  const want = labels[tri];
  const out = [];
  if (want === undefined || want === -1) return out;
  for (let t = 0; t < labels.length; t++) if (labels[t] === want) out.push(t);
  return out;
}

/**
 * Квадрат расстояния от точки до треугольника (ближайшая точка по Эриксону,
 * «Real-Time Collision Detection», 5.1.5).
 */
export function triangleDistance2(p, a, b, c) {
  const sub = (u, v) => [u[0] - v[0], u[1] - v[1], u[2] - v[2]];
  const dot = (u, v) => u[0] * v[0] + u[1] * v[1] + u[2] * v[2];
  const at = (s, u, t, v) => [a[0] + s * u[0] + t * v[0], a[1] + s * u[1] + t * v[1],
                              a[2] + s * u[2] + t * v[2]];
  const ab = sub(b, a), ac = sub(c, a), ap = sub(p, a);
  const d1 = dot(ab, ap), d2 = dot(ac, ap);
  let q;
  if (d1 <= 0 && d2 <= 0) q = a;
  else {
    const bp = sub(p, b), d3 = dot(ab, bp), d4 = dot(ac, bp);
    const cp = sub(p, c), d5 = dot(ab, cp), d6 = dot(ac, cp);
    const vc = d1 * d4 - d3 * d2, vb = d5 * d2 - d1 * d6, va = d3 * d6 - d5 * d4;
    if (d3 >= 0 && d4 <= d3) q = b;
    else if (d6 >= 0 && d5 <= d6) q = c;
    else if (vc <= 0 && d1 >= 0 && d3 <= 0) q = at(d1 / (d1 - d3), ab, 0, ac);
    else if (vb <= 0 && d2 >= 0 && d6 <= 0) q = at(0, ab, d2 / (d2 - d6), ac);
    else if (va <= 0 && d4 - d3 >= 0 && d5 - d6 >= 0) {
      const w = (d4 - d3) / ((d4 - d3) + (d5 - d6));
      q = [b[0] + w * (c[0] - b[0]), b[1] + w * (c[1] - b[1]), b[2] + w * (c[2] - b[2])];
    } else {
      const den = 1 / (va + vb + vc);
      q = at(vb * den, ab, vc * den, ac);
    }
  }
  const d = sub(p, q);
  return dot(d, d);
}

/**
 * Кисть: треугольники, до которых можно дойти от `start` по поверхности, не
 * отходя от точки дальше `radius`.
 *
 * По поверхности, а не просто по расстоянию: иначе кисть на тонком прикладе
 * красила бы и его обратную сторону, и соседнюю деталь сквозь зазор.
 *
 * Меряется расстояние до САМОГО треугольника, а не до его центра: у моделей
 * TF2 бока ствола — длинные узкие треугольники во всю длину, центр такого
 * далеко от курсора, и кисть по стволу брала три треугольника вместо полосы.
 */
export function brushTriangles(topo, start, point, radius) {
  if (start == null || start < 0 || start >= topo.count) return [];
  const pos = topo.positions;
  const r2 = radius * radius;
  const corner = (t, k) => [pos[t * 9 + k * 3], pos[t * 9 + k * 3 + 1], pos[t * 9 + k * 3 + 2]];
  const near = (t) => triangleDistance2(point, corner(t, 0), corner(t, 1), corner(t, 2)) <= r2;
  const seen = new Set([start]);
  const stack = [start];
  while (stack.length) {
    const t = stack.pop();
    for (const s of topo.neighbors[t]) {
      if (!seen.has(s) && near(s)) { seen.add(s); stack.push(s); }
    }
  }
  return [...seen];
}
