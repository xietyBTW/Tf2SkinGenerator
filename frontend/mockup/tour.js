/*
 * Обучение: короткие туры по экрану.
 *
 * Главный тур запускается сам при первом старте и ведёт по пути «предмет →
 * картинка → параметры → сборка». Остальные — маленькие, про одно место, и
 * появляются, когда человек впервые туда попал: в режим частей, в подгонку, в
 * War Paint, в раздел шапок, частиц, звуков. Пропустить можно на любом шаге.
 *
 * Подсветка НЕ перехватывает мышь: шаг «выберите предмет» просит сделать это
 * руками, и тур идёт дальше сам, когда дело сделано. Поэтому здесь нет своей
 * модели экрана — только селекторы и проверки по DOM: тур смотрит на страницу
 * так же, как человек, и не держит второй копии её состояния.
 *
 * Шаг, чьей кнопки сейчас нет на экране (у этой модели нет команд, панель
 * свёрнута), пропускается: обещать то, чего не видно, — хуже, чем промолчать.
 *
 * Что пройдено, помнит конфиг (`tours_done`, битовая маска): страницу отдаёт
 * локальный сервер на случайном порту, и localStorage не пережил бы перезапуск.
 */

import * as api from './api.js';
import { t } from './i18n.js';

const root = document.documentElement;
const $ = (sel) => document.querySelector(sel);

/** Видно ли элемент: есть место на экране и он не скрыт стилем. */
function shown(el) {
  return Boolean(el) && el.getClientRects().length > 0
    && getComputedStyle(el).visibility !== 'hidden';
}

/** Первый видимый из селекторов — у плавающих и прибитых панелей цели разные. */
function firstShown(...sels) {
  for (const s of sels) {
    const el = $(s);
    if (shown(el)) return el;
  }
  return null;
}

const hasItem = () => Boolean($('.album .frame'));
//: Предмет выбран, но модель могла ещё не приехать: подпись под названием
//: (класс, тип) ставится в тот же миг, что и щелчок в каталоге, а текстуры —
//: через секунды. Ждать выбора по текстурам значило держать человека на шаге
//: «выберите предмет», когда он его уже выбрал.
const picked = () => Boolean($('.title__meta')?.textContent.trim());
const section = () => root.dataset.section || 'weapons';

//: Своя картинка легла на материал (событие шлёт preview.js после загрузки).
//: Кнопка «Сохранить работу» — запасной признак: картинку могли бросить и на
//: саму модель, мимо карточки. Одной кнопки мало: у уже сохранённой работы
//: она не появляется, и шаг ждал бы вечно.
let textureSet = false;
document.addEventListener('texture:set', () => { textureSet = true; });
const hasOwnTexture = () => textureSet || shown($('#keep'));
//: Эффект открыт: у системы появились крутилки или дерево модулей.
const hasParams = () => Boolean($('#plist .params__row, #pexpert .expert__mod'));

//: Добавил ли человек что-то в дерево эксперта: число узлов запоминается при
//: входе на шаг (`enter`) и сравнивается с текущим. Дерево после правки
//: строится заново, поэтому считать надёжнее, чем следить за узлом.
const grew = (sel) => {
  let base = 0;
  const count = () => document.querySelectorAll(sel).length;
  return { enter: () => { base = count(); }, wait: () => count() > base };
};
const addedAttr = grew('#pexpert .params__row');
const addedModule = grew('#pexpert .expert__mod');
//: Модуль и группа для показа: настоящие, а не «система» — у неё свой набор
//: полей, и модуль в неё не добавить.
const someModule = () => $('#pexpert .expert__mod:not([data-group=""]) > summary');
const someGroup = () => [...document.querySelectorAll('#pexpert .expert__head')]
  .find((h) => !['система', 'children'].includes(h.textContent.trim().toLowerCase())) || null;

// ── Туры ─────────────────────────────────────────────────────────────────
// Шаг: `at` — цель (селектор или функция; нет — карточка по центру), `wait` —
// что человек должен сделать, чтобы тур пошёл дальше сам. `must` — без этого
// действия дальше показывать не о чем, и кнопки «Далее» у шага нет: иначе её
// жали, не сделав дела, и тур говорил про пустой экран. Выход есть всегда —
// «Пропустить обучение». `ready` — пока ложно, шагу нечего показать, и
// карточка говорит «загрузка». `enter` — зовётся при входе на шаг, до `wait`.
//
// Тексты — коротко и по делу: одно действие или одна мысль на шаг. Подробности
// живут в документации; тур, который пересказывает её, не дочитывают.

