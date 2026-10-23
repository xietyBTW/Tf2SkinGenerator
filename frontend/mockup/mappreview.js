/*
 * Превью карточек «Phong-карта», «Rim light», «Отражение» и «Detail»
 *
 * Картинки собирает Python (Session.map_preview) так же, как сборка, а здесь
 * они смешиваются по формулам шейдера модели (source-sdk-2013, skin_ps20b.fxc,
 * common_vertexlitgeneric_dx9.h, common_ps_fxc.h):
 *
 *   блик    = (L·R)^k · N·L · маска · $phongboost · ranges(френель);
 *             k = 1 + 149 · R Phong-карты (R читается без гаммы)
 *   обводка = max(блик, (L·R)^$rimlightexponent · N·L · маска · (1 − N·V)^4)
 *             + окружение · $rimlightboost · (маска · (1 − N·V)^4 · N.z)
 *   отражение = кубмапа(отражённый взгляд) · $envmaptint · маска
 *             · lerp(1, ranges(френель), $envmapfresnel)
 *   detail  = TextureCombine: 0 - база · lerp(1, 2·деталь, f) (деталь без
 *             гаммы), 1 - база + f · деталь, 2 - lerp(база, деталь, f · альфа
 *             детали), 5 - освещённое + f · деталь, координаты × $detailscale
 *
 * Геометрия своя: шар или текстура, согнутая как ствол (нормаль меняется
 * поперёк). Свет один, окружение ровное - так видно, что меняет поле.
 */

import * as api from './api.js';
import { ALBEDO, AMBIENT, toSrgb } from './lightwarp.js';
import { RANGES, fresnelRanges } from './phongwarp.js';

export const toLinear = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const SPEC_EXPONENT = 20;          // блик шара обводки: у материала свой, здесь средний
const BEND = 0.9;                  // «ствол»: нормаль от −0.9 до 0.9 рад поперёк текстуры

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** Картинка -> ImageData (null, если не загрузилась) */
export function load(url) {
  return new Promise((resolve) => {
    if (!url) { resolve(null); return; }
    const img = new Image();
    img.onload = () => {
      const c = document.createElement('canvas');
      c.width = img.naturalWidth;
      c.height = img.naturalHeight;
      const ctx = c.getContext('2d');
      ctx.drawImage(img, 0, 0);
      resolve(ctx.getImageData(0, 0, c.width, c.height));
    };
    img.onerror = () => resolve(null);
    img.src = url;
  });
}

/** Источник карты из состояния карточки - то, что пойдёт в сборку */
export function sourceSpec(st) {
  if (st.source === 'auto') return { derive: true, threshold: String(st.threshold || '') };
  if (st.source === 'mod') return { mod: true };
  if (st.source === 'file' && st.image) return { image: st.image };
  return null;
}

const channel = (img, c = 0) => {
  if (!img) return null;
  const out = new Float32Array(img.width * img.height);
  for (let i = 0; i < out.length; i++) out[i] = img.data[i * 4 + c] / 255;
  return out;
};

/** Картинки превью по `spec`; перезапрашивает, когда spec меняется */
function loader(material, mapId) {
  let data = null;
  let key = null;
  let busy = false;
  async function fetch(spec) {
    const res = await api.mapPreview(material, mapId, spec);
    if (!res || res.error) return null;
    const [tex, map, mask, env, mapAlpha] = await Promise.all([
      load(res.texture ? api.fileUrl(res.texture) : ''), load(res.map ? api.fileUrl(res.map) : ''),
      load(res.mask ? api.fileUrl(res.mask) : ''), load(res.env ? api.fileUrl(res.env) : ''),
      load(res.map_alpha ? api.fileUrl(res.map_alpha) : '')]);
    // Без текстуры материала (не загружена) - только шары
    const n = tex ? tex.width * tex.height : 0;
    const albedo = tex ? new Float32Array(n * 3) : null;
    for (let i = 0; i < n; i++) {
      for (let c = 0; c < 3; c++) albedo[i * 3 + c] = toLinear(tex.data[i * 4 + c] / 255);
    }
    let cube = null;
    if (env) {
      const lin = new Float32Array(env.width * env.height * 3);
      for (let i = 0; i < env.width * env.height; i++) {
        for (let c = 0; c < 3; c++) lin[i * 3 + c] = toLinear(env.data[i * 4 + c] / 255);
      }
      cube = { lin, size: env.height, stride: env.width };
    }
    return { w: tex ? tex.width : 0, h: tex ? tex.height : 0, albedo, map, mask: channel(mask), mapAlpha: channel(mapAlpha), cube,
             standIn: Boolean(res.stand_in) };
  }
  return {
    get busy() { return busy; },
    get(spec) {
      const k = JSON.stringify(spec);
      if (k !== key && !busy) {
        key = k;
        if (!spec) data = null;
        else {
          busy = true;
          fetch(spec).then((d) => { data = d; busy = false; }, () => { data = null; busy = false; });
        }
      }
      return data;
    },
  };
}

