/*
 * Карты материала: normal, phong, самосвечение и прочее поверх базовой текстуры
 *
 * Схему - какие карты бывают и что у каждой настраивается - отдаёт Python.
 * Список параметров и форматов на странице НЕ дублируется, иначе он разъедется
 * с генератором VTF
 *
 * Окно в две колонки: слева все карты строкой (галка, название, откуда
 * карта), справа одна выбранная целиком. Откуда карта берётся - один
 * переключатель «Файл / Авто / Конструктор / Из мода», чтобы не гадать, какая
 * из галок победит
 *
 * Запись карты для сессии (`collect`): {image} | {derive,
 * threshold} | {generate} | {mod} | {enabled} плюс числа карты и её свои
 * настройки (`settings`: цвет блика, маска обводки).
 */

import * as api from './api.js';
import { chooseFile } from './util.js';
import { say } from './stage.js';
import { currentMaterial } from './album.js';
import { lightwarpEditor } from './lightwarp.js';
import { phongwarpEditor, phongSphere } from './phongwarp.js';
import { glowPreview } from './glow.js';
import { mapPreview } from './mappreview.js';

export const mapsDlg = document.getElementById('maps');
const nav = document.getElementById('maps-nav');
const pane = document.getElementById('maps-pane');

//: Последняя выбранная карта: окно открывают, чтобы поправить ту же
let lastSelected = null;
//: Материал открытого окна - превью свечения берёт его текстуру
let openMaterial = '';

/** Состояние одной карты из сохранённой записи */
function stateOf(spec, saved) {
  const sources = [];
  if (!spec.vmt_only) {
    if (saved.mod) sources.push('mod');
    if (spec.generator) sources.push('gen');
    sources.push('file');
    if (spec.derive) sources.push('auto');
  }
  let source = sources[0] || null;
  if (saved.generate) source = 'gen';
  else if (saved.derive) source = 'auto';
  else if (saved.image) source = 'file';
  else if (saved.mod && !spec.vmt_only) source = 'mod';
  else if (spec.generator) source = 'gen';
  else if (sources.includes('file')) source = 'file';

  const numbers = {};
  for (const f of spec.numeric) numbers[f.param] = saved[f.param] ?? f.default;
  // Своя настройка, которой нет в сохранённой записи, у уже включённой карты
  // (старая работа, карта мода) - «как у материала», а не значение по
  // умолчанию: иначе первое же «Применить» поменяло бы материал, хотя
  // человек этого не выбирал (rim light снял бы родную маску обводки)
  const fresh = !Object.keys(saved).length;
  const settings = {};
  for (const f of spec.settings) settings[f.key] = saved[f.key] ?? (fresh ? f.default : undefined);
  return {
    spec,
    sources,
    source,
    on: spec.vmt_only ? Boolean(saved.enabled)
                      : Boolean(saved.image || saved.derive || saved.mod || saved.generate),
    mod: saved.mod ? { preview: saved.preview || '', texture: saved.texture || '' } : null,
    image: saved.generate ? '' : (saved.image || ''),
    threshold: saved.threshold ?? '',
    numbers,
    // Числа, что уже стояли в записи или тронуты руками. У карты мода уходят
    // только они: умолчание страницы ($phongboost 2) удвоило бы блик мода
    touched: new Set(Object.keys(saved).filter((k) => k.startsWith('$'))),
    settings,
    generate: saved.generate || null,
    editor: null,                      // конструктор полоски - создаётся по требованию
  };
}

