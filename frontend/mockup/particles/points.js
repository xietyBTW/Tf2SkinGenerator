/*
 * Контрольные точки эффекта.
 *
 * Движок держит их у себя (позиция, углы, пресет движения); отсюда только
 * команды. Номера точек, которые эффекту нужны, считает Python — вычитать их
 * из дерева свойств вручную никто не станет.
 */

import * as api from '../api.js';
import { ask } from '../ask.js';
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
