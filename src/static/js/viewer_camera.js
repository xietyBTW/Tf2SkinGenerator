// Камера вида от первого лица.
//
// Сцена вьюмодели приходит уже в общем пространстве: руки и оружие приведены
// туда матрицами скиннинга, а конвертер осей перевёл его в оси Three.js
// (x,y,z) → (x, z, -y). Замеры на настоящих моделях TF2 дают такую картину:
//
//     глаз      начало координат
//     вперёд    +Z        (в Source это -Y)
//     вверх     +Y        (в Source это +Z)
//     вправо    -X
//
// Поэтому модель НЕ центрируется и НЕ масштабируется, как в орбитальном
// режиме: она уже стоит там, где должна, относительно глаза. Камере остаётся
// встать в глаз и посмотреть вперёд.
//
// FOV — калибровочная ручка. У Source вьюмодель рисуется своим полем зрения
// (cvar viewmodel_fov), и «правильного» числа, выводимого из данных, нет:
// его подбирают глазами. По умолчанию берём значение из стоковой настройки.
//
// Модуль чистый (без THREE) — чтобы его считал тест на Node.

export const DEFAULT_VIEWMODEL_FOV = 54;
export const MIN_VIEWMODEL_FOV = 20;
export const MAX_VIEWMODEL_FOV = 120;

export const DEFAULT_RIG = {
  eye: [0, 0, 0],
  forward: [0, 0, 1],
  up: [0, 1, 0],
  fov: DEFAULT_VIEWMODEL_FOV,
};

// Куда поставить камеру и куда ей смотреть.
//
// rig: { eye, forward, up, fov } — любое поле можно опустить.
// Возвращает { position, target, up, fov } в координатах сцены.
export function firstPersonCamera(rig) {
  const source = rig || {};
  const eye = vec3(source.eye, DEFAULT_RIG.eye);
  const forward = normalize(vec3(source.forward, DEFAULT_RIG.forward),
                            DEFAULT_RIG.forward);
  const up = normalize(vec3(source.up, DEFAULT_RIG.up), DEFAULT_RIG.up);
  return {
    position: eye,
    // Точка взгляда на единицу вперёд: направление важно, расстояние нет.
    target: [eye[0] + forward[0], eye[1] + forward[1], eye[2] + forward[2]],
    up,
    fov: clampFov(source.fov),
  };
}

export function clampFov(value) {
  const fov = Number(value);
  if (!Number.isFinite(fov)) return DEFAULT_VIEWMODEL_FOV;
  return Math.min(MAX_VIEWMODEL_FOV, Math.max(MIN_VIEWMODEL_FOV, fov));
}

// ── Внутреннее ────────────────────────────────────────────────────────────── //

function vec3(value, fallback) {
  if (!Array.isArray(value) || value.length < 3) return fallback.slice();
  const out = value.slice(0, 3).map(Number);
  return out.every(Number.isFinite) ? out : fallback.slice();
}

// Нулевой или испорченный вектор направления развалил бы матрицу вида —
// возвращаем запасной, а не NaN.
function normalize(v, fallback) {
  const length = Math.hypot(v[0], v[1], v[2]);
  if (!(length > 1e-6)) return fallback.slice();
  return [v[0] / length, v[1] / length, v[2] / length];
}