/** Кубмапа в направлении (x, y, z) мира Source (Z вверх), линейный цвет.
 * Грани как в VTF: +X −X +Y −Y +Z −Z, раскладка D3D (проверено по швам) */
function cubeAt(cube, x, y, z) {
  const ax = Math.abs(x); const ay = Math.abs(y); const az = Math.abs(z);
  let f; let sc; let tc; let ma;
  if (ax >= ay && ax >= az) [f, sc, tc, ma] = x > 0 ? [0, -z, -y, ax] : [1, z, -y, ax];
  else if (ay >= az) [f, sc, tc, ma] = y > 0 ? [2, x, z, ay] : [3, x, -z, ay];
  else [f, sc, tc, ma] = z > 0 ? [4, x, -y, az] : [5, -x, -y, az];
  const s = cube.size;
  const u = Math.min(s - 1, Math.floor(((sc / ma + 1) / 2) * s));
  const v = Math.min(s - 1, Math.floor(((tc / ma + 1) / 2) * s));
  const at = (v * cube.stride + f * s + u) * 3;
  return [cube.lin[at], cube.lin[at + 1], cube.lin[at + 2]];
}

/** Отражённый взгляд (вид: x вправо, y вверх, z к зрителю) -> мир Source,
 * окружение повёрнуто вокруг вертикали на `turn`. Зритель смотрит вдоль +X */
function reflectWorld(n, turn) {
  const d = 2 * n[2];
  const r = [d * n[0], d * n[1], d * n[2] - 1];
  const wx = -r[2]; const wy = -r[0]; const wz = r[1];
  const c = Math.cos(turn); const s = Math.sin(turn);
  return [wx * c - wy * s, wx * s + wy * c, wz];
}

const normalize = (v) => { const l = Math.hypot(...v); return v.map((c) => c / l); };
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const hexLinear = (hex) => [1, 3, 5].map((i) => toLinear(parseInt(hex.slice(i, i + 2), 16) / 255));
const num = (value, fallback) => {
  const v = parseFloat(value);
  return Number.isFinite(v) ? v : fallback;
};

