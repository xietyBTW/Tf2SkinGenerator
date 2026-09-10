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
import { fileSize, chooseFile, plural } from './util.js';
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
import { applyLook } from './settings.js';
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

/*
 * Обложки специальных режимов.
 *
 * Иконки в рюкзаке у них нет и быть не может — спрей и эффекты смерти не
 * предметы, — а пустая рамка не отличала одну карточку от другой: пять
 * одинаковых квадратов, и узнать «Лёд» можно было только по подписи.
 *
 * Рисунок живёт здесь, а не в разметке: карточки строит код, и значок
 * выбирается по ключу режима. Тот же приём, что у шестерёнки кадра
 * (preview.js → GEAR).
 *
 * Сетка 32, линия волосяная, заливка только у капель баллончика — как у всех
 * значков окна. Толщину задаёт CSS (`.pick__art`), потому что она не должна
 * расти вместе с обложкой: в плавающем каталоге та около 190 точек, а в
 * прибитой панели 26.
 */
const SPECIAL_ART = {
  // Крит — вспышка попадания: восемь лучей, центр пуст.
  critHIT: '<path d="M16 2v7M16 23v7M2 16h7M23 16h7"/>'
         + '<path d="M6.2 6.2 11 11M21 21l4.8 4.8M25.8 6.2 21 11M11 21l-4.8 4.8"/>',
  // Спрей — единственный из пяти, что рисуют рукой: баллончик и три капли.
  spray: '<path d="M11 11h9v18h-9z"/><path d="M13.5 7.5h4V11h-4z"/>'
       + '<path d="M11 15h9"/>'
       + '<circle class="pick__drop" cx="24" cy="6" r="1"/>'
       + '<circle class="pick__drop" cx="27.5" cy="3.5" r="1"/>'
       + '<circle class="pick__drop" cx="27" cy="8.5" r="1"/>',
  // Лёд — кристалл. Огранка нужна, чтобы он не путался со вспышкой крита:
  // снежинка из тех же лучей была бы на неё похожа.
  death_ice: '<path d="M16 3 24 9.5 21.5 24 16 29 10.5 24 8 9.5Z"/>'
           + '<path d="M16 3v26M8 9.5 16 14l8-4.5"/>',
  // Золото — слиток. Блик обязателен: без него слиток читается коробкой.
  death_gold: '<path d="M6 26h20l-3.5-9.5h-13Z"/><path d="M9.5 16.5h13"/>'
            + '<path d="M11.5 21.5h9"/>'
            + '<path d="M24 3 25.2 6.3 28.5 7.5 25.2 8.7 24 12 22.8 8.7 19.5 7.5 22.8 6.3Z"/>',
  // Огонь — язык пламени со внутренним: самый однозначный силуэт из пяти.
  death_fire: '<path d="M16 2.5c5 5.5 7.5 9 7.5 13.5A7.5 7.5 0 0 1 8.5 16c0-3 '
            + '1.5-5.5 3.5-7.5 0 2.5 1 4 2.5 4.5-.5-4 .5-7.5 1.5-10.5Z"/>'
            + '<path d="M16 16.5c1.9 3 3.8 4.4 3.8 6.8 0 2.3-1.7 4-3.8 4s-3.8-1.7-3.8-4'
            + 'c0-2.4 1.9-3.8 3.8-6.8Z"/>',
};

