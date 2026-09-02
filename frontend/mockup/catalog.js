/*
 * Каталог: чем набивается левая панель и что происходит по выбору.
 *
 * Списки, фильтры и правила видимости приходят из src/app/api.py — здесь
 * только отрисовка. Ни перечня предметов, ни условий «что показывать» в
 * представлении быть не должно, иначе они разъедутся с приложением.
 *
 * Три источника, а не один: «Оружие» ходит в items() с категориями и типами,
 * «Шапки» — в hats() с поиском и классом, «Частицы» — в particle_files().
 */

import * as api from './api.js';
import { fileSize, chooseFile } from './util.js';
import { ask } from './ask.js';
import { say } from './stage.js';
import {
  root,
  catalog,
  plist,
  pnote,
  applyRightPanel,
  closeCat,
  setStatus,
  showTf2Path,
} from './layout.js';
import {
  loadPcf,
  pickSystem,
  systemMenu,
  showParticleFrame,
  cpBox,
  setSystem,
} from './particles/index.js';
import { diagDlg, diagSay } from './diagnostics.js';
import { setMode } from './controls.js';
import { startPreview, clearPreview } from './preview.js';

export const els = {
  cat:   document.getElementById('cat'),
  fClass:document.getElementById('f-class'),
  fHat:  document.getElementById('f-hat'),
  fType: document.getElementById('f-type'),
  catLabel: document.getElementById('catlabel'),
  note:  document.getElementById('cat-note'),
  grid:  document.getElementById('grid'),
};

export const sel = { section: 'weapons', category: 'weapon', cls: null,
              type: null, mode: 'normal', query: '' };

/** Рисует ряд фильтров; null-кнопка «Все» снимает ограничение. */
export function fillFilters(row, list, chosen, onPick) {
  row.querySelectorAll('.underlined').forEach((b) => b.remove());
  const add = (key, name) => {
    const b = document.createElement('button');
    b.className = 'underlined' + (key === chosen ? ' is-active' : '');
    b.textContent = name;
    b.addEventListener('click', () => onPick(key));
    row.appendChild(b);
  };
  add(null, 'Все');
  list.forEach((x) => add(x.key, x.name));
  row.hidden = list.length === 0;
}

export function fillGrid(list) {
  els.grid.innerHTML = '';
  for (const item of list) {
    const b = document.createElement('button');
    b.className = 'pick';
    b.dataset.mode = item.mode;
    b.innerHTML = `<span class="pick__box"></span>
      <span class="pick__name"></span><span class="mono"></span>`;
    // Вложенность системы в PCF: ребёнок принадлежит родителю, и без
    // отступа список из 114 имён читается как каша.
    if (item.depth) b.style.setProperty('--depth', item.depth);
    // Обложка — та же иконка, что у предмета в рюкзаке. Грузим лениво: на
    // экране три сотни карточек, а браузер запросит только видимые.
    // У частиц иконок нет вовсе — незачем стучаться за 404 сто раз.
    const key = item.type === 'particle' ? '' : (item.icon || item.key);
    if (key) {
      const img = document.createElement('img');
      img.className = 'pick__icon';
      img.loading = 'lazy';
      img.alt = '';
      // Иконки в игре есть не у всего (стоковые ножи, часть праздничных):
      // на 404 убираем картинку и оставляем пустую рамку.
      img.addEventListener('error', () => img.remove());
      img.src = api.iconUrl(key);
      b.querySelector('.pick__box').appendChild(img);
    }
    b.querySelector('.pick__name').textContent = item.name;
    b.querySelector('.mono').textContent = item.label ?? item.key;
    b.addEventListener('click', () => (item.type === 'particle'
      ? pickSystem(b, item) : choose(b, item)));
    // Правая кнопка на системе — её меню, как в дереве систем приложения.
    if (item.type === 'particle') {
      b.addEventListener('contextmenu', (e) => systemMenu(e, item.key));
    }
    els.grid.appendChild(b);
  }
  els.grid.hidden = list.length === 0;
}

/**
 * Категория «Кастомный мод»: дверь к файлу и всё, что через неё уже прошло.
 *
 * Мод — это ВЫБОР предмета, а не действие над загруженным: он заменяет собой
 * и модель, и текстуры. Поэтому живёт в каталоге рядом с оружием и шапками, а
 * не в ряду кнопок под моделью.
 */
