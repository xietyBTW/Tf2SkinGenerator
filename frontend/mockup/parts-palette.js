/*
 * Палитра режима частей: цвет кисти и переход из первого цвета во второй
 * (полоса с краями и серединой, ручка направления), сила тонировки, «точный
 * цвет», окантовка и случайная раскраска
 *
 * Всё это - настройки КИСТИ: они едут вместе с мазком (paintSpec), а не
 * задаются общими на предмет.
 */

import * as api from './api.js';
import { t } from './i18n.js';
import { pickColor, pickInto, picking, closeColor, hsvToHex } from './picker.js';
import { P, hintParts } from './parts-state.js';
import { colorParts } from './parts.js';

let gradientOn = false;   // красить переходом из первого цвета во второй
let gradientAngle = 0;    // направление перехода в градусах: 0 - сверху вниз
let gradientEnd = 1;      // какой конец перехода правит выбор цвета
//: Форма перехода в долях места части: где он начинается, где кончается и где
//: цвета смешаны поровну. Края задают ширину перелива (сдвинул друг к другу -
//: резче), середина - перевес одного цвета над другим
let gradStart = 0;
let gradEnd = 1;
let gradMid = 0.5;

/**
 * Палитра: выбранный цвет красит щелчком по куску модели
 *
 * Цвет, а не диалог с файлом, стоит первым: перекрасить деталь хочется чаще,
 * чем нарисовать на ней свою картинку, и это происходит мгновенно.
 */
export function showPalette(res) {
  document.getElementById('partspaint').hidden = false;

  const tint = document.getElementById('part-tint');
  tint.value = Math.round((res.tint || 1) * 100);
  document.getElementById('part-exact').checked = Boolean(res.exact);

  // Окантовка живёт в предмете: полоса должна показать то, что уже задано, а
  // не то, что осталось на контролах от прошлого предмета
  const edgeOn = (res.edge || 0) > 0;
  document.getElementById('parts-edge').classList.toggle('is-active', edgeOn);
  document.getElementById('part-edge-color').hidden = !edgeOn;
  document.getElementById('part-edge-box').hidden = !edgeOn;
  if (edgeOn) {
    document.getElementById('part-edge-width').value = Math.round(res.edge * 1000);
  }
  if (res.edge_color) document.getElementById('part-edge-color').value = res.edge_color;
  showColor();
}

/** Палитра закрылась: переход и окантовка - в начальное состояние */
export function resetPalette() {
  gradientOn = false;
  setGradientAngle(0);
  document.getElementById('parts-grad').classList.remove('is-active');
  document.getElementById('parts-grad-aim').hidden = true;
  gradStart = 0;
  gradEnd = 1;
  gradMid = 0.5;
  gradientEnd = 1;
  document.getElementById('parts-edge').classList.remove('is-active');
  document.getElementById('part-edge-color').hidden = true;
  document.getElementById('part-edge-box').hidden = true;
}

/**
 * Показывает, чем красят: квадраты в колонке
 *
 * Квадраты внахлёст - как в редакторах изображений, второй появляется только
 * с градиентом, иначе он обещал бы цвет, которым ничего не красится.
 */
function showColor() {
  const second = document.getElementById('part-color2').value;
  document.getElementById('parts-swatch-fg').style.background = P.brushColor;
  document.getElementById('parts-swatch-bg').style.background = second;
  document.getElementById('parts-swatch').classList.toggle('is-grad', gradientOn);
  showRamp(second);
}

/**
 * Полоса перехода: что получится на детали
 *
 * Середину рисуем ОТДЕЛЬНОЙ точкой полусмеси, а не одним отрезком: у CSS
 * такой ручки нет, а без неё полоса показывала бы ровный переход там, где на
 * модели он уже перекошен.
 */
function showRamp(second) {
  const ramp = document.getElementById('parts-ramp');
  if (!ramp) return;
  const at = (x) => (x * 100).toFixed(1) + '%';
  const middle = gradStart + (gradEnd - gradStart) * gradMid;
  ramp.style.background = 'linear-gradient(90deg,'
    + P.brushColor + ' 0 ' + at(gradStart) + ','
    + mixColors(P.brushColor, second) + ' ' + at(middle) + ','
    + second + ' ' + at(gradEnd) + ' 100%)';
  const place = { start: gradStart, mid: middle, end: gradEnd };
  ramp.querySelectorAll('.parts__stop').forEach((b) => {
    b.style.left = at(place[b.dataset.stop]);
  });
}

