/*
 * Оживление макета: ровно столько, чтобы можно было пощёлкать состояния.
 * Логики приложения здесь нет — это витрина оформления.
 */

import * as api from './api.js';
import { curveFraction, curveValue } from './curve.js';

/** Делает элементы внутри контейнера взаимоисключающими. */
function groupIn(root, itemSelector) {
  if (!root) return;
  root.addEventListener('click', (e) => {
    const target = e.target.closest(itemSelector);
    if (!target || !root.contains(target)) return;
    root.querySelectorAll(itemSelector).forEach((el) => el.classList.remove('is-active'));
    target.classList.add('is-active');
  });
}

/** То же по селектору контейнера. */
function group(selector, itemSelector) {
  groupIn(document.querySelector(selector), itemSelector);
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
group('.title__side', '.tag');
group('#skinbar', '.tag');
group('#fpbar', '.tag');
// Каждый ряд фильтров независим: класс, тип и подтип выбираются отдельно.


const root = document.documentElement;
const catalog = document.getElementById('catalog');
const build = document.getElementById('build');
//: Правая панель раздела частиц: крутилки эффекта вместо параметров VTF.
const pbuild = document.getElementById('pbuild');
const plist = document.getElementById('plist');
const pnote = document.getElementById('pnote');

/** Какая из правых панелей сейчас в деле. */
function panel() {
  return root.dataset.section === 'particles' ? pbuild : build;
}

/** Показывает панель своего раздела; вторая скрыта всегда.
 *  Отдельно от applyPanels: смена раздела не должна закрывать каталог. */
function applyRightPanel() {
  const particlesSection = root.dataset.section === 'particles';
  const pinned = root.dataset.panels === 'pinned';
  build.hidden = particlesSection || !pinned;
  // Крутилки эффекта нужны РЯДОМ с эффектом, а не по вызову: правку смотрят
  // тут же, в кадре. Поэтому в этом разделе панель открыта всегда.
  pbuild.hidden = !particlesSection;
}

// ── Панели: прибиты к краям или вызываются поверх ────────────────────────
// Единственная настройка, которая меняет раскладку. Каталог и параметры
// нарисованы по одному разу; здесь только их видимость в плавающем режиме —
// в прибитом они видны всегда.
const panelsBtn = document.getElementById('panels');

// Ниже этого порога три прибитые панели в строку не встают — они налезали бы
// друг на друга. Режим тогда принудительно плавающий, а кнопка гаснет: честнее
// сказать «не помещается», чем показать сломанный экран.
const narrow = matchMedia('(max-width: 1100px)');

//: Выбор пользователя. Хранится ОТДЕЛЬНО от действующего режима, иначе узкое
//: окно затирало бы его: сузил, вернул — а панели не вернулись.
let wantPinned = false;

function applyPanels() {
  const pinned = wantPinned && !narrow.matches;
  root.dataset.panels = pinned ? 'pinned' : 'float';
  // В прибитом режиме оба блока на экране всегда; в плавающем их показывают
  // по требованию, поэтому в покое они скрыты.
  catalog.hidden = !pinned;
  applyRightPanel();

  panelsBtn.textContent = wantPinned ? 'Открепить панели' : 'Закрепить панели';
  panelsBtn.disabled = narrow.matches;
  panelsBtn.title = narrow.matches
    ? 'Для закреплённых панелей нужно окно шире 1100 px' : '';
}

panelsBtn.addEventListener('click', () => {
  wantPinned = !wantPinned;
  applyPanels();
});

// Слушаем и медиазапрос, и resize: change у MediaQueryList приходит не во
// всех окружениях (проверено — в эмулированном вьюпорте не пришёл), а
// applyPanels идемпотентна, лишний вызов ничего не стоит.
narrow.addEventListener('change', applyPanels);
addEventListener('resize', applyPanels);
applyPanels();

// ── Каталог: вошёл, выбрал, вышел ───────────────────────────────────────
const floating = () => root.dataset.panels === 'float';
const openCat = () => {
  if (!floating()) return;          // прибитый каталог и так на экране
  catalog.hidden = false;
  catalog.querySelector('.catalog__search').focus();
};
const closeCat = () => { if (floating()) catalog.hidden = true; };

document.getElementById('opencat').addEventListener('click', openCat);
document.getElementById('closecat').addEventListener('click', closeCat);

// ── Параметры сборки ────────────────────────────────────────────────────
document.getElementById('opensettings').addEventListener('click', () => {
  if (floating()) { const el = panel(); el.hidden = !el.hidden; }
});

// Поле гаммы имеет смысл только когда она включена.
const gamma = document.getElementById('gamma');
gamma.addEventListener('change', () => {
  document.getElementById('gammaval').disabled = !gamma.checked;
});

// Инструменты: пока подключён экспорт UV-шаблона — он нужен, чтобы глазами
// сверить, куда какой кусок текстуры садится на модель.
document.getElementById('tools').addEventListener('click', async (e) => {
  const item = e.target.closest('.menu__item');
  if (!item) return;

  if (item.dataset.tool === 'open') {
    // Файл с диска кладём во временную папку и грузим оттуда: Python берёт
    // путь, а страница пути к выбранному файлу не знает и знать не должна.
    const file = await chooseFile('.pcf');
    if (!file) return;
    say('Загрузка ' + file.name + '…');
    try {
      await loadPcf(await api.upload(file), file.name);
    } catch (err) {
      say('Не удалось открыть: ' + err.message);
    }
    return;
  }
  if (item.dataset.tool === 'save') {
    const path = await ask({ title: 'Куда сохранить PCF',
                             value: 'export/' + (pSystem || 'effect') + '.pcf' });
    if (!path) return;
    const res = await api.saveParticles(path);
    say(res.error || `Сохранено: ${res.path} (${res.size} Б)`);
    return;
  }
  if (item.dataset.tool === 'ref' || item.dataset.tool === 'ref-ai') {
    const forAi = item.dataset.tool === 'ref-ai';
    say('Сбор справочника…');
    const res = await api.particleReference('', forAi);
    say(res.error || `Справочник сохранён: ${res.path}`);
    return;
  }

  if (item.dataset.tool === 'uv') {
    say('Построение UV-шаблона…');
    const res = await api.exportUv(1024);
    if (res.error) say(res.error);
    return;
  }

  // Извлечение модели двухшаговое: сначала Python готовит файлы во временной
  // папке, потом человек выбирает, что сохранить (событие extract_files).
  if (item.dataset.tool === 'model') {
    say('Извлечение модели…');
    const res = await api.extractModel();
    if (res.error) say(res.error);
    return;
  }

  if (item.dataset.tool === 'texture') {
    const res = await api.extractTexture();
    if (res.error) { say(res.error); return; }
    // У тела персонажа текстур два десятка — какие брать, решает человек.
    if (res.need_textures) {
      const picked = await ask({
        title: 'Какие текстуры извлечь',
        list: res.need_textures, multi: true, chosen: res.need_textures,
        ok: 'Извлечь',
      });
      if (!picked || !picked.length) return;
      const again = await api.extractTexture(picked);
      if (again.error) say(again.error);
      return;
    }
    say('Извлечение текстуры…');
    return;
  }

  if (item.dataset.tool === 'merge') { await mergeMods(); return; }
});

/**
 * Объединение собранных модов в один VPK.
 *
 * Моды, трогающие одно оружие, друг друга затирают — про такие Python
 * предупреждает до запуска и ждёт подтверждения.
 */
async function mergeMods() {
  const files = await api.exportVpks();
  if (!files.length) { say('В папке экспорта нет собранных модов'); return; }

  const picked = await ask({ title: 'Какие моды объединить', list: files,
                             multi: true, ok: 'Далее' });
  if (!picked || picked.length < 2) return;

  const name = await ask({ title: 'Имя выходного файла', value: 'merged_mod.vpk' });
  if (!name) return;

  let res = await api.mergeVpk(picked, name);
  if (res.duplicates) {
    const lines = Object.entries(res.duplicates)
      .map(([weapon, mods]) => `${weapon}: ${mods.join(', ')}`).join('\n');
    const go = await ask({
      title: 'Моды трогают одно оружие',
      text: lines + '\nОдин перекроет другой. Продолжить?',
      ok: 'Объединить',
    });
    if (!go) return;
    res = await api.mergeVpk(picked, name, true);
  }
  if (res.error) say(res.error);
  else say('Объединение…');
}

// ── Меню инструментов ───────────────────────────────────────────────────
const tools = document.getElementById('tools');
document.getElementById('opentools').addEventListener('click', (e) => {
  e.stopPropagation();
  tools.hidden = !tools.hidden;
});
document.addEventListener('click', (e) => {
  if (!tools.hidden && !e.target.closest('.menu')) tools.hidden = true;
});

document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  if (!tools.hidden) { tools.hidden = true; return; }
  if (floating() && !panel().hidden) { panel().hidden = true; return; }
  closeCat();
});

// ── Альбом текстур ───────────────────────────────────────────────────────
// Вкладки, стрелки и прокрутка — три входа в одно: какой кадр перед глазами.
// Текущий кадр определяется ОДИН раз по положению прокрутки, остальное его
// отражает.
//
// Содержимое приходит от воркера и пересобирается на каждой модели, поэтому
// списки кадров и вкладок перечитываются в bindAlbum, а не берутся один раз.

const album = document.querySelector('.album');
const albumCount = document.querySelector('.album__count b');
let frames = [];
let tabs = [];

function currentIndex() {
  const mid = album.scrollLeft + album.clientWidth / 2;
  let best = 0, bestDist = Infinity;
  frames.forEach((f, i) => {
    const dist = Math.abs(f.offsetLeft + f.offsetWidth / 2 - mid);
    if (dist < bestDist) { bestDist = dist; best = i; }
  });
  return best;
}

function sync(index) {
  const i = index ?? currentIndex();
  frames.forEach((f, n) => f.classList.toggle('is-current', n === i));
  tabs.forEach((t, n) => t.classList.toggle('is-active', n === i));
  albumCount.textContent = frames.length
    ? `${String(i + 1).padStart(2, '0')} / ${String(frames.length).padStart(2, '0')}`
    : '—';
}

function goTo(i) {
  const at = Math.max(0, Math.min(frames.length - 1, i));
  const f = frames[at];
  if (!f) return;
  album.scrollTo({ left: f.offsetLeft + f.offsetWidth / 2 - album.clientWidth / 2 });
  // Отмечаем сразу: при плавной прокрутке событие придёт через сотни
  // миллисекунд, и всё это время активной была бы чужая вкладка.
  sync(at);
}

/** Перечитывает содержимое альбома и вешает обработчики на свежие элементы. */
function bindAlbum() {
  frames = [...album.querySelectorAll('.frame')];
  tabs = [...document.querySelectorAll('.mattab')];
  tabs.forEach((tab, i) => tab.addEventListener('click', () => goTo(i)));
  frames.forEach((f, i) => {
    f.addEventListener('click', () => goTo(i));
    // У эффекта своя обработка перетаскивания (другой метод замены), и
    // вешать обе значило бы отправить файл дважды по разным путям.
    if (root.dataset.section !== 'particles') bindDrop(f);
    const gear = f.querySelector('.frame__tool');
    if (gear) gear.addEventListener('click', (e) => {
      e.stopPropagation();
      enterTextureEdit(f.dataset.mat);
    });
    // Материал, добавленный в стиль, из него же и убирается — иначе стиль
    // становится ловушкой: добавил лишнее и живи с этим.
    const drop = f.querySelector('.frame__off');
    if (drop) drop.addEventListener('click', async (e) => {
      e.stopPropagation();
      applyView(await api.dropFromStyle(f.dataset.mat));
    });
  });
  sync(0);
}

album.addEventListener('scroll', () => {
  clearTimeout(album._t);
  album._t = setTimeout(sync, 60);
});

// Колесо мыши листает вбок — как _HWheelScrollArea в приложении.
album.addEventListener('wheel', (e) => {
  if (e.deltaX) return;                 // горизонтальный жест трекпада не трогаем
  e.preventDefault();
  album.scrollLeft += e.deltaY;
}, { passive: false });

document.querySelector('.album__step--prev').addEventListener('click', () => goTo(currentIndex() - 1));
document.querySelector('.album__step--next').addEventListener('click', () => goTo(currentIndex() + 1));
bindAlbum();

// ── Режим показа: текстура, модель или обе ──────────────────────────────
const work = document.querySelector('.work');
document.querySelector('.modes').addEventListener('click', async (e) => {
  const btn = e.target.closest('.underlined');
  if (!btn) return;
  document.querySelectorAll('.modes .underlined').forEach((b) => b.classList.remove('is-active'));
  btn.classList.add('is-active');
  work.dataset.view = btn.dataset.view;

  // Вид от первого лица — не другой ракурс, а другая сцена: её собирает
  // отдельный воркер слиянием рук класса с оружием.
  if (btn.dataset.view === 'fp') {
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
  }
});

// ── Что показывать: решает Python ───────────────────────────────────────
// Таблицы правил здесь нет намеренно. api.controls_for(mode) отдаёт готовый
// ответ по тем же условиям, что и приложение (frontend/CONTROLS.md), а
// представление только применяет его. Иначе правила разъедутся.

//: Признак контрола (data-cond) → ключ в ответе Python.
const COND_KEY = {
  gamma: 'gamma',
  hat_paints: 'hat_paints',
  normal: 'normal_map',
  maps: 'material_maps',
  shoulders: 'shoulders',
  load: 'load_model',
  replace: 'replace_model',
  firstperson: 'first_person',
  misc: 'misc',
  styles: 'styles',
  aus: 'teams',
  team: 'teams',
  qc: 'replace_model',
  // Части — это куски декомпилированной геометрии: где нельзя заменить
  // модель, там и делить нечего.
  parts: 'replace_model',
};

//: Скрытый контрол ОБЯЗАН сбросить значение: невидимая галка иначе уезжает
//: в сборку, и результат не совпадает с тем, что человек видел на экране.
//: Так же поступает приложение (apply_mode_restrictions).
const RESET_ON_HIDE = new Set(['shoulders', 'normal', 'maps']);

//: Эти зависят не от режима, а от ЗАГРУЖЕННОЙ модели: есть ли у неё командный
//: вариант, вариантный кадр, служебные материалы. Режим их только разрешает —
//: показывает applyView по ответу view_state. Иначе кнопка мелькала бы до
//: загрузки и обещала то, чего у модели нет.
const MODEL_DRIVEN = new Set(['misc', 'team', 'aus', 'qc', 'styles']);

//: Последний ответ controls_for: applyView сверяется с ним, чтобы не показать
//: в режиме то, что режим запретил.
let modeControls = {};

function applyControls(c) {
  modeControls = c;
  document.querySelectorAll('[data-cond]').forEach((el) => {
    const shown = Boolean(c[COND_KEY[el.dataset.cond]])
      && !MODEL_DRIVEN.has(el.dataset.cond);
    el.hidden = !shown;
    if (!shown && RESET_ON_HIDE.has(el.dataset.cond)) {
      el.querySelectorAll('input[type="checkbox"]').forEach((i) => { i.checked = false; });
    }
  });

  // Разрешения: спрей прибит к 256.
  document.querySelectorAll('input[name="res"]').forEach((r, i) => {
    const value = ['256', '512', '1024', '2048'][i];
    const ok = c.resolutions.includes(value);
    r.disabled = !ok;
    if (!ok && r.checked) document.querySelector('input[name="res"]').checked = true;
  });

  // Формат: список сужается режимом, спрей его ещё и запирает.
  const fmt = document.getElementById('fmt');
  if (c.formats) {
    const keep = fmt.value;
    fmt.innerHTML = '';
    for (const f of c.formats) fmt.append(new Option(f, f));
    if (c.formats.includes(keep)) fmt.value = keep;
  }
  fmt.disabled = Boolean(c.format_locked);

  // Флаги VTF.
  const flagCol = [...document.querySelectorAll('.build__col')]
    .find((col) => col.textContent.includes('Флаги VTF'));
  flagCol.querySelectorAll('input').forEach((b, i) => {
    // Список флагов режима (null — все); Point Sample у скайбокса единственный
    // осмысленный, остальное там выставляет SkyboxService.
    const name = flagCol.querySelectorAll('.check span')[i].textContent;
    const allowed = c.flags === null || c.flags.some((f) => name.toLowerCase().includes(f.toLowerCase()));
    b.disabled = !c.flags_enabled || !allowed;
  });
}

// ── Режим правки настроек текстуры ──────────────────────────────────────
// Шестерёнка на кадре переводит панель сборки в правку ЭТОГО материала:
// глобальные значения стэшатся и возвращаются на выходе. Своя запись
// появляется только от реального изменения контрола — простое открытие
// настройки не создаёт (так же ведёт себя панель приложения).
const editbar = document.getElementById('editbar');

