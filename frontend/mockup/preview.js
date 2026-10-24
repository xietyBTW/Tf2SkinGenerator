/*
 * Превью предмета: что приехало от воркера и как это показано
 *
 * Модель приходит не ответом на запрос, а потоком событий: сначала прогресс,
 * потом готовая модель, потом материалы. Поэтому здесь только запуск и показ,
 * а разбор событий - в events.js
 *
 * У ОДНОМАТЕРИАЛЬНОЙ модели текстура приезжает прямо в model_ready и события
 * materials не будет вовсе: один кадр - не особый случай, а тот же альбом
 * длиной в единицу.
 */


import * as api from './api.js';
import { t } from './i18n.js';
import { say, sayError, stage, viewer, withViewer } from './stage.js';
import { work } from './layout.js';
import { SINGLE_TEX } from './album.js';
import { modeControls, restoreBadges } from './controls.js';
import { syncPaint } from './paint.js';
import { hideWarpaint, warpaintPreview } from './warpaint.js';
import { closeParts, bindParts, refreshParts } from './parts.js';
import { updateDockSummary } from './build.js';
import { refreshNormal } from './normals.js';
import { showFit, showDecorFit, showDecorBends, dropFitSave, bindFitViewer, isFitOn }
  from './custom-model.js';
import { hatModels, showHatClasses, showHatStyles, markEditedStyles } from './preview-hats.js';
import { showMaterials, setCardTitles } from './preview-frames.js';
import { showBodygroups, decorFittable, showFestive, forgetDecor, showSkins, showStyleBar }
  from './preview-variants.js';
import { resetView, forgetSpecialScene, applySpecialTexture } from './preview-scenes.js';

// Области превью - свои модули: шапки (preview-hats), карточки альбома
// (preview-frames), ряды вариантов модели (preview-variants), сцены кадра
// (preview-scenes). Остальные модули берут всё отсюда
export { hatModels, showHatClasses, hatClasses, showHatStyles, markEditedStyles }
  from './preview-hats.js';
export { frameNode, addFrame, cardTitles, setCardTitles, cardTitle, showMaterials }
  from './preview-frames.js';
export { showDecor, festiveFailed, showSkins, showStyleBar } from './preview-variants.js';
export { resetView, fpAction, applyFpClip, reloadSceneIfFp, showFpActions, tauntClass,
         showTauntClasses, showWearSlots, sceneKind, sceneModelTex, showSpecialScene,
         specialSceneFailed, showSpecialAnimated, applySpecialTexture, showSkybox,
         showFirstPerson } from './preview-scenes.js';

// Данные из Python
// Каталог, фильтры и правила видимости приходят из src/app/api.py. Здесь
// только отрисовка: ни списков предметов, ни условий «что показывать» в
// представлении быть не должно - иначе они разъедутся с приложением

// Загрузка превью
// Модель приезжает не ответом на запрос, а потоком событий: сначала прогресс,
// потом готовая модель, потом материалы. Поэтому здесь только запуск, а
// показывает результат обработчик событий ниже

//: Запросы состояния идут пачками (materials, blu_materials, australium
//: приходят подряд) - склеиваем их в один, иначе альбом перерисуется трижды
export let viewTimer = null;

export function refreshView() {
  clearTimeout(viewTimer);
  viewTimer = setTimeout(async () => {
    applyView(await api.viewState());
  }, 80);
}

/**
 * Убирает с экрана всё, что относилось к прошлому предмету
 *
 * Нужен не только новому предмету, но и смене РАЗДЕЛА: уходя в частицы или
 * шапки, человек уходит от оружия, а его текстура оставалась висеть в альбоме
 * - над чужим каталогом, с чужими карточками.
 */
