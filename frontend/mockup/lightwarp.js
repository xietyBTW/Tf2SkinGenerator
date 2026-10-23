/*
 * Конструктор полоски $lightwarptexture внутри карточки карты
 *
 * Полоску считает Python (services/lightwarp.py): основы - файлы игры, и
 * правило одно на превью и сборку. Здесь поля, редактор точек и рисование
 *
 * Шар показывает формулу игры: освещённость half-lambert 0.5·N·L + 0.5 -
 * координата полоски, свет = 2 · полоска (полоска линейная). Окружения и
 * блика в шаре нет - это примерный вид, подпись об этом говорит.
 */

import * as api from './api.js';

export const ALBEDO = 0.35;                       // серая модель, линейная (~0.63 в sRGB)
//: Окружающий свет (ambient cube) - ровный, как в помещении карты. В игре
//: он свой на каждой точке карты, здесь одно значение для сравнения
export const AMBIENT = 0.12;
export const LIGHT = (() => {                     // свет сверху слева, к зрителю
  const v = [-0.55, 0.6, 0.58];
  const len = Math.hypot(...v);
  return v.map((c) => c / len);
})();
const CHANNELS = ['#e0524f', '#4fbf6a', '#4f86e0'];

export const toSrgb = (c) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);
const hexRgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
const rgbHex = (rgb) => '#' + rgb.map((v) => Math.round(v).toString(16).padStart(2, '0')).join('');

function drawStrip(canvas, ramp) {
  const ctx = canvas.getContext('2d');
  const img = ctx.createImageData(ramp.length, 1);
  ramp.forEach(([r, g, b], i) => img.data.set([r, g, b, 255], i * 4));
  ctx.putImageData(img, 0, 0);
}

/**
 * Шар по формуле шейдера (source-sdk-2013, common_vertexlitgeneric_dx9.h,
 * PixelShaderDoLightingLinear): цвет = альбедо · (окружающий + прямой).
 * Окружающий свет (ambient cube) прибавляется МИМО полоски. Прямой -
 * DiffuseTerm: half-lambert x = 0.5·N·L + 0.5; с полоской 2·полоска(x),
 * без неё x² (half-lambert без полоски возводится в квадрат).
 * `ramp` - null: шар «без lightwarp».
 */
