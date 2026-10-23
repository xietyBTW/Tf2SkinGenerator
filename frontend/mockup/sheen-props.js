/*
 * Карточка «Свойства слоя» конструктора блеска. Поля - секциями, которые
 * сворачиваются (Форма, Движение, Цвет, Время): иначе два десятка полей шли
 * одной лентой, и не было видно, где кончается одна группа.
 */

import * as api from './api.js';
import { t } from './i18n.js';
import { chooseFile } from './util.js';
import { stopsEditor } from './lightwarp.js';
import { el, button, card, fillCss, angleDial } from './sheen-ui.js';

const IMAGE_TYPES = '.png,.jpg,.jpeg,.gif,.bmp,.webp,.tga';
//: Поля движения - своя секция свойств, остальные поля слоя - «Форма»
const MOTION = new Set(['angle', 'tilt', 'wave', 'waves', 'speed']);
//: Такому слою цвет не нужен - секция цвета его не показывает
const SHAPE_ONLY = new Set(['mask', 'cut']);

//: Какие секции свойств открыты - между показами окна тоже
const openSections = new Set(['shape', 'motion', 'colour']);

function section(id, title, rows, summary = null) {
  const box = el('div', 'sheenb__sec' + (openSections.has(id) ? ' is-open' : ''));
  const headBtn = button('', 'sheenb__sechead');
  headBtn.append(el('span', 'sheenb__chev', '›'), el('span', 'sheenb__sectitle', title));
  if (summary) headBtn.append(summary);
  headBtn.addEventListener('click', () => {
    if (openSections.has(id)) openSections.delete(id);
    else openSections.add(id);
    box.classList.toggle('is-open', openSections.has(id));
  });
  const inner = el('div', 'sheenb__secbody');
  inner.append(...rows);
  box.append(headBtn, inner);
  return box;
}

/**
 * `pattern` - SheenPattern, `schema` - ответ sheenBuilderSchema. Колбэки:
 * `changed(opts)` - правка слоя, `syncSwatch()` - обновить образец цвета
 * выбранного слоя в списке.
 */
