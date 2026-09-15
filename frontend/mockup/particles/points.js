/*
 * Контрольные точки эффекта.
 *
 * Движок держит их у себя (позиция, углы, пресет движения); отсюда только
 * команды. Номера точек, которые эффекту нужны, считает Python — вычитать их
 * из дерева свойств вручную никто не станет.
 */

import * as api from '../api.js';
import { pickCpModel } from './cpmodel.js';
import { t } from '../i18n.js';
import { say, withParticles } from '../stage.js';
import { pSystem } from './state.js';

// ── Контрольные точки ────────────────────────────────────────────────────
// Движок держит их у себя (позиция, углы, пресет движения); отсюда только
// команды. Номера точек, которые эффекту нужны, считает Python — вычитать их
// из дерева свойств вручную никто не станет.

export const cpBox = document.getElementById('cp');
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
  // Точка крепления — тоже часть состояния точки: у оружия точка 0 висит на
  // unusual_0, точка 1 — на unusual_1, и список должен показывать своё.
  cpEl('cp-attach').value = st.attach ?? '';
}

/** Шлёт движку положение, углы и пресет движения текущей точки. */
function cpPush() {
  // Точка, сдвинутая руками, уже не на attachment.
  cpEl('cp-attach').value = '';
  cpPushIndex(cpIndex, { values: CP_FIELDS.map(cpNum),
                         motion: cpEl('cp-motion').value });
}

/** Запоминает состояние точки и отдаёт его движку. */
function cpPushIndex(index, st) {
  const [x, y, z, p, yaw, r, amp, period] = st.values;
  cpState.set(index, st);
  withParticles((w) => {
    w.setControlPoint(index, x, y, z);
    // Нулевые углы — это тоже углы: сбрасывать ориентацию надо явно, иначе
    // точка осталась бы повёрнутой от прошлой правки.
    if (p || yaw || r) w.setControlPointOrientation(index, p, yaw, r);
    else w.clearControlPointOrientation(index);
    w.setControlPointMotion(index, st.motion, amp, period);
  });
}

/** Рисует ряд номеров точек; нужные эффекту помечены. */
export async function cpFillIndexes() {
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
  cpPush();
});

document.getElementById('pcpbtn').addEventListener('click', (e) => {
  cpBox.hidden = !cpBox.hidden;
  e.target.classList.toggle('is-off', cpBox.hidden);
  // Ручка в кадре нужна только пока точку правят.
  withParticles((w) => w.setGizmoVisible(!cpBox.hidden));
  if (!cpBox.hidden) cpFillIndexes();
});

//: Подпись модели, которую сейчас разбирает Crowbar: сцена придёт событием.
let cpPendingLabel = '';

cpEl('cp-model').addEventListener('click', async () => {
  const pick = await pickCpModel();
  if (!pick) return;
  if (pick.mode === 'cache') {
    // Уже разобрано: меш собирается сразу, без Crowbar.
    say('Сборка меша модели…');
    const scene = await api.particleModelScene(pick.qc);
    if (scene.error) { say(scene.error); return; }
    applyCpModelScene(scene, pick.label);
    return;
  }
  cpPendingLabel = pick.label;
  say('Разбор модели…');
  const res = await api.particleModelLoad(pick.mode, pick.key);
  if (res.error) { say(res.error); cpPendingLabel = ''; }
});

/** Сцена модели приехала (событие cp_model или ответ по кэшу). */
export function showCpModel(ev) {
  if (ev.error) { say(ev.error); cpPendingLabel = ''; return; }
  applyCpModelScene(ev.scene, cpPendingLabel);
  cpPendingLabel = '';
}

function applyCpModelScene(scene, label) {
  // Корневая кость — первой: к ней игра цепляет анюжуал косметики
  // (attach_to_rootbone), и у шапки это голова, а не ноги.
  const root = scene.root ? [{ ...scene.root, name: scene.root.name + ' (' + t('корень') + ')' }] : [];
  cpAttachments = [...root, ...(scene.attachments || [])];
  cpEl('cp-model-name').textContent = label || '';
  // Номера точек крепления прошлой модели больше ничего не значат.
  for (const st of cpState.values()) delete st.attach;

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
  // Точки сразу туда, куда вешает игра (econ_entity.cpp,
  // UpdateSingleParticleSystem): точка 0 — на attachment «unusual» (у шапок)
  // или «unusual_0» (у оружия), без них — на корневую кость (attach_to_rootbone);
  // точки 1..5 — на «unusual_1».. «unusual_5» (control_point_N в items_game).
  // Иначе эффект шапки стоял в нуле сцены, а сама шапка — на высоте головы,
  // и «как прицепить» было неоткуда узнать. Корень у шапки с полным
  // скелетом — таз, не голова: так и в игре.
  const byName = new Map(cpAttachments.map((a, i) => [a.name.toLowerCase(), i]));
  const zero = byName.get('unusual') ?? byName.get('unusual_0') ?? (root.length ? 0 : -1);
  if (zero >= 0) {
    cpPlace(0, zero);
    for (let n = 1; n <= 5; n++) {
      const i = byName.get('unusual_' + n);
      if (i !== undefined) cpPlace(n, i);
    }
    cpLoad();
  }
  say('');
}

/** Ставит точку ровно на attachment номер `at`: в игре эффект висит именно там. */
function cpPlace(index, at) {
  const a = cpAttachments[at];
  const st = cpState.get(index) || { values: [0, 0, 0, 0, 0, 0, 24, 2], motion: 'none' };
  const r1 = (v) => Math.round(v * 10) / 10;
  cpPushIndex(index, { values: [...a.pos.map(r1), ...a.angles.map(r1),
                                st.values[6], st.values[7]],
                       motion: st.motion, attach: String(at) });
}

cpEl('cp-attach').addEventListener('change', () => {
  const at = Number(cpEl('cp-attach').value);
  if (!cpAttachments[at]) return;
  cpPlace(cpIndex, at);
  cpLoad();
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
