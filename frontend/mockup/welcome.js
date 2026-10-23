/*
 * Встречающее окно первого запуска
 *
 * Пять шагов: язык и тема, папка игры, куда собирать моды, обход sv_pure,
 * итог. Выбор копится в черновике и пишется в настройки одним разом в конце -
 * кроме языка: он пропитывает всю страницу, и её поднимают заново
 * (settings.js -> restart), а окно продолжает со следующего шага (черновик в
 * sessionStorage). Тема меняется сразу, волной от плитки: ради этого на неё и
 * смотрят
 *
 * Ничего не обязательно: «Пропустить» сохраняет выбранное, а без годной папки
 * игры остаётся обычный вопрос (offerTf2). Кто работал с приложением до этого
 * окна (путь к игре есть, обучение пройдено), его не увидит.
 */

import * as api from './api.js';
import { t } from './i18n.js';
import { escapeHtml } from './util.js';
import { setTheme } from './log.js';
import { offerTf2, restart } from './settings.js';
import { showTf2Path } from './layout.js';
import { relabel } from './catalog.js';
import { startFirstRun, startTour, forgoTour } from './tour.js';
import { say, sayError } from './stage.js';

const STEPS = ['look', 'game', 'export', 'pure', 'done'];
const RESUME = 'welcome';
const root = document.documentElement;
const still = () => root.dataset.motion === 'off'
  || matchMedia('(prefers-reduced-motion: reduce)').matches;

let el = null;       // корень окна
let cfg = null;      // ответ api.settings(): варианты и умения окна
let draft = null;    // {language, theme, tf2, tf2Ok, exportDir, bypass}
let step = 0;
let close = null;    // завершает промис окна: 'tour' | 'start' | 'skip'

//: Ответ окна, если оно нужно (см. prepareWelcome); null - окна не будет
let pending = null;

/**
 * Решает, нужно ли окно, и строит его ЕЩЁ ПОД ЗАСТАВКОЙ: заставка уходит
 * прямо в окно, без кадра основного интерфейса между ними. Анимации карточки
 * стоят (is-held), пока её не видно, - их отпускает firstStart.
 */
export async function prepareWelcome() {
  try {
    const resume = readResume();
    cfg = await api.settings();
    const v = cfg.values;
    const forced = new URLSearchParams(location.search).get('welcome') === '1';
    if (!resume && !forced) {
      if (!v.welcome_done && cfg.tf2_ok && v.tours_done) api.setUiState('welcome_done', 1);
      if (v.welcome_done || (cfg.tf2_ok && v.tours_done)) return;
    }
    draft = resume?.draft || {
      language: v.language, theme: v.theme, tf2: v.tf2_game_folder,
      tf2Ok: cfg.tf2_ok, exportDir: v.export_folder, bypass: v.sv_pure_bypass,
    };
    // Язык уже записан в настройки (ради него страницу и перезапускали) -
    // правда о нём там, а не в черновике, снятом до перезапуска
    draft.language = v.language;
    pending = open(resume?.step || 0);
    // is-early - подложка без проявления (она уже под заставкой), is-held -
    // вход карточки на паузе до её ухода
    el.classList.add('is-early', 'is-held');
  } catch (err) {
    // Окно - не повод не открыть приложение: старт пойдёт обычным путём
    console.error(err);
    pending = null;
  }
}

/**
 * Первый запуск, когда заставка ушла: встречающее окно, а за ним обучение.
 * Кому окно не нужно - обычный путь: вопрос про игру и главный тур.
 */
export async function firstStart() {
  if (!pending) {
    await offerTf2();
    startFirstRun();
    return;
  }
  el.classList.remove('is-held');
  el.querySelector('.welcome__next').focus({ preventScroll: true });
  const answer = await pending;
  // Без игры не работает ничего: пустой путь спрашиваем при любом выходе
  if (!draft.tf2Ok) await offerTf2();
  if (answer === 'tour') startTour('main');
  else forgoTour('main');
}

