/*
 * Заставка запуска.
 *
 * Разметка и вход живут в index.html и style.css: они обязаны отрисоваться
 * раньше первого модуля. Здесь шаги загрузки и уход: знак улетает на своё
 * место в шапке, фон тает, а под ним уже собранное окно.
 *
 * После смены языка страница поднимается заново (settings.js → restart), и
 * второй раз смотреть вход незачем: заставка там — просто занавес цвета фона,
 * который поднимается, когда окно готово (data-splash="quick").
 */

const splash = document.getElementById('splash');
const root = document.documentElement;
let leaving = null;

/** Пройденная доля загрузки, 0..1: линия под знаком. */
export function splashStep(part) {
  document.getElementById('splash-fill')?.style.setProperty('--p', part);
}

/** Убирает заставку; промис — когда её больше нет на экране. Повторный вызов
 *  (страховка сработала раньше загрузки) ждёт того же ухода. */
export function hideSplash() {
  leaving ??= leave();
  return leaving;
}

async function leave() {
  if (!splash?.isConnected) return;
  splashStep(1);
  const still = root.dataset.motion === 'off'
    || matchMedia('(prefers-reduced-motion: reduce)').matches;
  try {
    if (still) return;
    if (root.dataset.splash === 'quick') {
      await splash.animate([{ opacity: 1 }, { opacity: 0 }],
                           { duration: 220, fill: 'forwards' }).finished;
      return;
    }
    await introDone();
    await flyHome();
  } finally {
    // Что бы ни случилось с анимацией, окно не должно остаться за заставкой.
    splash.remove();
    root.classList.remove('is-splash');
  }
}

/** Вход доигрывает до конца: быстрый старт не обрывает буквы на середине. */
function introDone() {
  const word = document.getElementById('splash-word');
  return Promise.allSettled(word.getAnimations({ subtree: true }).map((a) => a.finished));
}

/** Рамка самого текста, без хвостов блока (у знака в шапке он шире). */
function textBox(el) {
  const range = document.createRange();
  range.selectNodeContents(el);
  return range.getBoundingClientRect();
}

/** Знак летит в шапку и садится ровно на её знак; фон тем временем тает. */
async function flyHome() {
  const word = document.getElementById('splash-word');
  const home = document.querySelector('.chrome__mark');
  const from = textBox(word);
  const to = textBox(home);
  const scale = parseFloat(getComputedStyle(home).fontSize)
              / parseFloat(getComputedStyle(word).fontSize);
  const dx = to.left - from.left;
  const dy = to.top + to.height / 2 - (from.top + from.height * scale / 2);

  splash.style.pointerEvents = 'none';
  const flight = word.animate([
    { transform: 'none', color: getComputedStyle(word).color },
    { transform: `translate(${dx}px, ${dy}px) scale(${scale})`,
      color: getComputedStyle(home).color },
  ], { duration: 560, easing: 'cubic-bezier(.65, 0, .25, 1)', fill: 'forwards' });
  splash.querySelectorAll('.splash__swash, .splash__bar').forEach((el) => {
    el.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 200, fill: 'forwards' });
  });
  // Фон тает, когда знак уже у шапки: по пути он прошёл бы поверх заголовка.
  const fade = splash.animate([
    { backgroundColor: getComputedStyle(splash).backgroundColor },
    { backgroundColor: 'transparent' },
  ], { duration: 300, delay: 330, easing: 'ease', fill: 'forwards' });
  await Promise.all([flight.finished, fade.finished]);
  // Знак шапки встаёт под летящим, и тот тает: крупный текст, уменьшенный
  // трансформом, растрируется не так, как родной мелкий, и может разойтись с
  // ним на пиксель. Резкая подмена показала бы этот скачок.
  root.classList.remove('is-splash');
  await word.animate([{ opacity: 1 }, { opacity: 0 }],
                     { duration: 160, fill: 'forwards' }).finished;
}

// Страховка: если загрузка так и не закончилась, окно не должно навсегда
// остаться за заставкой — ошибку под ней иначе не увидеть.
setTimeout(hideSplash, 15000);
