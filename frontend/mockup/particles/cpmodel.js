/*
 * Модель для точек частиц: выбор из каталога игры, не из кэша.
 *
 * Тот же каталог, что в левой колонке (классы, шапки, оружие: обложки,
 * фильтр по классу, поиск), только в окне и с одним исходом — модель
 * встаёт в сцену частиц. Кэш декомпиляции общий с вкладками оружия и шапок:
 * что уже открывали, приходит сразу, остальное разбирает Crowbar (это
 * секунды-минуты, поэтому фоном: ответ «начали», сцена — событием cp_model).
 *
 * Четвёртая вкладка «Из кэша» — то, чего в каталоге нет (реквизит насмешек)
 * и вообще всё, что уже разобрано: без Crowbar и без ожидания.
 */

import * as api from '../api.js';
import { ask } from '../ask.js';
import { t } from '../i18n.js';
import { makePick, fillFilters } from '../catalog.js';
import { say } from '../stage.js';

const dlg = document.getElementById('cpmodeldlg');
const tabsEl = document.getElementById('cpm-tabs');
const classEl = document.getElementById('cpm-class');
const findEl = document.getElementById('cpm-find');
const noteEl = document.getElementById('cpm-note');
const gridEl = document.getElementById('cpm-grid');

const TABS = [
  { key: 'character', name: 'Классы' },
  { key: 'hat', name: 'Шапки' },
  { key: 'weapon', name: 'Оружие' },
  { key: 'cache', name: 'Из кэша' },
];
const CLASSES = ['Scout', 'Soldier', 'Pyro', 'Demoman', 'Heavy', 'Engineer',
                 'Medic', 'Sniper', 'Spy'];
const GROUPS = { player: 'Игроки', hat: 'Косметика', weapon: 'Оружие',
                 arms: 'Руки', other: 'Прочее' };

const state = { tab: 'character', cls: null, query: '' };
let resolveWith = null;

/** Открывает окно; ответ — {mode, key, qc, label} или null. */
export function pickCpModel() {
  return new Promise((resolve) => {
    resolveWith = resolve;
    state.query = '';
    findEl.value = '';
    drawTabs();
    refresh();
    dlg.showModal();
    findEl.focus();
  });
}

function settle(result) {
  const done = resolveWith;
  resolveWith = null;
  if (dlg.open) dlg.close();
  if (done) done(result);
}

dlg.addEventListener('cancel', () => settle(null));
dlg.addEventListener('close', () => settle(null));
document.getElementById('cpm-cancel').addEventListener('click', () => settle(null));
findEl.addEventListener('input', () => { state.query = findEl.value.trim(); refresh(); });
// Enter в поиске — не «отправить форму» (окно закрылось бы без ответа).
findEl.addEventListener('keydown', (e) => { if (e.key === 'Enter') e.preventDefault(); });

function drawTabs() {
  tabsEl.innerHTML = '';
  for (const tab of TABS) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'underlined' + (tab.key === state.tab ? ' is-active' : '');
    b.textContent = t(tab.name);
    b.addEventListener('click', () => { state.tab = tab.key; drawTabs(); refresh(); });
    tabsEl.appendChild(b);
  }
}

//: Номер последнего запроса: ответ более раннего (медленный поиск шапок)
//: не должен затирать свежий список.
let refreshSeq = 0;

async function refresh() {
  const tab = state.tab;
  const seq = ++refreshSeq;
  // Классы — сами по себе фильтр, у кэша класса нет.
  const withClass = tab === 'hat' || tab === 'weapon';
  classEl.hidden = !withClass;
  if (withClass) {
    fillFilters(classEl, CLASSES.map((c) => ({ key: c, name: c })), state.cls,
                (key) => { state.cls = key; refresh(); });
  }
  let list = [];
  try {
    list = await load(tab);
  } catch (err) {
    say(String(err.message || err));
  }
  if (seq !== refreshSeq) return;         // успели переключить вкладку или поиск
  const q = state.query.toLowerCase();
  if (q) {
    list = list.filter((it) => (it.name + ' ' + (it.label || '') + ' ' + (it.key || ''))
      .toLowerCase().includes(q));
  }
  gridEl.innerHTML = '';
  for (const item of list) {
    gridEl.appendChild(makePick(item, () => chosen(item)));
  }
  gridEl.hidden = list.length === 0;
  noteEl.hidden = list.length > 0;
  noteEl.textContent = tab === 'cache'
    ? t('В кэше нет разобранных моделей — откройте модель на вкладке оружия или шапок, и она появится здесь')
    : t('Ничего не найдено');
}

async function load(tab) {
  if (tab === 'character') {
    // Класс — заголовок карточки, «тело»/«руки» — подпись: здесь выбирают
    // модель, а не скин, и класс важнее.
    return (await api.items({ category: 'character' })).map((it) => ({
      ...it, name: it.cls, label: it.name,
    }));
  }
  if (tab === 'hat') {
    return (await api.hats({ query: state.query, tf2_class: state.cls })).items;
  }
  if (tab === 'weapon') {
    return api.items({ category: 'weapon', tf2_class: state.cls });
  }
  // Кэш: обложек у него нет — тип как у частиц, чтобы карточка не ходила
  // за иконкой; подпись — группа.
  return (await api.particleModels()).map((m) => ({
    key: m.qc, name: m.label, label: t(GROUPS[m.group] || GROUPS.other),
    type: 'particle', mode: 'cache',
  }));
}

/** Выбор карточки: у мультиклассовой шапки ещё спрашиваем класс. */
async function chosen(item) {
  if (item.mode === 'cache') {
    settle({ mode: 'cache', key: item.key, qc: item.key, label: item.name });
    return;
  }
  if (item.type === 'hat') {
    const perClass = item.per_class || {};
    const classes = Object.keys(perClass);
    let mdl = item.key;
    if (classes.length > 1) {
      const pick = (state.cls && perClass[state.cls]) ? state.cls : await ask({
        title: 'Какой класс',
        text: 'У этой шапки своя модель на каждый класс.',
        list: classes.map((c) => ({ label: c, value: c })),
        ok: 'Показать',
      });
      if (!pick) return;
      mdl = perClass[pick] || mdl;
    } else if (classes.length === 1) {
      mdl = perClass[classes[0]] || mdl;
    }
    settle({ mode: 'hat', key: mdl, label: item.name });
    return;
  }
  settle({ mode: item.mode, key: item.key, label: item.name });
}
