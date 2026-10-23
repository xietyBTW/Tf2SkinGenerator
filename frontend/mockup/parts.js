/*
 * Части модели: покрасить кусок геометрии, а не весь материал
 *
 * Материал у оружия почти всегда один - «покрасить только ствол» это кусок
 * геометрии, а не второй материал. Разбор и склейку делает Python; страница
 * показывает полосу частей, включает подсветку во вьювере и передаёт файл
 *
 * Полоса - три группы под вкладками (кисть, нарезка, окантовка), а не всё
 * сразу: человек в момент времени делает что-то одно, и показ всего разом был
 * причиной тесноты
 *
 * Здесь - разбор, полоса частей, связь с вьювером и история правок. Области
 * палитры - свои модули: parts-palette (цвет, переход, окантовка), parts-cut
 * (ножницы), parts-materials (свой материал части), parts-tools (значки,
 * курсор, пипетка), parts-panel (место и размер панели). Общее состояние -
 * parts-state.
 */

import * as api from './api.js';
import { chooseFile } from './util.js';
import { t } from './i18n.js';
import { stage, viewer, say } from './stage.js';
import { root } from './layout.js';
import { applyView } from './preview.js';
import { editPartLayers, imageClip, pasteImageTo } from './place.js';
import { closeColor } from './picker.js';
import { P, hintParts } from './parts-state.js';
import { cutOpts, applyCut, resetCut, showCutCount, selectWholePart, chunkStep, setCutMode }
  from './parts-cut.js';
import { showPalette, resetPalette, paintSpec } from './parts-palette.js';
import { showToolGroup, takeColor, showSample } from './parts-tools.js';
import { toggleMaterial, matOrder, isNative, showPartMaterials, partMenu }
  from './parts-materials.js';
import './parts-panel.js';

export { hintParts };

//: {ключ разбиения и части: обещание картинки-подсветки}. Наводят десятки раз,
//: а форма части меняется только от резки - второй раз спрашивать нечего.
//: Обещание, а не готовый адрес: на одно наведение приходят ДВА вызова - от
//: списка частей и от вьювера, - и с адресом первый кусок спрашивался дважды
const partMasks = new Map();
//: Номер последнего наведения: ответ на прошлое мог прийти после того, как
//: курсор уехал на соседнюю часть, и тогда подсветилась бы не та
let spotSeq = 0;
//: Идёт ли смена активного материала: курсор на границе мешей иначе слал бы
//: запрос на каждый кадр
let switching = false;
//: Часть под курсором. Нужна перерисовке полосы: список приходит ответом
//: Python и успевает обновиться уже после того, как чип пометили
let hoverPart = null;
//: Часть под курсором НА МОДЕЛИ - цель Ctrl+V для скопированной картинки.
//: Только модель: в списке частей вставки нет
let modelHover = null;

/** Включает и выключает режим частей */
export async function togglePartsMode() {
  const bar = document.getElementById('partsbar');
  if (!bar.hidden) { closeParts(); return; }
  const res = await loadParts();
  if (res && res.parts.length < 2) {
    hintParts('Эта модель - один цельный кусок, делить нечего');
  } else if (res) {
    hintParts('Возьми значок справа: кисть красит, ножницы дробят кусок. '
            + 'Ctrl+Z отменяет, Ctrl+Y возвращает');
  }
}

/**
 * Разбирает модель на части и включает подсветку
 *
 * Зовётся и по кнопке, и вьювером, когда на модель ТАЩАТ картинку: разбор
 * стоит около сотой доли секунды, и заставлять ради него нажимать кнопку -
 * значит терять тот единственный момент, когда подсветка что-то объясняет.
 */
export async function loadParts() {
  const res = await api.parts();
  if (res.error) { hintParts(res.error); return null; }

  P.material = res.material;
  P.main = res.material;
  showParts(res);
  showPalette(res);

  const w = viewer();
  if (w) w.setPartsMode(true);
  await loadOtherMaterials(res.material);
  return res;
}

