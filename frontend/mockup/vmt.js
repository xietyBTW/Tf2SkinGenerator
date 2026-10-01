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
import { pickEffect, closeEffects } from './vmt-effects.js';
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

//: {$параметр: описание} — для подсказок при наведении.
let vmtDocs = {};
//: Тот же справочник по группам — для списка «Справочник».
let vmtRef = [];


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
        ? `<span class="vmt-par" data-doc="${escapeHtml(doc)}">${chunk}</span>`
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

/*
 * Наведение на $параметр объясняет, что он делает.
 *
 * Мышь ловит ПОЛЕ: оно лежит поверх зеркала, и обработчики на самом зеркале
 * не получали ничего — подсказки молча пропали, когда редактор стал
 * прозрачным полем над подсветкой. Поэтому поле спрашивает, что под курсором
 * в зеркале (elementsFromPoint видит и то, что лежит ниже), и показывает
 * подсказку рядом с мышью, а не где-то в строке состояния.
 */
const vmtTip = document.getElementById('vmt-tip');
let tipFor = null;

function paramAt(x, y) {
  return document.elementsFromPoint(x, y)
    .find((el) => el.classList && el.classList.contains('vmt-par')) || null;
}

function hideTip() {
  tipFor = null;
  vmtTip.hidden = true;
}