//: Пока не null — панель показывает настройки материала, а не общие.
//: Держит и снимок контролов (вернуть на выходе), и глобальные параметры
//: сборки: собирать во время правки надо ИМИ, а не тем, что на экране.
let texEdit = null;

function buildInputs() {
  return [...document.querySelectorAll('.build__grid input')];
}

function readInputs() {
  return buildInputs().map((i) => (i.type === 'text' ? i.value : i.checked));
}

function writeInputs(values) {
  buildInputs().forEach((i, n) => {
    if (i.type === 'text') i.value = values[n];
    else i.checked = values[n];
  });
}

/** Ставит на контролы настройки материала (что не задано — остаётся общим). */
function applySettings(st) {
  if (!st || !st.size) return;
  const size = Array.isArray(st.size) ? st.size[0] : st.size;
  const index = [256, 512, 1024, 2048].indexOf(Number(size));
  const radios = [...document.querySelectorAll('input[name="res"]')];
  if (index >= 0 && radios[index]) radios[index].checked = true;
  if (st.format) document.getElementById('fmt').value = st.format;

  const flags = new Set(st.flags || []);
  const options = st.options || {};
  for (const col of document.querySelectorAll('.build__col')) {
    const isFlags = col.textContent.includes('Флаги VTF');
    const isOptions = col.textContent.includes('Опции');
    if (!isFlags && !isOptions) continue;
    col.querySelectorAll('.check').forEach((l) => {
      const name = l.querySelector('span').textContent.trim();
      const input = l.querySelector('input');
      input.checked = isFlags ? flags.has(name) : Boolean(options[name]);
    });
  }
}

async function enterTextureEdit(material) {
  // Служебный ключ наружу не отдаём — Python сам подставит главный материал.
  const key = material === SINGLE_TEX ? '' : material;
  if (texEdit === null) {
    texEdit = { key, inputs: readInputs(), global: buildParams() };
  } else {
    texEdit.key = key;
    writeInputs(texEdit.inputs);          // с чужого материала — на общие
  }
  // Показываем то же имя, что на вкладке: служебный ключ человеку ничего
  // не говорит.
  document.getElementById('editmat').textContent =
    material === SINGLE_TEX ? 'текстура' : material;
  editbar.hidden = false;
  if (floating()) build.hidden = false;   // панель должна быть на виду

  const res = await api.textureSettings(key);
  applySettings(res.settings);
}

function exitTextureEdit() {
  if (texEdit === null) return;
  writeInputs(texEdit.inputs);
  texEdit = null;
  editbar.hidden = true;
}

/** Пометка на кадре: у этого материала настройки свои. */
function markBadge(material, badge) {
  const frame = frames.find((f) => f.dataset.mat === material)
             || frames.find((f) => f.dataset.mat === SINGLE_TEX && !material);
  if (!frame) return;
  let el = frame.querySelector('.frame__badge');
  if (!badge) { if (el) el.remove(); return; }
  if (!el) {
    el = document.createElement('span');
    el.className = 'mono frame__badge';
    frame.querySelector('.frame__img').append(el);
  }
  el.textContent = badge;
}

// Любое изменение контрола в режиме правки — это запись настроек материала.
// Вне режима контролы остаются общими и в Python не уходят.
document.querySelector('.build__grid').addEventListener('change', async () => {
  if (texEdit === null) return;
  const params = buildParams({ live: true });
  const res = await api.setTextureSettings(texEdit.key, {
    size: [params.size, params.size],
    format: params.format,
    flags: params.flags,
    options: params.options,
  });
  markBadge(res.material, res.badge);
});

document.getElementById('editdone').addEventListener('click', exitTextureEdit);

document.getElementById('editreset').addEventListener('click', async () => {
  if (texEdit === null) return;
  const res = await api.setTextureSettings(texEdit.key, null);
  markBadge(res.material, '');
  exitTextureEdit();
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

document.getElementById('parts').addEventListener('click', togglePartsMode);

document.getElementById('part-color').addEventListener('input', (e) => {
  armedColor = e.target.value;
  markArmed();
  hintParts('Щёлкай по частям модели — покрасятся в этот цвет');
});

// Сила тонировки общая на предмет: тянуть ползунок ради одной части и потом
// ради другой — не то, чего от него ждут.
document.getElementById('part-tint').addEventListener('change', () => {
  if (partsMaterial !== null) colorParts({});
});

// «Случайно» — не забава: одним нажатием видно, из каких кусков состоит
// модель и что покраска вообще делает.
document.getElementById('parts-random').addEventListener('click', async () => {
  const fresh = await api.parts(partsMaterial);
  if (fresh.error) { hintParts(fresh.error); return; }
  // Не «каждой части случайный цвет»: так соседние куски выпадают одинаковыми
  // и модель выглядит просто перекрашенной. Раздаём цвета по кругу от
  // случайного места — соседи всегда разные.
  const start = Math.floor(Math.random() * PART_COLORS.length);
  const colors = {};
  fresh.parts.forEach((part, index) => {
    colors[part.id] = paintSpec(PART_COLORS[(start + index) % PART_COLORS.length]);
  });
  await colorParts(colors);
  hintParts('Случайная раскраска — щёлкай по частям, чтобы поправить');
});

// Отмена — то, что позволяет пробовать: без неё каждый щелчок по модели
// приходится обдумывать заранее.
async function undoParts() {
  const res = await api.undoParts(partsMaterial);
  if (res.error) { hintParts(res.error); return; }
  applyView(res);
  await refreshParts();
  hintParts('Отменено');
}

document.getElementById('parts-undo').addEventListener('click', undoParts);

document.getElementById('parts-grad').addEventListener('click', (e) => {
  gradientOn = !gradientOn;
  e.target.classList.toggle('is-active', gradientOn);
  document.getElementById('part-color2').hidden = !gradientOn;
  document.getElementById('parts-grad-dir').hidden = !gradientOn;
  hintParts(gradientOn ? 'Градиент: щёлкай по частям — переход из первого цвета'
                       : '');
});

document.getElementById('parts-grad-dir').addEventListener('click', (e) => {
  gradientAcross = !gradientAcross;
  e.target.textContent = gradientAcross ? 'Слева направо' : 'Сверху вниз';
});

document.addEventListener('keydown', (e) => {
  const editing = /^(INPUT|TEXTAREA)$/.test(document.activeElement?.tagName || '');
  if (e.key === 'z' && (e.ctrlKey || e.metaKey) && !editing
      && !document.getElementById('partsbar').hidden) {
    e.preventDefault();
    undoParts();
  }
});

document.getElementById('parts-clear').addEventListener('click', async () => {
  const res = await api.clearParts(partsMaterial);
  if (res.error) { hintParts(res.error); return; }
  applyView(res);
  await refreshParts();
  hintParts('');
});

// Шестерёнки кадров привязывает bindAlbum: кадры пересобираются на каждой
// модели, и статическая привязка отвалилась бы после первой же загрузки.

// ── Карты материала ─────────────────────────────────────────────────────
// Схему (какие карты бывают, что у них настраивается) отдаёт Python: список
// параметров и форматов на странице не дублируется — иначе он разъедется с
// генератором VTF.

const mapsDlg = document.getElementById('maps');

/** Материал, к которому относится правка: тот, что сейчас в альбоме. */
function currentMaterial() {
  const frame = frames[currentIndex()];
  const mat = frame && frame.dataset.mat;
  // Служебный ключ одноматериальной модели наружу не отдаём: пустая строка
  // означает «главный материал», и Python сам его подставит.
  return !mat || mat === SINGLE_TEX ? '' : mat;
}

/** Одна карточка карты. Возвращает функцию-сборщик своей записи. */
function mapCard(spec, saved) {
  const card = document.createElement('div');
  card.className = 'mapcard';

  // Голова — общий чекбокс интерфейса: щелчок по всей строке включает карту.
  const head = document.createElement('label');
  head.className = 'check mapcard__head';
  const on = document.createElement('input');
  on.type = 'checkbox';
  on.checked = spec.vmt_only ? Boolean(saved.enabled)
                             : Boolean(saved.image || saved.derive);
  const title = document.createElement('span');
  title.className = 'mapcard__title';
  title.textContent = spec.title;
  const badge = document.createElement('span');
  badge.className = 'mono mapcard__badge';
  badge.textContent = spec.badge;
  head.append(on, title, badge);
  card.append(head);

  // Подсказка видна ВСЕГДА: она нужна ровно в тот момент, когда решают,
  // включать ли карту, — то есть до включения.
  if (spec.tip) {
    const tip = document.createElement('p');
    tip.className = 'mapcard__tip';
    tip.textContent = spec.tip;
    card.append(tip);
  }

  const body = document.createElement('div');
  body.className = 'mapcard__body';
  card.append(body);

  // Авто-режим: карта выводится из базовой текстуры, файл не нужен.
  let auto = null;
  let threshold = null;
  if (spec.derive) {
    const row = document.createElement('label');
    row.className = 'check';
    auto = document.createElement('input');
    auto.type = 'checkbox';
    auto.checked = Boolean(saved.derive);
    const text = document.createElement('span');
    text.textContent = mapsDlg.dataset.autoLabel;
    row.append(auto, text);
    row.title = mapsDlg.dataset.autoTip || '';
    body.append(row);
  }

  let path = null;
  let fileRow = null;
  if (!spec.vmt_only) {
    fileRow = document.createElement('div');
    fileRow.className = 'mapcard__file';
    path = document.createElement('input');
    path.className = 'input';
    path.type = 'text';
    path.readOnly = true;
    path.placeholder = 'Файл не выбран';
    path.value = saved.image || '';
    const pick = document.createElement('button');
    pick.className = 'textbtn textbtn--sm';
    pick.type = 'button';
    pick.textContent = 'Выбрать';
    const clear = document.createElement('button');
    clear.className = 'textbtn textbtn--sm';
    clear.type = 'button';
    clear.textContent = 'Убрать';
    // Картинку кладём во временную папку и запоминаем ПУТЬ: генератор VTF
    // работает с файлами, а не с содержимым в браузере.
    pick.addEventListener('click', async () => {
      const file = await chooseFile('image/*');
      if (!file) return;
      path.value = await api.upload(file);
    });
    clear.addEventListener('click', () => { path.value = ''; });
    fileRow.append(path, pick, clear);
    body.append(fileRow);
  }

  const params = document.createElement('div');
  params.className = 'mapcard__params';
  const fields = {};

  const cellWith = (labelText, control) => {
    const cell = document.createElement('div');
    cell.className = 'mapcard__cell';
    const label = document.createElement('span');
    label.className = 'label label--inline';
    label.textContent = labelText;
    cell.append(label, control);
    params.append(cell);
    return cell;
  };

  if (spec.derive) {
    threshold = document.createElement('input');
    threshold.className = 'input input--num';
    threshold.type = 'number';
    threshold.min = '0';
    threshold.max = '255';
    threshold.placeholder = '0–255';
    threshold.value = saved.threshold ?? '';
    cellWith(mapsDlg.dataset.thresholdLabel, threshold);
  }

  for (const field of spec.numeric) {
    let input;
    if (field.choices) {
      // Список вариантов оформляем как остальные списки в интерфейсе.
      const box = document.createElement('div');
      box.className = 'select';
      input = document.createElement('select');
      for (const c of field.choices) input.append(new Option(c.label, c.value));
      input.value = saved[field.param] ?? field.default;
      box.append(input);
      cellWith(field.label, box);
    } else {
      input = document.createElement('input');
      input.className = 'input input--num';
      input.type = 'number';
      input.step = '0.1';
      input.value = saved[field.param] ?? field.default;
      cellWith(field.label, input);
    }
    fields[field.param] = input;
  }
  if (params.children.length) body.append(params);

  // Выключенная карта не должна оставлять доступными свои поля: значение,
  // которого не видно в сборке, — тот же несуществующий выбор.
  const sync = () => {
    card.classList.toggle('is-on', on.checked);
    body.hidden = !on.checked;
    if (auto && !on.checked) auto.checked = false;
    const derive = Boolean(auto && auto.checked);
    if (fileRow) fileRow.querySelectorAll('button, input')
                        .forEach((el) => { el.disabled = derive; });
    if (threshold) threshold.disabled = !derive;
  };
  on.addEventListener('change', sync);
  if (auto) auto.addEventListener('change', sync);
  sync();

  return {
    node: card,
    collect() {
      if (!on.checked) return null;
      let entry;
      if (spec.vmt_only) entry = { enabled: true };
      else if (auto && auto.checked) {
        entry = { derive: true };
        if (threshold && threshold.value.trim()) entry.threshold = threshold.value.trim();
      } else {
        if (!path || !path.value) return null;   // включили, но файла нет
        entry = { image: path.value };
      }
      for (const [param, input] of Object.entries(fields)) {
        if (String(input.value).trim()) entry[param] = String(input.value).trim();
      }
      return entry;
    },
  };
}

async function openMaterialMaps() {
  const material = currentMaterial();
  const [schema, saved] = await Promise.all([api.mapSchema(),
                                             api.textureMaps(material)]);

  mapsDlg.dataset.autoLabel = schema.auto_label;
  mapsDlg.dataset.autoTip = schema.auto_tip || '';
  mapsDlg.dataset.thresholdLabel = schema.threshold_label;
  mapsDlg.querySelector('.ask__title').textContent = schema.title;
  document.getElementById('maps-intro').textContent = schema.intro || '';
  document.getElementById('maps-mat').textContent = material || 'главная текстура';

  const list = document.getElementById('maps-list');
  list.innerHTML = '';
  const cards = schema.maps.map((spec) => {
    const card = mapCard(spec, saved[spec.id] || {});
    list.append(card.node);
    return [spec.id, card];
  });

  mapsDlg.showModal();

  const done = (apply) => async () => {
    if (apply) {
      const maps = {};
      for (const [id, card] of cards) {
        const entry = card.collect();
        if (entry) maps[id] = entry;
      }
      const res = await api.setTextureMaps(material, maps);
      const count = Object.keys(res.maps || {}).length;
      say(count ? `Карты материала: ${count}` : 'Карты материала сняты');
    }
    mapsDlg.close();
  };
  document.getElementById('maps-ok').onclick = done(true);
  document.getElementById('maps-cancel').onclick = done(false);
}

// ── Редактор VMT ────────────────────────────────────────────────────────
// Открывается сохранённая правка, иначе — оригинал из игры. Проверку
// синтаксиса делает Python при сохранении: сломанный VMT в игре даёт
// невидимый материал, и ловить это лучше до сборки.

const vmtDlg = document.getElementById('vmtdlg');
const vmtText = document.getElementById('vmt-text');
const vmtHl = document.getElementById('vmt-hl');
const vmtStatus = document.getElementById('vmt-status');
let vmtState = { material: '', original: '' };

//: {$параметр: описание} — тот же словарь, что знает редактор в приложении.
let vmtDocs = {};

//: Кавычки экранируем наравне со скобками: тот же текст уходит в атрибут
//: title, и незакрытая кавычка ломала бы разметку зеркала.
const escapeHtml = (text) => String(text).replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;',
            '"': '&quot;', "'": '&#39;' }[c]));

/**
 * Перерисовывает зеркало под полем.
 *
 * Подсветка тут вторична: главное — что $параметр становится отдельным
 * элементом, и на него можно навести мышь. Описание берётся из Python, поэтому
 * подсказка не может разойтись с тем, что редактор действительно знает.
 */
function paintVmt() {
  const text = vmtText.value;
  let html = '';
  // Один проход: комментарий до конца строки, строка в кавычках, $параметр.
  const re = /(\/\/[^\n]*)|("(?:[^"\\\n]|\\.)*")|(\$\w+)/g;
  let last = 0;
  for (let m = re.exec(text); m; m = re.exec(text)) {
    html += escapeHtml(text.slice(last, m.index));
    const chunk = escapeHtml(m[0]);
    // Параметр в VMT почти всегда В КАВЫЧКАХ ("$basetexture" "models/..."),
    // поэтому кавычки с $-именем внутри — это параметр, а не строка значения.
    const quotedParam = m[2] && m[2].match(/^"(\$\w+)"$/);
    const param = m[3] || (quotedParam && quotedParam[1]);
    if (m[1]) html += `<span class="vmt-com">${chunk}</span>`;
    else if (param) {
      const doc = vmtDocs[param.toLowerCase()];
      html += doc
        ? `<span class="vmt-par" title="${escapeHtml(param + ' — ' + doc)}">${chunk}</span>`
        : `<span class="vmt-par">${chunk}</span>`;
    } else html += `<span class="vmt-str">${chunk}</span>`;
    last = m.index + m[0].length;
  }
  // <pre> съедает последний перевод строки, а поле его сохраняет: без добавки
  // зеркало короче на строку, и в самом низу подсветка отстаёт от текста.
  vmtHl.innerHTML = html + escapeHtml(text.slice(last)) + '\n';
  vmtHl.scrollTop = vmtText.scrollTop;
  vmtHl.scrollLeft = vmtText.scrollLeft;
}