/**
 * Готовит разбор для перетаскивания: вьюверу - карты частей, чтобы он
 * подсвечивал деталь под курсором. Режим при этом НЕ открывается
 *
 * Не `loadParts` целиком: картинку несут с рабочего стола к карточке текстуры,
 * задевают по пути кадр модели, и палитра с частями открылась бы без просьбы.
 * Режим откроется, только если картинку бросят на деталь (onPartDropped).
 */
let priming = false;
async function primeParts() {
  if (priming) return;
  priming = true;
  try {
    const res = await api.parts();
    if (res.error) return;
    rememberMaps(res);
    await loadOtherMaterials(res.material);
  } finally {
    priming = false;
  }
}

/**
 * Карты треугольников ОСТАЛЬНЫХ материалов модели
 *
 * У шпиона голова и тело - разные материалы, у каждого своя развёртка и свой
 * разбор. Пока вьювер знал одну карту, он применял её ко ВСЕМ мешам (иначе
 * одноматериальные модели, где карта лежит под служебным ключом, вообще не
 * подсвечивались бы) - и наведение на тело возвращало номер части ГОЛОВЫ, а
 * разметка рисовалась на её текстуре
 *
 * Материалы берём из альбома: это ровно то, что человек видит кадрами.
 */
async function loadOtherMaterials(main) {
  const mats = [...document.querySelectorAll('.frame')]
    .map((f) => f.dataset.mat)
    .filter((m) => m && m !== main);
  if (!mats.length) return;          // одноматериальная модель - грузить нечего
  for (const mat of mats) {
    const res = await api.parts(mat);
    if (!res.error) rememberMaps(res);
  }
}

/**
 * Складывает карты материала и отдаёт вьюверу ВСЕ, что уже известны
 *
 * Именно все: `setModelParts` заменяет карту целиком, и передача одной стирала
 * бы соседний материал - а с одной записью вьювер снова начинал применять её к
 * чужим мешам.
 */
function rememberMaps(res) {
  if (!res || !res.material) return;
  if (res.shape) P.shapes[res.material] = res.shape;
  if (res.tri_part) P.maps[res.material] = res.tri_part;
  const w = viewer();
  if (!w || !res.tri_part) return;
  w.setModelParts({ ...P.maps });
}

/**
 * Делает материал активным: список частей и покраска относятся к нему
 *
 * Зовётся наведением: курсор ушёл с головы на тело - и полоса частей, и
 * разметка на текстуре должны говорить про тело. Переключение идёт по одному:
 * курсор на границе мешей иначе слал бы запрос на каждый кадр.
 */
export function partsTarget(material) {
  return hasOwnParts(material) ? material
    : (!String(material).startsWith('deco:') ? P.main : null);
}

export async function usePartsMaterial(material) {
  if (!material || switching) return;
  if (P.material === null) return;      // режим не открывали - нечего менять
  // Меш без своего разбора - это меш предмета с картой под служебным ключом
  // (одноматериальная модель). Рядом бывает гирлянда, и вернуться с неё на
  // оружие надо к ГЛАВНОМУ разбору
  const target = partsTarget(material);
  if (!target || target === P.material) return;
  switching = true;
  try {
    const res = await api.parts(target);
    if (res.error) return;
    P.material = res.material;
    showParts(res);
  } finally {
    switching = false;
  }
}

/**
 * Связывает вьювер с частями
 *
 * Ставится на КАЖДУЮ модель, а не по кнопке: перетаскивание картинки на кусок
 * должно работать сразу - иначе про части узнают, только случайно нажав
 * кнопку.
 */
