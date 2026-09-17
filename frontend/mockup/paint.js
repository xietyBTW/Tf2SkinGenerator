/*
 * Краска из игры в превью шапки.
 *
 * Две трети косметики красится по альфа-маске текстуры: что именно
 * закрасится у своей текстуры, автор иначе видит только в игре. Кнопка у
 * команд открывает банки игры; выбор красит и карточки, и модель — решает
 * Python (view_state), страница применяет ответ, как у команд.
 */

import * as api from './api.js';
import { applyView } from './preview.js';

const button = document.getElementById('paint');
const box = document.getElementById('paints');
//: Банки: [{key, name, red, blu}], один раз за сеанс.
let list = null;
//: Ключ выбранной банки — из ответа Python (см. syncPaint).
let chosen = '';

/** Точка цвета на кнопке: видно, что превью покрашено, не открывая список. */
export function syncPaint(st) {
  chosen = st.paint || '';
  const dot = button.querySelector('.paint__dot');
  // Краска выбрана до того, как список спросили (Python помнит её между
  // перезагрузками страницы): цвет точки узнаём и возвращаемся.
  if (chosen && !list) {
    api.paints().then((got) => { list = got; syncPaint(st); });
    return;
  }
  const paint = (list || []).find((p) => p.key === chosen);
  dot.hidden = !chosen;
  if (paint) {
    dot.style.setProperty('--c', paint.red);
    dot.style.setProperty('--c2', paint.blu);
  }
  button.classList.toggle('is-active', Boolean(chosen));
}

function close() {
  if (box.matches(':popover-open')) box.hidePopover();
  document.removeEventListener('mousedown', onAway, true);
  document.removeEventListener('keydown', onKey, true);
}
const onAway = (e) => { if (!box.contains(e.target) && e.target !== button) close(); };
const onKey = (e) => { if (e.key === 'Escape') close(); };

async function pick(key) {
  close();
  applyView(await api.setPaint(key));
}

async function open() {
  if (box.matches(':popover-open')) { close(); return; }
  if (!list) list = await api.paints();
  box.innerHTML = '';
  const none = document.createElement('button');
  none.type = 'button';
  none.className = 'textbtn textbtn--sm paints__none' + (chosen ? '' : ' is-active');
  none.textContent = 'Без краски';
  none.addEventListener('click', () => pick(''));
  box.append(none);
  const grid = document.createElement('div');
  grid.className = 'paints__grid';
  for (const p of list) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'swatch' + (p.key === chosen ? ' is-active' : '');
    b.title = p.name;
    b.style.setProperty('--c', p.red);
    b.style.setProperty('--c2', p.blu);
    b.addEventListener('click', () => pick(p.key));
    grid.append(b);
  }
  box.append(grid);
  box.showPopover();
  // Под кнопкой, правым краем к ней: кнопка у правого края экрана.
  const at = button.getBoundingClientRect();
  const size = box.getBoundingClientRect();
  box.style.top = (at.bottom + 8) + 'px';
  box.style.left = Math.max(8, at.right - size.width) + 'px';
  document.addEventListener('mousedown', onAway, true);
  document.addEventListener('keydown', onKey, true);
}

button.addEventListener('click', open);
