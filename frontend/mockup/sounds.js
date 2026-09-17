// Страница звуков: какая запись что играет и чем её заменить.
//
// Звук в игре зовут не файлом, а именем записи (`Weapon_Shotgun.Single`), и
// заменяется он подстановкой своего файла по тому же пути внутри `sound/`.
// Поэтому строка списка — это запись: имя, событие, предмет и файлы. Файлов у
// записи бывает несколько (игра берёт случайный), и заменяются они все разом —
// иначе свой звук слышно через раз.
//
// Разбор скрипта и сборка живут в Python (data/sound_catalog, services/
// sound_build_service). Здесь только показ и выбор.

import * as api from './api.js';
import { toGameWav } from './audio.js';
import { chooseFile } from './util.js';

const els = {
  box: document.getElementById('sounds'),
  query: document.getElementById('snd-q'),
  tabs: document.getElementById('snd-section'),
  facets: document.getElementById('snd-facets'),
  count: document.getElementById('snd-count'),
  list: document.getElementById('snd-list'),
  note: document.getElementById('snd-note'),
  clear: document.getElementById('snd-clear'),
  name: document.getElementById('snd-name'),
  build: document.getElementById('snd-build'),
  loading: document.getElementById('snd-loading'),
  loadingText: document.querySelector('#snd-loading .loading__text'),
  audio: document.getElementById('snd-audio'),
  playing: document.getElementById('snd-playing'),
  play: document.getElementById('snd-play'),
  seek: document.getElementById('snd-seek'),
  time: document.getElementById('snd-time'),
  vol: document.getElementById('snd-vol'),
};

//: Фильтры страницы. Ключи — те же, что у `api.sounds`; пустая строка —
//: «все». Раздел — ось главная: у оружия и реплик разные события и разные
//: говорящие, поэтому смена раздела сбрасывает остальное.
const sel = { section: 'weapon', who: '', group: '', variant: '', fmt: '',
              own: false, query: '' };
//: Фасеты колонки, кроме раздела: подпись и что стоит за ключом. У оружия и
//: реплик группы — события («Выстрел», «Смерть»), у игрока и мира — типы
//: звуков («Шаги», «Музыка»), и подпись говорит то, что в списке.
const FACETS = [
  ['who', 'Класс'], ['group', 'Событие'], ['variant', 'Вариант'],
  ['fmt', 'Формат'],
];
const GROUP_TITLE = { player: 'Тип', world: 'Тип' };
//: Имя фасета на странице → имя в ответе Python. Разошлись в одном месте:
//: `format` — зарезервированное слово в старых движках.
const FACET_KEY = { fmt: 'format' };
let rows = [];
let total = 0;
let ready = false;
//: Последний ответ про фильтры: колонку перерисовываем и без запроса —
//: когда меняется число своих звуков.
let lastFacets = null;
let lastAll = null;
//: Сколько своих звуков выбрано ВСЕГО. Считать по видимым строкам нельзя: их
//: не больше четырёхсот, и выбранное пропадало из счёта от смены фильтра.
//: `pickedTotal` — записей, затронутых заменами (это же число у фасета
//: «Заменённые»), `pickedFiles` — файлов игры под замену (это содержимое VPK).
let pickedTotal = 0;
let pickedFiles = 0;
//: Строка под клавиатурным курсором: стрелки ходят по списку, пробел играет,
//: Enter просит свой файл.
let cursor = -1;
//: Отложенный перезапрос: список перерисовывается целиком, и делать это на
//: каждую букву — четыреста узлов на нажатие.
let typing = null;
//: Один проигрыватель на страницу: два звука разом — это каша, а не проверка.
const player = els.audio;
//: Что играет сейчас — по нему подсвечивается строка списка.
let playingKey = '';
//: Пока полосу тянут, время в неё не пишем: иначе ползунок вырывается из-под
//: пальца на каждом кадре звука.
let seeking = false;
//: Номер последнего запроса списка. Фильтры и поиск шлют их подряд, а отвечает
//: Python не по порядку: без этого ответ на «a» мог лечь поверх ответа на «ab».
let turn = 0;

