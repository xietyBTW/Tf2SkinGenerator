/*
 * Сборка мода.
 *
 * Что собирать, знает Python: он смотрит, какие текстуры человек положил на
 * какие материалы. Отсюда уходят только параметры формата.
 */

import * as api from './api.js';
import { ask } from './ask.js';
import { chooseFile, plural } from './util.js';
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
/** Имя галки для сборки: своё, если задано, иначе подпись. */
export function checkName(label) {
  const span = label.querySelector('span');
  return (span.dataset.name || span.textContent).trim();
}

export function buildParams({ live = false } = {}) {
  if (!live && texEdit !== null) return { ...texEdit.global };

  // Колонку ищем по data-col, а имя галки берём из data-name: подписи
  // переводятся, а в сборку уходит имя — искать по надписи нельзя.
  const col = (key) => document.querySelector(`.build__col[data-col="${key}"]`);
  const checked = (key) => [...col(key).querySelectorAll('.check')]
    .filter((l) => l.querySelector('input').checked)
    .map((l) => checkName(l));

  const res = [...document.querySelectorAll('input[name="res"]')]
    .findIndex((r) => r.checked);
  return {
    size: [256, 512, 1024, 2048][res < 0 ? 1 : res],
    format: document.getElementById('fmt').value,
    filename: document.getElementById('out').value,
    flags: checked('flags'),
    options: Object.fromEntries(checked('options').map((n) => [n, true])),
    // Краски шапки — не флаг VTF: они решают, как красится материал, поэтому
    // едут отдельным полем, а не в общем наборе опций.
    hat_paints: document.getElementById('hat-paints').checked,
    // Классы мультиклассовой шапки: пусто — значит все.
    hat_classes: hatClasses(),
    // Сборка подписывает шаги и пишет комментарии в VMT на языке настроек.
    lang: api.lang(),
  };
}

/**
 * Сводка в нижней строке: что именно соберётся.
 *
 * Три поля из четырёх — эхо выбранного, и сами по себе они мало что дают. Ради
 * четвёртого всё и держится: ВЕС готового VTF глазами не увидеть, а он меняет
 * решение — 2048 DXT5 это 5.3 МБ против 1.3 МБ у 1024.
 */
export async function updateDockSummary() {
  const el = document.getElementById('docksum');
  const p = buildParams({ live: true });
  const parts = [p.size + ' × ' + p.size, p.format];
  try {
    const est = await api.vtfEstimate(p.size, p.format, p.flags);
    parts.push('≈ ' + est.text);
  } catch {
    // Оценка — украшение сводки, а не её смысл: без неё показываем остальное.
  }
  if (p.filename) parts.push(p.filename);
  el.textContent = parts.join(' · ');
}

// Любая правка параметров меняет то, что соберётся.
document.querySelector('.build__grid').addEventListener('change', updateDockSummary);
document.getElementById('out').addEventListener('input', updateDockSummary);
updateDockSummary();

const buildBtn = document.getElementById('buildvpk');

// Отмена: воркер проверяет её между шагами сам, поэтому кнопка только
// просит остановиться — о конце скажет обычное build_done.
document.getElementById('buildstop').addEventListener('click', async () => {
  setStatus('Останавливаю сборку…', true);
  await api.cancelBuild();
});
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
export async function askForTexture(material, remaining = 0) {
  // «И так для остальных» — ГАЛКА к выбору, а не два лишних пункта: это то же
  // действие, только шире. И появляется она, только когда остальные есть:
  // раньше её предлагали даже на последнем материале, обещая распространить
  // ответ на пустоту.
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
    ],
    check: remaining > 0
      ? 'И так для остальных — ещё ' + remaining + ' '
        + plural(remaining, 'материал', 'материала', 'материалов')
      : '',
    ok: 'Ответить',
  });

  // Окно закрыли — сборка ждать бесконечно не должна: отвечаем безопасным
  // вариантом (игровой оригинал ничего не портит).
  const picked = (answer && answer.value !== undefined) ? answer : { value: answer };
  const choice = picked.value || 'game';
  // «Для остальных» к выбору файла не применяем: своя картинка относится к
  // ЭТОМУ материалу, раздавать её всем никто не просил.
  const forAll = Boolean(picked.checked) && choice !== 'file';

  if (choice === 'file') {
    const file = await chooseFile('image/*');
    if (!file) { await api.answerTexture('game'); return; }
    await api.answerTexture('file', await api.upload(file));
    return;
  }
  await api.answerTexture(choice, '', forAll);
}
