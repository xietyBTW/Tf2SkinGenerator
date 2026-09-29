/*
 * War Paint: панель выбора раскраски с живым предпросмотром на модели.
 *
 * Панель ложится на место альбома, модель справа остаётся видна. Любой выбор
 * (раскраска, износ, сид, раскладка по деталям) сразу собирается в 512 px и
 * временно кладётся на модель; «Отмена» возвращает показ, «Нанести» собирает
 * в полном размере — это уже обычная своя текстура. Собирает Python
 * (paintkit_compositor), страница только выбирает и показывает.
 *
 * У оружия без War Paint в игре список — все War Paint с шаблоном, а узоры
 * раскладываются по деталям модели (paintkit_generic). «Перемешать детали»
 * раздаёт узоры по-другому, «Настроить по деталям» открывает второй экран —
 * раскладку вручную (warpaint-layout.js); она работает и у своих War Paint.
 */

import * as api from './api.js';
import { say, withViewer } from './stage.js';
import { modeControls } from './controls.js';
import { t } from './i18n.js';
import { SINGLE_TEX } from './album.js';
import { refreshView } from './preview.js';
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
const returnBtn = document.getElementById('parts-return');

//: Уровни износа War Paint по порядку игры (1…5): полное имя и сокращение.
const WEARS = [['Прямо с завода', 'FN'], ['Немного поношенное', 'MW'],
               ['После полевых испытаний', 'FT'], ['Поношенное', 'WW'],
               ['Закалённое в боях', 'BS']];

//: War Paint показанного оружия; null — ещё не спрашивали.
let items = null;
let generic = false;
//: Для какого оружия список: ответ на прошлую пушку сюда не годится.
let itemsFor = '';
//: Выбор живёт между открытиями: перебирают обычно сид и износ.
let chosen = null;
let wear = 1;
//: Номер последнего запроса предпросмотра: ответы на прежние отбрасываются.
let previewSeq = 0;
let previewTimer = null;
//: На модели сейчас предпросмотр, а не настоящая текстура.
let previewShown = false;

/**
 * Узнаёт, какие War Paint есть у показанного оружия, и показывает кнопку.
 * Зовётся на каждую новую модель.
 */
export async function refreshWarpaint(weaponKey) {
  items = null;
  itemsFor = weaponKey || '';
  button.hidden = true;
  // Модель перезагрузили: вьювер снова свой, карты деталей раскладки в нём нет.
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
  // id раскраски общий у всех пушек, а item — свой у каждой: берём запись
  // НОВОГО списка, иначе ушёл бы рецепт прошлой пушки.
  chosen = chosen ? (items.find((k) => k.id === chosen.id) || null) : null;
  applyBtn.disabled = !chosen;
  syncParts();
  // Пока ждали ответа, режим мог смениться (мод из VPK, другая категория).
  button.hidden = !(modeControls.warpaint && items.length);
}

/** Новый предмет: панель закрывается, предпросмотр прошлой пушки не нужен. */
export function hideWarpaint() {
  returnBtn.hidden = true;
  closeLayout(true);
  close(false);
  items = null;
  itemsFor = '';
  button.hidden = true;
}

// ── Панель ───────────────────────────────────────────────────────────────

function status(text) { statusEl.textContent = text ? t(text) : ''; }

async function open() {
  if (!items) await refreshWarpaint(itemsFor);
  if (!items || !items.length) { say('У этого оружия нет War Paint'); return; }
  panel.hidden = false;
  panel.parentElement.classList.add('is-warpaint');
  button.classList.add('is-active');
  sub.textContent = generic
    ? t('Универсальный режим')
    : t('Раскрасок для этого оружия: {}').replace('{}', items.length);
  genericBox.hidden = !generic;
  search.value = '';
  renderList();
  renderWears();
  status(chosen ? '' : 'Выберите раскраску — она сразу покажется на модели.');
  search.focus();
  listEl.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'center' });
  if (chosen) schedulePreview(0);
}

/** Закрывает панель; restore — вернуть на модель настоящую текстуру. */
function close(restore = true) {
  clearTimeout(previewTimer);
  previewSeq++;
  if (panel.hidden) return;
  closeLayout();
  panel.hidden = true;
  panel.parentElement.classList.remove('is-warpaint');
  button.classList.remove('is-active');
  if (restore && previewShown) refreshView();
  previewShown = false;
}

function rows() { return [...listEl.querySelectorAll('.wpanel__row')]; }