/** Открывает раздел: подписки один раз, список каждый вход. */
export async function openSounds() {
  els.box.hidden = false;
  if (!ready) {
    ready = true;
    // Первый вход разбирает все звуковые скрипты игры — десять тысяч записей,
    // пара секунд. Пустой список без единого слова выглядит поломкой.
    busy('Читаю звуки игры…');
    // Громкость — из общего конфига. Своим запросом, а не через applyLook:
    // раздел грузится по требованию (`import()` в catalog.js), и тянуть его
    // в стартовый набор модулей ради одного числа не стоит.
    setVolume((await api.settings()).values.sound_volume);
    els.query.addEventListener('input', () => {
      sel.query = els.query.value.trim();
      clearTimeout(typing);
      typing = setTimeout(reload, 150);
    });
    els.tabs.addEventListener('click', onTab);
    els.facets.addEventListener('click', onFacet);
    els.build.addEventListener('click', build);
    els.clear.addEventListener('click', clearAll);
    els.list.addEventListener('click', onClick);
    bindDrop();
    bindKeys();
    bindPlayer();
  }
  await reload();
}

/** Кружок вместо списка: страница занята. Пустой текст — вернуть список. */
function busy(text) {
  els.loadingText.textContent = text;
  els.loading.hidden = !text;
  els.list.hidden = Boolean(text);
  // Счётчик относится к списку, которого сейчас нет.
  if (text) els.count.hidden = true;
}

function onTab(e) {
  const btn = e.target.closest('[data-key]');
  if (!btn || btn.dataset.key === sel.section) return;
  sel.section = btn.dataset.key;
  // События прошлого раздела в новом не живут: у оружия не бывает боли, у
  // реплик — перезарядки. Поиск и «заменённые» — общие, их оставляем.
  Object.assign(sel, { who: '', group: '', variant: '', fmt: '' });
  reload();
}

function onFacet(e) {
  const btn = e.target.closest('[data-facet]');
  if (!btn) return;
  const { facet, key } = btn.dataset;
  if (facet === 'own') sel.own = !sel.own;
  else sel[facet] = sel[facet] === key ? '' : key;
  reload();
}

/**
 * Разделы в шапке и колонка фасетов — по ответу Python.
 *
 * Перерисовываем целиком: значения и счётчики зависят от остальных
 * фильтров, и держать их в узлах значит гнаться за ответом. Фасет с одним
 * значением не показываем — выбирать там не из чего.
 */
function showFilters(facets, all) {
  els.tabs.replaceChildren(...facets.section.map((opt) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'sounds__tab' + (opt.key === sel.section ? ' is-active' : '')
      + (opt.count ? '' : ' is-empty');
    b.dataset.key = opt.key;
    b.append(opt.name, count(opt.count));
    return b;
  }));

  const blocks = [];
  for (const [facet, label] of FACETS) {
    const title = facet === 'group' ? (GROUP_TITLE[sel.section] || label) : label;
    const key = FACET_KEY[facet] || facet;
    const opts = facets[key] || [];
    if (opts.length < 2) continue;
    blocks.push(block(title, [
      option(facet, '', 'Все', all[key], !sel[facet]),
      ...opts.map((o) => option(facet, o.key, o.name, o.count,
                                sel[facet] === o.key)),
    ]));
  }
  // Свои звуки — не свойство записи, а её состояние; но искать их по списку
  // из десяти тысяч без такого фильтра нечем.
  if (pickedTotal || sel.own) {
    blocks.push(block('Свои', [
      option('own', 'own', 'Заменённые', pickedTotal, sel.own),
    ]));
  }
  els.facets.replaceChildren(...blocks);
}

