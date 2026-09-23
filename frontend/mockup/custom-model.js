/*
 * Своя модель и её QC.
 *
 * Замена включается самим фактом загрузки — отдельной галочки нет ни здесь, ни
 * в приложении. Тип модели («готова» / «только геометрия») решает всё
 * дальнейшее, поэтому спрашиваем до показа.
 */

import * as api from './api.js';
import { ask } from './ask.js';
import { chooseFiles } from './util.js';
import { t } from './i18n.js';
import { say, viewer, withViewer } from './stage.js';
import { refreshView, reloadSceneIfFp } from './preview.js';
import { closeParts } from './parts.js';

/** Возвращает игровую модель вместо своей. */
export async function dropModel() {
  dropFitSave();            // подгонки больше не будет — и записывать нечего
  const res = await api.dropCustomModel();
  if (res.error) { say(res.error); return; }
  say('Своя модель убрана');
  refreshView();
  await reloadSceneIfFp();
}

// ── Своя модель и её QC ─────────────────────────────────────────────────
// Замена включается самим фактом загрузки: отдельной галочки нет ни здесь, ни
// в приложении. Тип модели («готова» / «только геометрия») решает всё
// дальнейшее, поэтому спрашиваем до показа.

/**
 * SMD — из Blender; OBJ/GLB/glTF — «из интернета», их приложение разбирает
 * само. Файлы рядом (MTL, .bin, картинки) выбирают вместе с моделью: все
 * ложатся в одну папку, и ссылки из OBJ/glTF находят их.
 */
export async function replaceModel() {
  const files = await chooseFiles(
    '.smd,.obj,.glb,.gltf,.mtl,.bin,.png,.jpg,.jpeg,.webp,.tga');
  const file = files.find((f) => /\.(smd|obj|glb|gltf)$/i.test(f.name));
  if (!file) { if (files.length) say('Среди выбранных файлов нет модели'); return; }

  say(`Конвертация ${file.name}…`);
  for (const extra of files) if (extra !== file) await api.upload(extra);
  const path = await api.upload(file);
  const first = await api.loadCustomModel(path);
  if (first.error) { say(first.error); return; }

  let keep = true;
  if (first.ask_keep) {
    const answer = await ask({
      title: 'Как использовать модель?',
      text: first.materials.length
        ? 'Материалы модели: ' + first.materials.join(', ')
        : 'Материалов в модели не нашлось.',
      list: [
        { label: 'Со своими материалами и костями',
          value: 'keep',
          hint: 'Каждый материал модели получит свой слот текстуры, кости с игровыми именами оживут в анимациях, QC можно править. Для моделей, сделанных под это оружие' },
        { label: 'Только форма — материалы оружия',
          value: 'geometry',
          hint: 'Все материалы модели схлопнутся в материал оружия: одна текстура на всё, кости игровые. Для моделей с сайта и простых замен' },
      ],
      ok: 'Загрузить',
    });
    if (!answer) return;
    keep = answer === 'keep';
  }

  const res = await api.loadCustomModel(path, keep);
  if (res.error) { say(res.error); return; }
  const notes = [keep ? 'Своя модель: материалы её собственные'
                      : 'Своя модель: геометрия ваша, текстуры игровые'];
  // Что приложение сделало само: скульпт из интернета упрощён до лимита
  // игры, базовый цвет из файла лёг в слоты.
  if (res.simplified) {
    notes.push(`упрощено: ${res.simplified[0]} → ${res.simplified[1]} треугольников`);
  }
  if (res.textures) notes.push(`текстур из файла: ${res.textures}`);
  // Каждую заметку переводим отдельно: склеенную строку словарь не узнаёт.
  say(notes.map(t).join('; '));
  refreshView();
  await reloadSceneIfFp();
}

