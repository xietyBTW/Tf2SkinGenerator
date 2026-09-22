/*
 * Каталог систем PCF: дерево слева и загрузка файла.
 *
 * Разбор PCF идёт ОТВЕТОМ, а не событием: он занимает около секунды, зато
 * приезжает целиком (системы, материалы с развёрнутыми в PNG текстурами и
 * дерево вложенности), и показывать до этого всё равно нечего.
 */

import * as api from '../api.js';
import { t } from '../i18n.js';
import { stage, say, sayBusy, withParticles } from '../stage.js';
import { closeCat } from '../layout.js';
import { els, fillFilters, applyToolsMenu } from '../catalog.js';
import { plural } from '../util.js';
import { pcfNodes, pcfTree, pcfCollapsed, pSystem, setTree, pcfDiff, setDiff } from './state.js';
import { systemMenu } from './actions.js';
import { showParams } from './params.js';
import { syncHistory, editorKey } from './playback.js';
import { showParticleMaterials } from './materials.js';
import { cpBox, cpFillIndexes } from './points.js';

//: Имена эффектов из игры по имени системы: «Burning Flames» под
//: `superrare_burning1`. Наполняется каталогом эффектов.
const fxNames = new Map();
//: Какой файл открыт — чтобы по щелчку в списке эффектов не перечитывать его.
let loadedFile = '';
let loadedShort = '';

/**
 * Заголовок: имя из игры, если оно есть, иначе имя системы; в подписи —
 * система, файл и размер. «Язычки пламени» человек узнаёт сразу,
 * `superrare_burning1` — нет.
 */
export function setTitle(system) {
  const known = fxNames.get(system);
  const status = pcfDiff.get(system);
  document.querySelector('.title__name').textContent = known || system;
  document.querySelector('.title__meta').textContent =
    (known ? system + ' · ' : '') + loadedShort + ' · ' + pcfTree.length
    + t(' систем, корней ') + pcfNodes.length
    + (status === 'changed' ? t(' · изменена относительно игры')
       : status === 'added' ? t(' · нет в игре') : '');
}
//: Загруженный файл могли открыть с диска, тогда путь чужой; для поиска
//: важен только игровой.
export const currentFile = () => loadedFile;

/**
 * Рисует дерево систем.
 *
 * Ребёнок стоит под родителем с отступом, у родителя — треугольник. Плоским
 * списком 104 системы class_fx читаются как свалка, а вложенность в PCF
 * настоящая: родитель тянет детей за собой.
 */
export function fillTree(nodes, selected) {
  els.grid.innerHTML = '';
  // Источники — про список игры; у дерева файла им делать нечего.
  els.fSource.hidden = true;
  let shown = 0;

  const walk = (list, depth) => {
    for (const node of list) {
      shown += 1;
      const row = document.createElement('div');
      row.className = 'tree__row';
      row.style.setProperty('--depth', depth);

      const twist = document.createElement('button');
      twist.className = 'tree__twist';
      twist.type = 'button';
      if (node.kids.length) {
        const open = !pcfCollapsed.has(node.key);
        twist.textContent = open ? '−' : '+';
        twist.title = open ? 'Свернуть' : 'Развернуть';
        twist.addEventListener('click', (e) => {
          e.stopPropagation();
          if (open) pcfCollapsed.add(node.key);
          else pcfCollapsed.delete(node.key);
          fillTree(pcfNodes, pSystem);
        });
      } else {
        twist.disabled = true;
      }

      const name = document.createElement('button');
      name.className = 'tree__name' + (node.key === selected ? ' is-active' : '');
      name.type = 'button';
      name.textContent = node.name;
      // Имя из игры — рядом: `superrare_burning1` человеку ничего не
      // говорит, «Burning Flames» — всё.
      const known = fxNames.get(node.key);
      if (known) {
        const tag = document.createElement('span');
        tag.className = 'tree__fx';
        tag.textContent = known;
        name.append(tag);
      }
      // Точка у изменённой системы: в чужом файле сразу видно, что трогали.
      const status = pcfDiff.get(node.key);
      if (status && status !== 'same') {
        name.classList.add('is-' + status);
        name.title = (status === 'added' ? 'Нет в игре' : 'Изменена относительно игры');
      }
      name.title = node.kids.length
        ? `${node.name} · дочерних: ${node.kids.length}` : node.name;
      name.addEventListener('click', () => pickSystem(name, node));
      name.addEventListener('contextmenu', (e) => systemMenu(e, node.key));

      row.append(twist, name);
      els.grid.append(row);

      if (node.kids.length && !pcfCollapsed.has(node.key)) {
        walk(node.kids, depth + 1);
      }
    }
  };

  walk(nodes, 0);
  // Счётчик — общий с предметами, но считает системы, а не предметы.
  const count = document.getElementById('cat-count');
  count.hidden = !shown;
  count.textContent = shown + ' ' + plural(shown, 'система', 'системы', 'систем');
}

