/*
 * Карточка «Слои» конструктора блеска: список слоёв (перестановка мышью,
 * меню строки), меню «+ Слой» и шаблоны узора на месте списка.
 */

import * as api from './api.js';
import { t } from './i18n.js';
import { el, button, card, glyph, clone, fillCss } from './sheen-ui.js';

//: Слой, который не светит сам, а режет слои под ним: метка в списке
const BLEND_BADGES = { mask: 'маска', cut: 'вырезает' };

/**
 * `pattern` - SheenPattern, `schema` - ответ sheenBuilderSchema. Колбэки:
 * `changed(opts)` - правка узора, `select(i)` - выбрать слой, `refresh()` -
 * пересчитать превью, `onRender()` - список перерисован (свойства тоже).
 * Отдаёт карточку, кнопку «Шаблоны» для шапки окна и методы.
 */
export function createLayers(pattern, schema, dlg, { changed, select, refresh, onRender }) {
  const addBtn = button(t('+ Слой'), 'tag sheenb__addbtn');
  const layersCard = card(t('Слои'), addBtn);
  const addMenu = el('div', 'sheenb__addmenu');
  addMenu.hidden = true;
  for (const ty of schema.types) {
    const b = button('', 'sheenb__addtype');
    b.append(glyph(ty.id), el('span', '', ty.label));
    b.addEventListener('click', () => {
      addMenu.hidden = true;
      addBtn.classList.remove('is-active');
      if (pattern.full) return;
      pattern.add(clone(ty.defaults));
      changed({ list: true });
    });
    addMenu.append(b);
  }
  addBtn.addEventListener('click', () => {
    addMenu.hidden = !addMenu.hidden;
    addBtn.classList.toggle('is-active', !addMenu.hidden);
  });

  // Шаблоны - карточки с кадром узора, на месте списка слоёв
  const presetsBtn = button(t('Шаблоны'), 'tag sheenb__presets-btn');
  const presets = el('div', 'sheenb__presets');
  presets.hidden = true;
  presets.append(el('p', 'sheenb__note', t('Начать с шаблона: заменит слои, отменить - Ctrl+Z.')));
  const cards = el('div', 'sheenb__cards');
  presets.append(cards);
  for (const p of schema.presets) {
    const tile = button('', 'sheenb__tile');
    const pic = el('img', 'sheenb__tileimg');
    pic.alt = '';
    tile.append(pic, el('span', 'sheenb__tilename', p.label));
    tile.dataset.preset = p.id;
    tile.addEventListener('click', () => {
      pattern.usePreset(p.spec.layers);
      presets.hidden = true;
      presetsBtn.classList.remove('is-active');
      changed({ list: true });
    });
    cards.append(tile);
  }
  presetsBtn.addEventListener('click', async () => {
    presets.hidden = !presets.hidden;
    presetsBtn.classList.toggle('is-active', !presets.hidden);
    if (presets.hidden || cards.dataset.loaded) return;
    cards.dataset.loaded = '1';
    try {
      const res = await api.sheenPresetThumbs();
      for (const tile of cards.children) {
        const src = res.thumbs[tile.dataset.preset];
        if (src) tile.querySelector('img').src = api.fileUrl(src);
      }
    } catch { /* без картинок - только подписи */ }
  });
  const list = el('div', 'sheenb__list');
  layersCard.content.append(presets, addMenu, list);

  /** Образец цвета слоя - только показ: цвет меняется в свойствах слоя */
  function swatchFor(layer) {
    const chip = el('span', 'sheenb__swatch');
    chip.style.background = fillCss(layer);
    chip.title = t('Цвет слоя - в свойствах слоя');
    return chip;
  }

  /** Меню «⋯» строки слоя: только этот слой, копия, удалить */
  let openMenu = null;
  const closeMenu = () => { if (openMenu) openMenu.hidden = true; openMenu = null; };
  dlg.addEventListener('click', closeMenu);
  function rowMenu(i) {
    const wrap = el('div', 'sheenb__more');
    const more = button('⋯', 'textbtn sheenb__morebtn', t('Ещё'));
    const menu = el('div', 'sheenb__menu');
    menu.hidden = true;
    const item = (label, fn) => {
      const b = button(label, 'sheenb__menuitem');
      b.addEventListener('click', (e) => { e.stopPropagation(); closeMenu(); fn(); });
      menu.append(b);
    };
    item(pattern.solo === i ? t('Показывать все слои') : t('Только этот слой в превью'), () => {
      pattern.toggleSolo(i);
      render();
      refresh();
    });
    item(t('Копия'), () => {
      if (pattern.full) return;
      pattern.duplicate(i);
      changed({ list: true });
    });
    item(t('Удалить'), () => remove(i));
    more.addEventListener('click', (e) => {
      e.stopPropagation();
      const was = !menu.hidden;
      closeMenu();
      if (!was) { menu.hidden = false; openMenu = menu; }
    });
    wrap.append(more, menu);
    return wrap;
  }

  let dragFrom = -1;
  function render() {
    openMenu = null;
    list.replaceChildren(...pattern.layers.map((layer, i) => {
      const row = el('div', 'sheenb__layer' + (i === pattern.selected ? ' is-active' : '')
                            + (layer.on ? '' : ' is-off')
                            + (pattern.solo >= 0 && pattern.solo !== i ? ' is-muted' : ''));
      row.draggable = true;
      row.title = t('Тяните, чтобы переставить');
      const eye = Object.assign(el('input'), { type: 'checkbox', checked: layer.on });
      eye.title = t('Показывать слой');
      eye.addEventListener('click', (e) => e.stopPropagation());
      eye.addEventListener('change', () => { layer.on = eye.checked; changed({ list: true }); });
      const label = el('span', 'sheenb__lname', pattern.layerName(i));
      if (pattern.solo === i) label.append(el('span', 'sheenb__badge', t('соло')));
      if (BLEND_BADGES[layer.blend]) label.append(el('span', 'sheenb__badge', t(BLEND_BADGES[layer.blend])));
      row.append(swatchFor(layer), glyph(layer.type), label, eye, rowMenu(i));
      row.addEventListener('click', () => select(i));
      row.addEventListener('dragstart', (e) => { dragFrom = i; e.dataTransfer.effectAllowed = 'move'; });
      row.addEventListener('dragover', (e) => {
        if (dragFrom < 0) return;
        e.preventDefault();
        row.classList.add('is-target');
      });
      row.addEventListener('dragleave', () => row.classList.remove('is-target'));
      row.addEventListener('dragend', () => { dragFrom = -1; });
      row.addEventListener('drop', (e) => {
        e.preventDefault();
        if (dragFrom < 0 || dragFrom === i) return;
        pattern.move(dragFrom, i);
        dragFrom = -1;
        changed({ list: true });
      });
      return row;
    }));
    if (!pattern.layers.length) {
      list.append(el('p', 'sheenb__note', t('Добавьте слой кнопкой «+ Слой».')));
    }
    onRender();
  }

  function remove(i) {
    pattern.remove(i);
    changed({ list: true });
  }

  /** Образец выбранного слоя - по его цвету, без перерисовки списка */
  function syncSwatch() {
    const layer = pattern.layers[pattern.selected];
    const sw = list.children[pattern.selected]?.querySelector('.sheenb__swatch');
    if (!layer || !sw) return;
    sw.style.background = fillCss(layer);
  }

  return {
    box: layersCard.box,
    presetsBtn,
    render,
    remove,
    syncSwatch,
    dispose() { dlg.removeEventListener('click', closeMenu); },
  };
}