export function clearPreview() {
  forgetDecor();          // гирлянда прошлого предмета, если ещё качается, не нужна
  setCardTitles({});      // подписи прошлого мода к новому предмету не относятся
  forgetSpecialScene();   // и спец-сцена: у обычной модели её нет
  lastModel = null;       // и кадр превью: вернуться к чужой модели нельзя
  resetView();
  document.getElementById('hatstyles').hidden = true;
  // Ряды прошлого оружия: версия с гирляндой, стили скина, состояние модели.
  // Раздел сменили (шапки) - предмета нет, и ряды висели бы ни к чему
  for (const id of ['festivebar', 'makefestive', 'skinbar', 'bodybar']) {
    document.getElementById(id).hidden = true;
  }
  showHatClasses(null);
  // Части считаны по ПРОШЛОЙ модели: у новой под тем же номером другой кусок
  closeParts();
  hideWarpaint();         // War Paint - про прошлое оружие, у нового свой список
  dropFitSave();          // и подгонка: её отложенная запись - про прошлую
  showMaterials([]);
  // Кнопки работы - про предмет, которого больше нет: «Вернуть правки» над
  // пустым альбомом обещало правки неизвестно чего. Их вернёт restoreBadges
  // вместе со следующей моделью
  for (const id of ['keep', 'restore', 'forget']) document.getElementById(id).hidden = true;
  withViewer((w) => w.resetViewer());
}

export async function startPreview(item) {
  clearPreview();

  // У неба нет модели: вьювер ставит его кубмапой, а не мешем
  if (item.type === 'skybox') {
    say('Извлечение граней неба…');
    const res = await api.loadSkybox(item.sky || item.key);
    if (res.error) sayError(res.error);
    return;
  }

  say('Загрузка модели…');
  // Крутилка в самом кадре и сразу: подпись выше появляется только через
  // 400 мс, а в пустом окне до тех пор стояло «Выберите оружие» - щелчок
  // выглядел непринятым
  withViewer((w) => w.showLoading());
  // У шапки своя модель на каждый предмет - ключ передаём явно, из режима
  // «hat» его не вывести.
  // У стилевой шапки покласcовые модели лежат В СТИЛЕ, а не в предмете:
  // берём модели показанного стиля, иначе класс-выбор пуст, а сборка не знает
  // ни одной модели класса
  const models = hatModels(item, 0);
  showHatClasses({ per_class: models });
  showHatStyles(item);
  // item.skin - строка скина модели, на которой открыть (Критокола - строка 2
  // модели Бонка): стиль включится, как только скины модели определятся
  const res = await api.loadPreview(item.mode, null,
                                    item.type === 'hat' ? item.key : null,
                                    models || null, item.skin ?? null, false,
                                    item.type === 'hat' ? item.key : '');
  if (res.error) {
    sayError(res.error);
    withViewer((w) => w.stopLoading());
  }
}

/**
 * Открывает сохранённую работу по шапке на том стиле, где её оставили
 *
 * Без строки каталога у стилевой шапки нет ни списка стилей, ни моделей
 * стиля: работа открывалась без переключателя, и правки соседних стилей
 * было не достать. Шапки нет в каталоге (другая версия игры) - открываем
 * как обычный предмет.
 */
export async function startHatWork(work) {
  clearPreview();
  say('Открываю работу…');
  const item = await api.hatItem(work.item_key);
  if (!item.key) {
    const res = await api.loadPreview('hat', null, work.item_key || null,
                                      work.per_class || null, null, true);
    if (res.error) sayError(res.error);
    return;
  }
  const index = work.style || 0;
  const models = hatModels(item, index);
  showHatClasses({ per_class: models });
  showHatStyles(item, index);
  const first = (models && Object.values(models)[0]) || item.key;
  const res = await api.loadPreview('hat', null, first, models || null,
                                    index, true, item.key);
  if (res.error) sayError(res.error);
  else markEditedStyles(res.edited_styles);
}

/**
 * Отдаёт модель вьюверу
 *
 * OBJ он ждёт СОДЕРЖИМЫМ, а не ссылкой (грузит его через Blob), поэтому файл
 * сначала выкачиваем. Центр и масштаб приходят из Python: bbox у Three.js
 * сразу после загрузки ненадёжен.
 */
