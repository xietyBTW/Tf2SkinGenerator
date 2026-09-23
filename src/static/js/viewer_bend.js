// Изгиб гирлянды во вьювере — та же формула, что у сборки
// (src/services/festive_decor.py: falloff, apply_bends). Совпадение держит
// тест (tests/test_viewer_bend_js.py): разойдись они — в игре гирлянда
// оказалась бы не там, где её согнули в превью.
//
// Изгиб — {c: точка, r: радиус, d: сдвиг} в осях SMD гирлянды. Меши вьювера
// лежат в осях сцены: (x, y, z)_smd → (x, z, −y), как в SmdToObjService.
// Расстояния и центры от такой замены осей не зависят, поэтому считать можно
// прямо в осях сцены, переведя только точку и сдвиг.

/** Вес движения на доле радиуса t: 1 в центре, плавно к 0 на краю. */
export function falloff(t) {
  if (t >= 1) return 0;
  const u = 1 - t * t;
  return u * u;
}

export const toScene = (v) => [v[0], v[2], -v[1]];
export const toSmd = (v) => [v[0], -v[2], v[1]];

/**
 * Изгибы по порядку — на месте.
 *
 * @param parts  [{positions: плоский массив xyz в осях сцены, groups: жёсткая
 *               группа каждой вершины (-1 — гнётся сама)}]. Группа может
 *               тянуться через несколько мешей (лампочка и её патрон — разные
 *               материалы), поэтому центры считаются по всем частям сразу.
 * @param bends  [{c, r, d}] в осях SMD.
 */
export function applyBends(parts, bends) {
  for (const bend of bends || []) {
    const r = Number(bend && bend.r) || 0;
    if (r <= 0) continue;
    const c = toScene(bend.c || [0, 0, 0]);
    const d = toScene(bend.d || [0, 0, 0]);

    const sums = new Map();
    for (const { positions, groups } of parts) {
      for (let i = 0; i < groups.length; i++) {
        const g = groups[i];
        if (g < 0) continue;
        let acc = sums.get(g);
        if (!acc) { acc = [0, 0, 0, 0]; sums.set(g, acc); }
        acc[0] += positions[3 * i];
        acc[1] += positions[3 * i + 1];
        acc[2] += positions[3 * i + 2];
        acc[3] += 1;
      }
    }
    const weightOf = new Map();
    for (const [g, [x, y, z, n]] of sums) {
      weightOf.set(g, falloff(Math.hypot(x / n - c[0], y / n - c[1], z / n - c[2]) / r));
    }
    for (const { positions, groups } of parts) {
      for (let i = 0; i < groups.length; i++) {
        const g = groups[i];
        const w = g >= 0 ? weightOf.get(g)
          : falloff(Math.hypot(positions[3 * i] - c[0], positions[3 * i + 1] - c[1],
                               positions[3 * i + 2] - c[2]) / r);
        if (!w) continue;
        positions[3 * i] += w * d[0];
        positions[3 * i + 1] += w * d[1];
        positions[3 * i + 2] += w * d[2];
      }
    }
  }
}