function drawSphere(canvas, ramp) {
  const size = canvas.width;
  const ctx = canvas.getContext('2d');
  const img = ctx.createImageData(size, size);
  const half = size / 2;
  for (let py = 0; py < size; py++) {
    for (let px = 0; px < size; px++) {
      const x = (px + 0.5 - half) / half;
      const y = (half - py - 0.5) / half;
      const rr = x * x + y * y;
      if (rr > 1) continue;
      const n = [x, y, Math.sqrt(1 - rr)];
      const lambert = 0.5 * (n[0] * LIGHT[0] + n[1] * LIGHT[1] + n[2] * LIGHT[2]) + 0.5;
      const texel = ramp && ramp[Math.min(ramp.length - 1, Math.round(lambert * (ramp.length - 1)))];
      const at = (py * size + px) * 4;
      for (let c = 0; c < 3; c++) {
        const direct = ramp ? 2 * (texel[c] / 255) : lambert * lambert;
        const lit = ALBEDO * (AMBIENT + direct);
        img.data[at + c] = Math.round(255 * toSrgb(Math.min(1, lit)));
      }
      img.data[at + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
}

/** Яркость каналов по полоске, пунктир - 128, то есть обычная яркость в игре */
function drawGraph(canvas, ramp) {
  const { width: w, height: h } = canvas;
  const ctx = canvas.getContext('2d');
  const css = getComputedStyle(canvas);
  ctx.clearRect(0, 0, w, h);
  const y = (v) => h - 1 - (v / 255) * (h - 2);
  ctx.fillStyle = css.getPropertyValue('--hairline').trim() || 'rgba(128,128,128,.15)';
  ctx.fillRect(0, 0, w, y(128));                        // зона пересвета
  ctx.setLineDash([4, 3]);
  ctx.strokeStyle = css.getPropertyValue('--ink-mute').trim() || '#888';
  ctx.beginPath();
  ctx.moveTo(0, y(128));
  ctx.lineTo(w, y(128));
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.lineWidth = 1.5;
  // Серая полоска: каналы совпадают, и от трёх линий видна была бы последняя
  // (синяя) - рисуем одну нейтральную
  const grey = ramp.every(([r, g, b]) => r === g && g === b);
  const lines = grey ? [css.getPropertyValue('--ink').trim() || '#ddd'] : CHANNELS;
  lines.forEach((colour, c) => {
    ctx.strokeStyle = colour;
    ctx.beginPath();
    ramp.forEach((px, i) => {
      const x = (i / (ramp.length - 1)) * (w - 1);
      if (i) ctx.lineTo(x, y(px[c])); else ctx.moveTo(x, y(px[c]));
    });
    ctx.stroke();
  });
}

/** Цвет градиента точек в позиции `pos` (как `_stops_curve` в Python) */
function colourAt(stops, pos) {
  if (pos <= stops[0].pos) return hexRgb(stops[0].colour);
  for (let i = 1; i < stops.length; i++) {
    const a = stops[i - 1];
    const b = stops[i];
    if (pos <= b.pos) {
      const t = b.pos > a.pos ? (pos - a.pos) / (b.pos - a.pos) : 1;
      const ca = hexRgb(a.colour);
      const cb = hexRgb(b.colour);
      return ca.map((v, c) => v + (cb[c] - v) * t);
    }
  }
  return hexRgb(stops[stops.length - 1].colour);
}

/**
 * Редактор цветных точек: полоса, ручки под ней, цвет и позиция выбранной.
 * Щелчок по полосе - новая точка, ручку можно тащить и двигать стрелками,
 * Delete убирает (меньше двух нельзя).
 */
export function stopsEditor(L, maxStops, onChange) {
  let stops = [];
  let selected = null;

  const node = document.createElement('div');
  node.className = 'lwarp__grad';
  const bar = document.createElement('div');
  bar.className = 'lwarp__bar';
  const barCanvas = document.createElement('canvas');
  barCanvas.width = 256;
  barCanvas.height = 1;
  bar.append(barCanvas);
  const handles = document.createElement('div');
  handles.className = 'lwarp__handles';

  const row = document.createElement('div');
  row.className = 'mapcard__params';
  const pointCell = document.createElement('label');
  pointCell.className = 'mapcard__cell';
  const pointText = document.createElement('span');
  pointText.className = 'label label--inline';
  pointText.textContent = L.point;
  const colour = document.createElement('input');
  colour.type = 'color';
  colour.className = 'lwarp__color';
  pointCell.append(pointText, colour);
  const posCell = document.createElement('label');
  posCell.className = 'mapcard__cell';
  const posText = document.createElement('span');
  posText.className = 'label label--inline';
  posText.textContent = L.position;
  const position = document.createElement('input');
  position.type = 'number';
  position.className = 'input input--num';
  position.min = '0';
  position.max = '100';
  position.step = '0.5';
  posCell.append(posText, position);
  const remove = document.createElement('button');
  remove.type = 'button';
  remove.className = 'textbtn textbtn--sm';
  remove.textContent = L.remove_point;
  row.append(pointCell, posCell, remove);

  const hint = document.createElement('p');
  hint.className = 'mapcard__tip lwarp__note';
  hint.textContent = L.gradient_hint;
  node.append(bar, handles, row, hint);

  const sorted = () => stops.sort((a, b) => a.pos - b.pos);
  const changed = () => { render(); onChange(); };

  function drawBar() {
    sorted();
    const ctx = barCanvas.getContext('2d');
    const img = ctx.createImageData(256, 1);
    for (let i = 0; i < 256; i++) img.data.set([...colourAt(stops, i / 255), 255], i * 4);
    ctx.putImageData(img, 0, 0);
  }

  function render() {
    drawBar();
    handles.replaceChildren(...stops.map((st) => {
      const h = document.createElement('button');
      h.type = 'button';
      h.className = 'lwarp__stop' + (st === selected ? ' is-on' : '');
      h.style.left = `${st.pos * 100}%`;
      h.style.background = st.colour;
      h.title = `${Math.round(st.pos * 1000) / 10}% ${st.colour}`;
      h.addEventListener('pointerdown', (e) => startDrag(e, st));
      h.addEventListener('keydown', (e) => keys(e, st));
      return h;
    }));
    const on = Boolean(selected);
    colour.disabled = position.disabled = !on;
    remove.disabled = !on || stops.length <= 2;
    if (on) {
      colour.value = selected.colour;
      position.value = String(Math.round(selected.pos * 1000) / 10);
    }
  }

  function posFromEvent(e) {
    const box = bar.getBoundingClientRect();
    return Math.min(1, Math.max(0, (e.clientX - box.left) / box.width));
  }

  function startDrag(e, st) {
    e.preventDefault();
    selected = st;
    render();                     // ручки пересозданы: тащим уже новую
    const live = handles.querySelector('.lwarp__stop.is-on');
    live.focus();
    const move = (ev) => {
      st.pos = Math.round(posFromEvent(ev) * 1000) / 1000;
      live.style.left = `${st.pos * 100}%`;
      position.value = String(Math.round(st.pos * 1000) / 10);
      drawBar();                  // полоса тянется за точкой сразу
      onChange();
    };
    let done = false;
    const up = () => {
      if (done) return;
      done = true;
      live.removeEventListener('pointermove', move);
      render();
      handles.querySelector('.lwarp__stop.is-on')?.focus();
    };
    live.setPointerCapture(e.pointerId);
    live.addEventListener('pointermove', move);
    // На тач-экране жест может отмениться - ручка не должна «прилипнуть»
    for (const end of ['pointerup', 'pointercancel', 'lostpointercapture']) {
      live.addEventListener(end, up, { once: true });
    }
  }

  function keys(e, st) {
    // Фокус клавиатурой (Tab) - тоже выбор: поля и стрелки про эту точку
    selected = st;
    if ((e.key === 'Delete' || e.key === 'Backspace') && stops.length > 2) {
      stops = stops.filter((x) => x !== st);
      selected = null;
      changed();
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault();
      st.pos = Math.min(1, Math.max(0, st.pos + (e.key === 'ArrowLeft' ? -0.01 : 0.01)));
      changed();
      handles.querySelector('.lwarp__stop.is-on')?.focus();
    }
  }

  bar.addEventListener('pointerdown', (e) => {
    if (stops.length >= maxStops) return;
    const pos = Math.round(posFromEvent(e) * 1000) / 1000;
    selected = { pos, colour: rgbHex(colourAt(stops, pos)) };
    stops.push(selected);
    changed();
  });
  colour.addEventListener('input', () => {
    if (!selected) return;
    selected.colour = colour.value;
    changed();
  });
  position.addEventListener('change', () => {
    if (!selected) return;
    const value = Number(position.value);
    if (Number.isFinite(value)) selected.pos = Math.min(100, Math.max(0, value)) / 100;
    changed();
  });
  remove.addEventListener('click', () => {
    if (!selected || stops.length <= 2) return;
    stops = stops.filter((x) => x !== selected);
    selected = null;
    changed();
  });

  return {
    node,
    set(list) {
      stops = list.map(([pos, c]) => ({ pos: Number(pos), colour: c }));
      selected = null;
      render();
    },
    get: () => sorted().map((st) => [st.pos, st.colour]),
  };
}

/**
 * Блок конструктора. `schema` - material_map_schema().lightwarp,
 * `saved` - сохранённые параметры или null, `onChange` - человек что-то
 * поменял (окно карт включает карту и обновляет строку списка).
 * Возвращает { node, params(), setEnabled(bool) }.
 */
export function lightwarpEditor(schema, saved, onChange = () => {}) {
  const L = schema.labels;
  const T = schema.tips || {};             // подсказки при наведении
  const values = { ...schema.defaults, ...(saved || {}) };
  const node = document.createElement('div');
  node.className = 'lwarp';

  const grid = document.createElement('div');
  grid.className = 'mapcard__params lwarp__grid';
  const cell = (label, ...controls) => {
    const box = document.createElement('label');
    box.className = 'mapcard__cell';
    const text = document.createElement('span');
    text.className = 'label label--inline';
    text.textContent = label;
    box.append(text, ...controls);
    grid.append(box);
    return box;
  };
  const range = (key, min, max) => {
    const el = document.createElement('input');
    el.type = 'range';
    el.className = 'slider lwarp__range';
    el.min = String(min);
    el.max = String(max);
    el.value = String(values[key]);
    return el;
  };
  const color = (key) => {
    const el = document.createElement('input');
    el.type = 'color';
    el.className = 'lwarp__color';
    el.value = values[key];
    return el;
  };

  const presetBox = document.createElement('div');
  presetBox.className = 'select';
  const preset = document.createElement('select');
  for (const p of schema.presets) preset.append(new Option(p.label, p.id));
  preset.value = values.preset;
  presetBox.append(preset);

  // «Сделать точками»: текущая полоска со всеми настройками - в редактор
  const toPoints = document.createElement('button');
  toPoints.type = 'button';
  toPoints.className = 'textbtn textbtn--sm';
  toPoints.textContent = L.to_points;

  const steps = range('steps', 0, schema.max_steps);
  const stepsOut = document.createElement('span');
  stepsOut.className = 'mono lwarp__value';
  const shadowColor = color('shadow_color');
  const shadow = range('shadow', 0, 100);
  const lightColor = color('light_color');
  const light = range('light', 0, 100);
  const brightness = range('brightness', 50, 150);
  const brightnessOut = document.createElement('span');
  brightnessOut.className = 'mono lwarp__value';

  const presetRow = document.createElement('div');
  presetRow.className = 'mapcard__cell lwarp__preset';
  const presetText = document.createElement('span');
  presetText.className = 'label label--inline';
  presetText.textContent = L.preset;
  presetRow.append(presetText, presetBox, toPoints);
  presetRow.title = T.preset || '';

  const editor = stopsEditor(L, schema.max_stops, () => { refresh(); onChange(); });
  editor.set(values.stops || schema.defaults.stops);

  cell(L.steps, steps, stepsOut).title = T.steps || '';
  cell(L.brightness, brightness, brightnessOut).title = T.brightness || '';
  const shadowCell = cell(L.shadow, shadowColor, shadow);
  shadowCell.title = T.shadow || '';
  const lightCell = cell(L.light, lightColor, light);
  lightCell.title = T.light || '';

  const view = document.createElement('div');
  view.className = 'lwarp__view';
  const strip = document.createElement('canvas');
  strip.className = 'lwarp__strip';
  strip.width = 256;
  strip.height = 1;
  const graph = document.createElement('canvas');
  graph.className = 'lwarp__graph';
  graph.width = 256;
  graph.height = 64;
  const graphNote = document.createElement('p');
  graphNote.className = 'mapcard__tip lwarp__note';
  graphNote.textContent = L.graph_hint;
  // Два шара рядом: «как было» и «как будет» - разница видна сразу, а не
  // по памяти. Свет и материал у них одни
  const figure = (caption) => {
    const fig = document.createElement('figure');
    fig.className = 'lwarp__fig';
    const canvas = document.createElement('canvas');
    canvas.className = 'lwarp__sphere';
    canvas.width = canvas.height = 120;
    const cap = document.createElement('figcaption');
    cap.className = 'label label--inline';
    cap.textContent = caption;
    fig.append(canvas, cap);
    return [fig, canvas];
  };
  const [beforeFig, before] = figure(L.before);
  const [afterFig, sphere] = figure(L.after);
  beforeFig.title = T.before || '';
  afterFig.title = T.after || '';
  strip.title = T.strip || '';
  graph.title = T.graph || '';
  drawSphere(before, null);
  const spheres = document.createElement('div');
  spheres.className = 'lwarp__spheres';
  spheres.append(beforeFig, afterFig);
  const note = document.createElement('p');
  note.className = 'mapcard__tip lwarp__note';
  note.textContent = `${L.preview} ${L.hint}`;
  const stripBox = document.createElement('div');
  stripBox.className = 'lwarp__stripbox';
  stripBox.append(strip, graph, graphNote);
  view.append(spheres, stripBox);

  // Сверху то, что меняют (основа, точки), под ним результат, ниже ползунки:
  // двигая ползунок, видишь шары, а не прокручиваешь к ним
  node.append(presetRow, editor.node, view, grid, note);

  const isCustom = () => preset.value === schema.custom;
  const params = () => ({
    preset: preset.value,
    steps: Number(steps.value),
    shadow_color: shadowColor.value,
    shadow: Number(shadow.value),
    light_color: lightColor.value,
    light: Number(light.value),
    brightness: Number(brightness.value),
    // Точки уходят всегда: переключились на основу игры и обратно - свои
    // точки на месте, и в сохранённой работе тоже
    stops: editor.get(),
  });

  // Ответы приходят не по порядку: рисуем только последний запрос
  let ticket = 0;
  let timer = null;
  function refresh() {
    editor.node.hidden = !isCustom();
    toPoints.hidden = isCustom();
    // В своём градиенте цвет задают точки - оттенки поверх лишние
    shadowCell.hidden = lightCell.hidden = isCustom();
    stepsOut.textContent = Number(steps.value) < 2 ? L.smooth : steps.value;
    brightnessOut.textContent = brightness.value;
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const mine = ++ticket;
      const res = await api.lightwarpRamp(params());
      if (mine !== ticket || !res || !res.ramp) return;
      drawStrip(strip, res.ramp);
      drawGraph(graph, res.ramp);
      drawSphere(sphere, res.ramp);
    }, 40);
  }
  for (const el of [preset, steps, shadowColor, shadow, lightColor, light, brightness]) {
    el.addEventListener('input', () => { refresh(); onChange(); });
  }
  toPoints.addEventListener('click', async () => {
    // Свежий расчёт, а не ответ прошлого запроса: ползунок могли двинуть
    // только что, и в точки ушла бы старая полоска
    const res = await api.lightwarpRamp(params());
    if (!res || !res.stops) return;
    // Настройки уже «впечены» в точки: сбрасываем их, иначе легли бы дважды
    editor.set(res.stops);
    preset.value = schema.custom;
    steps.value = '0';
    shadow.value = '0';
    light.value = '0';
    brightness.value = '100';
    refresh();
    onChange();
  });
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