//: Последнее событие model_ready: им возвращают обычную модель после вида от
//: первого лица, не пересобирая её воркером (так же делает панель приложения
//: в _restore_plain_model)
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
    bindFitViewer(w);
    say('');                            // модель на экране - подпись убираем

    // Материалы могли приехать раньше, чем OBJ попал в сцену: тогда они легли
    // бы в пустоту и модель осталась серой. Повторяем после загрузки
    refreshView();
  } catch (err) {
    sayError(`Не удалось показать модель: ${err.message}`);
  }
}

// Одна геометрия, много карточек
//: Меши, носящие ВЫБРАННУЮ карточку, и картинки карточек. У масок маскировки
//: девять текстур на одну голову: какая из них на модели - решает альбом,
//: положения прокрутки Python не знает (см. PreviewSession.card_mesh)
let cardMesh = [];
let cardTex = {};
//: Материал карточки, надетой сейчас. Пусто - обычная модель
let cardWorn = '';

/** {меш: png} для карточки, на которой стоит альбом. Пусто - красить нечего.
 *  Меши - общий список (маски шпиона) или свои у каждой карточки («Прочее»:
 *  убер и зомби стоят на месте тела, головы, глаз) */
function wornCard() {
  const png = cardTex[cardWorn];
  const meshes = Array.isArray(cardMesh) ? cardMesh : (cardMesh[cardWorn] || []);
  if (!meshes.length || !png) return {};
  return Object.fromEntries(meshes.map((m) => [m, png]));
}

//: Последняя анимация частей от Python: {mesh, still, frames, fps}. Нужна
//: после каждой раздачи текстур - вьювер при ней анимацию гасит
let partsAnim = null;

/** Гифка на части крутится в 3D: кадры посчитал Python (parts_animated) */
export function showPartsAnimation(ev) {
  partsAnim = ev.frames && ev.frames.length > 1 ? ev : null;
  if (!partsAnim) return;
  withViewer((w) => w.loadAnimatedTexture(
    partsAnim.frames.map(api.fileUrl), partsAnim.fps, partsAnim.mesh));
}

/** Настройку выключили: кадры забываем и перекрашиваем сцену неподвижной
 *  склейкой - раздача текстур во вьювере гасит анимацию сама */
export function stopPartsAnimation() {
  partsAnim = null;
  refreshView();
}

function replayPartsAnimation(w, entries) {
  if (!partsAnim) return;
  // Склейку сменил новый мазок - его кадры приедут своим событием, а старые
  // крутить поверх новой текстуры нельзя
  if (!entries.some(([, png]) => png === partsAnim.still)) { partsAnim = null; return; }
  w.loadAnimatedTexture(partsAnim.frames.map(api.fileUrl), partsAnim.fps, partsAnim.mesh);
}

//: Меши, на которых сейчас надетая карточка. У «Прочего» карточки носят
//: разные меши (тело, голова), и мешам прежней возвращают текстуру сцены -
//: иначе тело оставалось в убере, пока смотрят голову
let wornMeshes = [];

/** Одевает модель в карточку, на которой остановился альбом */
export function wearCard(name) {
  cardWorn = name || '';
  const map = wornCard();
  const scene = (lastView && (lastView.scene || lastView.textures)) || {};
  const back = Object.fromEntries(wornMeshes
    .filter((m) => !(m in map) && scene[m]).map((m) => [m, scene[m]]));
  wornMeshes = Object.keys(map);
  const all = { ...back, ...map };
  if (!Object.keys(all).length) return;
  withViewer((w) => w.applyMaterialMap(Object.fromEntries(
    Object.entries(all).map(([mat, png]) => [mat, api.fileUrl(png)]))));
}

/**
 * Применяет состояние показа, посчитанное Python
 *
 * Что именно показывать при этой команде, стиле и варианте, решает домен
 * (PreviewTextureState.resolve_card). Здесь только раздача: альбом, вьювер и
 * видимость кнопок команд.
 */
//: Последнее состояние показа: кнопкам модели нужно знать, что есть
export let lastView = null;

