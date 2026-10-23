/*
 * Конструктор узора блеска Killstreak
 *
 * Узор - слои (полоса, вспышка, искры, дымка, картинка), у каждого свой
 * цвет и свой отрезок времени внутри прохода. Кадры считает Python
 * (sheen_builder.py) - те же, что уйдут в мод, здесь поля и проигрыватель
 *
 * Окно - карточки: «Превью» и «Проход» слева, «Слои» и «Свойства слоя»
 * справа, «Время прохода» внизу на всю ширину. Каждая карточка - свой модуль
 * (sheen-player, sheen-layers, sheen-props, sheen-timeline), состояние узора
 * и история правок - SheenPattern (sheen-pattern.js). Здесь шапка, «Проход»,
 * раскладка, клавиши и сохранение
 *
 * Превью - плоская плитка в пропорциях показанного оружия: маска ложится на
 * оружие плоско, как трафарет сбоку, и растягивается на его габариты
 * (калибровка в игре). Проход идёт 25 кадров в секунду, пауза между
 * проходами - как у игры: 5 с без убийств, на каждое убийство на 1 с меньше.
 * Цвет слоя живёт в самой маске. Цвет эффекта у своего узора белый (форма
 * эффекта его прячет), так что в игре видны ровно цвета слоёв.
 */

import * as api from './api.js';
import { t } from './i18n.js';
import { el, button, card, clone } from './sheen-ui.js';
import { SheenPattern } from './sheen-pattern.js';
import { createPlayer } from './sheen-player.js';
import { createLayers } from './sheen-layers.js';
import { createProps } from './sheen-props.js';
import { createTimeline } from './sheen-timeline.js';

const dlg = document.getElementById('sheenb');

//: Текстовое поле в фокусе: там свои Ctrl+Z и пробел. Ползунок, галка и
//: палитра - не поле: после них отмена и пробел должны работать
const typing = (e) => e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT'
  || (e.target.tagName === 'INPUT' && /^(text|number|search)$/.test(e.target.type));

/**
 * Открывает конструктор. `patternId` - свой узор для правки (пусто - новый),
 * `length` - длина прохода нового узора, секунды (у своего - его сохранённая).
 * Цвет блеска здесь не задаётся: свой узор красят его слои, а цвет эффекта
 * для него белый (vmt_effects._sheen).
 * Отдаёт {id, length} сохранённого узора, {deleted} или null.
 */
