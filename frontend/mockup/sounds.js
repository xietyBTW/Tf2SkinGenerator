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
import { fillFilters } from './catalog.js';
import { chooseFile } from './util.js';

const els = {
  box: document.getElementById('sounds'),
  query: document.getElementById('snd-q'),
  section: document.getElementById('snd-section'),
  family: document.getElementById('snd-family'),
  cls: document.getElementById('snd-class'),
  count: document.getElementById('snd-count'),
  list: document.getElementById('snd-list'),
  note: document.getElementById('snd-note'),
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

const sel = { section: 'weapon', family: null, cls: null, query: '' };
let rows = [];
let ready = false;
let sections = [];
let classList = [];
//: Сколько своих звуков выбрано ВСЕГО. Считать по видимым строкам нельзя: их
//: не больше четырёхсот, и выбранное пропадало из счёта от смены фильтра.
let pickedTotal = 0;
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

/** Открывает раздел: фильтры один раз, список каждый вход. */
export async function openSounds() {
  els.box.hidden = false;
  if (!ready) {
    ready = true;
    // Первый вход разбирает все звуковые скрипты игры — десять тысяч записей,
    // пара секунд. Пустой список без единого слова выглядит поломкой.
    busy('Читаю звуки игры…');
    sections = await api.soundSections();
    classList = await api.classes();
    // Громкость — из общего конфига. Своим запросом, а не через applyLook:
    // раздел грузится по требованию (`import()` в catalog.js), и тянуть его
    // в стартовый набор модулей ради одного числа не стоит.
    setVolume((await api.settings()).values.sound_volume);
    await showFilters();
    els.query.addEventListener('input', () => {
      sel.query = els.query.value.trim();
      clearTimeout(typing);
      typing = setTimeout(reload, 150);
    });
    els.build.addEventListener('click', build);
    els.list.addEventListener('click', onClick);
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

/** Три ряда кнопок. Перерисовываем целиком: выбранную надо подсветить, а
 *  список событий у каждого раздела свой — у оружия не бывает боли, у реплик
 *  перезарядки. */
async function showFilters() {
  fillFilters(els.section, sections, sel.section, async (key) => {
    sel.section = key;
    sel.family = null;          // событие прошлого раздела в новом не живёт
    await showFilters();
    reload();
  });
  fillFilters(els.family, await api.soundFamilies(sel.section), sel.family,
              async (key) => {
                sel.family = key;
                await showFilters();
                reload();
              });
  fillFilters(els.cls, classList, sel.cls, async (key) => {
    sel.cls = key;
    await showFilters();
    reload();
  });
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

async function reload() {
  const mine = ++turn;
  // Отбор по десяти тысячам записей — сорок миллисекунд, и мигать словом
  // «ищу» на каждый чих незачем. Показываем, только если задумались.
  const wait = setTimeout(() => busy('Ищу…'), 250);
  const res = await api.sounds(sel.family || '', sel.cls || '', sel.query,
                               sel.section || '');
  clearTimeout(wait);
  if (mine !== turn) return;      // запрос обогнали — рисует тот, кто свежее
  busy('');
  rows = res.rows;
  pickedTotal = res.picked;
  // Записей в игре десять тысяч: рисуем первые четыреста, а про остальные
  // честно говорим — иначе список сам себе мешает.
  // Пустой список сам по себе ничего не объясняет: непонятно, сузил ли ты
  // фильтр до нуля или раздел не прочитался вовсе.
  if (!res.total) {
    els.count.textContent = res.section
      ? 'Под этими фильтрами ничего нет'
      : 'Раздел пуст: звуковые скрипты игры не прочитались';
  } else if (res.total > rows.length) {
    els.count.textContent =
      `Записей: ${rows.length} из ${res.total} — уточните фильтр`;
  } else {
    els.count.textContent = `Записей: ${res.total}`;
  }
  els.count.hidden = false;
  els.list.innerHTML = '';
  els.list.append(...rows.map(card));
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
      <span><b class="snd__title"></b><span class="snd__own" hidden>Заменён</span></span>
      <span class="snd__name mono"></span>
    </div>
    <span class="snd__event"></span>
    <button class="snd__file mono" type="button" data-act="open"></button>
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
  box.querySelector('.snd__name').textContent = row.name;
  // В столбце — само событие, а не семья: семью человек и так выбрал
  // кнопкой, а `PainSevere01` против `PainSharp02` только тут и видно.
  box.querySelector('.snd__event').textContent = row.event || row.family_name;
  const cell = box.querySelector('.snd__file');
  cell.textContent = files;
  // Разворачивать нечего, если файл один: у 9446 записей из 10720 это так.
  cell.disabled = !many;
  cell.classList.toggle('is-many', many);
  markOwn(box, row.own);
  return box;
}

/**
 * Отмечает строку как заменённую: полоска, слово и две кнопки.
 *
 * Заменённую запись надо с чем-то сравнивать: «Прослушать» играет свой файл, и
 * без «Оригинала» исходный звук становится недоступен.
 */
function markOwn(box, own) {
  box.classList.toggle('is-own', Boolean(own));
  for (const act of ['drop', 'orig']) {
    box.querySelector(`[data-act="${act}"]`).hidden = !own;
  }
  box.querySelector('.snd__own').hidden = !own;
}

async function onClick(e) {
  const btn = e.target.closest('[data-act]');
  const box = e.target.closest('.snd');
  if (!btn || !box) return;
  const row = rows.find((r) => r.name === box.dataset.key);
  if (!row) return;

  if (btn.dataset.act === 'open') return toggleFiles(row, box);
  if (btn.dataset.act === 'play') return play(row);
  if (btn.dataset.act === 'orig') return play(row, true);
  if (btn.dataset.act === 'save') return save(row);
  if (btn.dataset.act === 'drop') return setOwn(row, null);
  const file = await pickSound(row.waves);
  if (file) await setOwn(row, await api.upload(file));
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
async function pickSound(waves) {
  const file = await chooseFile('audio/*');
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
  playFile(row, row.waves[0], game ? '' : row.own);
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
  for (const wave of row.waves) {
    const one = document.createElement('div');
    one.className = 'snd__file-row';
    one.dataset.wave = wave;
    one.innerHTML = `
      <span class="snd__file-name mono"></span>
      <div class="snd__acts">
        <button class="textbtn textbtn--sm" data-file="play">Прослушать</button>
        <button class="textbtn textbtn--sm" data-file="save">Скачать</button>
        <button class="textbtn textbtn--sm" data-file="own">Свой файл</button>
        <button class="textbtn textbtn--sm" data-file="drop">Убрать</button>
      </div>`;
    one.querySelector('.snd__file-name').textContent = wave;
    markFile(one, row.own_waves[wave] || '');
    list.append(one);
  }
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
  let path = null;
  if (act === 'own') {
    const file = await pickSound([wave]);
    if (!file) return;
    path = await api.upload(file);
  }
  const res = await api.setSound(row.name, path, wave);
  if (res.error) {
    els.note.textContent = res.error;
    return;
  }
  if (res.own) row.own_waves[wave] = res.own;
  else delete row.own_waves[wave];
  pickedTotal = res.total;
  markFile(one, res.own);
  showPicked();
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
  row.own = res.own;
  pickedTotal = res.total;
  const box = els.list.querySelector(`[data-key="${CSS.escape(row.name)}"]`);
  if (box) markOwn(box, row.own);
  showPicked();
}

function showPicked() {
  els.note.textContent = pickedTotal
    ? `Своих звуков: ${pickedTotal}` : 'Своих звуков нет';
  els.build.disabled = !pickedTotal;
}

async function build() {
  els.note.textContent = 'Сборка…';
  const res = await api.buildSounds(els.name.value.trim());
  if (res.error) {
    els.note.textContent = res.error;
    return;
  }
  // У части записей файлы разных форматов вперемешку: свой ложится только на
  // совпавшие, и про остальные надо сказать, а не молчать.
  els.note.textContent = res.skipped
    ? `Готово: ${res.files} файлов в ${res.path}; ${res.skipped} другого формата остались игровыми`
    : `Готово: ${res.files} файлов в ${res.path}`;
}
