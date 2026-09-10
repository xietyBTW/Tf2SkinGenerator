/*
 * Мост к Python.
 *
 * Единственное место, которое знает о транспорте. Сейчас это dev-сервер по
 * HTTP; когда фронт переедет в окно WebView2, здесь появится ветка
 * `window.pywebview.api[method](params)` — и больше нигде менять не придётся.
 *
 * Сам набор методов и их результаты живут в src/app/api.py.
 */

//: Язык интерфейса. Ответам Python он не нужен — их язык берётся из общего
//: конфига (см. `api._lang` в Python), и раньше страница глушила настройку,
//: подставляя в каждый вызов 'ru'. Здесь он остался ради вьюверов: они живут
//: в отдельных документах и в конфиг не ходят.
let uiLang = 'en';
export const lang = () => uiLang;
export function setLang(value) { uiLang = value || 'en'; }

//: Куда писать обмен с Python. Ставится журналом; по умолчанию — никуда.
let sink = null;
export function setLogSink(fn) { sink = fn; }
function log(dir, text, kind) { if (sink) sink(dir, text, kind); }

//: Что НЕ пишем в журнал. Это опросы: страница дёргает их раз в секунду, и в
//: ленте обмена они вытесняют всё остальное. Отдельно смешно с log_tail —
//: открытая консоль засоряла бы сама себя.
const QUIET = new Set(['log_tail', 'update_progress']);