function renderList() {
  const needle = search.value.trim().toLowerCase();
  listEl.innerHTML = '';
  for (const kit of items || []) {
    if (needle && !kit.name.toLowerCase().includes(needle)) continue;
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'wpanel__row';
    b.dataset.id = kit.id;
    b.setAttribute('role', 'option');
    b.setAttribute('aria-selected', String(Boolean(chosen && chosen.id === kit.id)));
    b.textContent = kit.name;
    if (kit.team) {
      const tag = document.createElement('span');
      tag.className = 'wpanel__tag';
      tag.textContent = 'RED / BLU';
      tag.title = t('Узор у команд разный — собирается под текущую команду');
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
  applyBtn.disabled = !chosen;
  syncParts();
}

/** Детали можно раскладывать, если War Paint разложен по группам шаблоном. */
function syncParts() {
  partsField.hidden = !(chosen && (generic || chosen.layered));
}

function select(kit) {
  chosen = kit;
  for (const r of rows()) r.setAttribute('aria-selected', String(Number(r.dataset.id) === kit.id));
  applyBtn.disabled = false;
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

/** Сид — целое без знака до 2^64: в игре он 64-битный. */
function seedValue() {
  const digits = seedEl.value.replace(/\D/g, '');
  return digits ? BigInt.asUintN(64, BigInt(digits)).toString() : '0';
}

function randomSeed() {
  const parts = crypto.getRandomValues(new Uint32Array(2));
  return ((BigInt(parts[0]) << 32n) | BigInt(parts[1])).toString();
}

// ── Предпросмотр ─────────────────────────────────────────────────────────

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
    res = await api.previewPaintkit(chosen.id, chosen.item, wear, seedValue());
  } catch (err) {
    res = { error: err.message };
  }
  if (seq !== previewSeq || panel.hidden) return;    // выбор уже другой
  if (res.error) { status(res.error); return; }
  const url = api.fileUrl(res.png);
  const mats = res.materials || [];
  withViewer((w) => {
    if (!mats.length || (mats.length === 1 && mats[0] === SINGLE_TEX)) {
      w.updateTextureFromDataUrl(url);
    } else {
      w.applyMaterialMap(Object.fromEntries(mats.map((m) => [m, url])));
    }
  });
  previewShown = true;
  status('Предпросмотр на модели. «Нанести» соберёт в полном размере.');
}

async function apply() {
  if (!chosen) return;
  const seed = seedValue();
  seedEl.value = seed;
  const kit = chosen;
  // Раскладка по деталям могла ещё не уйти в Python — сборка её не увидела бы.
  await flushLayout();
  // Предпросмотр остаётся на модели, пока не приедет полная сборка:
  // её покажет событие paintkit_ready.
  close(false);
  say(t('War Paint «{}»: собираю…').replace('{}', kit.name));
  let res;
  try {
    res = await api.applyPaintkit(kit.id, kit.item, wear, seed);
  } catch (err) {
    res = { error: err.message };
  }
  // Не собралось — на модели не должен остаться предпросмотр, будто War
  // Paint наложен.
  if (res.error) { say(res.error); refreshView(); }
}

// ── События ──────────────────────────────────────────────────────────────

button.addEventListener('click', () => (panel.hidden ? open() : close()));
q('.wpanel__close').addEventListener('click', () => close());
q('.wpanel__cancel').addEventListener('click', () => close());
applyBtn.addEventListener('click', apply);
q('.wpanel__dice').addEventListener('click', () => { seedEl.value = randomSeed(); schedulePreview(0); });
//: Ответы экрана раскладки: пересобрать предпросмотр, вернуться, уйти резать.
const layoutCallbacks = {
  changed(kit) { if (chosen && kit.id === chosen.id) schedulePreview(0); },
  back() {
    closeLayout();
    status('');
    listEl.querySelector('[aria-selected="true"]')?.focus({ preventScroll: true });
  },
  // Резать уходят в «Части модели» с ножницами, а обратно — кнопкой в кадре
  // на тот же экран раскладки: номера деталей после разреза уже новые.
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
// Части закрыли сами — возвращаться уже неоткуда.
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

// Стрелки двигают выбор по списку прямо из поиска, Enter — нанести, Esc —
// закрыть с возвратом: мышь для перебора раскрасок не нужна.
panel.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    // Не дальше панели: общий Esc закрыл бы заодно каталог и прочее.
    e.preventDefault();
    e.stopPropagation();
    close();
    return;
  }
  // Enter и стрелки — только в поиске и списке: на «Отмене» или «Случайном»
  // Enter должен нажимать их, а не накладывать War Paint.
  const inList = e.target === search || e.target.classList?.contains('wpanel__row');
  if (!inList) return;
  const visible = rows();
  const current = visible.findIndex((r) => r.getAttribute('aria-selected') === 'true');
  if (e.key === 'Enter') {
    e.preventDefault();
    // Скрытая фильтром раскраска не накладывается: берём найденное.
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
