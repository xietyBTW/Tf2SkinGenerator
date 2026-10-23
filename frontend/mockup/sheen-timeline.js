/*
 * Карточка «Время прохода» конструктора блеска: шкала секунд и полосы слоёв,
 * которые тянут мышью (середина - сдвиг, края - начало и конец).
 */

import { t } from './i18n.js';
import { el, card, glyph, fillCss } from './sheen-ui.js';

/**
 * `pattern` - SheenPattern. `onSelect(i)` - щелчок по имени слоя,
 * `onChanged()` - полосу отпустили, `onSeek(f)` - перемотка в долю прохода,
 * отдаёт false, пока кадров нет.
 */
export function createTimeline(pattern, { onSelect, onChanged, onSeek }) {
  const timeCard = card(t('Время прохода'));
  timeCard.head.append(el('span', 'sheenb__hint', t('Тяните полосы и их края, щелчок по шкале - перемотка')));
  const ruler = el('div', 'sheenb__ruler');
  ruler.title = t('Щёлкните или тяните, чтобы перемотать');
  const lanes = el('div', 'sheenb__lanes');
  const playhead = el('div', 'sheenb__playhead');
  timeCard.content.append(ruler, lanes);

  function renderRuler() {
    const track = el('div', 'sheenb__rulertrack');
    for (let s = 0; s <= pattern.length + 1e-6; s += 0.5) {
      const whole = Math.abs(s - Math.round(s)) < 1e-6;
      const tick = el('span', 'sheenb__tick' + (whole ? ' is-major' : ''),
        whole ? t(`${Math.round(s)} с`) : '');
      tick.style.left = `${(s / pattern.length) * 100}%`;
      track.append(tick);
    }
    ruler.replaceChildren(el('span', 'sheenb__tlname'), track);
  }

  function render() {
    const rows = pattern.layers.map((layer, i) => {
      const row = el('div', 'sheenb__tlrow' + (i === pattern.selected ? ' is-active' : ''));
      const label = el('span', 'sheenb__tlname');
      label.append(glyph(layer.type), el('span', '', pattern.layerName(i)));
      label.addEventListener('click', () => onSelect(i));
      row.append(label);
      const track = el('div', 'sheenb__track');
      const bar = el('div', 'sheenb__span' + (layer.on ? '' : ' is-off'));
      bar.style.background = fillCss(layer);
      const place = () => {
        bar.style.left = `${layer.start * 100}%`;
        bar.style.width = `${(layer.end - layer.start) * 100}%`;
      };
      place();
      const lh = el('span', 'sheenb__handle sheenb__handle--l');
      const rh = el('span', 'sheenb__handle sheenb__handle--r');
      bar.append(lh, rh);
      track.append(bar);
      row.append(track);
      // Тянуть: середина - сдвиг, края - начало и конец
      const drag = (mode) => (e) => {
        e.preventDefault();
        e.stopPropagation();
        // Выбор - без перерисовки: она отцепила бы полосу, которую тянут
        // (ширина 0, слой улетал к краю). Список обновится в конце жеста
        pattern.selected = i;
        const box = track.getBoundingClientRect();
        if (!box.width) return;
        const x0 = e.clientX;
        const a0 = layer.start;
        const b0 = layer.end;
        const move = (ev) => {
          const d = (ev.clientX - x0) / box.width;
          const minLen = 0.03;
          if (mode === 'l') layer.start = Math.min(b0 - minLen, Math.max(0, a0 + d));
          else if (mode === 'r') layer.end = Math.max(a0 + minLen, Math.min(1, b0 + d));
          else {
            const len = b0 - a0;
            layer.start = Math.min(1 - len, Math.max(0, a0 + d));
            layer.end = layer.start + len;
          }
          place();
        };
        const up = () => {
          window.removeEventListener('pointermove', move);
          window.removeEventListener('pointerup', up);
          onChanged();
        };
        window.addEventListener('pointermove', move);
        window.addEventListener('pointerup', up);
      };
      bar.addEventListener('pointerdown', drag('m'));
      lh.addEventListener('pointerdown', drag('l'));
      rh.addEventListener('pointerdown', drag('r'));
      return row;
    });
    lanes.replaceChildren(...rows, playhead);
  }

  // Перемотка: щелчок или протяжка по шкале ставит время и паузу
  ruler.addEventListener('pointerdown', (e) => {
    const track = ruler.querySelector('.sheenb__rulertrack');
    if (!track) return;
    const at = (ev) => {
      const box = track.getBoundingClientRect();
      return Math.min(1, Math.max(0, (ev.clientX - box.left) / box.width));
    };
    if (!onSeek(at(e))) return;
    e.preventDefault();
    const seek = (ev) => onSeek(at(ev));
    const up = () => {
      window.removeEventListener('pointermove', seek);
      window.removeEventListener('pointerup', up);
    };
    window.addEventListener('pointermove', seek);
    window.addEventListener('pointerup', up);
  });

  /** Бегунок прохода: `pos` 0..1, меньше нуля - спрятать */
  function showPlayhead(pos) {
    playhead.hidden = pos < 0;
    if (pos >= 0) playhead.style.left = `calc(var(--tl-name) + (100% - var(--tl-name)) * ${pos})`;
  }

  return { box: timeCard.box, render, renderRuler, showPlayhead };
}