const TOURS = {
  main: {
    bit: 1,
    steps: [
      { title: 'Добро пожаловать',
        text: 'Покажу, как сделать скин: выбрать оружие, положить на него свою картинку и собрать мод. Это займёт минуту.' },
      { at: '.chrome__nav', title: 'Разделы',
        text: 'Оружие, шапки, эффекты и звуки. Начнём с оружия.' },
      { at: () => firstShown('#catalog', '#opencat'), title: 'Выберите оружие',
        text: 'Нажмите сюда и выберите любое оружие.',
        wait: picked, must: true },
      { at: () => firstShown('.album__box', '.viewport'), title: 'Своя картинка',
        text: 'Перетащите картинку на текстуру или дважды щёлкните по ней, чтобы выбрать файл.',
        ready: hasItem, wait: hasOwnTexture, must: true },
      { at: '.viewport', title: 'Превью',
        text: 'Так скин будет выглядеть в игре. Модель можно крутить мышкой.' },
      { at: '.half__bar--scenes', title: 'В руках',
        text: 'Можно посмотреть оружие от первого лица.' },
      { at: '.modes', title: 'Вид',
        text: 'Показывать текстуру, модель или обе сразу.' },
      { at: () => $('.album .frame.is-current .frame__tool:not(.frame__off)'),
        title: 'Своя настройка',
        text: 'Шестерёнка задаёт отдельные настройки для этой текстуры. Нажмите её ещё раз, чтобы вернуться к общим.' },
      { at: '.half--flat .acts', title: 'Материал',
        text: 'Правка материала и эффекты вроде свечения. Для обычного скина можно не трогать.' },
      { at: '#warpaint', title: 'War Paint',
        text: 'Раскраска из игры, собранная в текстуру. Поверх можно дорисовать своё.' },
      { at: () => ([...document.querySelectorAll('.teams > *')].some(shown) ? $('.teams') : null),
        title: 'RED и BLU',
        text: 'Отдельная текстура для RED и BLU.' },
      { at: '#model-acts', title: 'Модель',
        text: 'Можно заменить модель на свою или раскрасить её по частям.' },
      // Панель параметров в плавающем режиме спрятана, и человек не знает, что
      // флаги живут за этой кнопкой. Поэтому просим нажать; у прибитых панелей
      // она и так на экране — шаг пропускается.
      { at: () => (shown($('#build')) ? null : $('#opensettings')), title: 'Параметры',
        text: 'Нажмите «Параметры», чтобы открыть настройки сборки.',
        wait: () => shown($('#build')), must: true },
      { at: '#build', title: 'Настройки сборки',
        text: 'Обычно хватает выбрать разрешение. Остальное можно оставить как есть. Закрывается той же кнопкой.' },
      { at: '#buildvpk', title: 'Сборка',
        text: 'Соберите мод и положите файл в папку tf/custom игры.' },
      { at: '#opentools', title: 'Инструменты',
        text: 'Извлечь оригинальную текстуру, UV-шаблон и прочее.' },
      { at: '#opencfg', title: 'Настройки',
        text: 'Путь к игре, язык и тема. Здесь же можно пройти обучение ещё раз.' },
      { title: 'Готово',
        text: 'Остальное подскажу по ходу, когда дойдёте.' },
    ],
  },

  parts: {
    bit: 2,
    when: () => shown($('#partspaint')),
    steps: [
      { at: '#partsbar', title: 'Части',
        text: 'Модель поделена на части. Наведите на номер, чтобы увидеть, где она.' },
      { at: '#partspaint [data-tool="image"]', title: 'Картинка',
        text: 'Щёлкните по части, чтобы положить на неё картинку.' },
      { at: '#partspaint [data-tool="brush"]', title: 'Кисть',
        text: 'Красит часть в выбранный цвет.' },
      { at: '#parts-swatch', title: 'Цвет',
        text: 'Выбор цвета. Там же градиент и пипетка.' },
      { at: '#partspaint [data-tool="cut"]', title: 'Ножницы',
        text: 'Делят часть на части поменьше.' },
      { at: '#partspaint [data-tool="edge"]', title: 'Окантовка',
        text: 'Обводит края покрашенных частей.' },
      { at: '#parts-random', title: 'Кубик и ластик',
        text: 'Случайная раскраска и сброс. Ctrl+Z отменяет.' },
      { at: '#parts-done', title: 'Готово',
        text: 'Выйти из режима частей.' },
    ],
  },

  fit: {
    bit: 4,
    when: () => shown($('#fitpanel')),
    steps: [
      { at: '#fitpanel [data-tool="translate"]', title: 'Подгонка',
        text: 'Подгоните свою модель под полупрозрачный оригинал. G — двигать, R — вращать, S — масштаб.' },
      { at: '#fitpanel .ptools__opts', title: 'Числами',
        text: 'То же самое, только точно.' },
      { at: '#fit-done', title: 'Готово',
        text: 'Закончить подгонку.' },
    ],
  },

  // С входа в раздел, а не с выбранной шапки: иначе тур не видел тот, кому он
  // нужнее всех, — кто не понял, как шапку выбрать.
  hats: {
    bit: 8,
    when: () => section() === 'hats',
    steps: [
      { at: () => firstShown('#catalog', '#opencat'), title: 'Шапки',
        text: 'Выберите шапку. Фильтр «Куда» сужает список: голова, лицо, тело.',
        wait: picked, must: true },
      { at: () => firstShown('.album__box', '.viewport'), title: 'Своя картинка',
        text: 'Всё как с оружием: перетащите картинку на текстуру.',
        ready: hasItem },
      { at: '#hatstyles', title: 'Стили',
        text: 'У шапки несколько стилей. Каждый можно раскрасить отдельно.' },
      { at: '.half__bar--scenes [data-scene="wear"]', title: 'На модели',
        text: 'Посмотрите шапку прямо на персонаже. Под кадром можно выбрать класс и оружие в руках.' },
      { at: '#paint', title: 'Краска',
        text: 'Показывает, как шапка будет выглядеть с краской из игры.' },
      { at: '#buildvpk', title: 'Сборка',
        text: 'Если шапку носят несколько классов, при сборке спрошу, для каких.' },
    ],
  },

  particles: {
    bit: 16,
    when: () => section() === 'particles',
    steps: [
      { at: () => firstShown('#catalog', '#opencat'), title: 'Эффекты',
        text: 'Выберите эффект. Необычные эффекты подписаны именами из игры, поиск находит и по имени системы.',
        wait: picked, must: true },
      { at: '#particles', title: 'Превью',
        text: 'Эффект играет так же, как в игре. Мышью можно крутить.',
        ready: hasParams },
      { at: '#plist', title: 'Обычный режим',
        text: 'Главное: цвет, размер, скорость, время жизни. Правки сразу видно в кадре.' },
      { at: '.params__modes [data-pmode="expert"]', title: 'Эксперт',
        text: 'Все модули и параметры файла как есть. Нажмите, чтобы посмотреть.',
        wait: () => shown($('#pexpert')) },
      { at: '#pfind', title: 'Поиск',
        text: 'Параметров бывает под две сотни. Наберите часть имени, например radius.' },
      { at: someModule, title: 'Новый параметр',
        text: 'Щёлкните правой кнопкой по названию модуля и выберите «Добавить параметр…». В списке только то, чего в модуле ещё нет, а значение подставится как в игре.',
        ...addedAttr },
      { at: someGroup, title: 'Новый модуль',
        text: 'Модуль — это целое поведение: вращение, цвет по времени, сила. Правая кнопка по заголовку группы — «Добавить модуль…».',
        ...addedModule },
      { at: '#pexpert', title: 'Правка',
        text: 'Правая кнопка по параметру — удалить или вернуть как в игре. Изменённое подсвечено.' },
      { at: () => firstShown('#catalog', '#opencat'), title: 'Системы',
        text: 'Эффект собран из систем. Правая кнопка по системе — переименовать, дублировать, добавить дочернюю.' },
      { at: '.album__box', title: 'Текстуры',
        text: 'Текстуры эффекта. Перетащите картинку, чтобы заменить.' },
      { at: '#pacts', title: 'Просмотр',
        text: 'Перезапуск, пауза и замедление. Ctrl+Z отменяет правку.' },
      { at: '#pcpbtn', title: 'Точки',
        text: 'Контрольные точки: откуда эффект растёт и как движется. Можно повесить его на модель.' },
      { at: '#buildvpk', title: 'Сборка',
        text: 'Соберите эффект в мод.' },
    ],
  },

  // War Paint — своя панель со своими понятиями (износ, сид, детали);
  // главный тур только показывает кнопку.
  warpaint: {
    bit: 64,
    when: () => shown($('#warpaintpanel')),
    steps: [
      { at: '.wpanel__list', title: 'War Paint',
        text: 'Выберите раскраску, она сразу ляжет на модель.',
        wait: () => Boolean($('.wpanel__row[aria-selected="true"]')) },
      { at: '.wpanel__controls', title: 'Износ и сид',
        text: 'Как в игре. Сид решает, как узор ляжет на оружие.' },
      { at: '.wpanel__parts', title: 'Детали',
        text: 'Узоры разложены по деталям модели. Их можно перемешать или раздать вручную.' },
      { at: '.wpanel__apply', title: 'Нанести',
        text: 'Раскраска станет обычной текстурой. Поверх неё можно дорисовать своё.' },
    ],
  },

  sounds: {
    bit: 32,
    when: () => section() === 'sounds' && shown($('#snd-list')),
    steps: [
      { at: '#snd-section', title: 'Звуки',
        text: 'Выберите, что заменить: оружие, голоса или звуки мира.' },
      { at: '#snd-facets', title: 'Фильтры',
        text: 'Помогают быстро найти нужный звук.' },
      { at: '#snd-list', title: 'Замена',
        text: 'Перетащите свой звук на строку или нажмите «Свой файл».' },
      { at: '.sounds__foot', title: 'Сборка',
        text: 'Все заменённые звуки соберутся в один мод.' },
    ],
  },
};