export function bindParts(w) {
  // Разбор относился к ПРОШЛОЙ модели: у новой под тем же номером другой кусок
  closeParts();
  w.setModelParts(null);
  w.onPartsNeeded = () => { if (P.material === null) primeParts(); };
  // Материал приходит со ВСЕМИ вызовами вьювера: у модели их бывает
  // несколько, и часть под курсором принадлежит своему, а не тому, что сейчас
  // показан полосой.
  // Ctrl+щелчок по части: она на виду, остальное полупрозрачное (вьювер)
  w.onPartIsolated = (part) => {
    isolated = part !== null && part !== undefined;
    hintParts(isolated ? 'Видна только эта часть - Esc или Ctrl+щелчок по ней, чтобы вернуть' : '');
  };
  w.onPartHover = (part, material) => {
    modelHover = (part === null || part === undefined) ? null : { part, material };
    spotlightPart(part, material);
  };
  w.onPartDropped = async (material, part, file) => {
    // Картинку бросили на деталь - вот теперь человек работает частями, и
    // режим открывается (при перетаскивании он был только подготовлен)
    if (P.material === null && !(await loadParts())) return;
    await usePartsMaterial(material);
    paintPart(part, file);
  };
  // Пипетка в 3D: цвет вьювер берёт из текстуры под курсором - той же, что
  // показана кадром, поэтому оба входа пипетки дают один ответ
  w.onColorPicked = (hex) => takeColor(hex);
  // Отмена принадлежит странице, а фокус после щелчка по модели достаётся
  // iframe: вьювер передаёт нажатие, разбирает его тот же код (см. historyKey)
  w.onPartsKey = (e) => historyKey(e);
  // Пока кнопку держат, вьювер шлёт цвет под курсором вместе со своими
  // координатами: образец рисует страница, и место ему нужно в её системе
  w.onColorSample = (hex, x, y) => {
    const box = stage.frame.getBoundingClientRect();
    showSample(hex, x + box.left, y + box.top);
  };
  w.onPartPicked = async (material, part) => {
    await usePartsMaterial(material);
    pickPart(part);
  };
  // Ножницы: вьювер выделяет и сообщает, сколько; Enter и Esc приходят
  // оттуда же - фокус после щелчка по модели у него
  w.onCutSelection = (count) => showCutCount(count);
  w.onCutKey = (key) => (key === 'Enter' ? applyCut() : resetCut());
  if (w.setCutOptions) w.setCutOptions(cutOpts);
  if (w.setCutMode) w.setCutMode(P.cutMode);
}

/** Что делает щелчок по части: кисть красит, курсор спрашивает картинку */
function pickPart(part) {
  if (P.tool === 'image') { paintPart(part); return; }
  if (P.tool === 'material') { toggleMaterial(part); return; }
  // Всё остальное по части не работает: окантовка идёт по всей работе, цвет
  // берут с самой картинки, а без инструмента щелчку нечего делать.
  // `paintPart` на любой инструмент открыл бы выбор файла и для окантовки
  if (P.tool !== 'brush') {
    hintParts(P.tool === 'pick'
      ? 'Пипеткой щёлкай по модели или по текстуре слева, а не по списку'
      : 'Возьми кисть справа - щелчок по части покрасит её');
    return;
  }
  colorParts({ [part]: paintSpec(P.brushColor) });
  // Цвет ложится ПОД картинку: там, где она непрозрачна, его не увидеть.
  // Сказать об этом надо в тот момент, когда это произошло, - иначе человек
  // решит, что покраска не сработала
  const known = (P.list || []).find((x) => x.id === part);
  if (known && (known.images || []).length) {
    hintParts('У этой части своя картинка - цвет лёг под неё');
  }
}

