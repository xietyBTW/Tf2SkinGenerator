/*
 * Кнопки окна в шапке: свернуть, развернуть, закрыть.
 *
 * Системный заголовок убирает только окно приложения (frontend/titlebar.py).
 * В браузере и на dev-сервере ответ «custom: false»: кнопок нет, окном
 * управляет браузер. Таскать окно за шапку — CSS app-region (style.css), его
 * исполняет сам WebView2.
 */

import * as api from './api.js';
import { t } from './i18n.js';

const box = document.getElementById('winctl');
const max = box.querySelector('[data-win="maximize"]');
const root = document.documentElement;
let maximized = false;

/** Ответ окна → кнопки. Без своего заголовка ничего не меняется. */
function show(state) {
  if (!state || !state.custom) return;
  box.hidden = false;
  root.dataset.frame = 'custom';
  if (Boolean(state.maximized) === maximized) return;
  maximized = Boolean(state.maximized);
  box.classList.toggle('is-max', maximized);
  const label = t(maximized ? 'Свернуть в окно' : 'Развернуть окно');
  max.title = label;
  max.setAttribute('aria-label', label);
}

const ask = (action, theme) => api.windowControl(action, theme).then(show, () => {});

box.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-win]');
  if (btn) ask(btn.dataset.win);
});

// Разворачивают не только кнопкой: двойной щелчок по шапке, Win+↑, бросок к
// краю экрана. Поэтому после каждого изменения размера сверяемся с окном —
// заодно это второй шанс, если первый вопрос при запуске не дошёл.
let pending = 0;
addEventListener('resize', () => {
  clearTimeout(pending);
  pending = setTimeout(ask, 120);
});

// Полоска над страницей и рамка окна — под тему страницы (titlebar.py).
// Спрашиваем и тогда, когда кнопки ещё не показаны: тема могла смениться
// раньше первого ответа окна, а без своего заголовка окно ответит «нет».
new MutationObserver(() => ask('theme', root.dataset.theme))
  .observe(root, { attributes: true, attributeFilter: ['data-theme'] });

ask();
