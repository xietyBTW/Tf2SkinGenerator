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