/**
 * Есть ли у этого имени СВОЙ разбор
 *
 * Вьювер называет материал МЕША, а ключ разбора - наш, и сойтись они могут
 * далеко не всегда: у одноматериальной модели разбор лежит под служебным
 * ключом («__single__»), а вьювер в этом случае применяет единственную карту к
 * любому мешу и возвращает его собственное имя. В сцене от первого лица рядом
 * с оружием стоят и вовсе чужие меши
 *
 * Без этой проверки каждое наведение просило «переключись на материал меша», а
 * такой запрос присылает карты треугольников заново - вьювер, получив их,
 * гасит подсветку куска. Отсюда были и мигание под курсором (её создавало
 * движение и тут же убивал ответ), и полное её отсутствие, если мышь стояла на
 * месте. Тем же ответом перестраивалась полоса частей: кнопка «×» уезжала
 * из-под курсора между нажатием и отпусканием, и щелчок по ней пропадал.
 */
function hasOwnParts(name) {
  return Object.prototype.hasOwnProperty.call(P.maps, name);
}

/**
 * Показывает место части НА ТЕКСТУРЕ
 *
 * Связь «кусок модели ↔ участок картинки» иначе видна только тому, кто сам
 * делал развёртку. Наведение показывает её обеим сторонам сразу: и в 3D, и на
 * кадре слева.
 */
async function spotlightPart(part, material) {
  // Кадр - ТОГО материала, которому принадлежит часть. У шпиона голова и тело
  // разные материалы, и разметка тела, нарисованная на текстуре головы, - это
  // не подсказка, а дезинформация.
  // Имя из вьювера годится только когда у него есть свой разбор: иначе это
  // имя меша, а разметку надо рисовать на кадре ТЕКУЩЕГО материала. Заодно
  // ключ кэша маски выходит один и тот же у наведения на модель и на чип, и
  // одну маску не спрашивают дважды
  const owner = hasOwnParts(material) ? material : P.material;
  const frame = [...document.querySelectorAll('.frame')]
    .find((f) => f.dataset.mat === owner)
    || document.querySelector('.frame.is-current');
  document.querySelectorAll('.frame__uv').forEach((b) => b.remove());
  document.querySelectorAll('#partsbar .tag').forEach((b) => {
    b.classList.toggle('is-hover', Number(b.dataset.part) === part);
  });
  // Помним, на чём стоит курсор: полоса частей могла быть перерисована уже
  // ПОСЛЕ этой пометки (смена материала под курсором приходит ответом Python),
  // и новые чипы вышли бы без подсветки
  hoverPart = (part === null || part === undefined) ? null : part;
  const mine = ++spotSeq;
  if (part === null || part === undefined || !frame) return;
  // Полоса частей и покраска идут за курсором: ушёл на другой кусок модели -
  // и список, и «Убрать всё» относятся уже к его материалу
  if (material && material !== P.material) usePartsMaterial(material);

  // Форму рисует Python той же маской, по которой красит склейка. Картинкой, а
  // не списком координат: у крупного куска их полторы тысячи, и возить их на
  // каждое наведение дороже, чем отдать PNG в несколько килобайт.
  // Ключ с материалом: номера частей у каждого свои, и одна и та же «часть 3»
  // у головы и у тела - разные куски
  const key = owner + '|' + (P.shapes[owner] || P.shape) + '|' + part;
  let mask = partMasks.get(key);
  if (!mask) {
    mask = api.partMask(owner, part)
      .then((res) => (res.error ? null : api.fileUrl(res.mask)));
    partMasks.set(key, mask);
  }
  const url = await mask;
  // Неудачу не запоминаем: со следующим наведением стоит попробовать снова
  if (!url) { partMasks.delete(key); return; }
  // Пока ждали ответ, курсор мог уехать: подсвечивать уже не то нельзя
  if (mine !== spotSeq || !frame.isConnected) return;

  const spot = document.createElement('img');
  spot.className = 'frame__uv';
  spot.src = url;
  frame.querySelector('.frame__img').appendChild(spot);
}

//: Был ли режим частей открыт, когда его отложили сценой. Вид от первого лица
//: и насмешка собраны из ДРУГОЙ геометрии - руки класса, персонаж, - а карта
//: треугольников у страницы от обычной модели: подсветка и покраска попадали
//: бы не туда. Поэтому на сцене режим гасится, а по возвращении включается
//: сам: человек его не закрывал, и заново искать кнопку ему незачем
let suspended = false;