function readResume() {
  try {
    const raw = sessionStorage.getItem(RESUME);
    sessionStorage.removeItem(RESUME);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

// Окно

function open(at) {
  el = document.createElement('div');
  el.className = 'welcome';
  el.setAttribute('role', 'dialog');
  el.setAttribute('aria-modal', 'true');
  el.innerHTML = `
    <div class="welcome__card">
      <div class="welcome__head">
        <div class="welcome__steps">${STEPS.map(() => '<i class="welcome__seg"></i>').join('')}</div>
        <span class="welcome__count"></span>
      </div>
      <div class="welcome__stage"></div>
      <div class="welcome__foot">
        <button class="textbtn welcome__skip" type="button">${t('Пропустить')}</button>
        <button class="textbtn welcome__back" type="button">${t('Назад')}</button>
        <button class="btn--primary welcome__next" type="button"></button>
      </div>
    </div>`;
  document.body.append(el);
  root.classList.add('has-welcome');      // интерфейс за окном скрыт (style-welcome.css)
  // На последнем шаге та же кнопка - «начать без обучения»
  el.querySelector('.welcome__skip').addEventListener('click',
    () => leave(STEPS[step] === 'done' ? 'start' : 'skip'));
  el.querySelector('.welcome__back').addEventListener('click', () => go(step - 1));
  el.querySelector('.welcome__next').addEventListener('click', next);
  // Enter - «Далее», если фокус не на другой кнопке (плитка выбирается им же).
  // Клавиши окна дальше не идут: горячие клавиши страницы (консоль по `)
  // сработали бы под оверлеем
  el.addEventListener('keydown', (e) => {
    e.stopPropagation();
    if (e.key !== 'Enter' || e.target.matches('textarea, button:not(.welcome__next)')) return;
    e.preventDefault();
    next();
  });
  show(at, 0);
  return new Promise((resolve) => { close = resolve; });
}

//: «Далее» уже работает (проверка пути идёт к Python): второй щелчок или
//: Enter за это время перескочил бы шаг
let busy = false;
//: Окно уже уходит: второй выход сохранил бы и закрыл его дважды
let leaving = false;

async function next() {
  if (busy || leaving) return;
  busy = true;
  try {
    if (STEPS[step] === 'game' && !(await gameReady())) return;
    if (STEPS[step] === 'done') { leave('tour'); return; }
    go(step + 1);
  } finally {
    busy = false;
  }
}

function go(to) {
  if (to < 0 || to >= STEPS.length || to === step) return;
  show(to, Math.sign(to - step));
}

/** Шаг `at`; `dir` - откуда он въезжает (1 - справа, -1 - слева, 0 - сразу) */
function show(at, dir) {
  step = at;
  const stage = el.querySelector('.welcome__stage');
  const old = stage.querySelector('.welcome__page:not([inert])');
  const page = document.createElement('section');
  page.className = 'welcome__page';
  page.innerHTML = PAGES[STEPS[at]]();
  page.querySelectorAll('.wl-in').forEach((n, i) => n.style.setProperty('--d', i));
  stage.append(page);
  BIND[STEPS[at]]?.(page);

  el.querySelectorAll('.welcome__seg').forEach((seg, i) => {
    seg.classList.toggle('is-done', i < at);
    seg.classList.toggle('is-now', i === at);
  });
  el.querySelector('.welcome__count').textContent = `0${at + 1} / 0${STEPS.length}`;
  el.querySelector('.welcome__back').hidden = at === 0;
  el.querySelector('.welcome__skip').textContent =
    STEPS[at] === 'done' ? t('Начать без обучения') : t('Пропустить');
  const nextBtn = el.querySelector('.welcome__next');
  nextBtn.textContent = STEPS[at] === 'done' ? t('Пройти обучение') : t('Далее');
  nextBtn.classList.toggle('is-final', STEPS[at] === 'done');
  nextBtn.focus({ preventScroll: true });

  if (!old) return;
  old.inert = true;
  if (still() || !dir) { old.remove(); return; }
  // Старый шаг уходит в сторону, обратную приходу нового, и тает в размытие
  old.animate([
    { opacity: 1, transform: 'none', filter: 'none' },
    { opacity: 0, transform: `translateX(${-36 * dir}px)`, filter: 'blur(6px)' },
  ], { duration: 360, easing: 'cubic-bezier(.65, 0, .25, 1)', fill: 'forwards' })
    .finished.finally(() => old.remove());
  page.animate([
    { transform: `translateX(${48 * dir}px)` }, { transform: 'none' },
  ], { duration: 560, easing: 'cubic-bezier(.2, .7, .2, 1)' });
}

/** Сохраняет черновик и закрывает окно с ответом `answer` */
async function leave(answer) {
  if (leaving) return;
  leaving = true;
  const card = el.querySelector('.welcome__card');
  el.querySelectorAll('button').forEach((b) => { b.disabled = true; });
  try {
    await save();
  } catch (err) {
    // Не сохранилось - окно всё равно уходит: запертый за ним интерфейс хуже
    say(err.message || String(err));
  }
  // Интерфейс возвращается под уходящее окно: проступает сквозь его таяние
  root.classList.remove('has-welcome');
  if (!still()) {
    // Не дольше 900 мс: у скрытого окна анимации стоят, и finished не придёт
    await Promise.race([new Promise((r) => setTimeout(r, 900)), Promise.allSettled([
      card.animate([{ opacity: 1, transform: 'none', filter: 'none' },
                    { opacity: 0, transform: 'translateY(-10px) scale(.985)', filter: 'blur(6px)' }],
                   { duration: 380, easing: 'cubic-bezier(.65, 0, .25, 1)', fill: 'forwards' }).finished,
      el.animate([{ opacity: 1 }, { opacity: 0 }],
                 { duration: 420, delay: 160, easing: 'ease', fill: 'forwards' }).finished,
    ])]);
  }
  el.remove();
  leaving = false;
  close(answer);
}

/** Всё выбранное - в настройки одним вызовом. Путь к игре - только годный */
async function save() {
  const values = { theme: draft.theme, export_folder: draft.exportDir,
                   sv_pure_bypass: draft.bypass };
  if (draft.tf2Ok) values.tf2_game_folder = draft.tf2;
  const res = await api.setSettings(values);
  api.setUiState('welcome_done', 1);
  if (res.error || !draft.tf2Ok || draft.tf2 === cfg.values.tf2_game_folder) return;
  // Игра поменялась: подпись внизу и обложки каталога - уже по новой
  showTf2Path();
  api.forgetCached();
  await relabel();
}

// Шаги
// Русский текст стоит прямо в разметке: переводит его наблюдатель i18n.js,
// когда узел попадает на страницу. Вложенных шаблонов с текстом нет - куски,
// которые повторяются, собирают помощники ниже

//: Заголовки шагов: их режем по словам, поэтому переводим сами (t)
const TITLES = {
  look: 'Добро пожаловать',
  game: 'Где установлена TF2',
  export: 'Куда класть готовые моды',
  pure: 'Как моды пройдут проверку игры',
  done: 'Можно начинать',
};
//: Подписи плиток папки модов
const EXPORT_TEXT = {
  app: 'Папка приложения',
  appSub: 'Рядом с работами, переносите в игру сами',
  game: 'Сразу в игру',
  noGame: 'Сначала укажите папку игры',
  own: 'Своя папка',
  pick: 'Выбрать на диске',
  inSettings: 'Укажите в «Настройках»',
};
const DEFAULT_TAG = 'по умолчанию';

/** Заголовок по словам: каждое проявляется своим шагом (style-welcome.css) */
function title(text) {
  const words = t(text).split(' ').map((w, i) => `<span style="--i:${i}">${escapeHtml(w)}</span>`);
  return `<h2 class="wl-title">${words.join(' ')}</h2>`;
}

function tile(value, name, sub = '', extra = '', on = false, tag = '') {
  const subHtml = sub ? `<span class="wl-tile__sub">${sub}</span>` : '';
  const tagHtml = tag ? `<span class="wl-tile__tag">${tag}</span>` : '';
  return `<button class="wl-tile${on ? ' is-on' : ''}" type="button" data-value="${escapeHtml(value)}">`
    + `${extra}<span class="wl-tile__name">${name}</span>${subHtml}${tagHtml}</button>`;
}

const pathSpan = (path) => `<span class="wl-tile__path">${escapeHtml(path)}</span>`;

const wordmark = () => [...'TF2 Skin Generator']
  .map((c, i) => `<span style="--i:${i}">${c === ' ' ? '&nbsp;' : c}</span>`).join('');
const shot = (theme) => `<span class="wl-shot wl-shot--${theme}"><i></i><i></i><i></i><i></i></span>`;
const burst = () => Array.from({ length: 8 }, (_, i) => `<i style="--i:${i}"></i>`).join('');

const CHECK = '<svg class="wl-check" viewBox="0 0 30 30"><circle cx="15" cy="15" r="10"/><path d="M10.5 15.5l3 3 6-6.5"/></svg>';
const CROSS = '<svg class="wl-cross" viewBox="0 0 30 30"><circle cx="15" cy="15" r="10"/><path d="M11.5 11.5l7 7M18.5 11.5l-7 7"/></svg>';

function langTiles() {
  return cfg.languages.map((l) => tile(l.value, escapeHtml(l.label), '', '',
                                       l.value === draft.language)).join('');
}

function themeTiles() {
  return cfg.themes.map((th) => tile(th.value, escapeHtml(th.label), '', shot(th.value),
                                     th.value === draft.theme)).join('');
}

function exportTiles() {
  const game = customDir();
  const own = ownDir();
  const ownHint = cfg.folder_picker ? EXPORT_TEXT.pick : EXPORT_TEXT.inSettings;
  return tile('export', EXPORT_TEXT.app, EXPORT_TEXT.appSub, '',
              draft.exportDir === 'export', DEFAULT_TAG)
    + tile(game, EXPORT_TEXT.game, game ? pathSpan(game) : EXPORT_TEXT.noGame, '',
           Boolean(game) && draft.exportDir === game)
    + tile(own, EXPORT_TEXT.own, own ? pathSpan(own) : ownHint, '',
           Boolean(own) && draft.exportDir === own);
}

function bypassTiles() {
  // Подпись Python несёт «(по умолчанию)» в скобках - здесь это метка плитки
  const folder = (label) => label.replace(/\s*\(.*\)\s*$/, '');
  return cfg.bypass.map((b, i) => tile(b.value, escapeHtml(b.value),
    pathSpan(`materials\\${folder(b.label)}`), '', b.value === draft.bypass,
    i === 0 ? DEFAULT_TAG : '')).join('');
}

function summaryRows() {
  return summary().map(([k, v]) => `<dt class="wl-in">${k}</dt><dd class="wl-in">${v}</dd>`).join('');
}

const PAGES = {
  look: () => `
    <div class="wl-mark wl-in">
      <span class="wl-word">${wordmark()}</span>
      <i class="wl-swash wl-swash--red"></i><i class="wl-swash wl-swash--blu"></i>
    </div>
    ${title(TITLES.look)}
    <p class="wl-text wl-in">Пара настроек - и можно красить. Всё это потом меняется в «Настройках».</p>
    <div class="wl-group wl-in">
      <span class="wl-label">Язык</span>
      <div class="wl-tiles" data-pick="language">${langTiles()}</div>
    </div>
    <div class="wl-group wl-in">
      <span class="wl-label">Тема</span>
      <div class="wl-tiles" data-pick="theme">${themeTiles()}</div>
    </div>`,

  game: () => `
    <p class="wl-eyebrow wl-in">Игра</p>
    ${title(TITLES.game)}
    <p class="wl-text wl-in">Модели и текстуры приложение берёт прямо из игры.</p>
    <div class="wl-game wl-in">
      <div class="wl-status"></div>
      <div class="wl-pathrow">
        <input class="input" spellcheck="false" placeholder="Папка Team Fortress 2">
        <button class="textbtn" type="button" data-act="pick">Выбрать папку</button>
        <button class="textbtn" type="button" data-act="find">Найти снова</button>
      </div>
    </div>`,

  export: () => `
    <p class="wl-eyebrow wl-in">Сборка</p>
    ${title(TITLES.export)}
    <p class="wl-text wl-in">Сюда приложение положит собранный VPK.</p>
    <div class="wl-tiles wl-tiles--list wl-in" data-pick="exportDir">${exportTiles()}</div>`,

  pure: () => `
    <p class="wl-eyebrow wl-in">Серверы Valve</p>
    ${title(TITLES.pure)}
    <p class="wl-text wl-in">Материалы мода лежат в папке, которую игра пропускает и в казуале. Перестал работать один способ - выберите другой.</p>
    <div class="wl-tiles wl-in" data-pick="bypass">${bypassTiles()}</div>`,

  done: () => `
    <div class="wl-final">
      <div class="wl-big wl-in">${CHECK}<span class="wl-burst">${burst()}</span></div>
      <div>
        <p class="wl-eyebrow wl-in">Готово</p>
        ${title(TITLES.done)}
      </div>
    </div>
    <dl class="wl-sum">${summaryRows()}</dl>
    <p class="wl-text wl-in">Короткое обучение покажет, где что лежит. Его можно пройти и позже из «Настроек».</p>`,
};

function summary() {
  const label = (list, value) => escapeHtml((list.find((x) => x.value === value) || {}).label || value);
  const mono = (text) => `<span class="mono">${escapeHtml(text)}</span>`;
  return [
    [t('Язык'), label(cfg.languages, draft.language)],
    [t('Тема'), label(cfg.themes, draft.theme)],
    [t('Игра'), draft.tf2Ok ? mono(draft.tf2) : t('не указана')],
    [t('Моды'), draft.exportDir === 'export' ? t('Папка приложения') : mono(draft.exportDir)],
    [t('Обход'), escapeHtml(draft.bypass)],
  ];
}

/** tf\custom выбранной игры - туда игра сама подхватывает моды */
const customDir = () => (draft.tf2Ok ? `${draft.tf2.replace(/[\\/]+$/, '')}\\tf\\custom` : '');
/** Своя папка: выбранная раньше и не совпадающая с двумя готовыми */
const ownDir = () => (draft.exportDir && draft.exportDir !== 'export'
  && draft.exportDir !== customDir() ? draft.exportDir : '');

/** Новый путь к игре. Моды шли в tf\custom прежней - вернуть папку приложения:
 *  иначе они ушли бы в игру, которую человек только что сменил */
function setGame(path, ok) {
  const was = customDir();
  Object.assign(draft, { tf2: path, tf2Ok: ok });
  if (was && draft.exportDir === was && customDir() !== was) draft.exportDir = 'export';
}

// Действия шагов

const BIND = {
  look(page) {
    picks(page, 'theme', (value, btn, e) => switchTheme(value, e));
    picks(page, 'language', async (value) => {
      if (value === api.lang() || busy) return false;
      // Язык - перезапуском страницы, окно вернётся на следующий шаг. Тема -
      // вместе с ним: новая страница берёт её из конфига (applyLook)
      busy = true;
      try {
        const res = await api.setSettings({ language: value, theme: draft.theme });
        if (res.error) { sayError(res.error); return false; }
        try { sessionStorage.setItem(RESUME, JSON.stringify({ step: 1, draft })); } catch {}
        restart({ theme: draft.theme, ui_animations: root.dataset.motion !== 'off' });
        return true;
      } catch (err) {
        say(err.message || String(err));
        return false;
      } finally {
        busy = false;
      }
    });
  },

  game(page) {
    const input = page.querySelector('.input');
    input.value = draft.tf2Ok ? draft.tf2 : '';
    input.addEventListener('input', () => {
      findSeq++;              // поиск ещё идёт - его ответ уже не нужен
      setGame(input.value.trim(), false);
    });
    page.querySelector('[data-act="find"]').addEventListener('click', () => find(page));
    // Системный выбор папки есть только в окне приложения, не в браузере
    page.querySelector('[data-act="pick"]').hidden = !cfg.folder_picker;
    page.querySelector('[data-act="pick"]').addEventListener('click', async () => {
      const res = await api.pickFolder(input.value);
      if (!res.path) return;
      findSeq++;
      input.value = res.path;
      await verify(page, res.path);
    });
    if (draft.tf2Ok) status(page, 'ok', t('Игра на месте'));
    else find(page);
  },

  export(page) {
    const own = page.querySelectorAll('.wl-tile')[2];
    picks(page, 'exportDir', async (value, btn) => {
      if (btn !== own) return true;
      // Своя папка - каждый щелчок выбирает заново, системным выбором
      const clean = String((await api.pickFolder(value || '')).path || '').trim();
      if (!clean) return false;
      btn.dataset.value = clean;
      btn.querySelector('.wl-tile__sub').innerHTML = pathSpan(clean);
      return true;
    });
    if (!customDir()) page.querySelectorAll('.wl-tile')[1].disabled = true;
    // Системного выбора папки нет только вне окна приложения (dev-сервер)
    if (!cfg.folder_picker) own.disabled = true;
  },

  pure(page) { picks(page, 'bypass'); },
};

/** Плитки ряда `data-pick=key`: выбор пишет черновик; `act` может отказать (false) */
function picks(page, key, act) {
  const row = page.querySelector(`[data-pick="${key}"]`);
  row.querySelectorAll('.wl-tile').forEach((btn) => btn.addEventListener('click', async (e) => {
    if (act && (await act(btn.dataset.value, btn, e)) === false) return;
    draft[key] = btn.dataset.value;
    row.querySelectorAll('.wl-tile').forEach((x) => x.classList.toggle('is-on', x === btn));
  }));
}

/** Тема сразу на всём окне - волной из точки щелчка (View Transitions) */
function switchTheme(value, e) {
  if (value === root.dataset.theme) return;
  if (still() || !document.startViewTransition) { setTheme(value); return; }
  const x = e?.clientX ?? innerWidth / 2;
  const y = e?.clientY ?? innerHeight / 2;
  const r = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
  // Половины стола - именованные участники переходов (style-motion.css), а
  // такой рисуется своим слоем ПОВЕРХ всего: 3D-окно вылезало над карточкой.
  // На смену темы страница - одна картинка
  root.classList.add('is-theme-vt');
  // Новый снимок с первого кадра обрезан в точку щелчка (style-welcome.css):
  // между стартом перехода и волной он иначе мелькал целиком
  root.style.setProperty('--vt-x', `${x}px`);
  root.style.setProperty('--vt-y', `${y}px`);
  const vt = document.startViewTransition(() => setTheme(value));
  vt.ready.then(() => root.animate(
    { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${r}px at ${x}px ${y}px)`] },
    { duration: 620, easing: 'cubic-bezier(.65, 0, .25, 1)', fill: 'forwards',
      pseudoElement: '::view-transition-new(root)' })).catch(() => {});
  vt.finished.finally(() => root.classList.remove('is-theme-vt'));
}

// Поиск игры

/** Строка состояния: `kind` - scan (ищу), ok (галочка), bad (крестик) */
function status(page, kind, text, path = '') {
  const box = page.querySelector('.wl-status');
  const icon = kind === 'scan' ? '<span class="wl-scan"></span>' : (kind === 'ok' ? CHECK : CROSS);
  box.className = `wl-status is-new${kind === 'bad' ? ' is-bad' : ''}`;
  box.innerHTML = `${icon}<span class="wl-status__text"><span>${text}</span>${
    path ? `<span class="wl-status__path">${escapeHtml(path)}</span>` : ''}</span>`;
}

//: Номер поиска: ввод, выбор папки или уход с шага делают прошлый ответ
//: ненужным - иначе поздний автопоиск перетёр бы то, что человек ввёл сам
let findSeq = 0;

async function find(page) {
  const seq = ++findSeq;
  status(page, 'scan', t('Ищу игру…'));
  // Поиск занимает доли секунды, линия поиска должна успеть прочитаться
  const [res] = await Promise.all([api.findTf2(), new Promise((r) => setTimeout(r, 700))]);
  if (seq !== findSeq || page.inert || !page.isConnected) return;
  const found = (res.found || [])[0];
  if (!found) {
    status(page, 'bad', t('Не нашёл - укажите папку игры'));
    return;
  }
  page.querySelector('.input').value = found;
  setGame(found, true);
  status(page, 'ok', t('Нашёл игру'));
}

async function verify(page, path) {
  const ok = Boolean(path) && (await api.checkTf2(path)).ok;
  setGame(path, ok);
  if (ok) status(page, 'ok', t('Игра на месте'));
  else status(page, 'bad', t('Здесь нет TF2 - нужна папка Team Fortress 2'));
  return ok;
}

/** Можно ли дальше с шага игры: пустое поле - да (спросим позже), иначе - годный путь */
async function gameReady() {
  const page = el.querySelector('.welcome__page:not([inert])');
  const path = page.querySelector('.input').value.trim();
  if (!path || (draft.tf2Ok && path === draft.tf2)) return true;
  if (await verify(page, path)) return true;
  const row = page.querySelector('.wl-pathrow');
  row.classList.remove('is-shake');
  void row.offsetWidth;
  row.classList.add('is-shake');
  return false;
}
