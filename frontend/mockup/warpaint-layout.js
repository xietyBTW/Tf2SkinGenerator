/*
 * War Paint: раскладка узоров по деталям — второй экран панели War Paint.
 *
 * Сверху плитки узоров шаблона (картинки из игры), снизу детали модели от
 * крупной к мелкой. Узор кладут тремя способами, какой удобнее: выбрать
 * плитку-кисть и щёлкать детали на модели; перетащить строки (одну или
 * выделенные) на плитку; перетащить плитку на строку. Каждое изменение сразу
 * уходит в Python и пересобирает живой предпросмотр.
 *
 * Детали — части модели (у оружия без своих War Paint) или группы маски Valve
 * (у своих); это решает Python (paintkit_layout), страница показывает то, что
 * пришло. Слой 0 — основа: первый узор шаблона или голая текстура оружия.
 */

import * as api from './api.js';
import { t } from './i18n.js';
import { viewer } from './stage.js';
import { closeParts } from './parts.js';

const panel = document.getElementById('warpaintpanel');
const q = (sel) => panel.querySelector(sel);
const mainPane = q('.wpanel__pane--main');
const pane = q('.wpanel__pane--layout');
const kitEl = q('.wlay__kit');
const hintEl = q('.wlay__hint');
const layersEl = q('.wlay__layers');
const unitsEl = q('.wlay__units');
const statusEl = q('.wlay__status');
const undoBtn = q('.wlay__undo');
const resetBtn = q('.wlay__reset');
const cutBtn = q('.wlay__cut');

//: Мельче этой доли развёртки деталь почти не видна — «Мелкие — в основу».
const SMALL = 0.02;
const DRAG_UNITS = 'text/x-wlay-units';
const DRAG_LAYER = 'text/x-wlay-layer';

//: Ответ paintkit_layout: {mode, over_albedo, layers, units, tri_unit, material}.
let data = null;
let kit = null;
let brush = 0;
const selected = new Set();
let anchor = -1;
//: Снимки слоёв деталей до каждого изменения — Ctrl+Z внутри раскладки.
let history = [];
let hooks = null;
let saveTimer = null;
let saving = Promise.resolve();
let loadSeq = 0;
let hotRow = null;
//: Слой, чьи детали сейчас подсвечены на модели (наведение на плитку).
let layerView = null;
let callbacks = { changed() {}, back() {}, cut() {} };

export const layoutOpen = () => !pane.hidden;

// ── Данные ───────────────────────────────────────────────────────────────

async function load(k) {
  const seq = ++loadSeq;
  let res;
  try {
    res = await api.paintkitLayout(k.id, k.item);
  } catch (err) {
    res = { error: err.message };
  }
  if (seq !== loadSeq) return null;
  return res;
}

const layerOf = (n) => data.layers.find((l) => l.n === n) || data.layers[0];

function layerName(n) {
  const i = data.layers.findIndex((l) => l.n === n);
  if (i <= 0) return data.over_albedo ? t('Без узора') : t('Основа');
  return t('Узор {}').replace('{}', i);
}

function unitName(u, i) {
  if (u.key[0] === 'g') return t('Группа {}').replace('{}', u.key.slice(1));
  if (u.key[0] === 'i') return t('Участок {}').replace('{}', i + 1);
  return t('Деталь {}').replace('{}', i + 1);
}

function setLayers(indices, n) {
  const changed = indices.filter((i) => data.units[i] && data.units[i].layer !== n);
  if (!changed.length) return [];
  remember();
  for (const i of changed) {
    const u = data.units[i];
    u.layer = n;
    u.manual = n !== u.auto;
  }
  save();
  return changed;
}

function remember() {
  history.push(data.units.map((u) => u.layer));
  if (history.length > 60) history.shift();
}

/** Раздаёт узоры случайно; крупные детали получают разные. */
function mixedLayers() {
  const pool = data.layers.map((l) => l.n).filter((n) => n || !data.over_albedo);
  const now = data.units.map((u) => u.layer).join();
  for (let attempt = 0; attempt < 6; attempt++) {
    for (let i = pool.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [pool[i], pool[j]] = [pool[j], pool[i]];
    }
    const next = data.units.map((_u, i) => pool[i % pool.length]);
    if (next.join() !== now || pool.length < 2) return next;
  }
  return data.units.map((u) => u.layer);
}

function applyAll(layers) {
  remember();
  data.units.forEach((u, i) => { u.layer = layers[i]; u.manual = u.layer !== u.auto; });
  save();
}

function save() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(flushLayout, 220);
}