/** Шар: `shade(n, i)` -> линейный RGB точки с нормалью n */
function drawSphere(canvas, shade) {
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
      const rgb = shade([x, y, Math.sqrt(1 - rr)]);
      const at = (py * size + px) * 4;
      for (let c = 0; c < 3; c++) img.data[at + c] = Math.round(255 * toSrgb(Math.min(1, rgb[c])));
      img.data[at + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
}

/** Текстура, согнутая как ствол: `shade(n, i)` -> линейный RGB текселя i.
 * `tilt` - изгиб ещё и вдоль (рад): отражение берёт не только горизонт */
function drawBent(canvas, w, h, shade, tilt = 0) {
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  const img = ctx.createImageData(w, h);
  const normals = [];
  for (let x = 0; x < w; x++) {
    const a = ((x + 0.5) / w - 0.5) * 2 * BEND;
    normals.push([Math.sin(a), 0, Math.cos(a)]);
  }
  for (let y = 0; y < h; y++) {
    const b = (0.5 - (y + 0.5) / h) * 2 * tilt;
    const row = normals.map((n) => normalize([n[0], Math.sin(b), n[2] * Math.cos(b)]));
    for (let x = 0; x < w; x++) {
      const i = y * w + x;
      const rgb = shade(row[x], i);
      for (let c = 0; c < 3; c++) img.data[i * 4 + c] = Math.round(255 * toSrgb(Math.min(1, rgb[c])));
      img.data[i * 4 + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
}

/** Блик (L·R)^k при взгляде (0, 0, 1) */
const phong = (n, light, k) => Math.max(0, 2 * dot(n, light) * n[2] - light[2]) ** k;

function figure(caption, tip, className = 'glow__img') {
  const fig = el('figure', 'lwarp__fig');
  const canvas = el('canvas', className);
  fig.append(canvas, el('figcaption', 'label label--inline', caption));
  fig.title = tip || '';
  return [fig, canvas];
}

/** Обёртка превью: узел, кадр по таймеру, кадр сразу при показе */
function animated(node, frame, everyMs = 50) {
  let running = false;
  let last = 0;
  const tick = (now) => {
    if (!node.isConnected || document.hidden) { running = false; return; }
    if (now - last > everyMs) { last = now; frame(now); }
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

/** Phong-карта: размер блика (R) на согнутой текстуре, свет ходит */
function glossPreview(st, ui, material) {
  const node = el('div', 'glow');
  const row = el('div', 'glow__row');
  const [fig, canvas] = figure(ui.view_gloss, ui.view_gloss_tip);
  const [onlyFig, only] = figure(ui.view_gloss_only, ui.view_gloss_only_tip);
  row.append(fig, onlyFig);
  const empty = el('p', 'mapcard__tip', ui.view_none);
  node.append(row, empty);
  const data = loader(material, 'phongexp');
  return animated(node, (now) => {
    const spec = sourceSpec(st);
    const d = data.get(spec);
    row.hidden = !(d && d.map && d.albedo);
    empty.textContent = spec && d && !d.albedo ? ui.view_no_texture : ui.view_none;
    empty.hidden = !row.hidden || data.busy;
    if (row.hidden) return;
    const a = 1.1 * Math.sin((now / 5000) * Math.PI * 2);
    const light = normalize([Math.sin(a), 0.3, Math.cos(a)]);
    const boost = num(st.numbers.$phongboost, 2);
    const red = d.map.data;
    const specs = new Float32Array(d.w * d.h);
    drawBent(canvas, d.w, d.h, (n, i) => {
      const nl = dot(n, light);
      const diffuse = AMBIENT + (0.5 * nl + 0.5) ** 2;
      const k = 1 + 149 * (red[i * 4] / 255);
      const mask = d.mask ? d.mask[i] : 1;
      const spec = phong(n, light, k) * Math.max(0, nl) * mask * boost
                   * fresnelRanges((1 - n[2]) ** 2);
      specs[i] = spec;
      return [0, 1, 2].map((c) => d.albedo[i * 3 + c] * diffuse + spec);
    });
    drawBent(only, d.w, d.h, (n, i) => [specs[i], specs[i], specs[i]]);
  }, 66);
}

/** Rim light: шар, свет обходит его кругом - обводка видна, когда он сзади */
function rimPreview(st, ui, material) {
  const node = el('div', 'glow');
  const row = el('div', 'glow__row');
  const [sphereFig, sphere] = figure(ui.view_rim, ui.view_rim_tip, 'lwarp__sphere');
  sphere.width = sphere.height = 120;
  const [maskFig, maskCanvas] = figure(ui.view_mask, ui.view_mask_tip);
  row.append(sphereFig, maskFig);
  node.append(row);
  const data = loader(material, 'rimlight');
  let shownMask = null;
  return animated(node, (now) => {
    const mode = st.settings.rim_mask;
    const spec = mode === 'auto' ? { derive: true, threshold: String(st.settings.rim_threshold ?? '') }
      : (mode === 'file' && st.settings.rim_image ? { image: st.settings.rim_image } : null);
    const d = data.get(spec);
    maskFig.hidden = !(spec && d && d.map);
    if (!maskFig.hidden && shownMask !== d.map) {
      shownMask = d.map;
      maskCanvas.width = d.map.width;
      maskCanvas.height = d.map.height;
      maskCanvas.getContext('2d').putImageData(d.map, 0, 0);
    }
    const a = (now / 6000) * Math.PI * 2;
    const light = normalize([Math.sin(a), 0.25, Math.cos(a)]);
    const rimExp = num(st.numbers.$rimlightexponent, 4);
    const rimBoost = num(st.numbers.$rimlightboost, 2);
    drawSphere(sphere, (n) => {
      const nl = dot(n, light);
      const lr = Math.max(0, 2 * nl * n[2] - light[2]);
      const lit = Math.max(0, nl);
      const fres = (1 - n[2]) ** 2;
      const spec = lr ** SPEC_EXPONENT * lit * fresnelRanges(fres, RANGES);
      const rimMul = fres * fres;                         // (1 − N·V)^4, маска = 1
      let s = Math.max(spec, lr ** rimExp * lit * rimMul);
      s += AMBIENT * rimBoost * Math.max(0, Math.min(1, rimMul * n[1]));   // N.z мира = вверх
      const diffuse = ALBEDO * (AMBIENT + (0.5 * nl + 0.5) ** 2);
      return [diffuse + s, diffuse + s, diffuse + s];
    });
  }, 40);
}

/** Отражение: окружение на шаре и где оно легло на текстуру по маске */
function envPreview(st, ui, material) {
  const node = el('div', 'glow');
  const row = el('div', 'glow__row');
  const [sphereFig, sphere] = figure(ui.view_env, ui.view_env_tip, 'lwarp__sphere');
  sphere.width = sphere.height = 120;
  const [texFig, tex] = figure(ui.view_env_tex, ui.view_env_tex_tip);
  row.append(sphereFig, texFig);
  const note = el('p', 'mapcard__tip');
  node.append(row, note);
  const data = loader(material, 'envmapmask');
  return animated(node, (now) => {
    const spec = { ...(sourceSpec(st) || {}), cubemap: st.settings.env_cubemap || 'keep' };
    const d = data.get(spec);
    row.hidden = !(d && d.cube);
    note.textContent = !d ? '' : (!d.cube ? ui.view_no_game : (d.standIn ? ui.view_stand_in : ''));
    note.hidden = !note.textContent;
    if (row.hidden) return;
    const s = st.settings;
    const strength = num(s.env_strength, 100) / 100;
    const tint = hexLinear(s.env_tint || '#ffffff').map((c) => c * strength);
    const fresnel = num(s.env_fresnel, 0) / 100;
    const turn = (now / 20000) * Math.PI * 2;
    const env = (n, mask) => {
      const k = mask * (1 + (fresnelRanges((1 - n[2]) ** 2) - 1) * fresnel);
      const e = d.cube ? cubeAt(d.cube, ...reflectWorld(n, turn)) : [0, 0, 0];
      return [0, 1, 2].map((c) => e[c] * tint[c] * k);
    };
    const light = normalize([-0.5, 0.5, 0.7]);
    drawSphere(sphere, (n) => {
      const diffuse = ALBEDO * (AMBIENT + (0.5 * dot(n, light) + 0.5) ** 2);
      return env(n, 1).map((v) => diffuse + v);
    });
    texFig.hidden = !(d.map && d.albedo);
    if (texFig.hidden) return;
    drawBent(tex, d.w, d.h, (n, i) => {
      const diffuse = AMBIENT + (0.5 * dot(n, light) + 0.5) ** 2;
      const e = env(n, d.map.data[i * 4] / 255);
      return [0, 1, 2].map((c) => d.albedo[i * 3 + c] * diffuse + e[c]);
    }, 0.6);
  }, 66);
}

/** Detail: деталь поверх текстуры по режиму и плотности, на ровном свету */
function detailPreview(st, ui, material) {
  const node = el('div', 'glow');
  const [fig, canvas] = figure(ui.view_detail, ui.view_detail_tip);
  const empty = el('p', 'mapcard__tip', ui.view_none);
  node.append(fig, empty);
  const data = loader(material, 'detail');
  let drawn = '';
  let drawnData = null;
  return animated(node, () => {
    const spec = sourceSpec(st);
    const d = data.get(spec);
    fig.hidden = !(d && d.map && d.albedo);
    empty.textContent = spec && d && !d.albedo ? ui.view_no_texture : ui.view_none;
    empty.hidden = !fig.hidden || data.busy;
    if (fig.hidden) return;
    const scale = Math.max(0.01, num(st.numbers.$detailscale, 8));
    const mode = String(st.numbers.$detailblendmode ?? '0');
    const f = num(st.numbers.$detailblendfactor, 1);
    const key = JSON.stringify([spec, scale, mode, f, d.w]);
    // Данные тоже: пока шёл запрос, могли нарисоваться прошлые
    if (key === drawn && d === drawnData) return;
    drawn = key;
    drawnData = d;
    const det = d.map;
    canvas.width = d.w;
    canvas.height = d.h;
    const ctx = canvas.getContext('2d');
    const img = ctx.createImageData(d.w, d.h);
    for (let y = 0; y < d.h; y++) {
      for (let x = 0; x < d.w; x++) {
        const i = y * d.w + x;
        // Координаты детали = координаты базы × $detailscale, с повтором
        const u = (((x + 0.5) / d.w) * scale) % 1;
        const v = (((y + 0.5) / d.h) * scale) % 1;
        const at = (Math.floor(v * det.height) * det.width + Math.floor(u * det.width)) * 4;
        const raw = [det.data[at] / 255, det.data[at + 1] / 255, det.data[at + 2] / 255];
        const alpha = d.mapAlpha ? d.mapAlpha[at / 4] : 1;
        for (let c = 0; c < 3; c++) {
          const base = d.albedo[i * 3 + c];
          let out;
          if (mode === '0') out = base * (1 + (2 * raw[c] - 1) * f);       // деталь без гаммы
          else if (mode === '2') out = base + (toLinear(raw[c]) - base) * f * alpha;
          else out = base + f * toLinear(raw[c]);                         // 1 и 5
          img.data[i * 4 + c] = Math.round(255 * toSrgb(Math.min(1, Math.max(0, out))));
        }
        img.data[i * 4 + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
  }, 120);
}

const VIEWS = { gloss: glossPreview, rim: rimPreview, env: envPreview, detail: detailPreview };

/** Превью карточки по её `preview` или null */
export function mapPreview(st, schema, material) {
  const make = VIEWS[st.spec.preview];
  return make ? make(st, schema.ui, material) : null;
}