//: Номер последнего запроса эффектов: ответы приходят не по порядку.
let fxTurn = 0;
//: Выбранный источник: оружие, постройки, игрок… Пусто — все.
let source = '';
//: Последний запрос — чтобы смена источника перерисовала тот же список.
let lastQuery = '';
//: Корни списка эффектов, развёрнутые рукой; держатся между перерисовками.
const fxOpen = new Set();

/**
 * Каталог эффектов игры: по имени, а не по файлу.
 *
 * Без запроса — необычные эффекты с именами из игры по категориям: это то,
 * за чем сюда приходят. С запросом — поиск по ним и по всем системам всех
 * 134 файлов: знать, что «Burning Flames» лежит в `item_fx.pcf` как
 * `superrare_burning1`, никто не обязан.
 */
export async function showEffects(query = '') {
  const mine = ++fxTurn;
  lastQuery = query;
  const res = await api.particleEffects(query, source);
  if (mine !== fxTurn) return;
  for (const it of res.items) {
    for (const k of [it, ...it.kids]) if (k.name) fxNames.set(k.system, k.name);
  }

  // Виды источников — только те, что есть под этим запросом; выбор
  // держится, пока его не сняли.
  fillFilters(els.fSource, res.facets || [], source || null, (key) => {
    source = key || '';
    showEffects(lastQuery);
  });
  els.fSource.hidden = !(res.facets || []).length;

  els.grid.innerHTML = '';
  let group = '';
  for (const it of res.items) {
    // Без запроса список идёт группами: каталог — по категориям, источник
    // — по предмету («Огнемёт», «Турель»); подписываем границы.
    const key = query ? '' : (source ? (it.labels[0] || '') : it.category_name);
    if (!query && key !== group) {
      group = key;
      const head = document.createElement('p');
      head.className = 'label fx__head';
      head.textContent = group || 'Без предмета';
      els.grid.append(head);
    }
    // Корень первым, дочерние системы под ним свёрнуты: у эффекта из
    // тридцати систем человеку нужна одна строка. При поиске раскрыты те,
    // где совпали именно дети — иначе непонятно, почему корень в списке.
    const row = effectRow(it, 0, query);
    // У ребёнка не повторяем то, что уже сказано у корня: «Язычки пламени»
    // под «Язычками пламени» — шум.
    const said = new Set([it.name, ...it.labels]);
    const kids = it.kids.map((k) => effectRow(k, 1, query, said));
    if (kids.length) {
      const twist = row.firstChild;
      twist.disabled = false;
      const show = (on) => {
        twist.textContent = on ? '−' : '+';
        // Подпись на уже показанной кнопке: наблюдатель перевода её не
        // увидит, он смотрит только за добавленными узлами.
        twist.title = t(on ? 'Свернуть' : 'Развернуть');
        for (const k of kids) k.hidden = !on;
      };
      show(it.open || fxOpen.has(it.system));
      twist.addEventListener('click', () => {
        const on = kids[0].hidden;
        show(on);
        if (on) fxOpen.add(it.system); else fxOpen.delete(it.system);
      });
    }
    els.grid.append(row, ...kids);
  }

  const count = document.getElementById('cat-count');
  count.hidden = !res.items.length;
  count.textContent = res.total > res.items.length
    ? `${res.items.length} из ${res.total}`
    : res.items.length + ' ' + plural(res.items.length, 'эффект', 'эффекта', 'эффектов');
  els.note.hidden = res.items.length > 0;
  els.note.textContent = res.ready
    ? 'Ничего не найдено.'
    : 'Индекс эффектов ещё строится — пока ищем только по именам из игры.';
}

