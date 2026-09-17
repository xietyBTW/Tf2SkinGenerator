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

  say('Конвертация ' + file.name + '…');
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
  say(notes.join('; '));
  refreshView();
  await reloadSceneIfFp();
}

// ── Подгонка своей модели ────────────────────────────────────────────────
// Значения — в осях SMD оружия (Y вверх, ствол по +Z), теми же, что запекает
// Python. Вьювер крутит модель сам и сразу (гизмо в кадре, как в Blender);
// SMD пересобирается после паузы в правке — он нужен только сборке и виду от
// первого лица. Кнопка «Масштабировать» включает режим: призрак оригинала в
// кадре, гизмо и палитра поверх кадра, как у частей. Режимы частей и
// подгонки взаимоисключающие: у обоих свой захват мыши в кадре.

const fitPanel = document.getElementById('fitpanel');
const fitBtn = document.getElementById('fitbtn');
const partsBtn = document.getElementById('parts');
const FIT_FIELDS = ['fit-scale', 'fit-rx', 'fit-ry', 'fit-rz', 'fit-x', 'fit-y', 'fit-z'];
const fitEl = (id) => document.getElementById(id);
let fitTimer = null;
let fitOn = false;
let fitAvailable = false;

const partsOpen = () => !document.getElementById('partsbar').hidden;
export const isFitOn = () => fitOn;

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
  if (!fit) setFitMode(false);
  fitButtons();
  // Без подгонки вьювер тоже надо вернуть в ноль: иначе старый трансформ
  // пережил бы смену модели.
  fitWrite(fit);
  fitPush(false);
}

/** Кнопки режимов: каждая прячется, пока включён другой режим. */
function fitButtons() {
  fitBtn.hidden = !fitAvailable || partsOpen();
  if (fitOn) partsBtn.hidden = true;
}

function setFitMode(on) {
  const next = Boolean(on);
  if (next === fitOn) return;
  fitOn = next;
  if (fitOn) closeParts();
  fitPanel.hidden = !fitOn;
  fitBtn.classList.toggle('is-active', fitOn);
  withViewer((w) => {
    if (!w.setFitMode) return;
    w.setFitMode(fitOn);
    if (fitOn) w.setFitTool(currentTool());
  });
  if (fitOn) fitButtons();
  // «Разделить на части» возвращается по общему правилу. Строго после записи:
  // иначе состояние вернуло бы числа до последнего движения гизмо.
  else flushFitSave().then(refreshView);
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
}

fitPanel.addEventListener('click', (e) => {
  const b = e.target.closest('.ptools__btn[data-tool]');
  if (!b) return;
  markTool(b.dataset.tool);
  withViewer((w) => w.setFitTool && w.setFitTool(b.dataset.tool));
});

let fitPending = null;    // числа, которые ждут записи в SMD

function fitSave(f) {
  clearTimeout(fitTimer);
  fitPending = f;
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
  const f = fitPending;
  fitPending = null;
  if (!f) return;
  const res = await api.setCustomFit(f);
  if (res.error) say(res.error);
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
  withViewer((w) => w.setFitTransform
    && w.setFitTransform(f.scale, f.rotate, f.offset, animate));
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

/** Гизмо в кадре сдвинули: числа и SMD — за ним. */
export function bindFitViewer(w) {
  w.onFitChanged = (f) => { fitWrite(f); fitSave(f); };
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