/** Запись карты для сессии или null (выключена / включена без источника) */
function collect(st) {
  if (!st.on) return null;
  let entry;
  if (st.spec.vmt_only) {
    // Карта мода, которую не правили, остаётся как в моде, правленая - своя
    entry = st.mod ? { enabled: true, mod: true } : { enabled: true, ...visibleSettings(st) };
  }
  else if (st.source === 'auto') {
    entry = { derive: true };
    if (String(st.threshold).trim()) entry.threshold = String(st.threshold).trim();
  } else if (st.source === 'gen') {
    entry = { generate: st.editor ? st.editor.params() : (st.generate || {}) };
  } else if (st.source === 'mod') entry = { mod: true };
  else if (st.image) entry = { image: st.image };
  else return null;
  if (!st.spec.vmt_only) Object.assign(entry, visibleSettings(st));
  const fromMod = Boolean(entry.mod);
  for (const [param, value] of Object.entries(st.numbers)) {
    if (fromMod && !st.touched.has(param)) continue;
    if (String(value).trim()) entry[param] = String(value).trim();
  }
  return entry;
}

/** Видна ли настройка при текущих значениях остальных (`show_if`) */
const shown = (st, field) => !field.show_if
  || Object.entries(field.show_if).every(([key, value]) => (Array.isArray(value)
    ? value.includes(st.settings[key]) : st.settings[key] === value));

/** Настройки, которые сейчас имеют смысл: скрытые (не тот режим) не уходят */
function visibleSettings(st) {
  const out = {};
  for (const f of st.spec.settings) {
    const value = st.settings[f.key];
    if (shown(st, f) && value !== undefined && String(value).trim() !== '') out[f.key] = String(value);
  }
  return out;
}

/** Подпись выбранного варианта первой настройки-выбора - для строки списка */
function choiceLabel(st) {
  const field = st.spec.settings.find((f) => f.kind === 'choice');
  return field?.choices.find((c) => c.value === st.settings[field.key])?.label;
}

