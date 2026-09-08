/*
 * Превью предмета: что приехало от воркера и как это показано.
 *
 * Модель приходит не ответом на запрос, а потоком событий: сначала прогресс,
 * потом готовая модель, потом материалы. Поэтому здесь только запуск и показ,
 * а разбор событий — в events.js.
 *
 * У ОДНОМАТЕРИАЛЬНОЙ модели текстура приезжает прямо в model_ready и события
 * materials не будет вовсе: один кадр — не особый случай, а тот же альбом
 * длиной в единицу.
 */

import * as api from './api.js';
import { ask } from './ask.js';
import { say, sayBusy, stage, viewer, withViewer } from './stage.js';
import { root, work } from './layout.js';
import { bindAlbum, goTo, SINGLE_TEX } from './album.js';
import { modeControls, restoreBadges } from './controls.js';
import { closeParts, bindParts } from './parts.js';
import { updateDockSummary } from './build.js';

// ═══════════════════════════════════════════════════════════════════════════
// Данные из Python
// ═══════════════════════════════════════════════════════════════════════════
// Каталог, фильтры и правила видимости приходят из src/app/api.py. Здесь
// только отрисовка: ни списков предметов, ни условий «что показывать» в
// представлении быть не должно — иначе они разъедутся с приложением.

// ── Загрузка превью ──────────────────────────────────────────────────────
// Модель приезжает не ответом на запрос, а потоком событий: сначала прогресс,
// потом готовая модель, потом материалы. Поэтому здесь только запуск, а
// показывает результат обработчик событий ниже.

//: Запросы состояния идут пачками (materials, blu_materials, australium
//: приходят подряд) — склеиваем их в один, иначе альбом перерисуется трижды.
export let viewTimer = null;

export function refreshView() {
  clearTimeout(viewTimer);
  viewTimer = setTimeout(async () => {
    applyView(await api.viewState());
  }, 80);
}

/** Покласcовые модели шапки: у стилевой они в стиле, у обычной — в предмете. */
export function hatModels(item, index) {
  if (!item) return null;
  const style = ((item.styles || [])[index] || {}).per_class;
  const own = item.per_class;
  const models = (style && Object.keys(style).length) ? style : own;
  return (models && Object.keys(models).length) ? models : null;
}

/**
 * Классы мультиклассовой шапки.
 *
 * У каждого класса своя модель, и мод под все девять весит вдевятеро. По
 * умолчанию отмечены все — как в приложении; снятые в сборку не попадут.
 */
export function showHatClasses(item) {
  const bar = document.getElementById('hatclasses');
  const classes = Object.keys((item && item.per_class) || {});
  // Смена стиля обычно не меняет набор классов — тогда кнопки не трогаем,
  // иначе выбор человека сбрасывался бы при каждом переключении стиля.
  const shown = [...bar.querySelectorAll('.tag')].map((b) => b.dataset.hatClass);
  if (shown.length && shown.join() === classes.join()) return;

  bar.querySelectorAll('.tag').forEach((b) => b.remove());
  bar.hidden = classes.length < 2;
  if (bar.hidden) return;

  for (const cls of classes) {
    const b = document.createElement('button');
    b.className = 'tag is-active';
    b.dataset.hatClass = cls;
    b.textContent = cls;
    b.addEventListener('click', () => {
      b.classList.toggle('is-active');
      // Снять все — значит не собрать ничего; такой выбор не принимаем.
      if (!bar.querySelector('.tag.is-active')) b.classList.add('is-active');
    });
    bar.appendChild(b);
  }
}

/** Какие классы шапки отмечены (пусто — предмет не мультиклассовый). */
export function hatClasses() {
  const bar = document.getElementById('hatclasses');
  if (bar.hidden) return [];
  return [...bar.querySelectorAll('.tag.is-active')].map((b) => b.dataset.hatClass);
}

/**
 * Модельные стили шапки.
 *
 * Это не skinfamilies: у стиля СВОЯ геометрия («Только камень» — та же шапка
 * без оправы), поэтому выбор перезагружает превью другой моделью и меняет то,
 * что уйдёт в сборку.
 */