vmtText.addEventListener('mousemove', (e) => {
  const par = paramAt(e.clientX, e.clientY);
  if (!par || !par.dataset.doc) { hideTip(); return; }
  if (par !== tipFor) {
    tipFor = par;
    const name = document.createElement('b');
    name.className = 'mono';
    name.textContent = par.textContent.replace(/"/g, '');
    const doc = document.createElement('span');
    doc.textContent = par.dataset.doc;
    vmtTip.replaceChildren(name, doc);
    vmtTip.hidden = false;
  }
  // У курсора, но не за краем окна: у правого и нижнего края — с другой стороны.
  const box = vmtTip.getBoundingClientRect();
  const x = e.clientX + 16 + box.width > innerWidth - 8 ? e.clientX - 16 - box.width : e.clientX + 16;
  const y = e.clientY + 20 + box.height > innerHeight - 8 ? e.clientY - 12 - box.height : e.clientY + 20;
  vmtTip.style.left = Math.max(8, x) + 'px';
  vmtTip.style.top = Math.max(8, y) + 'px';
});
vmtText.addEventListener('mouseleave', hideTip);
// Печатают — подсказка мешает видеть строку.
vmtText.addEventListener('keydown', hideTip);

/**
 * «Готовые эффекты»: свечение, блики, прозрачность, анимация, особые
 * материалы, шаблоны.
 *
 * Набор общий с данными Python (`src/data/vmt_snippets.py`) — держать второй
 * список в JS значило бы его разъезд. Выбор — в панели категорий
 * (vmt-effects.js). Пункт-ШАБЛОН заменяет весь документ, поэтому о нём
 * спрашивают; эффект с формой приходит готовым текстом — о замене он
 * предупредил в самой форме.
 */
async function insertMenu(e) {
  if (closeEffects()) return;             // повторный щелчок — закрыть
  const anchor = e.currentTarget;         // после await его у события уже нет
  const data = await api.vmtSnippets();
  const res = await pickEffect(anchor, data, () => vmtText.value, vmtState.game);
  if (!res) return;
  if (res.text !== undefined) {
    vmtText.value = res.text;
    paintVmt();
    vmtText.focus();
    vmtText.setSelectionRange(0, 0);
    vmtText.scrollTop = 0;
    markVmtState();
    return;
  }
  const picked = res.item;

  if (picked.template) {
    const body = (data.templates || {})[picked.key] || '';
    if (!body) return;
    if (vmtText.value.trim()) {
      const go = await ask({ title: 'Заменить весь материал',
                             text: 'Текущий VMT заменится этим шаблоном.',
                             ok: 'Заменить' });
      if (!go) return;
    }
    vmtText.value = body;
  } else if (picked.merge) {
    // Слияние (австралий): у ключей, что уже есть, меняется значение — в
    // VMT последний одноимённый ключ перекрывает первые, и вставка в начало
    // блока ничего не дала бы; мешающие ключи гасятся комментарием.
    vmtText.value = mergeSnippet(vmtText.value, picked.snippet, picked.remove || []);
  } else {
    insertSnippet(picked.snippet);
  }
  paintVmt();
  vmtText.focus();
  markVmtState();
}

/**
 * Вставляет сниппет в документ.
 *
 * Параметры — под курсор, если его ставил человек. Окно открывается с
 * кареткой в нуле, и вставка «под курсор» уехала бы ПЕРЕД шейдером: битый VMT
 * с первого нажатия. Поэтому по умолчанию — сразу за открывающей скобкой.
 *
 * Блок "Proxies" вливается в уже существующий: материал читает только первый
 * "Proxies" (KeyValues::FindKey), а у почти каждого VMT из игры он уже есть —
 * второй блок молча не работал бы, и «краска» или «анимация» не включались.
 * В КОНЕЦ блока: прокси выполняются по порядку, и в оружии TF2 уже стоит
 * Equals $glowcolor → $color2 — встав раньше, краска была бы им затёрта.
 */
function insertSnippet(snippet) {
  const { plain, proxies } = splitProxies(snippet);
  let docProxies = proxies ? findProxiesBrace(vmtText.value) : -1;
  // Блок не закрыт (человек его как раз пишет) — вливать некуда.
  if (docProxies >= 0 && matchingBrace(vmtText.value, docProxies) < 0) docProxies = -1;
  // Своего блока у документа нет — сниппет встаёт целиком, со своим.
  const body = proxies && docProxies < 0 ? snippet : plain;
  let text = vmtText.value;
  let caret = null;
  if (body.trim()) {
    const at = insertPoint(text);
    const block = '\n\t' + body.trim();
    text = text.slice(0, at) + block + text.slice(at);
    caret = at + block.length;
  }
  if (proxies && docProxies >= 0) {
    // Позиция блока — по уже изменённому тексту: вставка выше могла её сдвинуть.
    const close = matchingBrace(text, findProxiesBrace(text));
    let end = close;
    while (end > 0 && /\s/.test(text[end - 1])) end--;      // за последним прокси
    text = text.slice(0, end) + proxies.trimEnd() + text.slice(end);
  }
  vmtText.value = text;
  if (caret !== null) vmtText.selectionStart = vmtText.selectionEnd = caret;
}

/** Делит сниппет на обычные строки и содержимое его блока "Proxies". */
function splitProxies(snippet) {
  const at = snippet.search(/"?proxies"?\s*\{/i);
  if (at < 0) return { plain: snippet, proxies: '' };
  const open = snippet.indexOf('{', at);
  const close = matchingBrace(snippet, open);
  if (close < 0) return { plain: snippet, proxies: '' };
  return { plain: snippet.slice(0, at), proxies: snippet.slice(open + 1, close) };
}

/** Позиция «{» блока "Proxies" документа; нет блока — -1. Строки-комментарии
 *  не в счёт: `//"Proxies"` начинается не с кавычки и не с имени. */
function findProxiesBrace(text) {
  // Между именем и скобкой бывают пустые строки и комментарии: в VMT из игры
  // встречается "Proxies", пустая строка, потом «{».
  const m = /^[ \t]*"?proxies"?(?:\s|\/\/[^\n]*)*\{/im.exec(text);
  return m ? m.index + m[0].length - 1 : -1;
}

/** Парная «}» к «{» на `open`; скобки в строках и комментариях не в счёт. */
function matchingBrace(text, open) {
  let depth = 0;
  for (let i = open; i < text.length; i++) {
    const c = text[i];
    if (c === '"') {
      const end = text.indexOf('"', i + 1);
      if (end < 0) return -1;
      i = end;
    } else if (c === '/' && text[i + 1] === '/') {
      const end = text.indexOf('\n', i);
      if (end < 0) return -1;
      i = end;
    } else if (c === '{') depth++;
    else if (c === '}' && --depth === 0) return i;
  }
  return -1;
}

/**
 * Куда вставлять: туда, где стоит каретка, если её ставил человек. После
 * записи в поле браузер уводит каретку в конец текста — за корневую «}», и
 * вставка туда дала бы битый VMT. Поэтому каретка в нуле или за последней
 * «}» считается «не выбрана»: вставка идёт сразу за открывающей скобкой.
 */
function insertPoint(text) {
  const at = vmtText.selectionStart;
  return at > 0 && at <= text.lastIndexOf('}') ? at : afterBrace(text);
}

//: Строка «"$ключ" значение» в начале строки (с любыми отступами, кавычки
//: у ключа не обязательны). `$envmap` не ловит `$envmaptint`: после ключа
//: обязателен пробел либо закрывающая кавычка.
const keyLine = (key) => new RegExp(
  '^([ \t]*)"?' + key.replace(/[$]/g, '[$]') + '"?[ \t]+[^\n]*$', 'im');

/**
 * Вливает сниппет в документ: одноимённые ключи заменяются на месте,
 * остальные встают за открывающей скобкой, `remove` комментируются.
 */
function mergeSnippet(text, snippet, remove) {
  let out = text;
  for (const key of remove) {
    out = out.replace(keyLine(key), (line, indent) => indent + '// ' + line.trim());
  }
  const fresh = [];
  for (const raw of snippet.split('\n')) {
    const line = raw.trim();
    const m = line.match(/^"?(\$[a-z0-9_]+)"?/i);
    if (!m) continue;
    const re = keyLine(m[1]);
    if (re.test(out)) out = out.replace(re, (_, indent) => indent + line);
    else fresh.push(line);
  }
  if (!fresh.length) return out;
  const at = afterBrace(out);
  const block = '\n\t' + fresh.join('\n\t');
  return out.slice(0, at) + block + out.slice(at);
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
  const [res, groups] = await Promise.all([api.openVmt(currentMaterial()),
                                           api.vmtParams()]);
  if (res.error) { say(res.error); return; }
  vmtRef = groups;
  vmtDocs = Object.fromEntries(groups.flatMap((g) => g.params)
    .map((p) => [p.param.toLowerCase(), p.doc]));
  renderRef();

  // `game` — игровой оригинал на всё время окна: `original` после сохранения
  // становится сохранённым текстом, а эффекту нужна родная текстура.
  vmtState = { material: res.material, original: res.original,
               custom: Boolean(res.edited), game: res.original };
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
// Окно закрыли с открытой панелью — она не должна пережить его.
vmtDlg.addEventListener('close', closeEffects);

// ── Справочник ──────────────────────────────────────────────────────────
// Все известные параметры по группам: узнать, что вообще бывает, и добавить
// нужный, не выходя из окна. Поиск — и по имени, и по описанию: «блики»
// находит $phong, хотя в имени этого слова нет.
const refPanel = document.getElementById('vmt-ref');
const refFind = document.getElementById('vmt-find');

function renderRef() {
  const box = document.getElementById('vmt-refs');
  const q = refFind.value.trim().toLowerCase();
  box.replaceChildren();
  for (const group of vmtRef) {
    const rows = group.params.filter((p) => !q
      || p.param.includes(q) || p.doc.toLowerCase().includes(q));
    if (!rows.length) continue;
    const head = document.createElement('p');
    head.className = 'label vmt__refgroup';
    head.textContent = group.group;
    box.append(head);
    for (const p of rows) {
      const row = document.createElement('button');
      row.type = 'button';
      row.className = 'vmt__refrow';
      const name = document.createElement('span');
      name.className = 'mono vmt__refname';
      name.textContent = p.param;
      const doc = document.createElement('span');
      doc.className = 'vmt__refdoc';
      doc.textContent = p.doc;
      row.append(name, doc);
      row.addEventListener('click', () => useParam(p.param));
      box.append(row);
    }
  }
  if (!box.children.length) {
    const none = document.createElement('p');
    none.className = 'vmt__refdoc';
    none.textContent = 'Ничего не нашлось';
    box.append(none);
  }
}

/**
 * Щелчок по параметру справочника. Уже есть в материале — ставим курсор на
 * его значение: второй такой же ключ только запутал бы. Нет — добавляем
 * строку с пустым значением и курсором внутри кавычек.
 */
function useParam(param) {
  const text = vmtText.value;
  const found = keyLine(param).exec(text);
  let caret;
  let until = null;
  if (found) {
    // Выделяем значение: начатый ввод его заменит. Значение бывает и без
    // кавычек ("$phong" 1) — тогда последняя кавычка строки принадлежит
    // ключу, и каретка встала бы внутрь имени.
    const m = /^([ \t]*"?\$\w+"?[ \t]+)(.*?)[ \t]*(?:\/\/.*)?$/.exec(found[0]);
    const start = found.index + (m ? m[1].length : found[0].length);
    let value = m ? m[2] : '';
    let from = start;
    if (value.startsWith('"')) {
      const close = value.indexOf('"', 1);
      from = start + 1;
      value = value.slice(1, close > 0 ? close : value.length);
    }
    caret = from;
    until = from + value.length;
    vmtSay('Уже есть в материале — курсор на нём');
  } else {
    const at = afterBrace(text);
    const block = `\n\t"${param}" ""`;
    vmtText.value = text.slice(0, at) + block + text.slice(at);
    caret = at + block.length - 1;
    paintVmt();
    markVmtState();
  }
  vmtText.focus();
  vmtText.setSelectionRange(caret, until ?? caret);
  // Прокрутить к строке: сама установка каретки поле не двигает.
  const line = vmtText.value.slice(0, caret).split('\n').length - 1;
  const lh = parseFloat(getComputedStyle(vmtText).lineHeight) || 19;
  vmtText.scrollTop = Math.max(0, line * lh - vmtText.clientHeight / 3);
}

refFind.addEventListener('input', renderRef);
document.getElementById('vmt-help').addEventListener('click', (e) => {
  refPanel.hidden = !refPanel.hidden;
  vmtDlg.classList.toggle('has-ref', !refPanel.hidden);
  e.currentTarget.classList.toggle('is-active', !refPanel.hidden);
  if (!refPanel.hidden) refFind.focus();
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