export function createProps(pattern, schema, { changed, syncSwatch }) {
  const propsCard = card(t('Свойства слоя'));
  propsCard.box.classList.add('sheenb__card--props');
  const params = propsCard.content;

  function render() {
    const layer = pattern.layers[pattern.selected];
    propsCard.head.querySelector('.sheenb__cardtitle').textContent = layer
      ? [t('Свойства слоя'), pattern.layerName(pattern.selected)].join(' · ') : t('Свойства слоя');
    if (!layer) { params.replaceChildren(el('p', 'sheenb__note', t('Выберите слой в списке.'))); return; }
    const fields = pattern.types[layer.type].fields;
    const shape = fields.filter((f) => !MOTION.has(f.key));
    const motion = fields.filter((f) => MOTION.has(f.key));
    const common = (key) => schema.common.filter((f) => f.key === key).map((f) => fieldRow(layer, f));
    const swatch = el('span', 'sheenb__secswatch');
    swatch.style.background = fillCss(layer);
    const span = el('span', 'mono sheenb__secsum',
      t(`${(layer.start * pattern.length).toFixed(1)}-${(layer.end * pattern.length).toFixed(1)} с`));
    // Маска и вырезание не светят сами - цвет им ни к чему
    const colour = SHAPE_ONLY.has(layer.blend) ? [] : [colourBlock(layer)];
    params.replaceChildren(...[
      shape.length && section('shape', layer.type === 'image' ? t('Картинка') : t('Форма'),
        shape.map((f) => fieldRow(layer, f))),
      motion.length && section('motion', t('Движение'), motion.map((f) => fieldRow(layer, f))),
      section('colour', t('Цвет и яркость'), [...common('blend'), ...colour, ...common('power')], swatch),
      section('time', t('Время'), [timeRow(layer), ...common('fade'), ...common('repeat'),
        ...common('bounce')], span),
    ].filter(Boolean));
  }

  /**
   * Цвет слоя одним блоком: образец и переключатель «Градиент». Градиент -
   * полоса с точками и стрелка направления по оружию, либо «Во времени»
   * (слой меняет цвет по ходу прохода) - тогда стрелка не нужна.
   */
  function colourBlock(layer) {
    const box = el('div', 'sheenb__colour');
    const field = (key) => schema.common.find((f) => f.key === key);
    const gradient = layer.fill === 'space' || layer.fill === 'time';
    const picture = layer.fill === 'image';
    const top = el('div', 'sheenb__row');
    const ctl = el('div', 'sheenb__rowctl');
    top.append(el('span', 'sheenb__lbl', t('Цвет')), ctl);
    box.append(top);
    // Свои цвета картинки вместо цвета слоя: цветной логотип на оружии
    const own = el('label', 'check');
    const ownOn = Object.assign(el('input'), { type: 'checkbox', checked: picture });
    ownOn.addEventListener('change', () => {
      layer.fill = ownOn.checked ? 'image' : 'solid';
      changed({ list: true });
    });
    own.append(ownOn, el('span', '', t('Цвета картинки')));
    own.title = t('Блеск возьмёт цвета самой картинки, а не цвет слоя');
    if (picture) {
      ctl.append(own);
      return box;
    }
    if (!gradient) {
      const pick = Object.assign(el('input', 'parts__color'), { type: 'color', value: layer.color });
      pick.addEventListener('input', () => {
        layer.color = pick.value;
        syncSwatch();
        changed({ time: true });
      });
      ctl.append(pick);
    }
    const toggle = el('label', 'check sheenb__gradtoggle');
    const on = Object.assign(el('input'), { type: 'checkbox', checked: gradient });
    on.addEventListener('change', () => {
      layer.fill = on.checked ? 'space' : 'solid';
      changed({ list: true });
    });
    toggle.append(on, el('span', '', t('Градиент')));
    ctl.append(toggle);
    if (layer.type === 'image') ctl.append(own);
    if (!gradient) return box;

    const editor = stopsEditor({
      point: t('Цвет точки'), position: t('Позиция, %'), remove_point: t('Убрать точку'),
      gradient_hint: '',
    }, field('stops').max_stops || 8, () => {
      layer.stops = editor.get();
      syncSwatch();
      changed({ time: true });
    });
    editor.set(layer.stops || field('stops').default);
    editor.node.title = t('Щёлкните по полосе - новая точка; точку можно тянуть, Delete убирает.');
    box.append(editor.node);

    const time = el('label', 'check');
    const timeOn = Object.assign(el('input'), { type: 'checkbox', checked: layer.fill === 'time' });
    timeOn.addEventListener('change', () => {
      layer.fill = timeOn.checked ? 'time' : 'space';
      changed({ list: true });
    });
    time.append(timeOn, el('span', '', t('Во времени')));
    time.title = t('Слой меняет цвет по ходу прохода, а не по оружию');
    const how = el('div', 'sheenb__row');
    const howCtl = el('div', 'sheenb__rowctl');
    if (layer.fill === 'space') {
      howCtl.append(angleDial(layer.gangle, (a) => {
        layer.gangle = a;
        syncSwatch();
        changed({ time: true });
      }));
    }
    howCtl.append(time);
    how.append(el('span', 'sheenb__lbl', t('Направление')), howCtl);
    box.append(how);
    return box;
  }

  /** Начало и конец слоя в секундах - числами, точнее, чем мышью */
  function timeRow(layer) {
    const num = (key) => {
      const input = Object.assign(el('input', 'input input--num sheenb__num'),
        { type: 'number', min: 0, max: pattern.length, step: 0.1 });
      input.value = (layer[key] * pattern.length).toFixed(1);
      input.addEventListener('change', () => {
        const v = Math.min(1, Math.max(0, Number(input.value) / pattern.length));
        if (key === 'start') {
          layer.start = Math.min(v, 0.97);
          if (layer.end - layer.start < 0.03) layer.end = layer.start + 0.03;
        } else {
          layer.end = Math.max(v, 0.03);
          if (layer.end - layer.start < 0.03) layer.start = layer.end - 0.03;
        }
        changed({ params: true });
      });
      return input;
    };
    const row = el('div', 'sheenb__row');
    const ctl = el('div', 'sheenb__rowctl');
    ctl.append(num('start'), el('span', 'sheenb__dash', '-'), num('end'), el('span', 'sheenb__unit', t('с')));
    row.append(el('span', 'sheenb__lbl', t('С и до')), ctl);
    return row;
  }

  function fieldRow(layer, f) {
    const row = el('div', 'sheenb__row');
    const ctl = el('div', 'sheenb__rowctl');
    row.append(el('span', 'sheenb__lbl', f.label), ctl);
    if (f.view === 'angle') {
      ctl.append(angleDial(layer[f.key], (a) => { layer[f.key] = a; changed({ time: false }); }));
    } else if (f.view === 'choice') {
      const box = el('div', 'seg sheenb__seg');
      const tags = f.choices.map((c) => {
        const b = button(c.label, layer[f.key] === c.value ? 'is-active' : '');
        b.addEventListener('click', () => {
          layer[f.key] = c.value;
          tags.forEach((x) => x.classList.toggle('is-active', x === b));
          // Смешивание меняет и секцию цвета, и метку слоя в списке
          changed(f.key === 'blend' ? { list: true } : { time: false });
        });
        return b;
      });
      box.append(...tags);
      ctl.append(box);
    } else if (f.view === 'range') {
      const input = Object.assign(el('input', 'slider'),
        { type: 'range', min: f.min, max: f.max, step: f.step, value: layer[f.key] });
      const out = Object.assign(el('input', 'input input--num sheenb__num'),
        { type: 'number', min: f.min, max: f.max, step: f.step });
      const digits = f.step >= 1 ? 0 : (f.step >= 0.1 ? 1 : 2);
      const show = () => { out.value = Number(layer[f.key]).toFixed(digits); };
      input.addEventListener('input', () => { layer[f.key] = Number(input.value); show(); changed({ time: false }); });
      out.addEventListener('change', () => {
        const v = Math.min(f.max, Math.max(f.min, Number(out.value) || 0));
        layer[f.key] = v;
        input.value = v;
        show();
        changed({ time: false });
      });
      show();
      ctl.append(input, out);
    } else if (f.view === 'seed') {
      const again = button(t('Перемешать'), 'tag');
      again.addEventListener('click', () => {
        layer[f.key] = Math.floor(Math.random() * 10000);
        changed({ time: false });
      });
      ctl.append(again);
    } else if (f.view === 'image') {
      const thumb = el('img', 'sheenb__thumb');
      thumb.alt = '';
      thumb.hidden = !layer.image;
      if (layer.image) thumb.src = api.fileUrl(layer.image, true);
      thumb.addEventListener('error', () => { thumb.hidden = true; });
      const pick = button(layer.image ? t('Заменить') : t('Выбрать'), 'tag');
      pick.addEventListener('click', async () => {
        // Только то, что читает сборка (Pillow): SVG и HEIC она не откроет
        const file = await chooseFile(IMAGE_TYPES);
        if (!file) return;
        layer.image = await api.upload(file);
        changed({ params: true, time: false });
      });
      ctl.append(thumb, pick);
      row.title = t('Светлое и непрозрачное проявляется блеском, чёрное и прозрачное - нет.');
    }
    return row;
  }

  return { box: propsCard.box, render };
}