/** Откладывает режим частей на время сцены. Закрыт - откладывать нечего */
export function suspendParts() {
  suspended = !document.getElementById('partsbar').hidden;
  if (suspended) closeParts();
}

/** Возвращает отложенный режим. Зовётся ПОСЛЕ возврата обычной модели: разбор
 *  спрашивается у Python по ней, и на сцене ответ был бы про чужую */
export async function resumeParts() {
  if (!suspended) return;
  suspended = false;
  await loadParts();
}

/** Выходит из режима частей: покраска остаётся, уходит только полоса */
export function closeParts() {
  const bar = document.getElementById('partsbar');
  bar.querySelectorAll('.tag').forEach((b) => b.remove());
  bar.hidden = true;
  document.getElementById('partspaint').hidden = true;
  document.getElementById('partspaint').classList.remove('is-folded');
  // Выбор цвета держит у себя блок перехода: уйти, не закрыв его, значило бы
  // оставить кусок спрятанной палитры висеть поверх кадра
  closeColor();
  showToolGroup(null);      // следующий раз палитра откроется без кисти
  resetPalette();
  hintParts('');
  setCutMode(false);
  spotlightPart(null);
  P.material = null;
  P.list = [];
  P.groups = {};
  P.shape = '';
  Object.keys(P.maps).forEach((m) => delete P.maps[m]);
  Object.keys(P.shapes).forEach((m) => delete P.shapes[m]);
  const w = viewer();
  if (w) w.setPartsMode(false);
  // Подгонка прячет свою кнопку, пока части открыты: сообщаем, что закрылись
  document.dispatchEvent(new Event('parts:changed'));
}

/** Открывает части сразу с ножницами - для «Разрезать деталь» в War Paint */
export async function openPartsCut() {
  const res = await loadParts();
  if (res) showToolGroup('cut');
  return res;
}

