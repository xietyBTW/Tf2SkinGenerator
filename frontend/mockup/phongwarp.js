/*
 * Конструктор $phongwarptexture - градиента, который красит блик
 *
 * Градиент считает Python (services/phongwarp.py), здесь поля и рисование.
 * Шары - формула шейдера (source-sdk-2013, common_vertexlitgeneric_dx9.h и
 * skin_ps20b.fxc): блик (L·R)^k; без градиента он умножается на маску
 * $phongfresnelranges (здесь [.25 .5 1] - так у 5922 материалов TF2), с
 * градиентом маска отключается, а блик умножается на градиент в точке
 * (сила блика, френель). Френель - (1 − N·V)²
 *
 * Свет ходит по кругу: при свете спереди блик в центре шара и берёт только
 * верх градиента, при свете сбоку и сзади - у края и берёт низ. Так виден
 * весь узор, а точки на квадрате показывают, что именно берётся сейчас.
 */

import * as api from './api.js';
import { ALBEDO, AMBIENT, toSrgb, stopsEditor } from './lightwarp.js';

const EXPONENT = 6;               // размер блика на шаре: широкий, чтобы узор был виден
const BOOST = 1.6;                // $phongboost шара
export const RANGES = [0.25, 0.5, 1];    // $phongfresnelranges шара без градиента

const ORBIT_MS = 7000;            // полный круг света

/** Свет на угле `a`: вокруг шара по горизонтали, чуть сверху */
function lightAt(a) {
  const v = [Math.sin(a) * 0.95, 0.35, Math.cos(a)];
  const len = Math.hypot(...v);
  return v.map((c) => c / len);
}

export const fresnelRanges = (f, r = RANGES) => (f < 0.5
  ? r[0] + (r[1] - r[0]) * f * 2
  : r[1] + (r[2] - r[1]) * (f * 2 - 1));

/** Шар с бликом при свете `light`. `warp` - градиент [строка френеля][столбец
 * блика] или null; без него блик идёт через `ranges` ($phongfresnelranges) и
 * красится `tint` ([r, g, b] 0..1, $phongtint). Отдаёт точки градиента, что
 * сейчас взяты, [[строка, столбец]] */