// ── Подгонка своей модели и гирлянды ─────────────────────────────────────
// Значения — в осях SMD оружия (Y вверх, ствол по +Z), теми же, что запекает
// Python. Вьювер крутит модель сам и сразу (гизмо в кадре, как в Blender);
// SMD пересобирается после паузы в правке — он нужен только сборке и виду от
// первого лица. Кнопка «Масштабировать» включает режим: призрак оригинала в
// кадре, гизмо и палитра поверх кадра, как у частей. Режимы частей и
// подгонки взаимоисключающие: у обоих свой захват мыши в кадре.
//
// Цель подгонки две: своя модель ('model') и гирлянда праздничной версии
// ('decor') — её сдвигают под свою модель, чтобы огоньки легли на неё, а не
// висели там, где их повесила бы стоковая. Панель и клавиши у них общие,
// числа и запись — у каждой свои.

const fitPanel = document.getElementById('fitpanel');
const fitBtn = document.getElementById('fitbtn');
const partsBtn = document.getElementById('parts');
const FIT_FIELDS = ['fit-scale', 'fit-rx', 'fit-ry', 'fit-rz', 'fit-x', 'fit-y', 'fit-z'];
const fitEl = (id) => document.getElementById(id);
let fitTimer = null;
let fitOn = false;
let fitAvailable = false;
//: Что подгоняют сейчас и последние числа каждой цели (null — единица).
let fitTarget = 'model';
const fitValues = { model: null, decor: null };

const partsOpen = () => !document.getElementById('partsbar').hidden;
export const isFitOn = () => fitOn;
export const isDecorFitOn = () => fitOn && fitTarget === 'decor';

function fitRead() {
  const n = (id, d = 0) => { const v = Number(fitEl(id).value); return Number.isFinite(v) ? v : d; };
  const scale = n('fit-scale', 1) > 0 ? n('fit-scale', 1) : 1;
  return { scale, rotate: [n('fit-rx'), n('fit-ry'), n('fit-rz')],
           offset: [n('fit-x'), n('fit-y'), n('fit-z')] };
}

function fitWrite(fit) {
  const f = fit || { scale: 1, rotate: [0, 0, 0], offset: [0, 0, 0] };
  const vals = [f.scale, ...f.rotate, ...f.offset];
  FIT_FIELDS.forEach((id, i) => { fitEl(id).value = vals[i]; });
}

/** Кнопка подгонки доступна, когда в кадре своя модель; `fit` — её числа. */
export function showFit(fit) {
  fitAvailable = Boolean(fit);
  if (!fit && fitTarget === 'model') setFitMode(false);
  fitButtons();
  // Без подгонки вьювер тоже надо вернуть в ноль: иначе старый трансформ
  // пережил бы смену модели.
  applyTarget('model', fit);
}

/**
 * Гирлянда показана (`available`) и её подгонка (`fit`, null — стоковая).
 * Вьюверу числа отдаются всегда: гирлянда пересобирается при каждом показе,
 * и без них вставала бы на стоковое место.
 */
export function showDecorFit(fit, available) {
  if (!available && fitTarget === 'decor') setFitMode(false);
  applyTarget('decor', available ? fit : null);
}

/** Числа цели — во вьювер, а в поля только если её сейчас и правят. Пока
 *  человек крутит гизмо, ответ сервера его не перебивает. */
function applyTarget(target, fit) {
  fitValues[target] = fit || null;
  if (fitOn && fitTarget === target) {
    if (fitPending) return;              // своя правка ещё не записана
    fitWrite(fit);
  }
  const f = fit || { scale: 1, rotate: [0, 0, 0], offset: [0, 0, 0] };
  withViewer((w) => w.setFitTransform
    && w.setFitTransform(f.scale, f.rotate, f.offset, false, target));
}

/** Закрывает подгонку гирлянды, дождавшись записи её чисел. */
export async function leaveDecorFit() {
  const writing = flushFitSave();           // забирает отложенное сразу
  if (fitOn && fitTarget === 'decor') setFitMode(false);
  await writing;
}

/** Подгонка гирлянды: включает режим с целью «гирлянда» или гасит его. */
export function toggleDecorFit() {
  if (fitOn && fitTarget === 'decor') { setFitMode(false); return; }
  setFitMode(false);
  setFitMode(true, 'decor');
}

/** Кнопки режимов: каждая прячется, пока включён другой режим. */
function fitButtons() {
  fitBtn.hidden = !fitAvailable || partsOpen();
  if (fitOn) partsBtn.hidden = true;
}

