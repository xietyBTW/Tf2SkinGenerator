/*
 * Уведомления про приложение целиком: настройки, кэш, инструменты, файлы в
 * папке экспорта
 *
 * Живут в нижней полосе, а не в кадре: кадр есть не на каждой странице, и на
 * звуках «Настройки сохранены» не видел никто. Кадру остаётся то, что про
 * модель и сцену (stage.js).
 */

import { say } from './stage.js';

const root = document.documentElement;
const dock = document.querySelector('.dock');
const note = document.getElementById('docknote');

//: Сколько держать сообщение. Ошибку читают, а не отмечают краем глаза
const KEEP = 5000;

let timer = null;
let pending = null;

/** kind: 'done' | 'error' | 'info' */
export function notifyApp(text, kind = 'done') {
  if (!text) return;
  // Сообщение о сделанном завершает работу: подпись стадии в кадре
  // («Извлечение текстуры…») иначе осталась бы висеть
  say('');
  // Полоса занята сборкой и её итогом - сообщение подождёт, перекрывать
  // прогресс нельзя
  if (root.dataset.dock === 'focus') { pending = [text, kind]; return; }
  show(text, kind);
}

function show(text, kind) {
  note.firstElementChild.textContent = text;
  note.title = text;
  note.dataset.kind = kind;
  // Новое сообщение заново въезжает, а не просто меняет текст
  dock.classList.remove('has-note');
  void note.offsetWidth;
  dock.classList.add('has-note');
  clearTimeout(timer);
  timer = setTimeout(() => dock.classList.remove('has-note'), KEEP);
}

new MutationObserver(() => {
  if (root.dataset.dock === 'focus' || !pending) return;
  const [text, kind] = pending;
  pending = null;
  show(text, kind);
}).observe(root, { attributes: true, attributeFilter: ['data-dock'] });
