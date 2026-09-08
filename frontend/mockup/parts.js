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
import { withViewer, viewer } from './stage.js';
import { applyView } from './preview.js';
import { askPartPlacement, repositionPart } from './place.js';

// ── Части модели ────────────────────────────────────────────────────────
// Материал у оружия почти всегда один: «покрасить только ствол» — это кусок
// геометрии, а не второй материал. Разбор и склейку делает Python, страница
// показывает список, включает подсветку во вьювере и передаёт файл.

export let partsMaterial = null;   // материал разобранной модели; null — не разбирали

/** Включает и выключает режим частей. */
//: Готовые цвета: пять оттенков, которыми чаще всего и красят.
const PART_COLORS = ['#c83c3c', '#3c6ec8', '#3ca05a', '#d2a03c', '#2a2a2a'];

export let armedColor = '';      // цвет, которым красит щелчок; пусто — цвета нет
//: {ключ разбиения и части: картинка-подсветка}. Наводят десятки раз, а форма
//: части меняется только от резки — второй раз спрашивать нечего.
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
//: Отмеченные для слияния отрезки: номера частей. Живут только в режиме резки.
let marked = new Set();
export let gradientOn = false;   // красить переходом из первого цвета во второй
export let gradientAngle = 0;    // направление перехода в градусах: 0 — сверху вниз