/** Полоса частей: крупные первыми, покрашенные помечены */
export function showParts(res) {
  const bar = document.getElementById('partsbar');
  const grid = document.getElementById('parts-grid');
  grid.replaceChildren();
  bar.hidden = false;
  document.getElementById('parts-count').textContent = String(res.parts.length);
  bar.dispatchEvent(new Event('parts:shown'));
  // Доля развёртки - относительно самой крупной части, корнем: винтик рядом со
  // стволом иначе был бы полоской в пиксель
  const biggest = Math.max(1e-9, ...res.parts.map((x) => x.area || 0));
  document.dispatchEvent(new Event('parts:changed'));

  // Карту «треугольник -> часть» вьювер получает по имени материала: у него
  // геометрия сгруппирована так же, как её отдал Python. Отдаём её ЗДЕСЬ, а не
  // только при первом разборе: после дробления номера другие, и по старой
  // карте щелчок вернул бы номер из прежнего разбиения
  P.list = res.parts;
  P.groups = res.group_islands || {};
  P.shape = res.shape || '';
  // Карты приходят только при смене разбиения: нет их в ответе - у вьювера
  // уже лежат нужные, и слать undefined значило бы стереть их
  rememberMaps(res);
  showPartMaterials(res.materials, res.targets);
  // Гирлянде и своей модели своих материалов не дать: значок не обещает
  document.querySelector('#partspaint [data-tool="material"]').hidden = !res.can_own;
  if (!res.can_own && P.tool === 'material') showToolGroup(null);

  res.parts.forEach((part) => {
    const images = part.images || [];
    const b = document.createElement('button');
    b.className = 'tag' + (images.length || part.color ? ' is-painted' : '')
      + (part.shared.length ? ' tag--shared' : '');
    b.dataset.part = part.id;
    b.style.setProperty('--share', Math.sqrt((part.area || 0) / biggest).toFixed(3));
    // На кнопке - только номер: частей бывает под три десятка, и «Часть 7 · 3%»
    // в двух строках делало из полосы стену. Доля развёртки ушла в подсказку -
    // «0%» там читается как поломка, поэтому у винтика пишем «<1%»
    //
    // Номер - КУСКА, а не сквозной по списку: сквозной съезжал от каждого
    // разреза, и человек терял из виду ту часть, с которой работал. Разрезанный
    // кусок даёт «04·1», «04·2» - видно и что это одно место модели, и что их
    // теперь несколько
    const share = part.area >= 0.01 ? Math.round(part.area * 100) + '%' : '<1%';
    const label = String(part.chunk + 1).padStart(2, '0')
                + (part.sub ? '·' + part.sub : '');
    const num = document.createElement('span');
    num.textContent = label;
    b.append(num);
    const size = document.createElement('span');
    size.className = 'part__size';
    b.append(size);
    // Куски, делящие развёртку, в игре красятся вместе - сказать об этом надо
    // до того, как человек нарисует и удивится
    b.title = t('Часть ') + label + ' · ' + share + t(' развёртки')
      + (part.shared.length
        ? '\n' + t('Делит развёртку с другими: в игре они покрасятся вместе, '
          + 'разными их сделать нельзя')
        : '');
    // Метка своего материала - его номер из списка инструмента «Материал»
    if (part.own) {
      const mark = document.createElement('span');
      mark.className = 'part__mat';
      mark.textContent = String(matOrder().indexOf(part.own) + 1);
      b.append(mark);
      b.title += '\n' + (isNative(part.own)
        ? t('Отдана материалу модели: {}') : t('Свой материал: {}')).replace('{}', part.own);
    }
    if (res.can_own) b.addEventListener('contextmenu', (e) => partMenu(e, part));
    // Наведение на пункт списка подсвечивает кусок на модели: иначе «Часть 3»
    // - это просто номер, и какой именно кусок за ним, узнать неоткуда
    b.addEventListener('mouseenter', () => {
      // Материал называем явно: у модели их бывает несколько, и «часть 3» есть
      // у каждого - без имени подсветился бы кусок соседнего меша
      viewer()?.highlightPart(part.id, P.material);
      spotlightPart(part.id, P.material);
    });
    b.addEventListener('mouseleave', () => {
      viewer()?.highlightPart(null);
      spotlightPart(null);
    });
    b.title += '\n' + t('Ctrl+щелчок - показать только эту часть');
    b.addEventListener('click', (e) => {
      if (e.target.closest('.parts__x, .parts__cut')) return;
      if (e.ctrlKey || e.metaKey) { viewer()?.isolatePart(part.id, P.material); return; }
      // С ножницами щелчок по чипу кладёт в выделение ВСЮ часть: так две
      // части сводят в одну - выделил обе, «Отделить»
      if (P.cutMode) { selectWholePart(part); return; }
      pickPart(part.id);
    });
    if (part.color) {
      const { color, color2 } = part.color;
      b.style.setProperty('--paint', color2
        ? 'linear-gradient(180deg,' + color + ',' + color2 + ')' : color);
    }
    // Кнопка только на ОТРЕЗАННОЙ части - вернуть её туда, откуда вырезали
    if ((part.islands && part.islands.length) || part.region >= 0) {
      b.appendChild(chunkStep(part, '−', 'Прирастить обратно'));
    }
    // У части с картинками - вход в их редактор: посадка, замена, ещё одна.
    // Туда же ведёт щелчок по чипу с картинкой-курсором, кнопка - для тех,
    // у кого в руке кисть
    if (images.length) {
      const fix = document.createElement('button');
      fix.className = 'parts__cut';
      fix.type = 'button';
      fix.textContent = images.length > 1 ? images.length + '…' : '…';
      fix.title = 'Картинки части: посадка, замена, ещё одна';
      fix.addEventListener('click', (e) => {
        e.stopPropagation();
        editPartLayers(part.id);
      });
      b.appendChild(fix);
    }
    if (part.id === hoverPart) b.classList.add('is-hover');
    if (images.length || part.color) {
      const x = document.createElement('button');
      x.className = 'parts__x';
      x.type = 'button';
      x.textContent = '×';
      x.title = 'Вернуть этой части игровую текстуру';
      // Снимаем ОБА слоя: у части может быть и цвет, и картинка поверх него, а
      // крестик обещает вернуть игровую текстуру - то есть убрать всё своё
      x.addEventListener('click', async () => {
        if (images.length) await paintPart(part.id, null);
        if (part.color) await colorParts({ [part.id]: null });
      });
      b.appendChild(x);
    }
    // Действий на чипе больше одного - одна клетка сетки для них узка
    if (b.querySelectorAll('button').length > 1) b.classList.add('part--wide');
    grid.appendChild(b);
  });
}