/** Отдаёт раскладку в Python сразу; «Нанести» ждёт этого. */
export function flushLayout() {
  if (!saveTimer || !data || !kit) return saving;
  clearTimeout(saveTimer);
  saveTimer = null;
  const assign = Object.fromEntries(data.units.filter((u) => u.manual)
    .map((u) => [u.key, u.layer]));
  const target = kit;
  saving = api.setPaintkitLayout(target.id, Object.keys(assign).length ? assign : null)
    .then((res) => {
      if (res && res.error) throw new Error(res.error);
      callbacks.changed(target);
    })
    .catch((err) => {
      // Предпросмотр по старой раскладке выдал бы её за новую — молчать нельзя.
      statusEl.textContent = t('Не удалось сохранить раскладку: {}')
        .replace('{}', t(err.message || ''));
    });
  return saving;
}

// ── Экран ────────────────────────────────────────────────────────────────

/**
 * Открывает раскладку War Paint ``k``. ``cb`` — {changed(kit), back(), cut()}:
 * пересобрать предпросмотр, вернуться к списку, уйти резать детали.
 */
export async function openLayout(k, cb) {
  callbacks = cb;
  kit = k;
  data = null;
  kitEl.textContent = k.name;
  layersEl.innerHTML = '';
  unitsEl.innerHTML = '';
  hintEl.textContent = '';
  status('Разбираю детали…');
  mainPane.hidden = true;
  pane.hidden = false;
  undoBtn.disabled = true;
  resetBtn.disabled = true;
  const res = await load(k);
  if (!res || pane.hidden || kit !== k) return;
  if (res.error) { status(res.error); return; }
  data = res;
  history = [];
  selected.clear();
  anchor = -1;
  brush = (data.layers[1] || data.layers[0]).n;
  hintEl.innerHTML = '';
  hintEl.append(t(data.mode === 'groups'
    ? 'Детали здесь — группы, как их разметили художники Valve.'
    : 'Детали — части модели, как их видно в «Частях модели».'), ' ',
  t('Выберите узор и щёлкайте детали на модели или перетаскивайте строки на узоры.'));
  cutBtn.hidden = data.mode !== 'parts';
  buildLayers();
  buildUnits();
  refresh();
  attachViewer();
  status(brushHint());
  q('.wlay__tile[aria-checked="true"]')?.focus({ preventScroll: true });
}

/**
 * Уходит с экрана раскладки: изменения уже отданы или уйдут сейчас.
 * ``discard`` — предмет сменился: неотправленное относится к прошлой пушке и
 * в новую попасть не должно.
 */
export function closeLayout(discard = false) {
  if (pane.hidden) return;
  loadSeq++;
  if (discard) {
    clearTimeout(saveTimer);
    saveTimer = null;
  } else {
    flushLayout();
  }
  detachViewer();
  pane.hidden = true;
  mainPane.hidden = false;
  data = null;
}

/** «Перемешать детали» с главного экрана: без открытия раскладки. */
export async function shuffleLayout(k, cb) {
  callbacks = cb;
  const res = await load(k);
  if (!res || res.error) return res?.error || '';
  kit = k;
  data = res;
  applyAll(mixedLayers());
  await flushLayout();
  if (pane.hidden) data = null;
  return '';
}

function status(text) { statusEl.textContent = text ? t(text) : ''; }

function brushHint() {
  return t('Кисть — «{}». Щелчок по детали на модели кладёт этот узор.')
    .replace('{}', layerName(brush));
}

function buildLayers() {
  layersEl.innerHTML = '';
  data.layers.forEach((layer, i) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'wlay__tile';
    b.dataset.n = layer.n;
    b.draggable = true;
    b.setAttribute('role', 'radio');
    b.title = layer.base
      ? t(data.over_albedo ? 'Родная текстура оружия, без узора'
        : 'Первый узор шаблона: лежит везде, где не выбран другой')
      : t('Узор шаблона War Paint');
    const sw = document.createElement('span');
    sw.className = 'wlay__swatch' + (layer.swatch ? '' : ' wlay__swatch--bare');
    if (layer.swatch) sw.style.backgroundImage = `url("${api.fileUrl(layer.swatch)}")`;
    const key = document.createElement('span');
    key.className = 'wlay__key';
    key.textContent = i;
    sw.appendChild(key);
    const name = document.createElement('span');
    name.className = 'wlay__name';
    name.textContent = layerName(layer.n);
    const count = document.createElement('span');
    count.className = 'wlay__count';
    b.append(sw, name, count);

    b.addEventListener('click', () => {
      if (selected.size) {
        const moved = setLayers([...selected], layer.n);
        selected.clear();
        refresh(moved);
        bump(layer.n);
      }
      brush = layer.n;
      refresh();
      status(brushHint());
    });
    b.addEventListener('mouseenter', () => showLayerOnModel(layer.n));
    b.addEventListener('mouseleave', () => showLayerOnModel(null));
    b.addEventListener('dragstart', (e) => {
      e.dataTransfer.setData(DRAG_LAYER, String(layer.n));
      e.dataTransfer.effectAllowed = 'copy';
      showLayerOnModel(null);
    });
    b.addEventListener('dragover', (e) => {
      if (!e.dataTransfer.types.includes(DRAG_UNITS)) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      b.classList.add('is-drop');
    });
    b.addEventListener('dragleave', () => b.classList.remove('is-drop'));
    b.addEventListener('drop', (e) => {
      b.classList.remove('is-drop');
      const raw = e.dataTransfer.getData(DRAG_UNITS);
      if (!raw) return;
      e.preventDefault();
      const moved = setLayers(JSON.parse(raw), layer.n);
      selected.clear();
      refresh(moved);
      bump(layer.n);
    });
    layersEl.appendChild(b);
  });
}

