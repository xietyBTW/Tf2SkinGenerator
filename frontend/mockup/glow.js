/*
 * Превью самосвечения: ваша текстура «на свету» и «в темноте»
 *
 * Формула шейдера (source-sdk-2013, skin_ps20b.fxc и
 * vertexlit_and_unlit_generic_bump_ps2x.fxc):
 *   цвет = lerp(текстура × свет, текстура × $selfillumtint, маска)
 * Свечение заменяет освещение, а не прибавляется, и от света сцены не
 * зависит - поэтому плоская картинка показывает его точно. $selfillumtint
 * движок берёт линейным (без перевода из гаммы), считаем в линейном цвете
 *
 * Пульсация - прокси Sine, как его считает игра:
 *   min + (max − min) · (sin(2π·t / период) · 0.5 + 0.5)
 *
 * «Затухание к краю» ($selfillumfresnel): вес = альфа основы ×
 * ((N·V)^exp · (1 − min/max) + min/max), яркость × max - от формы модели,
 * поэтому показан на шаре, на плоской картинке поверхность смотрит прямо на
 * зрителя (N·V = 1), и маской служит альфа основы, а не карта.
 */

import * as api from './api.js';
import { LIGHT, toSrgb } from './lightwarp.js';
import { load, sourceSpec as maskSpec, toLinear } from './mappreview.js';

const LIT = 1.0;          // освещение «на свету»
const DARK = 0.06;        // «в темноте»: почти ночь
const PERIODS = { slow: 3.0, medium: 1.5, fast: 0.6 };   // как в сборке

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/**
 * Блок превью для карточки «Самосвечение». `material` - карточка альбома.
 * Читает состояние `st` на каждом кадре: правки видны сразу, без перерисовки.
 */