function drawSphere(canvas, warp, light, ranges = RANGES, tint0 = null) {
  const LIGHT = light;
  const used = [];
  const size = canvas.width;
  const ctx = canvas.getContext('2d');
  const img = ctx.createImageData(size, size);
  const half = size / 2;
  const last = warp ? warp.length - 1 : 0;
  for (let py = 0; py < size; py++) {
    for (let px = 0; px < size; px++) {
      const x = (px + 0.5 - half) / half;
      const y = (half - py - 0.5) / half;
      const rr = x * x + y * y;
      if (rr > 1) continue;
      const n = [x, y, Math.sqrt(1 - rr)];
      const nl = n[0] * LIGHT[0] + n[1] * LIGHT[1] + n[2] * LIGHT[2];
      const lambert = 0.5 * nl + 0.5;
      // Отражённый свет к зрителю (0, 0, 1): R = 2(N·L)N − L
      const rv = Math.max(0, 2 * nl * n[2] - LIGHT[2]);
      const spec = rv ** EXPONENT;
      const fres = (1 - n[2]) ** 2;
      let tint = tint0 || [1, 1, 1];
      let mask = fresnelRanges(fres, ranges);
      if (warp) {
        const row = Math.round(fres * last);
        const col = Math.round(spec * last);
        const t = warp[row][col];
        tint = [t[0] / 255, t[1] / 255, t[2] / 255];
        mask = 1;                                   // маска френеля отключена
        if (spec > 0.05 && px % 5 === 0 && py % 5 === 0) used.push([row, col]);
      }
      const at = (py * size + px) * 4;
      for (let c = 0; c < 3; c++) {
        const diffuse = ALBEDO * (AMBIENT + lambert * lambert);
        const lit = diffuse + spec * BOOST * mask * tint[c];
        img.data[at + c] = Math.round(255 * toSrgb(Math.min(1, lit)));
      }
      img.data[at + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  return used;
}

/** Градиент (64×64) крупно и поверх - точки, что шар берёт сейчас, и
 * стрелка направления (`angle` в градусах; null - у узора его нет) */
/**
 * Шар для карточки «Блик»: свет ходит, как у Phong-warp, а блик идёт через
 * края блика ($phongfresnelranges) и цвет из настроек. `read()` отдаёт
 * {ranges, tint} при каждом кадре - карточка ничего не перерисовывает сама.
 */
export function phongSphere(caption, tip, read) {
  const fig = el('figure', 'lwarp__fig');
  const canvas = el('canvas', 'lwarp__sphere');
  canvas.width = canvas.height = 120;
  fig.append(canvas, el('figcaption', 'label label--inline', caption));
  fig.title = tip || '';
  let running = false;
  const draw = (now) => {
    const { ranges, tint } = read();
    drawSphere(canvas, null, lightAt(1.9 * Math.sin((now / ORBIT_MS) * Math.PI * 2)), ranges, tint);
  };
  const tick = (now) => {
    if (!fig.isConnected || document.hidden) { running = false; return; }
    draw(now);
    requestAnimationFrame(tick);
  };
  return {
    node: fig,
    start() {
      draw(performance.now());               // кадр сразу, даже в свёрнутом окне
      if (!running) { running = true; requestAnimationFrame(tick); }
    },
  };
}

function drawTexture(canvas, warp, used, angle) {
  const n = warp.length;
  const small = document.createElement('canvas');
  small.width = small.height = n;
  const sctx = small.getContext('2d');
  const img = sctx.createImageData(n, n);
  warp.forEach((row, r) => row.forEach(([red, g, b], c) => img.data.set([red, g, b, 255], (r * n + c) * 4)));
  sctx.putImageData(img, 0, 0);
  const ctx = canvas.getContext('2d');
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(small, 0, 0, canvas.width, canvas.height);
  const cell = canvas.width / n;
  ctx.fillStyle = 'rgba(255,255,255,.9)';
  ctx.strokeStyle = 'rgba(0,0,0,.6)';
  const seen = new Set();
  for (const [r, c] of used) {
    const key = r * n + c;
    if (seen.has(key)) continue;
    seen.add(key);
    ctx.beginPath();
    ctx.arc((c + 0.5) * cell, (r + 0.5) * cell, 1.2, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }
  if (angle !== null) drawArrow(ctx, canvas.width, angle);
}

/** Стрелка через центр квадрата: откуда и куда идут цвета точек */
function drawArrow(ctx, side, angle) {
  const a = (angle * Math.PI) / 180;
  const dx = Math.cos(a);
  const dy = Math.sin(a);
  const c = side / 2;
  const r = side * 0.38;
  const head = side * 0.08;
  const tip = [c + dx * r, c + dy * r];
  const path = () => {
    ctx.beginPath();
    ctx.moveTo(c - dx * r, c - dy * r);
    ctx.lineTo(...tip);
    ctx.moveTo(tip[0] - head * (dx - dy * 0.6), tip[1] - head * (dy + dx * 0.6));
    ctx.lineTo(...tip);
    ctx.lineTo(tip[0] - head * (dx + dy * 0.6), tip[1] - head * (dy - dx * 0.6));
  };
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.strokeStyle = 'rgba(0,0,0,.65)';
  ctx.lineWidth = 4;
  path();
  ctx.stroke();
  ctx.strokeStyle = '#fff';
  ctx.lineWidth = 2;
  path();
  ctx.stroke();
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/**
 * Блок конструктора. `schema` - material_map_schema().phongwarp, `saved` -
 * сохранённые параметры или null, `onChange` - человек что-то поменял.
 * Возвращает { node, params(), setEnabled(bool) } - как lightwarpEditor.
 */
export function phongwarpEditor(schema, saved, onChange = () => {}) {
  const L = schema.labels;
  const T = schema.tips || {};
  const values = { ...schema.defaults, ...(saved || {}) };
  const node = el('div', 'lwarp');

  const presetRow = el('div', 'mapcard__cell lwarp__preset');
  const presetBox = el('div', 'select');
  const preset = el('select');
  for (const p of schema.presets) preset.append(new Option(p.label, p.id));
  preset.value = values.preset;
  presetBox.append(preset);
  presetRow.append(el('span', 'label label--inline', L.preset), presetBox);
  presetRow.title = T.preset || '';

  const changed = () => { refresh(); onChange(); };
  const editor = stopsEditor({ ...L, gradient_hint: `${L.points} ${L.gradient_hint}` },
                             schema.max_stops, changed);
  editor.set(values.stops || schema.defaults.stops);

  // Второй ряд: цвета у края модели (низ квадрата). Верх - первый ряд
  const edgeToggle = el('label', 'check');
  const edgeRow = el('input');
  edgeRow.type = 'checkbox';
  edgeRow.checked = Boolean(values.edge_row);
  edgeToggle.append(edgeRow, el('span', '', L.edge_row));
  edgeToggle.title = T.edge_row || '';
  const mainHead = el('p', 'label label--inline lwarp__rowhead', L.row_main);
  const edgeHead = el('p', 'label label--inline lwarp__rowhead', L.row_edge);
  const edgeEditor = stopsEditor({ ...L, gradient_hint: '' }, schema.max_stops, changed);
  edgeEditor.set(values.edge_stops || schema.defaults.edge_stops);
  edgeEditor.node.querySelector('.lwarp__note').hidden = true;   // подсказка уже у первого
  const customBox = el('div', 'lwarp__custom');
  customBox.append(mainHead, editor.node, edgeToggle, edgeHead, edgeEditor.node);

  // Направление цветов: кнопки на частые углы, число, перетаскивание по квадрату
  let angle = Number(values.angle) || 0;
  const angleRow = el('div', 'mappane__row lwarp__angle');
  angleRow.title = T.angle || '';
  const angleSeg = el('div', 'seg lwarp__angleseg');
  const quick = [0, 45, 90, 135].map((deg) => {
    const b = el('button', '', `${deg}°`);
    b.type = 'button';
    b.addEventListener('click', () => setAngle(deg));
    angleSeg.append(b);
    return [deg, b];
  });
  const angleInput = el('input', 'input input--num');
  angleInput.type = 'number';
  angleInput.min = '0';
  angleInput.max = '359';
  angleInput.addEventListener('change', () => setAngle(Number(angleInput.value) || 0));
  angleRow.append(el('span', 'label label--inline', L.angle), angleSeg, angleInput,
                  el('span', 'mapcard__tip', L.angle_hint));
  function setAngle(deg, quiet = false) {
    angle = ((Math.round(deg) % 360) + 360) % 360;
    angleInput.value = String(angle);
    for (const [d, b] of quick) b.classList.toggle('is-active', d === angle);
    if (!quiet) changed();
  }
  setAngle(angle, true);

  const range = (key, min, max) => {
    const input = el('input', 'slider lwarp__range');
    input.type = 'range';
    input.min = String(min);
    input.max = String(max);
    input.value = String(values[key]);
    return input;
  };
  const strength = range('strength', 0, 100);
  const bands = range('bands', 1, schema.max_bands);
  const shift = range('shift', 0, 100);
  const edge = range('edge', 0, 100);
  const edgeColor = el('input', 'lwarp__color');
  edgeColor.type = 'color';
  edgeColor.value = values.edge_color;
  const out = (input) => {
    const span = el('span', 'mono lwarp__value');
    input.addEventListener('input', () => { span.textContent = input.value; });
    span.textContent = input.value;
    return span;
  };

  const grid = el('div', 'mapcard__params lwarp__grid');
  const cell = (label, tip, ...controls) => {
    const box = el('label', 'mapcard__cell');
    box.append(el('span', 'label label--inline', label), ...controls);
    box.title = tip || '';
    grid.append(box);
    return box;
  };
  cell(L.strength, T.strength, strength, out(strength));
  const bandsCell = cell(L.bands, T.bands, bands, out(bands));
  const shiftCell = cell(L.shift, T.shift, shift, out(shift));
  const edgeCell = cell(L.edge, T.edge, edgeColor, edge);

  // Градиент и два шара: «как было» и «как будет»
  const view = el('div', 'lwarp__view');
  const figure = (caption, className, side) => {
    const fig = el('figure', 'lwarp__fig');
    const canvas = el('canvas', className);
    canvas.width = canvas.height = side;
    fig.append(canvas, el('figcaption', 'label label--inline', caption));
    return [fig, canvas];
  };
  const [beforeFig, before] = figure(L.before, 'lwarp__sphere', 120);
  const [afterFig, after] = figure(L.after, 'lwarp__sphere', 120);
  const [textureFig, texture] = figure('', 'pwarp__texture', 128);
  textureFig.querySelector('figcaption').remove();
  beforeFig.title = T.before;
  afterFig.title = T.after;
  textureFig.title = T.texture;
  const spheres = el('div', 'lwarp__spheres');
  spheres.append(beforeFig, afterFig);
  const texBox = el('div', 'lwarp__stripbox');
  texBox.append(textureFig, el('p', 'mapcard__tip lwarp__note', L.texture));
  view.append(spheres, texBox);

  node.append(presetRow, customBox, angleRow, view, grid,
              el('p', 'mapcard__tip lwarp__note', L.hint));

  const isCustom = () => preset.value === schema.custom;
  const patterned = () => preset.value === 'rainbow' || preset.value === 'oil';
  const hasAngle = () => !patterned();             // у точек и золота - направление
  const params = () => ({
    preset: preset.value,
    strength: Number(strength.value),
    bands: Number(bands.value),
    shift: Number(shift.value),
    edge_color: edgeColor.value,
    edge: Number(edge.value),
    stops: editor.get(),
    angle,
    edge_row: edgeRow.checked,
    edge_stops: edgeEditor.get(),
  });

  // Тянуть по квадрату - повернуть стрелку: направление от центра к курсору.
  // Рядом с 0/45/90/… прилипает, чтобы ровный угол ловился без усилия
  const angleFrom = (e) => {
    const box = texture.getBoundingClientRect();
    const deg = (Math.atan2(e.clientY - box.top - box.height / 2,
                            e.clientX - box.left - box.width / 2) * 180) / Math.PI;
    const snap = Math.round(deg / 45) * 45;
    return Math.abs(deg - snap) < 5 ? snap : deg;
  };
  texture.addEventListener('pointerdown', (e) => {
    if (!hasAngle()) return;
    e.preventDefault();
    texture.setPointerCapture(e.pointerId);
    setAngle(angleFrom(e));
    const move = (ev) => setAngle(angleFrom(ev));
    texture.addEventListener('pointermove', move);
    const stop = () => texture.removeEventListener('pointermove', move);
    texture.addEventListener('pointerup', stop, { once: true });
    texture.addEventListener('pointercancel', stop, { once: true });
  });

  // Свет ходит по кругу, пока блок на экране, закрыли окно - анимация встала
  let warp = null;
  let frame = 0;
  let running = false;
  // Свет качается: спереди (блик в центре) -> сбоку и чуть сзади (блик у
  // края) -> обратно. Полностью сзади шар был бы почти чёрным
  const draw = (now) => {
    const light = lightAt(1.9 * Math.sin((now / ORBIT_MS) * Math.PI * 2));
    drawSphere(before, null, light);
    drawTexture(texture, warp, drawSphere(after, warp, light), hasAngle() ? angle : null);
  };
  const tick = (now) => {
    if (!node.isConnected || node.hidden || document.hidden) { running = false; return; }
    frame += 1;
    if (frame % 2 === 0 && warp) draw(now);         // ~30 кадров в секунду хватает
    requestAnimationFrame(tick);
  };
  const animate = () => {
    if (running) return;
    running = true;
    requestAnimationFrame(tick);
  };

  let ticket = 0;
  let timer = null;
  function refresh() {
    customBox.hidden = !isCustom();
    mainHead.hidden = edgeHead.hidden = edgeEditor.node.hidden = !edgeRow.checked;
    angleRow.hidden = !hasAngle();
    texture.classList.toggle('is-draggable', hasAngle());
    // Полосы и сдвиг оттенка - у радуги и плёнки, у градиентов их нет
    bandsCell.hidden = shiftCell.hidden = !patterned();
    // Второй ряд и есть цвета у края - отдельный «Цвет у края» лишний
    edgeCell.hidden = isCustom() && edgeRow.checked;
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const mine = ++ticket;
      const res = await api.phongwarpPreview(params());
      if (mine !== ticket || !res || !res.image) return;
      warp = res.image;
      // Кадр сразу: requestAnimationFrame в свёрнутом окне не идёт, и без
      // этого шары оставались бы пустыми до возврата в окно
      draw(performance.now());
      animate();
    }, 40);
  }
  for (const input of [preset, strength, bands, shift, edge, edgeColor, edgeRow]) {
    input.addEventListener('input', changed);
  }
  refresh();

  return {
    node,
    params,
    setEnabled(on) {
      node.hidden = !on;
      if (on) refresh();
    },
  };
}
