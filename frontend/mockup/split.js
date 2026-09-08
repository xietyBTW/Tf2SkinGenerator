/*
 * Граница между половинами работы: её тянут мышью.
 *
 * В режиме «Вместе» слева текстуры, справа модель (или эффект), и делили они
 * ширину поровну. Пополам подходит не всякой работе: у развёртки с четырьмя
 * материалами карточки жмутся в колонку, пока половина модели стоит пустой,
 * а модель, наоборот, разглядывают крупно.
 *
 * Своей разметки у границы нет — тянут за зазор сетки (`gap`), в котором и
 * так никого нет. Курсор над ним меняется на `col-resize`: это и есть
 * приглашение, отдельная полоска рисовала бы то, что уже видно.
 *
 * Доля левой половины живёт в `--split` (единицы `fr`, поэтому пропорция
 * переживает изменение размера окна), а между запусками — в общем конфиге
 * (`split_percent`), как ширина панели частиц (см. particles/resize.js).
 */

import * as api from './api.js';

const work = document.querySelector('.work');
const flat = work.querySelector('.half--flat');
const model = work.querySelector('.half--model');

//: Полоса захвата по обе стороны от границы.
const GRIP = 10;
//: Уже этого половина бесполезна: в ней не помещается ни карточка, ни модель.
const MIN = 15;
const MAX = 85;

//: Пока не null — тянут (само значение не нужно, важен сам факт).
let drag = null;

/** Ширина зазора сетки. Меряем, а не берём константой: на разных порогах своя. */
const gap = () => model.getBoundingClientRect().left - flat.getBoundingClientRect().right;

/**
 * Середина зазора, либо null — тянуть нечего.
 *
 * Половины стоят рядом только в режиме «Вместе» и только в широком окне: ниже
 * 1100px они ложатся друг под друга, и зазор между ними уже не вертикальный.
 */
function line() {
  if (work.dataset.view !== 'both') return null;
  const g = gap();
  return g > 0 ? flat.getBoundingClientRect().right + g / 2 : null;
}

const atGrip = (e) => {
  const x = line();
  return x !== null && Math.abs(e.clientX - x) <= GRIP;
};

/** Ставит долю левой половины в процентах. 0 — границу не трогали, поровну. */
export function setSplit(percent) {
  const p = Number(percent) || 0;
  if (!p) { work.style.removeProperty('--split'); return; }
  const share = Math.min(MAX, Math.max(MIN, p));
  // Левая колонка получает столько же долей, во сколько раз она больше правой.
  work.style.setProperty('--split', `${share / (100 - share)}fr`);
}

/** Доля левой половины под курсором, в процентах. */
function shareAt(clientX) {
  const box = work.getBoundingClientRect();
  const g = gap();
  // Курсор держит СЕРЕДИНУ зазора, поэтому половина зазора вычитается: иначе
  // граница уезжала бы от него на 15 точек.
  const left = clientX - box.left - g / 2;
  return Math.round((left / (box.width - g)) * 100);
}

work.addEventListener('pointerdown', (e) => {
  // Только левая кнопка: правой на половинах открывают контекстные меню.
  if (e.button !== 0 || !atGrip(e)) return;
  drag = true;
  work.setPointerCapture(e.pointerId);
  e.preventDefault();               // иначе тянется выделение текста
});

work.addEventListener('pointermove', (e) => {
  if (!drag) {
    work.classList.toggle('is-split', atGrip(e));
    return;
  }
  setSplit(Math.min(MAX, Math.max(MIN, shareAt(e.clientX))));
});

work.addEventListener('pointerleave', () => {
  if (!drag) work.classList.remove('is-split');
});

for (const done of ['pointerup', 'pointercancel']) {
  work.addEventListener(done, (e) => {
    // Пишем на ОТПУСКАНИИ: перетаскивание даёт сотню событий, и конфиг
    // переписывался бы сотню раз на одно движение.
    if (drag) {
      api.setUiState('split_percent',
                     Math.min(MAX, Math.max(MIN, shareAt(e.clientX))));
    }
    drag = null;
  });
}