export function glowPreview(st, schema, material) {
  const ui = schema.ui;
  const node = el('div', 'glow');
  node.title = ui.glow_tip || '';
  const figure = (caption) => {
    const fig = el('figure', 'lwarp__fig');
    const canvas = el('canvas', 'glow__img');
    fig.append(canvas, el('figcaption', 'label label--inline', caption));
    return [fig, canvas];
  };
  const [litFig, lit] = figure(ui.glow_lit);
  const [darkFig, dark] = figure(ui.glow_dark);
  const [fadeFig, fade] = figure(ui.glow_fade);
  fade.width = fade.height = 120;
  const empty = el('p', 'mapcard__tip', ui.glow_none);
  const row = el('div', 'glow__row');
  row.append(litFig, darkFig, fadeFig);
  node.append(row, empty);

  let data = null;           // {albedo: Float32Array RGB линейные, mask, alpha, w, h, avg}
  let loadedKey = null;
  let loading = false;

  async function fetchImages(spec) {
    loading = true;
    const res = await api.mapPreview(material, 'selfillum', spec);
    loading = false;
    if (!res || res.error) { data = null; return; }
    const [tex, mask, alpha] = await Promise.all([
      load(api.fileUrl(res.texture)), load(res.map ? api.fileUrl(res.map) : ''),
      load(api.fileUrl(res.alpha))]);
    if (!tex) { data = null; return; }
    const n = tex.width * tex.height;
    const albedo = new Float32Array(n * 3);
    const avg = [0, 0, 0];
    for (let i = 0; i < n; i++) {
      for (let c = 0; c < 3; c++) {
        const v = toLinear(tex.data[i * 4 + c] / 255);
        albedo[i * 3 + c] = v;
        avg[c] += v / n;
      }
    }
    const channel = (img) => {
      if (!img) return null;
      const out = new Float32Array(n);
      for (let i = 0; i < n; i++) out[i] = img.data[i * 4] / 255;
      return out;
    };
    data = { albedo, mask: channel(mask), alpha: channel(alpha), w: tex.width, h: tex.height, avg };
    for (const c of [lit, dark]) { c.width = tex.width; c.height = tex.height; }
  }

  /** Цвет свечения ($selfillumtint) в момент `now`: цвет × яркость × пульс */
  function tintAt(now) {
    const s = st.settings;
    const hex = s.glow_color || '#ffffff';
    const colour = [1, 3, 5].map((i) => toLinear(parseInt(hex.slice(i, i + 2), 16) / 255));
    const power = (parseFloat(s.glow_power) || 100) / 100;
    let pulse = 1;
    if (PERIODS[s.glow_pulse]) {
      const low = (s.glow_pulse_min === '' || s.glow_pulse_min === undefined
        ? 30 : parseFloat(s.glow_pulse_min)) / 100;
      pulse = low + (1 - low) * (Math.sin((2 * Math.PI * now) / 1000 / PERIODS[s.glow_pulse]) * 0.5 + 0.5);
    }
    return colour.map((c) => c * power * pulse);
  }

  function drawFlat(canvas, light, tint, fadeOn, bright) {
    const { albedo, w, h } = data;
    // При затухании маска - альфа основы (шейдер не читает карту), на
    // плоской картинке поверхность смотрит на зрителя: вес = альфа, яркость × max
    const mask = fadeOn ? data.alpha : data.mask;
    const k = fadeOn ? bright : 1;
    const ctx = canvas.getContext('2d');
    const img = ctx.createImageData(w, h);
    for (let i = 0; i < w * h; i++) {
      const m = mask ? mask[i] : 0;
      for (let c = 0; c < 3; c++) {
        const a = albedo[i * 3 + c];
        const v = a * light * (1 - m) + a * tint[c] * k * m;
        img.data[i * 4 + c] = Math.round(255 * toSrgb(Math.min(1, v)));
      }
      img.data[i * 4 + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
  }

  function drawFade(tint, bright, sharp) {
    const size = fade.width;
    const ctx = fade.getContext('2d');
    const img = ctx.createImageData(size, size);
    const half = size / 2;
    const albedo = data.avg;
    for (let py = 0; py < size; py++) {
      for (let px = 0; px < size; px++) {
        const x = (px + 0.5 - half) / half;
        const y = (half - py - 0.5) / half;
        const rr = x * x + y * y;
        if (rr > 1) continue;
        const n = [x, y, Math.sqrt(1 - rr)];
        const lambert = 0.5 * (n[0] * LIGHT[0] + n[1] * LIGHT[1] + n[2] * LIGHT[2]) + 0.5;
        // Шейдер: (N·V)^exp · (1 − min/max) + min/max; min = 0 - как в сборке
        const weight = Math.min(1, Math.max(0, n[2] ** sharp));
        const at = (py * size + px) * 4;
        for (let c = 0; c < 3; c++) {
          const litPart = albedo[c] * DARK * lambert * lambert;
          const v = litPart * (1 - weight) + albedo[c] * tint[c] * bright * weight;
          img.data[at + c] = Math.round(255 * toSrgb(Math.min(1, v)));
        }
        img.data[at + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
  }

  const frame = (now) => {
    const spec = maskSpec(st);
    const key = JSON.stringify(spec);
    if (key !== loadedKey && !loading) {
      loadedKey = key;
      if (spec) fetchImages(spec);
      else data = null;
    }
    const fadeOn = st.settings.glow_edge === 'on';
    row.hidden = !data;
    empty.hidden = Boolean(data) || loading;
    fadeFig.hidden = !fadeOn;
    if (!data) return;
    const tint = tintAt(now);
    const bright = parseFloat(st.settings.edge_bright) || 5;
    const sharp = parseFloat(st.settings.edge_sharp) || 8;
    drawFlat(lit, LIT, tint, fadeOn, bright);
    drawFlat(dark, DARK, tint, fadeOn, bright);
    if (fadeOn) drawFade(tint, bright, sharp);
  };

  let running = false;
  let last = 0;
  const tick = (now) => {
    if (!node.isConnected || document.hidden) { running = false; return; }
    // ~20 кадров в секунду: пульсации хватает, а 256×256 дважды - не даром
    if (now - last > 50) { last = now; frame(now); }
    requestAnimationFrame(tick);
  };
  return {
    node,
    start() {
      frame(performance.now());          // кадр сразу, даже в свёрнутом окне
      if (!running) { running = true; requestAnimationFrame(tick); }
    },
  };
}
