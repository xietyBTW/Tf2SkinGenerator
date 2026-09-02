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

/** Куда и какого размера ляжет картинка — в пикселях холста развёртки. */
function placeRect(image, box, spec, size) {
  const bw = Math.max(1, (box[2] - box[0]) * size);
  const bh = Math.max(1, (box[3] - box[1]) * size);
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
  h *= spec.scale;
  // Развёртка считает v снизу, холст — сверху: место части переворачивается.
  const cx = box[0] * size + bw / 2 + spec.offset[0] * bw;
  const cy = (1 - box[3]) * size + bh / 2 + spec.offset[1] * bh;
  return { x: cx, y: cy, w, h };
}

/**
 * Как холст показывает развёртку: целиком или вплотную к правимому куску.
 *
 * Всё рисование остаётся в координатах ТЕКСТУРЫ (0..size), приближение —
 * одно преобразование холста поверх. Иначе масштаб пришлось бы вносить в
 * каждую формулу, и посадка картинки разъехалась бы с тем, что считает Python.
 *
 * Автоматика не угадает, какой островок нужен человеку, поэтому она только
 * ставит СТАРТОВЫЙ вид, а дальше он приближает колесом.
 */
function placeView(state, size) {
  if (!state.zoom) return { k: 1, dx: 0, dy: 0 };
  const b = state.dense || state.bbox;
  const w = Math.max(1, (b[2] - b[0]) * size);
  const h = Math.max(1, (b[3] - b[1]) * size);
  // Запас по краям: деталь, прижатая к самой рамке, читается хуже, а картинку
  // нередко двигают чуть за край куска. Меньше единицы не опускаемся — окно
  // называется «приблизить», отдалять оно не должно.
  const fit = Math.max(1, Math.min(size / w, size / h) * 0.86);
  const k = fit * (state.zoomK || 1);
  const focus = state.focus
    || [b[0] * size + w / 2, (1 - b[3]) * size + h / 2];
  return { k, dx: size / 2 - k * focus[0], dy: size / 2 - k * focus[1] };
}