export async function showModLibrary() {
  els.grid.innerHTML = '';
  els.note.hidden = false;
  els.note.textContent = 'Мод откроется как предмет: его модель и текстуры '
    + 'станут тем, что на экране, а сам файл уйдёт в сборку основой.';

  const open = document.createElement('button');
  open.className = 'pick pick--open';
  open.innerHTML = `<span class="pick__box"></span>
    <span class="pick__name">Открыть VPK-мод…</span>
    <span class="mono">файл с диска</span>`;
  open.addEventListener('click', pickVpkMod);
  els.grid.append(open);

  for (const mod of await api.modLibrary()) {
    const card = document.createElement('button');
    card.className = 'pick pick--mod';
    card.innerHTML = `<span class="pick__box"></span>
      <span class="pick__name"></span><span class="mono"></span>`;
    card.querySelector('.pick__name').textContent = mod.name;
    card.querySelector('.mono').textContent = fileSize(mod.size);
    card.addEventListener('click', () => openMod(mod));
    showModIcon(card, mod);

    // Удаление — на самой карточке: искать папку на диске ради этого не
    // должно быть нужно. Спрашиваем подтверждение: файл уйдёт насовсем.
    const drop = document.createElement('span');
    drop.className = 'pick__drop';
    drop.title = 'Убрать из библиотеки (исходный файл останется)';
    drop.textContent = '×';
    drop.addEventListener('click', async (e) => {
      e.stopPropagation();                  // не открыть заодно
      // Про исходный файл говорим прямо: в библиотеке лежит НАША копия, и
      // «убрать» здесь не трогает то, что человек когда-то выбрал на диске.
      const yes = await ask({
        title: 'Убрать мод из библиотеки',
        text: mod.name + '\nУдалится копия в библиотеке. '
            + 'Исходный файл, который вы открывали, останется на месте.',
        ok: 'Убрать',
      });
      if (!yes) return;
      const res = await api.removeMod(mod.name);
      if (res.error) { say(res.error); return; }
      await showModLibrary();
    });
    card.append(drop);
    els.grid.append(card);
  }
}

/**
 * Обложка мода на карточке.
 *
 * Готовую ставим сразу, недостающую просим построить — по одной и не блокируя
 * список: первое открытие каталога иначе ждало бы декодирования всех текстур
 * библиотеки.
 */
async function showModIcon(card, mod) {
  const put = (path) => {
    if (!path) return;
    const img = document.createElement('img');
    img.className = 'pick__icon';
    img.alt = '';
    img.addEventListener('error', () => img.remove());
    img.src = api.fileUrl(path);
    card.querySelector('.pick__box').append(img);
  };

  if (mod.icon) { put(mod.icon); return; }
  const res = await api.modIcon(mod.name);
  // Карточка могла уехать, пока строилась обложка (удалили, сменили раздел).
  if (card.isConnected) put(res.icon);
}

/**
 * Показ чужого мода из VPK.
 *
 * Предмет не меняется: мод накладывается поверх текущего выбора, его модель и
 * текстуры становятся тем, что на экране, а сам файл уходит в сборку
 * источником.
 */
export async function openMod(mod) {
  say('Разбор ' + mod.name + '…');
  const res = await api.loadVpkMod(mod.path);
  if (res.error) { say(res.error); return; }
  showModAsItem(mod.name);
}

/** Выбирает файл с диска: он попадает в библиотеку и сразу открывается. */
async function pickVpkMod() {
  const file = await chooseFile('.vpk');
  if (!file) return;

  say('Разбор ' + file.name + '…');
  // Сохраняем ДО открытия: временную копию, в которую браузер положил файл,
  // рано или поздно чистят, и вернуться к моду было бы не по чему.
  const saved = await api.addMod(await api.upload(file));
  if (saved.error) { say(saved.error); return; }
  await openMod({ name: saved.name, path: saved.path });
}

/** Показанный мод становится выбранным предметом: заголовок называет его. */
function showModAsItem(name) {
  document.querySelector('.title__name').textContent = name;
  document.querySelector('.title__meta').textContent = 'мод из VPK';
  closeCat();
  setMode('custom');
}

async function choose(button, item) {
  els.grid.querySelectorAll('.pick').forEach((p) => p.classList.remove('is-active'));
  button.classList.add('is-active');
  document.querySelector('.title__name').textContent = item.name;
  document.querySelector('.title__meta').textContent =
    [item.label ?? item.key, item.cls].filter(Boolean).join(' · ');
  closeCat();
  await setMode(item.mode);
  await startPreview(item);
}

//: Номер последнего запроса списка. Ответы приходят по сети и могут обогнать
//: друг друга: быстро щёлкнув по фильтрам, легко получить список от прошлого
//: выбора. Рисуем только тот ответ, который всё ещё актуален.
let reloadSeq = 0;