/**
 * Куда уйти, если здесь пусто: разделы, где запрос что-то нашёл.
 *
 * Шаги лежат в «Мире», а ищут их в «Игроке»; насмешки — и в «Репликах», и в
 * «Игроке». Вкладка с числом это уже говорит, но тихо — здесь то же самое
 * словами и кнопкой, прямо там, куда смотрит человек.
 */
function elsewhere(sections) {
  const other = sections.filter((o) => o.count && o.key !== sel.section);
  if (!other.length) return [];
  const out = [document.createTextNode(' — есть в разделе ')];
  other.forEach((o, i) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'textbtn textbtn--sm';
    b.dataset.key = o.key;
    b.append(o.name, ' ', count(o.count));
    b.addEventListener('click', () => {
      sel.section = o.key;
      Object.assign(sel, { who: '', group: '', variant: '', fmt: '' });
      reload();
    });
    if (i) out.push(', ');
    out.push(b);
  });
  return out;
}

/** Опечатка: «scatergun» — предлагаем «scattergun» кнопкой в строку поиска. */
function maybe(words) {
  if (!words.length) return [];
  const out = [document.createTextNode(' — возможно: ')];
  words.forEach((word, i) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'textbtn textbtn--sm';
    b.textContent = word;
    b.addEventListener('click', () => {
      els.query.value = word;
      sel.query = word;
      reload();
    });
    if (i) out.push(', ');
    out.push(b);
  });
  return out;
}

function block(title, options) {
  const box = document.createElement('div');
  box.className = 'facet';
  const head = document.createElement('span');
  head.className = 'label';
  head.textContent = title;
  box.append(head, ...options);
  return box;
}

function option(facet, key, name, n, active) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'facet__opt' + (active ? ' is-active' : '');
  b.dataset.facet = facet;
  b.dataset.key = key;
  const label = document.createElement('span');
  label.textContent = name;
  b.append(label, count(n));
  return b;
}

function count(n) {
  const b = document.createElement('b');
  b.textContent = String(n);
  return b;
}

/** Ставит громкость и ползунок под неё. */
function setVolume(percent) {
  const n = Number(percent);
  // Значения нет — полная громкость: молчащий плеер читается как поломка,
  // а не как настройка, и человек полезет искать её причину в звуке.
  els.vol.value = String(Number.isFinite(n) ? Math.min(100, Math.max(0, n)) : 100);
  player.volume = Number(els.vol.value) / 100;
}

/** Свой пульт вместо браузерного: движок тот же <audio>, вид наш. */
function bindPlayer() {
  els.play.addEventListener('click', () => {
    if (!player.src) return;
    if (player.paused) player.play().catch(() => {});
    else player.pause();
  });
  els.seek.addEventListener('pointerdown', () => { seeking = true; });
  els.seek.addEventListener('change', () => {
    seeking = false;
    if (player.duration) player.currentTime = share() * player.duration;
  });
  els.seek.addEventListener('input', () => {
    if (player.duration) showTime(share() * player.duration, player.duration);
  });
  els.vol.addEventListener('input', () => {
    player.volume = Number(els.vol.value) / 100;
  });
  // Запоминаем на ОТПУСКАНИИ (`change`), а не на каждом шаге ползунка: одно
  // движение мыши даёт полсотни `input`, и конфиг переписывался бы полсотни
  // раз. Громкость общая с окном настроек — она в том же конфиге.
  els.vol.addEventListener('change',
    () => api.setUiState('sound_volume', Number(els.vol.value)));
  player.addEventListener('timeupdate', tick);
  player.addEventListener('durationchange', tick);
  player.addEventListener('play', showPlaying);
  player.addEventListener('pause', showPlaying);
  player.addEventListener('ended', showPlaying);
}

const share = () => Number(els.seek.value) / Number(els.seek.max);

function tick() {
  const total = Number.isFinite(player.duration) ? player.duration : 0;
  if (!seeking) {
    els.seek.value = total
      ? String(Math.round((player.currentTime / total) * els.seek.max)) : '0';
    showTime(player.currentTime, total);
  }
  // Заполненную часть полосы рисует градиент: у input type=range своего
  // «пройденного» куска нет ни в одном браузере.
  els.seek.style.setProperty('--done', `${share() * 100}%`);
}

