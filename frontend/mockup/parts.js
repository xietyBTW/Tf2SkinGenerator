/*
 * Части модели: покрасить кусок геометрии, а не весь материал.
 *
 * Материал у оружия почти всегда один — «покрасить только ствол» это кусок
 * геометрии, а не второй материал. Разбор и склейку делает Python; страница
 * показывает полосу частей, включает подсветку во вьювере и передаёт файл.
 *
 * Полоса — три группы под вкладками (кисть, нарезка, окантовка), а не всё
 * сразу: человек в момент времени делает что-то одно, и показ всего разом был
 * причиной тесноты.
 */

import * as api from './api.js';
import { plural } from './util.js';
import { t } from './i18n.js';
import { stage, withViewer, viewer } from './stage.js';
import { applyView } from './preview.js';
import { askPartPlacement, repositionPart } from './place.js';
import { pickColor, pickInto, picking, closeColor, hsvToHex, armDrop }
  from './picker.js';
import { colorAt } from './sample.js';

// ── Части модели ────────────────────────────────────────────────────────
// Материал у оружия почти всегда один: «покрасить только ствол» — это кусок
// геометрии, а не второй материал. Разбор и склейку делает Python, страница
// показывает список, включает подсветку во вьювере и передаёт файл.

export let partsMaterial = null;   // материал разобранной модели; null — не разбирали


//: Чем сейчас работают: 'image' (положить картинку), 'brush' (красить),
//: 'pick' (взять цвет), 'cut' (резать), 'edge' (обводить). Раньше это была
//: ОТСУТСТВУЮЩАЯ покраска: щелчок по части без выбранного цвета открывал
//: выбор файла, а с цветом — красил. Один щелчок делал два разных дела, и
//: узнать заранее какое было неоткуда. Теперь дело называет значок.
//:
//: null — не выбрано ничего, и это НАЧАЛЬНОЕ состояние: палитра открывается
//: без кисти в руке. Иначе первый же щелчок по модели красил её тем цветом,
//: который остался с прошлого предмета, — а просили посмотреть.
let tool = null;
//: Чем красит кисть. Умолчание берём из самого поля, а не повторяем цифрой:
//: два места с одним цветом расходятся, и подсветка образца врала бы.
let brushColor = document.getElementById('part-color').value;
//: {ключ разбиения и части: обещание картинки-подсветки}. Наводят десятки раз,
//: а форма части меняется только от резки — второй раз спрашивать нечего.
//: Обещание, а не готовый адрес: на одно наведение приходят ДВА вызова — от
//: списка частей и от вьювера, — и с адресом первый кусок спрашивался дважды.
const partMasks = new Map();
//: Номер последнего наведения: ответ на прошлое мог прийти после того, как
//: курсор уехал на соседнюю часть, и тогда подсветилась бы не та.
let spotSeq = 0;
//: Последний ответ `parts`: Alt+колесо приносит только номер части, а решать
//: про её кусок надо по тем же данным, что показаны в полосе.
export let partsList = [];
export let cutMode = false;      // щелчок по модели режет, а не красит
//: {группа: сколько в ней островов} — чтобы сказать «резать больше нечего».
export let partsGroups = {};
//: Отпечаток разбиения. Пока он тот же, Python не шлёт карты треугольников —
//: они почти весь ответ, а на покраске не меняются.
export let partsShape = '';
//: {материал: карта треугольников} и {материал: карта островов} — ВСЕ, что
//: отданы вьюверу. Держим их здесь, потому что `setModelParts` заменяет карту
//: целиком: передашь одну — сотрёшь соседний материал.
const partsMaps = {};
const islandMaps = {};
//: {материал: отпечаток разбиения} — ключ кэша масок у каждого свой.
const partsShapes = {};
//: Идёт ли смена активного материала: курсор на границе мешей иначе слал бы
//: запрос на каждый кадр.
let switching = false;
//: Часть под курсором. Нужна перерисовке полосы: список приходит ответом
//: Python и успевает обновиться уже после того, как чип пометили.
let hoverPart = null;
//: Отмеченные для слияния отрезки: номера частей. Живут только в режиме резки.
let marked = new Set();
export let gradientOn = false;   // красить переходом из первого цвета во второй
export let gradientAngle = 0;    // направление перехода в градусах: 0 — сверху вниз
let gradientEnd = 1;             // какой конец перехода правит выбор цвета
//: Форма перехода в долях места части: где он начинается, где кончается и где
//: цвета смешаны поровну. Края задают ширину перелива (сдвинул друг к другу —
//: резче), середина — перевес одного цвета над другим.
let gradStart = 0;
let gradEnd = 1;
let gradMid = 0.5;

/** Включает и выключает режим частей. */
export async function togglePartsMode() {
  const bar = document.getElementById('partsbar');
  if (!bar.hidden) { closeParts(); return; }
  const res = await loadParts();
  if (res && res.parts.length < 2) {
    hintParts('Эта модель — один цельный кусок, делить нечего');
  } else if (res) {
    hintParts('Возьми значок справа: кисть красит, ножницы дробят кусок. '
            + 'Ctrl+Z отменяет, Ctrl+Y возвращает');
  }
}

/**
 * Разбирает модель на части и включает подсветку.
 *
 * Зовётся и по кнопке, и вьювером, когда на модель ТАЩАТ картинку: разбор
 * стоит около сотой доли секунды, и заставлять ради него нажимать кнопку —
 * значит терять тот единственный момент, когда подсветка что-то объясняет.
 */
export async function loadParts() {
  const res = await api.parts();
  if (res.error) { hintParts(res.error); return null; }

  partsMaterial = res.material;
  showParts(res);
  showPalette(res);

  const w = viewer();
  if (w) w.setPartsMode(true);
  await loadOtherMaterials(res.material);
  return res;
}

/**
 * Карты треугольников ОСТАЛЬНЫХ материалов модели.
 *
 * У шпиона голова и тело — разные материалы, у каждого своя развёртка и свой
 * разбор. Пока вьювер знал одну карту, он применял её ко ВСЕМ мешам (иначе
 * одноматериальные модели, где карта лежит под служебным ключом, вообще не
 * подсвечивались бы) — и наведение на тело возвращало номер части ГОЛОВЫ, а
 * разметка рисовалась на её текстуре.
 *
 * Материалы берём из альбома: это ровно то, что человек видит кадрами.
 */
async function loadOtherMaterials(main) {
  const mats = [...document.querySelectorAll('.frame')]
    .map((f) => f.dataset.mat)
    .filter((m) => m && m !== main);
  if (!mats.length) return;          // одноматериальная модель — грузить нечего
  for (const mat of mats) {
    const res = await api.parts(mat);
    if (!res.error) rememberMaps(res);
  }
}

