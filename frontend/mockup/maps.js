/*
 * Карты материала: normal, phong, самосвечение и прочее поверх базовой текстуры.
 *
 * Схему — какие карты бывают и что у каждой настраивается — отдаёт Python.
 * Список параметров и форматов на странице НЕ дублируется, иначе он разъедется
 * с генератором VTF.
 */

import * as api from './api.js';
import { chooseFile } from './util.js';
import { say } from './stage.js';
import { currentMaterial } from './album.js';

// ── Карты материала ─────────────────────────────────────────────────────
// Схему (какие карты бывают, что у них настраивается) отдаёт Python: список
// параметров и форматов на странице не дублируется — иначе он разъедется с
// генератором VTF.

export const mapsDlg = document.getElementById('maps');


/** Одна карточка карты. Возвращает функцию-сборщик своей записи. */
function mapCard(spec, saved) {
  const card = document.createElement('div');
  card.className = 'mapcard';

  // Голова — общий чекбокс интерфейса: щелчок по всей строке включает карту.
  const head = document.createElement('label');
  head.className = 'check mapcard__head';
  const on = document.createElement('input');
  on.type = 'checkbox';
  on.checked = spec.vmt_only ? Boolean(saved.enabled)
                             : Boolean(saved.image || saved.derive);
  const title = document.createElement('span');
  title.className = 'mapcard__title';
  title.textContent = spec.title;
  const badge = document.createElement('span');
  badge.className = 'mono mapcard__badge';
  badge.textContent = spec.badge;
  head.append(on, title, badge);
  card.append(head);

  // Подсказка видна ВСЕГДА: она нужна ровно в тот момент, когда решают,
  // включать ли карту, — то есть до включения.
  if (spec.tip) {
    const tip = document.createElement('p');
    tip.className = 'mapcard__tip';
    tip.textContent = spec.tip;
    card.append(tip);
  }

  const body = document.createElement('div');
  body.className = 'mapcard__body';
  card.append(body);

  // Авто-режим: карта выводится из базовой текстуры, файл не нужен.
  let auto = null;
  let threshold = null;
  if (spec.derive) {
    const row = document.createElement('label');
    row.className = 'check';
    auto = document.createElement('input');
    auto.type = 'checkbox';
    auto.checked = Boolean(saved.derive);
    const text = document.createElement('span');
    text.textContent = mapsDlg.dataset.autoLabel;
    row.append(auto, text);
    row.title = mapsDlg.dataset.autoTip || '';
    body.append(row);
  }

  let path = null;
  let fileRow = null;
  if (!spec.vmt_only) {
    fileRow = document.createElement('div');
    fileRow.className = 'mapcard__file';
    path = document.createElement('input');
    path.className = 'input';
    path.type = 'text';
    path.readOnly = true;
    path.placeholder = 'Файл не выбран';
    path.value = saved.image || '';
    const pick = document.createElement('button');
    pick.className = 'textbtn textbtn--sm';
    pick.type = 'button';
    pick.textContent = 'Выбрать';
    const clear = document.createElement('button');
    clear.className = 'textbtn textbtn--sm';
    clear.type = 'button';
    clear.textContent = 'Убрать';
    // Картинку кладём во временную папку и запоминаем ПУТЬ: генератор VTF
    // работает с файлами, а не с содержимым в браузере.
    pick.addEventListener('click', async () => {
      const file = await chooseFile('image/*');
      if (!file) return;
      path.value = await api.upload(file);
    });
    clear.addEventListener('click', () => { path.value = ''; });
    fileRow.append(path, pick, clear);
    body.append(fileRow);
  }

  const params = document.createElement('div');
  params.className = 'mapcard__params';
  const fields = {};

  const cellWith = (labelText, control) => {
    const cell = document.createElement('div');
    cell.className = 'mapcard__cell';
    const label = document.createElement('span');
    label.className = 'label label--inline';
    label.textContent = labelText;
    cell.append(label, control);
    params.append(cell);
    return cell;
  };

  if (spec.derive) {
    threshold = document.createElement('input');
    threshold.className = 'input input--num';
    threshold.type = 'number';
    threshold.min = '0';
    threshold.max = '255';
    threshold.placeholder = '0–255';
    threshold.value = saved.threshold ?? '';
    cellWith(mapsDlg.dataset.thresholdLabel, threshold);
  }

  for (const field of spec.numeric) {
    let input;
    if (field.choices) {
      // Список вариантов оформляем как остальные списки в интерфейсе.
      const box = document.createElement('div');
      box.className = 'select';
      input = document.createElement('select');
      for (const c of field.choices) input.append(new Option(c.label, c.value));
      input.value = saved[field.param] ?? field.default;
      box.append(input);
      cellWith(field.label, box);
    } else {
      input = document.createElement('input');
      input.className = 'input input--num';
      input.type = 'number';
      input.step = '0.1';
      input.value = saved[field.param] ?? field.default;
      cellWith(field.label, input);
    }
    fields[field.param] = input;
  }
  if (params.children.length) body.append(params);

  // Выключенная карта не должна оставлять доступными свои поля: значение,
  // которого не видно в сборке, — тот же несуществующий выбор.
  const sync = () => {
    card.classList.toggle('is-on', on.checked);
    body.hidden = !on.checked;
    if (auto && !on.checked) auto.checked = false;
    const derive = Boolean(auto && auto.checked);
    if (fileRow) fileRow.querySelectorAll('button, input')
                        .forEach((el) => { el.disabled = derive; });
    if (threshold) threshold.disabled = !derive;
  };
  on.addEventListener('change', sync);
  if (auto) auto.addEventListener('change', sync);
  sync();

  return {
    node: card,
    collect() {
      if (!on.checked) return null;
      let entry;
      if (spec.vmt_only) entry = { enabled: true };
      else if (auto && auto.checked) {
        entry = { derive: true };
        if (threshold && threshold.value.trim()) entry.threshold = threshold.value.trim();
      } else {
        if (!path || !path.value) return null;   // включили, но файла нет
        entry = { image: path.value };
      }
      for (const [param, input] of Object.entries(fields)) {
        if (String(input.value).trim()) entry[param] = String(input.value).trim();
      }
      return entry;
    },
  };
}

export async function openMaterialMaps() {
  const material = currentMaterial();
  const [schema, saved] = await Promise.all([api.mapSchema(),
                                             api.textureMaps(material)]);

  mapsDlg.dataset.autoLabel = schema.auto_label;
  mapsDlg.dataset.autoTip = schema.auto_tip || '';
  mapsDlg.dataset.thresholdLabel = schema.threshold_label;
  mapsDlg.querySelector('.ask__title').textContent = schema.title;
  document.getElementById('maps-intro').textContent = schema.intro || '';
  document.getElementById('maps-mat').textContent = material || 'главная текстура';

  const list = document.getElementById('maps-list');
  list.innerHTML = '';
  const cards = schema.maps.map((spec) => {
    const card = mapCard(spec, saved[spec.id] || {});
    list.append(card.node);
    return [spec.id, card];
  });

  mapsDlg.showModal();

  const done = (apply) => async () => {
    if (apply) {
      const maps = {};
      for (const [id, card] of cards) {
        const entry = card.collect();
        if (entry) maps[id] = entry;
      }
      const res = await api.setTextureMaps(material, maps);
      const count = Object.keys(res.maps || {}).length;
      say(count ? `Карты материала: ${count}` : 'Карты материала сняты');
    }
    mapsDlg.close();
  };
  document.getElementById('maps-ok').onclick = done(true);
  document.getElementById('maps-cancel').onclick = done(false);
}