export function showHatStyles(item) {
  const bar = document.getElementById('hatstyles');
  bar.querySelectorAll('.tag').forEach((b) => b.remove());
  const styles = (item && item.styles) || [];
  bar.hidden = styles.length < 2;
  if (bar.hidden) return;

  styles.forEach((style, index) => {
    const b = document.createElement('button');
    b.className = 'tag' + (index === 0 ? ' is-active' : '');
    b.dataset.style = index;
    b.textContent = style.name;
    b.addEventListener('click', async () => {
      bar.querySelectorAll('.tag').forEach(
        (x) => x.classList.toggle('is-active', x === b));
      const models = hatModels(item, index) || {};
      showHatClasses({ per_class: models });
      const first = Object.values(models)[0] || item.key;
      say('Загрузка стиля: ' + style.name + '…');
      // Индекс нужен сеансу: по нему он и запоминает правки стиля, и понимает,
      // что это стиль ТОЙ ЖЕ шапки, а не новый предмет.
      const res = await api.loadPreview('hat', null, first, models, index);
      if (res.error) say(res.error);
      else markEditedStyles(res.edited_styles);
    });
    bar.appendChild(b);
  });
}

/**
 * Метка «стиль правлен».
 *
 * Правки соседних стилей уходят в тот же мод, и без метки о них вспоминают
 * уже в игре. Имя стиля берём из кнопки — список стилей здесь не нужен.
 */
export function markEditedStyles(indexes) {
  const edited = new Set((indexes || []).map(Number));
  document.querySelectorAll('#hatstyles .tag').forEach((b) => {
    const name = b.textContent.replace(/ ●$/, '');
    b.textContent = edited.has(Number(b.dataset.style)) ? name + ' ●' : name;
  });
}

/**
 * Убирает с экрана всё, что относилось к прошлому предмету.
 *
 * Нужен не только новому предмету, но и смене РАЗДЕЛА: уходя в частицы или
 * шапки, человек уходит от оружия, а его текстура оставалась висеть в альбоме
 * — над чужим каталогом, с чужими карточками.
 */
/**
 * Возвращает обычный вид «Вместе».
 *
 * Вид от первого лица и насмешка — это СЦЕНЫ, собранные под конкретный
 * предмет. У нового предмета такой сцены ещё нет, и оставленный выбор
 * показывал бы пустой кадр с активной кнопкой: человек уже сменил предмет, а
 * приложение всё ещё «в насмешке».
 */
export function resetView() {
  document.querySelectorAll('.modes .underlined').forEach(
    (b) => b.classList.toggle('is-active', b.dataset.view === 'both'));
  work.dataset.view = 'both';
  document.getElementById('fpbar').hidden = true;
  document.getElementById('tauntbar').hidden = true;
  // Камера возвращается к свободной орбите: риг остался от вида от первого лица.
  withViewer((w) => w.setViewRig(null));
}

export function clearPreview() {
  cardTitles = {};        // подписи прошлого мода к новому предмету не относятся
  sceneKind = '';         // и спец-сцена: у обычной модели её нет
  lastModel = null;       // и кадр превью: вернуться к чужой модели нельзя
  resetView();
  document.getElementById('hatstyles').hidden = true;
  document.getElementById('hatclasses').hidden = true;
  // Части считаны по ПРОШЛОЙ модели: у новой под тем же номером другой кусок.
  closeParts();
  showMaterials([]);
  withViewer((w) => w.resetViewer());
}

export async function startPreview(item) {
  clearPreview();

  // У неба нет модели: вьювер ставит его кубмапой, а не мешем.
  if (item.type === 'skybox') {
    say('Извлечение граней неба…');
    const res = await api.loadSkybox(item.sky || item.key);
    if (res.error) say(res.error);
    return;
  }

  say('Загрузка модели…');
  // У шапки своя модель на каждый предмет — ключ передаём явно, из режима
  // «hat» его не вывести.
  // У стилевой шапки покласcовые модели лежат В СТИЛЕ, а не в предмете:
  // берём модели показанного стиля, иначе класс-выбор пуст, а сборка не знает
  // ни одной модели класса.
  const models = hatModels(item, 0);
  showHatClasses({ per_class: models });
  showHatStyles(item);
  const res = await api.loadPreview(item.mode, null,
                                    item.type === 'hat' ? item.key : null,
                                    models || null);
  if (res.error) say(res.error);
}

/**
 * Отдаёт модель вьюверу.
 *
 * OBJ он ждёт СОДЕРЖИМЫМ, а не ссылкой (грузит его через Blob), поэтому файл
 * сначала выкачиваем. Центр и масштаб приходят из Python: bbox у Three.js
 * сразу после загрузки ненадёжен.
 */
//: Последнее событие model_ready: им возвращают обычную модель после вида от
//: первого лица, не пересобирая её воркером (так же делает панель приложения
//: в _restore_plain_model).
export let lastModel = null;