function showTime(now, total) {
  els.time.textContent = `${clock(now)} / ${clock(total)}`;
}

function clock(sec) {
  if (!Number.isFinite(sec)) return '0:00';
  const whole = Math.floor(sec);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}

/** Состояние кнопки и подсветка строки, которая звучит. */
function showPlaying() {
  const on = !player.paused && !player.ended;
  els.play.classList.toggle('is-playing', on);
  els.play.setAttribute('aria-label', on ? 'Пауза' : 'Играть');
  els.list.querySelectorAll('.snd.is-playing')
          .forEach((b) => b.classList.remove('is-playing'));
  if (!on || !playingKey) return;
  const box = els.list.querySelector(`[data-key="${CSS.escape(playingKey)}"]`);
  if (box) box.classList.add('is-playing');
}

export function closeSounds() {
  els.box.hidden = true;
  player.pause();
}

/** Запрашивает список заново: с начала, если `offset` не задан. */
async function reload(offset = 0) {
  const mine = ++turn;
  // Отбор по десяти тысячам записей — сорок миллисекунд, и мигать словом
  // «ищу» на каждый чих незачем. Показываем, только если задумались.
  // Первый вход уже показал «Читаю звуки игры…» — его не перебиваем.
  const wait = setTimeout(() => { if (els.loading.hidden) busy('Ищу…'); }, 250);
  const res = await api.sounds({ ...sel, offset });
  clearTimeout(wait);
  if (mine !== turn) return;      // запрос обогнали — рисует тот, кто свежее
  busy('');
  pickedTotal = res.picked;
  pickedFiles = res.files;
  total = res.total;
  cursor = -1;
  [lastFacets, lastAll] = [res.facets, res.all];
  showFilters(res.facets, res.all);
  // Пустой список сам по себе ничего не объясняет: непонятно, сузил ли ты
  // фильтр до нуля или раздел не прочитался вовсе.
  if (!res.loaded) {
    els.count.textContent = 'Раздел пуст: звуковые скрипты игры не прочитались';
  } else if (!total) {
    els.count.replaceChildren('Под этими фильтрами ничего нет',
                              ...elsewhere(res.facets.section),
                              ...maybe(res.suggest || []));
  } else {
    els.count.textContent = `Записей: ${total}`;
  }
  els.count.hidden = false;
  if (!offset) {
    rows = [];
    els.list.innerHTML = '';
  } else {
    els.list.querySelector('.sounds__more')?.remove();
  }
  rows.push(...res.rows);
  els.list.append(...res.rows.map(card));
  // Хвост: сколько ещё за кадром и кнопка за следующей порцией.
  if (rows.length < total) {
    const more = document.createElement('div');
    more.className = 'sounds__more';
    const b = document.createElement('button');
    b.className = 'textbtn';
    b.type = 'button';
    b.textContent = `Показать ещё ${Math.min(res.rows.length || 400, total - rows.length)}`;
    b.addEventListener('click', () => reload(rows.length));
    const rest = document.createElement('span');
    rest.className = 'mono';
    rest.textContent = `${rows.length} из ${total}`;
    more.append(b, rest);
    els.list.append(more);
  }
  showPicked();
}