/** Половина пути между двумя «#rrggbb» - только для показа полосы */
function mixColors(one, two) {
  const half = (at) => {
    const a = parseInt(one.substr(at, 2), 16);
    const b = parseInt(two.substr(at, 2), 16);
    return Math.round((a + b) / 2).toString(16).padStart(2, '0');
  };
  return '#' + half(1) + half(3) + half(5);
}

/**
 * Чем красить: сплошной цвет или градиент - и КАК, со всеми настройками кисти
 *
 * Настройки едут вместе с мазком, а не берутся общими на предмет: переключишь
 * потом «точный цвет» или окантовку - уже покрашенное останется таким, каким
 * его сделали. Так это и работает в редакторах: кисть меняешь для следующего
 * мазка, а не для всех прошлых
 *
 * Градиент строится по месту ЧАСТИ на развёртке, поэтому странице достаточно
 * назвать два цвета и направление - остальное считает Python.
 */
export function paintSpec(color) {
  const edgeOn = document.getElementById('parts-edge').classList.contains('is-active');
  const spec = {
    color,
    strength: Number(document.getElementById('part-tint').value) / 100,
    exact: document.getElementById('part-exact').checked,
    edge: edgeOn
      ? Number(document.getElementById('part-edge-width').value) / 1000 : 0,
    edge_color: document.getElementById('part-edge-color').value,
  };
  if (!gradientOn) return spec;
  return {
    ...spec,
    color2: document.getElementById('part-color2').value,
    angle: gradientAngle,
    start: gradStart,
    end: gradEnd,
    mid: gradMid,
  };
}

/**
 * Правка формы перехода задним числом
 *
 * Без неё ползунки говорили бы только о БУДУЩЕЙ покраске: покрутил - на модели
 * ничего, а понять, что делает середина, можно только глядя на деталь. Цвета у
 * каждой части свои, поэтому меняем ровно форму - угол, края и середину.
 */
async function applyGradientShape() {
  const fresh = {};
  (P.list || []).forEach((part) => {
    // Цвет части всегда приходит записью, градиент - та, где есть второй цвет
    if (part.color && part.color.color2) {
      fresh[part.id] = { ...part.color, angle: gradientAngle,
                         start: gradStart, end: gradEnd, mid: gradMid };
    }
  });
  if (Object.keys(fresh).length) await colorParts(fresh);
}

document.getElementById('part-color').addEventListener('input', (e) => {
  P.brushColor = e.target.value;
  showColor();
  // Про щелчок по частям говорим только с кистью в руке: выбор цвета её больше
  // не берёт, и обещать покраску от щелчка было бы враньём
  hintParts(P.tool === 'brush'
    ? 'Щёлкай по частям модели - покрасятся в этот цвет'
    : 'Цвет выбран - возьми кисть, чтобы им красить');
});

// Второй цвет виден на заднем квадрате колонки: там же, где первый
document.getElementById('part-color2').addEventListener('input', showColor);

// Сила тонировки общая на предмет: тянуть ползунок ради одной части и потом
// ради другой - не то, чего от него ждут
document.getElementById('part-tint').addEventListener('change', () => {
  // Пустой набор - «запомни настройку кисти»: уже покрашенные части держат
  // свои, те, что были в момент мазка
  if (P.material !== null) colorParts({});
});

// «Точный цвет» - настройка КИСТИ, как и сила: уже покрашенное помнит свою
// (см. paintSpec), здесь её только запоминаем. Python перекрашивает лишь
// старые работы, где мазок своих настроек не хранит
document.getElementById('part-exact').addEventListener('change', () => {
  if (P.material === null) return;
  hintParts(document.getElementById('part-exact').checked
    ? 'Цвет ложится ровно как в палитре; фактура остаётся за счёт теней'
    : 'Цвет смешивается с оригиналом - так деталь выглядит естественнее');
  colorParts({});
});

// Окантовка тоже настройка КИСТИ: обводятся те части, которые красят после
// её включения, а не всё сделанное разом

/**
 * Цвета для случайной раскраски
 *
 * Оттенок берётся с шагом ЗОЛОТОГО СЕЧЕНИЯ по цветовому кругу
 * (137.5°): соседние куски всегда далеко друг от друга по цвету, и при этом
 * ни один шаг не повторяет предыдущие - на любом числе частей раскладка
 * получается разной. Просто `random()` на каждую часть так не умеет: соседи
 * то и дело выпадают почти одинаковыми, и куски сливаются
 *
 * Насыщенность и светлота гуляют в узких пределах: это КРАСКА на модели, а не
 * неоновая подсветка - совсем случайные дают то кислоту, то грязь.
 */