/** Красит части: {часть: цвет}, значение null снимает цвет */
export async function colorParts(colors) {
  const strength = Number(document.getElementById('part-tint').value) / 100;
  const exact = document.getElementById('part-exact').checked;
  const res = await api.setPartColors(P.material, colors, strength, exact);
  if (res.error) { hintParts(res.error); return; }
  applyView(res);
  await refreshParts();
}

/** Перечитывает список частей - после любой покраски */
export async function refreshParts() {
  const fresh = await api.parts(P.material, P.shape);
  if (!fresh.error) showParts(fresh);
  return fresh;
}

/**
 * Картинка на часть
 *
 * `file` не задан - щелчок по части: у части с картинками открывает их
 * редактор (посадка, замена, ещё одна), у пустой спрашивает файл. `null` -
 * снять: слой `layer` либо все. Файл (в том числе брошенный на модель)
 * ложится сразу, поверх лежащих или на место слоя `layer`, и тут же
 * открывается редактор - поправить посадку, глядя на неё на месте.
 */
export async function paintPart(part, file = undefined, layer = null) {
  if (file === undefined) {
    const known = (P.list || []).find((x) => x.id === part);
    if (known && (known.images || []).length) { await editPartLayers(part); return; }
    file = await chooseFile('image/*,.vtf');
    if (!file) return;
  }
  hintParts(file ? 'Наложение на часть…' : 'Убираю…');
  try {
    const path = file ? await api.upload(file) : null;
    const res = await api.setPartTexture(P.material, part, path, null, layer);
    if (res.error) { hintParts(res.error); return; }
    applyView(res);
    const fresh = await refreshParts();
    // Куски, делящие развёртку, красятся вместе. Сказать об этом надо в тот
    // момент, когда это произошло, а не только подсказкой на кнопке
    const painted = (fresh.parts || []).find((p) => p.id === part);
    hintParts(file && painted && painted.shared.length
      ? 'Эта часть делит развёртку с соседними - они покрасились вместе'
      : '');
    if (file) await editPartLayers(part, layer === null ? -1 : layer);
  } catch (err) {
    hintParts(`Не удалось: ${err.message}`);
  }
}

document.getElementById('parts').addEventListener('click', togglePartsMode);

/**
 * Подробность резки: 0 - куски геометрии, 100 - каждый шов развёртки
 *
 * Спрашиваем по `change`, а не по `input`: перерезка модели и пересборка
 * склейки на каждом пикселе протяжки - это десятки лишних разборов.
 */
document.getElementById('part-detail').addEventListener('change', async (e) => {
  if (P.material === null) return;
  hintParts('Перерезаю модель…');
  const res = await api.setPartDetail(P.material, Number(e.target.value) / 100);
  if (res.error) { hintParts(res.error); return; }
  applyView(res);
  const fresh = await refreshParts();
  hintParts('Частей: ' + ((fresh && fresh.parts) || []).length);
});

