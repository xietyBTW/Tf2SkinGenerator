/*
 * Модель раздела частиц: что разобрано и что выбрано.
 *
 * Отдельно от показа, потому что читают это все — дерево, свойства, материалы,
 * контрольные точки, — а правят из трёх мест. Присваивать импортированную
 * привязку нельзя, поэтому правка идёт через сеттеры.
 */

//: Дерево систем последнего разобранного PCF — из него рисуется каталог.
export let pcfNodes = [];
//: Плоский список тех же систем — для списков выбора (дочерняя, поиск).
export let pcfTree = [];
//: Свёрнутые узлы. По ключу, а не по строке: одна система бывает ребёнком
//: сразу у нескольких родителей, и сворачивать её логично везде сразу.
export const pcfCollapsed = new Set();

/** Все системы дерева одним списком. */
export function flattenNodes(nodes, out = []) {
  for (const n of nodes) {
    out.push({ key: n.key, name: n.name, type: 'particle', mode: 'particles' });
    flattenNodes(n.kids, out);
  }
  return out;
}

//: Система, чьи параметры сейчас показаны.
export let pSystem = '';

//: Чем файл отличается от игры: {система: added|changed|same}. Пусто —
//: сравнивать не с чем (файл не из игры и одноимённого в ней нет).
export const pcfDiff = new Map();

/** Запоминает отличия от игры из ответа Python (если он их прислал). */
export function setDiff(diff) {
  if (!diff) return;
  pcfDiff.clear();
  for (const [name, status] of Object.entries(diff)) pcfDiff.set(name, status);
}

//: Обычный режим или экспертный. Выбор держится до смены раздела.
export let pMode = 'simple';

/** Запоминает разобранное дерево: плоский список считается из него же. */
export function setTree(nodes) {
  pcfNodes = nodes || [];
  pcfTree = flattenNodes(pcfNodes);
}

/** Выбранная система. Пустая строка — раздел открыт, но эффект не выбран. */
export function setSystem(name) { pSystem = name; }

/** Обычный режим или экспертный. */
export function setMode(mode) { pMode = mode; }
