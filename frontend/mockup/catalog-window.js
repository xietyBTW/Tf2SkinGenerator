/*
 * Окно сетки каталога: в документе только ряды у экрана
 *
 * Косметики почти две тысячи. Полная сетка - около десяти тысяч узлов, и
 * каждая смена раздела или фильтра стоила ~185 мс до кадра, а сто двадцать
 * карточек - 15. Остальную высоту держат две распорки во всю ширину сетки,
 * поэтому полоса прокрутки та же, что у полного списка
 *
 * Карточки одной высоты: имя и подпись режутся многоточием, а обложка
 * квадратная. На этом держится расчёт рядов
 */

import { dropCovers } from './catalog-cover.js';

//: Запас над и под экраном. Тот же, что у загрузки иконок (scrollMargin в
//: catalog-cover.js): дальше запаса иконки всё равно не грузятся
const MARGIN_PX = 900;
//: Сколько карточек ставим, пока сетку не видно и мерить её нечем (каталог
//: закрыт). Откроется - ResizeObserver перестроит окно по настоящим размерам
const BLIND = 60;

let win = null;
const watched = new WeakSet();

/**
 * Показывает `items` в сетке `grid` окном
 *
 * `make(item)` строит карточку, сетку перед этим очищают (clearCovers). `at` -
 * куда прокрутить. Очищенная сетка уже потеряла высоту, и браузер сбросил бы
 * прокрутку сам, а при смене языка место в списке должно остаться
 */
export function showWindowed(grid, items, make, at = 0) {
  const top = pad();
  const bottom = pad();
  grid.append(top, bottom);
  win = { grid, items, make, top, bottom, cards: new Map(), key: '', rowH: 0, at,
          lastTop: at, hidden: false };
  if (!watched.has(grid)) {
    watched.add(grid);
    grid.addEventListener('scroll', () => {
      if (win && grid.clientHeight) win.lastTop = grid.scrollTop;
      render();
    }, { passive: true });
    // Ширина колонки меняет и число карточек в ряду, и их высоту: обложка
    // квадратная. Режим панели (прибитая или на весь экран) тоже сюда
    new ResizeObserver(() => { if (win) { win.rowH = 0; render(true); } }).observe(grid);
  }
  render(true);
}

/** Распорка во всю ширину сетки: держит высоту рядов, которых нет в документе */
function pad() {
  const el = document.createElement('div');
  el.className = 'catalog__pad';
  el.hidden = true;
  return el;
}

/** Ставит в документ ряды у экрана. `force` - пересчитать, даже если ряды те же */
function render(force = false) {
  const w = win;
  if (!w) return;
  // В сетку написал кто-то другой (дерево частиц, библиотека модов)
  if (!w.top.isConnected) { win = null; return; }
  const n = w.items.length;
  const { grid } = w;
  if (!grid.clientWidth) {
    // Каталог закрыли, например выбрав предмет. Окно оставляем как есть, а
    // место в списке вернём при открытии: скрытая сетка прокрутку теряет
    if (w.cards.size) { w.hidden = true; return; }
    place(0, Math.min(n, BLIND), 0, 0);
    return;
  }
  if (w.hidden) {
    w.hidden = false;
    w.at ??= w.lastTop;
    force = true;
  }

  const cs = getComputedStyle(grid);
  const cols = Math.max(1, cs.gridTemplateColumns.split(' ').filter(Boolean).length);
  const gap = parseFloat(cs.rowGap) || 0;
  if (!w.rowH) {
    // Высоту ряда берём у настоящей карточки: она зависит от ширины колонки
    if (!w.cards.size) place(0, Math.min(n, cols), 0, 0);
    const first = w.cards.values().next().value;
    // Дробная высота: целая из offsetHeight набегала бы на тысяче рядов
    w.rowH = first ? first.getBoundingClientRect().height : 0;
    if (!w.rowH) return;
  }
  const pitch = w.rowH + gap;
  const rows = Math.ceil(n / cols);
  const extra = Math.ceil(MARGIN_PX / pitch);
  const firstRow = Math.floor((w.at ?? grid.scrollTop) / pitch);
  const a = Math.max(0, firstRow - extra);
  const b = Math.min(rows, firstRow + Math.ceil(grid.clientHeight / pitch) + 1 + extra);
  const key = `${a}:${b}:${cols}`;
  if (!force && key === w.key) return;
  w.key = key;
  // Распорка - сама ряд сетки, после неё ещё один промежуток: его вычитаем
  place(a * cols, Math.min(n, b * cols), a ? a * pitch - gap : 0,
        b < rows ? (rows - b) * pitch - gap : 0);
  if (w.at != null) {
    grid.scrollTop = w.at;
    w.at = null;
  }
}

/**
 * Оставляет в документе карточки с номерами [from, to)
 *
 * Те, что остаются, не трогаем: переставленная кнопка теряет фокус и
 * наведение, а картинка в ней - место в очереди загрузки
 */
function place(from, to, topPx, bottomPx) {
  const w = win;
  for (const [i, node] of w.cards) {
    if (i >= from && i < to) continue;
    dropCovers(node);
    node.remove();
    w.cards.delete(i);
  }
  // Оставшиеся идут подряд, новые встают перед ними или после
  const keptFrom = w.cards.size ? Math.min(...w.cards.keys()) : to;
  const head = [];
  const tail = [];
  for (let i = from; i < to; i++) {
    if (w.cards.has(i)) continue;
    const node = w.make(w.items[i]);
    w.cards.set(i, node);
    (i < keptFrom ? head : tail).push(node);
  }
  w.top.after(...head);
  w.bottom.before(...tail);
  setPad(w.top, topPx);
  setPad(w.bottom, bottomPx);
}

function setPad(el, px) {
  el.hidden = px <= 0;
  el.style.height = `${Math.max(0, px)}px`;
}
