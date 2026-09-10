/*
 * Пипетка по картинке: цвет одного пикселя из того, что показано на экране.
 *
 * Живёт отдельным модулем, потому что арифметика вписывания — единственное
 * место, где легко взять цвет НЕ ОТТУДА, куда ткнули, и заметить это глазами
 * почти невозможно: соседний пиксель тоже похож на правду. Чистая часть
 * (`containPixel`) вынесена наружу и проверяется тестом на числах.
 */

/**
 * Точка НА КАРТИНКЕ из точки на экране.
 *
 * Кадр показывает текстуру целиком (`object-fit: contain`), поэтому по одной
 * оси у него остаются поля: квадратными текстуры бывают не всегда (у тела
 * шпиона 1024×512), и «доля от рамки» брала бы цвет со сдвигом, а на полях —
 * вообще мимо картинки.
 *
 * `box` — размер рамки, `size` — размер самой картинки в пикселях, `point` —
 * щелчок относительно левого верхнего угла рамки. `null` означает «мимо».
 */
export function containPixel(box, size, point) {
  const scale = Math.min(box.w / size.w, box.h / size.h);
  if (!(scale > 0)) return null;
  const x = (point.x - (box.w - size.w * scale) / 2) / scale;
  const y = (point.y - (box.h - size.h * scale) / 2) / scale;
  if (x < 0 || y < 0 || x >= size.w || y >= size.h) return null;
  return { x: Math.floor(x), y: Math.floor(y) };
}

/** Цвет как «#rrggbb»: в этом виде его хранят поля цвета и палитра. */
export const rgbHex = (r, g, b) => '#'
  + [r, g, b].map((v) => v.toString(16).padStart(2, '0')).join('');

//: Одна клетка 1×1 на все замеры: канвас размером с текстуру ради одного
//: пикселя — это лишние мегабайты на каждый щелчок.
let cell = null;

/**
 * Цвет картинки под курсором. Пустая строка — мимо или прочитать не дали.
 *
 * Читаем `naturalWidth`, а не размер на экране: цвет берётся из исходных
 * пикселей, и масштаб показа на него влиять не должен.
 */
export function colorAt(img, clientX, clientY) {
  const w = img.naturalWidth;
  const h = img.naturalHeight;
  if (!w || !h) return '';
  const box = img.getBoundingClientRect();
  const at = containPixel({ w: box.width, h: box.height }, { w, h },
                          { x: clientX - box.left, y: clientY - box.top });
  if (!at) return '';
  if (!cell) {
    cell = document.createElement('canvas');
    cell.width = 1;
    cell.height = 1;
  }
  try {
    const ctx = cell.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(img, at.x, at.y, 1, 1, 0, 0, 1, 1);
    const px = ctx.getImageData(0, 0, 1, 1).data;
    return rgbHex(px[0], px[1], px[2]);
  } catch (err) {
    // Картинка с чужого адреса закрывает канвас на чтение. У нас все свои
    // (`/file?path=…`), но молча отдать чёрный цвет хуже, чем ничего.
    return '';
  }
}
