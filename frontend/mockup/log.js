/*
 * Журнал обмена с Python и переключатель темы.
 *
 * В журнале важнее уровня НАПРАВЛЕНИЕ: сразу видно, кто кого позвал. Вьювер
 * живёт в своём документе и токенов страницы не видит, поэтому цвет фона ему
 * передаётся явно — при старте и при каждой смене темы.
 */

import * as api from './api.js';
import { withViewer } from './stage.js';
import { root } from './layout.js';

// ── Журнал ──────────────────────────────────────────────────────────────
// Показывает, что уходит в Python и что приходит обратно. Направление важнее
// уровня: сразу видно, кто кого позвал.
const logBody = document.getElementById('logbody');
const consoleBox = document.getElementById('console');
const MAX_LOG = 400;

api.setLogSink((dir, text, kind) => {
  const line = document.createElement('div');
  line.className = 'logline' + (dir === '↓' ? ' logline--in' : '')
                              + (kind === 'err' ? ' logline--err' : '');
  const t = new Date();
  line.innerHTML = '<span class="logline__time"></span>'
                 + '<span class="logline__dir"></span>'
                 + '<span class="logline__text"></span>';
  line.querySelector('.logline__time').textContent =
    String(t.getHours()).padStart(2,'0') + ':' +
    String(t.getMinutes()).padStart(2,'0') + ':' +
    String(t.getSeconds()).padStart(2,'0');
  line.querySelector('.logline__dir').textContent = dir;
  line.querySelector('.logline__text').textContent = text;

  const внизу = logBody.scrollTop + logBody.clientHeight >= logBody.scrollHeight - 30;
  logBody.appendChild(line);
  while (logBody.children.length > MAX_LOG) logBody.firstChild.remove();
  // Прокручиваем только если человек и так смотрел конец: иначе журнал
  // выдёргивал бы его из места, которое он читает.
  if (внизу) logBody.scrollTop = logBody.scrollHeight;
});

const toggleConsole = () => { consoleBox.hidden = !consoleBox.hidden; };
document.getElementById('logclose').addEventListener('click', toggleConsole);
document.getElementById('logclear').addEventListener('click', () => { logBody.innerHTML = ''; });
document.querySelector('.dock__state').addEventListener('click', toggleConsole);
document.addEventListener('keydown', (e) => {
  if (e.key === '`' || e.key === 'ё') { e.preventDefault(); toggleConsole(); }
});

// ── Тема ────────────────────────────────────────────────────────────────
// Вьювер живёт в своём документе и токенов страницы не видит — цвет фона ему
// передаём явно, при старте и при каждой смене темы.
export function syncViewerTheme() {
  const bg = getComputedStyle(root).getPropertyValue('--viewport').trim();
  withViewer((w) => w.setViewerBackground && w.setViewerBackground(bg));
}

const themeBtn = document.getElementById('theme');
themeBtn.addEventListener('click', () => {
  const dark = root.dataset.theme === 'dark';
  root.dataset.theme = dark ? 'light' : 'dark';
  themeBtn.textContent = dark ? 'Тёмная' : 'Светлая';
  syncViewerTheme();
});