function buildUnits() {
  unitsEl.innerHTML = '';
  const biggest = Math.max(...data.units.map((u) => u.area), 1e-6);
  data.units.forEach((u, i) => {
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'wlay__unit';
    row.dataset.i = i;
    row.draggable = true;
    row.setAttribute('role', 'option');
    const chip = document.createElement('span');
    chip.className = 'wlay__chip';
    const name = document.createElement('span');
    name.className = 'wlay__uname';
    name.append(unitName(u, i), document.createElement('small'));
    const bar = document.createElement('span');
    bar.className = 'wlay__bar';
    bar.style.setProperty('--a', `${Math.max(3, (u.area / biggest) * 100).toFixed(1)}%`);
    bar.appendChild(document.createElement('i'));
    const pct = document.createElement('span');
    pct.className = 'wlay__pct';
    pct.textContent = u.area >= 0.01 ? `${Math.round(u.area * 100)}%` : '<1%';
    row.append(chip, name, bar, pct);

    row.addEventListener('click', (e) => choose(i, e));
    row.addEventListener('dblclick', () => { refresh(setLayers([i], brush)); bump(brush); });
    row.addEventListener('mouseenter', () => viewer()?.highlightPart(i, data.material));
    row.addEventListener('mouseleave', () => viewer()?.highlightPart(null));
    row.addEventListener('dragstart', (e) => {
      if (!selected.has(i)) { selected.clear(); selected.add(i); anchor = i; refresh(); }
      const carried = [...selected];
      e.dataTransfer.setData(DRAG_UNITS, JSON.stringify(carried));
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setDragImage(ghost(carried), -12, -8);
      for (const j of carried) unitsEl.children[j]?.classList.add('is-dragging');
    });
    row.addEventListener('dragend', () => {
      for (const r of unitsEl.children) r.classList.remove('is-dragging', 'is-hot');
    });
    // Плитку узора роняют на строку — узор ложится на неё (и на выделенные
    // вместе с ней).
    row.addEventListener('dragover', (e) => {
      if (!e.dataTransfer.types.includes(DRAG_LAYER)) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
      row.classList.add('is-hot');
    });
    row.addEventListener('dragleave', () => row.classList.remove('is-hot'));
    row.addEventListener('drop', (e) => {
      row.classList.remove('is-hot');
      const raw = e.dataTransfer.getData(DRAG_LAYER);
      if (raw === '') return;
      e.preventDefault();
      const n = Number(raw);
      const target = selected.has(i) ? [...selected] : [i];
      selected.clear();
      refresh(setLayers(target, n));
      bump(n);
    });
    unitsEl.appendChild(row);
  });
}

function choose(i, e) {
  if (e.shiftKey && anchor >= 0) {
    if (!(e.ctrlKey || e.metaKey)) selected.clear();
    const [a, b] = anchor < i ? [anchor, i] : [i, anchor];
    for (let j = a; j <= b; j++) selected.add(j);
  } else if (e.ctrlKey || e.metaKey) {
    if (selected.has(i)) selected.delete(i); else selected.add(i);
    anchor = i;
  } else {
    const only = selected.size === 1 && selected.has(i);
    selected.clear();
    if (!only) selected.add(i);
    anchor = i;
  }
  refresh();
  status(selected.size
    ? t('Выбрано деталей: {}. Щёлкните узор или перетащите их на него.').replace('{}', selected.size)
    : brushHint());
}