export function applyView(st) {
  lastView = st;
  // До перерисовки альбома: showMaterials пересобирает его и синхронизирует на
  // первую карточку, а та сразу надевается на меш (wearCard из album.js)
  cardMesh = st.card_mesh || [];
  cardTex = st.textures || {};

  showMaterials(st.materials.length ? st.materials : Object.keys(st.textures),
                st.textures, Boolean(st.style));
  showStyleBar(st);

  // У одноматериальной модели ключ служебный (SINGLE_TEX_KEY) - имени меша с
  // таким названием нет и быть не может. Вьювер искал бы его, не находил и
  // оставлял модель серой. Такую текстуру кладём глобально, на все меши.
  // Меши красим ПОЛНЫМ набором (st.scene): карточки отфильтрованы, а глаза и
  // зубы без текстуры остались бы серыми. Альбом при этом показывает только
  // редактируемое - как и панель приложения.
  // Выбранная карточка накрывает то, что Python положил на её меш: он о
  // положении альбома не знает и кладёт первую попавшуюся (см. wearCard).
  // Предпросмотр War Paint - поверх всего, в меши ЭТОЙ сцены (card_scene):
  // у одноматериальной модели в руках это настоящее имя меша, не служебный ключ
  const trial = Object.entries(warpaintPreview() || {}).flatMap(
    ([card, png]) => (st.card_scene?.[card] || [card]).map((mesh) => [mesh, png]));
  const worn = wornCard();
  wornMeshes = Object.keys(worn);
  const entries = Object.entries({ ...(st.scene || st.textures), ...worn,
                                   ...Object.fromEntries(trial) });
  const single = entries.length === 1 && entries[0][0] === SINGLE_TEX;

  // Куски своих материалов частей - до раздачи: текстуры ищут меши по имени
  withViewer((w) => w.setPartMaterials(st.part_materials || {}));

  if (applySpecialTexture(st.textures)) {
    // Сцена сама решила, куда положить картинку: обычная раздача по
    // материалам здесь только испортила бы её
  } else withViewer((w) => {
    if (single) {
      w.updateTextureFromDataUrl(api.fileUrl(entries[0][1]));
    } else if (entries.length) {
      // applyMaterialMap ждёт ОБЪЕКТ, несмотря на имя параметра texMapJson:
      // внутри он делает Object.entries. Строка перебиралась бы посимвольно
      w.applyMaterialMap(Object.fromEntries(
        entries.map(([mat, png]) => [mat, api.fileUrl(png)])));
    }
    // Раздача текстур останавливает анимацию во вьювере, если на сцене всё
    // ещё та склейка, для которой считались кадры, - запускаем их заново
    replayPartsAnimation(w, entries);
  });

  // Активный стиль подсвечиваем по ответу Python, а не по последнему клику.
  // Сравниваем по СЫРОМУ индексу скина: позиция кнопки в ряду ему не равна -
  // команда и вариант в ряд не попадают, а их строки индексы занимают
  //
  // Строго по своему ряду (#skinbar): рядом стоит ряд анимаций с тем же
  // классом, и общий селектор снимал с него подсветку при каждом обновлении
  //
  // Сам ряд - тоже по ответу Python: у своей модели «со своими материалами»
  // в нём ещё и Australium (PreviewSession.styles), а событие определения
  // стилей приносит только игровые
  const skinRow = document.getElementById('skinbar');
  if (st.skins !== undefined
      && skinRow.dataset.styles !== JSON.stringify((st.skins && st.skins.styles) || [])) {
    showSkins(st.skins);
  }
  document.querySelectorAll('#skinbar .tag').forEach((b) => {
    b.classList.toggle('is-active', Number(b.dataset.skin) === st.active_skin);
  });

  // Кнопки команд появляются, только если командный вариант ЕСТЬ: иначе
  // переключатель ничего бы не менял (правило в domain has_team_variant)
  const teams = document.querySelector('.teams');
  teams.querySelectorAll('.tag').forEach((b) => {
    const key = b.textContent.trim().toUpperCase();
    if (b.id === 'paint') {
      // Краска - про шапки: режим решает Python (controls_for)
      b.hidden = !modeControls.hat_paints;
      return;
    }
    if (key === 'RED' || key === 'BLU') {
      b.hidden = !st.has_teams;
      b.classList.toggle('is-active', st.team.toUpperCase() === key);
    } else {
      b.hidden = !(modeControls.teams && st.has_australium);
      b.classList.toggle('is-active', st.australium_active);
    }
  });

  // «Прочее» - служебные материалы модели: показать можно только то, что у
  // модели есть, поэтому решает состояние, а не режим
  const misc = document.getElementById('misc');
  misc.hidden = !(modeControls.misc && st.has_misc);
  misc.classList.toggle('is-active', Boolean(st.misc_mode));

  // «Сделать командным» предлагается, пока своего командного варианта нет:
  // после включения его место занимают RED/BLU
  const make = document.getElementById('maketeam');
  make.hidden = !(modeControls.teams && st.can_force_team);
  syncPaint(st);

  // «Редактировать QC» - только при загруженной своей готовой модели: у
  // замены геометрии сборка собирает QC сама. Признак держит Python: смена
  // предмета забывает свою модель, и страница узнаёт об этом оттуда же
  document.querySelector('[data-cond="qc"]').hidden =
    !(modeControls.replace_model && st.custom_keep);

  // «Разделить на части» - только когда модель и правда в сцене. Признак
  // держит Python (`can_split`): у скайбокса и спрея модели нет вовсе, а до
  // прихода model_ready её ещё нет - и кнопка обещала бы действие, которого
  // сделать нельзя. Режим при этом спрашиваем свой (`split_parts`), а не
  // подмену модели: тело класса не подменить, а разделить - можно.
  // На сцене её нет вовсе: карта частей у страницы от обычной модели, и
  // открытый на руках режим красил бы не то, что показано.
  // В режиме подгонки частей нет: у обоих свой захват мыши в кадре
  document.querySelector('[data-cond="parts"]').hidden =
    !(modeControls.split_parts && st.can_split) || work.dataset.scene !== 'item'
    || isFitOn();

  showBodygroups(st.bodygroups || []);
  showFestive(st);

  // «Убрать свою модель» - только когда своя геометрия (оружия или
  // гирлянды) и правда стоит. Без неё замена была билетом в один конец
  document.getElementById('dropmodel').hidden =
    !(st.has_custom || (st.decor_models || []).length
      || (st.bodygroups || []).some((g) => g.custom));
  // Подгонка - только у импортированной модели и только в кадре предмета:
  // на руках и в насмешке призрака нет
  showFit(work.dataset.scene === 'item' ? st.custom_fit : null);
  // Гирлянда: её подгонка и свои картинки идут вьюверу отдельно от
  // раздачи текстур предмета - её меши он красит своим слоем
  showDecorFit(st.decor_fit || null, Boolean(st.festive) && work.dataset.scene === 'item'
                                     && decorFittable(st));
  showDecorBends(st.decor_bends || []);
  withViewer((w) => w.setDecorOverrides && w.setDecorOverrides(Object.fromEntries(
    Object.entries(st.decor_textures || {}).map(([mesh, teams]) => [mesh, {
      red: (teams.red || []).map(api.fileUrl),
      blu: (teams.blu || []).map(api.fileUrl),
    }]))));

  // Альбом только что пересобран - вернуть пометки «свои настройки»
  restoreBadges();
  // Сводка внизу зависит от параметров предмета: у нового они свои
  updateDockSummary();
  // Рельеф строится из текстуры: сменилась она или предмет - и он
  refreshNormal();
}