/** Строка списка. Ключ записи держим в data-* — подпись переводится. */
function card(row) {
  const box = document.createElement('div');
  box.className = 'snd';
  box.dataset.key = row.name;
  box.classList.toggle('is-own', Boolean(row.own));

  const many = row.waves.length > 1;
  const files = many
    ? `${row.waves[0]} и ещё ${row.waves.length - 1}`
    : (row.waves[0] || '');
  box.innerHTML = `
    <img class="snd__icon" alt="" loading="lazy">
    <div class="snd__what">
      <span><b class="snd__title"></b><span class="snd__mvm" hidden>MvM</span><span class="snd__own" hidden>Заменён</span><span class="snd__own snd__part" hidden>Частично</span></span>
      <span class="snd__name mono"></span>
    </div>
    <span class="snd__group"></span>
    <button class="snd__file mono" type="button" data-act="open"><span class="snd__shared" hidden></span></button>
    <div class="snd__acts">
      <button class="textbtn textbtn--sm" data-act="play">Прослушать</button>
      <button class="textbtn textbtn--sm" data-act="orig" hidden>Оригинал</button>
      <button class="textbtn textbtn--sm" data-act="save">Скачать</button>
      <button class="textbtn textbtn--sm" data-act="own">Свой файл</button>
      <button class="textbtn textbtn--sm" data-act="drop" hidden>Убрать</button>
    </div>`;
  const icon = box.querySelector('.snd__icon');
  // Своей картинки может не быть у всей игры — тогда прячем, а не показываем
  // сломанный значок.
  if (row.icon) icon.src = api.iconUrl(row.icon);
  else icon.hidden = true;
  icon.addEventListener('error', () => { icon.hidden = true; });
  box.querySelector('.snd__title').textContent = row.title;
  box.querySelector('.snd__mvm').hidden = !row.mvm;
  box.querySelector('.snd__name').textContent = row.name;
  // В столбце — группа записи: событие и так стоит в имени строкой ниже, а
  // в списке «все события» группа говорит, что это за звук.
  box.querySelector('.snd__group').textContent = row.group_name;
  const cell = box.querySelector('.snd__file');
  cell.prepend(files);
  // Общий файл: игра подменяет файл, и заменив его здесь, человек заменил
  // его и у остальных записей. Скрывать это нельзя — скажем числом, а кто
  // именно, покажет раскрытие.
  const shared = cell.querySelector('.snd__shared');
  shared.hidden = !row.shared_count;
  if (row.shared_count) shared.textContent = `общий для ${row.shared_count}`;
  // Разворывать есть что, если файлов несколько или файл общий.
  cell.disabled = !(many || row.shared_count);
  cell.classList.toggle('is-many', many || Boolean(row.shared_count));
  markOwn(box, row);
  return box;
}

/**
 * Отмечает строку как заменённую: полоска, слово и две кнопки.
 *
 * Заменённую запись надо с чем-то сравнивать: «Прослушать» играет свой файл, и
 * без «Оригинала» исходный звук становится недоступен. Заменена часть файлов
 * — тоже отметка, но словом «Частично».
 */
function markOwn(box, { own, partial }) {
  const any = Boolean(own || partial);
  box.classList.toggle('is-own', any);
  for (const act of ['drop', 'orig']) {
    box.querySelector(`[data-act="${act}"]`).hidden = !any;
  }
  box.querySelector('.snd__own:not(.snd__part)').hidden = !own;
  box.querySelector('.snd__part').hidden = !(partial && !own);
}

/**
 * Разносит ответ Python по строкам: у общего файла хозяев несколько, и
 * заменив его у биты, человек заменил и у бутылки — её строка обязана это
 * показать сразу, а не после перезагрузки.
 */
function applyStates(affected) {
  for (const [name, state] of Object.entries(affected || {})) {
    const row = rows.find((r) => r.name === name);
    if (!row) continue;
    Object.assign(row, state);
    const box = els.list.querySelector(`[data-key="${CSS.escape(name)}"]`);
    if (!box) continue;
    markOwn(box, row);
    const open = box.nextElementSibling;
    if (open && open.classList.contains('snd__files')) {
      open.querySelectorAll('.snd__file-row').forEach((one) => {
        markFile(one, row.own_waves[one.dataset.wave] || '');
      });
    }
  }
}