// ── Отметка «пройден» ────────────────────────────────────────────────────

let done = 0;

/** Маска из настроек. Зовётся при старте (applyLook) — дальше её ведёт тур. */
export function setToursDone(mask) { done = Number(mask) || 0; }

function markDone(name) {
  done |= TOURS[name].bit;
  api.setUiState('tours_done', done);
}

// ── Показ ────────────────────────────────────────────────────────────────

const spot = document.createElement('div');
spot.className = 'tour__spot';
spot.hidden = true;
const card = document.createElement('div');
card.className = 'tour__card';
card.hidden = true;
card.setAttribute('role', 'dialog');
card.innerHTML = `
  <div class="tour__bar"><i class="tour__fill"></i></div>
  <div class="tour__body">
    <span class="mono tour__count"></span>
    <p class="tour__title"></p>
    <p class="tour__text"></p>
    <p class="tour__note tour__wait" hidden><i class="tour__pulse"></i><span>Продолжу, когда сделаете</span></p>
    <p class="tour__note tour__load" hidden><i class="tour__spin"></i><span>Загрузка модели…</span></p>
  </div>
  <div class="tour__acts">
    <button class="textbtn textbtn--sm tour__skip" type="button">Пропустить обучение</button>
    <button class="textbtn textbtn--sm tour__back" type="button">Назад</button>
    <button class="btn--primary tour__next" type="button">Далее</button>
  </div>
  <i class="tour__caret"></i>`;
