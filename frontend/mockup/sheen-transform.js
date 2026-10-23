/*
 * Рамка картинки на превью конструктора блеска: как в редакторах картинок
 *
 * Тянуть за середину - двигать, за угол - менять размер, за кружок над
 * рамкой - поворачивать (с Shift - шагом 15°), колесо - размер. Пока тянут,
 * меняется только рамка: кадры маски считает Python (около секунды), и они
 * пересчитываются после отпускания мыши
 *
 * Геометрия та же, что у sheen_builder._picture: «целиком» - вписать
 * картинку в бок оружия с её пропорцией, «растянуть» - на весь бок, потом
 * размер, поворот по часовой и центр в долях длины и высоты.
 */

import * as api from './api.js';
import { t } from './i18n.js';

const SVG = 'http://www.w3.org/2000/svg';
//: Пределы - как у полей слоя (sheen_builder.LAYER_TYPES["image"])
const SCALE = [0.1, 2];
const HANDLE = 5;
const ARM = 18;

const svgEl = (name, attrs = {}) => {
  const node = document.createElementNS(SVG, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
};

/**
 * `stage` - сцена превью, `canvas` - плитка. `onCommit()` - правка
 * закончена: пересчитать кадры и свойства слоя.
 */
export function createTransform(stage, canvas, pattern, { onCommit }) {
  const svg = svgEl('svg', { class: 'sheenb__xform' });
  const box = svgEl('polygon', { class: 'sheenb__xbox' });
  const arm = svgEl('line', { class: 'sheenb__xarm' });
  const spin = svgEl('circle', { class: 'sheenb__xspin', r: HANDLE });
  const corners = [0, 1, 2, 3].map(() => svgEl('rect', {
    class: 'sheenb__xcorner', width: HANDLE * 2, height: HANDLE * 2 }));
  box.append(svgEl('title'));
  box.firstChild.textContent = t('Тяните - двигать, колесо - размер');
  spin.append(svgEl('title'));
  spin.firstChild.textContent = t('Повернуть (Shift - шагом 15°)');
  svg.append(box, arm, spin, ...corners);
  stage.append(svg);

  //: Пропорции картинок: путь -> {w, h}; грузятся один раз
  const sizes = new Map();
  function natural(path) {
    if (!sizes.has(path)) {
      sizes.set(path, null);
      const img = new Image();
      img.onload = () => sizes.set(path, { w: img.naturalWidth, h: img.naturalHeight });
      img.src = api.fileUrl(path, true);
    }
    return sizes.get(path);
  }

  const layer = () => {
    const l = pattern.layers[pattern.selected];
    return l && l.type === 'image' && l.image && l.on ? l : null;
  };

  /** Центр, полуоси и угол рамки в пикселях плитки */
  function geometry(l) {
    const W = canvas.clientWidth;
    const H = canvas.clientHeight;
    const nat = natural(l.image);
    if (!W || !H || !nat) return null;
    let bw = W;
    let bh = H;
    if (l.fit !== 'stretch') {
      const k = Math.min(W / nat.w, H / nat.h);
      bw = nat.w * k;
      bh = nat.h * k;
    }
    const s = Number(l.scale) || 1;
    return { cx: l.pos_x * W, cy: l.pos_y * H, hw: bw * s / 2, hh: bh * s / 2,
             a: (Number(l.rot) || 0) * Math.PI / 180, W, H };
  }

  const turn = (g, x, y) => [g.cx + x * Math.cos(g.a) - y * Math.sin(g.a),
                             g.cy + x * Math.sin(g.a) + y * Math.cos(g.a)];

  /** Рамка по слою, зовётся каждый кадр проигрывателя - дёшево */
  function sync() {
    const l = drag ? drag.layer : layer();
    const g = l && geometry(l);
    svg.style.display = g ? '' : 'none';
    if (!g) return;
    Object.assign(svg.style, { left: `${canvas.offsetLeft}px`, top: `${canvas.offsetTop}px`,
                               width: `${g.W}px`, height: `${g.H}px` });
    const pts = [[-g.hw, -g.hh], [g.hw, -g.hh], [g.hw, g.hh], [-g.hw, g.hh]]
      .map(([x, y]) => turn(g, x, y));
    box.setAttribute('points', pts.map((p) => p.join(',')).join(' '));
    pts.forEach(([x, y], i) => {
      corners[i].setAttribute('x', x - HANDLE);
      corners[i].setAttribute('y', y - HANDLE);
    });
    const [tx, ty] = turn(g, 0, -g.hh);
    const [sx, sy] = turn(g, 0, -g.hh - ARM);
    arm.setAttribute('x1', tx); arm.setAttribute('y1', ty);
    arm.setAttribute('x2', sx); arm.setAttribute('y2', sy);
    spin.setAttribute('cx', sx); spin.setAttribute('cy', sy);
  }

  // Мышь
  let drag = null;
  const local = (e) => {
    const r = svg.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  };
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

  function start(kind, e) {
    const l = layer();
    const g = l && geometry(l);
    if (!g) return;
    e.preventDefault();
    e.stopPropagation();
    const [x, y] = local(e);
    drag = { kind, layer: l, g, x, y, pos: [l.pos_x, l.pos_y],
             scale: Number(l.scale) || 1, rot: Number(l.rot) || 0 };
    svg.setPointerCapture(e.pointerId);
  }
  box.addEventListener('pointerdown', (e) => start('move', e));
  spin.addEventListener('pointerdown', (e) => start('rotate', e));
  corners.forEach((c) => c.addEventListener('pointerdown', (e) => start('scale', e)));

  svg.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const [x, y] = local(e);
    const { g, layer: l } = drag;
    if (drag.kind === 'move') {
      l.pos_x = clamp(drag.pos[0] + (x - drag.x) / g.W, 0, 1);
      l.pos_y = clamp(drag.pos[1] + (y - drag.y) / g.H, 0, 1);
    } else if (drag.kind === 'scale') {
      const was = Math.hypot(drag.x - g.cx, drag.y - g.cy) || 1;
      l.scale = clamp(drag.scale * Math.hypot(x - g.cx, y - g.cy) / was, ...SCALE);
    } else {
      const d = Math.atan2(y - g.cy, x - g.cx) - Math.atan2(drag.y - g.cy, drag.x - g.cx);
      let rot = drag.rot + d * 180 / Math.PI;
      if (e.shiftKey) rot = Math.round(rot / 15) * 15;
      l.rot = Math.round(((rot + 540) % 360) - 180);
    }
    sync();
  });
  const finish = () => {
    if (!drag) return;
    drag = null;
    onCommit();
  };
  svg.addEventListener('pointerup', finish);
  svg.addEventListener('pointercancel', finish);

  // Колесо над рамкой - размер, одна правка после паузы, а не на каждый щелчок
  let wheelTimer = null;
  box.addEventListener('wheel', (e) => {
    const l = layer();
    if (!l) return;
    e.preventDefault();
    l.scale = clamp((Number(l.scale) || 1) * (e.deltaY < 0 ? 1.08 : 1 / 1.08), ...SCALE);
    sync();
    clearTimeout(wheelTimer);
    wheelTimer = setTimeout(onCommit, 250);
  }, { passive: false });

  return { sync };
}
