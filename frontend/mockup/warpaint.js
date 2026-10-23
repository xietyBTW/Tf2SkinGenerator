/*
 * War Paint: панель выбора раскраски с живым предпросмотром на модели
 *
 * Панель ложится на место альбома, модель справа остаётся видна. Любой выбор
 * (раскраска, износ, сид, раскладка по деталям) сразу собирается в 512 px и
 * временно кладётся на модель, «Отмена» возвращает показ, «Нанести» собирает
 * в полном размере - это уже обычная своя текстура. Собирает Python
 * (paintkit_compositor), страница только выбирает и показывает
 *
 * У оружия без War Paint в игре список - все War Paint с шаблоном, а узоры
 * раскладываются по деталям модели (paintkit_generic). «Перемешать детали»
 * раздаёт узоры по-другому, «Настроить по деталям» открывает второй экран -
 * раскладку вручную (warpaint-layout.js), она работает и у своих War Paint
 *
 * У оружия из нескольких материалов узор собирается под каждый отмеченный:
 * у каждого своя развёртка. War Paint игры по умолчанию ложится туда же, куда
 * в игре (материалы с WeaponSkin), остальные можно отметить - узор на них
 * разложится по их деталям, как в универсальном режиме
 *
 * Ниже War Paint - украшенное оружие коллекций (Current Event, Night Owl…):
 * в игре каждый такой скин есть только у своих пушек, здесь он ложится по
 * деталям любой модели. Искать можно и по английскому названию - им скины
 * знают в сообществе.
 */

import * as api from './api.js';
import { say, sayInfo, sayError } from './stage.js';
import { modeControls } from './controls.js';
import { t } from './i18n.js';
import { applyView, cardTitle, lastView, refreshView } from './preview.js';
import { openPartsCut, closeParts } from './parts.js';
import { openLayout, closeLayout, flushLayout, shuffleLayout } from './warpaint-layout.js';

const button = document.getElementById('warpaint');
const panel = document.getElementById('warpaintpanel');
const q = (sel) => panel.querySelector(sel);
const sub = q('.wpanel__sub');
const genericBox = q('.wpanel__generic');
const search = q('.wpanel__search');
const listEl = q('.wpanel__list');
const wearsEl = q('.wpanel__wears');
const wearName = q('.wpanel__wearname');
const seedEl = q('.wpanel__seed');
const statusEl = q('.wpanel__status');
const applyBtn = q('.wpanel__apply');
const partsField = q('.wpanel__parts');
const matsField = q('.wpanel__mats');
const matList = q('.wpanel__matlist');
const matNote = q('.wpanel__matnote');
const matCount = q('.wpanel__matcount');
const returnBtn = document.getElementById('parts-return');

//: Уровни износа War Paint по порядку игры (1…5): полное имя и сокращение
const WEARS = [['Прямо с завода', 'FN'], ['Немного поношенное', 'MW'],
               ['После полевых испытаний', 'FT'], ['Поношенное', 'WW'],
               ['Закалённое в боях', 'BS']];

//: War Paint показанного оружия; null - ещё не спрашивали
let items = null;
let generic = false;
//: Для какого оружия список: ответ на прошлую пушку сюда не годится
let itemsFor = '';
//: Выбор живёт между открытиями: перебирают обычно сид и износ
let chosen = null;
let wear = 1;
//: Номер последнего запроса предпросмотра: ответы на прежние отбрасываются
let previewSeq = 0;
let previewTimer = null;
//: Предпросмотр на модели: {карточка: png}. null - на модели настоящие текстуры
let preview = null;
//: Материалы оружия [{card, game}] и карточки, чья галочка не как по
//: умолчанию: так новая карточка (материал части) встаёт отмеченной сама
let mats = [];
let flipped = new Set();

/**
 * Предпросмотр для раздачи текстур: {карточка: png} или null
 *
 * Кладётся не отдельным вызовом во вьювер, а в ту же раздачу, что и настоящие
 * текстуры (applyView): сцена пересобирается при смене вида (модель, руки), и
 * отдельно положенная картинка пропадала бы - или проигрывала гонку загрузки
 * настоящей текстуре. Панель при этом продолжала бы обещать предпросмотр.
 */
