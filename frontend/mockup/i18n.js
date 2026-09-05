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

//: Обратное направление: чем сейчас заменено → русский оригинал. Нужно при
//: смене языка: на экране уже английский, и второй словарь его не узнает.
let back = new Map();

function escapeRx(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

function compile(map) {
  const out = [];
  for (const [from, to] of map) {
    if (!from.includes('{}')) continue;
    out.push([new RegExp('^' + from.split('{}').map(escapeRx).join('(.*?)') + '$', 's'), to]);
  }
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

//: Наблюдатель ставится один раз на весь сеанс — даже если язык потом сменят.
let watching = false;

/**
 * Ставит язык интерфейса и переводит страницу.
 *
 * Пустой словарь — русский, то есть исходный текст. При смене языка сперва
 * возвращаем страницу к русскому: на экране уже перевод, а новый словарь
 * знает только русские ключи.
 */
export function useDict(map) {
  const next = new Map(Object.entries(map || {}));
  if (back.size) walk(document.body, back, compile(back));

  dict = next;
  patterns = compile(dict);
  back = new Map([...dict].map(([from, to]) => [to, from]));
  if (dict.size) walk(document.body, dict, patterns);

  if (watching) return;
  watching = true;
  // Смотрим только за ДОБАВЛЕННЫМИ узлами: правку текста, которую делает сам
  // обход, наблюдатель не видит, и зацикливания нет.
  new MutationObserver((records) => {
    if (!dict.size) return;
    for (const rec of records) {
      for (const node of rec.addedNodes) walk(node, dict, patterns);
    }
  }).observe(document.body, { childList: true, subtree: true });
}