export async function showModel(ev) {
  const w = viewer();
  if (!w) { stage.frame.addEventListener('load', () => showModel(ev), { once: true }); return; }

  try {
    const obj = await (await fetch(api.fileUrl(ev.obj))).text();
    const b = ev.bounds || { cx: 0, cy: 0, cz: 0, scale: 1 };
    w.loadModelFromContent(obj, ev.texture ? api.fileUrl(ev.texture) : '',
                           b.cx, b.cy, b.cz, b.scale, 0);
    bindParts(w);
    say('');                            // модель на экране — подпись убираем

    // Материалы могли приехать раньше, чем OBJ попал в сцену: тогда они легли
    // бы в пустоту и модель осталась серой. Повторяем после загрузки.
    refreshView();
  } catch (err) {
    say('Не удалось показать модель: ' + err.message);
  }
}

// ── Одна геометрия, много карточек ──────────────────────────────────────
//: Меши, носящие ВЫБРАННУЮ карточку, и картинки карточек. У масок маскировки
//: девять текстур на одну голову: какая из них на модели — решает альбом,
//: положения прокрутки Python не знает (см. PreviewSession.card_mesh).
let cardMesh = [];
let cardTex = {};
//: Материал карточки, надетой сейчас. Пусто — обычная модель.
let cardWorn = '';

/** {меш: png} для карточки, на которой стоит альбом. Пусто — красить нечего. */
function wornCard() {
  const png = cardTex[cardWorn];
  if (!cardMesh.length || !png) return {};
  return Object.fromEntries(cardMesh.map((m) => [m, png]));
}

/** Одевает модель в карточку, на которой остановился альбом. */
export function wearCard(name) {
  cardWorn = name || '';
  const map = wornCard();
  if (!Object.keys(map).length) return;
  withViewer((w) => w.applyMaterialMap(Object.fromEntries(
    Object.entries(map).map(([mat, png]) => [mat, api.fileUrl(png)]))));
}

/**
 * Применяет состояние показа, посчитанное Python.
 *
 * Что именно показывать при этой команде, стиле и варианте, решает домен
 * (PreviewTextureState.resolve_card). Здесь только раздача: альбом, вьювер и
 * видимость кнопок команд.
 */