/** Обновляет строки, счётчики плиток и кнопки; ``flash`` — только что изменённые. */
function refresh(flash = []) {
  if (!data) return;
  const total = {};
  data.units.forEach((u, i) => {
    const row = unitsEl.children[i];
    if (!row) return;
    const layer = layerOf(u.layer);
    const chip = row.querySelector('.wlay__chip');
    chip.style.backgroundImage = layer.swatch ? `url("${api.fileUrl(layer.swatch)}")` : '';
    chip.classList.toggle('wlay__swatch--bare', !layer.swatch);
    row.querySelector('.wlay__uname small').textContent = layerName(u.layer);
    row.classList.toggle('is-manual', u.manual);
    row.setAttribute('aria-selected', String(selected.has(i)));
    row.title = u.manual ? t('Узор выбран вручную') : t('Узор выбрал автомат');
    const sum = total[u.layer] || (total[u.layer] = { n: 0, area: 0 });
    sum.n += 1;
    sum.area += u.area;
  });
  for (const i of flash) {
    const row = unitsEl.children[i];
    if (!row) continue;
    for (const [el, cls] of [[row, 'is-flash'], [row.querySelector('.wlay__chip'), 'is-swap']]) {
      el.classList.remove(cls);
      void el.offsetWidth;           // перезапуск анимации у той же строки
      el.classList.add(cls);
    }
  }
  if (flash.length === 1) unitsEl.children[flash[0]]?.scrollIntoView({ block: 'nearest' });
  // Подсветка слоя на модели строилась по прежней раскладке.
  if (layerView !== null) showLayerOnModel(layerView);
  for (const tile of layersEl.children) {
    const n = Number(tile.dataset.n);
    const sum = total[n] || { n: 0, area: 0 };
    tile.setAttribute('aria-checked', String(n === brush));
    tile.classList.toggle('is-empty', !sum.n);
    tile.querySelector('.wlay__count').textContent =
      `${sum.n} · ${Math.round(sum.area * 100)}%`;
  }
  undoBtn.disabled = !history.length;
  resetBtn.disabled = !data.units.some((u) => u.manual);
}

function bump(n) {
  const tile = layersEl.querySelector(`.wlay__tile[data-n="${n}"]`);
  if (!tile) return;
  tile.classList.remove('is-bump');
  void tile.offsetWidth;
  tile.classList.add('is-bump');
}

let ghostEl = null;
function ghost(carried) {
  if (!ghostEl) {
    ghostEl = document.createElement('div');
    ghostEl.className = 'wlay__ghost';
    document.body.appendChild(ghostEl);
  }
  ghostEl.textContent = carried.length === 1
    ? unitName(data.units[carried[0]], carried[0])
    : t('Деталей: {}').replace('{}', carried.length);
  return ghostEl;
}

// ── Модель ───────────────────────────────────────────────────────────────

/** Карта треугольников для вьювера: у других материалов модели — пустая. */
function modelMap(list) {
  const map = { [data.material]: list };
  for (const f of document.querySelectorAll('.frame')) {
    const mat = f.dataset.mat;
    if (mat && !(mat in map)) map[mat] = [];
  }
  return map;
}

function attachViewer() {
  const w = viewer();
  if (!w || !data) return;
  // «Части модели» держат свои карты и свои ответы на щелчок — две раскладки
  // на одной модели спорили бы, чья деталь под курсором.
  closeParts();
  hooks = { hover: w.onPartHover, picked: w.onPartPicked, keys: w.onPartsKey, win: w,
            ours: { hover: (part) => hot(part),
                    picked: (_mat, part) => pickOnModel(part),
                    // Ctrl-клавиши из кадра модели: после щелчка по детали фокус
                    // там, и Ctrl+Z иначе откатывал бы правку текстуры.
                    keys: (e) => { if (!layoutKey(e) && !isHistoryKey(e)) hooks?.keys?.(e); } } };
  w.onPartHover = hooks.ours.hover;
  w.onPartPicked = hooks.ours.picked;
  w.onPartsKey = hooks.ours.keys;
  w.setModelParts(modelMap(data.tri_unit));
  w.setPartsMode(true);
  w.setPartsTool?.('', 'pointer');
}

function detachViewer() {
  if (!hooks) return;
  const { win: w, ours } = hooks;
  // Вьювер могли перезагрузить: у новой модели свои обработчики, их не трогаем.
  if (w.onPartHover === ours.hover) w.onPartHover = hooks.hover;
  if (w.onPartPicked === ours.picked) w.onPartPicked = hooks.picked;
  if (w.onPartsKey === ours.keys) w.onPartsKey = hooks.keys;
  hooks = null;
  layerView = null;
  try {
    w.setPartsMode(false);
    w.setModelParts(null);
  } catch {
    /* вьювер уже перезагрузили — чистить нечего */
  }
}

