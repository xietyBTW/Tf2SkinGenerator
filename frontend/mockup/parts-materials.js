/*
 * Инструмент «Материал» режима частей: отдать части свой материал (копию
 * исходного) или родной материал модели - и вернуть их в общий.
 */

import * as api from './api.js';
import { t } from './i18n.js';
import { applyView } from './preview.js';
import { contextMenu } from './menu.js';
import { P, hintParts } from './parts-state.js';
import { refreshParts } from './parts.js';

//: Свои материалы частей (из ответа `parts`) и куда щелчок инструментом
//: «Материал» отдаёт часть: '' - в новый
let partMats = [];
//: Родные материалы модели, которым можно отдать части (`targets` разбора)
let matTargets = [];
let matTarget = '';

/** Части - в материал: '' - новый, имя - этот, '-' - обратно в общий */
async function movePartsTo(ids, target) {
  const res = await api.setPartMaterial(P.material, ids, target);
  if (res.error) { hintParts(res.error); return; }
  // Новый становится целью: следующие щелчки добавляют части в него же
  if (res.created) matTarget = res.created;
  applyView(res);
  await refreshParts();
}

/** Щелчок инструментом «Материал» по части: в выбранный материал */
export function toggleMaterial(part) {
  // Часть выбранного материала возвращается в общий: так ошибочный щелчок
  // исправляется тем же движением
  const own = (P.list.find((x) => x.id === part) || {}).own || '';
  movePartsTo([part], own && own === matTarget ? '-' : matTarget);
}

/** Куда пойдёт следующая часть, по порядку: свои материалы частей, потом
 *  родные материалы модели. Номер в этом списке стоит и на чипе части */
export function matOrder() {
  return [...partMats.filter((m) => !m.existing).map((m) => m.name), ...matTargets];
}

/** Родной ли это материал модели (а не свой материал части) */
export const isNative = (name) => Boolean(name) && matTargets.includes(name);

/** Список инструмента «Материал». Родные материалы модели - ниже своих:
 *  части можно отдать и им, тогда они берут их VMT и текстуру */
export function showPartMaterials(list, natives) {
  partMats = list || [];
  if (natives !== undefined) matTargets = natives || [];
  const order = matOrder();
  if (!order.includes(matTarget)) matTarget = '';
  const given = Object.fromEntries(partMats.filter((m) => m.existing).map((m) => [m.name, m]));
  const box = document.getElementById('pmat-list');
  box.replaceChildren();
  const row = (name, label) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'pmat__item' + (name === matTarget ? ' is-active' : '');
    b.append(label);
    b.addEventListener('click', (e) => {
      if (e.target.closest('.parts__x')) return;
      matTarget = name;
      showPartMaterials(partMats);
    });
    return b;
  };
  // Строка материала: номер, имя и крестик «вернуть части в общий» - у
  // родного он только там, где ему уже отданы части этого материала
  const entry = (title, removable) => {
    const num = document.createElement('span');
    num.className = 'pmat__num';
    num.textContent = String(order.indexOf(title) + 1);
    const name = document.createElement('span');
    name.className = 'pmat__name';
    name.textContent = title;
    name.title = title;
    const b = row(title, num);
    b.append(name);
    if (removable) {
      const x = document.createElement('button');
      x.type = 'button';
      x.className = 'parts__x';
      x.textContent = '×';
      x.title = t('Вернуть все части материала в общий');
      x.addEventListener('click', async () => {
        const res = await api.dropPartMaterial(title, P.material);
        if (res.error) { hintParts(res.error); return; }
        applyView(res);
        await refreshParts();
      });
      b.append(x);
    }
    return b;
  };
  box.append(row('', t('Новый материал')));
  partMats.filter((m) => !m.existing).forEach((m) => box.append(entry(m.name, true)));
  if (matTargets.length) {
    const head = document.createElement('p');
    head.className = 'pmat__head';
    head.textContent = t('Материалы модели');
    box.append(head);
    matTargets.forEach((name) => box.append(entry(name, Boolean(given[name]))));
  }
}

/** Правая кнопка по чипу - свой материал без смены инструмента */
export async function partMenu(e, part) {
  const items = [{ heading: t('Свой материал') },
                 { label: t('В новый материал'), value: '' }];
  for (const m of partMats) {
    if (!m.existing && m.name !== part.own) {
      items.push({ label: t('В материал «{}»').replace('{}', m.name), value: m.name });
    }
  }
  const natives = matTargets.filter((name) => name !== part.own);
  if (natives.length) items.push(null, { heading: t('Материалы модели') });
  for (const name of natives) {
    items.push({ label: t('В материал «{}»').replace('{}', name), value: name });
  }
  if (part.own) items.push(null, { label: t('Вернуть в общий'), value: '-' });
  const value = await contextMenu(e, items);
  if (value !== null) await movePartsTo([part.id], value);
}