vmtText.addEventListener('input', paintVmt);
// Зеркало прокручивается вместе с полем, иначе подсветка съезжает.
vmtText.addEventListener('scroll', () => {
  vmtHl.scrollTop = vmtText.scrollTop;
  vmtHl.scrollLeft = vmtText.scrollLeft;
});

//: Что показывает строка состояния, когда мышь не на параметре.
let vmtBaseStatus = { text: '', kind: '' };

function vmtSay(text, kind = '') {
  vmtBaseStatus = { text, kind };
  vmtStatus.textContent = text;
  vmtStatus.className = 'label vmt__status' + (kind ? ' is-' + kind : '');
}

// Наведение на $параметр объясняет, что он делает. Строкой состояния, а не
// системной подсказкой: она появляется сразу и читается там же, где остальные
// сообщения редактора. Атрибут title при этом остаётся — для тех, кто ждёт
// привычного всплывания.
vmtHl.addEventListener('mouseover', (e) => {
  const par = e.target.closest('.vmt-par');
  if (!par || !par.title) return;
  vmtStatus.textContent = par.title;
  vmtStatus.className = 'label vmt__status is-good';
});

vmtHl.addEventListener('mouseout', (e) => {
  if (!e.target.closest('.vmt-par')) return;
  vmtStatus.textContent = vmtBaseStatus.text;
  vmtStatus.className = 'label vmt__status'
    + (vmtBaseStatus.kind ? ' is-' + vmtBaseStatus.kind : '');
});

async function openVmtEditor() {
  const [res, params] = await Promise.all([api.openVmt(currentMaterial()),
                                           api.vmtParams()]);
  if (res.error) { say(res.error); return; }
  vmtDocs = Object.fromEntries(params.map((p) => [p.param.toLowerCase(), p.doc]));

  vmtState = { material: res.material, original: res.original };
  document.getElementById('vmt-mat').textContent = res.material;
  vmtText.value = res.content;
  paintVmt();
  vmtSay(res.edited ? 'Своя правка активна' : 'Показан игровой оригинал',
         res.edited ? 'good' : '');
  document.getElementById('vmt-reset').hidden = !res.edited;
  vmtDlg.showModal();
  // Прокрутка сбрасывается ТОЛЬКО после показа: у скрытого поля нет раскладки,
  // и присвоение до showModal терялось — файл открывался на хвосте.
  vmtText.scrollTop = 0;
  vmtText.setSelectionRange(0, 0);
}

document.getElementById('vmt-save').addEventListener('click', async () => {
  // Оригинал отправляем вместе с правкой: Python фиксирует его бэкапом один
  // раз, иначе «как в игре» после второй правки вернуло бы первую.
  const res = await api.saveVmt(vmtState.material, vmtText.value, vmtState.original);
  if (res.error) { vmtSay(res.error, 'bad'); return; }
  vmtText.value = res.content;          // с дописанным ватермарком
  paintVmt();
  document.getElementById('vmt-reset').hidden = false;
  vmtSay('Сохранено', 'good');
});

document.getElementById('vmt-reset').addEventListener('click', async () => {
  const res = await api.resetVmt(vmtState.material);
  if (res.error) { vmtSay(res.error, 'bad'); return; }
  vmtText.value = vmtState.original;
  paintVmt();
  document.getElementById('vmt-reset').hidden = true;
  vmtSay('Правка удалена, показан игровой оригинал');
});

document.getElementById('vmt-close').addEventListener('click', () => vmtDlg.close());

// Ctrl+S — привычка любого, кто правит текст. Браузерное «сохранить страницу»
// здесь ни к чему.
vmtText.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
    e.preventDefault();
    document.getElementById('vmt-save').click();
  }
});

// ── Своя модель и её QC ─────────────────────────────────────────────────
// Замена включается самим фактом загрузки: отдельной галочки нет ни здесь, ни
// в приложении. Тип модели («готова» / «только геометрия») решает всё
// дальнейшее, поэтому спрашиваем до показа.

async function replaceModel() {
  const file = await chooseFile('.smd');
  if (!file) return;

  say('Конвертация ' + file.name + '…');
  const path = await api.upload(file);
  const first = await api.loadCustomModel(path);
  if (first.error) { say(first.error); return; }

  let keep = true;
  if (first.ask_keep) {
    const answer = await ask({
      title: 'Что это за модель',
      text: first.materials.length
        ? 'Материалы модели: ' + first.materials.join(', ')
        : 'Материалов в модели не нашлось.',
      list: [
        { label: 'Готовая — со своими материалами',
          value: 'keep',
          hint: 'Карточки возьмутся из самой модели, будет доступна правка QC' },
        { label: 'Только геометрия — текстуры игровые',
          value: 'geometry',
          hint: 'На экране ваша геометрия, карточки из игрового QC' },
      ],
      ok: 'Загрузить',
    });
    if (!answer) return;
    keep = answer === 'keep';
  }

  const res = await api.loadCustomModel(path, keep);
  if (res.error) { say(res.error); return; }
  say(keep ? 'Своя модель: материалы её собственные'
           : 'Своя модель: геометрия ваша, текстуры игровые');
  refreshView();
}

/**
 * Показ чужого мода из VPK.
 *
 * Предмет не меняется: мод накладывается поверх текущего выбора, его модель и
 * текстуры становятся тем, что на экране, а сам файл уходит в сборку
 * источником.
 */
//: Имя показанного мода — заголовок называет то, что выбрано.
let modName = '';

/**
 * Подпись внизу: где найдена игра.
 *
 * Не украшение — без пути к TF2 не работает ничего, и узнать об этом лучше
 * сразу, а не по ошибке на первой же загрузке модели.
 */
async function showTf2Path() {
  const el = document.querySelector('.dock__tf2');
  const paths = await api.call('tf2_paths');
  el.textContent = paths.error
    ? 'TF2 не найдена — укажите папку игры в настройках'
    : 'TF2 найдена · ' + paths.root;
}

// ── Настройки ───────────────────────────────────────────────────────────
// Конфиг общий с окном приложения, поэтому здесь только показ и запись: что
// считать допустимым значением (пустая папка экспорта, разбор списка
// исключений), решает Python.

const cfgDlg = document.getElementById('cfgdlg');

function fillSelect(id, options, value) {
  const el = document.getElementById(id);
  el.innerHTML = '';
  for (const o of options) el.append(new Option(o.label ?? o, o.value ?? o));
  el.value = value;
}

async function openSettings() {
  const cfg = await api.settings();
  const v = cfg.values;

  document.getElementById('cfg-tf2').value = v.tf2_game_folder || '';
  document.getElementById('cfg-export').value = v.export_folder || '';
  fillSelect('cfg-format', cfg.formats, v.export_image_format);
  fillSelect('cfg-lang', cfg.languages, v.language);
  fillSelect('cfg-theme', cfg.themes, v.theme);
  fillSelect('cfg-bypass', cfg.bypass, v.sv_pure_bypass);
  document.getElementById('cfg-bypass-tip').textContent = cfg.bypass_tip || '';
  document.getElementById('cfg-save').checked = Boolean(v.save_edits);
  document.getElementById('cfg-tree').checked = Boolean(v.particles_group_tree);
  document.getElementById('cfg-temp').checked = Boolean(v.keep_temp_files);
  document.getElementById('cfg-debug').checked = Boolean(v.debug_mode);
  document.getElementById('cfg-blacklist').value =
    (v.material_blacklist || []).join('\\n');
  // Язык и тема относятся к ОКНУ приложения: страница живёт со своей темой,
  // и обещать её смену здесь было бы неправдой.
  document.getElementById('cfg-note').textContent = 'общие с приложением';

  cfgDlg.showModal();
}

document.getElementById('cfg-save').addEventListener('click', async () => {
  const res = await api.setSettings({
    tf2_game_folder: document.getElementById('cfg-tf2').value,
    export_folder: document.getElementById('cfg-export').value,
    export_image_format: document.getElementById('cfg-format').value,
    language: document.getElementById('cfg-lang').value,
    theme: document.getElementById('cfg-theme').value,
    sv_pure_bypass: document.getElementById('cfg-bypass').value,
    save_edits: document.getElementById('cfg-save').checked,
    particles_group_tree: document.getElementById('cfg-tree').checked,
    keep_temp_files: document.getElementById('cfg-temp').checked,
    debug_mode: document.getElementById('cfg-debug').checked,
    material_blacklist: document.getElementById('cfg-blacklist').value,
  });
  if (res.error) { say(res.error); return; }
  cfgDlg.close();
  say('Настройки сохранены');
  // Путь к игре мог измениться — подпись внизу обязана это показать.
  showTf2Path();
});

document.getElementById('cfg-cancel').addEventListener('click', () => cfgDlg.close());
document.getElementById('opencfg').addEventListener('click', openSettings);

// ── Диагностика мода ────────────────────────────────────────────────────
// Проверяет СОБРАННЫЙ файл, а не состояние сеанса: смотреть можно любой VPK,
// в том числе чужой. Отчёт приходит событием — проверка идёт в своём потоке.

const diagDlg = document.getElementById('diagdlg');

function diagSay(text, kind = '') {
  const el = document.getElementById('diag-status');
  el.textContent = text;
  el.className = 'label vmt__status' + (kind ? ' is-' + kind : '');
}

async function pickForDiagnosis() {
  const file = await chooseFile('.vpk');
  if (!file) return;
  document.getElementById('diag-file').textContent = file.name;
  document.getElementById('diag-list').innerHTML = '';
  diagSay('Проверка…');
  const res = await api.diagnose(await api.upload(file));
  if (res.error) diagSay(res.error, 'bad');
}

/** Раскладывает отчёт: сначала итог, потом находки в порядке важности. */
function showReport(ev) {
  const list = document.getElementById('diag-list');
  list.innerHTML = '';
  if (!ev.ok) { diagSay(ev.message || 'Проверка не удалась', 'bad'); return; }

  const r = ev.report;
  diagSay(r.healthy
    ? 'Проблем не найдено'
    : `Ошибок: ${r.errors} · предупреждений: ${r.warnings}`,
    r.healthy ? 'good' : 'bad');

  for (const f of r.findings) {
    const row = document.createElement('div');
    row.className = 'finding finding--' + f.severity;

    const title = document.createElement('div');
    title.className = 'finding__title';
    title.textContent = f.title;
    row.append(title);

    if (f.location) {
      const where = document.createElement('span');
      where.className = 'mono finding__where';
      where.textContent = f.location;
      row.append(where);
    }
    if (f.detail) {
      const detail = document.createElement('p');
      detail.className = 'finding__detail';
      detail.textContent = f.detail;
      row.append(detail);
    }
    if (f.fix) {
      const fix = document.createElement('p');
      fix.className = 'finding__fix';
      fix.textContent = 'Что делать: ' + f.fix;
      row.append(fix);
    }
    list.append(row);
  }
}

document.getElementById('diag-pick').addEventListener('click', pickForDiagnosis);
document.getElementById('diag-close').addEventListener('click', () => diagDlg.close());

// ── Редактор QC ─────────────────────────────────────────────────────────
const qcDlg = document.getElementById('qcdlg');
const qcText = document.getElementById('qc-text');

function qcSay(text, kind = '') {
  const el = document.getElementById('qc-status');
  el.textContent = text;
  el.className = 'label vmt__status' + (kind ? ' is-' + kind : '');
}

async function openQcEditor() {
  const res = await api.qcText();
  if (res.error) { say(res.error); return; }
  qcText.value = res.text;
  document.getElementById('qc-state').textContent =
    res.edited ? 'своя правка' : 'авто-QC';
  qcSay(res.edited ? 'Показана ваша правка' : 'Показан исправленный авто-QC');
  document.getElementById('qc-reset').hidden = !res.edited;
  qcDlg.showModal();
  qcText.scrollTop = 0;
  qcText.setSelectionRange(0, 0);
}

document.getElementById('qc-save').addEventListener('click', async () => {
  const res = await api.saveQc(qcText.value);
  if (res.error) { qcSay(res.error, 'bad'); return; }
  document.getElementById('qc-reset').hidden = !res.edited;
  document.getElementById('qc-state').textContent = res.edited ? 'своя правка' : 'авто-QC';
  qcSay('Сохранено', 'good');
});

document.getElementById('qc-reset').addEventListener('click', async () => {
  await api.saveQc('');
  const res = await api.qcText();
  qcText.value = res.text || '';
  document.getElementById('qc-reset').hidden = true;
  document.getElementById('qc-state').textContent = 'авто-QC';
  qcSay('Возвращён авто-QC');
});

document.getElementById('qc-close').addEventListener('click', () => qcDlg.close());

qcText.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
    e.preventDefault();
    document.getElementById('qc-save').click();
  }
});

// Действия над моделью под вьюпортом.
document.getElementById('model-acts').addEventListener('click', (e) => {
  const btn = e.target.closest('.textbtn');
  if (!btn) return;
  if (btn.dataset.cond === 'replace') replaceModel();
  else if (btn.dataset.cond === 'qc') openQcEditor();
});

// Кнопки под альбомом: обе про материал, который сейчас перед глазами.
// Пометки «свои настройки» переживают перерисовку альбома: карточки
// пересобираются на каждой модели, а записи живут в Python.
async function restoreBadges() {
  const badges = await api.textureBadges();
  for (const [material, badge] of Object.entries(badges)) markBadge(material, badge);
}

document.querySelector('.half--flat .acts').addEventListener('click', (e) => {
  const btn = e.target.closest('.textbtn');
  if (!btn) return;
  if (btn.dataset.cond === 'maps') openMaterialMaps();
  else if (btn.id === 'vmt') openVmtEditor();
});

// ── Сборка ──────────────────────────────────────────────────────────────
// Что собирать, знает Python: он смотрит, какие текстуры пользователь положил
// на какие материалы. Отсюда уходят только параметры формата.

/**
 * Параметры сборки с панели.
 *
 * Пока открыта правка настроек материала, на контролах показаны ЕГО значения,
 * а собирать надо общими — их и отдаём из снимка. Иначе настройки одной
 * текстуры молча стали бы настройками всего мода. Так же поступает
 * settings_panel.get_settings в приложении.
 *
 * live: true — прочитать именно то, что на контролах (это и есть правка).
 */
function buildParams({ live = false } = {}) {
  if (!live && texEdit !== null) return { ...texEdit.global };

  const col = (title) => [...document.querySelectorAll('.build__col')]
    .find((c) => c.textContent.includes(title));
  const checked = (title) => [...col(title).querySelectorAll('.check')]
    .filter((l) => l.querySelector('input').checked)
    .map((l) => l.querySelector('span').textContent.trim());

  const res = [...document.querySelectorAll('input[name="res"]')]
    .findIndex((r) => r.checked);
  return {
    size: [256, 512, 1024, 2048][res < 0 ? 1 : res],
    format: document.getElementById('fmt').value,
    filename: document.getElementById('out').value,
    flags: checked('Флаги VTF'),
    options: Object.fromEntries(checked('Опции').map((n) => [n, true])),
    // Краски шапки — не флаг VTF: они решают, как красится материал, поэтому
    // едут отдельным полем, а не в общем наборе опций.
    hat_paints: document.getElementById('hat-paints').checked,
    // Классы мультиклассовой шапки: пусто — значит все.
    hat_classes: hatClasses(),
    lang: 'ru',
  };
}

const buildBtn = document.querySelector('.btn--primary');
buildBtn.addEventListener('click', async () => {
  // У частиц своя сборка: PCF плюс заменённые текстуры, и перед ней —
  // проверка, потому что типовые ошибки эффекта видно только в игре.
  if (root.dataset.section === 'particles') { await buildParticles(); return; }
  const res = await api.build(buildParams());
  if (res.error) { setStatus(res.error, false); return; }
  setStatus('Сборка…', true);
});

/**
 * Вопрос сборки: чем красить материал, для которого текстуры нет.
 *
 * Три варианта — те же, что в окне приложения: оставить игровой оригинал (в мод
 * он не попадёт), скопировать главную текстуру или дать свою картинку.
 * «Ко всем» запоминает выбор до конца этой сборки.
 */