export async function openSheenBuilder({ patternId = '', length = 2.5 } = {}) {
  const schema = await api.sheenBuilderSchema();
  const fields = {
    id: '', name: t('Мой узор'), layers: clone(schema.presets[0].spec.layers),
    length: Number(length) || 2.5, streak: 5, quality: 'medium',
  };
  if (patternId) {
    const res = await api.sheenPatternLoad(patternId);
    if (!res.error) {
      Object.assign(fields, { id: res.id, name: res.name, layers: res.spec.layers,
        quality: res.spec.quality || 'medium', length: res.length });
    }
  }
  const state = new SheenPattern(schema, fields);

  return new Promise((resolve) => {
    const body = el('div', 'ask__body sheenb__body');
    dlg.replaceChildren(body);
    let alive = true;          // этот показ окна: после закрытия всё молчит

    /** Любая правка слоёв: перерисовать что нужно, пересчитать кадры */
    const changed = ({ list = false, params = false, time = true } = {}) => {
      if (list) layers.render();
      else if (params) props.render();
      if (time) timeline.render();
      state.commit();
      player.refresh();
    };
    const select = (i) => {
      state.selected = i;
      layers.render();
      timeline.render();
    };
    const travel = (d) => {
      if (!state.travel(d)) return;
      renderAll();
      player.refresh();
    };

    // Карточки
    const player = createPlayer(state, {
      onDropImage: async (file) => {
        if (state.full) return;
        const layer = clone(state.types.image.defaults);
        layer.image = await api.upload(file);
        state.add(layer);
        changed({ list: true });
      },
      onSheet: () => showSize(),
      onPlayhead: (pos) => timeline.showPlayhead(pos),
      onTransform: () => changed({ params: true, time: false }),
    });
    const layers = createLayers(state, schema, dlg, {
      changed, select, refresh: () => player.refresh(), onRender: () => props.render(),
    });
    const props = createProps(state, schema, { changed, syncSwatch: () => layers.syncSwatch() });
    const timeline = createTimeline(state, {
      onSelect: select, onChanged: () => changed({ list: true }), onSeek: (f) => player.seek(f),
    });

    // Шапка
    const head = el('div', 'sheenb__top');
    const name = el('input', 'input sheenb__name');
    name.value = state.name;
    name.maxLength = 60;
    name.placeholder = t('Имя узора');
    name.addEventListener('input', () => { state.name = name.value; });
    const undo = button('↶', 'textbtn sheenb__hist', t('Отменить (Ctrl+Z)'));
    const redo = button('↷', 'textbtn sheenb__hist', t('Вернуть (Ctrl+Y)'));
    undo.addEventListener('click', () => travel(-1));
    redo.addEventListener('click', () => travel(1));
    const syncHistory = () => { undo.disabled = !state.canUndo; redo.disabled = !state.canRedo; };
    state.onHistory = syncHistory;
    head.append(el('p', 'label sheenb__title', t('Конструктор блеска')), name, undo, redo,
      layers.presetsBtn);

    // Карточка «Проход»
    const pass = card(t('Проход'));
    // Качество - высота маски (64/128/256), ширина - по пропорции оружия
    const sizeOut = el('span', 'mono sheenb__val');
    // Размер и вес маски - формулой, как sheen_builder.mask_shape и
    // sheen_patterns.frames_for: сразу при нажатии, без ожидания кадров
    const showSize = () => {
      const h = schema.quality[state.quality] || 128;
      const aspect = player.sheet?.aspect || schema.default_aspect;
      const w = Math.min(1024, Math.max(16, 2 ** Math.round(Math.log2(Math.max(4, h * aspect)))));
      const fr = schema.frames;
      const frames = Math.min(fr.max, Math.max(fr.min, Math.round(state.length * fr.fps) + 1));
      const mb = (frames * w * h) / 2 / (1024 * 1024);
      sizeOut.textContent = t(`${w}×${h} · ${mb < 1 ? mb.toFixed(2) : mb.toFixed(1)} МБ`);
    };
    const qualitySeg = el('div', 'seg');
    const qualities = [['low', t('Низкое')], ['medium', t('Среднее')], ['high', t('Высокое')]];
    const qualityBtns = qualities.map(([id, label]) => {
      const b = button(label, id === state.quality ? 'is-active' : '');
      b.addEventListener('click', () => {
        state.quality = id;
        qualityBtns.forEach((x, i) => x.classList.toggle('is-active', qualities[i][0] === id));
        showSize();
        player.refresh();
      });
      qualitySeg.append(b);
      return b;
    });
    const pauseOut = el('span', 'mono sheenb__val', t(`пауза ${5 - state.streak} с`));
    const streakSeg = el('div', 'seg sheenb__streak');
    const streakBtns = [0, 1, 2, 3, 4, 5].map((n) => {
      const b = button(String(n), n === state.streak ? 'is-active' : '');
      b.addEventListener('click', () => {
        state.streak = n;
        streakBtns.forEach((x, i) => x.classList.toggle('is-active', i === n));
        pauseOut.textContent = t(`пауза ${5 - n} с`);
      });
      streakSeg.append(b);
      return b;
    });
    const lengthOut = el('span', 'mono sheenb__val');
    const lengthIn = Object.assign(el('input', 'slider'),
      { type: 'range', min: 1, max: 8, step: 0.5, value: state.length });
    const showLength = () => { lengthOut.textContent = t(`${state.length.toFixed(1)} с`); };
    lengthIn.addEventListener('input', () => {
      state.length = Number(lengthIn.value);
      showLength();
      showSize();
      timeline.renderRuler();
      props.render();
      player.refresh();
    });
    showLength();
    const prow = (label, title, ...nodes) => {
      const row = el('div', 'sheenb__row');
      row.title = title;
      const ctl = el('div', 'sheenb__rowctl');
      ctl.append(...nodes);
      row.append(el('span', 'sheenb__lbl', label), ctl);
      return row;
    };
    pass.content.append(
      prow(t('Качество'), t('Чётче узор - тяжелее мод. Справа - сколько маска займёт в моде.'),
        qualitySeg, sizeOut),
      prow(t('Длина прохода'), t('Сколько секунд идёт один проход.'), lengthIn, lengthOut),
      prow(t('Серия убийств'), t('Как в игре: чем больше убийств подряд, тем короче пауза между проходами.'),
        streakSeg, pauseOut));

    // Раскладка и низ
    const leftCol = el('div', 'sheenb__col');
    leftCol.append(player.box, pass.box);
    const rightCol = el('div', 'sheenb__col sheenb__col--right');
    rightCol.append(layers.box, props.box);
    const main = el('div', 'sheenb__main');
    main.append(leftCol, rightCol);

    const acts = el('div', 'ask__acts sheenb__acts');
    const del = button(t('Удалить узор'), 'textbtn sheenb__del');
    del.hidden = !state.id;
    const copy = button(t('Сохранить копией'), 'textbtn');
    copy.hidden = !state.id;
    const cancel = button(t('Отмена'), 'textbtn');
    const save = button(t('Сохранить узор'), 'btn--primary');
    acts.append(del, copy, cancel, save);
    body.append(head, main, timeline.box, acts);

    // Клавиши: пробел, Delete, Ctrl+Z/Y
    const onKey = (e) => {
      if (!alive) return;
      const mod = e.ctrlKey || e.metaKey;
      const key = e.code;
      if (mod && !typing(e) && key === 'KeyZ') {
        e.preventDefault();
        travel(e.shiftKey ? 1 : -1);
      } else if (mod && !typing(e) && key === 'KeyY') {
        e.preventDefault();
        travel(1);
      } else if (key === 'Space' && !typing(e)) {
        e.preventDefault();
        player.togglePlay();
      } else if (key === 'Delete' && !typing(e) && !e.target.closest('.lwarp__grad')
                 && state.layers[state.selected]) {
        e.preventDefault();
        layers.remove(state.selected);
      }
    };
    dlg.addEventListener('keydown', onKey);

    // Закрытие
    let saving = false;
    const finish = (value) => {
      alive = false;
      player.dispose();
      state.dispose();
      layers.dispose();
      dlg.removeEventListener('keydown', onKey);
      dlg.close();
      resolve(value);
    };
    cancel.addEventListener('click', () => finish(null));
    // Esc - как «Отмена» (своим обработчиком: прошлые показы не копятся)
    dlg.oncancel = (e) => { e.preventDefault(); if (!saving) finish(null); };
    const doSave = async (asCopy) => {
      save.disabled = true;
      copy.disabled = true;
      saving = true;
      const label = asCopy ? t(`${state.name} (копия)`) : state.name;
      const res = await api.sheenPatternSave(asCopy ? '' : state.id, label, state.spec(), state.length);
      saving = false;
      save.disabled = false;
      copy.disabled = false;
      if (res.error) { player.say(res.error); return; }
      finish({ id: res.id, length: state.length });
    };
    save.addEventListener('click', () => doSave(false));
    copy.addEventListener('click', () => doSave(true));
    let sure = false;
    del.addEventListener('click', async () => {
      if (!sure) { sure = true; del.textContent = t('Точно удалить?'); return; }
      await api.sheenPatternDelete(state.id);
      finish({ id: '', deleted: state.id, length: state.length });
    });

    function renderAll() {
      layers.render();
      timeline.renderRuler();
      timeline.render();
      syncHistory();
    }

    renderAll();
    showSize();
    dlg.showModal();
    player.refresh();
    player.start();
  });
}
