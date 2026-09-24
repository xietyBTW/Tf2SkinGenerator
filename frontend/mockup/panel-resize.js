/*
 * Ширина боковых панелей: их тянут за внутренний край.
 *
 * Делить экран между кадром и панелями человек должен сам: у одного предмета
 * важнее картинка, у другого — длинные имена в каталоге или три десятка
 * крутилок, которые в 280 точках режутся многоточием.
 *
 *   каталог слева   — за правый край, `--lw`, конфиг `catalog_width`;
 *   сборка справа   — за левый край,  `--bw`, конфиг `build_width`;
 *   частицы справа  — за левый край,  `--pw`, конфиг `params_width`.
 *
 * Сборка и частицы стоят на одном месте, но ширины у них свои: крутилкам
 * эффекта нужно куда больше места, чем флагам VTF.
 *
 * Ширина живёт в CSS-переменной, а между запусками — в общем конфиге.
 * localStorage не годится: страницу отдаёт локальный сервер на СЛУЧАЙНОМ
 * порту (frontend/app.py), и origin у каждого запуска свой.
 */

import * as api from './api.js';

const root = document.documentElement;

//: Полоса захвата у края. Внутри неё только отступ — попасть по полю или
//: карточке вместо края нельзя.
const GRIP = 8;
//: Уже этого панель не читается, а кадру (средней колонке) оставляем хотя бы
//: столько — с учётом ВТОРОЙ панели, а не только ширины окна.
const MIN = 200;
const KEEP = 320;

/** Ставит ширину из конфига. 0 — край не трогали, ширину задаёт CSS. */
function setWidth(cssVar, px) {
  const want = Number(px) || 0;
  if (want >= MIN) root.style.setProperty(cssVar, `${want}px`);
  else root.style.removeProperty(cssVar);
}

export const setParamsWidth = (px) => setWidth('--pw', px);
export const setCatalogWidth = (px) => setWidth('--lw', px);
export const setBuildWidth = (px) => setWidth('--bw', px);

/** Ширина кадра — колонки сцены, которая не боковая панель. У прибитых
 *  панелей колонок три (кадр в середине), у частиц в плавающем — две. */
function frameWidth(stage) {
  const cols = getComputedStyle(stage).gridTemplateColumns.split(' ').map(parseFloat);
  return cols.length === 3 ? cols[1] : cols[0];
}

/**
 * Делает край панели перетаскиваемым.
 *
 * `edge` — какой край тянут: 'left' у правых панелей, 'right' у левой.
 * Тянуть можно, только пока панель — колонка: плавающие накладки
 * (`position: fixed`) растягивать некуда.
 */
function resizable(panel, { edge, cssVar, key }) {
  if (!panel) return;
  const gripClass = `is-grip--${edge}`;
  const isColumn = () => getComputedStyle(panel).position !== 'fixed';
  const atGrip = (e) => {
    if (!isColumn()) return false;
    const r = panel.getBoundingClientRect();
    return edge === 'left' ? e.clientX - r.left < GRIP : r.right - e.clientX < GRIP;
  };
  let drag = null;              // {x, w} на момент нажатия, пока тянут

  panel.addEventListener('pointerdown', (e) => {
    // Только левая кнопка: правой на панелях открывают контекстное меню.
    if (e.button !== 0 || !atGrip(e)) return;
    const w = panel.getBoundingClientRect().width;
    // Расти можно только за счёт кадра: сколько в нём сверх KEEP.
    drag = { x: e.clientX, w, max: w + Math.max(0, frameWidth(panel.parentElement) - KEEP) };
    panel.setPointerCapture(e.pointerId);
    e.preventDefault();               // иначе тянется выделение текста
  });

  panel.addEventListener('pointermove', (e) => {
    if (!drag) {
      panel.classList.toggle(gripClass, atGrip(e));
      return;
    }
    // Правую панель тянут ВЛЕВО, чтобы расширить, — разность наоборот.
    const delta = edge === 'left' ? drag.x - e.clientX : e.clientX - drag.x;
    const want = Math.round(Math.min(Math.max(MIN, drag.max), Math.max(MIN, drag.w + delta)));
    root.style.setProperty(cssVar, `${want}px`);
  });

  panel.addEventListener('pointerleave', () => {
    if (!drag) panel.classList.remove(gripClass);
  });

  for (const done of ['pointerup', 'pointercancel']) {
    panel.addEventListener(done, () => {
      // Пишем на ОТПУСКАНИИ, а не по ходу тяги: перетаскивание даёт сотню
      // событий, и конфиг переписывался бы сотню раз на одно движение.
      if (drag) api.setUiState(key, parseInt(root.style.getPropertyValue(cssVar), 10) || 0);
      drag = null;
    });
  }
}

resizable(document.getElementById('catalog'),
          { edge: 'right', cssVar: '--lw', key: 'catalog_width' });
resizable(document.getElementById('build'),
          { edge: 'left', cssVar: '--bw', key: 'build_width' });
resizable(document.getElementById('pbuild'),
          { edge: 'left', cssVar: '--pw', key: 'params_width' });