document.body.append(spot, card);

//: Открытые туры: последний показан. Тур, который сработал посреди другого
//: (человек нажал «Разделить на части» во время главного), встаёт сверху, а
//: после него главный продолжается с того же шага.
const stack = [];
const current = () => stack[stack.length - 1];

//: Цель текущего шага и была ли задача шага уже сделана при входе: сам тур
//: идёт дальше только когда дело сделали ПРИ НЁМ, иначе «Назад» к такому
//: шагу тут же отбрасывал бы вперёд.
let target = null;
let waitAtEntry = false;
let frame = 0;

function resolve(step) {
  if (!step.at) return null;
  const el = typeof step.at === 'function' ? step.at() : $(step.at);
  return shown(el) ? el : null;
}

/** Ближайший шаг с видимой целью в направлении `dir` от `from`. */
function seek(steps, from, dir) {
  for (let i = from; i >= 0 && i < steps.length; i += dir) {
    if (!steps[i].at || resolve(steps[i])) return i;
  }
  return -1;
}

function show(dir = 1) {
  const run = current();
  if (!run) { hide(); return; }
  const steps = TOURS[run.name].steps;
  const i = seek(steps, run.i, dir);
  if (i < 0) {
    if (dir < 0) { run.i = seek(steps, 0, 1); show(); return; }
    // Тур, которого человек так и не увидел (цели не на экране), пройденным
    // не считается: иначе он больше не появился бы никогда.
    if (run.seen) finish(); else { stack.pop(); show(); }
    return;
  }
  run.i = i;
  run.seen = true;
  const step = steps[i];

  aim(resolve(step));
  if (target) target.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  step.enter?.();
  waitAtEntry = Boolean(step.wait && step.wait());

  card.querySelector('.tour__title').textContent = t(step.title);
  card.querySelector('.tour__text').textContent = t(step.text);
  card.querySelector('.tour__count').textContent = `${i + 1} / ${steps.length}`;
  card.querySelector('.tour__fill').style.width = `${(i + 1) / steps.length * 100}%`;
  showNotes(step);
  // Смена шага — короткое проявление текста: без него карточка, оставшаяся
  // на месте, выглядела так, будто ничего не произошло.
  const body = card.querySelector('.tour__body');
  body.classList.remove('is-new');
  void body.offsetWidth;
  body.classList.add('is-new');
  card.querySelector('.tour__back').hidden = seek(steps, i - 1, -1) < 0;
  // Дело уже сделано к приходу на шаг (тур перезапустили с открытым
  // предметом) — держать человека незачем.
  card.querySelector('.tour__next').hidden = Boolean(step.must && !waitAtEntry);
  const last = seek(steps, i + 1, 1) < 0;
  card.querySelector('.tour__next').textContent = t(last ? 'Готово' : 'Далее');
  // Появившаяся карточка встаёт на место сразу, а не въезжает из угла.
  if (card.hidden) card.classList.add('is-placing');
  spot.hidden = false;
  card.hidden = false;
  if (!frame) frame = requestAnimationFrame(tick);
}