export function warpaintPreview() {
  return preview;
}

/**
 * Узнаёт, какие War Paint есть у показанного оружия, и показывает кнопку.
 * Зовётся на каждую новую модель.
 */
export async function refreshWarpaint(weaponKey) {
  items = null;
  itemsFor = weaponKey || '';
  mats = [];
  flipped = new Set();
  button.hidden = true;
  // Модель перезагрузили: вьювер снова свой, карты деталей раскладки в нём нет
  closeLayout();
  if (!modeControls.warpaint || !weaponKey) return;
  let res;
  try {
    res = await api.paintkits();
  } catch {
    res = {};
  }
  if (itemsFor !== (weaponKey || '')) return;     // пока ждали, выбрали другое
  items = res.items || [];
  generic = Boolean(res.generic);
  // id раскраски общий у всех пушек, а item - свой у каждой: берём запись
  // НОВОГО списка, иначе ушёл бы рецепт прошлой пушки
  chosen = chosen ? (items.find((k) => k.id === chosen.id) || null) : null;
  applyBtn.disabled = !chosen;
  syncParts();
  // Пока ждали ответа, режим мог смениться (мод из VPK, другая категория)
  button.hidden = !(modeControls.warpaint && items.length);
  // Модель перезагрузили при открытой панели (переключатель частей): ряд
  // материалов строится заново, иначе галочки на экране ни на что не влияли
  if (!panel.hidden && items.length) await loadMaterials();
}

/**
 * Модель та же, но стало известно, чья она: мод из VPK опознаётся после
 * показа, и первый ответ каталога мог прийти ещё без оружия.
 */
export function recheckWarpaint() {
  if (itemsFor && panel.hidden) refreshWarpaint(itemsFor);
}

/** Новый предмет: панель закрывается, предпросмотр прошлой пушки не нужен */
export function hideWarpaint() {
  returnBtn.hidden = true;
  closeLayout(true);
  close(false);
  items = null;
  itemsFor = '';
  button.hidden = true;
}

// Панель

function status(text) { statusEl.textContent = text ? t(text) : ''; }

async function open() {
  if (!items) await refreshWarpaint(itemsFor);
  if (!items || !items.length) { sayInfo('У этого оружия нет War Paint'); return; }
  panel.hidden = false;
  panel.parentElement.classList.add('is-warpaint');
  button.classList.add('is-active');
  sub.textContent = generic
    ? t('Универсальный режим')
    : t('Раскрасок для этого оружия: {}').replace('{}', items.filter((k) => !k.decorated).length);
  genericBox.hidden = !generic;
  search.value = '';
  renderList();
  renderWears();
  await loadMaterials();
  status(chosen ? '' : 'Выберите раскраску - она сразу покажется на модели.');
  search.focus();
  listEl.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'center' });
  if (chosen) schedulePreview(0);
}

/** Закрывает панель; restore - вернуть на модель настоящую текстуру */
function close(restore = true) {
  clearTimeout(previewTimer);
  previewSeq++;
  if (panel.hidden) return;
  closeLayout();
  panel.hidden = true;
  panel.parentElement.classList.remove('is-warpaint');
  button.classList.remove('is-active');
  const shown = Boolean(preview);
  // Без перерисовки: при «Нанести» предпросмотр стоит на модели, пока не
  // приедет полная сборка (paintkit_ready перечитает показ сам)
  preview = null;
  if (restore && shown) refreshView();
}

function rows() { return [...listEl.querySelectorAll('.wpanel__row')]; }