/** Вызывает метод прикладного API. Бросает Error с текстом от Python. */
export async function call(method, params = {}) {
  const quiet = QUIET.has(method);
  if (!quiet) log('→', method + '(' + JSON.stringify(params).slice(0, 120) + ')');

  // Хост-мост, когда страница открыта в окне приложения.
  const bridge = window.pywebview && window.pywebview.api;
  if (bridge && typeof bridge[method] === 'function') {
    return bridge[method](params);
  }

  const res = await fetch(`/api/${method}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  const data = await res.json().catch(() => ({ error: `${res.status} ${res.statusText}` }));
  if (data.error) {
    // Ошибку показываем ВСЕГДА, даже у тихих: молчащий опрос, который на
    // самом деле падает, — худший вид тишины.
    log('!', method + ': ' + data.error, 'err');
    throw new Error(data.error);
  }
  if (!quiet) log('←', method + ' → ' + JSON.stringify(data.result).slice(0, 160));
  return data.result;
}

//: Справочники не меняются за сессию, а спрашивают их на каждый клик по
//: фильтру. Без кэша смена класса делала три запроса подряд, и список успевал
//: моргнуть чужим содержимым.
const memo = new Map();

function cached(method, params) {
  const key = method + JSON.stringify(params);
  if (!memo.has(key)) {
    // Кэшируется ОБЕЩАНИЕ, а не ответ: иначе два одновременных запроса ушли бы
    // оба. Но неудачное обещание надо забыть — список игровых материалов
    // падает, пока не указан путь к игре, и закэшированный отказ держался бы
    // до перезапуска, хотя путь уже поправили в настройках.
    memo.set(key, call(method, params).catch((err) => {
      memo.delete(key);
      throw err;
    }));
  }
  return memo.get(key);
}

/** Забывает закэшированные справочники: сменился язык — сменились имена. */
export function forgetCached() { memo.clear(); }

//: Размер кэша моделей. Отдельно от settings(): считается обходом всей папки
//: и на большой библиотеке занимает секунды — окно настроек его не ждёт.
export const cacheSize = () => call('cache_size', {});

//: Версия и обновление. update_status ходит в сеть, поэтому страница зовёт его
//: после отрисовки; install_update качает установщик, запускает его и ГАСИТ
//: приложение — ответ приходит раньше, чем оно закроется.
export const updateStatus = (force = false) => call('update_status', { force });
export const installUpdate = () => call('install_update', {});
export const updateProgress = () => call('update_progress', {});

export const categories   = () => cached('categories', {});
export const classes      = () => cached('classes', {});
export const weaponTypes  = (tf2_class) => cached('weapon_types', { tf2_class });
export const items        = (params) => call('items', params);
export const hats         = (params) => call('hats', params);
export const particleFiles = () => cached('particle_files', {});
export const loadParticles = (source) => call('load_particles', { source });
export const particleParams = (system) => call('particle_params', { system });
export const setParticleParam = (system, key, value) =>
  call('set_particle_param', { system, key, value });
export const particleSystem = (system) => call('particle_system', { system });
export const setParticleAttr = (system, group, index, attr, value) =>
  call('set_particle_attr', { system, group, index, attr, value });

// Правка структуры эффекта: модули, параметры, системы. Всё возвращает
// свежие systems и tree — каталог и свойства перерисовываются одним ответом.
export const particleModules  = (group) => cached('particle_module_catalog', { group });
export const addParticleModule = (system, group, function_name) =>
  call('add_particle_module', { system, group, function_name });
export const removeParticleModule = (system, group, index) =>
  call('remove_particle_module', { system, group, index });
export const particleMissingAttrs = (system, group, index) =>
  call('particle_missing_attrs', { system, group, index });
export const addParticleAttr = (system, group, index, attr, attr_type, value) =>
  call('add_particle_attr', { system, group, index, attr, attr_type, value });
export const removeParticleAttr = (system, group, index, attr) =>
  call('remove_particle_attr', { system, group, index, attr });
export const copyParticleParams = (system, group = null, index = null, attr = null) =>
  call('copy_particle_params', { system, group, index, attr });
export const pasteParticleParams = (system, payload, mode = 'overwrite') =>
  call('paste_particle_params', { system, payload, mode });
export const duplicateParticleSystem = (system, new_name) =>
  call('duplicate_particle_system', { system, new_name });
export const renameParticleSystem = (system, new_name) =>
  call('rename_particle_system', { system, new_name });
export const removeParticleSystem = (system) =>
  call('remove_particle_system', { system });
export const particleChildren = (system) => call('particle_children', { system });
export const addParticleChild = (parent, child, delay = 0) =>
  call('add_particle_child', { parent, child, delay });
export const removeParticleChild = (parent, index) =>
  call('remove_particle_child', { parent, index });
export const addParticleLayer = (parent) => call('add_particle_layer', { parent });
export const particleHistory = () => call('particle_history');
export const undoParticles = (delta = -1) =>
  call('undo_particles', { delta });
export const particleControlPoints = (system) =>
  call('particle_control_points', { system });
export const particleModels = () => call('particle_models');
export const particleModelScene = (qc) =>
  call('particle_model_scene', { qc });
export const particleMaterials = (system = '') =>
  call('particle_materials', { system });
export const setParticleTexture = (material, path, max_size = 512) =>
  call('set_particle_texture', { material, path, max_size });
export const resetParticleTexture = (material) =>
  call('reset_particle_texture', { material });
export const gameParticleMaterials = () => cached('game_particle_materials', {});
export const setParticleMaterialToGame = (material, game_material) =>
  call('set_particle_material_to_game', { material, game_material });
export const renameParticleMaterial = (material, new_material) =>
  call('rename_particle_material', { material, new_material });
export const useParticleTextureColors = (system) =>
  call('use_particle_texture_colors', { system });
export const particleLint = (system = '') => call('particle_lint', { system });
export const fixParticleLint = (system = '') => call('fix_particle_lint', { system });
export const saveParticles = (path) => call('save_particles', { path });
export const exportParticlesVpk = (name) => call('export_particles_vpk', { name });
export const particleReference = (path = '', for_ai = false) =>
  call('particle_param_reference', { path, for_ai });
export const hatFilters   = () => call('hat_filters');
export const setHatFilter = (tag, hidden) => call('set_hat_filter', { tag, hidden });
export const modeFor      = (category, subtype = null) => call('mode_for', { category, subtype });
// restore — открыть предмет с сохранённой работой. Из каталога он
// открывается ИГРОВЫМ: свои работы лежат своим списком (`works`).
export const loadPreview  = (mode, lang = null, model_key = null,
                             per_class = null, style = null, restore = false) =>
  call('load_preview', { mode, lang, model_key, per_class, style, restore });
export const works        = () => call('works', {});
export const stopPreview  = () => call('stop_preview');
export const viewState    = () => call('view_state');
export const setTeam      = (team) => call('set_team', { team });
export const setAustralium = (active) => call('set_australium', { active });
export const setSkin      = (index) => call('set_skin', { index });
export const addToStyle   = (material) => call('add_to_style', { material });
export const dropFromStyle = (material) => call('drop_from_style', { material });
export const toggleMisc   = (on = null) => call('toggle_misc', { on });
export const forceTeam    = () => call('force_team');

// Инструменты: извлечение оригиналов и объединение модов. Результат приходит
// событием (tool_done / extract_files), ответ говорит лишь о запуске.
export const extractModel = () => call('extract_model');
export const exportModelFiles = (files) => call('export_model_files', { files });
export const extractTexture = (textures = null) => call('extract_texture', { textures });
export const exportVpks   = () => call('export_vpks');
export const mergeVpk     = (files, name, confirmed = false) =>
  call('merge_vpk', { files, name, confirmed });

// Карты материала: схему (какие бывают и что настраивается) держит Python —
// список карт и их параметры на странице не дублируются.
export const mapSchema    = () => cached('material_map_schema', {});
export const textureMaps  = (material) => call('texture_maps', { material });
export const setTextureMaps = (material, maps) =>
  call('set_texture_maps', { material, maps });

// Пер-текстурные настройки сборки: какой материал собирается не как все.
export const textureSettings = (material) => call('texture_settings', { material });
export const setTextureSettings = (material, settings) =>
  call('set_texture_settings', { material, settings });
export const textureBadges = () => call('texture_badges');
// known_shape — отпечаток разбиения, который у страницы уже есть. Совпал —
// Python не шлёт карты треугольников: они почти весь ответ, а меняются только
// от резки, тогда как сам запрос идёт после каждого мазка кистью.
export const parts          = (material = '', known_shape = '') =>
  call('parts', { material, known_shape });
export const setPartTexture = (material, part, path = null, options = null) =>
  call('set_part_texture', { material, part, path, options });
export const partShape = (material, part) =>
  call('part_shape', { material, part });
export const partMask = (material, part) =>
  call('part_mask', { material, part });
export const setPartColors  = (material, colors, strength = null,
                               exact = null) =>
  call('set_part_colors', { material, colors, strength, exact });
export const clearParts     = (material = '') => call('clear_parts', { material });
export const setPartEdge    = (material, width, color) =>
  call('set_part_edge', { material, width, color });
export const undoParts      = (material = '') => call('undo_parts', { material });
export const redoParts      = (material = '') => call('redo_parts', { material });

// Работа над предметом. Автосохранение пишет черновик молча (если это не
// выключено), а в библиотеку работа попадает только по `keepWork`.
export const workState    = () => call('work_state');
export const keepWork     = () => call('keep_work');
export const restoreWork  = () => call('restore_work');
export const forgetWork   = () => call('forget_work');
// Черновики: их не видно в библиотеке, поэтому убираются отдельно, из настроек.
export const drafts       = () => call('drafts', {});
export const forgetDrafts = (keys = null) => call('forget_drafts', { keys });

// Библиотека модов: папка на диске, она же список. Открытый мод сохраняется
// туда, чтобы вернуться к нему потом.
export const modLibrary   = () => call('mod_library');
export const addMod       = (path) => call('add_mod', { path });
export const modIcon      = (name) => call('mod_icon', { name });

// ── Звуки ─────────────────────────────────────────────────────────────── //
export const sounds        = (family = '', tf2_class = '', query = '',
                              section = '') =>
  call('sounds', { family, tf2_class, query, section });
export const soundSections = () => call('sound_sections', {});
export const soundFamilies = (section = '') =>
  call('sound_families', { section });
export const setSound      = (name, path = null, wave = '') =>
  call('set_sound', { name, path, wave });
export const saveSound     = (name, wave = '') => call('save_sound', { name, wave });
export const buildSounds   = (filename = '') => call('build_sounds', { filename });

/** URL игрового звука прямо из VPK. Путь — от корня `sound/`. */
export const soundUrl = (path) => '/sound?wave=' + encodeURIComponent(path);
export const removeMod    = (name) => call('remove_mod', { name });
export const loadVpkMod   = (path) => call('load_vpk_mod', { path });
export const diagnose     = (path) => call('diagnose', { path });

// Настройки приложения: конфиг общий с окном, поэтому правка видна обоим.
export const settings     = () => call('settings');
export const clearModelCache = () => call('clear_model_cache');
//: Меню «Вставить» в редакторе VMT: набор не меняется за сеанс.
export const vmtSnippets  = () => cached('vmt_snippets', {});
export const setSettings  = (values) => call('set_settings', { values });
//: Мелочь раскладки (ширина панели, громкость): её правят прямо на экране, и
//: сохраняется она по одной, а не всем окном настроек разом.
export const setUiState   = (key, value) => call('set_ui_state', { key, value });

//: Журнал Python. Забирается опросом по номеру последней взятой записи и
//: только пока консоль открыта (см. log.js — почему не потоком событий).
export const logTail      = (since) => call('log_tail', { since });
export const clearLog     = () => call('clear_log', {});
export const logFolder    = () => call('log_folder', {});

// Своя модель: сначала спрашиваем тип (keep=null), потом грузим с ответом.
export const loadCustomModel = (path, keep = null) =>
  call('load_custom_model', { path, keep });
export const dropCustomModel = () => call('drop_custom_model');
export const qcText       = () => call('qc_text');
export const saveQc       = (text) => call('save_qc', { text });

// Редактор VMT.
export const vmtParams    = () => cached('vmt_params', {});
export const openVmt      = (material) => call('open_vmt', { material });
export const saveVmt      = (material, content, original) =>
  call('save_vmt', { material, content, original });
export const resetVmt     = (material) => call('reset_vmt', { material });
// full — собрать сцену целиком: страница просит это, когда дорожки не
// легли (сцены в кадре не оказалось). Обычная смена анимации идёт без
// него и обходится одними дорожками.
// Насмешка: персонаж играет тонт с реквизитом. Класс выбирают на странице —
// одну и ту же насмешку умеют до девяти классов, и модель у каждого своя.
export const loadTaunt    = (tf2_class = '') => call('load_taunt', { tf2_class });
export const loadFirstPerson = (action = 'IDLE', full = false) =>
  call('load_first_person', { action, full });
export const leaveFirstPerson = () => call('leave_first_person');
export const setPartDetail = (material, detail) =>
  call('set_part_detail', { material, detail });
export const togglePartIsland = (material, group, island) =>
  call('toggle_part_island', { material, group, island });
export const mergePartIslands = (material, group, islands) =>
  call('merge_part_islands', { material, group, islands });
export const loadSkybox   = (sky_name) => call('load_skybox', { sky_name });
export const setTexture   = (material, path) => call('set_texture', { material, path });
export const build        = (params) => call('build', { params });
//: Сборка шапки на девять классов идёт минуты — передумать надо давать.
export const cancelBuild  = () => call('cancel_build');
export const vtfEstimate  = (size, format, flags) =>
  call('vtf_estimate', { size, format, flags });
export const answerTexture = (choice, path = '', apply_all = false) =>
  call('answer_texture', { choice, path, apply_all });
export const exportUv     = (size = 1024) => call('export_uv', { size });

/** Кладёт файл во временную папку и возвращает его путь на диске. */
export async function upload(file) {
  const res = await fetch('/upload?name=' + encodeURIComponent(file.name), {
    method: 'POST', body: file,
  });
  const data = await res.json();
  if (data.error) throw new Error(data.error);
  return data.result.path;
}

/**
 * Подписка на события воркеров.
 *
 * Воркеры работают в своих потоках, и результат приезжает не ответом на
 * запрос, а потоком: progress → model_ready → materials. В окне приложения
 * события будет толкать pywebview через evaluate_js — там достаточно завести
 * глобальный приёмник; здесь их приносит SSE.
 */
export function subscribe(onEvent) {
  if (window.pywebview) {
    window.__tf2Event = onEvent;      // pywebview вызовет его из Python
    return () => { delete window.__tf2Event; };
  }
  const src = new EventSource('/events');
  src.onmessage = (e) => {
    try {
      const ev = JSON.parse(e.data);
      log('↓', ev.event + ' ' + JSON.stringify(ev).slice(0, 200),
          ev.event === 'failed' ? 'err' : '');
      onEvent(ev);
    } catch (err) {
      log('!', 'битое событие: ' + e.data, 'err');
      console.error('битое событие', e.data, err);
    }
  };
  // Браузер сам переподключается при обрыве — глушим только шум в консоли.
  src.onerror = () => {};
  return () => src.close();
}

/** URL файла, который сделал воркер (модель, текстура). */
// opaque=1 — PNG без альфы: в игровых текстурах она маска бликов, и на плоском
// показе картинка выглядела бы призраком (см. devserver._drop_alpha).
export const fileUrl = (path, opaque = false) =>
  '/file?path=' + encodeURIComponent(path) + (opaque ? '&opaque=1' : '');

/** То же, но без альфа-канала — для плоского показа текстуры.
 *  В игровых VTF альфа обычно маска бликов, и на карточке текстура из-за неё
 *  выглядит призраком. Вьюверу альфа нужна, ему отдаём обычный файл. */
export const opaqueUrl = (path) => fileUrl(path) + '&opaque=1';

/** URL иконки предмета из рюкзака. Ключ — icon из items_game, ключ оружия или
 *  путь к модели: что именно с ним делать, решает Python. Нет иконки — 404,
 *  и карточка каталога просто остаётся без картинки. */
export const iconUrl = (key) => '/icon?key=' + encodeURIComponent(key);