/**
 * Строки под текстом: «сделайте это» у шага, который ждёт действия, и
 * «загрузка» у шага, которому ещё нечего показать. Пятно у ждущего шага
 * пульсирует — туда и нажимать.
 */
function showNotes(step) {
  const loading = Boolean(step.ready && !step.ready());
  const waiting = Boolean(step.wait && !waitAtEntry);
  const load = card.querySelector('.tour__load');
  const wait = card.querySelector('.tour__wait');
  if (load.hidden === !loading && wait.hidden === !(waiting && !loading)) return;
  load.hidden = !loading;
  wait.hidden = !(waiting && !loading);
  spot.classList.toggle('is-waiting', waiting && !loading);
}

/** Переводит подсветку на новую цель (null — карточка по центру). */
function aim(el) {
  if (el === target) return;
  if (target) target.removeAttribute('data-tour-target');
  target = el;
  if (target) target.setAttribute('data-tour-target', '');
}

function hide() {
  aim(null);
  spot.hidden = true;
  card.hidden = true;
  cancelAnimationFrame(frame);
  frame = 0;
}

//: Последняя раскладка: пишем в стили только изменившееся, кадр за кадром.
let laid = '';

/**
 * Каждый кадр: подсветка ходит за целью (панели выезжают, окно меняет
 * размер), и проверяется, не сделал ли человек то, о чём просит шаг.
 */
function tick() {
  frame = requestAnimationFrame(tick);
  const run = current();
  if (!run) return;
  const step = TOURS[run.name].steps[run.i];
  if (step.wait && !waitAtEntry && step.wait()) { next(); return; }
  showNotes(step);

  // Цель ищется заново каждый кадр: человек открыл каталог — подсветка
  // переходит с кнопки на него; цель пропала (каталог закрылся после
  // выбора) — карточка ждёт по центру.
  aim(resolve(step));
  const r = target ? target.getBoundingClientRect() : null;
  const key = r ? `${r.left}|${r.top}|${r.width}|${r.height}` : '-';
  const size = `${innerWidth}|${innerHeight}|${card.offsetHeight}`;
  if (key + size === laid) return;
  laid = key + size;
  layout(r);
}