/**
 * Приём текстуры на материал: перетаскиванием на кадр или модель, двойным
 * щелчком по кадру
 *
 * Файл уезжает на диск, а материалу назначается путь - сборка работает с
 * файлами, а не с содержимым в браузере. Куда именно ляжет текстура (команда,
 * стиль, обе команды у нейтрального материала), решает домен в set_texture.
 */
async function acceptTexture(mat, file) {
  if (!file) return;
  say('Загрузка текстуры…');
  try {
    applyView(await api.setTexture(mat, await api.upload(file)));
    say('');
    // Обучение ждёт именно этого: своя картинка легла на материал
    document.dispatchEvent(new Event('texture:set'));
  } catch (err) {
    sayError(`Не удалось загрузить: ${err.message}`);
  }
}

/**
 * Картинку бросили прямо на модель во вьювере. Материал под курсором, если
 * у него есть карточка, иначе главная (первая в альбоме).
 */
function acceptModelDrop(material, file) {
  const frames = [...stage.album.querySelectorAll('.frame')];
  const frame = frames.find((f) => f.dataset.mat === material) || frames[0];
  if (frame) acceptTexture(frame.dataset.mat, file);
}

// Вьювер живёт в своём iframe и перезагружается со сменой сцены: крючок
// ставим на каждую загрузку, а не только когда приехала модель (у спрея и
// эффектов смерти её нет)
function bindModelDrop() {
  const w = viewer();
  if (w) w.onTextureDropped = acceptModelDrop;
}
stage.frame.addEventListener('load', bindModelDrop);
bindModelDrop();