function setFitMode(on, target = 'model') {
  const next = Boolean(on);
  if (next === fitOn) return;
  fitOn = next;
  if (fitOn) {
    fitTarget = target === 'decor' ? 'decor' : 'model';
    closeParts();
    fitWrite(fitValues[fitTarget]);
    // «Гнуть» и «Выпрямить» — только у гирлянды.
    fitPanel.querySelectorAll('[data-decor]').forEach(
      (b) => { b.hidden = fitTarget !== 'decor'; });
    if (fitTarget !== 'decor' && currentTool() === 'bend') markTool('scale');
  }
  fitPanel.hidden = !fitOn;
  fitBtn.classList.toggle('is-active', fitOn && fitTarget === 'model');
  const aim = fitTarget;
  withViewer((w) => {
    if (!w.setFitMode) return;
    w.setFitMode(fitOn, aim);
    if (fitOn) w.setFitTool(currentTool());
  });
  if (fitOn) fitButtons();
  // «Разделить на части» возвращается по общему правилу. Строго после записи:
  // иначе состояние вернуло бы числа до последнего движения гизмо.
  else {
    fitTarget = 'model';
    flushFitSave().then(refreshView);
  }
  document.dispatchEvent(new CustomEvent('fit:changed'));
}

fitBtn.addEventListener('click', () => setFitMode(!fitOn));
fitEl('fit-done').addEventListener('click', () => setFitMode(false));
// Части открываются — подгонка уходит первой (capture: раньше их обработчика).
partsBtn.addEventListener('click', () => setFitMode(false), true);
document.addEventListener('parts:changed', fitButtons);

function currentTool() {
  const b = fitPanel.querySelector('.ptools__btn[data-tool].is-active');
  return b ? b.dataset.tool : 'scale';
}

function markTool(tool) {
  fitPanel.querySelectorAll('.ptools__btn[data-tool]').forEach(
    (b) => b.classList.toggle('is-active', b.dataset.tool === tool));
  fitEl('fit-radius-box').hidden = tool !== 'bend';
}

fitPanel.addEventListener('click', (e) => {
  const b = e.target.closest('.ptools__btn[data-tool]');
  if (!b) return;
  markTool(b.dataset.tool);
  withViewer((w) => w.setFitTool && w.setFitTool(b.dataset.tool));
});

let fitPending = null;    // {target, fit} — числа, которые ждут записи

function fitSave(f) {
  // Другая цель — сначала записать прежнюю: иначе её правка потерялась бы.
  if (fitPending && fitPending.target !== fitTarget) flushFitSave();
  clearTimeout(fitTimer);
  fitValues[fitTarget] = f;
  fitPending = { target: fitTarget, fit: f };
  fitTimer = setTimeout(flushFitSave, 600);
}

/**
 * Записать ожидающую подгонку сейчас. Зовут перед всем, что читает SMD или
 * состояние: выход из режима перечитывает числа у Python, а сцена в руках
 * собирается из SMD — оба видели бы правку до последнего движения.
 */
export async function flushFitSave() {
  clearTimeout(fitTimer);
  fitTimer = null;
  const pending = fitPending;
  fitPending = null;
  if (!pending) return;
  try {
    const res = pending.target === 'decor'
      ? await api.setDecorFit(pending.fit)
      : await api.setCustomFit(pending.fit);
    if (res && res.error) say(res.error);
  } catch (err) {
    say(err.message);
  }
}

/**
 * Предмет сменился: отложенная запись подгонки принадлежала прошлому и на
 * новом либо падала ошибкой, либо запекла бы чужие числа в его модель.
 * Последние полсекунды правки теряются — они же и не были ещё записаны.
 */
export function dropFitSave() {
  clearTimeout(fitTimer);
  fitTimer = null;
  fitPending = null;
}

function fitPush(save = true, animate = false) {
  const f = fitRead();
  const aim = fitTarget;
  withViewer((w) => w.setFitTransform
    && w.setFitTransform(f.scale, f.rotate, f.offset, animate, aim));
  if (save) fitSave(f);
}

