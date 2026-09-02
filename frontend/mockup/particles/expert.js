/*
 * Экспертное дерево: группы → модули → все атрибуты, как они лежат в PCF.
 *
 * Обычный режим показывает крутилки, этот — файл как есть. Поиск сужает
 * показанное, а не запрашивает заново: дерево уже целиком на странице.
 */

import { say, withParticles } from '../stage.js';
import * as api from '../api.js';
import { pSystem } from './state.js';
import { attrField, supportedModules } from './fields.js';
import { expertMenu } from './actions.js';

export const pfind = document.getElementById('pfind');

/**
 * Оставляет в дереве то, что подходит под запрос.
 *
 * Пустой запрос сворачивает всё обратно: развёрнутые модули после поиска
 * выглядели бы так, будто их открыл пользователь.
 */
export function filterExpert(query) {
  const q = query.trim().toLowerCase();
  document.querySelectorAll('.expert__mod').forEach((mod) => {
    const modName = mod.querySelector('.expert__name').textContent.toLowerCase();
    let hits = 0;
    mod.querySelectorAll('.params__row').forEach((row) => {
      const name = row.querySelector('.params__name').textContent.toLowerCase();
      // Совпало имя модуля — показываем его целиком, иначе только строки.
      const ok = !q || modName.includes(q) || name.includes(q);
      row.hidden = !ok;
      if (ok) hits += 1;
    });
    mod.hidden = Boolean(q) && hits === 0;
    mod.open = Boolean(q) && hits > 0;
  });
  // Заголовок группы без единого модуля — висящая подпись; прячем вместе с ней.
  document.querySelectorAll('.expert__block').forEach((block) => {
    block.hidden = ![...block.querySelectorAll('.expert__mod')]
      .some((m) => !m.hidden);
  });
}

pfind.addEventListener('input', () => filterExpert(pfind.value));

/** Экспертное дерево: группы → модули → все атрибуты, как они лежат в PCF. */
export async function showExpert(system) {
  const data = await api.particleSystem(system);
  if (pSystem !== system) return;

  const supported = supportedModules();
  const box = document.getElementById('pexpert');
  box.innerHTML = '';
  for (const g of data.groups || []) {
    // Группа — заголовком над своими модулями, а не подписью на каждом:
    // «OPERATORS» пять раз подряд ничего не добавляло, только шумело.
    const block = document.createElement('section');
    block.className = 'expert__block';
    const head = document.createElement('p');
    head.className = 'label expert__head';
    head.textContent = g.group || 'система';
    // Правая кнопка на заголовке группы — добавить в неё модуль.
    head.addEventListener('contextmenu', (e) => expertMenu(e, {
      group: g.group, index: null, attr: null,
    }));
    block.append(head);
    box.append(block);

    if (g.group === 'children') {
      // Дети — ссылки, а не модули: у них нет параметров, только имя.
      for (const kid of g.modules) {
        const row = document.createElement('div');
        row.className = 'expert__kid';
        row.textContent = kid.title;
        row.addEventListener('contextmenu', (e) => expertMenu(e, {
          group: 'children', index: kid.index, attr: null,
        }));
        block.append(row);
      }
      continue;
    }

    for (const mod of g.modules) {
      const d = document.createElement('details');
      d.className = 'expert__mod';
      // Свёрнуто всё: 16 названий модулей — это карта системы, а 181 строка
      // подряд — стена, в которой ничего не найти.
      d.open = false;
      // Адрес модуля нужен кнопкам «Параметр +» и удалению.
      d.dataset.group = g.group || '';
      d.dataset.index = mod.index;

      const sum = document.createElement('summary');
      sum.innerHTML = '<span class="expert__name"></span>'
                    + '<span class="expert__warn"></span>';
      sum.querySelector('.expert__name').textContent = mod.title;
      sum.addEventListener('contextmenu', (e) => expertMenu(e, {
        group: g.group, index: mod.index, attr: null,
      }));
      sum.title = mod.help || '';
      // Модуль, который движок не симулирует: в игре он работает, в кадре —
      // нет. Промолчать нельзя, правка выглядела бы сломанной.
      if (g.group && supported && !supported(g.group, mod.title)) {
        sum.querySelector('.expert__warn').textContent = 'не в превью';
      }
      d.append(sum);

      for (const attr of mod.attrs) {
        const row = document.createElement('div');
        // Строке и вектору поле рядом с подписью не годится: подпись сжималась
        // до нуля, а третья компонента уезжала за край. Им — своя строка.
        // Цвет тоже массив, но образец с альфой рядом с подписью помещается.
        const wide = attr.t === 'string'
                  || (Array.isArray(attr.v) && attr.t !== 'color');
        row.className = 'params__row' + (wide ? ' params__row--wide' : '');
        row.innerHTML = '<span class="params__name"></span>';
        row.querySelector('.params__name').textContent = attr.name;
        row.title = attr.help || '';
        row.append(attrField(attr, async (value) => {
          const res = await api.setParticleAttr(system, g.group, mod.index,
                                                attr.name, value);
          if (res.error) { say(res.error); return; }
          withParticles((w) => w.updateSystems(res.systems, pSystem));
        }));
        row.addEventListener('contextmenu', (e) => expertMenu(e, {
          group: g.group, index: mod.index, attr: attr.name,
        }));
        d.append(row);
      }
      block.append(d);
    }
  }
}
