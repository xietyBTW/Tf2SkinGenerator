/*
 * Кадр: то, что стоит между альбомом текстур и двумя iframe.
 *
 * Вьювер моделей и движок частиц живут в своих документах, и обращаться к ним
 * можно только когда iframe загрузился, — отсюда `withViewer`/`withParticles`
 * вместо прямого вызова. Модуль ничего не знает ни о предмете, ни об эффекте:
 * он про сам кадр.
 */

export const stage = {
  hint: document.getElementById('stagehint'),
  tabs: document.querySelector('.mattabs'),
  album: document.querySelector('.album'),
  frame: document.getElementById('viewer'),
  pframe: document.getElementById('particles'),
};

//: Через сколько показывать сообщение о РАБОТЕ. Быстрая загрузка успевает
//: закончиться раньше — дорожки анимации из кэша приезжают примерно за 300 мс,
//: и подпись при них не появляется вовсе. Ловится именно мигание: сообщение,
//: висящее полсекунды, читается хуже, чем его отсутствие.
const BUSY_DELAY = 400;
//: А если уже показали — держим столько. Иначе сообщение, появившееся на
//: 401-й миллисекунде, моргнуло бы заметнее, чем если бы задержки не было.
const BUSY_KEEP = 500;
//: Сколько держать сообщение о сделанном или об ошибке. Ошибку читают, а не
//: отмечают краем глаза, поэтому не три секунды и не две.
const DONE_KEEP = 6000;

let busyTimer = null;    // отложенный показ
let holdTimer = null;    // отложенная уборка
let busyText = '';       // что покажем, когда таймер сработает
let shownAt = 0;         // когда подпись появилась; 0 — её нет

function put(text) {
  stage.hint.textContent = text;
  stage.hint.hidden = !text;
  shownAt = text ? Date.now() : 0;
}

/** Показывает сразу: результат, ошибка, подсказка. Пустая строка убирает. */
export function say(text) {
  clearTimeout(busyTimer);
  busyTimer = null;
  busyText = '';
  clearTimeout(holdTimer);
  holdTimer = null;
  if (text) {
    put(text);
    // Многоточие — признак СТАДИИ работы: её снимет тот, кто поставил, своим
    // `say('')`. У всего остального продолжения нет, и «правки удалены»
    // висело над кадром до конца сеанса. Такие снимаем сами.
    if (!text.trimEnd().endsWith('…')) {
      holdTimer = setTimeout(() => { holdTimer = null; put(''); }, DONE_KEEP);
    }
    return;
  }

  // Убрать просят сразу, но если подпись только что появилась — дадим её
  // дочитать: полсекунды текста лучше, чем вспышка.
  const shown = shownAt ? Date.now() - shownAt : Infinity;
  if (shown >= BUSY_KEEP) { put(''); return; }
  holdTimer = setTimeout(() => { holdTimer = null; put(''); },
                         BUSY_KEEP - shown);
}

/**
 * Сообщение о РАБОТЕ: появится, только если работа затянулась.
 *
 * Ровно для того, что может закончиться мгновенно: смена анимации, повторная
 * загрузка из кэша. Успело закончиться — `say('')` снимет отложенный показ, и
 * человек ничего не увидит. Уже что-то висит — меняем текст сразу: это
 * следующая стадия той же работы, а не новая вспышка.
 */
export function sayBusy(text) {
  clearTimeout(holdTimer);
  holdTimer = null;
  if (shownAt) { put(text); return; }
  // Отсчёт идёт с ПЕРВОГО сообщения о работе, а не с последнего: воркер шлёт
  // стадии пачкой, и перезапуск таймера на каждой отодвигал бы показ вечно —
  // подпись не появлялась вовсе даже на долгой сборке (поймано замером).
  busyText = text;
  if (busyTimer) return;
  busyTimer = setTimeout(() => { busyTimer = null; put(busyText); }, BUSY_DELAY);
}

/**
 * Окно вьювера. Это тот же viewer3d.html, что работает в приложении, и у него
 * есть готовый window-API (loadModelFromContent, applyMaterialMap, ...).
 * Возвращает null, пока iframe не загрузился.
 */
export function viewer() {
  const w = stage.frame.contentWindow;
  return (w && typeof w.loadModelFromContent === 'function') ? w : null;
}

/**
 * Окно движка частиц (particles3d.html). Тот же файл, что в приложении:
 * принимает {systems, materials} и сам крутит эффект.
 */
export function particles() {
  const w = stage.pframe.contentWindow;
  return (w && typeof w.loadParticleData === 'function') ? w : null;
}

/** Выполняет действие над движком частиц, дождавшись загрузки iframe. */
export function withParticles(fn) {
  const w = particles();
  if (w) { fn(w); return; }
  stage.pframe.addEventListener('load', () => {
    const ready = particles();
    if (ready) fn(ready);
  }, { once: true });
}

/** Выполняет действие над вьювером, дождавшись его готовности. */
export function withViewer(fn) {
  const w = viewer();
  if (w) { fn(w); return; }
  // Первый показ может опередить загрузку iframe — ждём его один раз.
  stage.frame.addEventListener('load', () => {
    const ready = viewer();
    if (ready) fn(ready);
  }, { once: true });
}
