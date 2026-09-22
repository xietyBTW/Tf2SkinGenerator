/*
 * Посадка картинки на часть: размер, поворот, место.
 *
 * Раньше картинка растягивалась по прямоугольнику части — пропорции терялись,
 * повернуть или сдвинуть было нельзя, а замечалось это уже в игре.
 *
 * Окно показывает НАСТОЯЩУЮ развёртку части (треугольники, по которым
 * маскирует склейка), а не рамку: положенное вне маски при сборке исчезает, и
 * рамка обещала бы то, чего не будет.
 *
 * Расчёт повторяет `texture_compose_service.place_image`: тот же порядок
 * (размер → поворот → место) и тот же знак угла. Разойтись им нельзя — человек
 * настраивает по одному изображению, а в мод уйдёт другое.
 */

import * as api from './api.js';
import { loadImage } from './util.js';
import { applyView } from './preview.js';
import { chooseFile } from './util.js';
import { partsMaterial, hintParts, refreshParts } from './parts.js';

// ── Посадка картинки на часть ───────────────────────────────────────────
// Раньше картинка растягивалась по прямоугольнику части: пропорции терялись,
// повернуть или сдвинуть было нельзя, а замечалось это уже в игре.
//
// Окно показывает НАСТОЯЩУЮ развёртку части (треугольники, по которым
// маскирует склейка), а не рамку: положенное вне маски при сборке исчезает, и
// рамка обещала бы то, чего не будет.
//
// Расчёт посадки повторяет `texture_compose_service.place_image`: тот же
// порядок (размер → поворот → место) и тот же знак угла. Разойтись им нельзя —
// человек настраивает по одному изображению, а в мод уйдёт другое.

const placeDlg = document.getElementById('placedlg');

/**
 * Куда и какого размера ляжет картинка — в пикселях холста развёртки.
 *
 * Холст повторяет ПРОПОРЦИИ текстуры (W × H), а не квадрат: у тела шпиона
 * она 1024×512, и на квадрате развёртка сжималась вдвое по ширине, а
 * «целиком» вписывалось не так, как это потом делала склейка в пикселях.
 */
function placeRect(image, box, spec, W, H) {
  const bw = Math.max(1, (box[2] - box[0]) * W);
  const bh = Math.max(1, (box[3] - box[1]) * H);
  let w = bw;
  let h = bh;
  if (spec.fit !== 'stretch') {
    const k = spec.fit === 'cover'
      ? Math.max(bw / image.width, bh / image.height)
      : Math.min(bw / image.width, bh / image.height);
    w = image.width * k;
    h = image.height * k;
  }
  w *= spec.scale;
  // По высоте — свой множитель: за угол рамки тянут целиком, за сторону —
  // только по её оси. Старые работы второго не знают: там он равен первому.
  h *= (spec.scale_y === undefined ? spec.scale : spec.scale_y);
  // Развёртка считает v снизу, холст — сверху: место части переворачивается.
  const cx = box[0] * W + bw / 2 + spec.offset[0] * bw;
  const cy = (1 - box[3]) * H + bh / 2 + spec.offset[1] * bh;
  return { x: cx, y: cy, w, h };
}

/**
 * Как холст показывает развёртку: целиком или вплотную к правимому куску.
 *
 * Всё рисование остаётся в координатах ТЕКСТУРЫ (0..size), приближение —
 * одно преобразование холста поверх. Иначе масштаб пришлось бы вносить в
 * каждую формулу, и посадка картинки разъехалась бы с тем, что считает Python.
 *
 * Приближаем РОВНО к габариту части — тому самому, в который вписана картинка.
 * Раньше здесь стоял «плотный» габарит: он отбрасывал по 4% площади с каждого
 * края, чтобы не показывать дальние островки. Но картинка ложится в ПОЛНЫЙ
 * габарит, и окно врало: у праздничного огнетопора в начальный вид не
 * попадало от 36 до 49% треугольников части, а рамка картинки уходила за край
 * холста — человек целился в кусок, которого не видит.
 *
 * Автоматика не угадает, какой островок нужен человеку, поэтому она только
 * ставит СТАРТОВЫЙ вид, а дальше он приближает колесом.
 */
function placeView(state, W, H) {
  if (!state.zoom) return { k: 1, dx: 0, dy: 0 };
  const b = state.bbox;
  const w = Math.max(1, (b[2] - b[0]) * W);
  const h = Math.max(1, (b[3] - b[1]) * H);
  // Запас по краям: деталь, прижатая к самой рамке, читается хуже, а картинку
  // нередко двигают чуть за край куска. Меньше единицы не опускаемся — окно
  // называется «приблизить», отдалять оно не должно.
  const fit = Math.max(1, Math.min(W / w, H / h) * 0.86);
  const k = fit * (state.zoomK || 1);
  const focus = state.focus
    || [b[0] * W + w / 2, (1 - b[3]) * H + h / 2];
  return { k, dx: W / 2 - k * focus[0], dy: H / 2 - k * focus[1] };
}

