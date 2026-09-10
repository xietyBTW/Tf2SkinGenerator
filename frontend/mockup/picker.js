/*
 * Свой выбор цвета вместо системного диалога Windows.
 *
 * Модуль самодостаточен: подключить его — значит перехватить щелчки по всем
 * <input type="color"> на странице. Сам input остаётся на месте, у него
 * по-прежнему читают .value и слушают input/change, поэтому отказ этого кода
 * означает лишь возврат к системному окну, а не сломанную страницу.
 */

// ── Выбор цвета ─────────────────────────────────────────────────────────
// <input type="color"> открывает диалог Windows — единственное окно в
// приложении, нарисованное не нами. Перехватываем щелчок и показываем свой
// поповер, а сам input оставляем на месте: у него читают .value и слушают
// его события в трёх местах, и подмена элемента заставила бы править их все.
// Заодно при отказе этого кода остаётся рабочий системный диалог.

const PICKER = { input: null, box: null, h: 0, s: 0, v: 0 };

export function hsvToHex(h, s, v) {
  const part = (n) => {
    const k = (n + h / 60) % 6;
    const x = v - v * s * Math.max(0, Math.min(k, 4 - k, 1));
    return Math.round(x * 255).toString(16).padStart(2, '0');
  };
  return '#' + part(5) + part(3) + part(1);
}

function hexToHsv(hex) {
  const n = parseInt(hex.slice(1), 16) || 0;
  const r = ((n >> 16) & 255) / 255;
  const g = ((n >> 8) & 255) / 255;
  const b = (n & 255) / 255;
  const max = Math.max(r, g, b);
  const d = max - Math.min(r, g, b);
  let h = 0;
  if (d) {
    if (max === r) h = ((g - b) / d + 6) % 6;
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h *= 60;
  }
  return { h, s: max ? d / max : 0, v: max };
}

/**
 * Тянуть можно за любую точку полосы, а не только за метку.
 *
 * Захват указателя — чтобы протяжка не обрывалась, когда курсор ушёл за край
 * квадрата: цвет там продолжает выбираться по ближайшему краю.
 */
function pickerDrag(el, onMove) {
  const at = (e) => {
    const r = el.getBoundingClientRect();
    onMove(Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)),
           Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)));
  };
  el.addEventListener('pointerdown', (e) => { el.setPointerCapture(e.pointerId); at(e); });
  el.addEventListener('pointermove', (e) => {
    if (el.hasPointerCapture(e.pointerId)) at(e);
  });
  el.addEventListener('pointerup', (e) => {
    el.releasePointerCapture(e.pointerId);
    commitPicker();
  });
}