function renderList() {
  const needle = search.value.trim().toLowerCase();
  listEl.innerHTML = '';
  let section = false;
  for (const kit of items || []) {
    if (needle && !kit.name.toLowerCase().includes(needle)
        && !(kit.en || '').toLowerCase().includes(needle)) continue;
    // Украшенное оружие с других пушек - своим разделом после War Paint
    if (kit.decorated && !section) {
      section = true;
      const head = document.createElement('p');
      head.className = 'wpanel__section';
      head.setAttribute('role', 'presentation');
      head.textContent = t('Украшенное оружие');
      head.title = t('Скины коллекций, которые в игре есть только у своего оружия. Здесь узор ложится по деталям этой модели.');
      listEl.appendChild(head);
    }
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'wpanel__row';
    b.dataset.id = kit.id;
    b.setAttribute('role', 'option');
    b.setAttribute('aria-selected', String(Boolean(chosen && chosen.id === kit.id)));
    const name = document.createElement('span');
    name.className = 'wpanel__name';
    name.textContent = kit.name;
    // Английское название - рядом: по нему скин и ищут
    const en = document.createElement('span');
    en.className = 'wpanel__en';
    en.textContent = kit.en && kit.en !== kit.name ? kit.en : '';
    b.append(name, en);
    if (kit.decorated) b.title = t('В игре только у: {}').replace('{}', kit.weapons.join(', '));
    if (kit.team) {
      const tag = document.createElement('span');
      tag.className = 'wpanel__tag';
      tag.textContent = 'RED / BLU';
      tag.title = t('Узор у команд разный - собирается под текущую команду');
      b.appendChild(tag);
    }
    b.addEventListener('click', () => select(kit));
    b.addEventListener('dblclick', () => { select(kit); apply(); });
    listEl.appendChild(b);
  }
  if (!listEl.children.length) {
    const empty = document.createElement('p');
    empty.className = 'wpanel__empty';
    empty.textContent = t('Ничего не нашлось');
    listEl.appendChild(empty);
  }
  syncMaterials();
  syncParts();
}

// Материалы

/** Весь War Paint ложится по деталям: универсальный режим или скин с другой пушки */
const byParts = () => generic || Boolean(chosen?.decorated);
/** Отмечен по умолчанию: War Paint игры - где его кладёт игра, иначе все */
const byDefault = (m) => generic || m.game;
/**
 * Ляжет ли War Paint на материал. Рецепт игры красит её материалы и без своей
 * геометрии, по деталям - только материал с ней, и не рецептом под одну пушку.
 */
const canPaint = (m) => (m.game && !byParts())
  || (m.parts && (byParts() || !chosen || chosen.by_parts));
const isOn = (m) => canPaint(m) && byDefault(m) !== flipped.has(m.card);

/**
 * Материалы оружия для ряда галочек. Спрашиваются при каждом открытии и после
 * перезагрузки модели: у многоматериальной модели они приходят позже самой
 * модели, а части могли добавить свои.
 */
async function loadMaterials() {
  const asked = itemsFor;
  let res;
  try {
    res = await api.paintkitMaterials((chosen || items[0]).item);
  } catch {
    res = {};
  }
  if (asked !== itemsFor || !items) return;       // пока ждали, сменили оружие
  mats = res.materials || [];
  renderMaterials();
}

/** Что красить: отмеченные карточки; null - список не пришёл, решит Python */
function picked() {
  return mats.length ? mats.filter(isOn).map((m) => m.card) : null;
}

/** Плитки материалов: миниатюра, имя и пометка «в игре» у War Paint игры */
function renderMaterials() {
  // Одна карточка - выбирать нечего
  matsField.hidden = mats.length < 2;
  matList.replaceChildren(...mats.map((m) => {
    const tile = document.createElement('button');
    tile.type = 'button';
    tile.className = 'wmat';
    tile.dataset.card = m.card;
    tile.setAttribute('role', 'checkbox');
    tile.disabled = !canPaint(m);
    const swatch = document.createElement('span');
    swatch.className = 'wmat__swatch';
    const name = document.createElement('span');
    name.className = 'wmat__name';
    // Длинное имя переносится по подчёркиваниям (c_bazaar_sniper_ | lens), а
    // не посреди слова
    name.textContent = cardTitle(m.card).replace(/_/g, '_\u200b');
    tile.append(swatch, name);
    // Пометки - только когда War Paint игры: у скина с другой пушки и в
    // универсальном режиме по деталям ложится всё
    if (!byParts() && canPaint(m)) {
      const tag = document.createElement('span');
      tag.className = 'wmat__tag';
      tag.textContent = t(m.game ? 'в игре' : 'по деталям');
      tile.append(tag);
    }
    const why = !canPaint(m)
      ? (m.parts ? t('Этот War Paint нарисован под развёртку оружия: по другим материалам его не разложить')
        : t('У этого материала нет своей геометрии: узор по деталям на него не положить'))
      : byParts() ? ''
        : t(m.game ? 'Игра кладёт War Paint на этот материал сама'
          : 'Игра этот материал не красит: узор ляжет по его деталям');
    // Имя материала целиком - в подсказке: на плитке оно может не влезть
    tile.title = why ? m.card + '\n' + why : m.card;
    tile.addEventListener('click', () => {
      if (flipped.has(m.card)) flipped.delete(m.card); else flipped.add(m.card);
      syncMaterials();
      schedulePreview(0);
    });
    return tile;
  }));
  syncMaterials();
}

