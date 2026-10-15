/*
 * Конструктор узора блеска Killstreak.
 *
 * Узор - слои (полоса, вспышка, искры, дымка, картинка), у каждого свой
 * цвет и свой отрезок времени внутри прохода. Кадры считает Python
 * (sheen_builder.py) - те же, что уйдут в мод; здесь поля и проигрыватель.
 *
 * Окно - карточки: «Превью» и «Проход» слева, «Слои» и «Свойства слоя»
 * справа, «Время прохода» внизу на всю ширину. Свойства слоя - секциями,
 * которые сворачиваются (Форма, Движение, Цвет, Время): иначе два десятка
 * полей шли одной лентой, и не было видно, где кончается одна группа.
 *
 * Превью - плоская плитка в пропорциях показанного оружия: маска ложится на
 * оружие плоско, как трафарет сбоку, и растягивается на его габариты
 * (калибровка в игре). Проход идёт 25 кадров в секунду, пауза между
 * проходами - как у игры: 5 с без убийств, на каждое убийство на 1 с меньше.
 * Цвет слоя живёт в самой маске, а цвет блеска эффекта умножается на него
 * (weapon_sheen_pass: цвет × маска по каналам).
 */

import * as api from './api.js';
import { t } from './i18n.js';
import { chooseFile } from './util.js';
import { stopsEditor } from './lightwarp.js';

const dlg = document.getElementById('sheenb');
const FPS = 25;
const IMAGE_TYPES = '.png,.jpg,.jpeg,.gif,.bmp,.webp,.tga';
//: Поля движения - своя секция свойств, остальные поля слоя - «Форма».
const MOTION = new Set(['angle', 'tilt', 'wave', 'waves', 'speed']);

//: Значки слоёв - простые линии, цвет берут от текста.
const GLYPHS = {
  stripe: '<path d="M5 18 9 4M10 18 14 4M15 18 19 4"/>',
  flash: '<circle cx="12" cy="12" r="4"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/>',
  sparkle: '<path d="M12 3v18M3 12h18M7 7l10 10M17 7 7 17" stroke-width="1"/><circle cx="12" cy="12" r="2"/>',
  clouds: '<path d="M7 17h10a4 4 0 0 0 0-8 5 5 0 0 0-9.6 1.5A3.3 3.3 0 0 0 7 17z"/>',
  image: '<rect x="3" y="5" width="18" height="14" rx="1"/><path d="m3 16 5-5 4 4 3-3 6 6"/><circle cx="16" cy="9" r="1.5"/>',
};

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function glyph(kind) {
  const span = el('span', 'sheenb__glyph');
  span.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" `
    + `stroke-linecap="round" stroke-linejoin="round">${GLYPHS[kind] || ''}</svg>`;
  return span;
}

const button = (text, className = 'textbtn textbtn--sm', title = '') => {
  const b = el('button', className, text);
  b.type = 'button';
  if (title) b.title = title;
  return b;
};

/** Карточка: заголовок (и действия справа) над содержимым. */
function card(title, ...actions) {
  const box = el('section', 'sheenb__card');
  const head = el('div', 'sheenb__cardhead');
  head.append(el('h3', 'sheenb__cardtitle', title), ...actions);
  const content = el('div', 'sheenb__cardbody');
  box.append(head, content);
  return { box, head, content };
}

const clone = (v) => JSON.parse(JSON.stringify(v));

/** CSS-фон слоя: один цвет или его градиент (для образца и шкалы времени). */
function fillCss(layer) {
  if (!layer.fill || layer.fill === 'solid' || !layer.stops) return layer.color;
  const stops = layer.stops.map(([pos, c]) => `${c} ${Math.round(pos * 100)}%`).join(', ');
  // У CSS 0° - вверх, у узора 0° - вправо (к дулу).
  const deg = layer.fill === 'space' ? (Number(layer.gangle) || 0) + 90 : 90;
  return `linear-gradient(${deg}deg, ${stops})`;
}

/**
 * Циферблат направления: стрелку тянут мышью, шаг 15° (с Alt - любой угол),
 * число рядом - для точности. 0° - вдоль оружия к дулу, 90° - вниз, как на
 * плитке превью. `onInput` зовётся на каждое движение.
 */
function angleDial(value, onInput) {
  const box = el('div', 'sheenb__dial');
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '-30 -30 60 60');
  svg.setAttribute('class', 'sheenb__dialsvg');
  svg.innerHTML = '<circle r="27" class="sheenb__dialring"/>'
    + [0, 90, 180, 270].map((a) => `<line x1="${23 * Math.cos(a * Math.PI / 180)}" `
      + `y1="${23 * Math.sin(a * Math.PI / 180)}" x2="${27 * Math.cos(a * Math.PI / 180)}" `
      + `y2="${27 * Math.sin(a * Math.PI / 180)}" class="sheenb__dialtick"/>`).join('')
    + '<g class="sheenb__dialarrow"><line x1="-14" y1="0" x2="16" y2="0"/>'
    + '<path d="M22 0 13 -6 13 6z"/></g><circle r="2.5" class="sheenb__dialhub"/>';
  const arrow = svg.querySelector('.sheenb__dialarrow');
  const num = Object.assign(el('input', 'input input--num sheenb__num'),
    { type: 'number', min: 0, max: 359, step: 1 });
  let angle = Number(value) || 0;
  const show = () => {
    arrow.setAttribute('transform', `rotate(${angle})`);
    num.value = String(Math.round(angle));
  };
  const set = (a) => {
    angle = ((Math.round(a) % 360) + 360) % 360;
    show();
    onInput(angle);
  };
  svg.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    const pick = (ev) => {
      const r = svg.getBoundingClientRect();
      const a = Math.atan2(ev.clientY - (r.top + r.height / 2), ev.clientX - (r.left + r.width / 2));
      const deg = (a * 180) / Math.PI;
      set(ev.altKey ? deg : Math.round(deg / 15) * 15);
    };
    pick(e);
    svg.setPointerCapture(e.pointerId);
    svg.addEventListener('pointermove', pick);
    const up = () => svg.removeEventListener('pointermove', pick);
    svg.addEventListener('pointerup', up, { once: true });
    svg.addEventListener('lostpointercapture', up, { once: true });
  });
  num.addEventListener('change', () => set(Number(num.value) || 0));
  box.title = t('Тяните стрелку: шаг 15°, с Alt - любой угол');
  show();
  box.append(svg, num);
  return box;
}

