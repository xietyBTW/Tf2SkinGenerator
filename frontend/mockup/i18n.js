/*
 * Язык интерфейса: подписи самой страницы.
 *
 * Имена предметов приходят из игры уже на нужном языке (их отдаёт Python), а
 * текст страницы — кнопки, заголовки, подсказки, сообщения — написан
 * по-русски прямо в разметке и в коде. Переписывать пять сотен мест на ключи
 * значило бы тронуть каждый файл фронта; вместо этого перевод делается на
 * ГРАНИЦЕ ПОКАЗА, а ключом служит сам русский текст (см. `strings.js`).
 *
 * Точки входа две, и других не нужно:
 *   • обход документа — разметка и всё, что уже на экране;
 *   • наблюдатель за добавленными узлами — карточки, диалоги, сообщения; они
 *     строятся кодом уже после старта.
 * Строку, которая в DOM не попадает, можно перевести вручную через `t()`.
 * Язык живёт до перезагрузки страницы: смена языка в настройках поднимает
 * её заново (settings.js), поэтому переводить экран обратно не приходится.
 *
 * Незнакомая строка остаётся русской. Это не поломка, а поведение: пропуск
 * виден на экране и чинится одной строкой в словаре.
 */

//: Текущее направление перевода: русский текст → показанный.
let dict = new Map();

//: Ключи-шаблоны (с `{}`). Сообщения Python собираются с подстановкой —
//: «Для режима «hat» модели нет», — и точного ключа у них быть не может.
//: Регулярки готовим заранее, чтобы не собирать их на каждый промах.
let patterns = [];

function escapeRx(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

function compile(map) {
  const out = [];
  for (const [from, to] of map) {
    if (!from.includes('{}')) continue;
    out.push([new RegExp('^' + from.split('{}').map(escapeRx).join('(.*?)') + '$', 's'),
              to, from.length]);
  }
  // Длинные шаблоны — первыми. «Записей: {}» подходит и к «Записей: 400 из 869
  // — уточните фильтр», и, попавшись раньше, съедает весь хвост непереведённым.
  out.sort((a, b) => b[2] - a[2]);
  return out;
}

function lookup(text, map, rules) {
  if (!map.size || typeof text !== 'string' || !text) return text;
  const exact = map.get(text);
  if (exact !== undefined) return exact;

  // Разметка переносит подписи по строкам, и в тексте узла остаются отступы:
  // ключом служит сама надпись, а обрамление возвращаем на место.
  const trimmed = text.trim();
  if (trimmed && trimmed !== text) {
    const inner = map.get(trimmed);
    if (inner !== undefined) return text.replace(trimmed, inner);
  }

  for (const [rx, out] of rules) {
    const m = rx.exec(text);
    if (!m) continue;
    let i = 1;
    return out.replace(/\{\}/g, () => m[i++] ?? '');
  }
  // Счётчики: «235 предметов», «12 систем». В словаре лежит слово — оно
  // склоняется по числу, и заводить шаблон на каждую форму незачем.
  const counted = /^(\d+) (\S.*)$/.exec(trimmed);
  if (counted) {
    const word = map.get(counted[2]);
    if (word !== undefined) return text.replace(trimmed, counted[1] + ' ' + word);
  }
  return text;
}

/** Перевод строки. Не нашли — отдаём как есть. */
export function t(text) { return lookup(text, dict, patterns); }

//: Атрибуты, которые человек читает. `value` не трогаем: это данные, а не
//: подпись (в поле экспорта лежит имя папки, в поиске — запрос).
const ATTRS = ['title', 'placeholder', 'aria-label'];

function walk(node, map, rules) {
  if (node.nodeType === Node.TEXT_NODE) {
    const out = lookup(node.data, map, rules);
    if (out !== node.data) node.data = out;
    return;
  }
  if (node.nodeType !== Node.ELEMENT_NODE) return;
  if (node.tagName === 'SCRIPT' || node.tagName === 'STYLE') return;
  for (const attr of ATTRS) {
    const value = node.getAttribute(attr);
    if (!value) continue;
    const out = lookup(value, map, rules);
    if (out !== value) node.setAttribute(attr, out);
  }
  for (const child of node.childNodes) walk(child, map, rules);
}

//: Словарь поставлен: повторные вызовы (сохранение настроек зовёт applyLook
//: снова) приходят с тем же языком, и гонять весь документ незачем.
let watching = false;

/**
 * Ставит язык интерфейса и переводит страницу. Пустой словарь — русский,
 * то есть исходный текст.
 */
export function useDict(map) {
  if (watching) return;
  watching = true;
  dict = new Map(Object.entries(map || {}));
  patterns = compile(dict);
  if (dict.size) walk(document.body, dict, patterns);
  // Смотрим только за ДОБАВЛЕННЫМИ узлами: правку текста, которую делает сам
  // обход, наблюдатель не видит, и зацикливания нет.
  new MutationObserver((records) => {
    if (!dict.size) return;
    for (const rec of records) {
      for (const node of rec.addedNodes) walk(node, dict, patterns);
    }
  }).observe(document.body, { childList: true, subtree: true });
}