function randomColors(count) {
  let hue = Math.random() * 360;
  const out = [];
  for (let i = 0; i < count; i++) {
    hue = (hue + 137.508) % 360;
    out.push(hsvToHex(hue, 0.45 + Math.random() * 0.3,
                      0.5 + Math.random() * 0.35));
  }
  return out;
}

// «Случайно» - не забава: одним нажатием видно, из каких кусков состоит
// модель и что покраска вообще делает
document.getElementById('parts-random').addEventListener('click', async () => {
  const fresh = await api.parts(P.material, P.shape);
  if (fresh.error) { hintParts(fresh.error); return; }
  const picked = randomColors(fresh.parts.length);
  const colors = {};
  fresh.parts.forEach((part, index) => {
    colors[part.id] = paintSpec(picked[index]);
  });
  await colorParts(colors);
  hintParts('Случайная раскраска - щёлкай по частям, чтобы поправить');
});

/**
 * Квадрат открывает выбор цвета - и переход задаётся там же
 *
 * Отдельным инструментом цвет не делаем: красит всё равно кисть, поэтому
 * щелчок по квадрату её и выбирает. Блок перехода переезжает в поповер: решать
 * «цвет или переход» в одном месте, а подбирать сам цвет в другом - значит
 * заставлять ходить туда-сюда ради одного решения.
 */
function openBrushColor() {
  const anchor = document.getElementById('parts-swatch');
  if (picking()) { closeColor(); return; }   // повторный щелчок закрывает
  pickColor(colorField(), {
    anchor,
    extra: document.getElementById('parts-grad-box'),
  });
}

/** Поле цвета, который сейчас правят: первый или второй конец перехода */
export function colorField() {
  return document.getElementById(gradientEnd === 2 ? 'part-color2' : 'part-color');
}

document.getElementById('parts-swatch').addEventListener('click', openBrushColor);

/**
 * Ползунки на полосе перехода
 *
 * Тянут их редко, а перекраска стоит десятых долей секунды на 2048 - поэтому
 * форма применяется по ОТПУСКАНИЮ, а полоса рисуется по ходу: видно сразу,
 * пересчитывается один раз
 *
 * Щелчок по краю (без протяжки) переводит на его цвет выбор наверху: два
 * цвета перехода правятся там же, где его форма.
 */
(function bindRamp() {
  const ramp = document.getElementById('parts-ramp');
  const GAP = 0.04;        // края не сходятся в точку: там уже не переход
  let held = null;         // какой ползунок держат
  let moved = false;       // тянули или только щёлкнули

  const at = (e) => {
    const r = ramp.getBoundingClientRect();
    return Math.min(1, Math.max(0, (e.clientX - r.left) / (r.width || 1)));
  };

  ramp.addEventListener('pointerdown', (e) => {
    const stop = e.target.closest('.parts__stop');
    if (!stop) return;
    held = stop.dataset.stop;
    moved = false;
    stop.setPointerCapture(e.pointerId);
    if (held !== 'mid') armEnd(held === 'end' ? 2 : 1);
  });

  ramp.addEventListener('pointermove', (e) => {
    if (!held || !e.target.hasPointerCapture?.(e.pointerId)) return;
    moved = true;
    const x = at(e);
    if (held === 'start') gradStart = Math.min(x, gradEnd - GAP);
    else if (held === 'end') gradEnd = Math.max(x, gradStart + GAP);
    else {
      const width = gradEnd - gradStart || 1;
      gradMid = Math.min(0.95, Math.max(0.05, (x - gradStart) / width));
    }
    showColor();
  });

  ramp.addEventListener('pointerup', (e) => {
    if (!held) return;
    e.target.releasePointerCapture?.(e.pointerId);
    held = null;
    if (moved) applyGradientShape();
  });
})();

/** Переводит выбор цвета на нужный конец перехода и отмечает его на полосе */
function armEnd(end) {
  gradientEnd = end;
  document.querySelectorAll('#parts-ramp .parts__stop').forEach((b) => {
    b.classList.toggle('is-active',
      b.dataset.stop === (end === 2 ? 'end' : 'start'));
  });
  pickInto(colorField());
}

/**
 * Сворачивание палитры
 *
 * Модель разглядывают и издали тоже, а колонка со своей панелью занимает
 * полосу кадра. Режим при этом не выключается: свёрнутая палитра - это всё
 * ещё режим частей, просто кадр чист.
 */
document.getElementById('parts-fold').addEventListener('click', () => {
  const bar = document.getElementById('partspaint');
  const folded = bar.classList.toggle('is-folded');
  const btn = document.getElementById('parts-fold');
  btn.title = t(folded ? 'Развернуть палитру' : 'Свернуть палитру');
});