export function applyView(st) {
  // До перерисовки альбома: showMaterials пересобирает его и синхронизирует на
  // первую карточку, а та сразу надевается на меш (wearCard из album.js).
  cardMesh = st.card_mesh || [];
  cardTex = st.textures || {};

  showMaterials(st.materials.length ? st.materials : Object.keys(st.textures),
                st.textures, Boolean(st.style));
  showStyleBar(st);

  // У одноматериальной модели ключ служебный (SINGLE_TEX_KEY) — имени меша с
  // таким названием нет и быть не может. Вьювер искал бы его, не находил и
  // оставлял модель серой. Такую текстуру кладём глобально, на все меши.
  // Меши красим ПОЛНЫМ набором (st.scene): карточки отфильтрованы, а глаза и
  // зубы без текстуры остались бы серыми. Альбом при этом показывает только
  // редактируемое — как и панель приложения.
  // Выбранная карточка накрывает то, что Python положил на её меш: он о
  // положении альбома не знает и кладёт первую попавшуюся (см. wearCard).
  const entries = Object.entries({ ...(st.scene || st.textures), ...wornCard() });
  const single = entries.length === 1 && entries[0][0] === SINGLE_TEX;

  if (applySpecialTexture(st.textures)) {
    // Сцена сама решила, куда положить картинку: обычная раздача по
    // материалам здесь только испортила бы её.
  } else withViewer((w) => {
    if (single) {
      w.updateTextureFromDataUrl(api.fileUrl(entries[0][1]));
    } else if (entries.length) {
      // applyMaterialMap ждёт ОБЪЕКТ, несмотря на имя параметра texMapJson:
      // внутри он делает Object.entries. Строка перебиралась бы посимвольно.
      w.applyMaterialMap(Object.fromEntries(
        entries.map(([mat, png]) => [mat, api.fileUrl(png)])));
    }
  });

  // Активный стиль подсвечиваем по ответу Python, а не по последнему клику.
  // Сравниваем по СЫРОМУ индексу скина: позиция кнопки в ряду ему не равна —
  // команда и вариант в ряд не попадают, а их строки индексы занимают.
  //
  // Строго по своему ряду (#skinbar): рядом стоит ряд анимаций с тем же
  // классом, и общий селектор снимал с него подсветку при каждом обновлении.
  document.querySelectorAll('#skinbar .tag').forEach((b) => {
    b.classList.toggle('is-active', Number(b.dataset.skin) === st.active_skin);
  });

  // Кнопки команд появляются, только если командный вариант ЕСТЬ: иначе
  // переключатель ничего бы не менял (правило в domain has_team_variant).
  const teams = document.querySelector('.teams');
  teams.querySelectorAll('.tag').forEach((b) => {
    const key = b.textContent.trim().toUpperCase();
    if (key === 'RED' || key === 'BLU') {
      b.hidden = !st.has_teams;
      b.classList.toggle('is-active', st.team.toUpperCase() === key);
      // Командный вариант есть, но в стоке он не отличается от RED: без
      // подсказки кажется, что переключатель сломан.
      if (key === 'BLU') {
        b.title = st.blu_matches_red
          ? 'В игре синий вариант этой модели не отличается от красного'
          : '';
      }
    } else {
      b.hidden = !(modeControls.teams && st.has_australium);
      b.classList.toggle('is-active', st.australium_active);
    }
  });

  // «Прочее» — служебные материалы модели: показать можно только то, что у
  // модели есть, поэтому решает состояние, а не режим.
  const misc = document.getElementById('misc');
  misc.hidden = !(modeControls.misc && st.has_misc);
  misc.classList.toggle('is-active', Boolean(st.misc_mode));

  // «Сделать командным» предлагается, пока своего командного варианта нет:
  // после включения его место занимают RED/BLU.
  const make = document.getElementById('maketeam');
  make.hidden = !(modeControls.teams && st.can_force_team);

  // «Редактировать QC» — только при загруженной своей готовой модели: у
  // замены геометрии сборка собирает QC сама. Признак держит Python: смена
  // предмета забывает свою модель, и страница узнаёт об этом оттуда же.
  document.querySelector('[data-cond="qc"]').hidden =
    !(modeControls.replace_model && st.custom_keep);

  // «Разделить на части» — только когда модель и правда в сцене. Признак
  // держит Python (`can_split`): у скайбокса и спрея модели нет вовсе, а до
  // прихода model_ready её ещё нет — и кнопка обещала бы действие, которого
  // сделать нельзя.
  document.querySelector('[data-cond="parts"]').hidden =
    !(modeControls.replace_model && st.can_split);

  // «Убрать свою модель» — только когда своя геометрия и правда стоит.
  // Без неё замена была билетом в один конец: вернуть игровую можно было
  // только выбрав предмет заново.
  document.getElementById('dropmodel').hidden = !st.has_custom;

  // Альбом только что пересобран — вернуть пометки «свои настройки».
  restoreBadges();
  // Сводка внизу зависит от параметров предмета: у нового они свои.
  updateDockSummary();
}

/**
 * Кнопки вариантных стилей (skinfamilies).
 *
 * Один стиль означает, что стилей НЕТ: «Skin 0» — это сама модель, и
 * предлагать выбор из одного варианта незачем.
 */
/**
 * Приём текстуры на кадр: перетаскиванием или двойным щелчком.
 *
 * Файл уезжает на диск, а материалу назначается путь — сборка работает с
 * файлами, а не с содержимым в браузере. Куда именно ляжет текстура (команда,
 * стиль, обе команды у нейтрального материала), решает домен в set_texture.
 */
export function bindDrop(frame) {
  const mat = frame.dataset.mat;

  const accept = async (file) => {
    if (!file) return;
    say('Загрузка текстуры…');
    try {
      applyView(await api.setTexture(mat, await api.upload(file)));
      say('');
    } catch (err) {
      say('Не удалось загрузить: ' + err.message);
    }
  };

  frame.addEventListener('dragover', (e) => {
    e.preventDefault();
    frame.classList.add('is-drop');
  });
  frame.addEventListener('dragleave', () => frame.classList.remove('is-drop'));
  frame.addEventListener('drop', (e) => {
    e.preventDefault();
    frame.classList.remove('is-drop');
    accept(e.dataTransfer.files[0]);
  });

  frame.addEventListener('dblclick', () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*,.vtf';
    input.addEventListener('change', () => accept(input.files[0]));
    input.click();
  });
}