function drawPlace(state) {
  const cv = document.getElementById('place-canvas');
  const g = cv.getContext('2d');
  const size = cv.width;
  g.setTransform(1, 0, 0, 1, 0, 0);
  g.clearRect(0, 0, size, size);

  const view = placeView(state, size);
  g.setTransform(view.k, 0, 0, view.k, view.dx, view.dy);

  if (state.base && !state.bare) g.drawImage(state.base, 0, 0, size, size);

  const shown = (state.frames && state.frames.length)
    ? state.frames[state.frame % state.frames.length]
    : state.image;
  const rect = shown ? placeRect(shown, state.bbox, state.spec, size) : null;

  const drawPicture = () => {
    g.save();
    g.translate(rect.x, rect.y);
    g.rotate(state.spec.angle * Math.PI / 180);
    g.drawImage(shown, -rect.w / 2, -rect.h / 2, rect.w, rect.h);
    g.restore();
  };

  const clipToPart = () => {
    g.beginPath();
    for (const tri of state.polygons) {
      g.moveTo(tri[0][0] * size, (1 - tri[0][1]) * size);
      g.lineTo(tri[1][0] * size, (1 - tri[1][1]) * size);
      g.lineTo(tri[2][0] * size, (1 - tri[2][1]) * size);
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
  for (const tri of state.polygons) {
    g.moveTo(tri[0][0] * size, (1 - tri[0][1]) * size);
    g.lineTo(tri[1][0] * size, (1 - tri[1][1]) * size);
    g.lineTo(tri[2][0] * size, (1 - tri[2][1]) * size);
    g.closePath();
  }
  g.stroke();

  if (rect) drawHandle(g, rect, state.spec.angle, view.k);
  g.setTransform(1, 0, 0, 1, 0, 0);
}

//: Маркер поворота: отступ от края картинки и радиус — в пикселях ХОЛСТА
//: (деление на масштаб вида гасит приближение, поэтому размер постоянный).
//: Холст 512 показывается примерно в 330 CSS-пикселях, то есть всё это ещё и
//: сжимается на треть — отсюда числа крупнее, чем кажется нужным.
const HANDLE_GAP = 38;
const HANDLE_R = 10;

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
  g.restore();
}

/** Точка холста в системе КАРТИНКИ: центр в нуле, поворот снят. */
function localPoint(state, rect, size, clientX, clientY, cv) {
  const view = placeView(state, size);
  const r = cv.getBoundingClientRect();
  const tex = [((clientX - r.left) / r.width * size - view.dx) / view.k,
               ((clientY - r.top) / r.height * size - view.dy) / view.k];
  const rad = -state.spec.angle * Math.PI / 180;
  const dx = tex[0] - rect.x;
  const dy = tex[1] - rect.y;
  return [dx * Math.cos(rad) - dy * Math.sin(rad),
          dx * Math.sin(rad) + dy * Math.cos(rad), view.k];
}


/**
 * Спрашивает, как посадить картинку. Возвращает настройку или null (отмена).
 *
 * `shape` — ответ `api.partShape`: развёртка части и то, что на ней уже лежит.
 */
export async function askPlacement(shape, imageUrl, spec) {
  const state = {
    polygons: shape.polygons || [],
    bbox: shape.bbox || [0, 0, 1, 1],
    spec: { fit: spec.fit, angle: spec.angle, scale: spec.scale,
            offset: [spec.offset[0], spec.offset[1]] },
    base: shape.base ? await loadImage(api.fileUrl(shape.base, true)) : null,
    image: await loadImage(imageUrl),
  };

  const cv = document.getElementById('place-canvas');
  const scale = document.getElementById('place-scale');
  const bare = document.getElementById('place-bare');
  const zoom = document.getElementById('place-zoom');
  // Игровая текстура под наклейкой — контекст, но пёстрый: на ней не видно
  // границ собственной картинки. Прятать её нужно только на время правки,
  // поэтому это галка окна, а не настройка предмета.
  bare.checked = false;
  state.bare = false;
  // Приближение по умолчанию: класть картинку на кусок, глядя на всю текстуру,
  // — то же, что целиться в спичку с другого конца комнаты.
  zoom.checked = true;
  state.zoom = true;
  // Плотный габарит считает Python и отдаёт вместе с развёрткой: там же он и
  // покрыт тестом, а страница не перебирает полторы тысячи треугольников.
  state.dense = shape.dense || null;
  state.zoomK = 1;
  state.focus = null;

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

  const sync = () => {
    placeDlg.querySelectorAll('[data-fit]').forEach((b) => {
      b.classList.toggle('is-active', b.dataset.fit === state.spec.fit);
    });
    scale.value = Math.round(state.spec.scale * 100);
    drawPlace(state);
  };

  document.getElementById('place-part').textContent =
    'часть ' + (shape.part + 1) + ' · развёртка ' + state.polygons.length + ' тр.';
  sync();

  return new Promise((resolve) => {
    let done = false;
    const off = [];
    const on = (el, type, fn, opts) => {
      el.addEventListener(type, fn, opts);
      off.push(() => el.removeEventListener(type, fn, opts));
    };

    const settle = (value) => {
      if (done) return;
      done = true;
      if (state.animate) clearInterval(state.animate);
      off.forEach((f) => f());
      placeDlg.close();
      resolve(value);
    };

    // Тянем картинку мышью: сдвиг считаем в долях места части — в тех же
    // единицах, в которых его понимает склейка.
    // Что делает нажатие — решает место: маркер над картинкой крутит её,
    // всё остальное двигает. Так это устроено в любом редакторе картинок, и
    // отдельного циферблата для поворота не нужно.
    const rectNow = () => {
      const shown = (state.frames && state.frames.length)
        ? state.frames[state.frame % state.frames.length]
        : state.image;
      return shown ? placeRect(shown, state.bbox, state.spec, cv.width) : null;
    };

    let drag = null;
    on(cv, 'pointerdown', (e) => {
      cv.focus();
      const rect = rectNow();
      if (!rect) return;
      cv.setPointerCapture(e.pointerId);
      const [lx, ly, k] = localPoint(state, rect, cv.width, e.clientX, e.clientY, cv);
      const handleY = -rect.h / 2 - HANDLE_GAP / k;
      const near = Math.hypot(lx, ly - handleY) <= (HANDLE_R + 6) / k;
      drag = near
        ? { turn: true }
        : { x: e.clientX, y: e.clientY, from: [...state.spec.offset] };
    });
    on(cv, 'pointermove', (e) => {
      if (!drag) return;
      const rect = rectNow();
      if (!rect) return;
      if (drag.turn) {
        // Угол — от центра картинки к курсору. Маркер стоит НАД картинкой,
        // поэтому ноль там же, где он: atan2(dx, -dy), а не наоборот.
        const [lx, ly] = localPoint(state, rect, cv.width, e.clientX, e.clientY, cv);
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
        return;
      }
      const r = cv.getBoundingClientRect();
      // Приближение меняет экранный размер места части: без множителя картинка
      // при перетаскивании убегала бы от курсора во столько же раз.
      const k = placeView(state, cv.width).k;
      const bw = Math.max(1e-3, (state.bbox[2] - state.bbox[0]) * r.width * k);
      const bh = Math.max(1e-3, (state.bbox[3] - state.bbox[1]) * r.height * k);
      state.spec.offset = [drag.from[0] + (e.clientX - drag.x) / bw,
                           drag.from[1] + (e.clientY - drag.y) / bh];
      drawPlace(state);
    });
    on(cv, 'pointerup', (e) => { cv.releasePointerCapture(e.pointerId); drag = null; });
    // Колесо приближает ВИД, а не картинку: размер картинки правится своим
    // ползунком, а вот подойти к нужному островку иначе нечем. Приближаем к
    // курсору, как в картах, — тогда панорамирование не нужно вовсе.
    on(cv, 'wheel', (e) => {
      e.preventDefault();
      if (!state.zoom) return;
      const size = cv.width;
      const r = cv.getBoundingClientRect();
      const at = [(e.clientX - r.left) / r.width * size,
                  (e.clientY - r.top) / r.height * size];
      const was = placeView(state, size);
      // Точка текстуры под курсором — она и должна остаться под ним.
      const tex = [(at[0] - was.dx) / was.k, (at[1] - was.dy) / was.k];
      state.zoomK = Math.max(1, Math.min(12,
        (state.zoomK || 1) * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
      const now = placeView({ ...state, focus: tex }, size);
      state.focus = [tex[0] - (at[0] - size / 2) / now.k,
                     tex[1] - (at[1] - size / 2) / now.k];
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
    });

    on(scale, 'input', () => {
      state.spec.scale = Number(scale.value) / 100;
      drawPlace(state);
    });
    on(bare, 'change', () => { state.bare = bare.checked; drawPlace(state); });
    on(zoom, 'change', () => {
      state.zoom = zoom.checked;
      state.zoomK = 1;             // выключили и включили — вид снова стартовый
      state.focus = null;
      drawPlace(state);
    });

    on(document.getElementById('place-reset'), 'click', () => {
      state.spec = { fit: 'contain', angle: 0, scale: 1, offset: [0, 0] };
      state.zoomK = 1;
      state.focus = null;
      sync();
    });
    on(document.getElementById('place-ok'), 'click', () => settle(state.spec));
    on(document.getElementById('place-cancel'), 'click', () => settle(null));
    on(placeDlg, 'cancel', () => settle(null));

    placeDlg.showModal();
  });
}

/**
 * Открывает окно посадки для части: развёртку и основу спрашиваем у Python.
 *
 * `path` — новая картинка; без него правится уже положенная.
 */
export async function askPartPlacement(part, path) {
  const shape = await api.partShape(partsMaterial, part);
  if (shape.error) { hintParts(shape.error); return null; }
  const spec = shape.image
    || { fit: 'contain', angle: 0, scale: 1, offset: [0, 0] };
  const url = api.fileUrl(path || spec.path);
  return askPlacement(shape, url, spec);
}

/** Правка посадки уже лежащей картинки — по щелчку на её метке в списке. */
export async function repositionPart(part) {
  const options = await askPartPlacement(part, null);
  if (options === null) return;
  hintParts('Перекладываю…');
  const res = await api.setPartTexture(partsMaterial, part, null, options);
  if (res.error) { hintParts(res.error); return; }
  applyView(res);
  await refreshParts();
  hintParts('');
}
