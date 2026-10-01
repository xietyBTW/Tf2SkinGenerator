/*
 * «Готовые эффекты» редактора VMT: панель категорий вместо длинного меню.
 *
 * Слева категории, справа пункты выбранной — высота панели своя, и она не
 * тянется через весь экран, как меню на двадцать пунктов с пояснениями.
 * Эффект с настройками (цвет, сила) открывает форму на месте списка: она
 * заполнена тем, что уже стоит в материале, так что эффект можно
 * перенастроить. Текст эффекта собирает Python (vmt_effects.py) — здесь
 * только выбор значений.
 *
 * Панель отдаёт выбор, а вставляет его vmt.js: {item} — обычный пункт меню,
 * {text, replace} — готовый текст эффекта.
 */

import * as api from './api.js';
import { t } from './i18n.js';
import { picking } from './picker.js';

const panel = document.getElementById('vmt-fx');
const cats = document.getElementById('vmt-fx-cats');
const pane = document.getElementById('vmt-fx-pane');

//: Последняя открытая категория: к особым материалам возвращаются чаще, чем
//: листают всё с начала.
let lastGroup = 0;
//: Закрыть текущий показ (Promise ждёт выбора).
let finish = null;
//: Игровой оригинал материала: из него эффект берёт родную текстуру.
let gameText = '';

/** Панель открыта — повторный щелчок по кнопке её закрывает. */
export function closeEffects() {
  if (!finish) return false;
  finish(null);
  return true;
}

/**
 * Показывает панель над кнопкой `anchor`. `getText` — текущий текст
 * материала (форма эффекта читает из него значения). Отдаёт выбор или null.
 */
export function pickEffect(anchor, data, getText, game = '') {
  gameText = game;
  if (finish) finish(null);
  return new Promise((resolve) => {
    const onAway = (e) => {
      // Палитра своего цвета — отдельный поповер, но выбор идёт для панели.
      if (e.target.closest && e.target.closest('.picker')) return;
      if (!panel.contains(e.target) && e.target !== anchor) done(null);
    };
    // Esc — только панель: общий Esc закрыл бы и само окно редактора. Пока
    // открыта палитра, Esc закрывает её одну (picker.js).
    const onKey = (e) => {
      if (e.key !== 'Escape' || picking()) return;
      e.preventDefault();
      e.stopPropagation();
      done(null);
    };
    const done = (value) => {
      finish = null;
      document.removeEventListener('mousedown', onAway, true);
      document.removeEventListener('keydown', onKey, true);
      if (panel.matches(':popover-open')) panel.hidePopover();
      panel.hidden = true;
      // Кнопка выбранного пункта уже вне документа — фокус ушёл бы в body.
      if (!value) anchor.focus();
      resolve(value);
    };
    finish = done;

    const groups = data.groups || [];
    lastGroup = Math.min(lastGroup, Math.max(0, groups.length - 1));
    renderCats(groups, done, getText);
    showGroup(groups, lastGroup, done, getText);

    panel.hidden = false;
    panel.showPopover();
    place(anchor);
    document.addEventListener('mousedown', onAway, true);
    document.addEventListener('keydown', onKey, true);
  });
}

/** Над кнопкой (она внизу окна), не за краем экрана. */
function place(anchor) {
  const a = anchor.getBoundingClientRect();
  const box = panel.getBoundingClientRect();
  const left = Math.min(Math.max(8, a.left), innerWidth - box.width - 8);
  const top = a.top - box.height - 8 >= 8 ? a.top - box.height - 8 : a.bottom + 8;
  panel.style.left = `${left}px`;
  panel.style.top = `${Math.max(8, Math.min(top, innerHeight - box.height - 8))}px`;
}

function renderCats(groups, done, getText) {
  cats.replaceChildren(...groups.map((g, i) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'fxpick__cat';
    b.textContent = g.name;
    b.addEventListener('click', () => showGroup(groups, i, done, getText));
    return b;
  }));
}

function showGroup(groups, index, done, getText) {
  lastGroup = index;
  [...cats.children].forEach((b, i) => b.classList.toggle('is-active', i === index));
  const list = document.createElement('div');
  list.className = 'fxpick__list';
  for (const it of groups[index]?.items || []) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'fxpick__item';
    const name = document.createElement('span');
    name.className = 'fxpick__name';
    name.textContent = it.label;
    // Пункт с формой отмечен: щелчок не вставит сразу, а спросит значения.
    if (it.fields.length) name.append(' ', Object.assign(document.createElement('span'),
      { className: 'fxpick__more', textContent: '›' }));
    const hint = document.createElement('span');
    hint.className = 'fxpick__hint';
    hint.textContent = it.hint;
    b.append(name, hint);
    b.addEventListener('click', () => {
      if (it.fields.length) openForm(it, () => showGroup(groups, index, done, getText),
                                     done, getText);
      else done({ item: it });
    });
    list.append(b);
  }
  pane.replaceChildren(list);
  pane.scrollTop = 0;
}