/**
 * Состояние плиток, счётчик, подпись и «Нанести» (без отмеченных наносить
 * нечего). Миниатюра отмеченного материала - его предпросмотр War Paint,
 * пока он есть, иначе текстура карточки, как в альбоме.
 */
function syncMaterials() {
  for (const tile of matList.children) {
    const m = mats.find((x) => x.card === tile.dataset.card);
    const on = isOn(m);
    tile.setAttribute('aria-checked', String(on));
    const shown = (on && preview?.[m.card]) || lastView?.textures?.[m.card];
    tile.firstChild.style.backgroundImage = shown ? `url("${api.opaqueUrl(shown)}")` : '';
  }
  const count = picked()?.length ?? 0;
  matCount.textContent = t('Выбрано {} из {}').replace('{}', count).replace('{}', mats.length);
  matNote.hidden = byParts() || matsField.hidden || !mats.some((m) => !m.game && isOn(m));
  applyBtn.disabled = !chosen || picked()?.length === 0;
}

/** Детали можно раскладывать, если War Paint разложен по группам шаблоном */
function syncParts() {
  partsField.hidden = !(chosen && (generic || chosen.layered));
}

function select(kit) {
  chosen = kit;
  for (const r of rows()) r.setAttribute('aria-selected', String(Number(r.dataset.id) === kit.id));
  // Ляжет ли War Paint на материалы, которые игра не красит, зависит от него
  renderMaterials();
  syncParts();
  renderWears();
  schedulePreview();
}

function renderWears() {
  wearsEl.innerHTML = '';
  const n = chosen ? chosen.wears : WEARS.length;
  wear = Math.min(wear, n);
  WEARS.slice(0, n).forEach(([name, abbr], i) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'wpanel__wear' + (wear === i + 1 ? ' is-active' : '');
    b.setAttribute('role', 'radio');
    b.setAttribute('aria-checked', String(wear === i + 1));
    b.textContent = abbr;
    b.title = t(name);
    b.addEventListener('click', () => { wear = i + 1; renderWears(); schedulePreview(); });
    wearsEl.appendChild(b);
  });
  wearName.textContent = t(WEARS[wear - 1][0]);
}

/** Сид - целое без знака до 2^64: в игре он 64-битный */
function seedValue() {
  const digits = seedEl.value.replace(/\D/g, '');
  return digits ? BigInt.asUintN(64, BigInt(digits)).toString() : '0';
}

function randomSeed() {
  const parts = crypto.getRandomValues(new Uint32Array(2));
  return ((BigInt(parts[0]) << 32n) | BigInt(parts[1])).toString();
}

// Предпросмотр

function schedulePreview(delay = 250) {
  clearTimeout(previewTimer);
  previewTimer = setTimeout(runPreview, delay);
}

async function runPreview() {
  if (!chosen || panel.hidden) return;
  const seq = ++previewSeq;
  status('Собираю предпросмотр…');
  let res;
  try {
    res = await api.previewPaintkit(chosen.id, chosen.item, wear, seedValue(), picked());
  } catch (err) {
    res = { error: err.message };
  }
  if (seq !== previewSeq || panel.hidden) return;    // выбор уже другой
  if (res.error) {
    status(res.error);
    // Прошлый предпросмотр не про этот выбор (сняли все галочки, другой
    // War Paint не собрался) - на модели остаются настоящие текстуры
    if (preview) { preview = null; if (lastView) applyView(lastView); syncMaterials(); }
    return;
  }
  preview = res.images || null;
  syncMaterials();
  if (lastView) applyView(lastView);
  status('Предпросмотр на модели. «Нанести» соберёт в полном размере.');
}