/**
 * Внешний контур развёртки: рёбра, у которых нет пары.
 *
 * Развёртка приезжает ТРЕУГОЛЬНИКАМИ, и обвести каждый — значит нарисовать
 * сетку: у детали из полутора тысяч треугольников за ней не видно ни картинки,
 * ни собственных краёв. Внутреннее ребро принадлежит двум треугольникам сразу,
 * граничное — одному: пары взаимно уничтожаются, остаётся контур. Островов у
 * куска бывает несколько — контуров тогда столько же, и это правда о нём.
 */
function outlineOf(polygons) {
  const edges = new Map();
  for (const tri of polygons) {
    for (let i = 0; i < 3; i++) {
      const from = tri[i];
      const to = tri[(i + 1) % 3];
      const a = from[0] + ',' + from[1];
      const b = to[0] + ',' + to[1];
      const key = a < b ? a + '|' + b : b + '|' + a;
      if (edges.has(key)) edges.delete(key);
      else edges.set(key, [from, to]);
    }
  }
  return [...edges.values()];
}

function drawPlace(state) {
  const cv = document.getElementById('place-canvas');
  const g = cv.getContext('2d');
  const W = cv.width;
  const H = cv.height;
  g.setTransform(1, 0, 0, 1, 0, 0);
  g.clearRect(0, 0, W, H);

  const view = placeView(state, W, H);
  g.setTransform(view.k, 0, 0, view.k, view.dx, view.dy);

  if (state.base && !state.bare) g.drawImage(state.base, 0, 0, W, H);

  const shown = (state.frames && state.frames.length)
    ? state.frames[state.frame % state.frames.length]
    : state.image;
  const rect = shown ? placeRect(shown, state.bbox, state.spec, W, H) : null;

  const drawPicture = () => {
    g.save();
    g.translate(rect.x, rect.y);
    g.rotate(state.spec.angle * Math.PI / 180);
    g.drawImage(shown, -rect.w / 2, -rect.h / 2, rect.w, rect.h);
    g.restore();
  };

  /**
   * Обрезка по маске части — тому же набору треугольников, по которому
   * маскирует склейка.
   *
   * Обход у всех треугольников разворачиваем В ОДНУ сторону. Холст заливает
   * путь по правилу nonzero: пара треугольников, лежащих друг на друге с
   * противоположным обходом, даёт число оборотов 0 — то есть ДЫРУ. А в TF2
   * зеркальные половины модели делят одну развёртку сплошь: у праздничного
   * огнетопора таких треугольников 253 из 1249, у другой его части ровно
   * половина (88 из 176). Отсюда и было «свою текстуру видно только местами»:
   * картинка пропадала там, где две половины кладутся на одно место.
   *
   * Склейка этим не болела и не болеет — она заливает каждый треугольник
   * отдельно (PIL), поэтому в моде картинка лежала правильно, а врал показ.
   */
  const clipToPart = () => {
    g.beginPath();
    for (const tri of state.polygons) {
      const [a, b, c] = tri;
      // Знак площади считаем в координатах РАЗВЁРТКИ; холст переворачивает v,
      // и знак вместе с ним, поэтому порядок выбираем по «< 0».
      const area = (b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1]);
      const [p, q, r] = area < 0 ? [a, b, c] : [a, c, b];
      g.moveTo(p[0] * W, (1 - p[1]) * H);
      g.lineTo(q[0] * W, (1 - q[1]) * H);
      g.lineTo(r[0] * W, (1 - r[1]) * H);
      g.closePath();
    }
    g.clip();
  };

  // Без игровой текстуры картинку показываем ЦЕЛИКОМ, а не её обрезок: тогда
  // видно, что именно кладёшь. Призраком — то, что при сборке отрежется, в
  // полную силу — то, что доживёт. Иначе выбор «без игровой» прятал бы больше,
  // чем показывал.
  if (shown && state.bare) {
    g.save();
    g.globalAlpha = 0.28;
    drawPicture();
    g.restore();
  }
  if (shown) {
    g.save();
    clipToPart();
    drawPicture();
    g.restore();
  }

  // Контур маски поверх всего: без него не видно, докуда картинка доживёт.
  // Толщину делим на масштаб — иначе при приближении он превращается в брус.
  g.strokeStyle = '#cc5522';
  g.lineWidth = 1 / view.k;
  g.beginPath();
  if (state.outline) {
    // Считаем один раз: треугольники за время окна не меняются.
    if (!state.edges) state.edges = outlineOf(state.polygons);
    for (const [from, to] of state.edges) {
      g.moveTo(from[0] * W, (1 - from[1]) * H);
      g.lineTo(to[0] * W, (1 - to[1]) * H);
    }
  } else {
    for (const tri of state.polygons) {
      g.moveTo(tri[0][0] * W, (1 - tri[0][1]) * H);
      g.lineTo(tri[1][0] * W, (1 - tri[1][1]) * H);
      g.lineTo(tri[2][0] * W, (1 - tri[2][1]) * H);
      g.closePath();
    }
  }
  g.stroke();

  if (rect) drawHandle(g, rect, state.spec.angle, view.k);
  g.setTransform(1, 0, 0, 1, 0, 0);
}

