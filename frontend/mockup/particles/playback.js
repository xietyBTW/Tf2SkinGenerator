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
import { applyStructure, PACTS } from './actions.js';
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

/**
 * Сочетания клавиш раздела: отмена, возврат, копирование и вставка системы.
 *
 * Разбор вынесен в функцию, потому что то же нажатие приходит ИЗ КАДРА:
 * щелчок по эффекту отдаёт фокус iframe, и Ctrl+Z молча не работал, пока не
 * щёлкнешь мимо. Движок передаёт само событие (см. onEditorKey).
 */
export function editorKey(e) {
  if (root.dataset.section !== 'particles' || !(e.ctrlKey || e.metaKey)) return;
  // В поле ввода Ctrl+Z — это отмена ТЕКСТА, её перехватывать нельзя; то же
  // с копированием выделенного.
  const tag = (e.target.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
  // По коду клавиши, а не по символу: в русской раскладке Z — это «я».
  if (e.code === 'KeyZ' && !e.shiftKey) { e.preventDefault(); historyGo(-1); }
  else if (e.code === 'KeyY' || (e.code === 'KeyZ' && e.shiftKey)) {
    e.preventDefault();
    historyGo(1);
  } else if (e.code === 'KeyC' && pSystem) {
    // Выделенный текст копируют как текст — это не про эффект.
    if (String(window.getSelection && window.getSelection()).trim()) return;
    e.preventDefault();
    PACTS.copy();
  } else if (e.code === 'KeyV' && pSystem) {
    e.preventDefault();
    PACTS.paste();
  }
}
document.addEventListener('keydown', editorKey);

document.getElementById('prestart').addEventListener('click',
  () => withParticles((w) => w.restartEffect()));

//: Состояние кнопок-переключателей. Движок своего состояния не отдаёт.
let pPaused = false;
let pLoop = true;

function togglePause() {
  pPaused = !pPaused;
  document.getElementById('ppause').textContent = pPaused ? 'Продолжить' : 'Пауза';
  withParticles((w) => w.setPaused(pPaused));
}
document.getElementById('ppause').addEventListener('click', togglePause);

//: Скорость времени по кругу: 1× → ½ → ¼ → 1×. Быстрые эффекты (крит,
//: вспышка) на глаз не разобрать без замедления.
const SPEEDS = [1, 0.5, 0.25];
let pSpeed = 0;
function cycleSpeed() {
  pSpeed = (pSpeed + 1) % SPEEDS.length;
  const k = SPEEDS[pSpeed];
  const btn = document.getElementById('pspeed');
  btn.textContent = { 1: '1×', 0.5: '½×', 0.25: '¼×' }[k];
  btn.classList.toggle('is-active', k !== 1);
  withParticles((w) => w.setTimeScale && w.setTimeScale(k));
}
document.getElementById('pspeed').addEventListener('click', cycleSpeed);

// Горячие клавиши кадра: пробел — пауза, R — заново, S — скорость. Только
// когда фокус не в поле ввода: там пробел — это пробел.
document.addEventListener('keydown', (e) => {
  if (root.dataset.section !== 'particles' || e.ctrlKey || e.altKey) return;
  const tag = (e.target.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select'
      || e.target.isContentEditable) return;
  // По коду клавиши, а не по символу: в русской раскладке R — это «к».
  if (e.code === 'Space') { e.preventDefault(); togglePause(); }
  else if (e.code === 'KeyR') withParticles((w) => w.restartEffect());
  else if (e.code === 'KeyS') cycleSpeed();
});

//: Фон кадра: тёмный, как карта в тени, как карта на свету. Полупрозрачные
//: слои (дымка воды) видны только на светлом — на чёрном это чёрный ящик.
const BACKGROUNDS = [0x1a1a1a, 0x5c6a72, 0xb8c2c8];
let pBg = 0;
document.getElementById('pbg').addEventListener('click', () => {
  pBg = (pBg + 1) % BACKGROUNDS.length;
  withParticles((w) => w.setBackground(BACKGROUNDS[pBg]));
});

document.getElementById('ploop').addEventListener('click', (e) => {
  pLoop = !pLoop;
  e.target.classList.toggle('is-off', !pLoop);
  withParticles((w) => w.setLoop(pLoop));
});