/** Форма эффекта: поля по описанию из Python, значения — из материала. */
async function openForm(item, back, done, getText) {
  let values = {};
  try {
    const res = await api.vmtEffectValues(item.key, getText());
    values = res.values || {};
  } catch { /* не прочиталось — умолчания формы */ }
  // Пока ждали, панель закрыли или открыли заново: форма старого показа в
  // новую панель не ложится (её `done` — чужой).
  if (finish !== done) return;
  for (const f of item.fields) if (!(f.key in values)) values[f.key] = f.default;

  const form = document.createElement('div');
  form.className = 'fxpick__form';
  const head = document.createElement('div');
  head.className = 'fxpick__head';
  const backBtn = Object.assign(document.createElement('button'),
    { type: 'button', className: 'textbtn', textContent: t('← Назад') });
  backBtn.addEventListener('click', back);
  const title = Object.assign(document.createElement('p'),
    { className: 'label fxpick__title', textContent: item.label });
  head.append(backBtn, title);
  const hint = Object.assign(document.createElement('p'),
    { className: 'fxpick__hint', textContent: item.hint });
  form.append(head, hint);

  // `show_if`: поле видно, пока другие поля имеют указанные значения («Круг
  // цветов» — только у радуги, плашки — только у одного цвета).
  const rows = [];
  const sync = () => rows.forEach(({ f, row }) => {
    row.hidden = !Object.entries(f.show_if || {}).every(([k, v]) => values[k] === v);
  });
  for (const f of item.fields) {
    const row = field(f, values, sync);
    rows.push({ f, row });
    form.append(row);
  }
  sync();

  // Замена всего материала — предупреждение прямо в форме, а не отдельным
  // окном после выбора: человек видит его до того, как нажмёт.
  if (item.replace) {
    form.append(Object.assign(document.createElement('p'), {
      className: 'fxpick__note',
      textContent: t('Заменит весь материал. Вернуть игровой — «Как в игре».'),
    }));
  }
  const apply = Object.assign(document.createElement('button'),
    { type: 'button', className: 'btn--primary fxpick__apply', textContent: t('Применить') });
  apply.addEventListener('click', async () => {
    apply.disabled = true;
    let res;
    try {
      res = await api.vmtApplyEffect(item.key, values, getText(), gameText);
    } catch (err) {
      res = { error: err.message };
    } finally {
      apply.disabled = false;
    }
    if (finish !== done) return;
    if (res.error) { hint.textContent = res.error; return; }
    done({ text: res.text, replace: res.replace });
  });
  form.append(apply);
  pane.replaceChildren(form);
  pane.scrollTop = 0;
}

/** Одно поле формы. Значение пишется в `values[f.key]` сразу при выборе;
 *  `changed` — пересчитать, какие поля видны. */
function field(f, values, changed = () => {}) {
  const row = document.createElement('div');
  row.className = 'fxpick__field';
  // Без подписи — поле продолжает предыдущее (цвет под «Один цвет / Радуга»).
  if (f.label) {
    row.append(Object.assign(document.createElement('span'),
      { className: 'label fxpick__label', textContent: f.label }));
  }
  const ctl = document.createElement('div');
  ctl.className = 'fxpick__ctl';

  if (f.type === 'color') {
    // Свой цвет — подписанная кнопка с образцом и кодом, а не ещё один
    // квадрат после готовых: пунктирный квадрат никто не узнавал как палитру.
    const own = Object.assign(document.createElement('label'), { className: 'fxpick__own' });
    const pick = Object.assign(document.createElement('input'),
      { type: 'color', className: 'parts__color', value: values[f.key] });
    const code = Object.assign(document.createElement('span'), { className: 'mono fxpick__hex' });
    own.append(pick, t('Свой цвет'), code);
    const swatches = f.presets.map((hex) => {
      const s = Object.assign(document.createElement('button'),
        { type: 'button', className: 'swatch', title: hex });
      s.style.setProperty('--c', hex);
      s.addEventListener('click', () => { values[f.key] = hex; pick.value = hex; mark(); });
      return s;
    });
    const mark = () => {
      const now = String(values[f.key]).toLowerCase();
      swatches.forEach((s) => s.classList.toggle('is-active', s.title === now));
      own.classList.toggle('is-active', !f.presets.includes(now));
      code.textContent = now;
    };
    pick.addEventListener('input', () => { values[f.key] = pick.value; mark(); });
    mark();
    ctl.append(...swatches, own);
  } else if (f.type === 'choice') {
    const tags = f.choices.map((c) => {
      const b = Object.assign(document.createElement('button'),
        { type: 'button', className: 'tag', textContent: c.label });
      b.addEventListener('click', () => {
        values[f.key] = c.value;
        changed();
        tags.forEach((x) => x.classList.toggle('is-active', x === b));
      });
      b.classList.toggle('is-active', c.value === values[f.key]);
      return b;
    });
    ctl.append(...tags);
  } else if (f.type === 'range') {
    const input = Object.assign(document.createElement('input'), {
      type: 'range', className: 'slider', min: f.min, max: f.max, step: f.step,
      value: values[f.key],
    });
    const out = Object.assign(document.createElement('span'), { className: 'mono fxpick__num' });
    const show = () => { out.textContent = Number(input.value).toFixed(1); };
    input.addEventListener('input', () => { values[f.key] = Number(input.value); show(); });
    show();
    ctl.append(input, out);
  }
  row.append(ctl);
  return row;
}
