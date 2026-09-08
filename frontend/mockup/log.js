/*
 * Журнал приложения и переключатель темы.
 *
 * В журнале две ленты, и это разные вещи:
 *
 *   обмен   что страница спросила у Python и что получила. Здесь важен не
 *           уровень, а НАПРАВЛЕНИЕ: сразу видно, кто кого позвал.
 *   Python  то, что пишет сам логгер приложения — 700 вызовов, из них 640 в
 *           src/services, то есть ровно там, где идёт работа: что нашлось в
 *           VPK, какой VMT взят, почему упал Crowbar. Раньше всё это уходило
 *           только в файл, и консоль в окне выглядела пустой.
 *
 * Python-часть забирается опросом (`log_tail`), раз в секунду и ТОЛЬКО пока
 * консоль открыта. Через поток событий воркеров её пускать нельзя: очередь
 * держит 500 штук и при переполнении выбрасывает старые, а лог одной сборки —
 * это сотни строк; он вытеснил бы progress и model_ready, и превью бы залипло.
 *
 * Вьювер живёт в своём документе и токенов страницы не видит, поэтому цвет
 * фона ему передаётся явно — при старте и при каждой смене темы.
 */

import * as api from './api.js';
import { withViewer } from './stage.js';
import { root } from './layout.js';
import { t } from './i18n.js';

const logBody = document.getElementById('logbody');
const consoleBox = document.getElementById('console');
const noteBox = document.getElementById('lognote');
const findBox = document.getElementById('logfind');
const MAX_LOG = 2000;

// ── Фильтр ──────────────────────────────────────────────────────────────
// Маска битами: её же числом хранит Python (console_filter), не толкуя.
// Значения заданы ЗДЕСЬ и только здесь.
const BIT = { exchange: 1, error: 2, warning: 4, info: 8, debug: 16 };
//: По умолчанию — обмен, ошибки, предупреждения. Инфо и отладка в спокойной
//: работе дают сотни строк на одну сборку и мешают увидеть важное.
let mask = BIT.exchange | BIT.error | BIT.warning;
let needle = '';

/** Категория строки: по ней и фильтруем. CRITICAL показываем как ошибку. */
function bitOf(level) {
  if (!level) return BIT.exchange;
  const low = level.toLowerCase();
  if (low === 'critical') return BIT.error;
  return BIT[low] || BIT.info;
}

/** Прячет или показывает строку по текущему фильтру и поиску. */
function applyOne(line) {
  const okLevel = (Number(line.dataset.bit) & mask) !== 0;
  const okFind = !needle || line.textContent.toLowerCase().includes(needle);
  line.hidden = !(okLevel && okFind);
}

function applyAll() {
  for (const line of logBody.children) applyOne(line);
  for (const chip of document.querySelectorAll('.console__filters [data-lvl]')) {
    chip.classList.toggle('is-active', (BIT[chip.dataset.lvl] & mask) !== 0);
  }
}

// ── Отрисовка строки ────────────────────────────────────────────────────

function stamp(date) {
  const p = (n) => String(n).padStart(2, '0');
  return p(date.getHours()) + ':' + p(date.getMinutes()) + ':' + p(date.getSeconds());
}

/**
 * Добавляет строку в ленту.
 *
 * `dir` — направление обмена (→ ← ↓ !), `level` — уровень записи Python.
 * Одновременно они не приходят: строка либо из обмена, либо из логгера.
 */
function push({ time, dir, level, source, text, kind }) {
  const line = document.createElement('div');
  const lvl = (level || '').toLowerCase();
  line.className = 'logline'
    + (dir === '↓' ? ' logline--in' : '')
    + (kind === 'err' ? ' logline--err' : '')
    + (lvl ? ' logline--' + lvl : '');
  line.dataset.bit = String(bitOf(level));

  line.innerHTML = '<span class="logline__time"></span>'
                 + '<span class="logline__dir"></span>'
                 + '<span class="logline__src"></span>'
                 + '<span class="logline__text"></span>';
  line.querySelector('.logline__time').textContent = stamp(time || new Date());
  line.querySelector('.logline__dir').textContent = dir || levelMark(level);
  line.querySelector('.logline__src').textContent = source || '';
  // Через t(): подписи страницы переводятся на границе показа, и сообщения
  // Python — не исключение (см. strings.js). Незнакомая строка остаётся как
  // есть, и пропуск виден на экране.
  line.querySelector('.logline__text').textContent = text ? t(text) : '';

  const atEnd = logBody.scrollTop + logBody.clientHeight >= logBody.scrollHeight - 30;
  applyOne(line);
  logBody.appendChild(line);
  while (logBody.children.length > MAX_LOG) logBody.firstChild.remove();
  // Прокручиваем только если человек и так смотрел конец: иначе журнал
  // выдёргивал бы его из места, которое он читает.
  if (atEnd) logBody.scrollTop = logBody.scrollHeight;
}

/** Короткая метка уровня в колонке направления — чтобы колонки не разъезжались. */
function levelMark(level) {
  return { ERROR: 'ERR', CRITICAL: 'CRIT', WARNING: 'WARN',
           INFO: 'INFO', DEBUG: 'DBG' }[level] || '';
}

api.setLogSink((dir, text, kind) => push({ dir, text, kind }));

// ── Забор журнала Python ────────────────────────────────────────────────

//: Номер последней взятой записи. Кольцо в Python нумерует их сквозным
//: счётчиком, поэтому разрыв в номерах — это потеря, а не тишина.
let seen = 0;
let timer = null;