/** Значок специального режима в обложку. Незнакомый режим — пустая рамка. */
function specialArt(box, mode) {
  const art = SPECIAL_ART[mode];
  if (!art) return;
  box.insertAdjacentHTML('beforeend',
    '<svg class="pick__art" viewBox="0 0 32 32" aria-hidden="true">' + art + '</svg>');
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
    // Обложка: иконка из рюкзака, а у кого её нет — текстура самой модели
    // (см. api.icon_png). Грузим лениво: на экране три сотни карточек, а
    // браузер запросит только видимые.
    // У частиц и спец-режимов картинки в игре нет вовсе — спрей и эффекты
    // смерти не предметы, и стучаться за 404 на каждую карточку незачем.
    // Спец-режимам обложку рисуем сами (см. SPECIAL_ART).
    const noIcon = item.type === 'particle' || item.type === 'special';
    const key = noIcon ? '' : (item.icon || item.key);
    // У спец-режима вместо картинки свой значок: что это за режим, видно на
    // обложке, а не только в подписи.
    if (item.type === 'special') specialArt(b.querySelector('.pick__box'), item.mode);
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
    // У косметики подпись — КЛАСС, а не имя файла: у мультиклассовой шапки в
    // пути стоит подстановка (`bak_teufort_knight_%s`), и показывать её
    // человеку незачем. Длинный список сворачивается в «N классов», иначе он
    // отъедает место у названия — как в панели приложения.
    b.querySelector('.mono').textContent = item.type === 'hat'
      ? classTag(item) : (item.label ?? item.key);
    // Пометка у шапки с модельными стилями: у каждого стиля СВОЯ геометрия, и
    // до выбора об этом узнать было неоткуда — а стилей больше одного у 224
    // предметов из 1822. Пометка на обложке, а не в подписи: подпись занята
    // классом, и число стилей спорило бы с ним за место.
    const styles = (item.styles || []).length;
    if (styles > 1) {
      const mark = document.createElement('i');
      mark.className = 'pick__styles';
      mark.textContent = styles + ' ' + plural(styles, 'стиль', 'стиля', 'стилей');
      b.querySelector('.pick__box').appendChild(mark);
    }
    b.addEventListener('click', () => (item.type === 'particle'
      ? pickSystem(b, item) : choose(b, item)));
    // Правая кнопка на системе — её меню, как в дереве систем приложения.
    if (item.type === 'particle') {
      b.addEventListener('contextmenu', (e) => systemMenu(e, item.key));
    }
    els.grid.appendChild(b);
  }
  els.grid.hidden = list.length === 0;
  showCount(list.length);
}

/** Класс предмета короткой подписью: длинный список — числом. */
function classTag(item) {
  const list = String(item.cls || '').split(',').map((c) => c.trim()).filter(Boolean);
  if (list.length === 0) return item.label ?? item.key;
  if (list.length === 1) return list[0];
  // Девять классов = «все»: перечислять их незачем, это половина косметики.
  return list.length >= 9 ? 'все классы' : list.length + ' ' + plural(
    list.length, 'класс', 'класса', 'классов');
}

