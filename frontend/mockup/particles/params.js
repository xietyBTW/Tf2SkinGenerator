/*
 * Панель свойств выбранной системы.
 *
 * Что показать — крутилки или файл как есть — решает переключатель режима.
 * Список параметров приходит из Python готовым: схема одна на панель
 * приложения и на эту страницу.
 */

import * as api from '../api.js';
import { plist, pnote } from '../layout.js';
import { pSystem, pMode, setSystem, setMode } from './state.js';
import { pairedField, colorField, editParam } from './fields.js';
import { pfind, filterExpert, showExpert } from './expert.js';
import { syncHistory } from './playback.js';

/** Рисует панель параметров выбранной системы. */
export async function showParams(system) {
  setSystem(system);
  const expert = pMode === 'expert';
  plist.hidden = expert;
  pfind.hidden = !expert;
  document.getElementById('pexpert').hidden = !expert;
  if (expert) {
    pnote.hidden = true;
    await showExpert(system);
    // Запрос переживает смену системы: ищут обычно одно и то же в разных.
    if (pfind.value) filterExpert(pfind.value);
    return;
  }

  const list = await api.particleParams(system);
  if (pSystem !== system) return;              // выбор успел смениться

  plist.innerHTML = '';
  pnote.hidden = list.length > 0;
  for (const param of list) {
    const row = document.createElement('div');
    row.className = 'params__row';
    row.innerHTML = '<span class="params__name"></span><div class="params__in"></div>';
    row.querySelector('.params__name').textContent = param.name;
    row.title = param.hint || '';
    const box = row.querySelector('.params__in');

    // value = null означает «модуля под параметром нет». Если создать его
    // нельзя (эмиттеры), поле не врём — гасим и говорим почему.
    const shown = param.value === null ? param.placeholder : param.value;
    const dead = param.value === null && !param.creatable;

    if (param.kind === 'color_pair') {
      shown.forEach((c, n) => box.append(colorField(c, (v) => {
        const pair = shown.map((x) => x.slice());
        pair[n] = v;
        editParam(param, pair);
      })));
    } else if (param.kind === 'range') {
      // Минимум и максимум — своя пара «дорожка + поле» у каждого: одной
      // дорожкой на два конца управлять неудобно, а концы правят порознь.
      shown.forEach((v, n) => box.append(pairedField(v, param, (x) => {
        const pair = shown.slice();
        pair[n] = x;
        // Границы диапазона не должны переползать друг через друга.
        if (n === 0) pair[1] = Math.max(pair[1], x);
        else pair[0] = Math.min(pair[0], x);
        editParam(param, pair);
      })));
    } else {
      box.append(pairedField(shown, param, (v) => editParam(param, v)));
    }

    if (dead) {
      box.querySelectorAll('input').forEach((i) => { i.disabled = true; });
      row.title = 'В этой системе нет модуля для этого параметра, а создавать '
                + 'его нельзя: лишний эмиттер задваивает залп.';
    }
    plist.appendChild(row);
  }
  // Доступность отмены зависит от ЛЮБОЙ правки, а не только структурной:
  // сюда сходятся и смена системы, и правка параметра (editParam зовёт нас
  // следом). Без этого кнопки «Отменить»/«Вернуть» показывали состояние на
  // момент загрузки файла.
  syncHistory();
}

document.querySelector('.params__modes').addEventListener('click', (e) => {
  const b = e.target.closest('[data-pmode]');
  if (!b) return;
  document.querySelectorAll('[data-pmode]')
          .forEach((x) => x.classList.toggle('is-active', x === b));
  setMode(b.dataset.pmode);
  if (pSystem) showParams(pSystem);
});