export function bindDrop(frame) {
  const accept = (file) => acceptTexture(frame.dataset.mat, file);

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

// Раскладка: текстура, модель или обе
//
// Только раскладка. Что показано в кадре, решает ряд у самого кадра (сцены):
// это разные вопросы, и пока они стояли одним рядом, «Вместе» с насмешкой было
// недостижимо, а выход из сцены случался ПОБОЧНО - от смены раскладки. Оттуда
// и брался баг: ветку выхода написали для вида от первого лица, появилась
// вторая сцена, и выключить её стало нечем
document.querySelector('.modes').addEventListener('click', (e) => {
  const btn = e.target.closest('.underlined');
  if (!btn) return;
  document.querySelectorAll('.modes .underlined').forEach((b) => b.classList.remove('is-active'));
  btn.classList.add('is-active');
  if (work.dataset.view === btn.dataset.view) return;
  // Половины разъезжаются по своим сторонам, оставшаяся растягивается -
  // это View Transitions: браузер снимает кадр «до», применяет смену и
  // сам ведёт каждую половину к кадру «после» (правила в style.css,
  // `::view-transition-*`). Без поддержки - просто переключение
  const apply = () => { work.dataset.view = btn.dataset.view; };
  const motion = document.documentElement.dataset.motion !== 'off';
  if (motion && document.startViewTransition) {
    const shift = document.startViewTransition(apply);
    // Переход бросается, когда кадры не рисуются (окно свёрнуто или за
    // другими): смена вида при этом уже применена, а отказ без обработчика
    // уходил на экран сырым «Transition was aborted…»
    shift.ready.catch(() => {});
    shift.finished.catch(() => {});
  } else {
    apply();
  }
});

// Команды и вариант: решение принимает Python, страница применяет ответ
document.querySelector('.teams').addEventListener('click', async (e) => {
  const btn = e.target.closest('.tag');
  if (!btn || btn.id === 'paint') return;      // у краски свой список (paint.js)
  const key = btn.textContent.trim().toUpperCase();
  applyView(key === 'RED' || key === 'BLU'
    ? await api.setTeam(key)
    : await api.setAustralium(!btn.classList.contains('is-active')));
  // Части красят то, что в кадре: с австралием - его карточку. Полоса
  // должна показать её покраску, а не главной
  if (!document.getElementById('partsbar').hidden) await refreshParts();
});

// «Прочее» и «Сделать командным»: состояние меняет Python, страница
// применяет ответ целиком - как у команд и варианта
document.getElementById('misc').addEventListener('click', async () => {
  applyView(await api.toggleMisc());
});

document.getElementById('maketeam').addEventListener('click', async () => {
  applyView(await api.forceTeam());
});

/** Запоминает последний кадр превью: им возвращают обычную модель после
 *  вида от первого лица, не пересобирая её воркером */
export function rememberModel(ev) { lastModel = ev; }