for (const id of FIT_FIELDS) fitEl(id).addEventListener('input', () => fitPush());
// Сброс — с движением: видно, откуда и куда вернулась модель.
fitEl('fit-reset').addEventListener('click', () => { fitWrite(null); fitPush(true, true); });

// Те же клавиши на странице: фокус после щелчка по кнопке остаётся у неё, а
// не у кадра. Как в Blender: G/R/S начинают операцию — модель идёт за
// мышью, X/Y/Z ограничивают ось, клик подтверждает, Esc отменяет; Esc без
// операции (или Enter) закрывает подгонку. В полях ввода буквы — текст, там
// не перехватываем.
const FIT_KEYS = { KeyG: 'translate', KeyR: 'rotate', KeyS: 'scale' };
const FIT_AXES = { KeyX: 'x', KeyY: 'y', KeyZ: 'z' };
document.addEventListener('keydown', (e) => {
  if (!fitOn || e.ctrlKey || e.metaKey || e.altKey) return;
  const tag = (e.target && e.target.tagName) || '';
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
  const w = viewer();
  if (e.code === 'Escape') { if (!(w && w.cancelFitOp && w.cancelFitOp())) setFitMode(false); return; }
  if (e.code === 'Enter') { setFitMode(false); return; }
  if (FIT_AXES[e.code]) { if (w && w.setFitAxis) w.setFitAxis(FIT_AXES[e.code]); return; }
  const tool = FIT_KEYS[e.code];
  if (!tool || !w || !w.startFitOp) return;
  e.preventDefault();
  w.startFitOp(tool);
});

// ── Изгибы гирлянды ─────────────────────────────────────────────────────
// Вьювер гнёт сам и после каждого движения присылает весь список; пишем его
// по очереди — ответы не должны обгонять друг друга.
let bendWrite = Promise.resolve();
//: Сколько списков ещё пишется. Пока > 0, состояние от Python старше того,
//: что во вьювере, и отдавать его вьюверу нельзя: он откатил бы последний
//: изгиб, а следующий дописал бы к откаченному — и тот пропал бы совсем.
let bendsPending = 0;

function saveBends(bends) {
  bendsPending += 1;
  bendWrite = bendWrite.then(async () => {
    try {
      await api.setDecorBends(bends);
    } catch (err) {
      say(err.message);
    } finally {
      bendsPending -= 1;
    }
  }).then(refreshView);
}

fitEl('fit-straighten').addEventListener('click', () => {
  withViewer((w) => w.setDecorBends && w.setDecorBends([]));
  saveBends([]);
});

fitEl('fit-radius').addEventListener('input', () => {
  const r = Number(fitEl('fit-radius').value);
  withViewer((w) => w.setBendRadius && w.setBendRadius(r));
});

/** Изгибы из состояния — вьюверу (отмена, возврат работы, новая гирлянда). */
export function showDecorBends(bends) {
  if (bendsPending) return;
  withViewer((w) => w.setDecorBends && w.setDecorBends(bends || []));
}

/** Гизмо в кадре сдвинули: числа и SMD — за ним. */
export function bindFitViewer(w) {
  w.onDecorBends = (bends) => saveBends(bends);
  w.onBendRadius = (r) => { fitEl('fit-radius').value = Math.round(r * 10) / 10; };
  w.onFitChanged = (f, target = 'model') => {
    if (!fitOn || target !== fitTarget) return;
    fitWrite(f);
    fitSave(f);
  };
  w.onFitTool = (tool) => markTool(tool);
}

// ── Редактор QC ─────────────────────────────────────────────────────────
const qcDlg = document.getElementById('qcdlg');
const qcText = document.getElementById('qc-text');

function qcSay(text, kind = '') {
  const el = document.getElementById('qc-status');
  el.textContent = text;
  el.className = 'label vmt__status' + (kind ? ' is-' + kind : '');
}

export async function openQcEditor() {
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
  if (btn.id === 'dropmodel') { dropModel(); return; }
  if (btn.dataset.cond === 'replace') replaceModel();
  else if (btn.dataset.cond === 'qc') openQcEditor();
});
