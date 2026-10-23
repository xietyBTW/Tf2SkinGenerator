/*
 * Движение списков: проявление лесенкой, перестановка с места на место и
 * вспышка изменившейся строки
 *
 * Общее для каталога и звуков - второй копии этих приёмов быть не должно.
 * Сами кадры - в style-motion.css; здесь только кому и когда. Без анимаций
 * (настройка или системное «меньше движения») всё ставится сразу.
 */

const root = document.documentElement;

/** Анимации выключены - настройкой или системой */
export const still = () => root.dataset.motion === 'off'
  || matchMedia('(prefers-reduced-motion: reduce)').matches;

//: Сколько первых узлов идут лесенкой: дальше задержка уже не видна, а
//: список в сотни строк иначе проявлялся бы секундами
const STAIRS = 24;
//: За сколько проходит вся лесенка, сколько бы узлов ни было: шаг 22 мс на
//: тридцати карточках тянул проявление почти на секунду, и его принимали за
//: медленную загрузку иконок
const CASCADE_MS = 180;

/** Узлы проявляются по очереди (класс `is-arrive`, задержка по --k).
 *  `limit` - сколько первых узлов вообще анимировать: у длинного списка
 *  остальные за краем окна. Задержка растёт только до STAIRS, дальше узлы
 *  проявляются вместе с последней ступенькой - но проявляются, а не стоят */
export function staggerIn(nodes, limit = STAIRS) {
  if (still()) return;
  const list = [...nodes].slice(0, limit);
  const step = Math.min(22, CASCADE_MS / Math.max(1, Math.min(list.length, STAIRS)));
  list.forEach((node, k) => {
    node.style.setProperty('--k', Math.min(k, STAIRS));
    node.style.setProperty('--step', `${step}ms`);
    node.classList.add('is-arrive');
    node.addEventListener('animationend', () => node.classList.remove('is-arrive'),
                          { once: true });
  });
}

/**
 * Перерисовка списка с переездом: карточки, что были и остались, плывут со
 * старого места на новое (FLIP), новые проявляются лесенкой
 *
 * `render` пересобирает содержимое `box` целиком, узнаём карточки по
 * `data-flip`. Меряем только видимые в окне списка: за его краем движения
 * не видно, а замер сотен карточек - лишняя работа.
 */
export function flipList(box, render) {
  if (still() || box.hidden) { render(); return; }
  // Видимая часть списка - по окну тоже: список бывает выше экрана
  const visibleIn = () => {
    const r = box.getBoundingClientRect();
    return [Math.max(r.top, 0), Math.min(r.bottom, innerHeight)];
  };
  let [top, bottom] = visibleIn();
  const before = new Map();
  for (const node of box.querySelectorAll('[data-flip]')) {
    const r = node.getBoundingClientRect();
    if (r.bottom < top || r.top > bottom) continue;
    before.set(node.dataset.flip, r);
  }
  render();
  if (box.hidden) return;
  // Рамку - заново: при смене раздела вёрстка над списком другая, и прежняя
  // рамка захватывала сотни карточек за краем
  [top, bottom] = visibleIn();
  const fresh = [];
  for (const node of box.querySelectorAll('[data-flip]')) {
    const r = node.getBoundingClientRect();
    if (r.bottom < top || r.top > bottom) continue;
    const was = before.get(node.dataset.flip);
    if (!was) { fresh.push(node); continue; }
    const dx = was.left - r.left;
    const dy = was.top - r.top;
    if (!dx && !dy) continue;
    node.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: 'none' }],
                 { duration: 420, easing: 'cubic-bezier(.2, .7, .2, 1)' });
  }
  // Здесь только видимые карточки: проявить надо все, сколько бы их ни было
  // на широком экране, иначе хвост ряда стоял бы, пока соседи ещё тают
  staggerIn(fresh, Infinity);
}

/** Короткая вспышка узла: его только что поменяли (класс `is-swapped`) */
export function flash(node) {
  if (still() || !node?.isConnected) return;
  node.classList.remove('is-swapped');
  void node.offsetWidth;            // перезапуск, если вспышка ещё идёт
  node.classList.add('is-swapped');
  node.addEventListener('animationend', () => node.classList.remove('is-swapped'),
                        { once: true });
}
