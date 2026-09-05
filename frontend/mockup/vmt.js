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
import { ask } from './ask.js';
import { contextMenu } from './menu.js';
import { currentMaterial } from './album.js';

// ── Редактор VMT ────────────────────────────────────────────────────────
// Открывается сохранённая правка, иначе — оригинал из игры. Проверку
// синтаксиса делает Python при сохранении: сломанный VMT в игре даёт
// невидимый материал, и ловить это лучше до сборки.

const vmtDlg = document.getElementById('vmtdlg');
const vmtText = document.getElementById('vmt-text');
const vmtHl = document.getElementById('vmt-hl');
const vmtStatus = document.getElementById('vmt-status');
//: `custom` — стоит ли своя правка: от неё зависит и строка состояния, и
//: кнопка «Как в игре».
let vmtState = { material: '', original: '', custom: false };

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

vmtText.addEventListener('input', () => { paintVmt(); markVmtState(); });
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

/**
 * Меню «Вставить»: параметр, прокси или целый шаблон.
 *
 * Набор общий с окном приложения (`src/data/vmt_snippets.py`) — держать
 * второй список в JS значило бы его разъезд. Пункт-ШАБЛОН заменяет весь
 * документ, поэтому о нём спрашивают отдельно: человек мог уже что-то
 * написать.
 */
async function insertMenu(e) {
  const data = await api.vmtSnippets();
  const items = [];
  for (const group of data.groups || []) {
    if (items.length) items.push(null);          // разделитель между группами
    for (const it of group.items) {
      items.push({ label: it.label, value: it });
    }
  }
  const picked = await contextMenu(e, items);
  if (!picked) return;

  if (picked.template) {
    const body = (data.templates || {})[picked.label] || '';
    if (!body) return;
    if (vmtText.value.trim()) {
      const go = await ask({ title: 'Применить шаблон',
                             text: 'Заменить весь VMT этим шаблоном?',
                             ok: 'Заменить' });
      if (!go) return;
    }
    vmtText.value = body;
  } else {
    // Под курсор — но только если курсор ставил человек. Окно открывается с
    // кареткой в нуле, и вставка «под курсор» уехала бы ПЕРЕД шейдером:
    // получался бы битый VMT с первого же нажатия. Поэтому по умолчанию
    // кладём внутрь блока — сразу за открывающей скобкой.
    const at = vmtText.selectionStart || afterBrace(vmtText.value);
    // Начинаем с перевода строки: вставка идёт и сразу за «{», и в конец
    // строки, где поставил каретку человек — в обоих случаях нужен свой ряд.
    const snippet = '\n\t' + picked.snippet;
    vmtText.value = vmtText.value.slice(0, at) + snippet + vmtText.value.slice(at);
    vmtText.selectionStart = vmtText.selectionEnd = at + snippet.length;
  }
  paintVmt();
  vmtText.focus();
  markVmtState();
}

/** Позиция сразу после открывающей скобки блока; её нет — конец файла. */
function afterBrace(text) {
  const at = text.indexOf('{');
  return at < 0 ? text.length : at + 1;
}

/**
 * Строка состояния: что сейчас в окне — оригинал игры, сохранённая правка или
 * несохранённые изменения. Раньше об этом можно было судить только по памяти.
 */
function markVmtState() {
  const changed = vmtText.value !== vmtState.original;
  if (changed) { vmtSay('● Есть несохранённые изменения', 'warn'); return; }
  vmtSay(vmtState.custom ? '✓ Используется свой VMT'
                         : 'Показывается оригинал из игры');
}

export async function openVmtEditor() {
  const [res, params] = await Promise.all([api.openVmt(currentMaterial()),
                                           api.vmtParams()]);
  if (res.error) { say(res.error); return; }
  vmtDocs = Object.fromEntries(params.map((p) => [p.param.toLowerCase(), p.doc]));

  vmtState = { material: res.material, original: res.original,
               custom: Boolean(res.edited) };
  document.getElementById('vmt-mat').textContent = res.material;
  vmtText.value = res.content;
  paintVmt();
  markVmtState();
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
  // Сохранённое становится новым «оригиналом» окна: иначе маркер «есть
  // несохранённые» висел бы сразу после сохранения.
  vmtState.original = res.content;
  vmtState.custom = true;
  document.getElementById('vmt-reset').hidden = false;
  vmtSay('Сохранено', 'good');
});

document.getElementById('vmt-reset').addEventListener('click', async () => {
  const res = await api.resetVmt(vmtState.material);
  if (res.error) { vmtSay(res.error, 'bad'); return; }
  vmtText.value = vmtState.original;
  paintVmt();
  vmtState.custom = false;
  document.getElementById('vmt-reset').hidden = true;
  vmtSay('Правка удалена, показан игровой оригинал');
});

document.getElementById('vmt-insert').addEventListener('click', insertMenu);
document.getElementById('vmt-close').addEventListener('click', () => vmtDlg.close());

// Ctrl+S — привычка любого, кто правит текст. Браузерное «сохранить страницу»
// здесь ни к чему.
vmtText.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
    e.preventDefault();
    document.getElementById('vmt-save').click();
  }
});
