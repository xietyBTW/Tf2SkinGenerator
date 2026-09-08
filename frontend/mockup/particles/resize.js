/*
 * Ширина панели параметров: её тянут за левый край.
 *
 * Эффект правят, ГЛЯДЯ на него, и делить экран между кадром и крутилками
 * человек должен сам: у одной системы важнее картинка, у другой — три
 * десятка полей, которые в 280 точках не помещаются и режутся многоточием.
 *
 * Выбранная ширина живёт в CSS-переменной `--pw`, а между запусками — в общем
 * конфиге (`params_width`), как и закрепление панелей. localStorage не годится:
 * страницу отдаёт локальный сервер на СЛУЧАЙНОМ порту (frontend/app.py), и
 * origin у каждого запуска свой.
 */

import * as api from '../api.js';

const panel = document.getElementById('pbuild');
const root = document.documentElement;

//: Полоса захвата у левого края панели. Внутри неё только отступ — попасть
//: по крутилке вместо края нельзя.
const GRIP = 8;
//: Уже этого панель не читается, а кадру оставляем хотя бы столько.
const MIN = 200;
const KEEP = 320;

//: Пока не null — тянут: {x, w} на момент нажатия.
let drag = null;

/** Панель сейчас колонка справа, а не шторка снизу (узкое окно). */
const isColumn = () => getComputedStyle(panel).position !== 'fixed';

const atGrip = (e) => isColumn() && e.clientX - panel.getBoundingClientRect().left < GRIP;

/** Ставит сохранённую ширину. 0 — край не трогали, ширину задаёт CSS. */
export function setParamsWidth(px) {
  const want = Number(px) || 0;
  if (want >= MIN) root.style.setProperty('--pw', `${want}px`);
  else root.style.removeProperty('--pw');
}

panel.addEventListener('pointerdown', (e) => {
  // Только левая кнопка: правой на панели открывают контекстное меню.
  if (e.button !== 0 || !atGrip(e)) return;
  drag = { x: e.clientX, w: panel.getBoundingClientRect().width };
  panel.setPointerCapture(e.pointerId);
  e.preventDefault();               // иначе тянется выделение текста
});

panel.addEventListener('pointermove', (e) => {
  if (!drag) {
    panel.classList.toggle('is-grip', atGrip(e));
    return;
  }
  // Тянут ВЛЕВО — панель растёт, поэтому разность взята наоборот.
  const max = Math.max(MIN, window.innerWidth - KEEP);
  const want = drag.w + drag.x - e.clientX;
  root.style.setProperty('--pw', `${Math.min(max, Math.max(MIN, want))}px`);
});

panel.addEventListener('pointerleave', () => {
  if (!drag) panel.classList.remove('is-grip');
});

for (const done of ['pointerup', 'pointercancel']) {
  panel.addEventListener(done, () => {
    // Пишем на ОТПУСКАНИИ, а не по ходу тяги: перетаскивание даёт сотню
    // событий, и конфиг переписывался бы сотню раз на одно движение.
    if (drag) api.setUiState('params_width', parseInt(root.style.getPropertyValue('--pw'), 10) || 0);
    drag = null;
  });
}