/** Сколько предметов показано. Пусто — счётчик прячется, о нуле скажет note. */
function showCount(n) {
  const el = document.getElementById('cat-count');
  el.hidden = n === 0;
  el.textContent = n + ' ' + plural(n, 'предмет', 'предмета', 'предметов');
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
  els.note.textContent = 'Свои работы и моды из VPK. Предмет из списка оружия '
    + 'открывается игровым — сохранённая работа открывается отсюда.';

  const works = await showWorks();

  const open = document.createElement('button');
  open.className = 'pick pick--open';
  open.innerHTML = `<span class="pick__box"></span>
    <span class="pick__name">Открыть VPK-мод…</span>
    <span class="mono">файл с диска</span>`;
  open.addEventListener('click', pickVpkMod);
  els.grid.append(open);

  const mods = await api.modLibrary();
  for (const mod of mods) {
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
  // Счётчик строится мимо fillGrid, обновить его надо самим: иначе тут
  // висит число от прошлой категории.
  showCount(works + mods.length);
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
 * Сохранённые работы — карточками, как предметы.
 *
 * Раньше работа возвращалась молча при открытии предмета: в каталоге «Обрез»,
 * на экране — твой обрез, и вернуться к игровому нечем. Теперь список оружия
 * показывает игру, а работа открывается отсюда, осознанно.
 */
async function showWorks() {
  const list = await api.works();
  if (!list.length) return 0;

  for (const work of list) {
    const card = document.createElement('button');
    card.className = 'pick pick--work';
    card.innerHTML = `<span class="pick__box"></span>
      <span class="pick__name"></span><span class="mono"></span>`;
    card.querySelector('.pick__name').textContent = work.name;
    card.querySelector('.mono').textContent = whenSaved(work.saved_at);
    if (work.icon) {
      const img = document.createElement('img');
      img.className = 'pick__icon';
      img.loading = 'lazy';
      img.alt = '';
      img.addEventListener('error', () => img.remove());
      img.src = api.iconUrl(work.icon);
      card.querySelector('.pick__box').appendChild(img);
    }
    card.addEventListener('click', () => openWork(work));
    els.grid.append(card);
  }
  return list.length;
}

/** Когда сохранено — словами: точное время тут ничего не решает. */
function whenSaved(stamp) {
  const days = Math.floor((Date.now() / 1000 - (stamp || 0)) / 86400);
  if (days <= 0) return 'сегодня';
  if (days === 1) return 'вчера';
  return days + ' ' + plural(days, 'день', 'дня', 'дней') + ' назад';
}

/**
 * Открывает работу: тот же предмет, но с восстановленными правками.
 *
 * Ключ модели передаём явно. Из режима его выводит Python, но только у
 * оружия: у шапки модель задаётся выбором в каталоге, и без ключа работа по
 * шапке не открывалась вовсе. Мод из VPK — вообще не предмет каталога:
 * он грузится файлом, а правки к нему возвращаются следом.
 */
async function openWork(work) {
  document.querySelector('.title__name').textContent = work.name;
  document.querySelector('.title__meta').textContent = 'сохранённая работа';
  closeCat();
  say('Открываю работу…');

  if (work.mod) {
    await openMod({ name: work.name, path: work.mod });
    const back = await api.restoreWork();
    if (back.error) say(back.error);
    return;
  }

  await setMode(work.mode);
  const res = await api.loadPreview(work.mode, null, work.item_key || null,
                                    work.per_class || null, null, true);
  if (res.error) say(res.error);
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
  // Косметика при первом открытии разбирает items_game целиком — это пара
  // секунд с пустым списком на экране. Ждём четверть секунды, прежде чем
  // сказать: обычный отбор укладывается в миллисекунды, и мигать словом на
  // каждую букву поиска незачем.
  const wait = setTimeout(() => {
    const el = document.getElementById('cat-count');
    el.textContent = 'Читаю список…';
    el.hidden = false;
  }, 250);
  const list = sel.section === 'hats'
    ? await api.hats({ query: sel.query || '', tf2_class: sel.cls })
    // Поиск работает во всех разделах, а не только у косметики: поле над
    // списком одно, и «не ищет» у оружия читалось как поломка.
    : await api.items({ category: sel.category, tf2_class: sel.cls,
                        weapon_type: sel.type, query: sel.query || '' });
  clearTimeout(wait);
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
 * Перерисовывает списки на другом языке, сохраняя выбор.
 *
 * Имена предметов приходят из игры вместе с языком: сменив его в настройках,
 * человек ждёт список на новом языке, а не после перезапуска. Раздел, класс и
 * тип при этом остаются — перебрасывать его в «Оружие» было бы наказанием за
 * настройку.
 */
export async function relabel() {
  if (sel.section === 'particles') return;   // имена систем приходят из PCF
  await fillCategories();
  els.cat.value = sel.category;
  if (sel.section === 'hats') {
    await fillHatFilters();
  } else {
    if (!els.fClass.hidden) {
      fillFilters(els.fClass, await api.classes(), sel.cls, pickClass);
    }
    if (!els.fType.hidden) {
      fillFilters(els.fType, await api.weaponTypes(sel.cls), sel.type, pickType);
    }
  }
  await reload();
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
  if (name === 'diagnostics') {
    diagDlg.showModal();
    if (!document.getElementById('diag-status').textContent) {
      diagSay('Выберите собранный VPK-мод');
    }
    return false;
  }

  const было = sel.section;
  sel.section = ['hats', 'particles', 'sounds'].includes(name)
    ? name : 'weapons';
  root.dataset.section = sel.section;

  // Звуки — раздел без предмета: ни модели, ни текстур, ни каталога. Стол он
  // занимает целиком, поэтому остальную настройку разделов не проходит.
  const { openSounds, closeSounds } = await import('./sounds.js');
  if (sel.section === 'sounds') {
    if (было !== 'sounds') {
      await api.stopPreview();
      clearPreview();
      say('');
    }
    await openSounds();
    return;
  }
  closeSounds();

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

  if (name !== 'weapons') {
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
    // Имя короткое, подсказка полная: обрезать здесь по «Скрыть » значило бы
    // держать в разметке правило одного языка.
    b.textContent = f.name;
    b.title = f.tip || f.name;
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
  // Внешний вид — до всего остального: иначе первые кадры страница показывает
  // светлой и перекрашивается на глазах.
  applyLook((await api.settings()).values || {});
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
  // Ключ из data-section, а не подпись: подпись переводится.
  if (await pickSection(btn.dataset.section) === false) return;
  document.querySelectorAll('.chrome__nav .underlined')
          .forEach((b) => b.classList.remove('is-active'));
  btn.classList.add('is-active');
});
