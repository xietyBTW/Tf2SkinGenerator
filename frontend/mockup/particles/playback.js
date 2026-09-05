/*
 * Проигрывание и отмена правок.
 *
 * Снимками занимается Python — он же и хранит дерево. Здесь только сочетание
 * клавиш, кнопки проигрывателя и перерисовка тем, что вернулось. Состояние
 * кнопок держим у себя: движок своего не отдаёт.
 */

import * as api from '../api.js';
import { say, withParticles } from '../stage.js';
import { root } from '../layout.js';
import { pSystem } from './state.js';
import { applyStructure } from './actions.js';
import { showParticleMaterials } from './materials.js';

// ── Отмена правок ────────────────────────────────────────────────────────
// Снимками занимается Python: он же и хранит дерево. Здесь только сочетание
// клавиш и перерисовка тем, что вернулось.

export async function historyGo(delta) {
  const res = await api.undoParticles(delta);
  if (res.error) { say(res.error); return; }
  await applyStructure(res);
  if (res.materials) {
    withParticles((w) => w.loadParticleData({ ...res, rootName: pSystem }));
    await showParticleMaterials();
  }
  say(delta < 0 ? 'Правка отменена' : 'Правка возвращена');
  await syncHistory();
}

/** Гасит кнопки отмены, когда откатываться некуда. */
export async function syncHistory() {
  const st = await api.particleHistory();
  document.getElementById('pundo').disabled = !st.undo;
  document.getElementById('predo').disabled = !st.redo;
}

document.getElementById('pundo').addEventListener('click', () => historyGo(-1));
document.getElementById('predo').addEventListener('click', () => historyGo(1));

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
