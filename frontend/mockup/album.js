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
import { bindDrop, applyView, wearCard } from './preview.js';

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
//: Материал карточки, на которой стоял альбом. Переживает пересборку —
//: по нему в неё и возвращаются (см. bindAlbum).
let lastMat = '';

//: Куда листается альбом. Решает CSS (@container в style.css): в узкой
//: половине кадры стоят столбцом, и листать их вбок было бы враньём. Здесь
//: только СПРАШИВАЕМ направление — второй копии порога быть не должно.
const DOWN = { pos: 'scrollTop', off: 'offsetTop', size: 'offsetHeight',
               view: 'clientHeight', edge: 'top' };
const SIDE = { pos: 'scrollLeft', off: 'offsetLeft', size: 'offsetWidth',
               view: 'clientWidth', edge: 'left' };
const axis = () => (getComputedStyle(album).flexDirection === 'column' ? DOWN : SIDE);

export function currentIndex() {
  const a = axis();
  const mid = album[a.pos] + album[a.view] / 2;
  let best = 0, bestDist = Infinity;
  frames.forEach((f, i) => {
    const dist = Math.abs(f[a.off] + f[a.size] / 2 - mid);
    if (dist < bestDist) { bestDist = dist; best = i; }
  });
  return best;
}

/**
 * Кадр, ОТ которого шагают стрелка и колесо.
 *
 * По отметке, а не по прокрутке: пока идёт плавная прокрутка, положение ещё
 * старое, и второй щелчок подряд возвращал бы на тот же кадр.
 */
function stepFrom() {
  const at = frames.findIndex((f) => f.classList.contains('is-current'));
  return at < 0 ? currentIndex() : at;
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
  // Модель носит ту карточку, на которой остановились. Обычно карточка — это
  // материал, и надевать нечего; у масок маскировки девять текстур на один
  // меш головы, и без этого модель показывала бы одну и ту же (см. wearCard).
  if (frames[i]) {
    lastMat = frames[i].dataset.mat || '';
    wearCard(lastMat);
  }
}

export function goTo(i, smooth = true) {
  const at = Math.max(0, Math.min(frames.length - 1, i));
  const f = frames[at];
  if (!f) return;
  const a = axis();
  // `instant` перебивает `scroll-behavior: smooth` из стилей. Нужен там, где
  // альбом ВОССТАНАВЛИВАЮТ после пересборки: человек с места не уходил, и
  // проматывать ему кадры на глазах не за что.
  album.scrollTo({ [a.edge]: f[a.off] + f[a.size] / 2 - album[a.view] / 2,
                   behavior: smooth ? 'smooth' : 'instant' });
  // Отмечаем сразу: при плавной прокрутке событие придёт через сотни
  // миллисекунд, и всё это время активной была бы чужая вкладка.
  sync(at);
}

/** Перечитывает содержимое альбома и вешает обработчики на свежие элементы. */
export function bindAlbum() {
  // Куда вернуться. Альбом пересобирается на КАЖДЫЙ ответ Python (правка
  // текстуры, команда, стиль), и раньше он всегда вставал на первую карточку:
  // поправил шестую текстуру — смотришь на первую и ищешь, где был.
  const want = lastMat;
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

  if (!frames.length) {
    // Альбом опустел — сменился предмет (clearPreview). Прошлая карточка к
    // новому отношения не имеет, иначе тёзка-материал утащил бы не туда.
    lastMat = '';
    sync(0);
    return;
  }
  // Карточки могло не остаться (другой предмет, другой стиль) — тогда сначала.
  const at = frames.findIndex((f) => f.dataset.mat === want);
  goTo(at < 0 ? 0 : at, false);
}

album.addEventListener('scroll', () => {
  clearTimeout(album._t);
  album._t = setTimeout(sync, 60);
});

//: Когда колесу можно листать снова. Трекпад шлёт события пачкой по два
//: десятка на одно движение пальцами — без задержки альбом пролетал бы
//: насквозь, и человек терял место.
let wheelAfter = 0;

// Колесо листает КАДРАМИ, а не точками. Прежде оно двигало прокрутку на
// величину прожига (`scrollLeft += deltaY`), и это не работало: кадр почти во
// всю рамку, сотня точек внутри него ничего не меняет, а `scroll-snap:
// mandatory` возвращает прокрутку обратно — колесо выглядело сломанным.
// Направление спрашивать не надо: `goTo` листает по той оси, по которой стоят
// кадры.
album.addEventListener('wheel', (e) => {
  if (e.deltaX || !e.deltaY) return;         // горизонтальный жест трекпада не трогаем
  e.preventDefault();
  if (e.timeStamp < wheelAfter) return;
  wheelAfter = e.timeStamp + 220;
  goTo(stepFrom() + Math.sign(e.deltaY));
}, { passive: false });

stepPrev.addEventListener('click', () => goTo(stepFrom() - 1));
stepNext.addEventListener('click', () => goTo(stepFrom() + 1));
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