async function askForTexture(material) {
  const answer = await ask({
    title: 'Чем красить «' + material + '»',
    text: 'Своей текстуры для этого материала нет.',
    list: [
      { label: 'Оставить игровую', value: 'game',
        hint: 'Материал не попадёт в мод — в игре останется стоковый' },
      { label: 'Скопировать главную', value: 'main',
        hint: 'На этот материал ляжет та же текстура, что и на основной' },
      { label: 'Выбрать файл…', value: 'file',
        hint: 'Своя картинка именно для этого материала' },
      { label: 'Оставить игровую — и так для всех', value: 'game-all' },
      { label: 'Скопировать главную — и так для всех', value: 'main-all' },
    ],
    ok: 'Ответить',
  });

  // Окно закрыли — сборка ждать бесконечно не должна: отвечаем безопасным
  // вариантом (игровой оригинал ничего не портит).
  const choice = answer || 'game';
  if (choice === 'file') {
    const file = await chooseFile('image/*');
    if (!file) { await api.answerTexture('game'); return; }
    await api.answerTexture('file', await api.upload(file));
    return;
  }
  const [kind, all] = choice.split('-');
  await api.answerTexture(kind, '', all === 'all');
}

function setStatus(text, busy) {
  const el = document.querySelector('.dock__state');
  el.textContent = text;
  buildBtn.disabled = Boolean(busy);
}

// ── Журнал ──────────────────────────────────────────────────────────────
// Показывает, что уходит в Python и что приходит обратно. Направление важнее
// уровня: сразу видно, кто кого позвал.
const logBody = document.getElementById('logbody');
const consoleBox = document.getElementById('console');
const MAX_LOG = 400;

api.setLogSink((dir, text, kind) => {
  const line = document.createElement('div');
  line.className = 'logline' + (dir === '↓' ? ' logline--in' : '')
                              + (kind === 'err' ? ' logline--err' : '');
  const t = new Date();
  line.innerHTML = '<span class="logline__time"></span>'
                 + '<span class="logline__dir"></span>'
                 + '<span class="logline__text"></span>';
  line.querySelector('.logline__time').textContent =
    String(t.getHours()).padStart(2,'0') + ':' +
    String(t.getMinutes()).padStart(2,'0') + ':' +
    String(t.getSeconds()).padStart(2,'0');
  line.querySelector('.logline__dir').textContent = dir;
  line.querySelector('.logline__text').textContent = text;

  const внизу = logBody.scrollTop + logBody.clientHeight >= logBody.scrollHeight - 30;
  logBody.appendChild(line);
  while (logBody.children.length > MAX_LOG) logBody.firstChild.remove();
  // Прокручиваем только если человек и так смотрел конец: иначе журнал
  // выдёргивал бы его из места, которое он читает.
  if (внизу) logBody.scrollTop = logBody.scrollHeight;
});

const toggleConsole = () => { consoleBox.hidden = !consoleBox.hidden; };
document.getElementById('logclose').addEventListener('click', toggleConsole);
document.getElementById('logclear').addEventListener('click', () => { logBody.innerHTML = ''; });
document.querySelector('.dock__state').addEventListener('click', toggleConsole);
document.addEventListener('keydown', (e) => {
  if (e.key === '`' || e.key === 'ё') { e.preventDefault(); toggleConsole(); }
});

// ── Тема ────────────────────────────────────────────────────────────────
// Вьювер живёт в своём документе и токенов страницы не видит — цвет фона ему
// передаём явно, при старте и при каждой смене темы.
function syncViewerTheme() {
  const bg = getComputedStyle(root).getPropertyValue('--viewport').trim();
  withViewer((w) => w.setViewerBackground && w.setViewerBackground(bg));
}

const themeBtn = document.getElementById('theme');
themeBtn.addEventListener('click', () => {
  const dark = root.dataset.theme === 'dark';
  root.dataset.theme = dark ? 'light' : 'dark';
  themeBtn.textContent = dark ? 'Тёмная' : 'Светлая';
  syncViewerTheme();
});


// ═══════════════════════════════════════════════════════════════════════════
// Данные из Python
// ═══════════════════════════════════════════════════════════════════════════
// Каталог, фильтры и правила видимости приходят из src/app/api.py. Здесь
// только отрисовка: ни списков предметов, ни условий «что показывать» в
// представлении быть не должно — иначе они разъедутся с приложением.

//: Служебный ключ одноматериальной модели (SINGLE_TEX_KEY в домене). Именем
//: меша он не является — во вьювер его отдавать нельзя.
const SINGLE_TEX = '__single__';

const els = {
  cat:   document.getElementById('cat'),
  fClass:document.getElementById('f-class'),
  fHat:  document.getElementById('f-hat'),
  fType: document.getElementById('f-type'),
  catLabel: document.getElementById('catlabel'),
  note:  document.getElementById('cat-note'),
  grid:  document.getElementById('grid'),
};

const sel = { section: 'weapons', category: 'weapon', cls: null,
              type: null, mode: 'normal', query: '' };