//: Текстовое поле в фокусе: там свои Ctrl+Z и пробел. Ползунок, галка и
//: палитра - не поле: после них отмена и пробел должны работать.
const typing = (e) => e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT'
  || (e.target.tagName === 'INPUT' && /^(text|number|search)$/.test(e.target.type));

//: Какие секции свойств открыты - между показами окна тоже.
const openSections = new Set(['shape', 'motion', 'colour']);

/**
 * Открывает конструктор. `patternId` - свой узор для правки (пусто - новый),
 * `length` - длина прохода, секунды, `color` - цвет блеска для превью.
 * Отдаёт {id, length} сохранённого узора, {deleted} или null.
 */
export async function openSheenBuilder({ patternId = '', length = 2.5, color = '#ffffff' } = {}) {
  const schema = await api.sheenBuilderSchema();
  const types = Object.fromEntries(schema.types.map((x) => [x.id, x]));
  const state = {
    id: '', name: t('Мой узор'), layers: clone(schema.presets[0].spec.layers),
    length: Number(length) || 2.5, color, streak: 5, selected: 0, solo: -1, mask: false,
    quality: 'medium',
  };
  if (patternId) {
    const res = await api.sheenPatternLoad(patternId);
    if (!res.error) {
      Object.assign(state, { id: res.id, name: res.name, layers: res.spec.layers,
        quality: res.spec.quality || 'medium' });
      state.length = Number(length) || res.length;
    }
  }

  return new Promise((resolve) => {
    const body = el('div', 'ask__body sheenb__body');
    dlg.replaceChildren(body);
    let alive = true;          // этот показ окна: после закрытия всё молчит

    // ── История правок: Ctrl+Z / Ctrl+Y ──────────────────────────────
    const history = [JSON.stringify(state.layers)];
    let at = 0;
    let commitTimer = null;
    const flush = () => {
      clearTimeout(commitTimer);
      const snap = JSON.stringify(state.layers);
      if (snap === history[at]) return;
      history.splice(at + 1);
      history.push(snap);
      if (history.length > 80) history.shift();
      at = history.length - 1;
      syncHistory();
    };
    const commit = () => {
      clearTimeout(commitTimer);
      commitTimer = setTimeout(flush, 350);
    };
    const travel = (d) => {
      // Правка, что ещё ждёт записи, сначала встаёт в историю: иначе
      // Ctrl+Z сразу после неё терял бы её без возврата.
      flush();
      const j = at + d;
      if (j < 0 || j >= history.length) return;
      at = j;
      state.layers = JSON.parse(history[at]);
      state.selected = Math.min(state.selected, state.layers.length - 1);
      state.solo = -1;
      renderAll();
      refresh();
    };

    /** Любая правка слоёв: перерисовать что нужно, пересчитать кадры. */
    const changed = ({ list = false, params = false, time = true } = {}) => {
      if (list) renderLayers();
      else if (params) renderParams();
      if (time) renderTimeline();
      commit();
      refresh();
    };

    // ── Шапка ─────────────────────────────────────────────────────────
    const head = el('div', 'sheenb__top');
    const name = el('input', 'input sheenb__name');
    name.value = state.name;
    name.maxLength = 60;
    name.placeholder = t('Имя узора');
    name.addEventListener('input', () => { state.name = name.value; });
    const undo = button('↶', 'textbtn sheenb__hist', t('Отменить (Ctrl+Z)'));
    const redo = button('↷', 'textbtn sheenb__hist', t('Вернуть (Ctrl+Y)'));
    undo.addEventListener('click', () => travel(-1));
    redo.addEventListener('click', () => travel(1));
    const syncHistory = () => { undo.disabled = at <= 0; redo.disabled = at >= history.length - 1; };
    const presetsBtn = button(t('Шаблоны'), 'tag sheenb__presets-btn');
    head.append(el('p', 'label sheenb__title', t('Конструктор блеска')), name, undo, redo, presetsBtn);

    // ── Карточка «Превью» ─────────────────────────────────────────────
    const maskBtn = button(t('Маска'), 'tag', t('Сама маска: белое - блеск ярче всего'));
    maskBtn.addEventListener('click', () => {
      state.mask = !state.mask;
      maskBtn.classList.toggle('is-active', state.mask);
    });
    const preview = card(t('Превью'), maskBtn);
    const stage = el('div', 'sheenb__stage');
    const canvas = el('canvas', 'sheenb__canvas');
    const busy = el('span', 'sheenb__busy', t('Считаю…'));
    busy.hidden = true;
    const dropHint = el('div', 'sheenb__drop', t('Отпустите - картинка станет слоем'));
    stage.append(canvas, busy, dropHint);
    const note = el('p', 'sheenb__note');

    // Картинку можно бросить прямо на превью.
    stage.addEventListener('dragover', (e) => {
      if (![...(e.dataTransfer?.types || [])].includes('Files')) return;
      e.preventDefault();
      stage.classList.add('is-over');
    });
    stage.addEventListener('dragleave', () => stage.classList.remove('is-over'));
    stage.addEventListener('drop', async (e) => {
      e.preventDefault();
      stage.classList.remove('is-over');
      const file = [...(e.dataTransfer?.files || [])].find((f) => f.type.startsWith('image/'));
      if (!file || state.layers.length >= schema.max_layers) return;
      const layer = clone(types.image.defaults);
      layer.image = await api.upload(file);
      state.layers.push(layer);
      state.selected = state.layers.length - 1;
      changed({ list: true });
    });

    // Проигрыватель: кадр назад, играть, кадр вперёд и время прохода.
    let playing = true;
    const play = button('', 'sheenb__play');
    const syncPlay = () => {
      play.textContent = playing ? '❚❚' : '▶';
      play.title = playing ? t('Пауза (пробел)') : t('Играть (пробел)');
    };
    play.addEventListener('click', () => { playing = !playing; syncPlay(); });
    syncPlay();
    const stepBack = button('◀', 'textbtn sheenb__step', t('Кадр назад'));
    const stepFwd = button('▶', 'textbtn sheenb__step', t('Кадр вперёд'));
    const step = (d) => {
      playing = false;
      syncPlay();
      if (!sheet) return;
      const pass = sheet.frames / FPS;
      clock = Math.max(1 / FPS, Math.min(pass - 1e-3, (Math.floor(clock * FPS) + d + 0.5) / FPS));
    };
    stepBack.addEventListener('click', () => step(-1));
    stepFwd.addEventListener('click', () => step(1));
    const clockOut = el('span', 'mono sheenb__clock');
    const transport = el('div', 'sheenb__transport');
    const buttons = el('div', 'sheenb__transportbtns');
    buttons.append(stepBack, play, stepFwd);
    transport.append(el('span'), buttons, clockOut);
    preview.content.append(stage, transport, note);

    // ── Карточка «Проход» ─────────────────────────────────────────────
    const pass = card(t('Проход'));
    // Качество - высота маски (64/128/256), ширина - по пропорции оружия.
    const sizeOut = el('span', 'mono sheenb__val');
    // Размер и вес маски - формулой, как sheen_builder.mask_shape и
    // sheen_patterns.frames_for: сразу при нажатии, без ожидания кадров.
    const showSize = () => {
      const h = schema.quality[state.quality] || 128;
      const aspect = sheet?.aspect || schema.default_aspect;
      const w = Math.min(1024, Math.max(16, 2 ** Math.round(Math.log2(Math.max(4, h * aspect)))));
      const fr = schema.frames;
      const frames = Math.min(fr.max, Math.max(fr.min, Math.round(state.length * fr.fps) + 1));
      const mb = (frames * w * h) / 2 / (1024 * 1024);
      sizeOut.textContent = t(`${w}×${h} · ${mb < 1 ? mb.toFixed(2) : mb.toFixed(1)} МБ`);
    };
    const qualitySeg = el('div', 'seg');
    const qualities = [['low', t('Низкое')], ['medium', t('Среднее')], ['high', t('Высокое')]];
    const qualityBtns = qualities.map(([id, label]) => {
      const b = button(label, id === state.quality ? 'is-active' : '');
      b.addEventListener('click', () => {
        state.quality = id;
        qualityBtns.forEach((x, i) => x.classList.toggle('is-active', qualities[i][0] === id));
        showSize();
        refresh();
      });
      qualitySeg.append(b);
      return b;
    });
    const pauseOut = el('span', 'mono sheenb__val', t(`пауза ${5 - state.streak} с`));
    const streakSeg = el('div', 'seg sheenb__streak');
    const streakBtns = [0, 1, 2, 3, 4, 5].map((n) => {
      const b = button(String(n), n === state.streak ? 'is-active' : '');
      b.addEventListener('click', () => {
        state.streak = n;
        streakBtns.forEach((x, i) => x.classList.toggle('is-active', i === n));
        pauseOut.textContent = t(`пауза ${5 - n} с`);
      });
      streakSeg.append(b);
      return b;
    });
    const lengthOut = el('span', 'mono sheenb__val');
    const lengthIn = Object.assign(el('input', 'slider'),
      { type: 'range', min: 1, max: 8, step: 0.5, value: state.length });
    const showLength = () => { lengthOut.textContent = t(`${state.length.toFixed(1)} с`); };
    lengthIn.addEventListener('input', () => {
      state.length = Number(lengthIn.value);
      showLength();
      showSize();
      renderRuler();
      renderParams();
      refresh();
    });
    showLength();
    const colorIn = Object.assign(el('input', 'parts__color'), { type: 'color', value: state.color });
    colorIn.addEventListener('input', () => { state.color = colorIn.value; });
    const prow = (label, title, ...nodes) => {
      const row = el('div', 'sheenb__row');
      row.title = title;
      const ctl = el('div', 'sheenb__rowctl');
      ctl.append(...nodes);
      row.append(el('span', 'sheenb__lbl', label), ctl);
      return row;
    };
    pass.content.append(
      prow(t('Качество'), t('Чётче узор - тяжелее мод. Справа - сколько маска займёт в моде.'),
        qualitySeg, sizeOut),
      prow(t('Длина прохода'), t('Сколько секунд идёт один проход.'), lengthIn, lengthOut),
      prow(t('Серия убийств'), t('Как в игре: чем больше убийств подряд, тем короче пауза между проходами.'),
        streakSeg, pauseOut),
      prow(t('Цвет блеска'), t('Цвет из эффекта: в игре он умножается на цвет слоя. Для точных цветов слоёв - белый.'),
        colorIn));

    // ── Карточка «Слои» ───────────────────────────────────────────────
    const addBtn = button(t('+ Слой'), 'tag sheenb__addbtn');
    const layersCard = card(t('Слои'), addBtn);
    const addMenu = el('div', 'sheenb__addmenu');
    addMenu.hidden = true;
    for (const ty of schema.types) {
      const b = button('', 'sheenb__addtype');
      b.append(glyph(ty.id), el('span', '', ty.label));
      b.addEventListener('click', () => {
        addMenu.hidden = true;
        addBtn.classList.remove('is-active');
        if (state.layers.length >= schema.max_layers) return;
        state.layers.push(clone(ty.defaults));
        state.selected = state.layers.length - 1;
        changed({ list: true });
      });
      addMenu.append(b);
    }
    addBtn.addEventListener('click', () => {
      addMenu.hidden = !addMenu.hidden;
      addBtn.classList.toggle('is-active', !addMenu.hidden);
    });

    // Шаблоны - карточки с кадром узора, на месте списка слоёв.
    const presets = el('div', 'sheenb__presets');
    presets.hidden = true;
    presets.append(el('p', 'sheenb__note', t('Начать с шаблона: заменит слои, отменить - Ctrl+Z.')));
    const cards = el('div', 'sheenb__cards');
    presets.append(cards);
    for (const p of schema.presets) {
      const tile = button('', 'sheenb__tile');
      const pic = el('img', 'sheenb__tileimg');
      pic.alt = '';
      tile.append(pic, el('span', 'sheenb__tilename', p.label));
      tile.dataset.preset = p.id;
      tile.addEventListener('click', () => {
        state.layers = clone(p.spec.layers);
        state.selected = 0;
        state.solo = -1;
        presets.hidden = true;
        presetsBtn.classList.remove('is-active');
        changed({ list: true });
      });
      cards.append(tile);
    }
    presetsBtn.addEventListener('click', async () => {
      presets.hidden = !presets.hidden;
      presetsBtn.classList.toggle('is-active', !presets.hidden);
      if (presets.hidden || cards.dataset.loaded) return;
      cards.dataset.loaded = '1';
      try {
        const res = await api.sheenPresetThumbs();
        for (const tile of cards.children) {
          const src = res.thumbs[tile.dataset.preset];
          if (src) tile.querySelector('img').src = api.fileUrl(src);
        }
      } catch { /* без картинок - только подписи */ }
    });
    const list = el('div', 'sheenb__list');
    layersCard.content.append(presets, addMenu, list);

    // ── Карточка «Свойства слоя» ──────────────────────────────────────
    const propsCard = card(t('Свойства слоя'));
    propsCard.box.classList.add('sheenb__card--props');
    const params = propsCard.content;

    // ── Время ─────────────────────────────────────────────────────────
    const timeCard = card(t('Время прохода'));
    timeCard.head.append(el('span', 'sheenb__hint', t('Тяните полосы и их края, щелчок по шкале - перемотка')));
    const ruler = el('div', 'sheenb__ruler');
    ruler.title = t('Щёлкните или тяните, чтобы перемотать');
    const lanes = el('div', 'sheenb__lanes');
    const playhead = el('div', 'sheenb__playhead');
    timeCard.content.append(ruler, lanes);

    // ── Раскладка и низ ──────────────────────────────────────────────
    const leftCol = el('div', 'sheenb__col');
    leftCol.append(preview.box, pass.box);
    const rightCol = el('div', 'sheenb__col sheenb__col--right');
    rightCol.append(layersCard.box, propsCard.box);
    const main = el('div', 'sheenb__main');
    main.append(leftCol, rightCol);

    const acts = el('div', 'ask__acts sheenb__acts');
    const del = button(t('Удалить узор'), 'textbtn sheenb__del');
    del.hidden = !state.id;
    const copy = button(t('Сохранить копией'), 'textbtn');
    copy.hidden = !state.id;
    const cancel = button(t('Отмена'), 'textbtn');
    const save = button(t('Сохранить узор'), 'btn--primary');
    acts.append(del, copy, cancel, save);
    body.append(head, main, timeCard.box, acts);

    // ── Слои: список ──────────────────────────────────────────────────
    function layerName(layer, i) {
      const same = state.layers.slice(0, i + 1).filter((x) => x.type === layer.type).length;
      return same > 1 ? `${types[layer.type].label} ${same}` : types[layer.type].label;
    }

    /** Образец цвета слоя: палитра у одного цвета, полоска у градиента. */
    function swatchFor(layer) {
      if (!layer.fill || layer.fill === 'solid') {
        const sw = Object.assign(el('input', 'sheenb__swatch'), { type: 'color', value: layer.color });
        sw.title = t('Цвет слоя');
        sw.addEventListener('click', (e) => e.stopPropagation());
        sw.addEventListener('input', () => { layer.color = sw.value; changed({ params: true }); });
        return sw;
      }
      const chip = el('span', 'sheenb__swatch sheenb__swatch--grad');
      chip.style.background = fillCss(layer);
      chip.title = t('Градиент слоя - в настройках слоя');
      return chip;
    }

    /** Меню «⋯» строки слоя: только этот слой, копия, удалить. */
    let openMenu = null;
    function rowMenu(i) {
      const wrap = el('div', 'sheenb__more');
      const more = button('⋯', 'textbtn sheenb__morebtn', t('Ещё'));
      const menu = el('div', 'sheenb__menu');
      menu.hidden = true;
      const item = (label, fn) => {
        const b = button(label, 'sheenb__menuitem');
        b.addEventListener('click', (e) => { e.stopPropagation(); closeMenu(); fn(); });
        menu.append(b);
      };
      item(state.solo === i ? t('Показывать все слои') : t('Только этот слой в превью'), () => {
        state.solo = state.solo === i ? -1 : i;
        renderLayers();
        refresh();
      });
      item(t('Копия'), () => {
        if (state.layers.length >= schema.max_layers) return;
        state.layers.splice(i + 1, 0, clone(state.layers[i]));
        state.selected = i + 1;
        if (state.solo > i) state.solo += 1;
        changed({ list: true });
      });
      item(t('Удалить'), () => removeLayer(i));
      more.addEventListener('click', (e) => {
        e.stopPropagation();
        const was = !menu.hidden;
        closeMenu();
        if (!was) { menu.hidden = false; openMenu = menu; }
      });
      wrap.append(more, menu);
      return wrap;
    }
    const closeMenu = () => { if (openMenu) openMenu.hidden = true; openMenu = null; };
    dlg.addEventListener('click', closeMenu);

    let dragFrom = -1;
    function renderLayers() {
      openMenu = null;
      list.replaceChildren(...state.layers.map((layer, i) => {
        const row = el('div', 'sheenb__layer' + (i === state.selected ? ' is-active' : '')
                              + (layer.on ? '' : ' is-off')
                              + (state.solo >= 0 && state.solo !== i ? ' is-muted' : ''));
        row.draggable = true;
        row.title = t('Тяните, чтобы переставить');
        const eye = Object.assign(el('input'), { type: 'checkbox', checked: layer.on });
        eye.title = t('Показывать слой');
        eye.addEventListener('click', (e) => e.stopPropagation());
        eye.addEventListener('change', () => { layer.on = eye.checked; changed({ list: true }); });
        const label = el('span', 'sheenb__lname', layerName(layer, i));
        if (state.solo === i) label.append(el('span', 'sheenb__badge', t('соло')));
        row.append(swatchFor(layer), glyph(layer.type), label, eye, rowMenu(i));
        row.addEventListener('click', () => select(i));
        row.addEventListener('dragstart', (e) => { dragFrom = i; e.dataTransfer.effectAllowed = 'move'; });
        row.addEventListener('dragover', (e) => {
          if (dragFrom < 0) return;
          e.preventDefault();
          row.classList.add('is-target');
        });
        row.addEventListener('dragleave', () => row.classList.remove('is-target'));
        row.addEventListener('dragend', () => { dragFrom = -1; });
        row.addEventListener('drop', (e) => {
          e.preventDefault();
          if (dragFrom < 0 || dragFrom === i) return;
          const [moved] = state.layers.splice(dragFrom, 1);
          state.layers.splice(i, 0, moved);
          state.selected = i;
          dragFrom = -1;
          state.solo = -1;
          changed({ list: true });
        });
        return row;
      }));
      if (!state.layers.length) {
        list.append(el('p', 'sheenb__note', t('Добавьте слой кнопкой «+ Слой».')));
      }
      renderParams();
    }

    function select(i) {
      state.selected = i;
      renderLayers();
      renderTimeline();
    }

    function removeLayer(i) {
      state.layers.splice(i, 1);
      if (state.selected > i) state.selected -= 1;
      state.selected = Math.min(state.selected, state.layers.length - 1);
      if (state.solo === i) state.solo = -1;
      else if (state.solo > i) state.solo -= 1;
      changed({ list: true });
    }

    // ── Свойства: секции ──────────────────────────────────────────────
    function section(id, title, rows, summary = null) {
      const box = el('div', 'sheenb__sec' + (openSections.has(id) ? ' is-open' : ''));
      const headBtn = button('', 'sheenb__sechead');
      headBtn.append(el('span', 'sheenb__chev', '›'), el('span', 'sheenb__sectitle', title));
      if (summary) headBtn.append(summary);
      headBtn.addEventListener('click', () => {
        if (openSections.has(id)) openSections.delete(id);
        else openSections.add(id);
        box.classList.toggle('is-open', openSections.has(id));
      });
      const inner = el('div', 'sheenb__secbody');
      inner.append(...rows);
      box.append(headBtn, inner);
      return box;
    }

    function renderParams() {
      const layer = state.layers[state.selected];
      propsCard.head.querySelector('.sheenb__cardtitle').textContent = layer
        ? [t('Свойства слоя'), layerName(layer, state.selected)].join(' · ') : t('Свойства слоя');
      if (!layer) { params.replaceChildren(el('p', 'sheenb__note', t('Выберите слой в списке.'))); return; }
      const fields = types[layer.type].fields;
      const shape = fields.filter((f) => !MOTION.has(f.key));
      const motion = fields.filter((f) => MOTION.has(f.key));
      const common = (key) => schema.common.filter((f) => f.key === key).map((f) => fieldRow(layer, f));
      const swatch = el('span', 'sheenb__secswatch');
      swatch.style.background = fillCss(layer);
      const span = el('span', 'mono sheenb__secsum',
        t(`${(layer.start * state.length).toFixed(1)}-${(layer.end * state.length).toFixed(1)} с`));
      params.replaceChildren(...[
        shape.length && section('shape', layer.type === 'image' ? t('Картинка') : t('Форма'),
          shape.map((f) => fieldRow(layer, f))),
        motion.length && section('motion', t('Движение'), motion.map((f) => fieldRow(layer, f))),
        section('colour', t('Цвет и яркость'), [colourBlock(layer), ...common('power')], swatch),
        section('time', t('Время'), [timeRow(layer), ...common('fade')], span),
      ].filter(Boolean));
    }

    /**
     * Цвет слоя одним блоком: образец и переключатель «Градиент». Градиент -
     * полоса с точками и стрелка направления по оружию, либо «Во времени»
     * (слой меняет цвет по ходу прохода) - тогда стрелка не нужна.
     */
    function colourBlock(layer) {
      const box = el('div', 'sheenb__colour');
      const field = (key) => schema.common.find((f) => f.key === key);
      const gradient = layer.fill === 'space' || layer.fill === 'time';
      const top = el('div', 'sheenb__row');
      const ctl = el('div', 'sheenb__rowctl');
      if (!gradient) {
        const pick = Object.assign(el('input', 'parts__color'), { type: 'color', value: layer.color });
        pick.addEventListener('input', () => {
          layer.color = pick.value;
          const row = list.children[state.selected];
          const sw = row && row.querySelector('.sheenb__swatch');
          if (sw && sw.type === 'color') sw.value = pick.value;
          changed({ time: true });
        });
        ctl.append(pick);
      }
      const toggle = el('label', 'check sheenb__gradtoggle');
      const on = Object.assign(el('input'), { type: 'checkbox', checked: gradient });
      on.addEventListener('change', () => {
        layer.fill = on.checked ? 'space' : 'solid';
        changed({ list: true });
      });
      toggle.append(on, el('span', '', t('Градиент')));
      ctl.append(toggle);
      top.append(el('span', 'sheenb__lbl', t('Цвет')), ctl);
      box.append(top);
      if (!gradient) return box;

      const editor = stopsEditor({
        point: t('Цвет точки'), position: t('Позиция, %'), remove_point: t('Убрать точку'),
        gradient_hint: '',
      }, field('stops').max_stops || 8, () => {
        layer.stops = editor.get();
        const row = list.children[state.selected];
        const chip = row && row.querySelector('.sheenb__swatch--grad');
        if (chip) chip.style.background = fillCss(layer);
        changed({ time: true });
      });
      editor.set(layer.stops || field('stops').default);
      editor.node.title = t('Щёлкните по полосе - новая точка; точку можно тянуть, Delete убирает.');
      box.append(editor.node);

      const time = el('label', 'check');
      const timeOn = Object.assign(el('input'), { type: 'checkbox', checked: layer.fill === 'time' });
      timeOn.addEventListener('change', () => {
        layer.fill = timeOn.checked ? 'time' : 'space';
        changed({ list: true });
      });
      time.append(timeOn, el('span', '', t('Во времени')));
      time.title = t('Слой меняет цвет по ходу прохода, а не по оружию');
      const how = el('div', 'sheenb__row');
      const howCtl = el('div', 'sheenb__rowctl');
      if (layer.fill === 'space') {
        howCtl.append(angleDial(layer.gangle, (a) => {
          layer.gangle = a;
          const row = list.children[state.selected];
          const chip = row && row.querySelector('.sheenb__swatch--grad');
          if (chip) chip.style.background = fillCss(layer);
          changed({ time: true });
        }));
      }
      howCtl.append(time);
      how.append(el('span', 'sheenb__lbl', t('Направление')), howCtl);
      box.append(how);
      return box;
    }

    /** Начало и конец слоя в секундах - числами, точнее, чем мышью. */
    function timeRow(layer) {
      const num = (key) => {
        const input = Object.assign(el('input', 'input input--num sheenb__num'),
          { type: 'number', min: 0, max: state.length, step: 0.1 });
        input.value = (layer[key] * state.length).toFixed(1);
        input.addEventListener('change', () => {
          const v = Math.min(1, Math.max(0, Number(input.value) / state.length));
          if (key === 'start') {
            layer.start = Math.min(v, 0.97);
            if (layer.end - layer.start < 0.03) layer.end = layer.start + 0.03;
          } else {
            layer.end = Math.max(v, 0.03);
            if (layer.end - layer.start < 0.03) layer.start = layer.end - 0.03;
          }
          changed({ params: true });
        });
        return input;
      };
      const row = el('div', 'sheenb__row');
      const ctl = el('div', 'sheenb__rowctl');
      ctl.append(num('start'), el('span', 'sheenb__dash', '-'), num('end'), el('span', 'sheenb__unit', t('с')));
      row.append(el('span', 'sheenb__lbl', t('С и до')), ctl);
      return row;
    }

    function fieldRow(layer, f) {
      const row = el('div', 'sheenb__row');
      const ctl = el('div', 'sheenb__rowctl');
      row.append(el('span', 'sheenb__lbl', f.label), ctl);
      if (f.view === 'angle') {
        ctl.append(angleDial(layer[f.key], (a) => { layer[f.key] = a; changed({ time: false }); }));
      } else if (f.view === 'choice') {
        const box = el('div', 'seg sheenb__seg');
        const tags = f.choices.map((c) => {
          const b = button(c.label, layer[f.key] === c.value ? 'is-active' : '');
          b.addEventListener('click', () => {
            layer[f.key] = c.value;
            tags.forEach((x) => x.classList.toggle('is-active', x === b));
            changed({ time: false });
          });
          return b;
        });
        box.append(...tags);
        ctl.append(box);
      } else if (f.view === 'range') {
        const input = Object.assign(el('input', 'slider'),
          { type: 'range', min: f.min, max: f.max, step: f.step, value: layer[f.key] });
        const out = Object.assign(el('input', 'input input--num sheenb__num'),
          { type: 'number', min: f.min, max: f.max, step: f.step });
        const digits = f.step >= 1 ? 0 : (f.step >= 0.1 ? 1 : 2);
        const show = () => { out.value = Number(layer[f.key]).toFixed(digits); };
        input.addEventListener('input', () => { layer[f.key] = Number(input.value); show(); changed({ time: false }); });
        out.addEventListener('change', () => {
          const v = Math.min(f.max, Math.max(f.min, Number(out.value) || 0));
          layer[f.key] = v;
          input.value = v;
          show();
          changed({ time: false });
        });
        show();
        ctl.append(input, out);
      } else if (f.view === 'seed') {
        const again = button(t('Перемешать'), 'tag');
        again.addEventListener('click', () => {
          layer[f.key] = Math.floor(Math.random() * 10000);
          changed({ time: false });
        });
        ctl.append(again);
      } else if (f.view === 'image') {
        const thumb = el('img', 'sheenb__thumb');
        thumb.alt = '';
        thumb.hidden = !layer.image;
        if (layer.image) thumb.src = api.fileUrl(layer.image, true);
        thumb.addEventListener('error', () => { thumb.hidden = true; });
        const pick = button(layer.image ? t('Заменить') : t('Выбрать'), 'tag');
        pick.addEventListener('click', async () => {
          // Только то, что читает сборка (Pillow): SVG и HEIC она не откроет.
          const file = await chooseFile(IMAGE_TYPES);
          if (!file) return;
          layer.image = await api.upload(file);
          changed({ params: true, time: false });
        });
        ctl.append(thumb, pick);
        row.title = t('Светлое и непрозрачное проявляется блеском, чёрное и прозрачное - нет.');
      }
      return row;
    }

    // ── Время: шкала и полосы слоёв ───────────────────────────────────
    function renderRuler() {
      const track = el('div', 'sheenb__rulertrack');
      for (let s = 0; s <= state.length + 1e-6; s += 0.5) {
        const whole = Math.abs(s - Math.round(s)) < 1e-6;
        const tick = el('span', 'sheenb__tick' + (whole ? ' is-major' : ''),
          whole ? t(`${Math.round(s)} с`) : '');
        tick.style.left = `${(s / state.length) * 100}%`;
        track.append(tick);
      }
      ruler.replaceChildren(el('span', 'sheenb__tlname'), track);
    }

    function renderTimeline() {
      const rows = state.layers.map((layer, i) => {
        const row = el('div', 'sheenb__tlrow' + (i === state.selected ? ' is-active' : ''));
        const label = el('span', 'sheenb__tlname');
        label.append(glyph(layer.type), el('span', '', layerName(layer, i)));
        label.addEventListener('click', () => select(i));
        row.append(label);
        const track = el('div', 'sheenb__track');
        const bar = el('div', 'sheenb__span' + (layer.on ? '' : ' is-off'));
        bar.style.background = fillCss(layer);
        const place = () => {
          bar.style.left = `${layer.start * 100}%`;
          bar.style.width = `${(layer.end - layer.start) * 100}%`;
        };
        place();
        const lh = el('span', 'sheenb__handle sheenb__handle--l');
        const rh = el('span', 'sheenb__handle sheenb__handle--r');
        bar.append(lh, rh);
        track.append(bar);
        row.append(track);
        // Тянуть: середина - сдвиг, края - начало и конец.
        const drag = (mode) => (e) => {
          e.preventDefault();
          e.stopPropagation();
          // Выбор - без перерисовки: она отцепила бы полосу, которую тянут
          // (ширина 0, слой улетал к краю). Список обновится в конце жеста.
          state.selected = i;
          const box = track.getBoundingClientRect();
          if (!box.width) return;
          const x0 = e.clientX;
          const a0 = layer.start;
          const b0 = layer.end;
          const move = (ev) => {
            const d = (ev.clientX - x0) / box.width;
            const minLen = 0.03;
            if (mode === 'l') layer.start = Math.min(b0 - minLen, Math.max(0, a0 + d));
            else if (mode === 'r') layer.end = Math.max(a0 + minLen, Math.min(1, b0 + d));
            else {
              const len = b0 - a0;
              layer.start = Math.min(1 - len, Math.max(0, a0 + d));
              layer.end = layer.start + len;
            }
            place();
          };
          const up = () => {
            window.removeEventListener('pointermove', move);
            window.removeEventListener('pointerup', up);
            changed({ list: true });
          };
          window.addEventListener('pointermove', move);
          window.addEventListener('pointerup', up);
        };
        bar.addEventListener('pointerdown', drag('m'));
        lh.addEventListener('pointerdown', drag('l'));
        rh.addEventListener('pointerdown', drag('r'));
        return row;
      });
      lanes.replaceChildren(...rows, playhead);
    }

    // Перемотка: щелчок или протяжка по шкале ставит время и паузу.
    ruler.addEventListener('pointerdown', (e) => {
      const track = ruler.querySelector('.sheenb__rulertrack');
      if (!track || !sheet) return;
      e.preventDefault();
      playing = false;
      syncPlay();
      const seek = (ev) => {
        const box = track.getBoundingClientRect();
        const f = Math.min(1, Math.max(0, (ev.clientX - box.left) / box.width));
        const passSec = sheet.frames / FPS;
        clock = Math.max(1 / FPS, Math.min(passSec - 1e-3, 1 / FPS + f * (passSec - 2 / FPS)));
      };
      seek(e);
      const up = () => {
        window.removeEventListener('pointermove', seek);
        window.removeEventListener('pointerup', up);
      };
      window.addEventListener('pointermove', seek);
      window.addEventListener('pointerup', up);
    });

    // ── Кадры: запрос и проигрыватель ─────────────────────────────────
    // Запрос один за раз: пока Python считает, новые правки только
    // помечаются, и по готовности уходит одна - последняя.
    let sheet = null;          // {img, frames, cols, size, aspect}
    let timer = null;
    let inflight = false;
    let dirty = false;

    function refresh() {
      clearTimeout(timer);
      timer = setTimeout(request, 160);
    }

    async function request() {
      if (inflight) { dirty = true; return; }
      inflight = true;
      dirty = false;
      busy.hidden = false;
      // «Только этот слой» - в превью, в узор не уходит.
      const layers = state.solo >= 0
        ? state.layers.map((l, i) => ({ ...l, on: i === state.solo }))
        : state.layers;
      let res;
      try {
        res = await api.sheenPatternPreview({ layers, quality: state.quality }, state.length);
      } catch (err) {
        res = { error: err.message };
      }
      inflight = false;
      if (!alive) return;
      if (dirty) { request(); return; }
      busy.hidden = true;
      if (res.error) { note.textContent = res.error; return; }
      const img = new Image();
      img.onload = () => {
        if (!alive) return;
        sheet = { img, ...res };
        showSize();             // пропорция оружия известна точно только теперь
        note.textContent = res.weapon
          ? t('Плитка в пропорциях оружия: узор ляжет на его бок так же.')
          : t('Оружие не выбрано: показана обычная пропорция ствола.');
        sizeCanvas();
      };
      img.src = api.fileUrl(res.image);
    }

    // Плитка - всегда по ширине своей колонки (раньше 600 px наезжали на
    // слои в узком окне), высота - по пропорции оружия.
    function sizeCanvas() {
      if (!sheet) return;
      const room = stage.clientWidth - 2;
      if (room <= 0) return;
      let w = room;
      let h = Math.round(w / sheet.aspect);
      if (h > 260) { h = 260; w = Math.round(h * sheet.aspect); }
      if (h < 60) h = 60;
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
    }
    const resizer = new ResizeObserver(() => sizeCanvas());
    resizer.observe(stage);

    // Кадр × цвет блеска - на маленьком холсте (128×128) каждый кадр.
    const tint = document.createElement('canvas');
    let clock = 0;
    let last = performance.now();
    function draw(now) {
      if (!alive) return;
      const dt = (now - last) / 1000;
      last = now;
      if (playing) clock += dt;
      const ctx = canvas.getContext('2d');
      const w = canvas.width;
      const h = canvas.height;
      ctx.globalCompositeOperation = 'source-over';
      if (state.mask) {
        ctx.fillStyle = '#000';
      } else {
        const grad = ctx.createLinearGradient(0, 0, 0, h);
        grad.addColorStop(0, '#4a4f55');
        grad.addColorStop(1, '#2c2f33');
        ctx.fillStyle = grad;
      }
      ctx.fillRect(0, 0, w, h);
      let pos = -1;
      let shown = '';
      if (sheet) {
        const passSec = sheet.frames / FPS;
        const cycle = passSec + Math.max(0, 5 - state.streak);
        if (playing) clock %= cycle;
        const frame = clock < passSec ? Math.min(sheet.frames - 1, Math.floor(clock * FPS)) : 0;
        shown = clock < passSec ? t(`${clock.toFixed(1)} / ${passSec.toFixed(1)} с`)
          : t(`пауза ${(cycle - clock).toFixed(1)} с`);
        if (frame > 0) {
          const cw = sheet.cell_w;
          const ch = sheet.cell_h;
          const col = frame % sheet.cols;
          const row = Math.floor(frame / sheet.cols);
          tint.width = cw;
          tint.height = ch;
          const tc = tint.getContext('2d');
          tc.drawImage(sheet.img, col * cw, row * ch, cw, ch, 0, 0, cw, ch);
          if (!state.mask) {
            tc.globalCompositeOperation = 'multiply';
            tc.fillStyle = state.color;
            tc.fillRect(0, 0, cw, ch);
          }
          ctx.globalCompositeOperation = state.mask ? 'source-over' : 'lighter';
          ctx.drawImage(tint, 0, 0, cw, ch, 0, 0, w, h);
          pos = (frame - 1) / Math.max(1, sheet.frames - 2);
        }
      }
      clockOut.textContent = shown;
      playhead.hidden = pos < 0;
      if (pos >= 0) playhead.style.left = `calc(var(--tl-name) + (100% - var(--tl-name)) * ${pos})`;
      requestAnimationFrame(draw);
    }

    // ── Клавиши: пробел, Delete, Ctrl+Z/Y ─────────────────────────────
    const onKey = (e) => {
      if (!alive) return;
      const mod = e.ctrlKey || e.metaKey;
      const key = e.code;
      if (mod && !typing(e) && key === 'KeyZ') {
        e.preventDefault();
        travel(e.shiftKey ? 1 : -1);
      } else if (mod && !typing(e) && key === 'KeyY') {
        e.preventDefault();
        travel(1);
      } else if (key === 'Space' && !typing(e)) {
        e.preventDefault();
        playing = !playing;
        syncPlay();
      } else if (key === 'Delete' && !typing(e) && !e.target.closest('.lwarp__grad')
                 && state.layers[state.selected]) {
        e.preventDefault();
        removeLayer(state.selected);
      }
    };
    dlg.addEventListener('keydown', onKey);

    // ── Закрытие ───────────────────────────────────────────────────────
    let saving = false;
    const finish = (value) => {
      alive = false;
      clearTimeout(timer);
      clearTimeout(commitTimer);
      resizer.disconnect();
      dlg.removeEventListener('keydown', onKey);
      dlg.removeEventListener('click', closeMenu);
      dlg.close();
      resolve(value);
    };
    cancel.addEventListener('click', () => finish(null));
    // Esc - как «Отмена» (своим обработчиком: прошлые показы не копятся).
    dlg.oncancel = (e) => { e.preventDefault(); if (!saving) finish(null); };
    const doSave = async (asCopy) => {
      save.disabled = true;
      copy.disabled = true;
      saving = true;
      const label = asCopy ? t(`${state.name} (копия)`) : state.name;
      const res = await api.sheenPatternSave(asCopy ? '' : state.id, label,
        { layers: state.layers, quality: state.quality }, state.length);
      saving = false;
      save.disabled = false;
      copy.disabled = false;
      if (res.error) { note.textContent = res.error; return; }
      finish({ id: res.id, length: state.length });
    };
    save.addEventListener('click', () => doSave(false));
    copy.addEventListener('click', () => doSave(true));
    let sure = false;
    del.addEventListener('click', async () => {
      if (!sure) { sure = true; del.textContent = t('Точно удалить?'); return; }
      await api.sheenPatternDelete(state.id);
      finish({ id: '', deleted: state.id, length: state.length });
    });

    function renderAll() {
      renderLayers();
      renderRuler();
      renderTimeline();
      syncHistory();
    }

    renderAll();
    showSize();
    dlg.showModal();
    refresh();
    requestAnimationFrame((now) => { last = now; draw(now); });
  });
}