export function showSkins(info) {
  const row = document.getElementById('skinbar');
  row.querySelectorAll('.tag').forEach((b) => b.remove());

  // Стили — это ДОПОЛНИТЕЛЬНЫЕ скины (bloody/clean и т.п.), а не команда и не
  // вариант: у тех свои тумблеры. Строить ряд по num_skins/roles было нельзя —
  // у командного оружия он повторял RED/BLU, а клик по такому «стилю» уходил
  // с ПОЗИЦИОННЫМ индексом и попадал в другую строку $texturegroup (у
  // праздничного гранатомёта — в Festive). Картинка не менялась.
  const styles = (info && info.styles) || [];
  row.hidden = styles.length === 0;
  if (row.hidden) return;

  // Базовый стиль — первой кнопкой. Без него из варианта не выйти: в списке
  // styles его нет (там только варианты), и полоса становилась ловушкой.
  for (const entry of [['Базовый', 0], ...styles]) {
    // (подпись, сырой индекс скина в модели) — индекс именно сырой, по нему
    // выбирают скин и превью, и сборка.
    const [label, index] = Array.isArray(entry) ? entry : [String(entry), 0];
    const b = document.createElement('button');
    b.className = 'tag';
    b.dataset.skin = index;
    b.textContent = label;
    b.addEventListener('click', async () => applyView(await api.setSkin(index)));
    row.appendChild(b);
  }
}

/**
 * Полоса вариантного стиля под альбомом.
 *
 * Стиль переопределяет базу ВЫБОРОЧНО: у него нет своих карточек, пока человек
 * не скажет, какой материал в нём меняет. Пустой альбом здесь — не поломка, но
 * молчать о нём нельзя: именно так это и выглядело — «текстура пропала».
 * Модель при этом показывает базу, а не пустоту.
 */
export function showStyleBar(st) {
  const bar = document.getElementById('stylebar');
  const style = st.style || 0;
  bar.hidden = !style;
  if (!style) return;

  const add = document.getElementById('style-add');
  const candidates = st.style_candidates || [];
  add.hidden = candidates.length === 0;

  document.getElementById('style-note').textContent = st.materials.length
    ? 'Материалы стиля: остальные наследуют базовую текстуру.'
    : 'Стиль пока целиком наследует базу. Добавьте материал, чтобы дать ему свою текстуру.';

  add.onclick = async () => {
    const material = await ask({
      title: 'Какой материал меняет этот стиль',
      list: candidates,
      ok: 'Добавить',
    });
    if (!material) return;
    applyView(await api.addToStyle(material));
  };
}

//: Проигрываемая сейчас анимация вида от первого лица.
export let fpAction = 'IDLE';

/**
 * Ряд анимаций вида от первого лица.
 *
 * Показывается только в этом виде: в обычном ракурсе выбирать нечего, а
 * пустой ряд занимал бы место под моделью.
 */
/**
 * Смена анимации на УЖЕ показанной сцене: приехали одни дорожки.
 *
 * Меш, скелет и текстуры у одного оружия те же, поэтому Python и не собирает
 * их заново. Не легли (сцены в кадре почему-то нет) — просим полную сборку,
 * иначе кадр остался бы с прошлой анимацией и без объяснений.
 */
export function applyFpClip(clip) {
  withViewer((w) => {
    if (clip && w.setViewmodelClip && w.setViewmodelClip(clip)) {
      say('');
      return;
    }
    api.loadFirstPerson(fpAction, true);
  });
}

export function showFpActions(actions) {
  const bar = document.getElementById('fpbar');
  bar.querySelectorAll('.tag').forEach((b) => b.remove());
  const list = actions || [];
  bar.hidden = list.length < 2 || work.dataset.view !== 'fp';
  if (bar.hidden) return;

  for (const action of list) {
    const b = document.createElement('button');
    b.className = 'tag' + (action === fpAction ? ' is-active' : '');
    b.textContent = action;
    b.addEventListener('click', async () => {
      fpAction = action;
      bar.querySelectorAll('.tag').forEach(
        (x) => x.classList.toggle('is-active', x === b));
      // Из кэша сцена приезжает дорожками за треть секунды — при такой
      // скорости подпись только мигнёт, поэтому она отложенная.
      sayBusy('Сборка сцены: ' + action + '…');
      const res = await api.loadFirstPerson(action);
      if (res.error) say(res.error);
    });
    bar.appendChild(b);
  }
}

//: Класс, чью насмешку показываем. Пусто — первый, кто её умеет.
export let tauntClass = '';

/**
 * Ряд классов насмешки.
 *
 * Одну и ту же насмешку играют до девяти классов, и у каждого своя модель
 * реквизита — выбор меняет и персонажа, и то, что у него в руках.
 */
export function showTauntClasses(classes) {
  const bar = document.getElementById('tauntbar');
  bar.querySelectorAll('.tag').forEach((b) => b.remove());
  const list = classes || [];
  bar.hidden = list.length < 2 || work.dataset.view !== 'taunt';
  if (bar.hidden) return;

  if (!list.includes(tauntClass)) tauntClass = list[0];
  for (const name of list) {
    const b = document.createElement('button');
    b.className = 'tag' + (name === tauntClass ? ' is-active' : '');
    b.textContent = name;
    b.addEventListener('click', async () => {
      tauntClass = name;
      bar.querySelectorAll('.tag').forEach(
        (x) => x.classList.toggle('is-active', x === b));
      sayBusy('Сборка сцены: ' + name + '…');
      const res = await api.loadTaunt(name);
      if (res.error) say(res.error);
    });
    bar.appendChild(b);
  }
}