function layout(r) {
  const pad = 6;
  if (r) {
    Object.assign(spot.style, {
      left: `${r.left - pad}px`, top: `${r.top - pad}px`,
      width: `${r.width + pad * 2}px`, height: `${r.height + pad * 2}px`,
    });
  } else {
    // Без цели — пятно схлопывается в центр: затемнён весь экран.
    Object.assign(spot.style, {
      left: `${innerWidth / 2}px`, top: `${innerHeight / 2}px`, width: '0px', height: '0px',
    });
  }

  const W = innerWidth, H = innerHeight, m = 12, gap = 18;
  const cw = card.offsetWidth, ch = card.offsetHeight;
  const clampX = (x) => Math.max(m, Math.min(W - cw - m, x));
  const clampY = (y) => Math.max(m, Math.min(H - ch - m, y));
  let x = (W - cw) / 2, y = (H - ch) / 2, side = '';
  if (r) {
    // Справа, слева, снизу, сверху — первое, куда карточка влезает целиком.
    // Сторона — та, которой карточка смотрит на цель: там стоит уголок.
    const cy = clampY(r.top + r.height / 2 - ch / 2);
    const cx = clampX(r.left + r.width / 2 - cw / 2);
    const beside = [
      [r.right + gap, cy, 'left', (px) => px + cw <= W - m],
      [r.left - gap - cw, cy, 'right', (px) => px >= m],
    ];
    const across = [
      [cx, r.bottom + gap, 'top', (_, py) => py + ch <= H - m],
      [cx, r.top - gap - ch, 'bottom', (_, py) => py >= m],
    ];
    // Широкая плоская цель (ряд разделов, подвал) — карточка под ней или
    // над ней: сбоку она уезжала к краю экрана, далеко от середины цели.
    const tries = r.width > r.height * 2 ? [...across, ...beside] : [...beside, ...across];
    const fit = tries.find(([px, py, , ok]) => ok(px, py));
    // Цель во весь экран (кадр модели) — в угол, поверх неё, без уголка.
    [x, y, side] = fit ? fit : [W - cw - m, H - ch - m, ''];
    // Уголок — напротив середины цели, но не у самого края карточки.
    const along = side === 'left' || side === 'right'
      ? r.top + r.height / 2 - y : r.left + r.width / 2 - x;
    const span = side === 'left' || side === 'right' ? ch : cw;
    card.style.setProperty('--caret', `${Math.max(18, Math.min(span - 18, along))}px`);
  }
  card.dataset.side = side;
  card.style.left = `${x}px`;
  card.style.top = `${y}px`;
  if (card.classList.contains('is-placing')) {
    requestAnimationFrame(() => card.classList.remove('is-placing'));
  }
}

// ── Навигация ────────────────────────────────────────────────────────────

function next() {
  const run = current();
  if (!run) return;
  run.i += 1;
  show(1);
}

function back() {
  const run = current();
  if (!run) return;
  run.i -= 1;
  show(-1);
}

/** Тур закончен или пропущен: отмечаем и возвращаемся к прерванному. */
function finish() {
  const run = stack.pop();
  if (run) markDone(run.name);
  laid = '';
  if (stack.length) show(); else hide();
}

/** «Пропустить обучение» — всё, а не только верхний тур: вложенный тур
 *  сверху главного иначе возвращал бы главный, хотя человек просил конец. */
function skipAll() {
  while (stack.length) markDone(stack.pop().name);
  laid = '';
  hide();
}

card.querySelector('.tour__next').addEventListener('click', next);
card.querySelector('.tour__back').addEventListener('click', back);
card.querySelector('.tour__skip').addEventListener('click', skipAll);

/** Запускает тур (поверх текущего, если он есть). */
export function startTour(name) {
  if (!TOURS[name] || stack.some((r) => r.name === name)) return;
  stack.push({ name, i: 0 });
  laid = '';
  show();
}

/** Главный тур при первом старте. */
export function startFirstRun() {
  if (!(done & TOURS.main.bit)) startTour('main');
}

/** Сброс из настроек: все туры заново, начиная с главного. */
export function replayTours() {
  done = 0;
  api.setUiState('tours_done', 0);
  startTour('main');
}

// Туры мест: срабатывают, когда человек впервые туда попал. Опрос раз в
// секунду вместо подписки на каждую панель — туры не должны знать, как
// устроены модули, которые они описывают.
// ponytail: опрос по таймеру; перейти на события, если туров станет много.
setInterval(() => {
  for (const [name, tour] of Object.entries(TOURS)) {
    if (tour.when && !(done & tour.bit) && tour.when()) startTour(name);
  }
}, 1000);