//: Маркер поворота: отступ от края картинки и радиус — в пикселях ХОЛСТА
//: (деление на масштаб вида гасит приближение, поэтому размер постоянный).
//: Холст (длинная сторона 512) показывается примерно в 330 CSS-пикселях, то
//: есть всё это ещё и сжимается на треть — отсюда числа крупнее, чем кажется
//: нужным.
const HANDLE_GAP = 38;
const HANDLE_R = 10;
//: Сторона квадратика на рамке и радиус попадания по нему. Попадание крупнее
//: самого квадратика: целиться в семь пикселей мышью — работа, а не правка.
const GRIP = 9;
const GRIP_HIT = 14;

//: Ручки рамки: углы и середины сторон. Знаки говорят, какой край тянут, и
//: они же дают точку, которая при этом остаётся на месте (противоположная).
const GRIPS = [[-1, -1], [1, -1], [1, 1], [-1, 1],
               [0, -1], [1, 0], [0, 1], [-1, 0]];

/** Ручка под курсором в системе картинки. null — курсор не на ручке. */
function gripAt(rect, lx, ly, k) {
  const reach = GRIP_HIT / k;
  let best = null;
  for (const [sx, sy] of GRIPS) {
    const gap = Math.hypot(lx - sx * rect.w / 2, ly - sy * rect.h / 2);
    if (gap <= reach && (!best || gap < best.gap)) best = { sx, sy, gap };
  }
  return best;
}

/** Рамка картинки и маркер поворота над ней — привычная ручка, а не циферблат. */
function drawHandle(g, rect, angle, k) {
  const gap = HANDLE_GAP / k;
  const radius = HANDLE_R / k;
  g.save();
  g.translate(rect.x, rect.y);
  g.rotate(angle * Math.PI / 180);
  g.strokeStyle = '#cc5522';
  g.lineWidth = 1.5 / k;
  g.setLineDash([7 / k, 5 / k]);
  g.strokeRect(-rect.w / 2, -rect.h / 2, rect.w, rect.h);
  g.setLineDash([]);
  g.beginPath();
  g.moveTo(0, -rect.h / 2);
  g.lineTo(0, -rect.h / 2 - gap);
  g.stroke();
  // Заливка акцентом, обводка белым, а не наоборот: маркер висит над самой
  // картинкой, и белый кружок терялся на светлых наклейках.
  g.beginPath();
  g.arc(0, -rect.h / 2 - gap, radius, 0, Math.PI * 2);
  g.fillStyle = '#cc5522';
  g.fill();
  g.strokeStyle = '#fff';
  g.lineWidth = 2 / k;
  g.stroke();

  // Ручки размера — там же, где их ищет рука: по углам и серединам сторон.
  // Белая заливка с акцентной обводкой: они лежат на самой картинке, и
  // сплошной акцент на оранжевой наклейке пропадал бы.
  const side = GRIP / k;
  g.lineWidth = 1.5 / k;
  for (const [sx, sy] of GRIPS) {
    g.beginPath();
    g.rect(sx * rect.w / 2 - side / 2, sy * rect.h / 2 - side / 2, side, side);
    g.fillStyle = '#fff';
    g.fill();
    g.strokeStyle = '#cc5522';
    g.stroke();
  }
  g.restore();
}

/** Точка холста в системе КАРТИНКИ: центр в нуле, поворот снят. */
function localPoint(state, rect, clientX, clientY, cv) {
  const view = placeView(state, cv.width, cv.height);
  const r = cv.getBoundingClientRect();
  const tex = [((clientX - r.left) / r.width * cv.width - view.dx) / view.k,
               ((clientY - r.top) / r.height * cv.height - view.dy) / view.k];
  const rad = -state.spec.angle * Math.PI / 180;
  const dx = tex[0] - rect.x;
  const dy = tex[1] - rect.y;
  return [dx * Math.cos(rad) - dy * Math.sin(rad),
          dx * Math.sin(rad) + dy * Math.cos(rad), view.k];
}