async function apply() {
  if (!chosen) return;
  // Enter и двойной щелчок идут мимо выключенной «Нанести»
  if (picked()?.length === 0) { status('Отметьте хотя бы один материал'); return; }
  const seed = seedValue();
  seedEl.value = seed;
  const kit = chosen;
  // Раскладка по деталям могла ещё не уйти в Python - сборка её не увидела бы
  await flushLayout();
  // Предпросмотр остаётся на модели, пока не приедет полная сборка:
  // её покажет событие paintkit_ready
  close(false);
  say(t('War Paint «{}»: собираю…').replace('{}', kit.name));
  let res;
  try {
    res = await api.applyPaintkit(kit.id, kit.item, wear, seed, picked());
  } catch (err) {
    res = { error: err.message };
  }
  // Не собралось - на модели не должен остаться предпросмотр, будто War
  // Paint наложен
  if (res.error) { sayError(res.error); refreshView(); }
}

// События

button.addEventListener('click', () => (panel.hidden ? open() : close()));
q('.wpanel__close').addEventListener('click', () => close());
q('.wpanel__cancel').addEventListener('click', () => close());
applyBtn.addEventListener('click', apply);
q('.wpanel__dice').addEventListener('click', () => { seedEl.value = randomSeed(); schedulePreview(0); });
//: Ответы экрана раскладки: пересобрать предпросмотр, вернуться, уйти резать
const layoutCallbacks = {
  changed(kit) { if (chosen && kit.id === chosen.id) schedulePreview(0); },
  back() {
    closeLayout();
    status('');
    listEl.querySelector('[aria-selected="true"]')?.focus({ preventScroll: true });
  },
  // Резать уходят в «Части модели» с ножницами, а обратно - кнопкой в кадре
  // на тот же экран раскладки: номера деталей после разреза уже новые
  async cut() {
    close();
    if (await openPartsCut()) returnBtn.hidden = false;
  },
};

returnBtn.addEventListener('click', async () => {
  returnBtn.hidden = true;
  closeParts();
  await open();
  if (chosen && !panel.hidden) openLayout(chosen, layoutCallbacks);
});
// Части закрыли сами - возвращаться уже неоткуда
document.addEventListener('parts:changed', () => {
  if (document.getElementById('partsbar').hidden) returnBtn.hidden = true;
});

q('.wpanel__shuffle').addEventListener('click', async () => {
  if (!chosen) return;
  status('Перемешиваю детали…');
  const error = await shuffleLayout(chosen, layoutCallbacks);
  if (error) status(error);
});
q('.wpanel__tune').addEventListener('click', () => {
  if (chosen) openLayout(chosen, layoutCallbacks);
});
seedEl.addEventListener('input', () => schedulePreview(500));
search.addEventListener('input', renderList);

// Стрелки двигают выбор по списку прямо из поиска, Enter - нанести, Esc -
// закрыть с возвратом: мышь для перебора раскрасок не нужна
panel.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    // Не дальше панели: общий Esc закрыл бы заодно каталог и прочее
    e.preventDefault();
    e.stopPropagation();
    close();
    return;
  }
  // Enter и стрелки - только в поиске и списке: на «Отмене» или «Случайном»
  // Enter должен нажимать их, а не накладывать War Paint
  const inList = e.target === search || e.target.classList?.contains('wpanel__row');
  if (!inList) return;
  const visible = rows();
  const current = visible.findIndex((r) => r.getAttribute('aria-selected') === 'true');
  if (e.key === 'Enter') {
    e.preventDefault();
    // Скрытая фильтром раскраска не накладывается: берём найденное
    if (current >= 0) apply(); else visible[0]?.click();
    return;
  }
  if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
  e.preventDefault();
  if (!visible.length) return;
  const i = e.key === 'ArrowDown' ? Math.min(current + 1, visible.length - 1)
                                  : Math.max(current - 1, 0);
  visible[i].click();
  visible[i].scrollIntoView({ block: 'nearest' });
});