/**
 * Окантовка: полоса по краю покрашенных частей
 *
 * Ширина уходит в Python долей стороны текстуры, а не пикселями: одна и та же
 * работа собирается и в 512, и в 2048, и полоса должна выглядеть одинаково.
 * Ползунок при этом показывает тысячные доли - «6» это 0.006 стороны.
 */
async function applyEdge() {
  if (P.material === null) return;
  const on = document.getElementById('parts-edge').classList.contains('is-active');
  const width = on ? Number(document.getElementById('part-edge-width').value) / 1000 : 0;
  const color = document.getElementById('part-edge-color').value;
  const res = await api.setPartEdge(P.material, width, color);
  if (res.error) { hintParts(res.error); return; }
  hintParts(on
    ? 'Окантовка пойдёт по краям тех частей, которые покрасишь дальше'
    : '');
}

document.getElementById('parts-edge').addEventListener('click', (e) => {
  const on = !e.target.classList.contains('is-active');
  e.target.classList.toggle('is-active', on);
  document.getElementById('part-edge-color').hidden = !on;
  document.getElementById('part-edge-box').hidden = !on;
  applyEdge();
});
// Цвет и толщину применяем по отпусканию: каждое движение ползунка -
// пересборка всей текстуры, а это десятые доли секунды на 2048
document.getElementById('part-edge-width').addEventListener('change', applyEdge);
document.getElementById('part-edge-color').addEventListener('change', applyEdge);

document.getElementById('parts-grad').addEventListener('click', (e) => {
  gradientOn = !gradientOn;
  e.target.classList.toggle('is-active', gradientOn);
  document.getElementById('parts-grad-aim').hidden = !gradientOn;
  // Выключили переход - правим снова первый цвет: второго больше нет
  if (!gradientOn) armEnd(1);
  else pickInto(colorField());
  showColor();   // задний квадрат в колонке появляется вместе с переходом
  hintParts(gradientOn ? 'Градиент: щёлкай по частям - переход из первого цвета. '
                       + 'Полоса задаёт края и середину перелива, ручка - направление'
                       : '');
});

/**
 * Ручка направления градиента
 *
 * Угол берётся от центра ручки к указателю, поэтому «потянуть в ту сторону,
 * куда должен идти переход» - и есть всё управление. Ровные направления
 * (каждые 45°) подтягиваются: попасть в точную вертикаль мышью иначе нельзя,
 * а хочется её чаще всего.
 */
function setGradientAngle(deg) {
  let angle = ((deg % 360) + 360) % 360;
  const step = Math.round(angle / 45) * 45;
  if (Math.abs(angle - step) < 6) angle = step % 360;
  gradientAngle = angle;
  // Стрелка нарисована ВНИЗ - это и есть нулевое направление, «сверху вниз».
  // CSS крутит по часовой, а угол растёт против неё, отсюда минус
  const needle = document.querySelector('#parts-grad-dir .parts__needle');
  needle.style.transform = 'rotate(' + (-angle) + 'deg)';
  hintParts(`Направление перехода: ${Math.round(angle)}°`);
}

(function bindGradientDial() {
  const dial = document.getElementById('parts-grad-dir');
  const aim = (e) => {
    const r = dial.getBoundingClientRect();
    // Экранный y растёт вниз, а 0° - «сверху вниз», то есть в сторону
    // возрастания y. Отсюда atan2(dx, dy), а не привычный atan2(dy, dx)
    setGradientAngle(Math.atan2(e.clientX - (r.left + r.width / 2),
                                e.clientY - (r.top + r.height / 2))
                     * 180 / Math.PI);
  };
  dial.addEventListener('pointerdown', (e) => {
    dial.setPointerCapture(e.pointerId);
    aim(e);
  });
  dial.addEventListener('pointermove', (e) => {
    if (dial.hasPointerCapture(e.pointerId)) aim(e);
  });
  dial.addEventListener('pointerup', (e) => {
    dial.releasePointerCapture(e.pointerId);
    applyGradientShape();
  });
  // С клавиатуры - шагом 15°: ручку надо уметь довернуть и без мыши
  dial.addEventListener('keydown', (e) => {
    const step = { ArrowLeft: -15, ArrowDown: -15, ArrowRight: 15, ArrowUp: 15 }[e.key];
    if (step === undefined) return;
    e.preventDefault();
    setGradientAngle(gradientAngle + step);
    applyGradientShape();
  });
})();
