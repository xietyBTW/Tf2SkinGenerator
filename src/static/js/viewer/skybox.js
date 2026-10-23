import * as THREE from 'three';

// Соответствие граней Source -> слотам CubeTexture Three.js.
// Порядок слотов WebGL-кубмапы: [+X, -X, +Y, -Y, +Z, -Z].
// rot - поворот картинки по часовой стрелке (в градусах) на канвасе
//
// ОТКАЛИБРОВАНО по стоковым небам TF2 (sky_halloween/sky_badlands_01) через
// численное сравнение стыков краёв: боковые грани хранятся КАК ФОТО (прямо,
// без зеркала), цепочка горизонта при повороте вправо - ft -> lf -> bk -> rt;
// up стыкуется низом к rt (поворот -90°). С учётом flipEnvMap Three.js
// (сэмплирование фона инвертирует X) слот nz показывает своё фото «как есть»
// для взгляда вдоль -Z. Менять ТОЛЬКО вместе с FACE_BASES в
// skybox_service.py - превью и нарезка панорамы обязаны совпадать
export const SRC_FACE_MAP = [
  { src: 'rt', rot: 0   },   // +X (справа-сзади по часовой от ft)
  { src: 'lf', rot: 0   },   // -X (следующая при повороте вправо от ft)
  { src: 'up', rot: -90 },   // +Y (низ картинки up примыкает к rt)
  { src: 'dn', rot: 90  },   // -Y (симметрично up; в стоке почти всегда 1×1)
  { src: 'bk', rot: 0   },   // +Z (за спиной)
  { src: 'ft', rot: 0   },   // -Z (фронт, направление камеры по умолчанию)
];

// Грань на квадратном канвасе с поворотом. Размер нормализуется (у стоковых
// небес грань dn часто крошечная - растягиваем до общего размера куба).
// Текстуры 2:1 (ширина = 2×высоты, полвысоты боковых граней стоковых небес)
// движок кладёт на ВЕРХНЮЮ половину грани, низ - растянутая нижняя строка
// (проверено: луна sky_halloween в 1024×512 круглая, при растяжении на весь
// квадрат была бы яйцом). Правило - только для боковых граней (isSide):
// up/dn в Source всегда квадратные. Квадратные текстуры - на всю грань
function _faceToCanvas(img, rotDeg, size, isSide) {
  const c   = document.createElement('canvas');
  c.width   = c.height = size;
  const ctx = c.getContext('2d');
  ctx.save();
  ctx.translate(size / 2, size / 2);
  ctx.rotate(rotDeg * Math.PI / 180);
  if (isSide && img.width >= img.height * 2) {
    // 2:1 - верхняя половина + низ из растянутой нижней строки
    ctx.drawImage(img, 0, 0, img.width, img.height, -size / 2, -size / 2, size, size / 2);
    ctx.drawImage(img, 0, img.height - 1, img.width, 1, -size / 2, 0, size, size / 2);
  } else {
    ctx.drawImage(img, -size / 2, -size / 2, size, size);
  }
  ctx.restore();
  return c;
}

/**
 * Заглушка отсутствующей грани: ровный цвет, усреднённый по тем, что есть
 *
 * Средний, а не чёрный: у ночного неба чёрное дно и так сойдёт, а у дневного
 * (sky_harvest_01) выглядит дырой в мире. Считаем по уменьшенным до 8x8
 * копиям - усреднять миллион пикселей ради одного цвета незачем.
 */
function _skyFlatFace(imgs, size) {
  let fill = 'rgb(90,90,90)';
  try {
    const probe = document.createElement('canvas');
    probe.width = probe.height = 8;
    const p = probe.getContext('2d', { willReadFrequently: true });
    let r = 0, g = 0, b = 0, n = 0;
    for (const img of imgs) {
      p.clearRect(0, 0, 8, 8);
      p.drawImage(img, 0, 0, 8, 8);
      const d = p.getImageData(0, 0, 8, 8).data;
      for (let i = 0; i < d.length; i += 4) { r += d[i]; g += d[i + 1]; b += d[i + 2]; n++; }
    }
    if (n) fill = 'rgb(' + Math.round(r / n) + ',' + Math.round(g / n) + ','
                         + Math.round(b / n) + ')';
  } catch (err) {
    // Канвас закрыт на чтение - серый лучше отказа от показа неба
    console.warn('[skybox] средний цвет не посчитать:', err);
  }
  const c = document.createElement('canvas');
  c.width = c.height = size;
  const ctx = c.getContext('2d');
  ctx.fillStyle = fill;
  ctx.fillRect(0, 0, size, size);
  return c;
}

// imgs - загруженные грани в порядке SRC_FACE_MAP, недостающие пустые. Куб
// единого размера: отсутствующие грани закрываются ровным средним цветом
export function buildSkyCube(imgs) {
  const real = imgs.filter(Boolean);
  const size = Math.max(...real.map(i => Math.max(i.width, i.height)));
  const flat = real.length < SRC_FACE_MAP.length
    ? _skyFlatFace(real, size) : null;
  const canvases = SRC_FACE_MAP.map((mm, i) => (imgs[i]
    ? _faceToCanvas(imgs[i], mm.rot, size, mm.src !== 'up' && mm.src !== 'dn')
    : flat));
  const cube = new THREE.CubeTexture(canvases);
  cube.colorSpace  = THREE.SRGBColorSpace;
  cube.needsUpdate = true;
  return cube;
}