async function onClick(e) {
  const btn = e.target.closest('[data-act]');
  const box = e.target.closest('.snd');
  if (!box) return;
  const row = rows.find((r) => r.name === box.dataset.key);
  if (!row) return;
  setCursor(rows.indexOf(row));
  if (!btn) {
    // Щелчок по пустому месту строки — берём клавиатуру себе.
    els.list.focus();
    return;
  }

  if (btn.dataset.act === 'open') return toggleFiles(row, box);
  if (btn.dataset.act === 'play') return play(row);
  if (btn.dataset.act === 'orig') return play(row, true);
  if (btn.dataset.act === 'save') return save(row);
  if (btn.dataset.act === 'drop') return setOwn(row, null);
  return ownFor(row);
}

/** Просит свой файл на запись: из диалога или уже брошенный на строку. */
async function ownFor(row, dropped = null) {
  const file = await pickSound(row.waves, dropped);
  if (file) await setOwn(row, await api.upload(file));
}

/** Бросить файл на строку — то же, что «Свой файл», без диалога. */
function bindDrop() {
  const target = (e) => e.target.closest('.snd__file-row, .snd');
  let lit = null;
  const light = (el) => {
    if (lit && lit !== el) lit.classList.remove('is-drop');
    lit = el;
    if (el) el.classList.add('is-drop');
  };
  els.list.addEventListener('dragover', (e) => {
    const el = target(e);
    if (!el) return;
    e.preventDefault();
    light(el);
  });
  els.list.addEventListener('dragleave', (e) => {
    if (!els.list.contains(e.relatedTarget)) light(null);
  });
  els.list.addEventListener('drop', (e) => {
    const el = target(e);
    light(null);
    const file = e.dataTransfer.files[0];
    if (!el || !file) return;
    e.preventDefault();
    if (el.classList.contains('snd__file-row')) {
      const box = el.closest('.snd__files').previousElementSibling;
      const row = rows.find((r) => r.name === box.dataset.key);
      if (row) ownForFile(row, el, el.dataset.wave, file);
      return;
    }
    const row = rows.find((r) => r.name === el.dataset.key);
    if (row) ownFor(row, file);
  });
}

/** Клавиатура: стрелки — по строкам, пробел — играть, Enter — свой файл,
 *  Delete — убрать. Из поиска стрелка вниз уводит в список. */
function bindKeys() {
  els.query.addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowDown' || !rows.length) return;
    e.preventDefault();
    els.list.focus();
    setCursor(0);
  });
  els.list.addEventListener('keydown', (e) => {
    // Кнопки внутри строк живут своей клавиатурой: пробел на них — нажатие.
    if (e.target !== els.list) return;
    const row = rows[cursor];
    const acts = {
      ArrowDown: () => setCursor(Math.min(rows.length - 1, cursor + 1)),
      ArrowUp: () => setCursor(Math.max(0, cursor - 1)),
      Home: () => setCursor(0),
      End: () => setCursor(rows.length - 1),
      ' ': () => row && play(row),
      Enter: () => row && ownFor(row),
      Delete: () => row && (row.own || row.partial) && setOwn(row, null),
      Escape: () => els.query.focus(),
    };
    const act = acts[e.key];
    if (!act) return;
    e.preventDefault();
    act();
  });
}

function setCursor(index) {
  els.list.querySelectorAll('.snd.is-cursor')
          .forEach((b) => b.classList.remove('is-cursor'));
  cursor = index;
  const row = rows[cursor];
  if (!row) return;
  const box = els.list.querySelector(`[data-key="${CSS.escape(row.name)}"]`);
  if (!box) return;
  box.classList.add('is-cursor');
  box.scrollIntoView({ block: 'nearest' });
}

/**
 * Спрашивает свой файл и приводит его к тому, что игра здесь играет.
 *
 * Читалку движок выбирает по расширению из записи, а не по содержимому файла:
 * WAV под именем `.mp3` — это тишина. В WAV браузер переводит что угодно
 * (см. audio.js), обратно в MP3 — ничего, поэтому записи с MP3 берут только
 * готовый MP3.
 *
 * Возвращает null, если человек передумал или файл не разобрать.
 */
