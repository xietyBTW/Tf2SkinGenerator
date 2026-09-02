/*
 * Редактор VMT: текст материала с подсветкой и подсказками по параметрам.
 *
 * Открывается сохранённая правка, иначе — оригинал из игры. Синтаксис
 * проверяет Python при сохранении: сломанный VMT в игре даёт невидимый
 * материал, и ловить это лучше до сборки.
 */

import * as api from './api.js';
import { escapeHtml } from './util.js';
import { say } from './stage.js';
import { currentMaterial } from './album.js';

// ── Редактор VMT ────────────────────────────────────────────────────────
// Открывается сохранённая правка, иначе — оригинал из игры. Проверку
// синтаксиса делает Python при сохранении: сломанный VMT в игре даёт
// невидимый материал, и ловить это лучше до сборки.

const vmtDlg = document.getElementById('vmtdlg');
const vmtText = document.getElementById('vmt-text');
const vmtHl = document.getElementById('vmt-hl');
const vmtStatus = document.getElementById('vmt-status');
let vmtState = { material: '', original: '' };

//: {$параметр: описание} — тот же словарь, что знает редактор в приложении.
let vmtDocs = {};


/**
 * Перерисовывает зеркало под полем.
 *
 * Подсветка тут вторична: главное — что $параметр становится отдельным
 * элементом, и на него можно навести мышь. Описание берётся из Python, поэтому
 * подсказка не может разойтись с тем, что редактор действительно знает.
 */
function paintVmt() {
  const text = vmtText.value;
  let html = '';
  // Один проход: комментарий до конца строки, строка в кавычках, $параметр.
  const re = /(\/\/[^\n]*)|("(?:[^"\\\n]|\\.)*")|(\$\w+)/g;
  let last = 0;
  for (let m = re.exec(text); m; m = re.exec(text)) {
    html += escapeHtml(text.slice(last, m.index));
    const chunk = escapeHtml(m[0]);
    // Параметр в VMT почти всегда В КАВЫЧКАХ ("$basetexture" "models/..."),
    // поэтому кавычки с $-именем внутри — это параметр, а не строка значения.
    const quotedParam = m[2] && m[2].match(/^"(\$\w+)"$/);
    const param = m[3] || (quotedParam && quotedParam[1]);
    if (m[1]) html += `<span class="vmt-com">${chunk}</span>`;
    else if (param) {
      const doc = vmtDocs[param.toLowerCase()];
      html += doc
        ? `<span class="vmt-par" title="${escapeHtml(param + ' — ' + doc)}">${chunk}</span>`
        : `<span class="vmt-par">${chunk}</span>`;
    } else html += `<span class="vmt-str">${chunk}</span>`;
    last = m.index + m[0].length;
  }
  // <pre> съедает последний перевод строки, а поле его сохраняет: без добавки
  // зеркало короче на строку, и в самом низу подсветка отстаёт от текста.
  vmtHl.innerHTML = html + escapeHtml(text.slice(last)) + '\n';
  vmtHl.scrollTop = vmtText.scrollTop;
  vmtHl.scrollLeft = vmtText.scrollLeft;
}

vmtText.addEventListener('input', paintVmt);
// Зеркало прокручивается вместе с полем, иначе подсветка съезжает.
vmtText.addEventListener('scroll', () => {
  vmtHl.scrollTop = vmtText.scrollTop;
  vmtHl.scrollLeft = vmtText.scrollLeft;
});

//: Что показывает строка состояния, когда мышь не на параметре.
let vmtBaseStatus = { text: '', kind: '' };

function vmtSay(text, kind = '') {
  vmtBaseStatus = { text, kind };
  vmtStatus.textContent = text;
  vmtStatus.className = 'label vmt__status' + (kind ? ' is-' + kind : '');
}

// Наведение на $параметр объясняет, что он делает. Строкой состояния, а не
// системной подсказкой: она появляется сразу и читается там же, где остальные
// сообщения редактора. Атрибут title при этом остаётся — для тех, кто ждёт
// привычного всплывания.
vmtHl.addEventListener('mouseover', (e) => {
  const par = e.target.closest('.vmt-par');
  if (!par || !par.title) return;
  vmtStatus.textContent = par.title;
  vmtStatus.className = 'label vmt__status is-good';
});

vmtHl.addEventListener('mouseout', (e) => {
  if (!e.target.closest('.vmt-par')) return;
  vmtStatus.textContent = vmtBaseStatus.text;
  vmtStatus.className = 'label vmt__status'
    + (vmtBaseStatus.kind ? ' is-' + vmtBaseStatus.kind : '');
});

export async function openVmtEditor() {
  const [res, params] = await Promise.all([api.openVmt(currentMaterial()),
                                           api.vmtParams()]);
  if (res.error) { say(res.error); return; }
  vmtDocs = Object.fromEntries(params.map((p) => [p.param.toLowerCase(), p.doc]));

  vmtState = { material: res.material, original: res.original };
  document.getElementById('vmt-mat').textContent = res.material;
  vmtText.value = res.content;
  paintVmt();
  vmtSay(res.edited ? 'Своя правка активна' : 'Показан игровой оригинал',
         res.edited ? 'good' : '');
  document.getElementById('vmt-reset').hidden = !res.edited;
  vmtDlg.showModal();
  // Прокрутка сбрасывается ТОЛЬКО после показа: у скрытого поля нет раскладки,
  // и присвоение до showModal терялось — файл открывался на хвосте.
  vmtText.scrollTop = 0;
  vmtText.setSelectionRange(0, 0);
}

document.getElementById('vmt-save').addEventListener('click', async () => {
  // Оригинал отправляем вместе с правкой: Python фиксирует его бэкапом один
  // раз, иначе «как в игре» после второй правки вернуло бы первую.
  const res = await api.saveVmt(vmtState.material, vmtText.value, vmtState.original);
  if (res.error) { vmtSay(res.error, 'bad'); return; }
  vmtText.value = res.content;          // с дописанным ватермарком
  paintVmt();
  document.getElementById('vmt-reset').hidden = false;
  vmtSay('Сохранено', 'good');
});

document.getElementById('vmt-reset').addEventListener('click', async () => {
  const res = await api.resetVmt(vmtState.material);
  if (res.error) { vmtSay(res.error, 'bad'); return; }
  vmtText.value = vmtState.original;
  paintVmt();
  document.getElementById('vmt-reset').hidden = true;
  vmtSay('Правка удалена, показан игровой оригинал');
});

document.getElementById('vmt-close').addEventListener('click', () => vmtDlg.close());

// Ctrl+S — привычка любого, кто правит текст. Браузерное «сохранить страницу»
// здесь ни к чему.
vmtText.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
    e.preventDefault();
    document.getElementById('vmt-save').click();
  }
});