/** Включает и выключает режим частей. */
export async function togglePartsMode() {
  const bar = document.getElementById('partsbar');
  if (!bar.hidden) { closeParts(); return; }
  const res = await loadParts();
  if (res && res.parts.length < 2) {
    hintParts('Эта модель — один цельный кусок, делить нечего');
  } else if (res) {
    hintParts('Щёлкай по кускам модели — покрасятся. Нарезать мельче или '
            + 'обвести края — вкладками слева. Ctrl+Z отменяет, Ctrl+Y '
            + 'возвращает');
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
  return res;
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
  w.onPartHover = (part) => spotlightPart(part);
  w.onPartDropped = (material, part, file) => paintPart(part, file);
  w.onPartPicked = (material, part) => {
    if (armedColor) colorParts({ [part]: paintSpec(armedColor) });
    else paintPart(part);
  };
  // Резать там же, где смотрят: щелчок отрезает ОБВЕДЁННЫЙ остров развёртки
  // или приращивает его обратно. Номер части нужен, чтобы узнать её группу.
  w.onPartCut = (material, part, island) => cutIsland(part, island);
  if (w.setCutMode) w.setCutMode(cutMode);
}

/**
 * Показывает место части НА ТЕКСТУРЕ.
 *
 * Связь «кусок модели ↔ участок картинки» иначе видна только тому, кто сам
 * делал развёртку. Наведение показывает её обеим сторонам сразу: и в 3D, и на
 * кадре слева.
 */
async function spotlightPart(part) {
  const frame = [...document.querySelectorAll('.frame')]
    .find((f) => f.dataset.mat === partsMaterial)
    || document.querySelector('.frame.is-current');
  document.querySelectorAll('.frame__uv').forEach((b) => b.remove());
  document.querySelectorAll('#partsbar .tag').forEach((b) => {
    b.classList.toggle('is-hover', Number(b.dataset.part) === part);
  });
  const mine = ++spotSeq;
  if (part === null || part === undefined || !frame) return;

  // Форму рисует Python той же маской, по которой красит склейка. Картинкой, а
  // не списком координат: у крупного куска их полторы тысячи, и возить их на
  // каждое наведение дороже, чем отдать PNG в несколько килобайт.
  const key = partsShape + ':' + part;
  let url = partMasks.get(key);
  if (!url) {
    const res = await api.partMask(partsMaterial, part);
    if (res.error) return;
    url = api.fileUrl(res.mask);
    partMasks.set(key, url);
  }
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
  const row = document.getElementById('partspaint');
  row.hidden = false;
  // Образцы кладём В ГРУППУ кисти, а не в ряд: в ряду они оказались бы перед
  // вкладками и не прятались бы вместе с остальными настройками кисти.
  const brush = row.querySelector('[data-group="brush"]');
  brush.querySelectorAll('.parts__swatch').forEach((b) => b.remove());

  const custom = document.getElementById('part-color');
  PART_COLORS.forEach((color) => {
    const b = document.createElement('button');
    b.className = 'parts__swatch';
    b.type = 'button';
    b.style.background = color;
    b.dataset.color = color;
    b.title = 'Красить этим цветом';
    b.addEventListener('click', () => armColor(color));
    brush.insertBefore(b, custom);
  });

  const tint = document.getElementById('part-tint');
  tint.value = Math.round((res.tint || 1) * 100);

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
  markArmed();
}

/** Запоминает цвет щелчка. Повторный щелчок по тому же — выключает. */
function armColor(color) {
  if (cutMode) setCutMode(false);   // выбрал цвет — значит, хочет красить
  armedColor = (armedColor === color) ? '' : color;
  markArmed();
  hintParts(armedColor
    ? 'Щёлкай по частям модели — покрасятся в этот цвет'
    : 'Перетащи картинку на часть модели или выбери цвет');
}

function markArmed() {
  document.querySelectorAll('#partspaint .parts__swatch').forEach((b) => {
    b.classList.toggle('is-active', b.dataset.color === armedColor);
  });
  const custom = document.getElementById('part-color');
  custom.classList.toggle('is-active', armedColor === custom.value);
}

/** Выходит из режима частей: покраска остаётся, уходит только полоса. */
export function closeParts() {
  const bar = document.getElementById('partsbar');
  bar.querySelectorAll('.tag').forEach((b) => b.remove());
  bar.hidden = true;
  document.getElementById('partspaint').hidden = true;
  showToolGroup('brush');   // следующий раз полоса откроется с кисти
  armedColor = '';
  gradientOn = false;
  setGradientAngle(0);
  document.getElementById('parts-grad').classList.remove('is-active');
  document.getElementById('parts-edge').classList.remove('is-active');
  document.getElementById('part-edge-color').hidden = true;
  document.getElementById('part-edge-box').hidden = true;
  document.getElementById('part-color2').hidden = true;
  document.getElementById('parts-grad-dir').hidden = true;
  hintParts('');
  setCutMode(false);
  partsFoot(false);
  spotlightPart(null);
  partsMaterial = null;
  partsList = [];
  partsGroups = {};
  partsShape = '';
  marked.clear();
  const w = viewer();
  if (w) w.setPartsMode(false);
}

/**
 * Подвал в режиме частей.
 *
 * Классом, а не атрибутом `hidden`: `hidden` у ряда действий уже занят
 * переключением раздела (у эффекта своего ряда нет), и два хозяина одного
 * признака рано или поздно разъезжаются.
 */
function partsFoot(on) {
  document.getElementById('partsbar').closest('.half__foot')
    .classList.toggle('parts-on', on);
}

/** Полоса частей: крупные первыми, покрашенные помечены. */
export function showParts(res) {
  const bar = document.getElementById('partsbar');
  bar.querySelectorAll('.tag').forEach((b) => b.remove());
  bar.hidden = false;
  partsFoot(true);

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
  const w = viewer();
  if (w && res.tri_part) {
    w.setModelParts({ [res.material]: res.tri_part });
    if (w.setModelIslands) w.setModelIslands({ [res.material]: res.tri_island });
  }

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
      viewer()?.highlightPart(part.id);
      spotlightPart(part.id);
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
      // С выбранным цветом щелчок красит; без него — спрашивает картинку.
      if (armedColor) colorParts({ [part.id]: paintSpec(armedColor) });
      else paintPart(part.id);
    });
    if (part.color) {
      const dot = document.createElement('span');
      dot.className = 'parts__dot';
      dot.style.background = part.color;
      b.appendChild(dot);
    }
    // Кнопка только на ОТРЕЗАННОЙ части — прирастить её обратно. Кнопки
    // «разрезать» здесь нет и быть не может: резать надо названный остров, а
    // из списка не видно, какой именно. Для этого есть режим «Резать».
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
    if (part.image || part.color) {
      const x = document.createElement('button');
      x.className = 'parts__x';
      x.type = 'button';
      x.textContent = '\u00d7';
      x.title = 'Вернуть этой части игровую текстуру';
      x.addEventListener('click', () => (part.color
        ? colorParts({ [part.id]: null })
        : paintPart(part.id, null)));
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
  btn.title = title + '. То же — щелчок по ней на модели в режиме «Резать»';
  btn.addEventListener('click', (e) => {
    e.stopPropagation();          // щелчок по чипу красит — здесь этого не надо
    uncutPart(part);
  });
  return btn;
}

/**
 * Чем красить: сплошной цвет или градиент.
 *
 * Градиент строится по месту ЧАСТИ на развёртке, поэтому странице достаточно
 * назвать два цвета и направление — остальное считает Python.
 */