/**
 * Тянет рамку за ручку.
 *
 * Противоположный край стоит на месте — так это работает в редакторах
 * изображений: тянешь правый край, левый не шевелится. Значит меняется не
 * только размер, но и центр, а центр здесь живёт в сдвиге (`offset`), в долях
 * места части.
 *
 * Угол тянет обе оси разом, сохраняя пропорции: чаще всего наклейку просто
 * увеличивают. Сторона тянет свою — ею картинку и вытягивают под деталь.
 */
function resizeBy(state, drag, event, cv) {
  const { sx, sy } = drag.grip;
  // Считаем в системе рамки НА МОМЕНТ НАЖАТИЯ: она не должна ехать вслед за
  // собственным изменением, иначе тяга разгоняется сама по себе.
  const [lx, ly] = localPoint(state, drag.rect, event.clientX, event.clientY, cv);
  let w = drag.w0;
  let h = drag.h0;
  if (sx) w = Math.max(4, Math.abs(lx + sx * drag.w0 / 2));
  if (sy) h = Math.max(4, Math.abs(ly + sy * drag.h0 / 2));
  if (sx && sy) {
    const k = Math.hypot(w, h) / Math.hypot(drag.w0, drag.h0);
    w = drag.w0 * k;
    h = drag.h0 * k;
  }

  const clamp = (value) => Math.max(0.05, Math.min(20, value));
  state.spec.scale = clamp(drag.scale0 * w / drag.w0);
  state.spec.scale_y = clamp(drag.scaleY0 * h / drag.h0);

  // Двигаем центр так, чтобы противоположный край остался там же, где был.
  const shiftX = -sx * (w - drag.w0) / 2;
  const shiftY = -sy * (h - drag.h0) / 2;
  const rad = state.spec.angle * Math.PI / 180;
  const worldX = shiftX * Math.cos(rad) - shiftY * Math.sin(rad);
  const worldY = shiftX * Math.sin(rad) + shiftY * Math.cos(rad);
  const bw = Math.max(1, (state.bbox[2] - state.bbox[0]) * cv.width);
  const bh = Math.max(1, (state.bbox[3] - state.bbox[1]) * cv.height);
  state.spec.offset = [drag.off0[0] - worldX / bw, drag.off0[1] - worldY / bh];
  drawPlace(state);
}

/**
 * Окно посадки одной картинки части.
 *
 * `shape` — ответ `api.partShape`: развёртка части, основа (всё, что на
 * материале уже лежит, кроме этой картинки) и список картинок части.
 * Список стоит слева; щелчок по другой картинке, «+ Добавить», «Заменить…»
 * и «Убрать» — тоже ответы окна, только оно при них не закрывается: цикл
 * в `editPartLayers` сохраняет посадку, делает дело и открывает окно на
 * нужном слое заново.
 *
 * Отвечает {act, spec, changed[, layer, file]}: act — ok, cancel, layer,
 * add, replace или drop; spec — посадка на момент ответа; changed — правили
 * ли её.
 */