async function pickSound(waves, given = null) {
  const file = given || await chooseFile('audio/*');
  if (!file) return null;
  if (!waves.some((w) => w.toLowerCase().endsWith('.wav'))) {
    if (/\.mp3$/i.test(file.name)) return file;
    els.note.textContent =
      'Игра ждёт здесь MP3, а перекодировать в MP3 браузер не умеет';
    return null;
  }
  // Приводим ВСЕГДА, даже готовый WAV: 48 кГц, 24 бита и стерео игра молча не
  // проигрывает, и на глаз такой файл от годного не отличить.
  els.note.textContent = 'Перекодирую звук…';
  try {
    return await toGameWav(file);
  } catch (err) {
    els.note.textContent = `Не разобрать этот звук: ${err.message || err}`;
    return null;
  }
}

/** Свой файл, если он выбран, иначе игровой. `game` — всегда игровой. */
function play(row, game = false) {
  const wave = row.waves[0];
  playFile(row, wave, game ? '' : (row.own_waves[wave] || ''));
}

/**
 * Жалоба на формат — но только настоящая.
 *
 * Смена `src` обрывает предыдущий `play()` отказом AbortError, и по двум
 * быстрым нажатиям страница ругалась на совершенно исправный звук. Формат
 * бывает такой, что браузер его не берёт (в игре это ADPCM), и молчать про
 * это нельзя: человек решит, что сломалась кнопка.
 */
function cannotPlay(err) {
  if (err && err.name === 'AbortError') return;
  els.note.textContent = 'Этот файл браузер проиграть не может';
}

/**
 * Раскрывает файлы записи.
 *
 * У 1274 записей файлов несколько: игра берёт случайный, чтобы звук не
 * приедался. Обычно это варианты одного и того же (`ric1…ric5`), но иногда —
 * разные фразы, и тогда менять надо не все разом, а одну.
 */
function toggleFiles(row, box) {
  const open = box.nextElementSibling;
  if (open && open.classList.contains('snd__files')) {
    open.remove();
    return;
  }
  const list = document.createElement('div');
  list.className = 'snd__files';
  // Как игра играет запись: свой файл зазвучит с теми же каналом,
  // громкостью и уровнем, и знать их полезно до того, как он зазвучал.
  const props = [row.channel, row.level,
                 row.volume && `volume ${row.volume}`,
                 row.pitch && `pitch ${row.pitch}`].filter(Boolean);
  if (props.length) {
    const head = document.createElement('div');
    head.className = 'snd__props mono';
    head.textContent = props.join(' · ');
    list.append(head);
  }
  row.waves.forEach((wave, i) => {
    const one = document.createElement('div');
    one.className = 'snd__file-row';
    one.dataset.wave = wave;
    one.innerHTML = `
      <div class="snd__file-what">
        <span class="snd__file-name mono"></span>
        <span class="snd__file-also mono" hidden></span>
      </div>
      <div class="snd__acts">
        <button class="textbtn textbtn--sm" data-file="play">Прослушать</button>
        <button class="textbtn textbtn--sm" data-file="save">Скачать</button>
        <button class="textbtn textbtn--sm" data-file="own">Свой файл</button>
        <button class="textbtn textbtn--sm" data-file="drop">Убрать</button>
      </div>`;
    one.querySelector('.snd__file-name').textContent = wave;
    // Дубль, свёрнутый в запись, — под именем записи игры; общий файл — с
    // теми, у кого он ещё стоит.
    const notes = [];
    if (row.takes[i] && row.takes[i] !== row.name) notes.push(row.takes[i]);
    if (row.shared[wave]) notes.push(`также у: ${row.shared[wave].join(', ')}`);
    const also = one.querySelector('.snd__file-also');
    also.hidden = !notes.length;
    also.textContent = notes.join(' · ');
    markFile(one, row.own_waves[wave] || '');
    list.append(one);
  });
  list.addEventListener('click', (e) => onFile(e, row));
  box.after(list);
}

function markFile(one, own) {
  one.classList.toggle('is-own', Boolean(own));
  one.querySelector('[data-file="drop"]').hidden = !own;
}