export function paintSpec(color) {
  if (!gradientOn) return color;
  return {
    color,
    color2: document.getElementById('part-color2').value,
    angle: gradientAngle,
  };
}

/** Красит части: {часть: цвет}, значение null снимает цвет. */
export async function colorParts(colors) {
  const strength = Number(document.getElementById('part-tint').value) / 100;
  const res = await api.setPartColors(partsMaterial, colors, strength);
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
  armedColor = e.target.value;
  markArmed();
  hintParts('Щёлкай по частям модели — покрасятся в этот цвет');
});

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
  if (partsMaterial !== null) colorParts({});
});

// «Случайно» — не забава: одним нажатием видно, из каких кусков состоит
// модель и что покраска вообще делает.
document.getElementById('parts-random').addEventListener('click', async () => {
  const fresh = await api.parts(partsMaterial, partsShape);
  if (fresh.error) { hintParts(fresh.error); return; }
  // Не «каждой части случайный цвет»: так соседние куски выпадают одинаковыми
  // и модель выглядит просто перекрашенной. Раздаём цвета по кругу от
  // случайного места — соседи всегда разные.
  const start = Math.floor(Math.random() * PART_COLORS.length);
  const colors = {};
  fresh.parts.forEach((part, index) => {
    colors[part.id] = paintSpec(PART_COLORS[(start + index) % PART_COLORS.length]);
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
 */
function setCutMode(on) {
  cutMode = !!on;
  marked.clear();
  syncMarks();
  document.getElementById('parts-cut').classList.toggle('is-active', cutMode);
  if (cutMode) hintParts('');
  withViewer((w) => w.setCutMode && w.setCutMode(cutMode));
  if (cutMode) {
    armedColor = '';
    markArmed();
    hintParts('Наведи на модель — обведётся кусок развёртки, который отрежется. '
            + 'Щелчок режет; щелчки по отрезанным в списке отмечают их, '
            + 'чтобы свести в одну часть');
  } else {
    hintParts('');
  }
}

/**
 * Какая группа настроек видна: кисть, нарезка или окантовка.
 *
 * Видна одна: человек в момент времени делает что-то одно, а показ всего разом
 * давал четыре строки под моделью — с «Толщиной», оторванной переносом от
 * своей же «Окантовки» и уехавшей к «Убрать всё».
 *
 * Уход с «Нарезки» гасит режим резки: оставить его включённым, спрятав кнопку,
 * значило бы, что щелчок по модели молча делает не то, что показано.
 */
function showToolGroup(name) {
  document.querySelectorAll('.parts__tabs .underlined').forEach((b) => {
    b.classList.toggle('is-active', b.dataset.tool === name);
  });
  document.querySelectorAll('.parts__group').forEach((g) => {
    g.hidden = g.dataset.group !== name;
  });
  if (name !== 'cut' && cutMode) setCutMode(false);
}

document.querySelector('.parts__tabs').addEventListener('click', (e) => {
  const btn = e.target.closest('[data-tool]');
  if (btn) showToolGroup(btn.dataset.tool);
});

document.getElementById('parts-cut').addEventListener(
  'click', () => setCutMode(!cutMode));

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
  hintParts(on ? 'Обвожу края…' : 'Убираю окантовку…');
  const res = await api.setPartEdge(partsMaterial, width, color);
  if (res.error) { hintParts(res.error); return; }
  applyView(res);
  await refreshParts();
  hintParts('');
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
  document.getElementById('part-color2').hidden = !gradientOn;
  document.getElementById('parts-grad-dir').hidden = !gradientOn;
  hintParts(gradientOn ? 'Градиент: щёлкай по частям — переход из первого цвета. '
                       + 'Направление задаёт ручка'
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
  dial.addEventListener('pointerup', (e) => dial.releasePointerCapture(e.pointerId));
  // С клавиатуры — шагом 15°: ручку надо уметь довернуть и без мыши.
  dial.addEventListener('keydown', (e) => {
    const step = { ArrowLeft: -15, ArrowDown: -15, ArrowRight: 15, ArrowUp: 15 }[e.key];
    if (step === undefined) return;
    e.preventDefault();
    setGradientAngle(gradientAngle + step);
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
 */
document.addEventListener('keydown', (e) => {
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
});

document.getElementById('parts-clear').addEventListener('click', async () => {
  const res = await api.clearParts(partsMaterial);
  if (res.error) { hintParts(res.error); return; }
  applyView(res);
  await refreshParts();
  hintParts('');
});