//: Какая спец-сцена сейчас в кадре: '' | 'none' | 'crit' | 'death'.
//: От неё зависит, КУДА кладётся текстура — на билборд или на персонажа.
export let sceneKind = '';
//: Текстура персонажа в сцене (у эффекта смерти — игровая по умолчанию).
export let sceneModelTex = '';
//: Что человек положил сам. Сцена приходит позже текстуры и наоборот —
//: помним последнее, иначе сборка сцены стирала уже выбранную картинку.
let userTextures = {};

/**
 * Сцена спец-режима.
 *
 * Спрей — просто картинка, показывать нечего. Крит — персонаж и билборд над
 * ним. Эффект смерти — тот же персонаж, но текстура ложится на него.
 */
export function showSpecialScene(ev) {
  sceneKind = ev.scene_kind || 'none';
  sceneModelTex = ev.model_texture || '';
  userTextures = {};
  // Кнопки стилей прошлого предмета к спец-режиму не относятся: своего
  // события skins тут не будет, и они остались бы в ряду навсегда.
  document.querySelectorAll('#skinbar .tag').forEach((b) => b.remove());

  if (sceneKind === 'none') {
    withViewer((w) => w.resetViewer && w.resetViewer());
    say('Положите картинку в кадр — модели у этого режима нет');
    return;
  }

  // Настоящую сцену — солдата с анимацией смерти — собирает воркер, и это
  // секунды на распаковку модели. Кубики в это время показывать нельзя: при
  // каждом переключении режима в кадре мелькал бы человечек из коробок.
  if (ev.pending) {
    say('Собираем сцену…');
    return;
  }
  specialFallback();
}

//: Кубики вместо персонажа. Запасной кадр: сюда приходят, если сцену собрать
//: не вышло — игры нет или модель не разобралась.
function specialFallback() {
  const modelUrl = sceneModelTex ? api.fileUrl(sceneModelTex) : '';
  withViewer((w) => w.loadCritHitScene('', modelUrl));
  say(sceneKind === 'crit'
    ? 'Картинка ляжет билбордом над персонажем'
    : 'Картинка ляжет на персонажа — так эффект выглядит в игре');
}

/** Сцену собрать не вышло: показываем то, что показывали раньше. */
export function specialSceneFailed(error) {
  if (!sceneKind || sceneKind === 'none') return false;
  specialFallback();
  if (error) say(error);       // причина важнее подсказки про картинку
  return true;
}

/**
 * Настоящая сцена спец-режима: солдат играет ту смерть, что подходит режиму.
 *
 * Крит — выстрел в голову и билборд над телом; лёд и золото — удар в спину;
 * огонь — своя анимация горения. Сцена та же, что у насмешки, поэтому и
 * показывает её общий загрузчик.
 */
export function showSpecialAnimated(ev) {
  const url = specialTextureUrl();
  withViewer((w) => {
    w.setViewRig(null);
    w.loadViewmodelAnimated(ev.scene, 0);
    if (sceneKind === 'crit') w.setCritSprite(url);
    // У эффекта смерти игра ЗАМЕНЯЕТ материалы трупа целиком: одна картинка
    // ложится на всё тело, а не по материалам.
    else if (url) w.updateTextureFromDataUrl(url);
  });
  // Сообщение о сборке иначе висит поверх кадра до конца сеанса: своего
  // события «готово» у прогресса нет.
  say('');
  // Текстуры персонажа приехали раньше сцены — разложить их некуда было.
  if (sceneKind === 'crit') refreshView();
}

//: Что сейчас показывать в спец-сцене: своя картинка человека, иначе игровая.
function specialTextureUrl() {
  const own = Object.values(userTextures || {})[0];
  if (own) return api.fileUrl(own);
  return sceneModelTex ? api.fileUrl(sceneModelTex) : '';
}

/**
 * Текстура спец-сцены: у крита — билборд, у эффекта смерти — сам персонаж.
 *
 * Возвращает true, если сцена забрала текстуру на себя и обычная раздача по
 * материалам не нужна.
 */
