/*
 * Общие кирпичики конструктора блеска (sheen-builder.js): узлы, кнопки,
 * карточки, значки слоёв, CSS-фон слоя и циферблат угла.
 */

import * as api from './api.js';
import { t } from './i18n.js';

//: Значки слоёв - простые линии, цвет берут от текста
const GLYPHS = {
  stripe: '<path d="M5 18 9 4M10 18 14 4M15 18 19 4"/>',
  flash: '<circle cx="12" cy="12" r="4"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/>',
  sparkle: '<path d="M12 3v18M3 12h18M7 7l10 10M17 7 7 17" stroke-width="1"/><circle cx="12" cy="12" r="2"/>',
  clouds: '<path d="M7 17h10a4 4 0 0 0 0-8 5 5 0 0 0-9.6 1.5A3.3 3.3 0 0 0 7 17z"/>',
  image: '<rect x="3" y="5" width="18" height="14" rx="1"/><path d="m3 16 5-5 4 4 3-3 6 6"/><circle cx="16" cy="9" r="1.5"/>',
};

export function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function glyph(kind) {
  const span = el('span', 'sheenb__glyph');
  span.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" `
    + `stroke-linecap="round" stroke-linejoin="round">${GLYPHS[kind] || ''}</svg>`;
  return span;
}

export const button = (text, className = 'textbtn textbtn--sm', title = '') => {
  const b = el('button', className, text);
  b.type = 'button';
  if (title) b.title = title;
  return b;
};

/** Карточка: заголовок (и действия справа) над содержимым */
export function card(title, ...actions) {
  const box = el('section', 'sheenb__card');
  const head = el('div', 'sheenb__cardhead');
  head.append(el('h3', 'sheenb__cardtitle', title), ...actions);
  const content = el('div', 'sheenb__cardbody');
  box.append(head, content);
  return { box, head, content };
}

export const clone = (v) => JSON.parse(JSON.stringify(v));

/** CSS-фон слоя: один цвет, градиент или сама картинка (для образца и шкалы времени) */
export function fillCss(layer) {
  if (layer.fill === 'image') {
    return layer.image ? `center / cover no-repeat url("${api.fileUrl(layer.image, true)}")` : '#888';
  }
  if (!layer.fill || layer.fill === 'solid' || !layer.stops) return layer.color;
  const stops = layer.stops.map(([pos, c]) => `${c} ${Math.round(pos * 100)}%`).join(', ');
  // У CSS 0° - вверх, у узора 0° - вправо (к дулу)
  const deg = layer.fill === 'space' ? (Number(layer.gangle) || 0) + 90 : 90;
  return `linear-gradient(${deg}deg, ${stops})`;
}

/**
 * Циферблат направления: стрелку тянут мышью, шаг 15° (с Alt - любой угол),
 * число рядом - для точности. 0° - вдоль оружия к дулу, 90° - вниз, как на
 * плитке превью. `onInput` зовётся на каждое движение.
 */
export function angleDial(value, onInput) {
  const box = el('div', 'sheenb__dial');
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '-30 -30 60 60');
  svg.setAttribute('class', 'sheenb__dialsvg');
  svg.innerHTML = '<circle r="27" class="sheenb__dialring"/>'
    + [0, 90, 180, 270].map((a) => `<line x1="${23 * Math.cos(a * Math.PI / 180)}" `
      + `y1="${23 * Math.sin(a * Math.PI / 180)}" x2="${27 * Math.cos(a * Math.PI / 180)}" `
      + `y2="${27 * Math.sin(a * Math.PI / 180)}" class="sheenb__dialtick"/>`).join('')
    + '<g class="sheenb__dialarrow"><line x1="-14" y1="0" x2="16" y2="0"/>'
    + '<path d="M22 0 13 -6 13 6z"/></g><circle r="2.5" class="sheenb__dialhub"/>';
  const arrow = svg.querySelector('.sheenb__dialarrow');
  const num = Object.assign(el('input', 'input input--num sheenb__num'),
    { type: 'number', min: 0, max: 359, step: 1 });
  let angle = Number(value) || 0;
  const show = () => {
    arrow.setAttribute('transform', `rotate(${angle})`);
    num.value = String(Math.round(angle));
  };
  const set = (a) => {
    angle = ((Math.round(a) % 360) + 360) % 360;
    show();
    onInput(angle);
  };
  svg.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    const pick = (ev) => {
      const r = svg.getBoundingClientRect();
      const a = Math.atan2(ev.clientY - (r.top + r.height / 2), ev.clientX - (r.left + r.width / 2));
      const deg = (a * 180) / Math.PI;
      set(ev.altKey ? deg : Math.round(deg / 15) * 15);
    };
    pick(e);
    svg.setPointerCapture(e.pointerId);
    svg.addEventListener('pointermove', pick);
    const up = () => svg.removeEventListener('pointermove', pick);
    svg.addEventListener('pointerup', up, { once: true });
    svg.addEventListener('lostpointercapture', up, { once: true });
  });
  num.addEventListener('change', () => set(Number(num.value) || 0));
  box.title = t('Тяните стрелку: шаг 15°, с Alt - любой угол');
  show();
  box.append(svg, num);
  return box;
}
