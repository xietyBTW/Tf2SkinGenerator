/*
 * Альбом текстур: вкладки, стрелки и прокрутка — три входа в одно.
 *
 * Какой кадр перед глазами, определяется ОДИН раз по положению прокрутки,
 * остальное его отражает. Содержимое приходит от воркера и пересобирается на
 * каждой модели, поэтому список кадров перечитывается в bindAlbum, а не
 * берётся один раз.
 *
 * Обвязку кадра (перетаскивание, шестерёнка, выход из стиля) даёт app.js —
 * альбом про неё не знает, его дело показать нужный кадр.
 */

import * as api from './api.js';
import { root } from './layout.js';
import { enterTextureEdit } from './controls.js';
import { bindDrop, applyView } from './preview.js';

// ── Альбом текстур ───────────────────────────────────────────────────────
// Вкладки, стрелки и прокрутка — три входа в одно: какой кадр перед глазами.
// Текущий кадр определяется ОДИН раз по положению прокрутки, остальное его
// отражает.
//
// Содержимое приходит от воркера и пересобирается на каждой модели, поэтому
// списки кадров и вкладок перечитываются в bindAlbum, а не берутся один раз.

const album = document.querySelector('.album');
const albumCount = document.querySelector('.album__count b');
const stepPrev = document.querySelector('.album__step--prev');
const stepNext = document.querySelector('.album__step--next');
let frames = [];
let tabs = [];

export function currentIndex() {
  const mid = album.scrollLeft + album.clientWidth / 2;
  let best = 0, bestDist = Infinity;
  frames.forEach((f, i) => {
    const dist = Math.abs(f.offsetLeft + f.offsetWidth / 2 - mid);
    if (dist < bestDist) { bestDist = dist; best = i; }
  });
  return best;
}

export function sync(index) {
  const i = index ?? currentIndex();
  frames.forEach((f, n) => f.classList.toggle('is-current', n === i));
  tabs.forEach((t, n) => t.classList.toggle('is-active', n === i));
  albumCount.textContent = frames.length
    ? `${String(i + 1).padStart(2, '0')} / ${String(frames.length).padStart(2, '0')}`
    : '—';
  // Стрелку, которой некуда вести, не показываем: на одной текстуре их не
  // должно быть вовсе, а на краю списка щелчок по ней молча ничего не делал бы.
  stepPrev.hidden = i <= 0;
  stepNext.hidden = i >= frames.length - 1;
}

export function goTo(i) {
  const at = Math.max(0, Math.min(frames.length - 1, i));
  const f = frames[at];
  if (!f) return;
  album.scrollTo({ left: f.offsetLeft + f.offsetWidth / 2 - album.clientWidth / 2 });
  // Отмечаем сразу: при плавной прокрутке событие придёт через сотни
  // миллисекунд, и всё это время активной была бы чужая вкладка.
  sync(at);
}

/** Перечитывает содержимое альбома и вешает обработчики на свежие элементы. */
export function bindAlbum() {
  frames = [...album.querySelectorAll('.frame')];
  tabs = [...document.querySelectorAll('.mattab')];
  tabs.forEach((tab, i) => tab.addEventListener('click', () => goTo(i)));
  frames.forEach((f, i) => {
    f.addEventListener('click', () => goTo(i));
    // У эффекта своя обработка перетаскивания (другой метод замены), и
    // вешать обе значило бы отправить файл дважды по разным путям.
    if (root.dataset.section !== 'particles') bindDrop(f);
    const gear = f.querySelector('.frame__tool');
    if (gear) gear.addEventListener('click', (e) => {
      e.stopPropagation();
      enterTextureEdit(f.dataset.mat);
    });
    // Материал, добавленный в стиль, из него же и убирается — иначе стиль
    // становится ловушкой: добавил лишнее и живи с этим.
    const drop = f.querySelector('.frame__off');
    if (drop) drop.addEventListener('click', async (e) => {
      e.stopPropagation();
      applyView(await api.dropFromStyle(f.dataset.mat));
    });
  });
  sync(0);
}

album.addEventListener('scroll', () => {
  clearTimeout(album._t);
  album._t = setTimeout(sync, 60);
});

// Колесо мыши листает вбок — как _HWheelScrollArea в приложении.
album.addEventListener('wheel', (e) => {
  if (e.deltaX) return;                 // горизонтальный жест трекпада не трогаем
  e.preventDefault();
  album.scrollLeft += e.deltaY;
}, { passive: false });

stepPrev.addEventListener('click', () => goTo(currentIndex() - 1));
stepNext.addEventListener('click', () => goTo(currentIndex() + 1));
bindAlbum();

export //: Служебный ключ одноматериальной модели (SINGLE_TEX_KEY в домене). Именем
//: меша он не является — во вьювер его отдавать нельзя.
const SINGLE_TEX = '__single__';

/** Материал, к которому относится правка: тот, что сейчас в альбоме. */
export function currentMaterial() {
  const frame = frames[currentIndex()];
  const mat = frame && frame.dataset.mat;
  // Служебный ключ одноматериальной модели наружу не отдаём: пустая строка
  // означает «главный материал», и Python сам его подставит.
  return !mat || mat === SINGLE_TEX ? '' : mat;
}