/** Рисует ряд фильтров; null-кнопка «Все» снимает ограничение. */
function fillFilters(row, list, chosen, onPick) {
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

function fillGrid(list) {
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
async function showModLibrary() {
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

/** Размер файла человеческим языком: точность тут не нужна, порядок — да. */
function fileSize(bytes) {
  const mb = bytes / (1024 * 1024);
  return mb >= 1 ? mb.toFixed(1) + ' МБ' : Math.max(1, Math.round(bytes / 1024)) + ' КБ';
}

/** Открывает мод из библиотеки. */
async function openMod(mod) {
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
  modName = name;
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

// ── Загрузка превью ──────────────────────────────────────────────────────
// Модель приезжает не ответом на запрос, а потоком событий: сначала прогресс,
// потом готовая модель, потом материалы. Поэтому здесь только запуск, а
// показывает результат обработчик событий ниже.

const stage = {
  hint: document.getElementById('stagehint'),
  tabs: document.querySelector('.mattabs'),
  album: document.querySelector('.album'),
  frame: document.getElementById('viewer'),
  pframe: document.getElementById('particles'),
};

function say(text) {
  stage.hint.textContent = text;
  stage.hint.hidden = !text;
}

/**
 * Окно вьювера. Это тот же viewer3d.html, что работает в приложении, и у него
 * есть готовый window-API (loadModelFromContent, applyMaterialMap, ...).
 * Возвращает null, пока iframe не загрузился.
 */
function viewer() {
  const w = stage.frame.contentWindow;
  return (w && typeof w.loadModelFromContent === 'function') ? w : null;
}

/**
 * Окно движка частиц (particles3d.html). Тот же файл, что в приложении:
 * принимает {systems, materials} и сам крутит эффект.
 */
function particles() {
  const w = stage.pframe.contentWindow;
  return (w && typeof w.loadParticleData === 'function') ? w : null;
}

/** Выполняет действие над движком частиц, дождавшись загрузки iframe. */
function withParticles(fn) {
  const w = particles();
  if (w) { fn(w); return; }
  stage.pframe.addEventListener('load', () => {
    const ready = particles();
    if (ready) fn(ready);
  }, { once: true });
}

/** Выполняет действие над вьювером, дождавшись его готовности. */
function withViewer(fn) {
  const w = viewer();
  if (w) { fn(w); return; }
  // Первый показ может опередить загрузку iframe — ждём его один раз.
  stage.frame.addEventListener('load', () => {
    const ready = viewer();
    if (ready) fn(ready);
  }, { once: true });
}

//: Запросы состояния идут пачками (materials, blu_materials, australium
//: приходят подряд) — склеиваем их в один, иначе альбом перерисуется трижды.
let viewTimer = null;

function refreshView() {
  clearTimeout(viewTimer);
  viewTimer = setTimeout(async () => {
    applyView(await api.viewState());
  }, 80);
}

// ── Части модели ────────────────────────────────────────────────────────
// Материал у оружия почти всегда один: «покрасить только ствол» — это кусок
// геометрии, а не второй материал. Разбор и склейку делает Python, страница
// показывает список, включает подсветку во вьювере и передаёт файл.

let partsMaterial = null;   // материал разобранной модели; null — не разбирали

/** Включает и выключает режим частей. */
//: Готовые цвета: пять оттенков, которыми чаще всего и красят.
const PART_COLORS = ['#c83c3c', '#3c6ec8', '#3ca05a', '#d2a03c', '#2a2a2a'];

let armedColor = '';      // цвет, которым красит щелчок; пусто — цвета нет
let partsBoxes = {};      // {часть: место на развёртке} — для подсветки текстуры
let gradientOn = false;   // красить переходом из первого цвета во второй
let gradientAcross = false;   // направление перехода

/** Включает и выключает режим частей. */
async function togglePartsMode() {
  const bar = document.getElementById('partsbar');
  if (!bar.hidden) { closeParts(); return; }
  const res = await loadParts();
  if (res && res.parts.length < 2) {
    hintParts('Эта модель — один цельный кусок, делить нечего');
  }
}

/**
 * Разбирает модель на части и включает подсветку.
 *
 * Зовётся и по кнопке, и вьювером, когда на модель ТАЩАТ картинку: разбор
 * стоит около сотой доли секунды, и заставлять ради него нажимать кнопку —
 * значит терять тот единственный момент, когда подсветка что-то объясняет.
 */
async function loadParts() {
  const res = await api.parts();
  if (res.error) { hintParts(res.error); return null; }

  partsMaterial = res.material;
  partsBoxes = Object.fromEntries(res.parts.map((p) => [p.id, p.bbox]));
  showParts(res);
  showPalette(res);

  const w = viewer();
  if (w) {
    // Карту «треугольник → часть» вьювер получает по имени материала: у него
    // геометрия сгруппирована так же, как её отдал Python.
    w.setModelParts({ [res.material]: res.tri_part });
    w.setPartsMode(true);
  }
  return res;
}

/**
 * Связывает вьювер с частями.
 *
 * Ставится на КАЖДУЮ модель, а не по кнопке: перетаскивание картинки на кусок
 * должно работать сразу — иначе про части узнают, только случайно нажав
 * кнопку.
 */
function bindParts(w) {
  // Разбор относился к ПРОШЛОЙ модели: у новой под тем же номером другой кусок.
  closeParts();
  w.setModelParts(null);
  w.onPartsNeeded = () => { if (partsMaterial === null) loadParts(); };
  w.onPartHover = (part) => spotlightPart(part);
  w.onPartDropped = (material, part, file) => paintPart(part, file);
  w.onPartPicked = (material, part) => {
    if (armedColor) colorParts({ [part]: paintSpec(armedColor) });
    else paintPart(part);
  };
}

/**
 * Показывает место части НА ТЕКСТУРЕ.
 *
 * Связь «кусок модели ↔ участок картинки» иначе видна только тому, кто сам
 * делал развёртку. Наведение показывает её обеим сторонам сразу: и в 3D, и на
 * кадре слева.
 */
function spotlightPart(part) {
  const frame = [...document.querySelectorAll('.frame')]
    .find((f) => f.dataset.mat === partsMaterial)
    || document.querySelector('.frame.is-current');
  document.querySelectorAll('.frame__uv').forEach((b) => b.remove());
  document.querySelectorAll('#partsbar .tag').forEach((b) => {
    b.classList.toggle('is-hover', Number(b.dataset.part) === part);
  });
  if (part === null || part === undefined || !frame) return;

  const box = (partsBoxes || {})[part];
  if (!box) return;
  const [u0, v0, u1, v1] = box;
  const spot = document.createElement('div');
  spot.className = 'frame__uv';
  // Развёртка считает v снизу, страница — сверху.
  spot.style.left = (u0 * 100) + '%';
  spot.style.top = ((1 - v1) * 100) + '%';
  spot.style.width = ((u1 - u0) * 100) + '%';
  spot.style.height = ((v1 - v0) * 100) + '%';
  frame.querySelector('.frame__img').appendChild(spot);
}

/** Подсказка живёт рядом с частями, а не поперёк модели. */
function hintParts(text) {
  const hint = document.getElementById('parts-hint');
  if (hint) hint.textContent = text || '';
}

/**
 * Палитра: выбранный цвет красит щелчком по куску модели.
 *
 * Цвет, а не диалог с файлом, стоит первым: перекрасить деталь хочется чаще,
 * чем нарисовать на ней свою картинку, и это происходит мгновенно.
 */
function showPalette(res) {
  const row = document.getElementById('partspaint');
  row.hidden = false;
  row.querySelectorAll('.parts__swatch').forEach((b) => b.remove());

  const custom = document.getElementById('part-color');
  PART_COLORS.forEach((color) => {
    const b = document.createElement('button');
    b.className = 'parts__swatch';
    b.type = 'button';
    b.style.background = color;
    b.dataset.color = color;
    b.title = 'Красить этим цветом';
    b.addEventListener('click', () => armColor(color));
    row.insertBefore(b, custom);
  });

  const tint = document.getElementById('part-tint');
  tint.value = Math.round((res.tint || 1) * 100);
  markArmed();
}

/** Запоминает цвет щелчка. Повторный щелчок по тому же — выключает. */
function armColor(color) {
  armedColor = (armedColor === color) ? '' : color;
  markArmed();
  hintParts(armedColor
    ? 'Щёлкай по частям модели — покрасятся в этот цвет'
    : 'Перетащи картинку на часть модели или выбери цвет');
}

function markArmed() {
  document.querySelectorAll('#partspaint .parts__swatch').forEach((b) => {
    b.classList.toggle('is-active', b.dataset.color === armedColor);
  });
  const custom = document.getElementById('part-color');
  custom.classList.toggle('is-active', armedColor === custom.value);
}

/** Выходит из режима частей: покраска остаётся, уходит только полоса. */
function closeParts() {
  const bar = document.getElementById('partsbar');
  bar.querySelectorAll('.tag').forEach((b) => b.remove());
  bar.hidden = true;
  document.getElementById('partspaint').hidden = true;
  armedColor = '';
  gradientOn = false;
  document.getElementById('parts-grad').classList.remove('is-active');
  document.getElementById('part-color2').hidden = true;
  document.getElementById('parts-grad-dir').hidden = true;
  hintParts('');
  spotlightPart(null);
  partsMaterial = null;
  partsBoxes = {};
  const w = viewer();
  if (w) w.setPartsMode(false);
}

/** Полоса частей: крупные первыми, покрашенные помечены. */
function showParts(res) {
  const bar = document.getElementById('partsbar');
  bar.querySelectorAll('.tag').forEach((b) => b.remove());
  bar.hidden = false;

  res.parts.forEach((part, order) => {
    const b = document.createElement('button');
    b.className = 'tag' + (part.image || part.color ? ' is-painted' : '')
      + (part.shared.length ? ' tag--shared' : '');
    b.dataset.part = part.id;
    // «0%» читается как поломка: у винтика доля развёртки и правда меньше
    // процента, но он существует и покрасить его можно.
    const share = part.area >= 0.01 ? Math.round(part.area * 100) + '%' : '<1%';
    b.textContent = 'Часть ' + (order + 1) + ' · ' + share;
    // Куски, делящие развёртку, в игре красятся вместе — сказать об этом надо
    // до того, как человек нарисует и удивится.
    if (part.shared.length) {
      b.title = 'Эта часть делит развёртку с другими: в игре они покрасятся '
        + 'вместе, разными их сделать нельзя';
    }
    // Наведение на пункт списка подсвечивает кусок на модели: иначе «Часть 3»
    // — это просто номер, и какой именно кусок за ним, узнать неоткуда.
    b.addEventListener('mouseenter', () => {
      viewer()?.highlightPart(part.id);
      spotlightPart(part.id);
    });
    b.addEventListener('mouseleave', () => {
      viewer()?.highlightPart(null);
      spotlightPart(null);
    });
    b.addEventListener('click', (e) => {
      if (e.target.classList.contains('parts__x')) return;
      // С выбранным цветом щелчок красит; без него — спрашивает картинку.
      if (armedColor) colorParts({ [part.id]: paintSpec(armedColor) });
      else paintPart(part.id);
    });
    if (part.color) {
      const dot = document.createElement('span');
      dot.className = 'parts__dot';
      dot.style.background = part.color;
      b.appendChild(dot);
    }
    if (part.image || part.color) {
      const x = document.createElement('button');
      x.className = 'parts__x';
      x.type = 'button';
      x.textContent = '\u00d7';
      x.title = 'Вернуть этой части игровую текстуру';
      x.addEventListener('click', () => (part.color
        ? colorParts({ [part.id]: null })
        : paintPart(part.id, null)));
      b.appendChild(x);
    }
    bar.appendChild(b);
  });
}

/**
 * Чем красить: сплошной цвет или градиент.
 *
 * Градиент строится по месту ЧАСТИ на развёртке, поэтому странице достаточно
 * назвать два цвета и направление — остальное считает Python.
 */
function paintSpec(color) {
  if (!gradientOn) return color;
  return {
    color,
    color2: document.getElementById('part-color2').value,
    horizontal: gradientAcross,
  };
}

/** Красит части: {часть: цвет}, значение null снимает цвет. */
async function colorParts(colors) {
  const strength = Number(document.getElementById('part-tint').value) / 100;
  const res = await api.setPartColors(partsMaterial, colors, strength);
  if (res.error) { hintParts(res.error); return; }
  applyView(res);
  await refreshParts();
}

/** Перечитывает список частей — после любой покраски. */
async function refreshParts() {
  const fresh = await api.parts(partsMaterial);
  if (!fresh.error) showParts(fresh);
  return fresh;
}

/** Кладёт (или снимает) картинку на часть и обновляет полосу. */
async function paintPart(part, file = undefined) {
  const apply = async (file) => {
    hintParts('Наложение на часть…');
    try {
      const res = await api.setPartTexture(partsMaterial, part,
                                           file ? await api.upload(file) : null);
      if (res.error) { hintParts(res.error); return; }
      applyView(res);
      const fresh = await refreshParts();
      // Куски, делящие развёртку, красятся вместе. Сказать об этом надо в тот
      // момент, когда это произошло, а не только подсказкой на кнопке.
      const painted = (fresh.parts || []).find((p) => p.id === part);
      hintParts(file && painted && painted.shared.length
        ? 'Эта часть делит развёртку с соседними — они покрасились вместе'
        : '');
    } catch (err) {
      hintParts('Не удалось: ' + err.message);
    }
  };

  if (file !== undefined) { apply(file); return; }   // null — снять картинку

  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/*,.vtf';
  input.addEventListener('change', () => input.files[0] && apply(input.files[0]));
  input.click();
}

/** Покласcовые модели шапки: у стилевой они в стиле, у обычной — в предмете. */
function hatModels(item, index) {
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
function showHatClasses(item) {
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
function hatClasses() {
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
function showHatStyles(item) {
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
      const res = await api.loadPreview('hat', 'ru', first, models, index);
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
function markEditedStyles(indexes) {
  const edited = new Set((indexes || []).map(Number));
  document.querySelectorAll('#hatstyles .tag').forEach((b) => {
    const name = b.textContent.replace(/ ●$/, '');
    b.textContent = edited.has(Number(b.dataset.style)) ? name + ' ●' : name;
  });
}

async function startPreview(item) {
  cardTitles = {};        // подписи прошлого мода к новому предмету не относятся
  modName = '';           // и его имя тоже
  sceneKind = '';         // и спец-сцена: у обычной модели её нет
  document.getElementById('hatstyles').hidden = true;
  document.getElementById('hatclasses').hidden = true;
  // Части считаны по ПРОШЛОЙ модели: у новой под тем же номером другой кусок.
  closeParts();
  showMaterials([]);
  withViewer((w) => w.resetViewer());

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
  const res = await api.loadPreview(item.mode, 'ru',
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
async function showModel(ev) {
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

/**
 * Применяет состояние показа, посчитанное Python.
 *
 * Что именно показывать при этой команде, стиле и варианте, решает домен
 * (PreviewTextureState.resolve_card). Здесь только раздача: альбом, вьювер и
 * видимость кнопок команд.
 */
function applyView(st) {
  showMaterials(st.materials.length ? st.materials : Object.keys(st.textures),
                st.textures, Boolean(st.style));
  showStyleBar(st);

  // У одноматериальной модели ключ служебный (SINGLE_TEX_KEY) — имени меша с
  // таким названием нет и быть не может. Вьювер искал бы его, не находил и
  // оставлял модель серой. Такую текстуру кладём глобально, на все меши.
  // Меши красим ПОЛНЫМ набором (st.scene): карточки отфильтрованы, а глаза и
  // зубы без текстуры остались бы серыми. Альбом при этом показывает только
  // редактируемое — как и панель приложения.
  const entries = Object.entries(st.scene || st.textures);
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

  // Альбом только что пересобран — вернуть пометки «свои настройки».
  restoreBadges();
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
function bindDrop(frame) {
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

function showSkins(info) {
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
function showStyleBar(st) {
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
let fpAction = 'IDLE';

/**
 * Ряд анимаций вида от первого лица.
 *
 * Показывается только в этом виде: в обычном ракурсе выбирать нечего, а
 * пустой ряд занимал бы место под моделью.
 */
function showFpActions(actions) {
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
      say('Сборка сцены: ' + action + '…');
      const res = await api.loadFirstPerson(action);
      if (res.error) say(res.error);
    });
    bar.appendChild(b);
  }
}

//: Какая спец-сцена сейчас в кадре: '' | 'none' | 'crit' | 'death'.
//: От неё зависит, КУДА кладётся текстура — на билборд или на персонажа.
let sceneKind = '';
//: Текстура персонажа в сцене (у эффекта смерти — игровая по умолчанию).
let sceneModelTex = '';

/**
 * Сцена спец-режима.
 *
 * Спрей — просто картинка, показывать нечего. Крит — персонаж и билборд над
 * ним. Эффект смерти — тот же персонаж, но текстура ложится на него.
 */
function showSpecialScene(ev) {
  sceneKind = ev.scene_kind || 'none';
  sceneModelTex = ev.model_texture || '';
  // Кнопки стилей прошлого предмета к спец-режиму не относятся: своего
  // события skins тут не будет, и они остались бы в ряду навсегда.
  document.querySelectorAll('#skinbar .tag').forEach((b) => b.remove());

  if (sceneKind === 'none') {
    withViewer((w) => w.resetViewer && w.resetViewer());
    say('Положите картинку в кадр — модели у этого режима нет');
    return;
  }

  const modelUrl = sceneModelTex ? api.fileUrl(sceneModelTex) : '';
  withViewer((w) => w.loadCritHitScene('', modelUrl));
  say(sceneKind === 'crit'
    ? 'Картинка ляжет билбордом над персонажем'
    : 'Картинка ляжет на персонажа — так эффект выглядит в игре');
}

/**
 * Текстура спец-сцены: у крита — билборд, у эффекта смерти — сам персонаж.
 *
 * Возвращает true, если сцена забрала текстуру на себя и обычная раздача по
 * материалам не нужна.
 */
function applySpecialTexture(textures) {
  if (!sceneKind || sceneKind === 'none') return false;
  const path = Object.values(textures || {})[0];
  const url = path ? api.fileUrl(path) : '';
  withViewer((w) => {
    if (sceneKind === 'crit') w.updateCritHitTexture(url);
    else w.loadCritHitScene('', url || (sceneModelTex ? api.fileUrl(sceneModelTex) : ''));
  });
  return true;
}

/** Небо: шесть граней кубмапой вместо модели. */
function showSkybox(faces) {
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
async function showFirstPerson(objPath, rig) {
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
function frameNode(name) {
  const fig = document.createElement('figure');
  fig.className = 'frame';
  fig.dataset.mat = name;
  fig.innerHTML = `<div class="frame__img">
                     <div class="frame__tools">
                       <button class="frame__tool" type="button"
                               title="Настройки этой текстуры">⚙</button>
                       <button class="frame__tool frame__off" type="button" hidden
                               title="Убрать материал из стиля">×</button>
                     </div>
                   </div>
                   <figcaption class="frame__name"></figcaption>`;
  return fig;
}

/** Добавляет один кадр в конец альбома, не трогая остальные. */
function addFrame(name, png) {
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
let cardTitles = {};

/** Как подписать карточку: служебный ключ и имена мода — особые случаи. */
function cardTitle(name) {
  if (name === SINGLE_TEX) return 'текстура';
  return cardTitles[name] || name;
}

/** Перерисовывает вкладки и альбом под материалы, пришедшие от воркера. */
function showMaterials(names, textures = {}, inStyle = false) {
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

// ── События воркеров ─────────────────────────────────────────────────────
// Порядок важен. У ОДНОМАТЕРИАЛЬНОЙ модели текстура приезжает прямо в
// model_ready и события materials не будет вовсе; у многоматериальной
// materials придёт следом и перепишет альбом. Поэтому один кадр — не особый
// случай, а тот же альбом длиной в единицу.

api.subscribe((ev) => {
  switch (ev.event) {
    case 'progress':
      say(ev.text);
      break;

    case 'model_ready':
      // Альбом наполняется ТОЛЬКО из applyView: два источника расходились —
      // кадр из события затирался пустым состоянием и обратно.
      showModel(ev);
      break;

    // Материалы, командные текстуры и вариант меняют то, ЧТО показывать.
    // Пересчитывает это Python, поэтому спрашиваем состояние целиком.
    case 'materials':
    case 'blu_materials':
    case 'blu_ready':
    case 'australium':
    // «Синий есть, но он равен красному» меняет только подпись кнопки —
    // состояние уже знает об этом (blu_matches_red).
    case 'blu_same_as_red':
      refreshView();
      break;

    case 'animated':
      // Многокадровый VTF: анимацию крутит сам вьювер.
      withViewer((w) => w.loadAnimatedTexture(
        ev.frames.map(api.fileUrl), ev.fps, ''));
      showMaterials(['текстура'], { 'текстура': ev.frames[0] });
      break;

    case 'render_hints':
      withViewer((w) => w.setMaterialHints(ev.hints));
      break;

    case 'skins':
      showSkins(ev.info);
      break;

    // Вид от первого лица: сцена приходит либо мешем, либо со скелетом.
    // Текстуры к ней приезжают обычным materials, поэтому здесь только меш.
    case 'fp_ready':
      showFirstPerson(ev.obj, ev.rig);
      break;

    case 'fp_animated':
      withViewer((w) => {
        // Риг СТРОГО до сцены: applyTransform читает его при показе модели,
        // иначе камера встаёт орбитой и кадр оказывается пустым.
        w.setViewRig(ev.rig);
        w.loadViewmodelAnimated(ev.scene, 0);
      });
      say('');
      break;

    // Какие анимации есть у этого оружия — знает только воркер: список
    // приходит из QC модели, общего перечня не существует.
    case 'fp_actions':
      showFpActions(ev.actions);
      break;

    case 'fp_editable':
      // Правится только оружие: руки в сцене стоковые и чужие.
      withViewer((w) => w.setEditableMeshNames(ev.names));
      break;

    // Спец-режимы. У спрея модели нет вовсе, у крита и эффектов смерти есть
    // сцена с персонажем — её строит вьювер.
    case 'texture_only':
      showSpecialScene(ev);
      refreshView();
      break;

    case 'skybox':
      showSkybox(ev.faces);
      break;

    case 'build_progress':
      setStatus(ev.text || 'Сборка…', true);
      break;

    // Сборке не хватило текстуры для материала: она СТОИТ и ждёт ответа.
    // Пока человек думает, воркер держит паузу (300 секунд), поэтому вопрос
    // задаём сразу и не копим.
    case 'need_texture':
      askForTexture(ev.material);
      break;

    case 'build_done':
      setStatus(ev.message || (ev.ok ? 'Готово' : 'Ошибка сборки'), false);
      break;

    case 'uv_ready':
      if (!ev.ok || !ev.path) { say(ev.message || 'UV-шаблон не построен'); break; }
      // Кладём рядом с текстурами: сравнивать развёртку с текстурой удобнее
      // в одном ряду, чем в отдельном окне.
      // У многоматериальной модели разметок несколько: у каждого материала
      // своя текстура и своя развёртка в тех же координатах.
      const uvFiles = (ev.paths && ev.paths.length) ? ev.paths : [ev.path];
      say(uvFiles.length > 1 ? 'UV-шаблоны: ' + uvFiles.length + ' шт.'
                             : 'UV-шаблон: ' + uvFiles[0]);
      uvFiles.forEach((file, index) => addFrame(
        uvFiles.length > 1 ? 'UV-шаблон ' + (index + 1) : 'UV-шаблон', file));
      break;

    // Файлы декомпиляции готовы: пока выбор не сделан, за ними числится
    // временная папка — отказ тоже надо отправить, иначе она останется.
    case 'extract_files':
      if (!ev.ok) { say(ev.message || 'Модель не извлечена'); break; }
      ask({ title: 'Что сохранить в папку экспорта', list: ev.files,
            multi: true, chosen: ev.selected || [], ok: 'Сохранить' })
        .then(async (picked) => {
          const res = await api.exportModelFiles(picked || []);
          if (res.error) say(res.error);
          else if (res.cancelled) say('Извлечение отменено');
        });
      break;

    // Мод из VPK: карточки строятся из его VTF, а не из материалов игровой
    // модели. Подписи запоминаем — дальше альбом рисуется обычным путём.
    case 'mod_cards':
      cardTitles = Object.fromEntries(
        ev.cards.map((c) => [c.name, c.display_name || c.name]));
      refreshView();
      break;

    // Режим «только геометрия»: пришла игровая текстура, а модель на экране
    // остаётся пользовательской — красим её глобально.
    case 'cards_ready':
      if (ev.texture) withViewer((w) => w.updateTextureFromDataUrl(api.fileUrl(ev.texture)));
      break;

    case 'diagnostics':
      showReport(ev);
      break;

    case 'tool_done':
      say(ev.message || (ev.ok ? 'Готово' : 'Не получилось'));
      break;

    case 'failed':
      say(ev.error);
      break;

    default:
      break;
  }
});

/** Спрашивает Python, что показывать при этом режиме, и применяет ответ. */
async function setMode(mode) {
  sel.mode = mode;
  applyControls(await api.call('controls_for', { mode }));
}

//: Номер последнего запроса списка. Ответы приходят по сети и могут обогнать
//: друг друга: быстро щёлкнув по фильтрам, легко получить список от прошлого
//: выбора. Рисуем только тот ответ, который всё ещё актуален.
let reloadSeq = 0;

async function reload() {
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


// ═══════════════════════════════════════════════════════════════════════════
// Частицы
// ═══════════════════════════════════════════════════════════════════════════
// Отдельный источник каталога и отдельный движок в кадре. Разбор PCF идёт
// ОТВЕТОМ, а не событием: он занимает около секунды, зато приезжает целиком
// (системы, материалы с развёрнутыми в PNG текстурами и дерево вложенности),
// и показывать до этого всё равно нечего.

//: Дерево систем последнего разобранного PCF — из него рисуется каталог.
let pcfNodes = [];
//: Плоский список тех же систем — для списков выбора (дочерняя, поиск).
let pcfTree = [];
//: Свёрнутые узлы. По ключу, а не по строке: одна система бывает ребёнком
//: сразу у нескольких родителей, и сворачивать её логично везде сразу.
const pcfCollapsed = new Set();

/** Все системы дерева одним списком. */
function flattenNodes(nodes, out = []) {
  for (const n of nodes) {
    out.push({ key: n.key, name: n.name, type: 'particle', mode: 'particles' });
    flattenNodes(n.kids, out);
  }
  return out;
}

/**
 * Рисует дерево систем.
 *
 * Ребёнок стоит под родителем с отступом, у родителя — треугольник. Плоским
 * списком 104 системы class_fx читаются как свалка, а вложенность в PCF
 * настоящая: родитель тянет детей за собой.
 */
function fillTree(nodes, selected) {
  els.grid.innerHTML = '';

  const walk = (list, depth) => {
    for (const node of list) {
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
}

/** Переводит кадр на движок частиц (или обратно на вьювер моделей). */
function showParticleFrame(on) {
  // Адрес ставим при первом входе: второй three.js на неоткрытой вкладке
  // грузить незачем.
  if (on && !stage.pframe.src) stage.pframe.src = '/viewer/particles3d.html';
  stage.pframe.hidden = !on;
  stage.frame.hidden = on;
}

/** Загружает PCF и показывает первый эффект. */
async function loadPcf(source, label = '') {
  const short = label || source.replace(/^particles\//, '');
  say('Разбор ' + short + '…');
  els.grid.innerHTML = '';
  const data = await api.loadParticles(source);
  if (data.error) { say(data.error); return; }

  pcfNodes = data.tree || [];
  pcfTree = flattenNodes(pcfNodes);
  // Новый файл — свои узлы; старое состояние свёрнутости к ним не относится.
  pcfCollapsed.clear();
  // Дочерние сворачиваем сразу: сверху видно корни эффектов, а не всё подряд.
  for (const n of pcfNodes) if (n.kids.length) pcfCollapsed.add(n.key);

  withParticles((w) => {
    w.setLanguage && w.setLanguage('ru');
    w.loadParticleData(data);
  });
  document.querySelector('.title__name').textContent =
    short.replace(/\.pcf$/, '');
  document.querySelector('.title__meta').textContent =
    short + ' · ' + pcfTree.length + ' систем, корней ' + pcfNodes.length;

  fillTree(pcfNodes, data.rootName);
  els.note.hidden = pcfTree.length > 0;
  els.note.textContent = 'В этом файле систем нет.';
  say('');
  if (data.rootName) await showParams(data.rootName);
  await showParticleMaterials();
}


// ── Параметры эффекта ────────────────────────────────────────────────────
// Крутилки описаны в Python (services/simple_params) — здесь только поля и
// отправка значений. Список параметров, границы и подписи приходят готовыми:
// схема одна на панель приложения и на эту страницу.

//: Система, чьи параметры сейчас показаны.
let pSystem = '';

/**
 * Дорожка ползунка. Границы у неё МЯГКИЕ (сколько нужно в 99% эффектов), а
 * поле рядом принимает и жёсткие: в стоке встречаются emission_rate под
 * миллион, и запрет на них молча испортил бы чужой эффект.
 */
function sliderField(value, param, onLive, onDone) {
  const r = document.createElement('input');
  r.className = 'slider';
  r.type = 'range';
  r.min = 0; r.max = 1000; r.step = 1;
  r.value = Math.round(curveFraction(param, value) * 1000);
  const read = () => {
    const v = curveValue(param, Number(r.value) / 1000);
    return param.decimals ? Number(v.toFixed(param.decimals)) : Math.round(v);
  };
  // Пока тянут — только показываем; в Python уходит отпускание, иначе одно
  // перетаскивание давало бы сотню правок файла.
  r.addEventListener('input', () => onLive(read()));
  r.addEventListener('change', () => onDone(read()));
  return r;
}

/** Поле одного числа. Возвращает input; onEdit получает уже число. */
function numberField(value, param, onEdit) {
  const i = document.createElement('input');
  i.className = 'input input--num';
  i.type = 'number';
  i.step = param.decimals ? String(10 ** -param.decimals) : '1';
  i.min = param.hard_min;
  i.max = param.hard_max;
  i.value = Number(value).toFixed(param.decimals);
  // Пока модуля под параметром нет, поле показывает умолчание Source бледным:
  // именно его эффект и получит, если правку не тронуть.
  i.classList.toggle('is-placeholder', param.value === null);
  i.addEventListener('change', () => {
    const v = Math.min(param.hard_max, Math.max(param.hard_min, Number(i.value)));
    i.value = v.toFixed(param.decimals);
    onEdit(v);
  });
  return i;
}

/**
 * Дорожка и поле на одно значение: тянуть удобнее, вписать точнее.
 *
 * Дорожка ходит по мягким границам, поле принимает и жёсткие — поэтому
 * значение из чужого эффекта (emission_rate под миллион) правится вручную,
 * а дорожка просто упирается в край.
 */
function pairedField(value, param, onEdit) {
  const wrap = document.createElement('div');
  wrap.className = 'pair';
  const field = numberField(value, param, onEdit);
  const track = sliderField(value, param,
    (v) => { field.value = v.toFixed(param.decimals); },
    onEdit);
  field.addEventListener('input', () => {
    track.value = Math.round(curveFraction(param, Number(field.value)) * 1000);
  });
  wrap.append(track, field);
  return wrap;
}

/** Цвет как #rrggbb; альфу сохраняем — её правит отдельный параметр. */
function colorField(rgba, onEdit) {
  const i = document.createElement('input');
  i.type = 'color';
  i.className = 'colorfield';
  const hex = (n) => Math.max(0, Math.min(255, n | 0)).toString(16).padStart(2, '0');
  i.value = '#' + hex(rgba[0]) + hex(rgba[1]) + hex(rgba[2]);
  i.addEventListener('change', () => {
    const n = parseInt(i.value.slice(1), 16);
    onEdit([(n >> 16) & 255, (n >> 8) & 255, n & 255, rgba[3] ?? 255]);
  });
  return i;
}

/** Отправляет правку и переливает результат в живое превью. */
async function editParam(param, value) {
  const res = await api.setParticleParam(pSystem, param.key, value);
  if (res.error) { say(res.error); return; }
  withParticles((w) => w.updateSystems(res.systems, pSystem));
  // Значение могло создать модуль — перечитываем, чтобы бледные поля стали
  // обычными, а соседние крутилки показали то, что теперь в файле.
  await showParams(pSystem);
}

//: Обычный режим или экспертный. Выбор держится до смены раздела.
let pMode = 'simple';

document.querySelector('.params__modes').addEventListener('click', (e) => {
  const b = e.target.closest('[data-pmode]');
  if (!b) return;
  document.querySelectorAll('[data-pmode]')
          .forEach((x) => x.classList.toggle('is-active', x === b));
  pMode = b.dataset.pmode;
  if (pSystem) showParams(pSystem);
});

/** Редактор одного атрибута экспертного режима — по типу из PCF. */
function attrField(attr, onEdit) {
  const box = document.createElement('div');
  box.className = 'params__in';

  // Атрибут с фиксированным набором значений — список, а не голое число.
  if (attr.enum) {
    const sel = document.createElement('select');
    sel.className = 'input';
    for (const [v, label] of Object.entries(attr.enum)) sel.append(new Option(label || v, v));
    sel.value = String(attr.v);
    sel.addEventListener('change', () => onEdit(Number(sel.value)));
    box.append(sel);
    return box;
  }

  if (attr.t === 'bool') {
    const i = document.createElement('input');
    i.type = 'checkbox';
    i.checked = Boolean(attr.v);
    i.addEventListener('change', () => onEdit(i.checked));
    box.append(i);
    return box;
  }

  if (attr.t === 'color') {
    // Цвет и прозрачность — разными полями: альфа в PCF четвёртая компонента,
    // а <input type="color"> о ней не знает.
    const rgba = attr.v.slice();
    const hex = (n) => Math.max(0, Math.min(255, n | 0)).toString(16).padStart(2, '0');
    const c = document.createElement('input');
    c.type = 'color';
    c.className = 'colorfield';
    c.value = '#' + hex(rgba[0]) + hex(rgba[1]) + hex(rgba[2]);
    const alpha = document.createElement('input');
    alpha.className = 'input input--num input--tiny';
    alpha.type = 'number'; alpha.min = 0; alpha.max = 255; alpha.step = 1;
    alpha.value = rgba[3] ?? 255;
    const push = () => {
      const n = parseInt(c.value.slice(1), 16);
      onEdit([(n >> 16) & 255, (n >> 8) & 255, n & 255, Number(alpha.value)]);
    };
    c.addEventListener('change', push);
    alpha.addEventListener('change', push);
    box.append(c, alpha);
    return box;
  }

  if (attr.t === 'string') {
    const i = document.createElement('input');
    i.className = 'input';
    i.type = 'text';
    i.value = attr.v ?? '';
    i.addEventListener('change', () => onEdit(i.value));
    box.append(i);
    return box;
  }

  if (Array.isArray(attr.v)) {
    // vec2/vec3/vec4 — по полю на компоненту, значение уходит целиком.
    const vals = attr.v.slice();
    vals.forEach((v, n) => {
      const i = document.createElement('input');
      i.className = 'input input--num input--tiny';
      i.type = 'number'; i.step = '0.01';
      i.value = v;
      i.addEventListener('change', () => {
        vals[n] = Number(i.value);
        onEdit(vals.slice());
      });
      box.append(i);
    });
    return box;
  }

  const i = document.createElement('input');
  i.className = 'input input--num';
  i.type = 'number';
  i.step = attr.t === 'integer' ? '1' : '0.01';
  // В PCF числа float32, и 0.1 приезжает как 0.10000000149011612. Показываем
  // округлённо: значение в файле не трогаем, пока его не правят.
  i.value = attr.t === 'integer' ? attr.v : Number(Number(attr.v).toPrecision(7));
  i.addEventListener('change',
    () => onEdit(attr.t === 'integer' ? parseInt(i.value, 10) : Number(i.value)));
  box.append(i);
  return box;
}

/** Проверка «умеет ли движок этот модуль», либо null — движок ещё молчит. */
function supportedModules() {
  const w = particles();
  if (!w || typeof w.implementedModules !== 'function') return null;
  const impl = w.implementedModules();
  const aliases = impl.aliases || {};
  return (group, fn) => {
    const name = String(fn || '').trim().toLowerCase();
    const real = aliases[name] || name;
    return (impl[group] || []).some((x) => String(x).toLowerCase() === real);
  };
}

// ── Диалог ───────────────────────────────────────────────────────────────
// Три вида в одном окне: спросить текст, выбрать из списка, подтвердить.
// Возвращает значение или null, если отменили.

const askEl = document.getElementById('ask');

function ask({ title, text = '', value = null, list = null, multi = false,
               chosen = [], ok = 'Готово' }) {
  const titleEl = askEl.querySelector('.ask__title');
  const textEl = askEl.querySelector('.ask__text');
  const input = askEl.querySelector('.ask__input');
  const listEl = askEl.querySelector('.ask__list');
  const okBtn = askEl.querySelector('.ask__ok');
  const cancelBtn = askEl.querySelector('.ask__cancel');

  titleEl.textContent = title;
  textEl.textContent = text;
  textEl.hidden = !text;
  input.hidden = value === null;
  input.value = value ?? '';
  listEl.hidden = !list;
  listEl.innerHTML = '';
  askEl.querySelector('.ask__ok').textContent = ok;

  return new Promise((resolve) => {
    // Один выбор — значение; множественный — набор отмеченного.
    const marks = new Set(multi ? chosen : []);
    let picked = null;
    let done = false;

    // Событие close тут ненадёжно: отправка формы method="dialog" закрывает
    // окно, но события не шлёт — цепочка из двух вопросов подряд на этом
    // молча обрывалась. Поэтому ответ отдаём из обработчиков кнопок, а
    // close/cancel держим только для Esc.
    const settle = (result) => {
      if (done) return;
      done = true;
      okBtn.removeEventListener('click', onOk);
      cancelBtn.removeEventListener('click', onCancel);
      askEl.removeEventListener('cancel', onCancel);
      askEl.removeEventListener('close', onCancel);
      if (askEl.open) askEl.close();
      resolve(result);
    };
    const onOk = (e) => {
      e.preventDefault();
      if (list) { settle(multi ? [...marks] : picked); return; }
      settle(value === null ? true : input.value.trim());
    };
    const onCancel = () => settle(null);

    if (list) {
      for (const item of list) {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'ask__item';
        b.textContent = item.label ?? item;
        b.title = item.hint || '';
        const value = item.value ?? item;
        if (multi && marks.has(value)) b.classList.add('is-active');
        b.addEventListener('click', () => {
          if (multi) {
            // Отмеченных может быть сколько угодно: подсветку с других не
            // снимаем, иначе список вёл бы себя как выбор одного.
            if (marks.has(value)) marks.delete(value);
            else marks.add(value);
            b.classList.toggle('is-active', marks.has(value));
            return;
          }
          listEl.querySelectorAll('.ask__item')
                .forEach((x) => x.classList.remove('is-active'));
          b.classList.add('is-active');
          picked = value;
        });
        // Двойной клик — выбрать и закрыть: список длинный, тянуться к
        // кнопке ради каждого выбора незачем. При множественном выборе он
        // означал бы «отметил и передумал», поэтому там его нет.
        if (!multi) {
          b.addEventListener('dblclick', () => {
            picked = value;
            settle(picked);
          });
        }
        listEl.appendChild(b);
      }
    }

    okBtn.addEventListener('click', onOk);
    cancelBtn.addEventListener('click', onCancel);
    askEl.addEventListener('cancel', onCancel);      // Esc
    askEl.addEventListener('close', onCancel);
    askEl.showModal();
    if (value !== null) { input.focus(); input.select(); }
  });
}

const pfind = document.getElementById('pfind');

/**
 * Оставляет в дереве то, что подходит под запрос.
 *
 * Пустой запрос сворачивает всё обратно: развёрнутые модули после поиска
 * выглядели бы так, будто их открыл пользователь.
 */
function filterExpert(query) {
  const q = query.trim().toLowerCase();
  document.querySelectorAll('.expert__mod').forEach((mod) => {
    const modName = mod.querySelector('.expert__name').textContent.toLowerCase();
    let hits = 0;
    mod.querySelectorAll('.params__row').forEach((row) => {
      const name = row.querySelector('.params__name').textContent.toLowerCase();
      // Совпало имя модуля — показываем его целиком, иначе только строки.
      const ok = !q || modName.includes(q) || name.includes(q);
      row.hidden = !ok;
      if (ok) hits += 1;
    });
    mod.hidden = Boolean(q) && hits === 0;
    mod.open = Boolean(q) && hits > 0;
  });
  // Заголовок группы без единого модуля — висящая подпись; прячем вместе с ней.
  document.querySelectorAll('.expert__block').forEach((block) => {
    block.hidden = ![...block.querySelectorAll('.expert__mod')]
      .some((m) => !m.hidden);
  });
}

pfind.addEventListener('input', () => filterExpert(pfind.value));

/** Экспертное дерево: группы → модули → все атрибуты, как они лежат в PCF. */
async function showExpert(system) {
  const data = await api.particleSystem(system);
  if (pSystem !== system) return;

  const supported = supportedModules();
  const box = document.getElementById('pexpert');
  box.innerHTML = '';
  for (const g of data.groups || []) {
    // Группа — заголовком над своими модулями, а не подписью на каждом:
    // «OPERATORS» пять раз подряд ничего не добавляло, только шумело.
    const block = document.createElement('section');
    block.className = 'expert__block';
    const head = document.createElement('p');
    head.className = 'label expert__head';
    head.textContent = g.group || 'система';
    // Правая кнопка на заголовке группы — добавить в неё модуль.
    head.addEventListener('contextmenu', (e) => expertMenu(e, {
      group: g.group, index: null, attr: null,
    }));
    block.append(head);
    box.append(block);

    if (g.group === 'children') {
      // Дети — ссылки, а не модули: у них нет параметров, только имя.
      for (const kid of g.modules) {
        const row = document.createElement('div');
        row.className = 'expert__kid';
        row.textContent = kid.title;
        row.addEventListener('contextmenu', (e) => expertMenu(e, {
          group: 'children', index: kid.index, attr: null,
        }));
        block.append(row);
      }
      continue;
    }

    for (const mod of g.modules) {
      const d = document.createElement('details');
      d.className = 'expert__mod';
      // Свёрнуто всё: 16 названий модулей — это карта системы, а 181 строка
      // подряд — стена, в которой ничего не найти.
      d.open = false;
      // Адрес модуля нужен кнопкам «Параметр +» и удалению.
      d.dataset.group = g.group || '';
      d.dataset.index = mod.index;

      const sum = document.createElement('summary');
      sum.innerHTML = '<span class="expert__name"></span>'
                    + '<span class="expert__warn"></span>';
      sum.querySelector('.expert__name').textContent = mod.title;
      sum.addEventListener('contextmenu', (e) => expertMenu(e, {
        group: g.group, index: mod.index, attr: null,
      }));
      sum.title = mod.help || '';
      // Модуль, который движок не симулирует: в игре он работает, в кадре —
      // нет. Промолчать нельзя, правка выглядела бы сломанной.
      if (g.group && supported && !supported(g.group, mod.title)) {
        sum.querySelector('.expert__warn').textContent = 'не в превью';
      }
      d.append(sum);

      for (const attr of mod.attrs) {
        const row = document.createElement('div');
        // Строке и вектору поле рядом с подписью не годится: подпись сжималась
        // до нуля, а третья компонента уезжала за край. Им — своя строка.
        // Цвет тоже массив, но образец с альфой рядом с подписью помещается.
        const wide = attr.t === 'string'
                  || (Array.isArray(attr.v) && attr.t !== 'color');
        row.className = 'params__row' + (wide ? ' params__row--wide' : '');
        row.innerHTML = '<span class="params__name"></span>';
        row.querySelector('.params__name').textContent = attr.name;
        row.title = attr.help || '';
        row.append(attrField(attr, async (value) => {
          const res = await api.setParticleAttr(system, g.group, mod.index,
                                                attr.name, value);
          if (res.error) { say(res.error); return; }
          withParticles((w) => w.updateSystems(res.systems, pSystem));
        }));
        row.addEventListener('contextmenu', (e) => expertMenu(e, {
          group: g.group, index: mod.index, attr: attr.name,
        }));
        d.append(row);
      }
      block.append(d);
    }
  }
}

// ── Действия над системой ────────────────────────────────────────────────
// Один разбор ответа на всех: правка структуры отдаёт свежие systems и tree,
// и после неё надо обновить и кадр, и каталог, и панель свойств.

async function applyStructure(res, { reselect = null } = {}) {
  if (!res || res.error) { say(res?.error || 'не получилось'); return false; }
  if (res.tree) {
    pcfNodes = res.tree;
    pcfTree = flattenNodes(pcfNodes);
    const keep = reselect || res.selected || pSystem;
    // Систему могли переименовать или удалить — тогда показываем первую.
    pSystem = pcfTree.some((n) => n.key === keep) ? keep
            : (pcfTree[0] ? pcfTree[0].key : '');
    fillTree(pcfNodes, pSystem);
    document.querySelector('.title__name').textContent = pSystem;
  }
  if (res.systems) {
    withParticles((w) => w.updateSystems(res.systems, pSystem));
  }
  if (pSystem) await showParams(pSystem);
  return true;
}

/** Выбор группы и модуля для «Модуль +». */
async function askModule() {
  const group = await ask({
    title: 'В какую группу',
    list: [
      { label: 'operators — что делает с частицей по ходу жизни', value: 'operators' },
      { label: 'initializers — каким рождается', value: 'initializers' },
      { label: 'renderers — чем рисуется', value: 'renderers' },
      { label: 'emitters — как выпускаются', value: 'emitters' },
      { label: 'forces — что на неё давит', value: 'forces' },
      { label: 'constraints — что ограничивает', value: 'constraints' },
    ],
    ok: 'Дальше',
  });
  if (!group) return null;
  const names = await api.particleModules(group);
  const fn = await ask({
    title: 'Какой модуль',
    text: 'Сверху — ходовые, ниже всё, что встречается в эффектах игры.',
    list: names.map((n) => ({ label: n, value: n })),
    ok: 'Добавить',
  });
  return fn ? { group, fn } : null;
}

/** Адрес модуля для действий: тот узел, на котором открыли меню. */
function currentModule() {
  if (ctxNode && ctxNode.index !== null) {
    return { group: ctxNode.group || null, index: ctxNode.index };
  }
  const open = document.querySelector('.expert__mod[open]');
  return open && open.dataset.group !== undefined
    ? { group: open.dataset.group || null, index: Number(open.dataset.index) }
    : null;
}

const PACTS = {
  async module() {
    // Меню открыто на группе — она и есть ответ на первый вопрос.
    const group = ctxNode && ctxNode.group && ctxNode.group !== 'children'
      ? ctxNode.group : null;
    let pick;
    if (group) {
      const names = await api.particleModules(group);
      const fn = await ask({
        title: 'Какой модуль',
        text: 'Сверху — ходовые, ниже всё, что встречается в эффектах игры.',
        list: names.map((n) => ({ label: n, value: n })),
        ok: 'Добавить',
      });
      pick = fn ? { group, fn } : null;
    } else {
      pick = await askModule();
    }
    if (!pick) return;
    await applyStructure(
      await api.addParticleModule(pSystem, pick.group, pick.fn));
  },

  async delmodule() {
    const mod = currentModule();
    if (!mod) return;
    const yes = await ask({ title: 'Удалить модуль?', ok: 'Удалить' });
    if (yes) {
      await applyStructure(
        await api.removeParticleModule(pSystem, mod.group, mod.index));
    }
  },

  async delattr() {
    if (!ctxNode || !ctxNode.attr) return;
    await applyStructure(await api.removeParticleAttr(
      pSystem, ctxNode.group || null, ctxNode.index, ctxNode.attr));
  },

  async detach() {
    if (!ctxNode || ctxNode.index === null) return;
    await applyStructure(
      await api.removeParticleChild(pSystem, ctxNode.index));
  },

  async attr() {
    // Параметр добавляют В МОДУЛЬ: какой именно — тот, что раскрыт в дереве.
    const mod = currentModule();
    if (!mod) {
      say('Раскройте модуль в экспертном режиме — параметр добавляется в него');
      return;
    }
    const missing = await api.particleMissingAttrs(pSystem, mod.group, mod.index);
    if (!missing.length) { say('Все известные параметры уже заданы'); return; }
    const name = await ask({
      title: 'Какой параметр',
      text: 'Значение подставится такое, как в эффектах игры.',
      list: missing.map((a) => ({ label: a.name, value: a.name, hint: a.help })),
      ok: 'Добавить',
    });
    if (!name) return;
    const attr = missing.find((a) => a.name === name);
    await applyStructure(await api.addParticleAttr(
      pSystem, mod.group, mod.index, attr.name, attr.t, attr.v));
  },

  /** Копирует ровно то, на чём открыли меню: параметр, модуль или группу. */
  async copyone() {
    const n = ctxNode || {};
    return PACTS.copy({ group: n.group || null, index: n.index, attr: n.attr });
  },

  async copy(scope = {}) {
    const res = await api.copyParticleParams(
      pSystem, scope.group ?? null, scope.index ?? null, scope.attr ?? null);
    if (res.error) { say(res.error); return; }
    const text = JSON.stringify({ tf2sgParticleParams: res.payload });
    try {
      await navigator.clipboard.writeText(text);
      say('Параметры скопированы — можно вставить в другую систему или отдать ИИ');
    } catch {
      // Доступ к буферу может быть закрыт настройками браузера — тогда
      // показываем набор, чтобы его можно было выделить и скопировать самому.
      await ask({ title: 'Скопируйте набор параметров', value: text,
                  text: 'Буфер обмена недоступен — выделите и скопируйте.' });
    }
  },

  async paste() {
    let text = '';
    try { text = await navigator.clipboard.readText(); } catch { text = ''; }
    // Чтение буфера может быть запрещено — тогда просим вставить руками.
    if (!text) {
      text = await ask({ title: 'Вставьте набор параметров', value: '',
                         text: 'JSON с ключом tf2sgParticleParams' });
      if (!text) return;
    }
    let payload = null;
    try {
      payload = JSON.parse(text).tf2sgParticleParams;
    } catch (e) { say('В буфере не JSON: ' + e.message); return; }
    if (!payload) { say('В JSON нет раздела tf2sgParticleParams'); return; }

    // Полный набор можно влить поверх или заменить систему целиком.
    let mode = 'overwrite';
    if (payload.full) {
      mode = await ask({
        title: 'Как вставить',
        list: [
          { label: 'Поверх — совпадающие параметры заменить', value: 'overwrite' },
          { label: 'Без замены — дописать только недостающее', value: 'keep' },
          { label: 'Полная замена — снести модули системы', value: 'replace' },
        ],
        ok: 'Вставить',
      });
      if (!mode) return;
    }
    const res = await api.pasteParticleParams(pSystem, payload, mode);
    if (await applyStructure(res) && res.report?.length) {
      say('Вставлено, но часть пропущена: ' + res.report[0]);
    }
  },

  async duplicate() {
    const name = await ask({ title: 'Имя копии', value: pSystem + '_copy' });
    if (!name) return;
    await applyStructure(await api.duplicateParticleSystem(pSystem, name),
                         { reselect: name });
  },

  async rename() {
    const name = await ask({ title: 'Новое имя системы', value: pSystem });
    if (!name || name === pSystem) return;
    await applyStructure(await api.renameParticleSystem(pSystem, name),
                         { reselect: name });
  },

  async child() {
    // Дочернюю можно подцепить и отцепить — обе операции об одном списке.
    const kids = await api.particleChildren(pSystem);
    const what = await ask({
      title: 'Дочерние системы',
      text: kids.length ? kids.map((k) => k.name).join(', ') : 'Пока ни одной.',
      list: [
        { label: 'Подцепить существующую…', value: 'add' },
        ...(kids.length ? [{ label: 'Отцепить…', value: 'remove' }] : []),
      ],
      ok: 'Дальше',
    });
    if (what === 'add') {
      const child = await ask({
        title: 'Какую систему подцепить',
        list: pcfTree.filter((n) => n.key !== pSystem)
                     .map((n) => ({ label: n.key, value: n.key })),
        ok: 'Подцепить',
      });
      if (child) await applyStructure(await api.addParticleChild(pSystem, child));
    } else if (what === 'remove') {
      const idx = await ask({
        title: 'Какую отцепить',
        list: kids.map((k) => ({ label: k.name, value: String(k.index) })),
        ok: 'Отцепить',
      });
      if (idx !== null) {
        await applyStructure(
          await api.removeParticleChild(pSystem, Number(idx)));
      }
    }
  },

  async layer() {
    const res = await api.addParticleLayer(pSystem);
    await applyStructure(res, { reselect: res.selected });
    if (!res.error) say('Слой добавлен — задайте ему параметры и текстуру');
  },

  /** Родные цвета текстур: у системы и детей снимаются модули тинта. */
  async natural() {
    const yes = await ask({
      title: 'Показать родные цвета текстур?',
      text: 'У этой системы и её дочерних будут удалены модули цвета, '
          + 'а базовый цвет станет белым.',
      ok: 'Убрать подкраску',
    });
    if (!yes) return;
    const res = await api.useParticleTextureColors(pSystem);
    if (res.error) { say(res.error); return; }
    withParticles((w) => w.loadParticleData({ ...res, rootName: pSystem }));
    await showParams(pSystem);
    say(res.removed ? `Удалено модулей цвета: ${res.removed}`
                    : 'Модулей цвета не было — текстуры уже в родных цветах');
  },

  async remove() {
    const yes = await ask({ title: 'Удалить систему?', text: pSystem,
                            ok: 'Удалить' });
    if (!yes) return;
    await applyStructure(await api.removeParticleSystem(pSystem));
  },
};

// ── Контекстные меню ─────────────────────────────────────────────────────
// Как в панели приложения: набор пунктов зависит от того, на чём щёлкнули.
// Правая кнопка на системе даёт одно, на модуле — другое, на параметре —
// третье. Разделитель — пункт со значением null.

const menuEl = document.createElement('div');
menuEl.className = 'menu__list ctx';
menuEl.hidden = true;
document.body.append(menuEl);

/** Показывает меню в точке события; отдаёт значение пункта или null. */
function contextMenu(e, items) {
  e.preventDefault();
  menuEl.innerHTML = '';
  return new Promise((resolve) => {
    const close = (value) => {
      menuEl.hidden = true;
      document.removeEventListener('mousedown', onAway, true);
      document.removeEventListener('keydown', onKey, true);
      resolve(value);
    };
    const onAway = (ev) => { if (!menuEl.contains(ev.target)) close(null); };
    const onKey = (ev) => { if (ev.key === 'Escape') close(null); };

    for (const item of items) {
      if (!item) {
        const hr = document.createElement('div');
        hr.className = 'ctx__sep';
        menuEl.append(hr);
        continue;
      }
      const b = document.createElement('button');
      b.className = 'menu__item';
      b.type = 'button';
      b.textContent = item.label;
      b.disabled = Boolean(item.disabled);
      b.addEventListener('click', () => close(item.value));
      menuEl.append(b);
    }

    menuEl.hidden = false;
    // Меню не должно уезжать за край: у нижних строк дерева места вниз нет.
    const box = menuEl.getBoundingClientRect();
    const x = Math.min(e.clientX, innerWidth - box.width - 8);
    const y = Math.min(e.clientY, innerHeight - box.height - 8);
    menuEl.style.left = Math.max(8, x) + 'px';
    menuEl.style.top = Math.max(8, y) + 'px';

    document.addEventListener('mousedown', onAway, true);
    document.addEventListener('keydown', onKey, true);
  });
}

//: Копирование есть у всего, кроме детей: там ссылки, а не параметры. Первый
//: пункт зависит от узла — копируют либо то, на чём щёлкнули, либо всё.
function copyItems(label) {
  return [
    ...(label ? [{ label, value: 'copyone' }] : []),
    { label: 'Копировать все параметры системы', value: 'copy' },
    { label: 'Вставить параметры', value: 'paste' },
  ];
}

/** Меню системы — то же, что было на дереве систем в приложении. */
async function systemMenu(e, name) {
  pSystem = name;
  const chosen = await contextMenu(e, [
    { label: 'Добавить слой со своей текстурой…', value: 'layer' },
    null,
    { label: 'Переименовать систему…', value: 'rename' },
    { label: 'Дублировать систему…', value: 'duplicate' },
    { label: 'Добавить дочернюю…', value: 'child' },
    { label: 'Удалить систему', value: 'remove' },
    null,
    { label: 'Цвета текстуры (снять подкраску)', value: 'natural' },
    null,
    ...copyItems(null),
  ]);
  if (chosen) await PACTS[chosen]();
}

/** Меню в дереве свойств. Что предложить — решает узел под курсором. */
async function expertMenu(e, node) {
  const { group, index, attr } = node;
  let items;
  if (group === 'children') {
    items = index === null
      ? [{ label: 'Добавить дочернюю…', value: 'child' }]
      : [{ label: 'Отцепить дочернюю', value: 'detach' }];
  } else if (index === null) {
    // Заголовок группы: сюда добавляют модуль, отсюда копируют её целиком.
    const label = group ? `Копировать группу «${group}»` : null;
    items = [...copyItems(label), null,
             { label: 'Добавить модуль…', value: 'module' }];
  } else if (attr) {
    items = [...copyItems(`Копировать параметр «${attr}»`), null,
             { label: 'Добавить параметр…', value: 'attr' },
             { label: 'Удалить параметр (вернуть умолчание)', value: 'delattr' }];
  } else {
    items = [...copyItems('Копировать этот модуль'), null,
             { label: 'Добавить параметр…', value: 'attr' },
             { label: 'Удалить модуль', value: 'delmodule' }];
  }

  const chosen = await contextMenu(e, items);
  if (!chosen) return;
  // Узел под курсором и есть адрес: кнопке «Параметр +» иначе пришлось бы
  // угадывать, в какой модуль добавлять.
  ctxNode = node;
  await PACTS[chosen]();
  ctxNode = null;
}

//: Узел, на котором открыли меню — адрес для действий над модулем.
let ctxNode = null;

/**
 * Сборка мода с эффектом.
 *
 * Сначала проверка: типовые поломки (нет рендерера, нулевой максимум частиц)
 * видно только в игре, и находить их там — это заново собирать и перезапускать
 * TF2. Часть находок чинится сама.
 */
async function buildParticles() {
  setStatus('Проверка эффекта…', true);
  const lint = await api.particleLint(pSystem);
  if (lint.error) { setStatus(lint.error, false); return; }

  const bad = lint.findings || [];
  if (bad.length) {
    const fixable = bad.filter((f) => f.fixable).length;
    const answer = await ask({
      title: 'Проверка перед сборкой',
      text: bad.slice(0, 5).map((f) => (f.system ? f.system + ': ' : '') + f.message)
               .join('\n') + (bad.length > 5 ? `\n…и ещё ${bad.length - 5}` : ''),
      list: [
        ...(fixable ? [{ label: `Исправить (${fixable}) и собрать`, value: 'fix' }] : []),
        { label: 'Собрать как есть', value: 'as_is' },
      ],
      ok: 'Дальше',
    });
    if (!answer) { setStatus('Готово', false); return; }
    if (answer === 'fix') {
      const fixed = await api.fixParticleLint(pSystem);
      await applyStructure(fixed);
    }
  }

  const name = await ask({ title: 'Имя файла мода',
                           value: (pSystem || 'particles') + '.vpk' });
  if (!name) { setStatus('Готово', false); return; }

  setStatus('Сборка VPK…', true);
  const res = await api.exportParticlesVpk(name);
  if (res.error) { setStatus(res.error, false); return; }

  // Обход sv_pure в казуале не грузит PCF больше оригинального: выросший
  // файл просто не заработает, и знать об этом надо до похода в игру.
  const over = res.overflow;
  setStatus(over && over > 0
    ? `Собрано, но PCF на ${over} Б больше оригинала — в казуале не загрузится`
    : `Собрано: ${res.path}`, false);
}

// ── Текстуры эффекта ─────────────────────────────────────────────────────
// Карточки материалов в той же половине сцены, где у оружия альбом текстур.
// Двойной клик или перетаскивание картинки — своя текстура, правая кнопка —
// остальное. Разница между «своей картинкой» и «материалом игры» важна:
// первая добавляет в мод новый файл, и в казуале обход sv_pure его не берёт.

//: Скрытый выбор файла — один на все карточки.
const pickFile = document.createElement('input');
pickFile.type = 'file';
pickFile.accept = 'image/*';
pickFile.hidden = true;
document.body.append(pickFile);

function chooseFile(accept = 'image/*') {
  return new Promise((resolve) => {
    pickFile.value = '';
    pickFile.accept = accept;
    pickFile.onchange = () => resolve(pickFile.files[0] || null);
    pickFile.click();
  });
}

const chooseImage = () => chooseFile('image/*');

/** Загружает картинку на диск и ставит её материалу. */
async function applyTexture(material, file, sheet) {
  if (!file) return;
  // Покадровая анимация: одна картинка вместо листа кадров остановит её.
  if (sheet) {
    const yes = await ask({
      title: 'У текстуры покадровая анимация',
      text: 'Своя картинка встанет одним кадром, и анимация пропадёт.',
      ok: 'Всё равно заменить',
    });
    if (!yes) return;
  }
  say('Замена текстуры…');
  const path = await api.upload(file);
  const res = await api.setParticleTexture(material, path);
  if (res.error) { say(res.error); return; }
  withParticles((w) => w.loadParticleData({ ...res, rootName: pSystem }));
  await showParticleMaterials();
  say('');
}

/** Меню материала — то же, что было на карточке в 2D приложения. */
async function materialMenu(e, mat) {
  const chosen = await contextMenu(e, [
    { label: 'Своя картинка…', value: 'image' },
    { label: 'Игровая текстура из списка…', value: 'game' },
    null,
    { label: 'Переименовать материал…', value: 'rename' },
    { label: 'Вернуть текстуру игры', value: 'reset', disabled: !mat.custom },
  ]);
  if (!chosen) return;

  if (chosen === 'image') {
    await applyTexture(mat.name, await chooseImage(), mat.sheet);
    return;
  }
  if (chosen === 'game') {
    const all = await api.gameParticleMaterials();
    const pickd = await ask({
      title: 'Текстура из эффектов игры',
      text: 'Такой материал уже есть в игре, поэтому мод работает в казуале.',
      list: all.map((n) => ({ label: n, value: n })),
      ok: 'Заменить',
    });
    if (!pickd) return;
    const res = await api.setParticleMaterialToGame(mat.name, pickd);
    if (res.error) { say(res.error); return; }
    withParticles((w) => w.loadParticleData({ ...res, rootName: pSystem }));
    await showParticleMaterials();
    return;
  }
  if (chosen === 'rename') {
    const name = await ask({ title: 'Новый путь материала', value: mat.name });
    if (!name || name === mat.name) return;
    const res = await api.renameParticleMaterial(mat.name, name);
    if (res.error) { say(res.error); return; }
    withParticles((w) => w.loadParticleData({ ...res, rootName: pSystem }));
    await showParticleMaterials();
    return;
  }
  if (chosen === 'reset') {
    const res = await api.resetParticleTexture(mat.name);
    if (res.error) { say(res.error); return; }
    withParticles((w) => w.loadParticleData({ ...res, rootName: pSystem }));
    await showParticleMaterials();
  }
}

/** Рисует карточки материалов эффекта. */
async function showParticleMaterials() {
  // Материалы ВЫБРАННОГО эффекта, а не всего файла: в PCF систем десятки,
  // и чужая карточка предлагала бы заменить не ту текстуру.
  const mats = await api.particleMaterials(pSystem);
  stage.tabs.innerHTML = '';
  stage.album.innerHTML = '';

  for (const mat of mats) {
    const tab = document.createElement('button');
    tab.className = 'mattab';
    // Заменённую текстуру отмечаем так же, как у оружия: точкой у имени.
    tab.innerHTML = mat.custom ? '<span class="mattab__mark"></span>' : '';
    tab.append(mat.name.split(/[\\/]/).pop());
    stage.tabs.append(tab);

    const fig = document.createElement('figure');
    fig.className = 'frame';
    fig.dataset.mat = mat.name;
    fig.innerHTML = '<div class="frame__img"></div>'
                  + '<figcaption class="frame__name"></figcaption>';
    fig.querySelector('.frame__name').textContent = mat.name;
    fig.title = `${mat.width}×${mat.height}`
              + (mat.sheet ? ' · покадровая анимация' : '');
    if (mat.dataUrl) {
      const img = document.createElement('img');
      img.src = mat.dataUrl;
      img.alt = mat.name;
      fig.querySelector('.frame__img').append(img);
    }

    fig.addEventListener('dblclick',
      async () => applyTexture(mat.name, await chooseImage(), mat.sheet));
    fig.addEventListener('contextmenu', (e) => materialMenu(e, mat));
    fig.addEventListener('dragover', (e) => {
      e.preventDefault();
      fig.classList.add('is-drop');
    });
    fig.addEventListener('dragleave', () => fig.classList.remove('is-drop'));
    fig.addEventListener('drop', (e) => {
      e.preventDefault();
      fig.classList.remove('is-drop');
      applyTexture(mat.name, e.dataTransfer.files[0], mat.sheet);
    });

    stage.album.append(fig);
  }
  bindAlbum();
}

/** Рисует панель параметров выбранной системы. */
async function showParams(system) {
  pSystem = system;
  const expert = pMode === 'expert';
  plist.hidden = expert;
  pfind.hidden = !expert;
  document.getElementById('pexpert').hidden = !expert;
  if (expert) {
    pnote.hidden = true;
    await showExpert(system);
    // Запрос переживает смену системы: ищут обычно одно и то же в разных.
    if (pfind.value) filterExpert(pfind.value);
    return;
  }

  const list = await api.particleParams(system);
  if (pSystem !== system) return;              // выбор успел смениться

  plist.innerHTML = '';
  pnote.hidden = list.length > 0;
  for (const param of list) {
    const row = document.createElement('div');
    row.className = 'params__row';
    row.innerHTML = '<span class="params__name"></span><div class="params__in"></div>';
    row.querySelector('.params__name').textContent = param.name;
    row.title = param.hint || '';
    const box = row.querySelector('.params__in');

    // value = null означает «модуля под параметром нет». Если создать его
    // нельзя (эмиттеры), поле не врём — гасим и говорим почему.
    const shown = param.value === null ? param.placeholder : param.value;
    const dead = param.value === null && !param.creatable;

    if (param.kind === 'color_pair') {
      shown.forEach((c, n) => box.append(colorField(c, (v) => {
        const pair = shown.map((x) => x.slice());
        pair[n] = v;
        editParam(param, pair);
      })));
    } else if (param.kind === 'range') {
      // Минимум и максимум — своя пара «дорожка + поле» у каждого: одной
      // дорожкой на два конца управлять неудобно, а концы правят порознь.
      shown.forEach((v, n) => box.append(pairedField(v, param, (x) => {
        const pair = shown.slice();
        pair[n] = x;
        // Границы диапазона не должны переползать друг через друга.
        if (n === 0) pair[1] = Math.max(pair[1], x);
        else pair[0] = Math.min(pair[0], x);
        editParam(param, pair);
      })));
    } else {
      box.append(pairedField(shown, param, (v) => editParam(param, v)));
    }

    if (dead) {
      box.querySelectorAll('input').forEach((i) => { i.disabled = true; });
      row.title = 'В этой системе нет модуля для этого параметра, а создавать '
                + 'его нельзя: лишний эмиттер задваивает залп.';
    }
    plist.appendChild(row);
  }
}

/** Выбор системы: движок строит эффект от названного узла. */
function pickSystem(button, item) {
  els.grid.querySelectorAll('.tree__name, .pick')
          .forEach((b) => b.classList.remove('is-active'));
  button.classList.add('is-active');
  document.querySelector('.title__name').textContent = item.name;
  closeCat();
  withParticles((w) => w.setRootSystem(item.key));
  showParams(item.key);
  showParticleMaterials();
  if (!cpBox.hidden) cpFillIndexes();
}

// ── Контрольные точки ────────────────────────────────────────────────────
// Движок держит их у себя (позиция, углы, пресет движения); отсюда только
// команды. Номера точек, которые эффекту нужны, считает Python — вычитать их
// из дерева свойств вручную никто не станет.

const cpBox = document.getElementById('cp');
const cpEl = (id) => document.getElementById(id);
//: Текущая точка. Ноль — та, вокруг которой строится почти всё в TF2.
let cpIndex = 0;
//: Точки крепления выбранной модели (имя, позиция, углы).
let cpAttachments = [];

const cpNum = (id) => Number(cpEl(id).value) || 0;

//: Своё состояние у каждой точки. Без него правка после переключения
//: переносила бы на новую точку значения предыдущей.
const cpState = new Map();
const CP_FIELDS = ['cp-x', 'cp-y', 'cp-z', 'cp-p', 'cp-yaw', 'cp-r',
                   'cp-amp', 'cp-period'];

/** Показывает в полях состояние выбранной точки. */
function cpLoad() {
  const st = cpState.get(cpIndex)
    || { values: [0, 0, 0, 0, 0, 0, 24, 2], motion: 'none' };
  CP_FIELDS.forEach((id, n) => { cpEl(id).value = st.values[n]; });
  cpEl('cp-motion').value = st.motion;
}

/** Шлёт движку положение, углы и пресет движения текущей точки. */
function cpPush() {
  const [x, y, z, p, yaw, r, amp, period] = CP_FIELDS.map(cpNum);
  const kind = cpEl('cp-motion').value;
  cpState.set(cpIndex, { values: [x, y, z, p, yaw, r, amp, period],
                         motion: kind });
  withParticles((w) => {
    w.setControlPoint(cpIndex, x, y, z);
    // Нулевые углы — это тоже углы: сбрасывать ориентацию надо явно, иначе
    // точка осталась бы повёрнутой от прошлой правки.
    if (p || yaw || r) w.setControlPointOrientation(cpIndex, p, yaw, r);
    else w.clearControlPointOrientation(cpIndex);
    w.setControlPointMotion(cpIndex, kind, amp, period);
  });
}

/** Рисует ряд номеров точек; нужные эффекту помечены. */
async function cpFillIndexes() {
  const box = cpEl('cp-index');
  const res = pSystem ? await api.particleControlPoints(pSystem) : { used: [] };
  const used = res.used || [];
  cpEl('cp-used').textContent = used.length
    ? 'эффекту нужны: ' + used.join(', ') : '';

  box.innerHTML = '';
  // Показываем нужные точки плюс небольшой запас: всего их 64, и рисовать
  // все — это ряд из шестидесяти четырёх кнопок ради двух используемых.
  const shown = [...new Set([...used, 0, 1, 2, 3])].sort((a, b) => a - b);
  for (const i of shown) {
    const b = document.createElement('button');
    b.className = 'tag' + (i === cpIndex ? ' is-active' : '');
    b.textContent = i;
    if (used.includes(i)) b.classList.add('is-used');
    b.title = used.includes(i) ? 'Эту точку эффект использует' : '';
    b.addEventListener('click', () => {
      cpIndex = i;
      cpLoad();            // у каждой точки своё положение
      cpFillIndexes();
    });
    box.append(b);
  }
}

for (const id of ['cp-x', 'cp-y', 'cp-z', 'cp-p', 'cp-yaw', 'cp-r',
                  'cp-amp', 'cp-period']) {
  cpEl(id).addEventListener('input', cpPush);
}
cpEl('cp-motion').addEventListener('change', cpPush);

cpEl('cp-reset').addEventListener('click', () => {
  cpState.delete(cpIndex);
  cpLoad();
  cpEl('cp-attach').value = '';
  cpPush();
});

document.getElementById('pcpbtn').addEventListener('click', (e) => {
  cpBox.hidden = !cpBox.hidden;
  e.target.classList.toggle('is-off', cpBox.hidden);
  // Ручка в кадре нужна только пока точку правят.
  withParticles((w) => w.setGizmoVisible(!cpBox.hidden));
  if (!cpBox.hidden) cpFillIndexes();
});

cpEl('cp-model').addEventListener('click', async () => {
  const models = await api.particleModels();
  if (!models.length) {
    say('В кэше нет разобранных моделей — откройте модель на вкладке оружия '
      + 'или шапок, и она появится здесь');
    return;
  }
  const qc = await ask({
    title: 'Модель из кэша декомпиляции',
    list: models.map((m) => ({ label: m.label, value: m.qc })),
    ok: 'Показать',
  });
  if (!qc) return;

  say('Сборка меша модели…');
  const scene = await api.particleModelScene(qc);
  if (scene.error) { say(scene.error); return; }
  cpAttachments = scene.attachments || [];
  cpEl('cp-model-name').textContent =
    models.find((m) => m.qc === qc)?.label || '';

  const sel = cpEl('cp-attach');
  sel.innerHTML = '';
  sel.append(new Option('— не выбрана —', ''));
  cpAttachments.forEach((a, i) => sel.append(new Option(a.name, String(i))));
  sel.disabled = cpAttachments.length === 0;

  withParticles((w) => {
    w.loadModelObj(scene.obj, scene.textures || {});
    w.setModelVisible(true);
  });
  cpScene(true);
  say('');
});

cpEl('cp-attach').addEventListener('change', () => {
  const a = cpAttachments[Number(cpEl('cp-attach').value)];
  if (!a) return;
  // Точка садится ровно туда, где она у модели: в игре эффект висит именно
  // на attachment, а не в произвольной точке рядом.
  const put = (ids, vals) => ids.forEach(
    (id, n) => { cpEl(id).value = Math.round(vals[n] * 10) / 10; });
  put(['cp-x', 'cp-y', 'cp-z'], a.pos);
  put(['cp-p', 'cp-yaw', 'cp-r'], a.angles);
  cpPush();
});

/** Переключает сцену: пустое пространство или модель под эффектом. */
function cpScene(onModel) {
  document.querySelectorAll('.cp__scene .tag').forEach(
    (b) => b.classList.toggle('is-active', (b.dataset.scene === 'model') === onModel));
  withParticles((w) => w.setModelVisible(onModel));
}

document.querySelector('.cp__scene').addEventListener('click', (e) => {
  const b = e.target.closest('[data-scene]');
  if (b) cpScene(b.dataset.scene === 'model');
});

// ── Отмена правок ────────────────────────────────────────────────────────
// Снимками занимается Python: он же и хранит дерево. Здесь только сочетание
// клавиш и перерисовка тем, что вернулось.

async function historyGo(delta) {
  const res = await api.undoParticles(delta);
  if (res.error) { say(res.error); return; }
  await applyStructure(res);
  if (res.materials) {
    withParticles((w) => w.loadParticleData({ ...res, rootName: pSystem }));
    await showParticleMaterials();
  }
  say(delta < 0 ? 'Правка отменена' : 'Правка возвращена');
}

document.addEventListener('keydown', (e) => {
  if (root.dataset.section !== 'particles' || !e.ctrlKey) return;
  // В поле ввода Ctrl+Z — это отмена ТЕКСТА, её перехватывать нельзя.
  const tag = (e.target.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
  const key = e.key.toLowerCase();
  if (key === 'z' && !e.shiftKey) { e.preventDefault(); historyGo(-1); }
  else if (key === 'y' || (key === 'z' && e.shiftKey)) {
    e.preventDefault();
    historyGo(1);
  }
});

document.getElementById('prestart').addEventListener('click',
  () => withParticles((w) => w.restartEffect()));

//: Состояние кнопок-переключателей. Движок своего состояния не отдаёт.
let pPaused = false;
let pLoop = true;

document.getElementById('ppause').addEventListener('click', (e) => {
  pPaused = !pPaused;
  e.target.textContent = pPaused ? 'Продолжить' : 'Пауза';
  withParticles((w) => w.setPaused(pPaused));
});

document.getElementById('ploop').addEventListener('click', (e) => {
  pLoop = !pLoop;
  e.target.classList.toggle('is-off', !pLoop);
  withParticles((w) => w.setLoop(pLoop));
});

/**
 * Переключение раздела.
 *
 * «Оружие» ходит в items() с категориями и типами, «Шапки» — в hats() с
 * поиском и классом: у косметики нет ни слотов оружия, ни подтипов, и
 * притворяться, что есть, значило бы показывать пустые фильтры.
 */
async function pickSection(name) {
  // Диагностика — отчёт, а не рабочее место: открываем окно и оставляем
  // текущий раздел на месте.
  if (name === 'Диагностика') {
    diagDlg.showModal();
    if (!document.getElementById('diag-status').textContent) {
      diagSay('Выберите собранный VPK-мод');
    }
    return false;
  }

  sel.section = { 'Шапки': 'hats', 'Частицы': 'particles' }[name] || 'weapons';
  root.dataset.section = sel.section;

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
    pSystem = '';
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

async function pickCategory(key) {
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
async function fillHatFilters() {
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

async function pickClass(key) {
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

async function pickType(key) {
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
async function fillCategories() {
  els.cat.innerHTML = '';
  for (const c of await api.categories()) els.cat.append(new Option(c.name, c.key));
}

/** Меню инструментов: у эффекта свои пункты, у предмета — свои.
 *  Зовётся и на старте: раздел «Оружие» открывается без pickSection, и без
 *  этого в меню висели пункты PCF при выбранном оружии. */
function applyToolsMenu(particlesSection) {
  document.querySelectorAll('#tools .menu__item').forEach((i) => {
    i.hidden = (i.dataset.for === 'particles') !== particlesSection;
  });
}

async function boot() {
  applyToolsMenu(false);
  showTf2Path();
  await fillCategories();
  els.cat.addEventListener('change', () => (sel.section === 'particles'
    ? loadPcf(els.cat.value) : pickCategory(els.cat.value)));
  await pickCategory('weapon');
}

boot().catch((err) => {
  els.note.hidden = false;
  els.note.textContent = 'Нет связи с Python: ' + err.message;
  console.error(err);
});

// Стартовые вызовы — в конце файла: syncViewerTheme и boot обращаются к
// объектам, объявленным ниже по тексту, и раньше падали на этом.
syncViewerTheme();
