/*
 * Карта нормалей: галка «Normal Map», её настройки и живое превью на модели.
 *
 * Раньше галка работала вслепую: рельеф появлялся только в игре, после
 * сборки. Теперь он виден сразу. Картинку строит Python (normal_map.py) — та
 * же уйдёт в мод; страница только показывает её: вьювер кладёт нормаль на
 * главный материал (setNormalMap).
 */

import * as api from './api.js';
import { withViewer } from './stage.js';
import { buildParams } from './build.js';
import { texEdit } from './controls.js';

const box = document.querySelector('.nmap');
const on = document.getElementById('normal-on');
const body = box.querySelector('.nmap__body');
const range = document.getElementById('normal-strength');
const value = document.getElementById('normal-strength-val');
const invert = body.querySelector('[data-name="normal_invert"]').closest('.check').querySelector('input');
const stockBox = document.getElementById('normal-stock');
const replace = stockBox.querySelector('input');

let timer = null;
//: Номер последнего запроса: ответ на прежние настройки не нужен.
let seq = 0;

const active = () => !box.hidden && on.checked;

/** Показ настроек по галке и пересборка превью (после любой смены извне). */
export function syncNormal() {
  body.hidden = !active();
  value.textContent = `${range.value}%`;
  refreshNormal();
}

/** Пересобрать превью: сменилась текстура, предмет или настройки. */
export function refreshNormal(delay = 120) {
  clearTimeout(timer);
  timer = setTimeout(run, delay);
}

async function run() {
  const mine = ++seq;
  // Режим без нормалей — снять. Остальное решает Python: у главной карточки
  // бывают свои настройки сборки, и тогда рельеф в моде — по ним, а не по
  // галкам на экране.
  if (box.hidden) {
    withViewer((w) => w.setNormalMap?.(null));
    return;
  }
  const screen = buildParams({ live: true }).options;
  let res;
  try {
    res = await api.normalPreview(screen, texEdit ? texEdit.global.options : screen,
                                  texEdit ? texEdit.key : null);
  } catch {
    return;
  }
  if (mine !== seq) return;
  if (res.off || res.error) {
    withViewer((w) => w.setNormalMap?.(null));
    return;
  }
  // «Заменить родной рельеф» имеет смысл, только если он есть.
  stockBox.hidden = !res.stock;
  if (!res.stock) replace.checked = false;
  withViewer((w) => w.setNormalMap?.(api.fileUrl(res.png), res.material));
}

on.addEventListener('change', syncNormal);
range.addEventListener('input', () => {
  value.textContent = `${range.value}%`;
  refreshNormal(160);
});
invert.addEventListener('change', () => refreshNormal(0));
replace.addEventListener('change', () => refreshNormal(0));