/** Поповер один на всё приложение: строится при первом открытии. */
function pickerBox() {
  if (PICKER.box) return PICKER.box;
  const box = document.createElement('div');
  box.className = 'picker';
  box.hidden = true;
  box.innerHTML = '<div class="picker__sv"><i class="picker__dot"></i></div>'
    + '<div class="picker__hue"><i class="picker__bar"></i></div>'
    + '<div class="picker__foot"><span class="picker__now"></span>'
    + '<input class="picker__hex" maxlength="7" spellcheck="false"></div>'
    + '<div class="picker__extra"></div>';
  document.body.appendChild(box);
  PICKER.box = box;

  pickerDrag(box.querySelector('.picker__sv'), (x, y) => {
    PICKER.s = x;
    PICKER.v = 1 - y;
    pushPicker();
  });
  pickerDrag(box.querySelector('.picker__hue'), (x) => {
    PICKER.h = x * 360;
    pushPicker();
  });

  // Точный код цвета нужен тем, кто подбирает его не на глаз, а по образцу.
  const hex = box.querySelector('.picker__hex');
  hex.addEventListener('input', () => {
    if (!/^#[0-9a-fA-F]{6}$/.test(hex.value)) return;
    Object.assign(PICKER, hexToHsv(hex.value));
    pushPicker(true);   // поле уже показывает нужное — не сбиваем каретку
  });
  hex.addEventListener('change', commitPicker);
  return box;
}

/** Перерисовывает поповер по текущему HSV и отдаёт значение полю. */
function pushPicker(keepHex) {
  const box = PICKER.box;
  const color = hsvToHex(PICKER.h, PICKER.s, PICKER.v);
  box.querySelector('.picker__sv').style.background =
    'linear-gradient(to top, #000, rgba(0,0,0,0)),'
    + 'linear-gradient(to right, #fff, hsl(' + PICKER.h + ' 100% 50%))';
  const dot = box.querySelector('.picker__dot');
  dot.style.left = (PICKER.s * 100) + '%';
  dot.style.top = ((1 - PICKER.v) * 100) + '%';
  box.querySelector('.picker__bar').style.left = (PICKER.h / 360 * 100) + '%';
  box.querySelector('.picker__now').style.background = color;
  if (!keepHex) box.querySelector('.picker__hex').value = color;
  if (!PICKER.input) return;
  PICKER.input.value = color;
  PICKER.input.dispatchEvent(new Event('input', { bubbles: true }));
}

/**
 * Фиксация выбора.
 *
 * Отдельно от pushPicker и только по отпусканию: change у цветов частиц уходит
 * в Python, и на одной протяжке таких событий набралось бы полсотни. Ровно так
 * же ведёт себя нативное поле — input по ходу, change по завершении.
 */
function commitPicker() {
  if (PICKER.input) PICKER.input.dispatchEvent(new Event('change', { bubbles: true }));
}

/**
 * Чужой блок в подвале поповера и место, откуда он взят.
 *
 * Нужен затем, что у цвета кисти есть продолжение — переход из первого цвета
 * во второй: спрашивать его отдельным окном значило бы, что человек задаёт
 * цвет в одном месте, а решает, цвет это или переход, в другом. Блок
 * ПЕРЕЕЗЖАЕТ сюда и возвращается домой при закрытии: копия разошлась бы с
 * оригиналом, а `getElementById` у отсоединённого узла ничего не находит.
 */
let extraHome = null;

function setExtra(node) {
  const slot = PICKER.box.querySelector('.picker__extra');
  if (extraHome && slot.firstChild) extraHome.appendChild(slot.firstChild);
  extraHome = null;
  if (!node || node.parentNode === slot) return;
  extraHome = node.parentNode;
  slot.appendChild(node);
}

function openPicker(input, opts) {
  const box = pickerBox();
  PICKER.input = input;
  Object.assign(PICKER, hexToHsv(input.value));
  box.hidden = false;
  setExtra((opts && opts.extra) || null);
  pushPicker();

  // Поповер встаёт у ЯКОРЯ, а им не всегда служит само поле: цвет кисти
  // задаётся квадратом в палитре, а поле при нём только хранит значение.
  const r = ((opts && opts.anchor) || input).getBoundingClientRect();
  const w = box.offsetWidth;
  const h = box.offsetHeight;
  // Слева от якоря, если справа не помещается: палитра стоит у правого края
  // окна, и поповер иначе наезжал бы на неё саму.
  box.style.left = (r.right + w + 8 > window.innerWidth && r.left - w - 6 >= 8
    ? r.left - w - 6
    : Math.max(8, Math.min(window.innerWidth - w - 8, r.left))) + 'px';
  // Под полем, а если там не помещается — над ним: палитра частей стоит у
  // самого низа экрана, и снизу места нет никогда.
  box.style.top = (r.bottom + h + 8 < window.innerHeight
    ? r.bottom + 6 : Math.max(8, r.top - h - 6)) + 'px';
}

function closePicker() {
  if (PICKER.box) {
    setExtra(null);          // блок уезжает домой, иначе он пропал бы со страницы
    PICKER.box.hidden = true;
  }
  PICKER.input = null;
}

/**
 * Открывает выбор цвета не по щелчку в само поле.
 *
 * `anchor` — у чего встать, `extra` — что показать под выбором.
 */
export function pickColor(input, opts) { openPicker(input, opts); }

/** Переводит открытый поповер на другое поле: тот же выбор, другой цвет. */
export function pickInto(input) {
  if (!PICKER.box || PICKER.box.hidden) return;
  PICKER.input = input;
  Object.assign(PICKER, hexToHsv(input.value));
  pushPicker();
}

/** Закрывает поповер снаружи: тем же путём, что и щелчок мимо. */
export function closeColor() { closePicker(); }

//: Взведена ли пипетка. Пока да, щелчок по кадру поповер не закрывает:
//: пипеткой как раз и щёлкают мимо него — по модели и по текстуре, — а
//: закрывшийся выбор цвета отнимал бы то, ради чего его открыли. Владелец
//: состояния один — выбранный инструмент частей (см. showToolCursor).
let dropping = false;

/** Сообщает поповеру, что цвет сейчас берут пипеткой. */
export function armDrop(on) { dropping = !!on; }

/** Открыт ли поповер для этого поля. */
export function picking(input) {
  return Boolean(PICKER.box) && !PICKER.box.hidden
    && (input === undefined || PICKER.input === input);
}

// Фаза перехвата: отменённый здесь click не даёт браузеру открыть системный
// диалог, и до обработчиков страницы событие уже не доходит.
document.addEventListener('click', (e) => {
  const input = e.target.closest && e.target.closest('input[type="color"]');
  if (input) { e.preventDefault(); openPicker(input); return; }
  // Щелчок по тому, ЧЕМ открыли, закрывает поповер сам — иначе он закрылся
  // бы здесь и тут же открылся заново, и повторный щелчок ничего не делал.
  // Кадр при взведённой пипетке — не «щелчок мимо»: цвет берут именно там.
  // Всё остальное закрывает поповер по-прежнему, иначе он оставался бы висеть
  // после ухода в другую часть окна.
  if (PICKER.input && !(dropping && e.target.closest('.album'))
      && !e.target.closest('.picker')
      && !e.target.closest('.picker-anchor')) closePicker();
}, true);

document.addEventListener('keydown', (e) => {
  const input = e.target.closest && e.target.closest('input[type="color"]');
  if (input && (e.key === 'Enter' || e.key === ' ')) {
    e.preventDefault();
    openPicker(input);
    return;
  }
  // Пока открыт поповер, Escape закрывает его, а не диалог за ним.
  if (e.key === 'Escape' && PICKER.input) { e.stopPropagation(); closePicker(); }
}, true);

// Поповер прибит к месту поля: при прокрутке и смене размера он уезжает.
window.addEventListener('resize', closePicker);
// Прокручивается не страница, а списки внутри неё (альбом, дерево свойств
// эффекта), поэтому в фазе перехвата: обычный scroll не всплывает.
window.addEventListener('scroll', closePicker, true);