/** Короткое «откуда карта» для строки списка */
function statusOf(st, ui, schema) {
  if (!st.on) return ui.off;
  if (st.spec.vmt_only) return st.mod ? schema.from_mod : (choiceLabel(st) || ui.on);
  if (st.source === 'mod') return schema.from_mod;
  if (st.source === 'auto') return ui.src_auto;
  if (st.source === 'gen') return ui.src_gen;
  return st.image ? st.image.split(/[\\/]/).pop() : ui.no_file;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** Левая колонка: строка на карту. Щелчок выбирает, галка включает */
function renderNav(states, schema, select) {
  nav.replaceChildren(...states.map((st) => {
    // `check` - та же галочка, что во всём приложении, а не браузерная
    const row = el('div', 'check maprow' + (st === select.current ? ' is-active' : '')
                          + (st.on ? ' is-on' : ''));
    const check = el('input');
    check.type = 'checkbox';
    check.checked = st.on;
    check.title = schema.ui.on;
    check.addEventListener('click', (e) => e.stopPropagation());
    check.addEventListener('change', () => {
      st.on = check.checked;
      select.show(st);
    });
    const text = el('div', 'maprow__text');
    text.append(el('span', 'maprow__title', st.spec.title),
                el('span', 'maprow__status' + (st.on && collect(st) === null ? ' is-warn' : ''),
                   statusOf(st, schema.ui, schema)));
    row.append(check, text);
    row.addEventListener('click', () => select.show(st));
    return row;
  }));
}

/** Правая колонка: выбранная карта целиком */
function renderPane(st, schema, touch) {
  const ui = schema.ui;
  const head = el('div', 'mappane__head');
  const title = el('p', 'mappane__title', st.spec.title);
  const badge = el('span', 'mono mapcard__badge', st.spec.badge);
  const toggle = el('label', 'check mappane__on');
  const on = el('input');
  on.type = 'checkbox';
  on.checked = st.on;
  on.addEventListener('change', () => { st.on = on.checked; touch(false); });
  toggle.append(on, el('span', '', ui.on));
  head.append(title, badge, toggle);

  const body = el('div', 'mappane__body' + (st.on ? '' : ' is-off'));
  if (st.spec.tip) body.append(el('p', 'mapcard__tip mappane__tip', st.spec.tip));

  // Любая правка включает карту: человек настраивает её, чтобы она была
  const edit = () => { if (!st.on) { st.on = true; on.checked = true; body.classList.remove('is-off'); } touch(true); };

  if (st.sources.length > 1) {
    const seg = el('div', 'seg mappane__seg');
    const names = { mod: schema.from_mod, gen: ui.src_gen, file: ui.src_file, auto: ui.src_auto };
    for (const src of st.sources) {
      const b = el('button', src === st.source ? 'is-active' : '', names[src]);
      b.type = 'button';
      b.addEventListener('click', () => { st.source = src; edit(); touch(false); });
      seg.append(b);
    }
    const row = el('div', 'mappane__row');
    row.append(el('span', 'label label--inline', ui.source), seg);
    body.append(row);
  }

  if (!st.spec.vmt_only) body.append(sourceView(st, schema, edit, () => touch(false)));
  if (st.spec.settings.length) {
    // У параметрической карты из мода правка делает её своей, у карты с
    // текстурой источник «из мода» остаётся - меняются только настройки
    body.append(settingsView(st, schema, () => {
      if (st.spec.vmt_only) st.mod = null;
      edit();
    }, () => touch(false)));
  }

  if (st.spec.numeric.length) {
    const params = el('div', 'mapcard__params mappane__params');
    for (const field of st.spec.numeric) {
      const cell = el('label', 'mapcard__cell');
      cell.append(el('span', 'label label--inline', field.label));
      let input;
      if (field.choices) {
        const box = el('div', 'select');
        input = el('select');
        for (const c of field.choices) input.append(new Option(c.label, c.value));
        box.append(input);
        cell.append(box);
      } else {
        input = el('input', 'input input--num');
        input.type = 'number';
        input.step = '0.1';
        cell.append(input);
      }
      input.value = st.numbers[field.param];
      input.addEventListener('input', () => {
        st.numbers[field.param] = input.value;
        st.touched.add(field.param);
        edit();
      });
      params.append(cell);
    }
    body.append(params);
  }
  // Превью карты - после всех полей: оно читает их на каждом кадре
  const preview = mapPreview(st, schema, openMaterial);
  if (preview) {
    body.append(preview.node);
    requestAnimationFrame(() => preview.start());
  }
  pane.replaceChildren(head, body);
}

/** Содержимое выбранного источника. `redraw` - перерисовать панель целиком
 * (новый файл - новое превью) */
function sourceView(st, schema, edit, redraw) {
  const ui = schema.ui;
  if (st.source === 'mod') {
    const box = el('div', 'mappane__file');
    if (st.mod.preview) box.append(thumb(api.fileUrl(st.mod.preview, true)));
    const name = el('span', 'mono mapcard__modname', st.mod.texture.split('/').pop() || schema.from_mod);
    name.title = st.mod.texture;
    box.append(name);
    return box;
  }
  if (st.source === 'auto') {
    const box = el('div', 'mappane__auto');
    box.append(el('p', 'mapcard__tip mappane__tip', ui.auto_text));
    const cell = el('label', 'mapcard__cell');
    const threshold = el('input', 'input input--num');
    threshold.type = 'number';
    threshold.min = '0';
    threshold.max = '255';
    threshold.placeholder = '0-255';
    threshold.value = st.threshold;
    threshold.addEventListener('input', () => { st.threshold = threshold.value; edit(); });
    cell.append(el('span', 'label label--inline', mapsDlg.dataset.thresholdLabel), threshold);
    box.append(cell);
    return box;
  }
  if (st.source === 'gen') {
    // Конструктор живёт, пока открыто окно: переключение карт его не сбрасывает
    if (!st.editor) {
      st.editor = st.spec.generator === 'phongwarp'
        ? phongwarpEditor(schema.phongwarp, st.generate, () => edit())
        : lightwarpEditor(schema.lightwarp, st.generate, () => edit());
    }
    st.editor.setEnabled(true);
    return st.editor.node;
  }
  return fileZone(st.image, ui.drop, (path) => { st.image = path; edit(); redraw(); });
}

/** Свои настройки карты: выбор - переключателем, сила - ползунком, порог -
 * числом, цвет - палитрой, файл - полем с превью */
function settingsView(st, schema, edit, redraw) {
  const box = el('div', 'mappane__settings');
  // Соседние простые поля (числа, ползунки, цвет) - одной строкой, а не
  // столбиком, переключатель или поле файла начинают новую
  let line = null;
  for (const f of st.spec.settings) {
    if (!shown(st, f)) continue;
    const value = st.settings[f.key];
    if (f.kind === 'choice' || f.kind === 'file') line = null;
    if (f.kind === 'choice') {
      const seg = el('div', 'seg mappane__seg');
      for (const c of f.choices) {
        const b = el('button', c.value === value ? 'is-active' : '', c.label);
        b.type = 'button';
        // Выбор меняет набор полей ниже - панель перерисовывается
        b.addEventListener('click', () => { st.settings[f.key] = c.value; edit(); redraw(); });
        seg.append(b);
      }
      const row = el('div', 'mappane__row');
      row.append(el('span', 'label label--inline', f.label), seg);
      row.title = f.tip || '';
      box.append(row);
      // Пояснение о последствиях выбора - видно сразу, а не только при наведении
      if (f.note && value && value !== f.default) box.append(el('p', 'mapcard__tip mappane__warn', f.note));
    } else if (f.kind === 'file') {
      const row = el('div', 'mappane__auto');
      row.title = f.tip || '';
      row.append(el('span', 'label label--inline', f.label),
                 fileZone(value, schema.ui.drop,
                          (path) => { st.settings[f.key] = path; edit(); redraw(); }));
      box.append(row);
    } else {
      const cell = el('label', 'mapcard__cell');
      cell.append(el('span', 'label label--inline', f.label));
      cell.title = f.tip || '';
      // Не тронутое («как у материала») показывается подсказкой `display`,
      // но в запись не уходит
      const untouched = value === undefined || String(value).trim() === '';
      const shownValue = String(untouched ? (f.display ?? f.default ?? '') : value);
      let input;
      if (f.kind === 'color') {
        input = el('input', 'lwarp__color');
        input.type = 'color';
        input.value = shownValue;
        cell.append(input);
      } else if (f.slider || f.max === 100) {
        input = el('input', 'slider lwarp__range');
        input.type = 'range';
        input.min = String(f.min);
        input.max = String(f.max);
        input.step = String(f.step || 1);
        input.value = shownValue;
        // Не тронут - значение приглушено: в материал оно не пишется
        const out = el('span', 'mono lwarp__value' + (untouched ? ' is-default' : ''), shownValue);
        input.addEventListener('input', () => {
          out.textContent = input.value;
          out.classList.remove('is-default');
        });
        cell.append(input, out);
      } else {
        input = el('input', 'input input--num');
        input.type = 'number';
        input.min = String(f.min);
        input.max = String(f.max);
        input.step = String(f.step || 1);
        // Пустое - как у материала, подсказка показывает обычное значение
        input.placeholder = untouched ? String(f.display ?? `${f.min}-${f.max}`) : '';
        input.value = untouched ? '' : shownValue;
        cell.append(input);
      }
      input.addEventListener('input', () => { st.settings[f.key] = input.value; edit(); });
      if (!line) {
        line = el('div', 'mapcard__params');
        box.append(line);
      }
      line.append(cell);
    }
  }
  if (st.spec.preview === 'phong') box.append(phongPreview(st, schema));
  if (st.spec.preview === 'glow') {
    const preview = glowPreview(st, schema, openMaterial);
    box.append(preview.node);
    requestAnimationFrame(() => preview.start());
  }
  return box;
}

/** Шар карточки «Блик»: края блика и цвет - из текущих настроек */
function phongPreview(st, schema) {
  const num = (key, fallback) => {
    const v = parseFloat(st.settings[key]);
    return Number.isFinite(v) ? v : fallback;
  };
  const sphere = phongSphere(schema.ui.preview, schema.ui.preview_tip, () => ({
    ranges: [num('fres_center', 0.25), num('fres_mid', 0.5), num('fres_edge', 1)],
    tint: st.settings.tint === 'color' && st.settings.tint_color
      ? [1, 3, 5].map((i) => parseInt(st.settings.tint_color.slice(i, i + 2), 16) / 255)
      : null,
  }));
  requestAnimationFrame(() => sphere.start());
  return sphere.node;
}

/** Поле файла: превью, «Выбрать», «Убрать», картинку можно бросить на поле */
function fileZone(path, dropText, onSet) {
  const zone = el('div', 'mappane__drop' + (path ? ' has-file' : ''));
  if (path) zone.append(thumb(api.fileUrl(path, true)));
  const text = el('div', 'mappane__droptext');
  text.append(el('span', 'mono mapcard__modname', path ? path.split(/[\\/]/).pop() : dropText));
  const acts = el('div', 'mappane__acts');
  const pick = el('button', 'textbtn textbtn--sm', 'Выбрать');
  pick.type = 'button';
  const clear = el('button', 'textbtn textbtn--sm', 'Убрать');
  clear.type = 'button';
  clear.hidden = !path;
  acts.append(pick, clear);
  text.append(acts);
  zone.append(text);
  const take = async (file) => {
    if (!file) return;
    onSet(await api.upload(file));
  };
  pick.addEventListener('click', async () => take(await chooseFile('image/*')));
  clear.addEventListener('click', () => onSet(''));
  zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('is-over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('is-over'));
  zone.addEventListener('drop', (e) => {
    e.preventDefault();
    zone.classList.remove('is-over');
    const file = [...(e.dataTransfer?.files || [])].find((f) => f.type.startsWith('image/'));
    take(file);
  });
  return zone;
}

function thumb(src) {
  const img = el('img', 'mapcard__thumb');
  img.src = src;
  img.alt = '';
  return img;
}

export async function openMaterialMaps() {
  const material = currentMaterial();
  openMaterial = material;
  const [schema, saved] = await Promise.all([api.mapSchema(),
                                             api.textureMaps(material)]);

  mapsDlg.dataset.thresholdLabel = schema.threshold_label;
  mapsDlg.querySelector('.ask__title').textContent = schema.title;
  document.getElementById('maps-intro').textContent = schema.intro || '';
  document.getElementById('maps-mat').textContent = material || 'главная текстура';

  const states = schema.maps.map((spec) => stateOf(spec, saved[spec.id] || {}));
  const select = {
    current: states.find((st) => st.spec.id === lastSelected)
             || states.find((st) => st.on) || states[0],
    show(st) {
      select.current = st;
      lastSelected = st.spec.id;
      renderNav(states, schema, select);
      renderPane(st, schema, (repaint) => {
        // Правка поля - только строка слева, смена источника - и правая
        if (repaint) renderNav(states, schema, select);
        else select.show(st);
      });
    },
  };
  select.show(select.current);

  mapsDlg.showModal();

  const done = (apply) => async () => {
    if (apply) {
      const maps = {};
      states.forEach((st) => {
        const entry = collect(st);
        if (entry) maps[st.spec.id] = entry;
      });
      const res = await api.setTextureMaps(material, maps);
      const count = Object.keys(res.maps || {}).filter((id) => !(res.maps[id] || {}).off).length;
      say(count ? `Карты материала: ${count}` : 'Карты материала сняты');
    }
    mapsDlg.close();
  };
  document.getElementById('maps-ok').onclick = done(true);
  document.getElementById('maps-cancel').onclick = done(false);
}