export function applySpecialTexture(textures) {
  if (!sceneKind || sceneKind === 'none') return false;
  userTextures = textures || {};
  const url = specialTextureUrl();
  if (sceneKind === 'crit') {
    // Крит забирает на себя ТОЛЬКО билборд: сам солдат красится своими
    // игровыми текстурами, и обычную раздачу по материалам перебивать нельзя
    // — иначе он остаётся серым.
    withViewer((w) => w.updateCritHitTexture(url));
    return false;
  }
  // На кубиках-заглушке это тоже работает: текстура кладётся на все меши
  // сцены, чем бы она ни была.
  withViewer((w) => w.updateTextureFromDataUrl(url));
  return true;
}

/** Небо: шесть граней кубмапой вместо модели. */
export function showSkybox(faces) {
  const names = Object.keys(faces || {});
  if (!names.length) {
    say('У этого неба граней в игре не нашлось');
    return;
  }
  withViewer((w) => w.loadSkybox(
    Object.fromEntries(names.map((f) => [f, api.fileUrl(faces[f])]))));
  say(names.length < 6 ? `Найдено граней: ${names.length} из 6` : '');
  showMaterials(names, faces);

  // Небо приходит своим событием, минуя applyView, поэтому кнопки прошлого
  // предмета надо убрать здесь: у неба нет ни команд, ни варианта, ни стилей.
  document.querySelectorAll('.teams .tag').forEach((b) => { b.hidden = true; });
  document.getElementById('skinbar').hidden = true;
  document.getElementById('stylebar').hidden = true;
}

/** Статичная сцена вида от первого лица. */
export async function showFirstPerson(objPath, rig) {
  const w = viewer();
  if (!w) return;
  try {
    const obj = await (await fetch(api.fileUrl(objPath))).text();
    // Риг до загрузки: сцена уже стоит там, где надо относительно глаза, и
    // центрировать её нельзя — двигается камера.
    w.setViewRig(rig);
    w.loadModelFromContent(obj, '', 0, 0, 0, 1, 0);
    say('');
  } catch (err) {
    say('Не удалось показать сцену: ' + err.message);
  }
}

/**
 * Пустой кадр альбома.
 *
 * Шестерёнка тут не для красоты: она переводит панель сборки в правку
 * настроек ЭТОГО материала (разрешение и формат бывают нужны свои — например
 * мелкой детали ни к чему 2048).
 */
//: Значок настроек кадра. Раньше здесь стоял знак шестерни (U+2699): системный
//: шрифт рисует его сплошным пятном, и рядом с интерфейсом из волосяных линий
//: он выглядел чужим. Две дорожки с ползунками — та же толщина линии, что у
//: рамок, и честнее по смыслу: за кнопкой параметры сборки, а не механизм.
//: Рисуем 1:1 — единица `viewBox` равна точке экрана, а дорожки стоят на
//: половинах (4.5, 9.5). Линия толщиной 1 ложится тогда РОВНО в пиксельный
//: ряд; при 12 точках из шестнадцатеричной сетки она попадала между рядами и
//: размывалась неравномерно — значок выглядел косым.
const GEAR = `<svg viewBox="0 0 14 14" width="14" height="14" fill="none"
                   stroke="currentColor" stroke-width="1" stroke-linecap="round"
                   aria-hidden="true">
                <path d="M1.5 4.5h11M1.5 9.5h11"/>
                <circle cx="4.5" cy="4.5" r="1.75" fill="var(--surface)"/>
                <circle cx="9.5" cy="9.5" r="1.75" fill="var(--surface)"/>
              </svg>`;

export function frameNode(name) {
  const fig = document.createElement('figure');
  fig.className = 'frame';
  fig.dataset.mat = name;
  fig.innerHTML = `<div class="frame__img">
                     <div class="frame__tools">
                       <button class="frame__tool" type="button"
                               title="Настройки этой текстуры">${GEAR}</button>
                       <button class="frame__tool frame__off" type="button" hidden
                               title="Убрать материал из стиля">×</button>
                     </div>
                   </div>
                   <figcaption class="frame__name"></figcaption>`;
  return fig;
}

/** Добавляет один кадр в конец альбома, не трогая остальные. */
export function addFrame(name, png) {
  const tab = document.createElement('button');
  tab.className = 'mattab';
  tab.textContent = name;
  stage.tabs.appendChild(tab);

  const fig = frameNode(name);
  fig.querySelector('.frame__name').textContent = name;
  const img = document.createElement('img');
  img.src = api.opaqueUrl(png);
  img.alt = name;
  fig.querySelector('.frame__img').appendChild(img);
  stage.album.appendChild(fig);

  bindAlbum();
  goTo(frames.length - 1);        // сразу показываем то, что построили
}