/**
 * Складывает карты материала и отдаёт вьюверу ВСЕ, что уже известны.
 *
 * Именно все: `setModelParts` заменяет карту целиком, и передача одной стирала
 * бы соседний материал — а с одной записью вьювер снова начинал применять её к
 * чужим мешам.
 */
function rememberMaps(res) {
  if (!res || !res.material) return;
  if (res.shape) partsShapes[res.material] = res.shape;
  if (res.tri_part) partsMaps[res.material] = res.tri_part;
  if (res.tri_island) islandMaps[res.material] = res.tri_island;
  const w = viewer();
  if (!w || !res.tri_part) return;
  w.setModelParts({ ...partsMaps });
  if (w.setModelIslands) w.setModelIslands({ ...islandMaps });
}

/**
 * Делает материал активным: список частей и покраска относятся к нему.
 *
 * Зовётся наведением: курсор ушёл с головы на тело — и полоса частей, и
 * разметка на текстуре должны говорить про тело. Переключение идёт по одному:
 * курсор на границе мешей иначе слал бы запрос на каждый кадр.
 */
async function usePartsMaterial(material) {
  if (!material || material === partsMaterial || switching) return;
  if (partsMaterial === null) return;      // режим не открывали — нечего менять
  if (!hasOwnParts(material)) return;      // переключаться не на что
  switching = true;
  try {
    const res = await api.parts(material);
    if (res.error) return;
    partsMaterial = res.material;
    showParts(res);
  } finally {
    switching = false;
  }
}

/**
 * Связывает вьювер с частями.
 *
 * Ставится на КАЖДУЮ модель, а не по кнопке: перетаскивание картинки на кусок
 * должно работать сразу — иначе про части узнают, только случайно нажав
 * кнопку.
 */
export function bindParts(w) {
  // Разбор относился к ПРОШЛОЙ модели: у новой под тем же номером другой кусок.
  closeParts();
  w.setModelParts(null);
  w.onPartsNeeded = () => { if (partsMaterial === null) loadParts(); };
  // Материал приходит со ВСЕМИ вызовами вьювера: у модели их бывает
  // несколько, и часть под курсором принадлежит своему, а не тому, что сейчас
  // показан полосой.
  w.onPartHover = (part, material) => spotlightPart(part, material);
  w.onPartDropped = async (material, part, file) => {
    await usePartsMaterial(material);
    paintPart(part, file);
  };
  // Пипетка в 3D: цвет вьювер берёт из текстуры под курсором — той же, что
  // показана кадром, поэтому оба входа пипетки дают один ответ.
  w.onColorPicked = (hex) => takeColor(hex);
  // Отмена принадлежит странице, а фокус после щелчка по модели достаётся
  // iframe: вьювер передаёт нажатие, разбирает его тот же код (см. historyKey).
  w.onPartsKey = (e) => historyKey(e);
  // Пока кнопку держат, вьювер шлёт цвет под курсором вместе со своими
  // координатами: образец рисует страница, и место ему нужно в её системе.
  w.onColorSample = (hex, x, y) => {
    const box = stage.frame.getBoundingClientRect();
    showSample(hex, x + box.left, y + box.top);
  };
  w.onPartPicked = async (material, part) => {
    await usePartsMaterial(material);
    pickPart(part);
  };
  // Резать там же, где смотрят: щелчок отрезает ОБВЕДЁННЫЙ остров развёртки
  // или приращивает его обратно. Номер части нужен, чтобы узнать её группу.
  w.onPartCut = async (material, part, island) => {
    await usePartsMaterial(material);
    cutIsland(part, island);
  };
  if (w.setCutMode) w.setCutMode(cutMode);
}

/** Что делает щелчок по части: кисть красит, курсор спрашивает картинку. */
function pickPart(part) {
  if (tool === 'image') { paintPart(part); return; }
  // Всё остальное по части не работает: окантовка идёт по всей работе, цвет
  // берут с самой картинки, а без инструмента щелчку нечего делать. Раньше
  // здесь стоял `paintPart` на любой инструмент — и окантовка, выбранная
  // значком, молча открывала выбор файла.
  if (tool !== 'brush') {
    hintParts(tool === 'pick'
      ? 'Пипеткой щёлкай по модели или по текстуре слева, а не по списку'
      : 'Возьми кисть справа — щелчок по части покрасит её');
    return;
  }
  colorParts({ [part]: paintSpec(brushColor) });
  // Цвет ложится ПОД картинку: там, где она непрозрачна, его не увидеть.
  // Сказать об этом надо в тот момент, когда это произошло, — иначе человек
  // решит, что покраска не сработала.
  const known = (partsList || []).find((x) => x.id === part);
  if (known && known.image) {
    hintParts('У этой части своя картинка — цвет лёг под неё');
  }
}

/**
 * Есть ли у этого имени СВОЙ разбор.
 *
 * Вьювер называет материал МЕША, а ключ разбора — наш, и сойтись они могут
 * далеко не всегда: у одноматериальной модели разбор лежит под служебным
 * ключом («__single__»), а вьювер в этом случае применяет единственную карту к
 * любому мешу и возвращает его собственное имя. В сцене от первого лица рядом
 * с оружием стоят и вовсе чужие меши.
 *
 * Без этой проверки каждое наведение просило «переключись на материал меша», а
 * такой запрос присылает карты треугольников заново — вьювер, получив их,
 * гасит подсветку куска. Отсюда были и мигание под курсором (её создавало
 * движение и тут же убивал ответ), и полное её отсутствие, если мышь стояла на
 * месте. Тем же ответом перестраивалась полоса частей: кнопка «×» уезжала
 * из-под курсора между нажатием и отпусканием, и щелчок по ней пропадал.
 */
function hasOwnParts(name) {
  return Object.prototype.hasOwnProperty.call(partsMaps, name);
}

/**
 * Показывает место части НА ТЕКСТУРЕ.
 *
 * Связь «кусок модели ↔ участок картинки» иначе видна только тому, кто сам
 * делал развёртку. Наведение показывает её обеим сторонам сразу: и в 3D, и на
 * кадре слева.
 */