async function pull() {
  let res;
  try {
    res = await api.logTail(seen);
  } catch (err) {
    return;                       // приложение закрывается — это не ошибка
  }
  for (const e of res.entries || []) {
    push({ time: new Date(e.time * 1000), level: e.level,
           source: e.source, text: e.text });
  }
  seen = res.next ?? seen;
  if (res.dropped) {
    noteBox.hidden = false;
    noteBox.textContent = t('Пропущено записей:') + ' ' + res.dropped
      + ' ' + t('(журнал не успевали читать; всё есть в файле)');
  }
}

function watch(on) {
  clearInterval(timer);
  timer = null;
  if (on) {
    pull();
    timer = setInterval(pull, 1000);
  }
}

// ── Открытие, закрытие, действия ────────────────────────────────────────

function toggleConsole(show) {
  const open = show === undefined ? consoleBox.hidden : show;
  consoleBox.hidden = !open;
  // Опрашиваем только пока смотрят: закрыта консоль почти всегда.
  watch(open);
}

document.getElementById('logclose').addEventListener('click', () => toggleConsole(false));

document.getElementById('logclear').addEventListener('click', async () => {
  logBody.innerHTML = '';
  noteBox.hidden = true;
  try {
    await api.clearLog();
  } catch (err) { /* кольцо в Python не критично */ }
});

document.getElementById('logcopy').addEventListener('click', () => {
  // Копируем ВИДИМОЕ: человек отфильтровал ошибки и хочет отправить их, а не
  // две тысячи строк вместе с отладкой.
  const text = [...logBody.children]
    .filter((l) => !l.hidden)
    .map((l) => l.textContent.replace(/\s+/g, ' ').trim())
    .join('\n');
  navigator.clipboard.writeText(text).catch(() => {});
});

document.getElementById('logopen').addEventListener('click', () => {
  api.logFolder().catch(() => {});
});

const wideBtn = document.getElementById('logwide');
wideBtn.addEventListener('click', () => {
  const wide = consoleBox.dataset.wide === '1';
  consoleBox.dataset.wide = wide ? '0' : '1';
  wideBtn.textContent = wide ? t('Во всё окно') : t('Свернуть');
});

for (const chip of document.querySelectorAll('.console__filters [data-lvl]')) {
  chip.addEventListener('click', () => {
    mask ^= BIT[chip.dataset.lvl];
    applyAll();
    api.setUiState('console_filter', mask).catch(() => {});
  });
}

findBox.addEventListener('input', () => {
  needle = findBox.value.trim().toLowerCase();
  applyAll();
});

// Состояние лежит ВНУТРИ кнопки «Параметры», и без остановки всплытия щелчок
// по нему открывал заодно панель настроек — журнал и параметры вылезали вместе.
document.querySelector('.dock__state').addEventListener('click', (e) => {
  e.stopPropagation();
  toggleConsole();
});
document.addEventListener('keydown', (e) => {
  if (e.target.matches('input, textarea')) return;
  if (e.key === '`' || e.key === 'ё') { e.preventDefault(); toggleConsole(); }
});

// ── Ширина: тянут за левый край ─────────────────────────────────────────
// Тот же приём, что у панели параметров (particles/resize.js): ширина живёт в
// CSS-переменной, а между запусками — в общем конфиге. localStorage не годится:
// страницу отдаёт локальный сервер на СЛУЧАЙНОМ порту, origin каждый раз свой.

const grip = document.getElementById('loggrip');
const MIN_W = 320;
let drag = null;

/** Ставит сохранённую ширину. 0 — край не трогали, ширину задаёт CSS. */
export function setConsoleWidth(px) {
  const want = Number(px) || 0;
  if (want >= MIN_W) root.style.setProperty('--cw', `${want}px`);
  else root.style.removeProperty('--cw');
}

/** Ставит сохранённый фильтр. Зовётся из настроек вместе с остальной раскладкой. */
export function setConsoleFilter(bits) {
  const want = Number(bits);
  mask = Number.isFinite(want) ? want : mask;
  applyAll();
}

grip.addEventListener('pointerdown', (e) => {
  if (e.button !== 0) return;
  drag = { x: e.clientX, w: consoleBox.getBoundingClientRect().width };
  grip.setPointerCapture(e.pointerId);
});

grip.addEventListener('pointermove', (e) => {
  if (!drag) return;
  // Консоль прижата к правому краю: тянем влево — она шире.
  const want = Math.max(MIN_W, Math.min(window.innerWidth - 120,
                                        drag.w + (drag.x - e.clientX)));
  root.style.setProperty('--cw', `${Math.round(want)}px`);
});

grip.addEventListener('pointerup', (e) => {
  if (!drag) return;
  drag = null;
  grip.releasePointerCapture(e.pointerId);
  const width = Math.round(consoleBox.getBoundingClientRect().width);
  api.setUiState('console_width', width).catch(() => {});
});

applyAll();

// ── Тема ────────────────────────────────────────────────────────────────
// Вьювер живёт в своём документе и токенов страницы не видит — цвет фона ему
// передаём явно, при старте и при каждой смене темы.
export function syncViewerTheme() {
  const bg = getComputedStyle(root).getPropertyValue('--viewport').trim();
  withViewer((w) => w.setViewerBackground && w.setViewerBackground(bg));
}

/**
 * Ставит тему страницы. Выбор живёт в настройках (`theme` в общем конфиге) —
 * кнопкой в шапке он не сохранялся, а при следующем запуске приложение опять
 * открывалось светлым.
 */
export function setTheme(name) {
  root.dataset.theme = name === 'dark' ? 'dark' : 'light';
  syncViewerTheme();
}
