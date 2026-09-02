/*
 * Сборка мода.
 *
 * Что собирать, знает Python: он смотрит, какие текстуры человек положил на
 * какие материалы. Отсюда уходят только параметры формата.
 */

import * as api from './api.js';
import { ask } from './ask.js';
import { chooseFile } from './util.js';
import { root, setStatus } from './layout.js';
import { buildParticles } from './particles/index.js';
import { texEdit } from './controls.js';
import { hatClasses } from './preview.js';

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
export function buildParams({ live = false } = {}) {
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
export async function askForTexture(material) {
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