export async function reload() {
  const seq = ++reloadSeq;
  const list = sel.section === 'hats'
    ? await api.hats({ query: sel.query || '', tf2_class: sel.cls, lang: 'ru' })
    : await api.items({ category: sel.category, tf2_class: sel.cls,
                        weapon_type: sel.type, lang: 'ru' });
  if (seq !== reloadSeq) return;               // выбор успел смениться

  // Кастомный мод: предмет здесь — файл на диске. Список берётся не из
  // данных игры, а из библиотеки уже открытых модов.
  if (sel.category === 'custom' && sel.section !== 'hats') {
    await showModLibrary();
    return;
  }

  fillGrid(list);
  els.note.hidden = list.length > 0;
  // Пусто по разной причине: у косметики фильтры просто ничего не нашли,
  // у остальных категорий списка ещё нет.
  if (!list.length) {
    els.note.textContent = sel.section === 'hats'
      ? 'Ничего не найдено — попробуйте изменить фильтр или запрос.'
      : 'Для этой категории список ещё не подключён.';
  }
}

/**
 * Переключение раздела.
 *
 * «Оружие» ходит в items() с категориями и типами, «Шапки» — в hats() с
 * поиском и классом: у косметики нет ни слотов оружия, ни подтипов, и
 * притворяться, что есть, значило бы показывать пустые фильтры.
 */
export async function pickSection(name) {
  // Диагностика — отчёт, а не рабочее место: открываем окно и оставляем
  // текущий раздел на месте.
  if (name === 'Диагностика') {
    diagDlg.showModal();
    if (!document.getElementById('diag-status').textContent) {
      diagSay('Выберите собранный VPK-мод');
    }
    return false;
  }

  const было = sel.section;
  sel.section = { 'Шапки': 'hats', 'Частицы': 'particles' }[name] || 'weapons';
  root.dataset.section = sel.section;

  // Смена раздела — это уход от предмета. Воркер останавливаем ПЕРВЫМ: иначе
  // он ещё пришлёт model_ready, и текстура оружия вернётся в альбом уже поверх
  // чужого каталога.
  if (было !== sel.section) {
    await api.stopPreview();
    clearPreview();
    say('');
  }

  const это_шапки = sel.section === 'hats';
  const это_частицы = sel.section === 'particles';
  showParticleFrame(это_частицы);
  cpBox.hidden = true;                 // точки живут только у эффекта
  document.getElementById('pacts').hidden = !это_частицы;
  document.getElementById('model-acts').hidden = это_частицы;
  applyRightPanel();      // правая панель зависит от раздела
  // Переключатель показа общий с оружием, но у эффекта правая половина —
  // не модель: там сцена с частицами. Меняем подпись, а не поведение.
  const modeModel = document.querySelector('.modes [data-view="model"]');
  modeModel.textContent = это_частицы ? 'Эффект' : 'Модель';
  document.querySelector('.modes [data-view="fp"]').hidden = это_частицы;
  // Раздел открывается на «Вместе»: слева текстуры, справа эффект.
  document.querySelectorAll('.modes .underlined').forEach(
    (b) => b.classList.toggle('is-active', b.dataset.view === 'both'));
  document.querySelector('.work').dataset.view = 'both';

  els.cat.parentElement.parentElement.hidden = это_шапки;   // категорию прячем
  els.fType.hidden = true;
  els.fClass.hidden = это_частицы;
  els.fHat.hidden = !это_шапки;
  catalog.classList.toggle('no-icons', это_частицы);
  catalog.classList.toggle('catalog--tree', это_частицы);

  // Сборка VPK у частиц своя (ParticleEditorService.export_vpk) и ещё не
  // подключена. Кнопка собрала бы текстуру ОРУЖИЯ — лучше честно погасить.
  setStatus('Готово', false);
  applyToolsMenu(это_частицы);

  // Заголовок называет ВЫБРАННОЕ. Уходя из раздела, чужое имя надо убрать —
  // иначе над каталогом оружия висит название эффекта.
  document.querySelector('.title__name').textContent = это_частицы
    ? 'Файл не выбран' : 'Выберите предмет';
  document.querySelector('.title__meta').textContent = '';

  if (это_частицы) {
    els.catLabel.textContent = 'Файл частиц';
    els.cat.innerHTML = '';
    for (const f of await api.particleFiles()) {
      els.cat.append(new Option(f.name, f.key));
    }
    els.note.hidden = false;
    els.note.textContent = 'Выберите файл — в нём десятки эффектов.';
    els.grid.innerHTML = '';
    plist.innerHTML = '';
    pnote.hidden = false;
    setSystem('');
    return;
  }

  els.catLabel.textContent = 'Категория';

  if (это_шапки) {
    sel.category = 'hat';
    sel.cls = null;
    fillFilters(els.fClass, await api.classes(), null, pickClass);
    els.fClass.hidden = false;
    await fillHatFilters();
    await setMode('hat');
    await reload();
    return;
  }

  if (name !== 'Оружие') {
    els.grid.innerHTML = '';
    els.note.hidden = false;
    els.note.textContent = 'Раздел «' + name + '» ещё не подключён.';
    return;
  }
  await fillCategories();
  await pickCategory('weapon');
}