/** Наведение на плитку: на модели подсвечено всё, где лежит этот узор. */
function showLayerOnModel(n) {
  const w = hooks?.win;
  layerView = n;
  if (!w || !data) return;
  if (n === null) {
    w.setModelParts(modelMap(data.tri_unit));
    w.highlightPart(null);
    return;
  }
  w.setModelParts(modelMap(data.tri_unit.map((i) => (i == null ? null : data.units[i].layer))));
  w.highlightPart(n, data.material);
}

function hot(part) {
  // Пока подсвечен слой, вьювер сообщает номер СЛОЯ, а не детали.
  if (layerView !== null) return;
  hotRow?.classList.remove('is-hot');
  hotRow = (part == null || !data) ? null : unitsEl.children[part] || null;
  hotRow?.classList.add('is-hot');
}

function pickOnModel(part) {
  if (part == null || !data || !data.units[part]) return;
  const target = selected.has(part) ? [...selected] : [part];
  if (selected.has(part)) selected.clear();
  refresh(setLayers(target, brush));
  bump(brush);
}

// ── Кнопки и клавиши ─────────────────────────────────────────────────────

q('.wlay__back').addEventListener('click', () => callbacks.back());
cutBtn.addEventListener('click', () => callbacks.cut());
q('.wlay__tidy').addEventListener('click', () => {
  if (!data) return;
  const small = data.units.map((u, i) => (u.area < SMALL ? i : -1)).filter((i) => i >= 0);
  const moved = setLayers(small, 0);
  refresh(moved);
  if (moved.length) bump(0);
  status(moved.length ? '' : 'Мелкие детали уже на основе');
});
q('.wlay__mix').addEventListener('click', () => {
  if (!data) return;
  const before = data.units.map((u) => u.layer);
  applyAll(mixedLayers());
  refresh(data.units.map((u, i) => (u.layer !== before[i] ? i : -1)).filter((i) => i >= 0));
});
undoBtn.addEventListener('click', undo);
resetBtn.addEventListener('click', () => {
  if (!data) return;
  const before = data.units.map((u) => u.layer);
  applyAll(data.units.map((u) => u.auto));
  refresh(data.units.map((u, i) => (u.layer !== before[i] ? i : -1)).filter((i) => i >= 0));
});

function undo() {
  if (!data || !history.length) return;
  const prev = history.pop();
  const changed = [];
  data.units.forEach((u, i) => {
    if (u.layer !== prev[i]) changed.push(i);
    u.layer = prev[i];
    u.manual = u.layer !== u.auto;
  });
  save();
  refresh(changed);
}

pane.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    // Esc возвращает к списку, а не закрывает всю панель.
    e.preventDefault();
    e.stopPropagation();
    if (selected.size) { selected.clear(); refresh(); status(brushHint()); return; }
    callbacks.back();
  }
});

/** Ctrl+Y и Ctrl+Shift+Z: своего повтора у раскладки нет, общий — не про неё. */
function isHistoryKey(e) {
  return (e.ctrlKey || e.metaKey) && (e.code === 'KeyY' || (e.code === 'KeyZ' && e.shiftKey));
}

/** Клавиши раскладки; true — нажатие её. */
function layoutKey(e) {
  if (pane.hidden || !data || document.querySelector('dialog[open]')) return false;
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '')) return false;
  const mod = e.ctrlKey || e.metaKey;
  if (mod && e.code === 'KeyZ' && !e.shiftKey) {
    e.preventDefault();
    undo();
    return true;
  }
  if (mod && e.code === 'KeyA') {
    e.preventDefault();
    data.units.forEach((_u, i) => selected.add(i));
    refresh();
    return true;
  }
  if (mod || e.altKey) return false;
  if ((e.key === 'Delete' || e.key === 'Backspace') && selected.size) {
    e.preventDefault();
    const moved = setLayers([...selected], 0);
    selected.clear();
    refresh(moved);
    bump(0);
    return true;
  }
  const digit = /^Digit(\d)$/.exec(e.code);
  const tile = digit && layersEl.children[Number(digit[1])];
  if (tile) {
    e.preventDefault();
    tile.click();
    return true;
  }
  return false;
}

// Клавиши раскладки — раньше общих: Ctrl+Z здесь отменяет раскладку, а не
// правку текстуры, которую человек сейчас не видит.
document.addEventListener('keydown', (e) => {
  if (layoutKey(e) || (!pane.hidden && data && isHistoryKey(e))) {
    e.preventDefault();
    e.stopPropagation();
  }
}, true);