//: {имя_карточки: подпись} — мод из VPK называет текстуры по VTF, а человеку
//: показывает понятное имя. Пусто у обычных моделей.
export let cardTitles = {};

/** Как подписать карточку: служебный ключ и имена мода — особые случаи. */
export function cardTitle(name) {
  if (name === SINGLE_TEX) return 'текстура';
  return cardTitles[name] || name;
}

/** Перерисовывает вкладки и альбом под материалы, пришедшие от воркера. */
export function showMaterials(names, textures = {}, inStyle = false) {
  stage.tabs.innerHTML = '';
  stage.album.innerHTML = '';

  for (const name of names) {
    const tab = document.createElement('button');
    tab.className = 'mattab';
    tab.textContent = cardTitle(name);
    stage.tabs.appendChild(tab);
    // Убрать из стиля можно только то, что в стиль добавляли.

    const fig = frameNode(name);
    const png = textures[name];
    // Служебный ключ одноматериальной модели показывать как имя нельзя.
    fig.querySelector('.frame__name').textContent = cardTitle(name);
    if (png) {
      const img = document.createElement('img');
      img.src = api.opaqueUrl(png);
      img.alt = name;
      fig.querySelector('.frame__img').appendChild(img);
    }
    fig.querySelector('.frame__off').hidden = !inStyle;
    stage.album.appendChild(fig);
  }
  bindAlbum();
}

// ── Режим показа: текстура, модель или обе ──────────────────────────────
document.querySelector('.modes').addEventListener('click', async (e) => {
  const btn = e.target.closest('.underlined');
  if (!btn) return;
  const wasFp = work.dataset.view === 'fp';
  document.querySelectorAll('.modes .underlined').forEach((b) => b.classList.remove('is-active'));
  btn.classList.add('is-active');
  work.dataset.view = btn.dataset.view;

  // Вид от первого лица — не другой ракурс, а другая сцена: её собирает
  // отдельный воркер слиянием рук класса с оружием.
  if (btn.dataset.view === 'taunt') {
    // Насмешка — тоже не ракурс, а другая сцена: персонаж с реквизитом.
    // Камера у неё свободная, поэтому рига нет.
    say('Сборка насмешки…');
    withViewer((w) => w.setViewRig(null));
    const res = await api.loadTaunt(tauntClass);
    if (res.error) say(res.error);
  } else if (btn.dataset.view === 'fp') {
    say('Сборка вида от первого лица…');
    const res = await api.loadFirstPerson(fpAction);
    if (res.error) say(res.error);
    // Риг придёт вместе со сценой: ответ на этот запрос может отстать от
    // события, и полагаться на его порядок нельзя.
  } else if (root.dataset.section !== 'particles') {
    // Выход из вида: возвращаем свободную орбиту. У частиц вьювер моделей
    // не участвует — дёргать его незачем.
    withViewer((w) => w.setViewRig(null));
    document.getElementById('fpbar').hidden = true;
    document.getElementById('tauntbar').hidden = true;
    // Свободная камера — это ещё не выход: сцену рук собирал отдельный воркер,
    // и без возврата обычной модели оружие оставалось в руках, только вертеть
    // его теперь можно было свободно. Кадр обычного превью уже есть, поэтому
    // Python пересобирать нечего — он лишь снимает сцену и подложку.
    if (wasFp) {
      applyView(await api.leaveFirstPerson());
      if (lastModel) await showModel(lastModel);
    }
  }
});

// Команды и вариант: решение принимает Python, страница применяет ответ.
document.querySelector('.teams').addEventListener('click', async (e) => {
  const btn = e.target.closest('.tag');
  if (!btn) return;
  const key = btn.textContent.trim().toUpperCase();
  applyView(key === 'RED' || key === 'BLU'
    ? await api.setTeam(key)
    : await api.setAustralium(!btn.classList.contains('is-active')));
});

// «Прочее» и «Сделать командным»: состояние меняет Python, страница
// применяет ответ целиком — как у команд и варианта.
document.getElementById('misc').addEventListener('click', async () => {
  applyView(await api.toggleMisc());
});

document.getElementById('maketeam').addEventListener('click', async () => {
  applyView(await api.forceTeam());
});

/** Запоминает последний кадр превью: им возвращают обычную модель после
 *  вида от первого лица, не пересобирая её воркером. */
export function rememberModel(ev) { lastModel = ev; }

/** Подписи карточек мода из VPK: он называет текстуры по VTF, а человеку
 *  показывает понятное имя. */
export function setCardTitles(titles) { cardTitles = titles; }