export async function askPlacement(shape, imageUrl, spec, layers = null) {
  const state = {
    polygons: shape.polygons || [],
    bbox: shape.bbox || [0, 0, 1, 1],
    spec: { fit: spec.fit, angle: spec.angle, scale: spec.scale,
            scale_y: spec.scale_y === undefined ? spec.scale : spec.scale_y,
            offset: [spec.offset[0], spec.offset[1]] },
    base: shape.base ? await loadImage(api.fileUrl(shape.base, true)) : null,
    image: await loadImage(imageUrl),
  };

  const cv = document.getElementById('place-canvas');
  // Холст — в пропорциях основы: склейка считает «целиком»/«заполнить» в
  // ПИКСЕЛЯХ текстуры, и на квадратном холсте под текстуру 1024×512 картинка
  // вписывалась иначе, чем потом ложилась в мод, а развёртка стояла сжатой.
  // Длинная сторона — 512: размеры ручек считаются в пикселях холста.
  const ratio = state.base ? state.base.naturalWidth / state.base.naturalHeight : 1;
  cv.width = Math.round(ratio >= 1 ? 512 : 512 * ratio);
  cv.height = Math.round(ratio >= 1 ? 512 / ratio : 512);
  const wide = document.getElementById('place-w');
  const tall = document.getElementById('place-h');
  const angle = document.getElementById('place-a');
  const shiftX = document.getElementById('place-x');
  const shiftY = document.getElementById('place-y');
  const bare = document.getElementById('place-bare');
  const zoom = document.getElementById('place-zoom');
  const outline = document.getElementById('place-outline');
  // Галки показа под холстом — настройки ОКНА, а не предмета, и каждое
  // открытие начинает с одного и того же:
  //  • игровая текстура под наклейкой видна — контекст, хоть и пёстрый;
  //  • контур выключен — сетка треугольников нужна только на мелкой детали;
  //  • приближение включено: класть картинку на кусок, глядя на всю
  //    текстуру, — то же, что целиться в спичку с другого конца комнаты.
  state.bare = false;
  state.outline = false;
  state.zoom = true;
  state.zoomK = 1;
  state.focus = null;
  bare.checked = false;
  outline.checked = false;
  zoom.checked = true;

  // Кадры анимации приходят от Python отдельными картинками: браузер их из
  // гифки не достаёт — отсоединённый <img> её не крутит, а drawImage берёт
  // всегда первый кадр. Разбирает их тот же PIL, что и склейка, поэтому
  // предпросмотр показывает ровно то, что уйдёт в мод.
  state.frame = 0;
  if ((shape.frames || []).length > 1) {
    state.frames = await Promise.all(
      shape.frames.map((f) => loadImage(api.fileUrl(f))));
    const wait = Math.max(30, (shape.delays || [])[0] || 100);
    state.animate = setInterval(() => {
      state.frame += 1;
      drawPlace(state);
    }, wait);
  }

  //: Числа в полях — то же самое, что показывает рамка. Тянут её мышью, а
  //: поля обязаны идти следом: иначе они врут о том, что сейчас на холсте.
  const syncNumbers = () => {
    wide.value = Math.round(state.spec.scale * 100);
    tall.value = Math.round(state.spec.scale_y * 100);
    angle.value = Math.round(state.spec.angle);
    shiftX.value = Math.round(state.spec.offset[0] * 100);
    shiftY.value = Math.round(state.spec.offset[1] * 100);
  };

  const sync = () => {
    placeDlg.querySelectorAll('[data-fit]').forEach((b) => {
      b.classList.toggle('is-active', b.dataset.fit === state.spec.fit);
    });
    syncNumbers();
    drawPlace(state);
  };

  document.getElementById('place-part').textContent =
    `часть ${shape.part + 1} · развёртка ${state.polygons.length} тр.`;
  sync();
  const initial = JSON.stringify(state.spec);

  return new Promise((resolve) => {
    let done = false;
    const off = [];
    const on = (el, type, fn, opts) => {
      el.addEventListener(type, fn, opts);
      off.push(() => el.removeEventListener(type, fn, opts));
    };

    // `close` — закрыть ли окно: смена слоя и действия над списком оставляют
    // его открытым, чтобы оно не мигало между шагами.
    const settle = (value, close = true) => {
      if (done) return;
      done = true;
      if (state.animate) clearInterval(state.animate);
      off.forEach((f) => f());
      if (close) placeDlg.close();
      resolve({ ...value, spec: state.spec,
                changed: JSON.stringify(state.spec) !== initial });
    };

    showLayers(layers, on, settle);

    // Тянем картинку мышью: сдвиг считаем в долях места части — в тех же
    // единицах, в которых его понимает склейка.
    // Что делает нажатие — решает место: маркер над картинкой крутит её,
    // всё остальное двигает. Так это устроено в любом редакторе картинок, и
    // отдельного циферблата для поворота не нужно.
    const rectNow = () => {
      const shown = (state.frames && state.frames.length)
        ? state.frames[state.frame % state.frames.length]
        : state.image;
      return shown ? placeRect(shown, state.bbox, state.spec, cv.width, cv.height) : null;
    };

    let drag = null;
    on(cv, 'pointerdown', (e) => {
      cv.focus();
      const rect = rectNow();
      if (!rect) return;
      cv.setPointerCapture(e.pointerId);
      const [lx, ly, k] = localPoint(state, rect, e.clientX, e.clientY, cv);
      const handleY = -rect.h / 2 - HANDLE_GAP / k;
      const near = Math.hypot(lx, ly - handleY) <= (HANDLE_R + 6) / k;
      // Что делает нажатие, решает место: маркер над картинкой крутит,
      // квадратик на рамке тянет размер, всё остальное двигает.
      const grip = near ? null : gripAt(rect, lx, ly, k);
      if (near) drag = { turn: true };
      else if (grip) {
        drag = { grip, rect, w0: rect.w, h0: rect.h,
                 scale0: state.spec.scale, scaleY0: state.spec.scale_y,
                 off0: [...state.spec.offset] };
      } else {
        drag = { x: e.clientX, y: e.clientY, from: [...state.spec.offset] };
      }
    });
    on(cv, 'pointermove', (e) => {
      if (!drag) return;
      const rect = rectNow();
      if (!rect) return;
      if (drag.turn) {
        // Угол — от центра картинки к курсору. Маркер стоит НАД картинкой,
        // поэтому ноль там же, где он: atan2(dx, -dy), а не наоборот.
        const [lx, ly] = localPoint(state, rect, e.clientX, e.clientY, cv);
        const rad = state.spec.angle * Math.PI / 180;
        const dx = lx * Math.cos(rad) - ly * Math.sin(rad);
        const dy = lx * Math.sin(rad) + ly * Math.cos(rad);
        let angle = (Math.atan2(dx, -dy) * 180 / Math.PI + 360) % 360;
        // Прямые углы подтягиваются: попасть мышью ровно в 90° иначе нельзя,
        // а нужны они чаще всего.
        const step = Math.round(angle / 15) * 15;
        if (Math.abs(angle - step) < 3) angle = step % 360;
        state.spec.angle = angle;
        drawPlace(state);
        syncNumbers();
        return;
      }
      if (drag.grip) { resizeBy(state, drag, e, cv); syncNumbers(); return; }
      const r = cv.getBoundingClientRect();
      // Приближение меняет экранный размер места части: без множителя картинка
      // при перетаскивании убегала бы от курсора во столько же раз.
      const k = placeView(state, cv.width, cv.height).k;
      const bw = Math.max(1e-3, (state.bbox[2] - state.bbox[0]) * r.width * k);
      const bh = Math.max(1e-3, (state.bbox[3] - state.bbox[1]) * r.height * k);
      state.spec.offset = [drag.from[0] + (e.clientX - drag.x) / bw,
                           drag.from[1] + (e.clientY - drag.y) / bh];
      drawPlace(state);
      syncNumbers();
    });
    on(cv, 'pointerup', (e) => { cv.releasePointerCapture(e.pointerId); drag = null; });
    // Колесо приближает ВИД, а не картинку: размер картинки правится своим
    // ползунком, а вот подойти к нужному островку иначе нечем. Приближаем к
    // курсору, как в картах, — тогда панорамирование не нужно вовсе.
    on(cv, 'wheel', (e) => {
      e.preventDefault();
      if (!state.zoom) return;
      const W = cv.width;
      const H = cv.height;
      const r = cv.getBoundingClientRect();
      const at = [(e.clientX - r.left) / r.width * W,
                  (e.clientY - r.top) / r.height * H];
      const was = placeView(state, W, H);
      // Точка текстуры под курсором — она и должна остаться под ним.
      const tex = [(at[0] - was.dx) / was.k, (at[1] - was.dy) / was.k];
      state.zoomK = Math.max(1, Math.min(12,
        (state.zoomK || 1) * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
      const now = placeView({ ...state, focus: tex }, W, H);
      state.focus = [tex[0] - (at[0] - W / 2) / now.k,
                     tex[1] - (at[1] - H / 2) / now.k];
      drawPlace(state);
    }, { passive: false });

    on(placeDlg, 'click', (e) => {
      const fit = e.target.closest('[data-fit]');
      if (!fit) return;
      state.spec.fit = fit.dataset.fit;
      sync();
    });

    // Поворот стрелками: маркер мышкой — привычно, но не единственный способ
    // должен быть у того, кто мышью не работает.
    on(cv, 'keydown', (e) => {
      const step = { ArrowLeft: -15, ArrowDown: -15, ArrowRight: 15, ArrowUp: 15 }[e.key];
      if (step === undefined) return;
      e.preventDefault();
      state.spec.angle = ((state.spec.angle + step) % 360 + 360) % 360;
      drawPlace(state);
      syncNumbers();
    });

    // Поля — для точного числа; мышью то же самое делают ручки на рамке.
    const byNumber = (field, axis) => on(field, 'input', () => {
      const value = Number(field.value) / 100;
      if (!(value > 0)) return;              // пустое поле — человек его чистит
      state.spec[axis] = Math.max(0.05, Math.min(20, value));
      drawPlace(state);
    });
    byNumber(wide, 'scale');
    byNumber(tall, 'scale_y');
    // Поворот и сдвиг числом: то же, что маркер и перетаскивание, только точно.
    on(angle, 'input', () => {
      const value = Number(angle.value);
      if (!Number.isFinite(value) || angle.value === '') return;
      state.spec.angle = ((value % 360) + 360) % 360;
      drawPlace(state);
    });
    const byShift = (field, axis) => on(field, 'input', () => {
      const value = Number(field.value);
      if (!Number.isFinite(value) || field.value === '') return;
      const offset = [...state.spec.offset];
      offset[axis] = Math.max(-5, Math.min(5, value / 100));
      state.spec.offset = offset;
      drawPlace(state);
    });
    byShift(shiftX, 0);
    byShift(shiftY, 1);
    on(bare, 'change', () => { state.bare = bare.checked; drawPlace(state); });
    on(outline, 'change', () => {
      state.outline = outline.checked;
      drawPlace(state);
    });
    on(zoom, 'change', () => {
      state.zoom = zoom.checked;
      state.zoomK = 1;             // выключили и включили — вид снова стартовый
      state.focus = null;
      drawPlace(state);
    });

    on(document.getElementById('place-reset'), 'click', () => {
      state.spec = { fit: 'contain', angle: 0, scale: 1, scale_y: 1,
                     offset: [0, 0] };
      state.zoomK = 1;
      state.focus = null;
      sync();
    });
    on(document.getElementById('place-ok'), 'click', () => settle({ act: 'ok' }));
    on(document.getElementById('place-cancel'), 'click', () => settle({ act: 'cancel' }));
    on(placeDlg, 'cancel', (e) => { e.preventDefault(); settle({ act: 'cancel' }); });

    if (!placeDlg.open) placeDlg.showModal();
  });
}

/**
 * Колонка картинок части.
 *
 * Строки лежат так же, как картинки: верхняя — поверх. Щелчок выбирает
 * слой, а перетаскивание переставляет — порядок в списке и есть порядок
 * наложения. Тащим сами, без drag-and-drop браузера: тому нужен призрак и
 * долгое нажатие на тачпаде, а здесь строка едет за курсором сразу, соседи
 * уступают место плавно, и отпущенная доезжает до своей щели.
 */
function showLayers(layers, on, settle) {
  const panel = document.getElementById('place-layers');
  panel.hidden = !layers;
  if (!layers) return;
  const list = document.getElementById('place-list');
  list.innerHTML = '';
  const count = layers.images.length;
  document.getElementById('place-count').textContent = String(count);
  //: Порядок показа → номер слоя в стопке (стопка считается снизу вверх).
  const shown = layers.images.map((_, i) => i).reverse();
  const rows = shown.map((li, di) => {
    const img = layers.images[li];
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'place__layer' + (li === layers.selected ? ' is-active' : '');
    row.innerHTML = '<span class="place__grip" aria-hidden="true"></span>'
      + '<span class="place__thumb"><img alt=""></span>'
      + '<span class="place__meta"><span class="place__name mono"></span>'
      + '<span class="place__pos"></span></span>';
    row.querySelector('img').src = api.fileUrl(img.path);
    const name = row.querySelector('.place__name');
    name.textContent = String(img.path).split(/[\\/]/).pop();
    name.title = name.textContent;
    row.querySelector('.place__pos').textContent =
      count === 1 ? '' : di === 0 ? 'поверх' : di === count - 1 ? 'внизу' : '';
    return row;
  });
  list.append(...rows);

  //: Длительность из темы: при выключенной анимации — ноль, и ждать нечего.
  const dur = parseFloat(getComputedStyle(document.documentElement)
    .getPropertyValue('--dur')) || 0;
  //: Шаг между строками — расстояние между их верхами, вместе с зазором.
  const pitch = () => (rows.length > 1
    ? rows[1].offsetTop - rows[0].offsetTop : rows[0].offsetHeight);

  let drag = null;
  rows.forEach((row, di) => {
    on(row, 'click', () => {
      // После перетаскивания браузер шлёт и щелчок — он не выбор.
      if (row.dataset.dragged) { delete row.dataset.dragged; return; }
      if (shown[di] !== layers.selected) settle({ act: 'layer', layer: shown[di] }, false);
    });
    on(row, 'pointerdown', (e) => {
      if (e.button !== 0 || rows.length < 2) return;
      drag = { di, y0: e.clientY, moved: false, target: di };
      row.setPointerCapture(e.pointerId);
    });
    on(row, 'pointermove', (e) => {
      if (!drag || drag.di !== di) return;
      const dy = e.clientY - drag.y0;
      // Порог: щелчок с дрожью руки — всё ещё щелчок.
      if (!drag.moved) {
        if (Math.abs(dy) < 4) return;
        drag.moved = true;
        row.dataset.dragged = '1';
        row.classList.add('is-dragging');
        list.classList.add('is-sorting');
      }
      const h = pitch();
      row.style.transform = `translateY(${dy}px) scale(1.02)`;
      const target = Math.max(0, Math.min(rows.length - 1, Math.round(di + dy / h)));
      if (target === drag.target) return;
      drag.target = target;
      // Соседи между старым и новым местом сдвигаются на одну строку.
      rows.forEach((other, oi) => {
        if (other === row) return;
        let shift = 0;
        if (di < target && oi > di && oi <= target) shift = -h;
        else if (di > target && oi >= target && oi < di) shift = h;
        other.style.transform = shift ? `translateY(${shift}px)` : '';
      });
    });
    const finish = (e) => {
      if (!drag || drag.di !== di) return;
      const { target, moved } = drag;
      drag = null;
      if (row.hasPointerCapture(e.pointerId)) row.releasePointerCapture(e.pointerId);
      if (!moved) return;
      // Довести строку до щели плавно — и только потом отдать ответ: список
      // перестроится уже на том же месте, и глазу не за что зацепиться.
      row.classList.remove('is-dragging');
      list.classList.remove('is-sorting');
      row.classList.add('is-settling');
      row.style.transform = `translateY(${(target - di) * pitch()}px)`;
      setTimeout(() => {
        if (target !== di) {
          settle({ act: 'move', layer: shown[di], to: shown[target] }, false);
          return;
        }
        rows.forEach((r) => { r.style.transform = ''; r.classList.remove('is-settling'); });
      }, dur);
    };
    on(row, 'pointerup', finish);
    on(row, 'pointercancel', finish);
  });

  // Файл спрашиваем ЗДЕСЬ, до ответа окна: отказ от выбора файла ничего не
  // меняет, и окно остаётся жить как было.
  const withFile = (act) => async () => {
    const file = await chooseFile('image/*,.vtf');
    if (file) settle({ act, file }, false);
  };
  on(document.getElementById('place-add'), 'click', withFile('add'));
  on(document.getElementById('place-replace'), 'click', withFile('replace'));
  on(document.getElementById('place-drop'), 'click', () => settle({ act: 'drop' }, false));
}

/**
 * Редактор картинок части: окно посадки со списком слоёв слева.
 *
 * Открывается на слое `layer` (отрицательный — с конца). Каждое действие в
 * списке — свой шаг: посадка правимого слоя сохраняется при любом уходе с
 * него, добавление кладёт картинку поверх и открывает её, замена ставит
 * файл на место слоя с его посадкой, «Убрать» снимает слой, перетаскивание
 * переставляет в стопке (выше в списке — поверх на модели). Всё это —
 * обычные правки предмета, Ctrl+Z их откатывает по одной. «Отмена» бросает
 * только несохранённую посадку текущего слоя.
 */
export async function editPartLayers(part, layer = -1) {
  let current = layer;
  for (;;) {
    const shape = await api.partShape(partsMaterial, part, current);
    if (shape.error) { hintParts(shape.error); break; }
    const images = shape.images || [];
    if (!images.length || !shape.image) break;       // снять больше нечего
    current = shape.layer;

    const res = await askPlacement(shape, api.fileUrl(shape.image.path), shape.image,
                                   { images, selected: current });
    if (res.act === 'cancel') return;
    if (res.changed && res.act !== 'drop'
        && !await persist(part, null, res.spec, current)) return;
    if (res.act === 'ok') return;

    if (res.act === 'layer') {
      current = res.layer;
    } else if (res.act === 'drop') {
      if (!await persist(part, null, null, current)) return;
      current = Math.min(current, images.length - 2);
    } else if (res.act === 'add') {
      if (!await persist(part, await api.upload(res.file), null, null)) return;
      current = -1;                                   // новая — верхняя
    } else if (res.act === 'replace') {
      if (!await persist(part, await api.upload(res.file), res.spec, current)) return;
    } else if (res.act === 'move') {
      hintParts('Переставляю…');
      const moved = await api.movePartTexture(partsMaterial, part, res.layer, res.to);
      if (moved.error) { hintParts(moved.error); return; }
      applyView(moved);
      await refreshParts();
      hintParts('');
      current = res.to;
    }
  }
  if (placeDlg.open) placeDlg.close();
}

/** Одно действие над картинками части — и модель с полосой частей следом. */
async function persist(part, path, options, layer) {
  hintParts(path ? 'Наложение на часть…' : 'Перекладываю…');
  const res = await api.setPartTexture(partsMaterial, part, path, options, layer);
  if (res.error) { hintParts(res.error); return false; }
  applyView(res);
  await refreshParts();
  hintParts('');
  return true;
}