async function spotlightPart(part, material) {
  // Кадр — ТОГО материала, которому принадлежит часть. У шпиона голова и тело
  // разные материалы, и разметка тела, нарисованная на текстуре головы, — это
  // не подсказка, а дезинформация.
  // Имя из вьювера годится только когда у него есть свой разбор: иначе это
  // имя меша, а разметку надо рисовать на кадре ТЕКУЩЕГО материала. Заодно
  // ключ кэша маски выходит один и тот же у наведения на модель и на чип —
  // раньше они спрашивали одну и ту же маску дважды.
  const owner = hasOwnParts(material) ? material : partsMaterial;
  const frame = [...document.querySelectorAll('.frame')]
    .find((f) => f.dataset.mat === owner)
    || document.querySelector('.frame.is-current');
  document.querySelectorAll('.frame__uv').forEach((b) => b.remove());
  document.querySelectorAll('#partsbar .tag').forEach((b) => {
    b.classList.toggle('is-hover', Number(b.dataset.part) === part);
  });
  // Помним, на чём стоит курсор: полоса частей могла быть перерисована уже
  // ПОСЛЕ этой пометки (смена материала под курсором приходит ответом Python),
  // и новые чипы вышли бы без подсветки.
  hoverPart = (part === null || part === undefined) ? null : part;
  const mine = ++spotSeq;
  if (part === null || part === undefined || !frame) return;
  // Полоса частей и покраска идут за курсором: ушёл на другой кусок модели —
  // и список, и «Убрать всё» относятся уже к его материалу.
  if (material && material !== partsMaterial) usePartsMaterial(material);

  // Форму рисует Python той же маской, по которой красит склейка. Картинкой, а
  // не списком координат: у крупного куска их полторы тысячи, и возить их на
  // каждое наведение дороже, чем отдать PNG в несколько килобайт.
  // Ключ с материалом: номера частей у каждого свои, и одна и та же «часть 3»
  // у головы и у тела — разные куски.
  const key = owner + '|' + (partsShapes[owner] || partsShape) + '|' + part;
  let mask = partMasks.get(key);
  if (!mask) {
    mask = api.partMask(owner, part)
      .then((res) => (res.error ? null : api.fileUrl(res.mask)));
    partMasks.set(key, mask);
  }
  const url = await mask;
  // Неудачу не запоминаем: со следующим наведением стоит попробовать снова.
  if (!url) { partMasks.delete(key); return; }
  // Пока ждали ответ, курсор мог уехать: подсвечивать уже не то нельзя.
  if (mine !== spotSeq || !frame.isConnected) return;

  const spot = document.createElement('img');
  spot.className = 'frame__uv';
  spot.src = url;
  frame.querySelector('.frame__img').appendChild(spot);
}

/** Подсказка живёт рядом с частями, а не поперёк модели. */
export function hintParts(text) {
  const hint = document.getElementById('parts-hint');
  if (hint) hint.textContent = text || '';
}

/**
 * Палитра: выбранный цвет красит щелчком по куску модели.
 *
 * Цвет, а не диалог с файлом, стоит первым: перекрасить деталь хочется чаще,
 * чем нарисовать на ней свою картинку, и это происходит мгновенно.
 */