// Отмена - то, что позволяет пробовать: без неё каждый щелчок по модели
// приходится обдумывать заранее
export async function undoParts() {
  return stepHistory(-1);
}

/** Возвращает вперёд то, что отменили */
export async function redoParts() {
  return stepHistory(1);
}

/**
 * Шаг по истории правок предмета - в любую сторону: движение одно и то же
 *
 * История одна на всё (текстуры, части, своя модель): Python держит её
 * снимками `user_edits`. Полоса частей, если открыта, перечитывается: шаг
 * возвращает и силу тонировки с окантовкой, а они живут на ползунках - без
 * этого контролы показывали бы значения, от которых на модели уже ничего не
 * осталось.
 */
async function stepHistory(delta) {
  const open = !document.getElementById('partsbar').hidden;
  const tell = open ? hintParts : say;
  const res = await api.undoEdits(delta);
  if (res.error) { tell(res.error); return; }
  applyView(res);
  if (open) {
    const fresh = await refreshParts();
    if (fresh && !fresh.error) showPalette(fresh);
  }
  tell(delta < 0 ? 'Отменено' : 'Возвращено');
}

document.getElementById('parts-done').addEventListener('click', closeParts);

/**
 * Отмена и возврат - только с клавиатуры
 *
 * Кнопки у них нет намеренно: красят десятками щелчков подряд, а откатывают
 * редко, и ряд действий из-за неё стоял вчетвером. Раскладка та же, что
 * везде: Ctrl+Z назад, Ctrl+Y (и Ctrl+Shift+Z, как в редакторах) вперёд.
 * Работает по всему редактору предмета, не только в частях: положенная
 * текстура и подменённая модель откатываются той же лентой
 *
 * Пока курсор в поле ввода, клавиши принадлежат ему: там своя отмена текста.
 * У раздела эффектов история своя (particles/playback.js)
 *
 * Разбор вынесен в функцию, потому что то же нажатие приходит ИЗ ВЬЮВЕРА:
 * щелчок по модели отдаёт фокус iframe, и обещанный подсказкой Ctrl+Z молча
 * не работал, пока не щёлкнешь мимо кадра - а красят как раз по модели.
 * Второй копии раскладки при этом нет: вьювер передаёт само событие.
 */
function historyKey(e) {
  const editing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '');
  if (!(e.ctrlKey || e.metaKey) || editing
      || document.querySelector('dialog[open]')
      // У эффектов история своя, у звуков предмета нет вовсе
      || root.dataset.section === 'particles' || root.dataset.section === 'sounds') return;
  // Скопированная в окне посадки картинка - на деталь под курсором
  if (e.code === 'KeyV' && modelHover && imageClip()) {
    e.preventDefault();
    pasteOnModel(modelHover);
    return;
  }
  // По коду клавиши, а не по символу: в русской раскладке Z - это «я»
  const back = e.code === 'KeyZ' && !e.shiftKey;
  const forward = e.code === 'KeyY' || (e.code === 'KeyZ' && e.shiftKey);
  if (!back && !forward) return;
  e.preventDefault();
  stepHistory(back ? -1 : 1);
}

document.addEventListener('keydown', historyKey);

//: Показана ли одна часть (Ctrl+щелчок): Esc на странице возвращает модель,
//: когда фокус не у вьювера
let isolated = false;
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && isolated && !document.querySelector('dialog[open]')) {
    viewer()?.isolatePart(null);
  }
});

/** Ctrl+V над деталью: скопированная картинка того же размера - на неё */
async function pasteOnModel(target) {
  await usePartsMaterial(target.material);
  hintParts('Вставляю…');
  if (await pasteImageTo(target.part)) {
    hintParts('Картинка вставлена - поправить посадку можно в «…»');
  }
}

document.getElementById('parts-clear').addEventListener('click', async () => {
  const res = await api.clearParts(P.material);
  if (res.error) { hintParts(res.error); return; }
  applyView(res);
  await refreshParts();
  hintParts('');
});