/** Строка списка эффектов: имя, чем вызывается, система, файл. */
function effectRow(it, depth, query, said = new Set()) {
  const row = document.createElement('div');
  row.className = 'tree__row';
  row.style.setProperty('--depth', depth);
  const twist = document.createElement('button');
  twist.className = 'tree__twist';
  twist.type = 'button';
  twist.disabled = true;

  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'fx' + (depth ? ' fx--kid' : '')
                + (it.system === pSystem ? ' is-active' : '');
  btn.innerHTML = '<span class="fx__what"><b class="fx__name"></b>'
                + '<span class="fx__who"></span></span>'
                + '<span class="fx__sys mono"></span>'
                + '<span class="fx__file mono"></span>';
  btn.querySelector('.fx__name').textContent = it.name || it.system;
  // Чем вызывается — словами: «Огнемёт», «Турель». В группе по предмету
  // первый уже в заголовке, остальные (общие эффекты) — при строке.
  const who = it.labels.filter((l, i) => !(source && !query && i === 0) && !said.has(l));
  btn.querySelector('.fx__who').textContent = who.join(', ');
  btn.querySelector('.fx__sys').textContent = it.name ? it.system : '';
  btn.querySelector('.fx__file').textContent =
    (it.file || '').replace(/^particles\//, '');
  btn.addEventListener('click', () => openEffect(it));
  btn.addEventListener('contextmenu', (e) => {
    if (it.file === loadedFile) systemMenu(e, it.system);
  });
  row.append(twist, btn);
  return row;
}

/** Открывает эффект из списка: файл, если он другой, затем систему. */
async function openEffect(it) {
  if (!it.file) {
    say('Индекс эффектов ещё строится — попробуйте через несколько секунд');
    return;
  }
  if (it.file !== loadedFile) {
    await loadPcf(it.file);
    // Файл не открылся — дерева нет, выбирать не из чего.
    if (loadedFile !== it.file) return;
  }
  const node = pcfTree.find((n) => n.key === it.system);
  if (!node) { say('В файле нет такой системы'); return; }
  fillTree(pcfNodes, it.system);
  const button = [...els.grid.querySelectorAll('.tree__name')]
    .find((b) => b.firstChild && b.firstChild.textContent === node.name);
  await pickSystem(button || document.createElement('button'), node);
}

/** Переводит кадр на движок частиц (или обратно на вьювер моделей). */
export function showParticleFrame(on) {
  // Адрес ставим при первом входе: второй three.js на неоткрытой вкладке
  // грузить незачем.
  if (on && !stage.pframe.src) {
    stage.pframe.src = '/viewer/particles3d.html';
    // Язык — сразу: подсказка «выберите систему» стоит в кадре до первого
    // файла, а до него движок говорил по-английски при любой настройке.
    withParticles((w) => w.setLanguage && w.setLanguage(api.lang()));
  }
  stage.pframe.hidden = !on;
  stage.frame.hidden = on;
}

/** Загружает PCF и показывает первый эффект. */
export async function loadPcf(source, label = '') {
  const short = label || source.replace(/^particles\//, '');
  say(`Разбор ${short}…`);
  els.grid.innerHTML = '';
  const data = await api.loadParticles(source);
  if (data.error) { say(data.error); return; }

  setTree(data.tree || []);
  setDiff(data.diff || {});
  loadedFile = source;
  applyToolsMenu();            // «Сохранить PCF» — теперь есть что
  // Выпадашка показывает открытый файл и когда его выбрали из списка игры.
  if ([...els.cat.options].some((o) => o.value === source)) els.cat.value = source;
  // Новый файл — свои узлы; старое состояние свёрнутости к ним не относится.
  pcfCollapsed.clear();
  // Дочерние сворачиваем сразу: сверху видно корни эффектов, а не всё подряд.
  for (const n of pcfNodes) if (n.kids.length) pcfCollapsed.add(n.key);

  withParticles((w) => {
    w.setLanguage && w.setLanguage(api.lang());
    // Клавиши принадлежат странице, а фокус после щелчка по кадру — движку:
    // он передаёт нажатие сюда (см. playback.js → editorKey).
    w.onEditorKey = editorKey;
    w.loadParticleData(data);
  });
  loadedShort = short;
  setTitle(data.rootName || short.replace(/\.pcf$/, ''));

  fillTree(pcfNodes, data.rootName);
  els.note.hidden = pcfTree.length > 0;
  els.note.textContent = 'В этом файле систем нет.';
  say('');
  await syncHistory();
  if (data.rootName) await showParams(data.rootName);
  await showParticleMaterials();
}

/** Выбор системы: движок строит эффект от названного узла. */
export async function pickSystem(button, item) {
  els.grid.querySelectorAll('.tree__name, .pick')
          .forEach((b) => b.classList.remove('is-active'));
  button.classList.add('is-active');
  setTitle(item.key);
  closeCat();
  // Пока собирается, кадр остаётся прежним: у эффекта распаковываются
  // текстуры, и без единого слова это читается как «ничего не произошло».
  // sayBusy, а не say: маленький эффект успевает раньше, чем подпись нужна.
  sayBusy('Собираю эффект…');
  withParticles((w) => w.setRootSystem(item.key));
  await showParams(item.key);
  await showParticleMaterials();
  say('');
  if (!cpBox.hidden) cpFillIndexes();
}
