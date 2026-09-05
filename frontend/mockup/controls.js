/*
 * Что показывать при этом режиме — и правка настроек одного материала.
 *
 * Таблицы правил здесь нет НАМЕРЕННО: `api.controls_for(mode)` отдаёт готовый
 * ответ по тем же условиям, что и приложение (frontend/CONTROLS.md), а
 * представление только применяет его. Иначе правила разъедутся.
 *
 * Шестерёнка на кадре переводит панель сборки в правку ЭТОГО материала:
 * глобальные значения стэшатся и возвращаются на выходе. Своя запись
 * появляется только от реального изменения контрола — открытие настройки её
 * не создаёт, ровно как в панели приложения.
 */

import * as api from './api.js';
import { say } from './stage.js';
import { build, floating } from './layout.js';
import { SINGLE_TEX } from './album.js';
import { sel } from './catalog.js';
import { buildParams, checkName } from './build.js';
import { openMaterialMaps } from './maps.js';
import { openVmtEditor } from './vmt.js';
import { applyView } from './preview.js';

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
  taunt: 'taunt',
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
const MODEL_DRIVEN = new Set(['misc', 'team', 'aus', 'qc', 'styles', 'parts']);

//: Последний ответ controls_for: applyView сверяется с ним, чтобы не показать
//: в режиме то, что режим запретил.
export let modeControls = {};

export function applyControls(c) {
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
  const flagCol = document.querySelector('.build__col[data-col="flags"]');
  flagCol.querySelectorAll('input').forEach((b, i) => {
    // Список флагов режима (null — все); Point Sample у скайбокса единственный
    // осмысленный, остальное там выставляет SkyboxService.
    const name = flagCol.querySelectorAll('.check span')[i].textContent.trim();
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
export let texEdit = null;

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
export function applySettings(st) {
  if (!st || !st.size) return;
  const size = Array.isArray(st.size) ? st.size[0] : st.size;
  const index = [256, 512, 1024, 2048].indexOf(Number(size));
  const radios = [...document.querySelectorAll('input[name="res"]')];
  if (index >= 0 && radios[index]) radios[index].checked = true;
  if (st.format) document.getElementById('fmt').value = st.format;

  const flags = new Set(st.flags || []);
  const options = st.options || {};
  for (const col of document.querySelectorAll('.build__col[data-col]')) {
    const isFlags = col.dataset.col === 'flags';
    if (!isFlags && col.dataset.col !== 'options') continue;
    col.querySelectorAll('.check').forEach((l) => {
      const name = checkName(l);
      const input = l.querySelector('input');
      input.checked = isFlags ? flags.has(name) : Boolean(options[name]);
    });
  }
}

export async function enterTextureEdit(material) {
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
export function markBadge(material, badge) {
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

// Кнопки под альбомом: обе про материал, который сейчас перед глазами.
// Пометки «свои настройки» переживают перерисовку альбома: карточки
// пересобираются на каждой модели, а записи живут в Python.
/**
 * Три кнопки про одну работу: сохранить, вернуть, забыть.
 *
 * Автосохранение пишет черновик молча — и раньше он же попадал в библиотеку:
 * человек просто открывал предмет, что-то трогал, и получал «мод», которого не
 * делал. Теперь молчаливая запись остаётся черновиком при предмете, а в раздел
 * «Кастомный мод» работа попадает только отсюда, нажатием.
 */
async function keepWork() {
  const res = await api.keepWork();
  if (res.error) { say(res.error); return; }
  say('Работа сохранена — она в разделе «Кастомный мод»');
  showWork(res);
}

async function restoreWork() {
  const res = await api.restoreWork();
  if (res.error) { say(res.error); return; }
  // applyView сам пересобирает альбом и через restoreBadges обновляет кнопки.
  applyView(res);
  say('Отложенные правки вернулись');
}

async function forgetWork() {
  const res = await api.forgetWork();
  if (res.error) { say(res.error); return; }
  applyView(res);
  say('Правки удалены');
}

/** Раскладывает кнопки по состоянию работы. */
function showWork(st) {
  const btn = (id) => document.getElementById(id);
  // Сохранять нечего, пока нет правок; сохранённую второй раз не сохраняют —
  // автосохранение и так пишет её дальше.
  btn('keep').hidden = !(st.has_edits && !st.kept);
  // Вернуть можно только то, чего сейчас на предмете нет.
  btn('restore').hidden = !(st.has_saved && !st.has_edits);
  btn('forget').hidden = !(st.has_saved || st.has_edits);
  btn('forget').textContent = st.kept ? 'Удалить работу' : 'Забыть правки';
}

async function syncWork() {
  showWork(await api.workState());
}

export async function restoreBadges() {
  const badges = await api.textureBadges();
  for (const [material, badge] of Object.entries(badges)) markBadge(material, badge);
  await syncWork();
}

document.querySelector('.half--flat .acts').addEventListener('click', (e) => {
  const btn = e.target.closest('.textbtn');
  if (!btn) return;
  if (btn.id === 'keep') { keepWork(); return; }
  if (btn.id === 'restore') { restoreWork(); return; }
  if (btn.id === 'forget') { forgetWork(); return; }
  if (btn.dataset.cond === 'maps') openMaterialMaps();
  else if (btn.id === 'vmt') openVmtEditor();
});

/** Спрашивает Python, что показывать при этом режиме, и применяет ответ. */
export async function setMode(mode) {
  sel.mode = mode;
  applyControls(await api.call('controls_for', { mode }));
}