export async function pickCategory(key) {
  sel.category = key;
  sel.cls = null;
  sel.type = null;

  // Класс имеет смысл только у оружия и персонажа, тип — только у оружия.
  const wantClass = key === 'weapon' || key === 'character';
  const wantType = key === 'weapon';
  els.fClass.hidden = !wantClass;
  els.fType.hidden = !wantType;

  if (wantClass) fillFilters(els.fClass, await api.classes(), null, pickClass);
  else els.fClass.querySelectorAll('.underlined').forEach((b) => b.remove());

  // Тип работает и без класса: «Ближний бой» по всем классам — нормальный
  // запрос, требовать сперва выбрать класс незачем.
  if (wantType) fillFilters(els.fType, await api.weaponTypes(null), null, pickType);
  else els.fType.querySelectorAll('.underlined').forEach((b) => b.remove());

  await setMode(await api.modeFor(key));
  await reload();
}

/**
 * Фильтр категорий косметики: медали, Halloween, сезонные.
 *
 * Это переключатели «скрыть», а не «показать»: медалей 7628 из 9504, и
 * держать их в списке по умолчанию бессмысленно. Состояние живёт в конфиге
 * приложения — то же, что видит панель шапок в окне.
 */
export async function fillHatFilters() {
  els.fHat.querySelectorAll('.tag').forEach((b) => b.remove());
  for (const f of await api.hatFilters()) {
    const b = document.createElement('button');
    b.className = 'tag' + (f.hidden ? ' is-active' : '');
    b.textContent = f.name.replace(/^Скрыть /, '');
    b.title = f.name;
    b.addEventListener('click', async () => {
      const state = await api.setHatFilter(f.key, !b.classList.contains('is-active'));
      const now = state.find((x) => x.key === f.key);
      b.classList.toggle('is-active', now.hidden);
      await reload();
    });
    els.fHat.appendChild(b);
  }
}

export async function pickClass(key) {
  sel.cls = key;
  fillFilters(els.fClass, await api.classes(), key, pickClass);

  if (sel.category === 'weapon') {
    // Набор типов сужается классом: у скаута нет часов. Выбранный тип
    // сохраняем, если он у нового класса есть, иначе снимаем — иначе список
    // молча оказался бы пустым.
    const types = await api.weaponTypes(key);
    if (sel.type && !types.some((t) => t.key === sel.type)) sel.type = null;
    fillFilters(els.fType, types, sel.type, pickType);
  }
  await reload();
}

export async function pickType(key) {
  sel.type = key;
  fillFilters(els.fType, await api.weaponTypes(sel.cls), key, pickType);
  await reload();
}

// Поиск: у шапок это единственный способ найти нужное среди тысяч, поэтому
// он ищет на стороне Python, а не фильтрует показанное.
let searchTimer = null;
document.querySelector('.catalog__search').addEventListener('input', (e) => {
  sel.query = e.target.value.trim();
  clearTimeout(searchTimer);
  searchTimer = setTimeout(reload, 250);
});

/** Заполняет селектор категориями предметов (раздел частиц ставит туда PCF). */
export async function fillCategories() {
  els.cat.innerHTML = '';
  for (const c of await api.categories()) els.cat.append(new Option(c.name, c.key));
}

/** Меню инструментов: у эффекта свои пункты, у предмета — свои.
 *  Зовётся и на старте: раздел «Оружие» открывается без pickSection, и без
 *  этого в меню висели пункты PCF при выбранном оружии. */
export function applyToolsMenu(particlesSection) {
  document.querySelectorAll('#tools .menu__item').forEach((i) => {
    i.hidden = (i.dataset.for === 'particles') !== particlesSection;
  });
}

export async function boot() {
  applyToolsMenu(false);
  showTf2Path();
  await fillCategories();
  els.cat.addEventListener('change', () => (sel.section === 'particles'
    ? loadPcf(els.cat.value) : pickCategory(els.cat.value)));
  await pickCategory('weapon');
}

// Разделы в шапке: «Оружие», «Шапки» и «Частицы» — разные источники каталога.
// «Диагностика» раздела не занимает (открывает отчёт), поэтому подсветку
// двигаем только если раздел действительно сменился.
document.querySelector('.chrome__nav').addEventListener('click', async (e) => {
  const btn = e.target.closest('.underlined');
  if (!btn) return;
  if (await pickSection(btn.textContent.trim()) === false) return;
  document.querySelectorAll('.chrome__nav .underlined')
          .forEach((b) => b.classList.remove('is-active'));
  btn.classList.add('is-active');
});