async function onFile(e, row) {
  const btn = e.target.closest('[data-file]');
  const one = e.target.closest('.snd__file-row');
  if (!btn || !one) return;
  const wave = one.dataset.wave;
  const act = btn.dataset.file;

  if (act === 'play') {
    // Свой файл этого варианта, если он выбран, иначе игровой.
    const own = row.own_waves[wave] || '';
    return playFile(row, wave, own);
  }
  if (act === 'save') {
    const res = await api.saveSound(row.name, wave);
    els.note.textContent = res.error || `Сохранено: ${res.path}`;
    return;
  }
  if (act === 'own') return ownForFile(row, one, wave);
  return setFile(row, one, wave, null);
}

/** Свой файл на ОДИН файл записи: из диалога или брошенный на строку. */
async function ownForFile(row, one, wave, dropped = null) {
  const file = await pickSound([wave], dropped);
  if (!file) return;
  await setFile(row, one, wave, await api.upload(file));
}

async function setFile(row, one, wave, path) {
  const res = await api.setSound(row.name, path, wave);
  if (res.error) {
    els.note.textContent = res.error;
    return;
  }
  pickedTotal = res.total;
  pickedFiles = res.files;
  applyStates(res.affected);
  markFile(one, row.own_waves[wave] || '');
  showPicked();
  refreshIfOwnFilter();
}

/** Ставит на проигрывание один файл: свой, если он выбран, иначе игровой. */
function playFile(row, wave, own) {
  player.pause();
  playingKey = row.name;
  player.src = own ? api.fileUrl(own) : api.soundUrl(wave);
  els.playing.textContent = own ? `${wave} — свой файл` : wave;
  player.play().catch(cannotPlay);
}

/** Кладёт игровой звук в папку экспорта: чтобы переделать, его надо достать. */
async function save(row) {
  const res = await api.saveSound(row.name);
  if (res.error) {
    els.note.textContent = res.error;
    return;
  }
  // У записи бывает несколько файлов — игра берёт случайный, и переделывать
  // обычно надо все.
  els.note.textContent = res.files > 1
    ? `Сохранено файлов: ${res.files}, рядом с ${res.path}`
    : `Сохранено: ${res.path}`;
}

async function setOwn(row, path) {
  const res = await api.setSound(row.name, path);
  if (res.error) {
    els.note.textContent = res.error;
    return;
  }
  pickedTotal = res.total;
  pickedFiles = res.files;
  applyStates(res.affected);
  showPicked();
  // У части записей файлы разных форматов вперемешку: свой ложится только
  // на совпавшие, и про остальные надо сказать, а не молчать.
  if (res.skipped) {
    els.note.textContent =
      `Файлов другого формата осталось игровыми: ${res.skipped}`;
  }
  refreshIfOwnFilter();
}

function showPicked() {
  els.note.textContent = pickedFiles
    ? `Своих файлов: ${pickedFiles}` : 'Своих звуков нет';
  els.build.disabled = !pickedFiles;
  els.clear.hidden = !pickedFiles;
  // Счётчик «заменённых» в колонке — тот же pickedTotal.
  if (lastFacets) showFilters(lastFacets, lastAll);
}

/** Снять все свои звуки разом — без перебора по строкам. */
async function clearAll() {
  const res = await api.clearSounds();
  pickedTotal = res.total;
  pickedFiles = res.files;
  showPicked();
  // Состояние строк проще перечитать, чем гасить по одной.
  reload();
}

/** После выбора или снятия своего файла под фильтром «заменённые» список
 *  устарел: снятая строка в нём уже не живёт. */
function refreshIfOwnFilter() {
  if (sel.own) reload();
}

async function build() {
  els.note.textContent = 'Сборка…';
  const res = await api.buildSounds(els.name.value.trim());
  if (res.error) {
    els.note.textContent = res.error;
    return;
  }
  els.note.textContent = `Готово: ${res.files} файлов в ${res.path}`;
}