function showPalette(res) {
  document.getElementById('partspaint').hidden = false;

  const tint = document.getElementById('part-tint');
  tint.value = Math.round((res.tint || 1) * 100);
  document.getElementById('part-exact').checked = Boolean(res.exact);

  // Окантовка живёт в предмете: полоса должна показать то, что уже задано, а
  // не то, что осталось на контролах от прошлого предмета.
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

/**
 * Показывает, чем красят: квадраты в колонке.
 *
 * Квадраты внахлёст — как в редакторах изображений; второй появляется только
 * с градиентом, иначе он обещал бы цвет, которым ничего не красится.
 */
function showColor() {
  const second = document.getElementById('part-color2').value;
  document.getElementById('parts-swatch-fg').style.background = brushColor;
  document.getElementById('parts-swatch-bg').style.background = second;
  document.getElementById('parts-swatch').classList.toggle('is-grad', gradientOn);
  showRamp(second);
}

/**
 * Полоса перехода: что получится на детали.
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
    + brushColor + ' 0 ' + at(gradStart) + ','
    + mixColors(brushColor, second) + ' ' + at(middle) + ','
    + second + ' ' + at(gradEnd) + ' 100%)';
  const place = { start: gradStart, mid: middle, end: gradEnd };
  ramp.querySelectorAll('.parts__stop').forEach((b) => {
    b.style.left = at(place[b.dataset.stop]);
  });
}

/** Половина пути между двумя «#rrggbb» — только для показа полосы. */
function mixColors(one, two) {
  const half = (at) => {
    const a = parseInt(one.substr(at, 2), 16);
    const b = parseInt(two.substr(at, 2), 16);
    return Math.round((a + b) / 2).toString(16).padStart(2, '0');
  };
  return '#' + half(1) + half(3) + half(5);
}

/** Выходит из режима частей: покраска остаётся, уходит только полоса. */
export function closeParts() {
  const bar = document.getElementById('partsbar');
  bar.querySelectorAll('.tag').forEach((b) => b.remove());
  bar.hidden = true;
  document.getElementById('partspaint').hidden = true;
  document.getElementById('partspaint').classList.remove('is-folded');
  // Выбор цвета держит у себя блок перехода: уйти, не закрыв его, значило бы
  // оставить кусок спрятанной палитры висеть поверх кадра.
  closeColor();
  showToolGroup(null);      // следующий раз палитра откроется без кисти
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
  hintParts('');
  setCutMode(false);
  spotlightPart(null);
  partsMaterial = null;
  partsList = [];
  partsGroups = {};
  partsShape = '';
  Object.keys(partsMaps).forEach((m) => delete partsMaps[m]);
  Object.keys(islandMaps).forEach((m) => delete islandMaps[m]);
  Object.keys(partsShapes).forEach((m) => delete partsShapes[m]);
  marked.clear();
  const w = viewer();
  if (w) w.setPartsMode(false);
}

/** Полоса частей: крупные первыми, покрашенные помечены. */
export function showParts(res) {
  const bar = document.getElementById('partsbar');
  bar.querySelectorAll('.tag').forEach((b) => b.remove());
  bar.hidden = false;

  // Карту «треугольник → часть» вьювер получает по имени материала: у него
  // геометрия сгруппирована так же, как её отдал Python. Отдаём её ЗДЕСЬ, а не
  // только при первом разборе: после дробления номера другие, и со старой
  // картой новые части в 3D не выбирались вовсе — щелчок возвращал номер из
  // прежнего разбиения.
  partsList = res.parts;
  partsGroups = res.group_islands || {};
  partsShape = res.shape || '';
  // Часть могла исчезнуть при перерезке: отметка на неё больше ничего не значит.
  const alive = new Set(res.parts.map((x) => x.id));
  [...marked].forEach((id) => { if (!alive.has(id)) marked.delete(id); });
  // Карты приходят только при смене разбиения: нет их в ответе — у вьювера
  // уже лежат нужные, и слать undefined значило бы стереть их.
  rememberMaps(res);

  res.parts.forEach((part) => {
    const b = document.createElement('button');
    b.className = 'tag' + (part.image || part.color ? ' is-painted' : '')
      + (part.shared.length ? ' tag--shared' : '');
    b.dataset.part = part.id;
    // На кнопке — только номер: частей бывает под три десятка, и «Часть 7 · 3%»
    // в двух строках делало из полосы стену. Доля развёртки ушла в подсказку —
    // «0%» там читается как поломка, поэтому у винтика пишем «<1%».
    //
    // Номер — КУСКА, а не сквозной по списку: сквозной съезжал от каждого
    // разреза, и человек терял из виду ту часть, с которой работал. Разрезанный
    // кусок даёт «04·1», «04·2» — видно и что это одно место модели, и что их
    // теперь несколько.
    const share = part.area >= 0.01 ? Math.round(part.area * 100) + '%' : '<1%';
    b.textContent = String(part.chunk + 1).padStart(2, '0')
                  + (part.sub ? '\u00b7' + part.sub : '');
    // Куски, делящие развёртку, в игре красятся вместе — сказать об этом надо
    // до того, как человек нарисует и удивится.
    b.title = t('Часть ') + b.textContent + ' · ' + share + t(' развёртки')
      + (part.shared.length
        ? '\n' + t('Делит развёртку с другими: в игре они покрасятся вместе, '
          + 'разными их сделать нельзя')
        : '');
    // Наведение на пункт списка подсвечивает кусок на модели: иначе «Часть 3»
    // — это просто номер, и какой именно кусок за ним, узнать неоткуда.
    b.addEventListener('mouseenter', () => {
      // Материал называем явно: у модели их бывает несколько, и «часть 3» есть
      // у каждого — без имени подсветился бы кусок соседнего меша.
      viewer()?.highlightPart(part.id, partsMaterial);
      spotlightPart(part.id, partsMaterial);
    });
    b.addEventListener('mouseleave', () => {
      viewer()?.highlightPart(null);
      spotlightPart(null);
    });
    b.addEventListener('click', (e) => {
      if (e.target.classList.contains('parts__x')
          || e.target.classList.contains('parts__cut')) return;
      // Резать из списка нечего — какой остров имеется в виду, видно только
      // на модели. Зато список — единственное место, где можно ткнуть в две
      // части сразу, поэтому здесь щелчок ОТМЕЧАЕТ их для слияния.
      if (cutMode) { markPart(part); return; }
      pickPart(part.id);
    });
    if (part.color) {
      const dot = document.createElement('span');
      dot.className = 'parts__dot';
      dot.style.background = (typeof part.color === 'object')
        ? 'linear-gradient(90deg,' + part.color.color + ','
          + (part.color.color2 || part.color.color) + ')'
        : part.color;
      b.appendChild(dot);
    }
    // Кнопка только на ОТРЕЗАННОЙ части — прирастить её обратно. Кнопки
    // «разрезать» здесь нет и быть не может: резать надо названный остров, а
    // из списка не видно, какой именно. Для этого есть ножницы.
    if (part.islands && part.islands.length) {
      b.classList.toggle('is-marked', marked.has(part.id));
      b.appendChild(chunkStep(part, '\u2212', 'Прирастить обратно'));
    }
    // У части с картинкой — вход в окно посадки. Щелчок по самому чипу
    // спрашивает файл заново, а поправить нужно чаще, чем заменить.
    if (part.image) {
      const fix = document.createElement('button');
      fix.className = 'parts__cut';
      fix.type = 'button';
      fix.textContent = '…';
      fix.title = 'Как положена картинка: размер, поворот, место';
      fix.addEventListener('click', (e) => {
        e.stopPropagation();
        repositionPart(part.id);
      });
      b.appendChild(fix);
    }
    if (part.id === hoverPart) b.classList.add('is-hover');
    if (part.image || part.color) {
      const x = document.createElement('button');
      x.className = 'parts__x';
      x.type = 'button';
      x.textContent = '\u00d7';
      x.title = 'Вернуть этой части игровую текстуру';
      // Снимаем ОБА слоя: у части может быть и цвет, и картинка поверх него, а
      // крестик обещает вернуть игровую текстуру — то есть убрать всё своё.
      x.addEventListener('click', async () => {
        if (part.image) await paintPart(part.id, null);
        if (part.color) await colorParts({ [part.id]: null });
      });
      b.appendChild(x);
    }
    bar.appendChild(b);
  });
  syncMarks();          // кнопка слияния живёт по отметкам, а не по прошлому списку
}

/**
 * Отрезает названный остров развёртки или приращивает его обратно.
 *
 * Остров, а не «следующий шов»: счётчик резал в своём порядке, от крупного, и
 * до мизинца можно было добраться только разрезав перед ним всё остальное.
 *
 * Режется ГРУППА — все куски, делящие эту развёртку. У рук шпиона левая и
 * правая делят её целиком, и разрезать одну без другой нельзя: в игре у них
 * общие пиксели, краска легла бы на обе.
 */
/** Возвращает отрезок в кусок целиком — со всеми островами, из которых он собран. */
async function uncutPart(part) {
  for (const island of part.islands || []) await cutIsland(part.id, island);
}

async function cutIsland(partId, island) {
  const known = (partsList || []).find((x) => x.id === partId);
  if (!known || island == null || island < 0) return;
  const total = (partsGroups || {})[known.group] || 1;
  if (total < 2) { hintParts('У этого куска один остров развёртки — резать нечего'); return; }

  hintParts('Режу…');
  const res = await api.togglePartIsland(partsMaterial, known.group, island);
  if (res.error) { hintParts(res.error); return; }
  applyView(res);
  const fresh = await refreshParts();
  const cut = ((fresh && fresh.parts) || [])
    .filter((x) => x.group === known.group && (x.islands || []).length);
  const uniq = new Set(cut.flatMap((x) => x.islands)).size;
  // Про возврат говорим, только когда есть что возвращать: у мелкого острова
  // попасть по нему курсором трудно, поэтому там же называем «−» на чипе.
  hintParts('Отрезано ' + uniq + ' ' + plural(uniq, 'остров', 'острова', 'островов')
            + ' из ' + total
            + (uniq ? '. Вернуть — щелчок по нему же или «−» на его чипе' : ''));
}

/**
 * Отмечает отрезок для слияния.
 *
 * Отмечать можно только отрезанное и только внутри одного куска: слить
 * отрезки разных кусков нельзя — это разные места модели, а не одна вещь,
 * разложенная развёрткой на два острова.
 */
function markPart(part) {
  if (!part.islands || !part.islands.length) {
    hintParts('Отмечать можно только отрезанное: сперва отрежь на модели');
    return;
  }
  const same = (partsList || []).filter((x) => marked.has(x.id));
  if (same.length && same[0].group !== part.group) marked.clear();
  if (marked.has(part.id)) marked.delete(part.id);
  else marked.add(part.id);
  syncMarks();
}

/** Подсветка отметок и кнопка слияния: нажимать её не на что, пока отмечен один. */
function syncMarks() {
  document.querySelectorAll('#partsbar .tag').forEach((b) => {
    b.classList.toggle('is-marked', marked.has(Number(b.dataset.part)));
  });
  const chosen = (partsList || []).filter((x) => marked.has(x.id));
  document.getElementById('parts-join').hidden = chosen.length < 2;
  if (chosen.length >= 2) {
    hintParts('Отмечено ' + chosen.length + '. «Объединить» сведёт их в одну часть');
  }
}

/** Кнопка «−» на отрезанной части: вернуть её в кусок, из которого вырезали. */
function chunkStep(part, glyph, title) {
  const btn = document.createElement('button');
  btn.className = 'parts__cut';
  btn.type = 'button';
  btn.textContent = glyph;
  btn.title = title + '. То же — щелчок по ней на модели с ножницами';
  btn.addEventListener('click', (e) => {
    e.stopPropagation();          // щелчок по чипу красит — здесь этого не надо
    uncutPart(part);
  });
  return btn;
}

/**
 * Чем красить: сплошной цвет или градиент — и КАК, со всеми настройками кисти.
 *
 * Настройки едут вместе с мазком, а не берутся общими на предмет: переключишь
 * потом «точный цвет» или окантовку — уже покрашенное останется таким, каким
 * его сделали. Так это и работает в редакторах: кисть меняешь для следующего
 * мазка, а не для всех прошлых.
 *
 * Градиент строится по месту ЧАСТИ на развёртке, поэтому странице достаточно
 * назвать два цвета и направление — остальное считает Python.
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
 * Правка формы перехода задним числом.
 *
 * Без неё ползунки говорили бы только о БУДУЩЕЙ покраске: покрутил — на модели
 * ничего, а понять, что делает середина, можно только глядя на деталь. Цвета у
 * каждой части свои, поэтому меняем ровно форму — угол, края и середину.
 */
async function applyGradientShape() {
  const fresh = {};
  (partsList || []).forEach((part) => {
    if (part.color && typeof part.color === 'object') {
      fresh[part.id] = { ...part.color, angle: gradientAngle,
                         start: gradStart, end: gradEnd, mid: gradMid };
    }
  });
  if (Object.keys(fresh).length) await colorParts(fresh);
}

/** Красит части: {часть: цвет}, значение null снимает цвет. */
export async function colorParts(colors) {
  const strength = Number(document.getElementById('part-tint').value) / 100;
  const exact = document.getElementById('part-exact').checked;
  const res = await api.setPartColors(partsMaterial, colors, strength, exact);
  if (res.error) { hintParts(res.error); return; }
  applyView(res);
  await refreshParts();
}

/** Перечитывает список частей — после любой покраски. */
export async function refreshParts() {
  const fresh = await api.parts(partsMaterial, partsShape);
  if (!fresh.error) showParts(fresh);
  return fresh;
}

/** Кладёт (или снимает) картинку на часть и обновляет полосу. */
export async function paintPart(part, file = undefined) {
  const apply = async (file) => {
    hintParts('Наложение на часть…');
    try {
      let path = null;
      let options;
      if (file) {
        path = await api.upload(file);
        // Спрашиваем ДО наложения: иначе человек сперва видит перекошенную
        // картинку, а потом её правит — и первый кадр всегда испорчен.
        options = await askPartPlacement(part, path);
        if (options === null) { hintParts(''); return; }
      }
      const res = await api.setPartTexture(partsMaterial, part, path, options);
      if (res.error) { hintParts(res.error); return; }
      applyView(res);
      const fresh = await refreshParts();
      // Куски, делящие развёртку, красятся вместе. Сказать об этом надо в тот
      // момент, когда это произошло, а не только подсказкой на кнопке.
      const painted = (fresh.parts || []).find((p) => p.id === part);
      hintParts(file && painted && painted.shared.length
        ? 'Эта часть делит развёртку с соседними — они покрасились вместе'
        : '');
    } catch (err) {
      hintParts('Не удалось: ' + err.message);
    }
  };

  if (file !== undefined) { apply(file); return; }   // null — снять картинку

  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/*,.vtf';
  input.addEventListener('change', () => input.files[0] && apply(input.files[0]));
  input.click();
}

document.getElementById('parts').addEventListener('click', togglePartsMode);

document.getElementById('part-color').addEventListener('input', (e) => {
  brushColor = e.target.value;
  showColor();
  // Про щелчок по частям говорим только с кистью в руке: выбор цвета её больше
  // не берёт, и обещать покраску от щелчка было бы враньём.
  hintParts(tool === 'brush'
    ? 'Щёлкай по частям модели — покрасятся в этот цвет'
    : 'Цвет выбран — возьми кисть, чтобы им красить');
});

// Второй цвет виден на заднем квадрате колонки: там же, где первый.
document.getElementById('part-color2').addEventListener('input', showColor);

/**
 * Подробность резки: 0 — куски геометрии, 100 — каждый шов развёртки.
 *
 * Спрашиваем по `change`, а не по `input`: перерезка модели и пересборка
 * склейки на каждом пикселе протяжки — это десятки лишних разборов.
 */
document.getElementById('part-detail').addEventListener('change', async (e) => {
  if (partsMaterial === null) return;
  hintParts('Перерезаю модель…');
  const res = await api.setPartDetail(partsMaterial, Number(e.target.value) / 100);
  if (res.error) { hintParts(res.error); return; }
  applyView(res);
  const fresh = await refreshParts();
  hintParts('Частей: ' + ((fresh && fresh.parts) || []).length);
});

// Сила тонировки общая на предмет: тянуть ползунок ради одной части и потом
// ради другой — не то, чего от него ждут.
document.getElementById('part-tint').addEventListener('change', () => {
  // Пустой набор — «запомни настройку кисти»: уже покрашенные части держат
  // свои, те, что были в момент мазка.
  if (partsMaterial !== null) colorParts({});
});

// «Точный цвет» — свойство всей работы, как и сила: переключили — пересобрали
// уже покрашенное, иначе о нём можно судить только по следующему мазку.
document.getElementById('part-exact').addEventListener('change', () => {
  if (partsMaterial === null) return;
  hintParts(document.getElementById('part-exact').checked
    ? 'Цвет ложится ровно как в палитре; фактура остаётся за счёт теней'
    : 'Цвет смешивается с оригиналом — так деталь выглядит естественнее');
  colorParts({});
});

// Окантовка тоже настройка КИСТИ: обводятся те части, которые красят после
// её включения, а не всё сделанное разом.

/**
 * Цвета для случайной раскраски.
 *
 * Раньше здесь было пять готовых оттенков по кругу: «случайно» отличалось от
 * раза к разу только тем, с какого из пяти начать, и модель выходила всегда
 * одна и та же.
 *
 * Теперь оттенок берётся с шагом ЗОЛОТОГО СЕЧЕНИЯ по цветовому кругу
 * (137.5°): соседние куски всегда далеко друг от друга по цвету, и при этом
 * ни один шаг не повторяет предыдущие — на любом числе частей раскладка
 * получается разной. Просто `random()` на каждую часть так не умеет: соседи
 * то и дело выпадают почти одинаковыми, и куски сливаются.
 *
 * Насыщенность и светлота гуляют в узких пределах: это КРАСКА на модели, а не
 * неоновая подсветка — совсем случайные дают то кислоту, то грязь.
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

// «Случайно» — не забава: одним нажатием видно, из каких кусков состоит
// модель и что покраска вообще делает.
document.getElementById('parts-random').addEventListener('click', async () => {
  const fresh = await api.parts(partsMaterial, partsShape);
  if (fresh.error) { hintParts(fresh.error); return; }
  const picked = randomColors(fresh.parts.length);
  const colors = {};
  fresh.parts.forEach((part, index) => {
    colors[part.id] = paintSpec(picked[index]);
  });
  await colorParts(colors);
  hintParts('Случайная раскраска — щёлкай по частям, чтобы поправить');
});

// Отмена — то, что позволяет пробовать: без неё каждый щелчок по модели
// приходится обдумывать заранее.
export async function undoParts() {
  return stepParts(api.undoParts, 'Отменено');
}

/** Возвращает вперёд то, что отменили. */
export async function redoParts() {
  return stepParts(api.redoParts, 'Возвращено');
}

/** Шаг по истории покраски — в любую сторону: движение одно и то же. */
async function stepParts(step, said) {
  const res = await step(partsMaterial);
  if (res.error) { hintParts(res.error); return; }
  applyView(res);
  // Не только полоса частей: шаг возвращает и силу тонировки с окантовкой, а
  // они живут на ползунках. Без этого контролы показывали бы значения, от
  // которых на модели уже ничего не осталось.
  const fresh = await refreshParts();
  if (fresh && !fresh.error) showPalette(fresh);
  hintParts(said);
}

/**
 * Режим резки.
 *
 * Выключает покраску щелчком нарочно: раньше щелчок по модели всегда открывал
 * выбор картинки, и человек, который хотел разрезать кусок, получал файловое
 * окно. Один щелчок — один ответ.
 *
 * Включает и выключает его САМ значок ножниц (см. showToolGroup): своей кнопки
 * у режима нет — два выключателя у одного режима рано или поздно разъезжаются,
 * и тогда один из них молча проигрывает.
 */
function setCutMode(on) {
  cutMode = !!on;
  marked.clear();
  syncMarks();
  if (cutMode) hintParts('');
  withViewer((w) => w.setCutMode && w.setCutMode(cutMode));
  if (cutMode) {
    hintParts('Наведи на модель — обведётся кусок развёртки, который отрежется. '
            + 'Щелчок режет; щелчки по отрезанным в списке отмечают их, '
            + 'чтобы свести в одну часть');
  } else {
    hintParts('');
  }
}

//: Как называется выбранный значок. Значок без слова запоминается со второго
//: раза, а не с первого, поэтому имя стоит над его настройками.
const TOOL_NAMES = { image: 'Картинка', brush: 'Кисть', pick: 'Пипетка',
                     cut: 'Нарезка', edge: 'Окантовка' };

//: У кого есть значок-приставка к курсору. Курсору («положить картинку») и
//: ножницам она не нужна: у первого дело и есть «показать», у вторых
//: перекрестие само говорит про разрез.
const TOOL_BADGE = new Set(['brush', 'pick', 'edge']);

/**
 * Значок инструмента из разметки: одна копия рисунка на всё приложение.
 *
 * Ищем по всей палитре, а не в колонке: у пипетки кнопка стоит в самом выборе
 * цвета — там, где цвет и подбирают.
 */
function toolIcon(name) {
  return document.querySelector('#partspaint [data-tool="' + name + '"] svg');
}

/**
 * Курсор: САМА СТРЕЛКА плюс значок дела у неё справа-снизу.
 *
 * Стрелка остаётся, потому что она показывает ТОЧКУ — по ней целятся в кусок
 * размером с винтик, и значок вместо неё отнимал бы прицел. Значок только
 * называет дело, поэтому висит сбоку и острия не имеет.
 *
 * Рисунки берём из разметки, а не повторяем их здесь: две копии одного значка
 * расходятся, и курсор начинает обещать не тот инструмент, что горит в
 * колонке. Стрелка — тот же значок «курсор», только залитый белым.
 *
 * Тёмный контур под светлым: курсор ходит и по белой текстуре, и по чёрной, и
 * однотонный на одной из них исчезает.
 */
function toolCursor(name) {
  if (!TOOL_BADGE.has(name)) return '';
  const badge = toolIcon(name);
  const arrow = toolIcon('image');
  if (!badge || !arrow) return '';
  const art = '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"'
    + ' viewBox="0 0 32 32" fill="none" stroke-linecap="round"'
    + ' stroke-linejoin="round">'
    + '<g transform="translate(-3.4 -2.2) scale(1.5)" fill="#fff" stroke="#000"'
    + ' stroke-width=".9">' + arrow.innerHTML + '</g>'
    + '<g transform="translate(16 15)">'
    + '<g stroke="#000" stroke-width="2.6" opacity=".55">' + badge.innerHTML + '</g>'
    + '<g stroke="#fff" stroke-width="1.2">' + badge.innerHTML + '</g></g></svg>';
  // Острие — у стрелки, в её собственном кончике: значок сбоку ничего не
  // показывает, и «горячей точкой» ему быть нельзя.
  return 'url("data:image/svg+xml,' + encodeURIComponent(art) + '") 1 1, auto';
}

/**
 * Показывает инструмент курсором — там, где он работает.
 *
 * Вьювер знает про инструмент ровно две вещи: каким курсором показать и надо
 * ли брать цвет вместо покраски, — поэтому одна передача, а не две.
 * Пипетка работает и по кадру слева, и курсор ей нужен там же; остальные
 * инструменты кадра не касаются, и обещать над ним кисть было бы враньём.
 *
 * Здесь же взводится пипетка у поповера выбора цвета: владелец этого
 * состояния один — выбранный инструмент, иначе кнопка в палитре и значок в
 * колонке разъехались бы.
 */
function showToolCursor(name) {
  const css = toolCursor(name);
  withViewer((w) => w.setPartsTool && w.setPartsTool(name || '', css));
  stage.album.style.cursor = name === 'pick' ? css : '';
  armDrop(name === 'pick');
}

/**
 * Какой инструмент выбран: кисть, пипетка, ножницы или окантовка.
 *
 * Настройки видны только у него: человек в момент времени делает что-то одно,
 * а показ всего разом давал четыре строки под моделью — с «Толщиной»,
 * оторванной переносом от своей же «Окантовки».
 *
 * Ножницы — это и есть режим резки: выбрал значок, и щелчок по модели режет.
 * Уход с них его гасит, иначе щелчок молча делал бы не то, что показано.
 */
function showToolGroup(name) {
  tool = name;
  document.querySelectorAll('.ptools__btn[data-tool]').forEach((b) => {
    b.classList.toggle('is-active', b.dataset.tool === name);
  });
  let shown = false;
  document.querySelectorAll('.parts__group').forEach((g) => {
    g.hidden = g.dataset.group !== name;
    shown = shown || !g.hidden;
  });
  // У картинки настроек нет: пустая панель с одним заголовком закрывала бы
  // кадр, ничего не сообщая.
  document.getElementById('parts-opts').hidden = !shown;
  document.getElementById('parts-tool').textContent = t(TOOL_NAMES[name] || '');
  showToolCursor(name);
  if ((name === 'cut') !== cutMode) setCutMode(name === 'cut');
  if (name === 'image') {
    hintParts('Щёлкай по частям модели или тащи на них картинку — она ляжет '
            + 'на кусок');
  }
  if (name === 'pick') {
    hintParts('Зажми на модели или на текстуре — цвет виден под курсором, '
            + 'а берётся там, где отпустишь');
  }
  // Про Alt говорим у кисти: пипетка в палитре, и найти её оттуда — два
  // движения, а посреди покраски цвет подбирают чаще всего.
  if (name === 'brush') {
    hintParts('Щёлкай по частям — покрасятся. Alt при щелчке берёт цвет '
            + 'с модели или с текстуры');
  }
}

/**
 * Пипетка: взятый цвет становится цветом кисти.
 *
 * Через то же поле, что и выбор цвета: у кисти цвет живёт в нём, и второй
 * путь к нему разъехался бы с первым — задним квадратом градиента и открытым
 * поповером. `pickInto` нужен затем, что цвет могли брать при открытом
 * выборе: щелчок по модели идёт внутри iframe, и поповер остаётся на месте.
 */
function takeColor(hex) {
  if (!hex) return;
  const field = colorField();
  field.value = hex;
  field.dispatchEvent(new Event('input', { bubbles: true }));
  pickInto(field);
  hintParts(`Взят цвет ${hex}`);
}

/**
 * Берут ли этим щелчком цвет.
 *
 * Alt при кисти — пипетка «на минуту»: так это устроено в редакторах
 * изображений. Держать её отдельным инструментом ради одного цвета значит
 * дважды сходить за значком, а подбирают цвет как раз посреди покраски.
 *
 * Решает НАЧАЛО протяжки: Alt, отпущенный по дороге, цвет не отменяет — рука
 * уже ведёт пипетку, и обрывать её на полпути было бы неожиданно.
 */
const sampling = (e) => tool === 'pick' || (e.altKey && tool === 'brush');

/**
 * Образец под пипеткой: цвет пикселя, на котором стоит курсор.
 *
 * Один на страницу и на вьювер. В 3D цвет берут внутри iframe, но рисовать
 * образец там значило бы держать вторую копию этого окошка — а вьювер про
 * палитру ничего не знает и знать не должен. Пустой цвет убирает образец:
 * курсор ушёл с модели, и показывать нечего.
 */
let spot = null;

function showSample(hex, x, y) {
  if (!spot) {
    spot = document.createElement('div');
    spot.className = 'pickspot';
    spot.innerHTML = '<i></i><b></b>';
    document.body.appendChild(spot);
  }
  spot.hidden = !hex;
  if (!hex) return;
  spot.querySelector('i').style.background = hex;
  spot.querySelector('b').textContent = hex;
  // Справа-снизу от курсора, как подсказка; у края окна — по другую сторону,
  // иначе образец уезжает за экран ровно там, где текстура и кончается.
  const box = spot.getBoundingClientRect();
  spot.style.left = Math.min(x + 18, window.innerWidth - box.width - 6) + 'px';
  spot.style.top = Math.min(y + 18, window.innerHeight - box.height - 6) + 'px';
}

/**
 * Пипетка по кадру слева — с зажатой кнопкой, как в редакторах изображений.
 *
 * Цвет видно, пока держат, и он берётся там, где отпустили: попасть в нужный
 * пиксель с первого щелчка нельзя — на кадре 2048 точек текстуры сжаты до
 * четырёхсот, и соседние пиксели там разного цвета.
 *
 * Всё в фазе перехвата: у кадра свой щелчок, он листает альбом, — и без этого
 * пипетка сперва уводила бы текстуру из-под курсора.
 */
(function bindFramePick() {
  const album = stage.album;
  let img = null;          // картинка, с которой сейчас берут цвет

  const sample = (e) => {
    const hex = img ? colorAt(img, e.clientX, e.clientY) : '';
    showSample(hex, e.clientX, e.clientY);
    return hex;
  };

  const stop = (e) => {
    if (album.hasPointerCapture(e.pointerId)) album.releasePointerCapture(e.pointerId);
    img = null;
    showSample('');
  };

  album.addEventListener('pointerdown', (e) => {
    if (!sampling(e)) return;
    const box = e.target.closest('.frame__img');
    // Не `img` вообще: поверх текстуры лежит подсветка части (`.frame__uv`), и
    // цвет надо брать из самой текстуры, а не из разметки над ней.
    img = box && box.querySelector('img:not(.frame__uv)');
    if (!img) return;
    e.preventDefault();     // иначе кадр уезжает перетаскиванием картинки
    album.setPointerCapture(e.pointerId);
    sample(e);
  }, true);

  album.addEventListener('pointermove', (e) => { if (img) sample(e); }, true);

  album.addEventListener('pointerup', (e) => {
    if (!img) return;
    const hex = sample(e);
    stop(e);
    takeColor(hex);         // пустой — отпустили мимо текстуры, и брать нечего
  }, true);

  album.addEventListener('pointercancel', (e) => { if (img) stop(e); }, true);

  album.addEventListener('click', (e) => {
    if (sampling(e)) e.stopPropagation();
  }, true);
})();

// Пипетка в палитре — обычный инструмент: кнопка его выбирает, а подсветку ей
// ставит showToolGroup по `data-tool`, как значкам в колонке. Повторный щелчок
// её снимает — иначе выйти из пипетки можно было бы только через другой
// инструмент, а вернуться к покраске хочется тем же движением.
document.getElementById('parts-drop').addEventListener('click',
  () => showToolGroup(tool === 'pick' ? null : 'pick'));

document.querySelector('.ptools__bar').addEventListener('click', (e) => {
  const btn = e.target.closest('[data-tool]');
  if (btn) showToolGroup(btn.dataset.tool);
});

/**
 * Квадрат открывает выбор цвета — и переход задаётся там же.
 *
 * Отдельным инструментом цвет не делаем: красит всё равно кисть, поэтому
 * щелчок по квадрату её и выбирает. Блок перехода переезжает в поповер: решать
 * «цвет или переход» в одном месте, а подбирать сам цвет в другом — значит
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

/** Поле цвета, который сейчас правят: первый или второй конец перехода. */
function colorField() {
  return document.getElementById(gradientEnd === 2 ? 'part-color2' : 'part-color');
}

document.getElementById('parts-swatch').addEventListener('click', openBrushColor);

/**
 * Ползунки на полосе перехода.
 *
 * Тянут их редко, а перекраска стоит десятых долей секунды на 2048 — поэтому
 * форма применяется по ОТПУСКАНИЮ, а полоса рисуется по ходу: видно сразу,
 * пересчитывается один раз.
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

/** Переводит выбор цвета на нужный конец перехода и отмечает его на полосе. */
function armEnd(end) {
  gradientEnd = end;
  document.querySelectorAll('#parts-ramp .parts__stop').forEach((b) => {
    b.classList.toggle('is-active',
      b.dataset.stop === (end === 2 ? 'end' : 'start'));
  });
  pickInto(colorField());
}

/**
 * Сворачивание палитры.
 *
 * Модель разглядывают и издали тоже, а колонка со своей панелью занимает
 * полосу кадра. Режим при этом не выключается: свёрнутая палитра — это всё
 * ещё режим частей, просто кадр чист.
 */
document.getElementById('parts-fold').addEventListener('click', () => {
  const bar = document.getElementById('partspaint');
  const folded = bar.classList.toggle('is-folded');
  const btn = document.getElementById('parts-fold');
  btn.title = t(folded ? 'Развернуть палитру' : 'Свернуть палитру');
});

document.getElementById('parts-join').addEventListener('click', async () => {
  const chosen = (partsList || []).filter((x) => marked.has(x.id));
  if (chosen.length < 2) return;
  const islands = [...new Set(chosen.flatMap((x) => x.islands || []))];
  hintParts('Объединяю…');
  const res = await api.mergePartIslands(partsMaterial, chosen[0].group, islands);
  if (res.error) { hintParts(res.error); return; }
  marked.clear();
  applyView(res);
  await refreshParts();
  hintParts('Отрезки сведены в одну часть');
});

/**
 * Окантовка: полоса по краю покрашенных частей.
 *
 * Ширина уходит в Python долей стороны текстуры, а не пикселями: одна и та же
 * работа собирается и в 512, и в 2048, и полоса должна выглядеть одинаково.
 * Ползунок при этом показывает тысячные доли — «6» это 0.006 стороны.
 */
async function applyEdge() {
  if (partsMaterial === null) return;
  const on = document.getElementById('parts-edge').classList.contains('is-active');
  const width = on ? Number(document.getElementById('part-edge-width').value) / 1000 : 0;
  const color = document.getElementById('part-edge-color').value;
  const res = await api.setPartEdge(partsMaterial, width, color);
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
// Цвет и толщину применяем по отпусканию: каждое движение ползунка —
// пересборка всей текстуры, а это десятые доли секунды на 2048.
document.getElementById('part-edge-width').addEventListener('change', applyEdge);
document.getElementById('part-edge-color').addEventListener('change', applyEdge);

document.getElementById('parts-done').addEventListener('click', closeParts);

document.getElementById('parts-grad').addEventListener('click', (e) => {
  gradientOn = !gradientOn;
  e.target.classList.toggle('is-active', gradientOn);
  document.getElementById('parts-grad-aim').hidden = !gradientOn;
  // Выключили переход — правим снова первый цвет: второго больше нет.
  if (!gradientOn) armEnd(1);
  else pickInto(colorField());
  showColor();   // задний квадрат в колонке появляется вместе с переходом
  hintParts(gradientOn ? 'Градиент: щёлкай по частям — переход из первого цвета. '
                       + 'Полоса задаёт края и середину перелива, ручка — направление'
                       : '');
});

/**
 * Ручка направления градиента.
 *
 * Угол берётся от центра ручки к указателю, поэтому «потянуть в ту сторону,
 * куда должен идти переход» — и есть всё управление. Ровные направления
 * (каждые 45°) подтягиваются: попасть в точную вертикаль мышью иначе нельзя,
 * а хочется её чаще всего.
 */
function setGradientAngle(deg) {
  let angle = ((deg % 360) + 360) % 360;
  const step = Math.round(angle / 45) * 45;
  if (Math.abs(angle - step) < 6) angle = step % 360;
  gradientAngle = angle;
  // Стрелка нарисована ВНИЗ — это и есть нулевое направление, «сверху вниз».
  // CSS крутит по часовой, а угол растёт против неё, отсюда минус.
  const needle = document.querySelector('#parts-grad-dir .parts__needle');
  needle.style.transform = 'rotate(' + (-angle) + 'deg)';
  hintParts('Направление перехода: ' + Math.round(angle) + '°');
}

(function bindGradientDial() {
  const dial = document.getElementById('parts-grad-dir');
  const aim = (e) => {
    const r = dial.getBoundingClientRect();
    // Экранный y растёт вниз, а 0° — «сверху вниз», то есть в сторону
    // возрастания y. Отсюда atan2(dx, dy), а не привычный atan2(dy, dx).
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
  // С клавиатуры — шагом 15°: ручку надо уметь довернуть и без мыши.
  dial.addEventListener('keydown', (e) => {
    const step = { ArrowLeft: -15, ArrowDown: -15, ArrowRight: 15, ArrowUp: 15 }[e.key];
    if (step === undefined) return;
    e.preventDefault();
    setGradientAngle(gradientAngle + step);
    applyGradientShape();
  });
})();

/**
 * Отмена и возврат — только с клавиатуры.
 *
 * Кнопки в полосе у них нет намеренно: красят десятками щелчков подряд, а
 * откатывают редко, и ряд действий из-за неё стоял вчетвером. Раскладка та
 * же, что везде: Ctrl+Z назад, Ctrl+Y (и Ctrl+Shift+Z, как в редакторах)
 * вперёд.
 *
 * Пока курсор в поле ввода, клавиши принадлежат ему: там своя отмена текста.
 *
 * Разбор вынесен в функцию, потому что то же нажатие приходит ИЗ ВЬЮВЕРА:
 * щелчок по модели отдаёт фокус iframe, и обещанный подсказкой Ctrl+Z молча
 * не работал, пока не щёлкнешь мимо кадра — а красят как раз по модели.
 * Второй копии раскладки при этом нет: вьювер передаёт само событие.
 */
function historyKey(e) {
  const editing = /^(INPUT|TEXTAREA)$/.test(document.activeElement?.tagName || '');
  if (!(e.ctrlKey || e.metaKey) || editing
      || document.getElementById('partsbar').hidden) return;
  const key = e.key.toLowerCase();
  const back = key === 'z' && !e.shiftKey;
  const forward = key === 'y' || (key === 'z' && e.shiftKey);
  if (!back && !forward) return;
  e.preventDefault();
  if (back) undoParts();
  else redoParts();
}

document.addEventListener('keydown', historyKey);

document.getElementById('parts-clear').addEventListener('click', async () => {
  const res = await api.clearParts(partsMaterial);
  if (res.error) { hintParts(res.error); return; }
  applyView(res);
  await refreshParts();
  hintParts('');
});
