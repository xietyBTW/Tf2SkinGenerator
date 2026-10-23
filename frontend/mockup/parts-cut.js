/*
 * Ножницы режима частей: выделить на модели и «Отделить» в новую часть,
 * отрезать остров развёртки, вернуть отрезанное на место
 *
 * Выделение ведёт вьювер (он его рисует и знает меш), здесь - способ
 * выделения, подсказки и запросы к Python.
 */

import * as api from './api.js';
import { plural } from './util.js';
import { t } from './i18n.js';
import { withViewer, viewer } from './stage.js';
import { applyView } from './preview.js';
import { P, hintParts } from './parts-state.js';
import { usePartsMaterial, partsTarget, refreshParts } from './parts.js';

//: Ножницы: чем выделять и сколько выделено (ведёт вьювер, число - отсюда)
export const cutOpts = { tool: 'detail', angle: 30, radius: 0.05, erase: false };

/** Возвращает отрезок туда, откуда вырезали: область ножниц - одним шагом,
 *  отрезок по островам - со всеми островами, из которых он собран */
async function uncutPart(part) {
  if (part.region >= 0) {
    const res = await api.removePartRegion(P.material, part.region);
    if (res.error) { hintParts(res.error); return; }
    applyView(res);
    await refreshParts();
    hintParts('Часть возвращена на место');
    return;
  }
  for (const island of part.islands || []) await cutIsland(part.id, island);
}

/**
 * Отрезает названный остров развёртки или приращивает его обратно
 *
 * Остров, а не «следующий шов»: счётчик резал в своём порядке, от крупного, и
 * до мизинца можно было добраться только разрезав перед ним всё остальное
 *
 * Режется ГРУППА - все куски, делящие эту развёртку. У рук шпиона левая и
 * правая делят её целиком, и разрезать одну без другой нельзя: в игре у них
 * общие пиксели, краска легла бы на обе.
 */
async function cutIsland(partId, island) {
  const known = (P.list || []).find((x) => x.id === partId);
  if (!known || island == null || island < 0) return;
  const total = (P.groups || {})[known.group] || 1;
  if (total < 2) { hintParts('У этого куска один остров развёртки - резать нечего'); return; }

  hintParts('Режу…');
  const res = await api.togglePartIsland(P.material, known.group, island);
  if (res.error) { hintParts(res.error); return; }
  applyView(res);
  const fresh = await refreshParts();
  const cut = ((fresh && fresh.parts) || [])
    .filter((x) => x.group === known.group && (x.islands || []).length);
  const uniq = new Set(cut.flatMap((x) => x.islands)).size;
  // Про возврат говорим, только когда есть что возвращать: у мелкого острова
  // попасть по нему курсором трудно, поэтому там же называем «−» на чипе.
  // Фразой целиком - так её узнаёт словарь, хвост переводим сами, склейку
  // он уже не узнает
  hintParts(plural(uniq, `Отрезано ${uniq} остров из ${total}`,
                   `Отрезано ${uniq} острова из ${total}`,
                   `Отрезано ${uniq} островов из ${total}`)
            + (uniq ? t('. Вернуть - щелчок по нему же или «−» на его чипе') : ''));
}

/** Вся часть - в выделение ножниц или из него (щелчок по чипу) */
export function selectWholePart(part) {
  const map = P.maps[P.material];
  const w = viewer();
  if (!map || !w || !w.toggleCutTris) return;
  const tris = [];
  map.forEach((owner, tri) => { if (owner === part.id) tris.push(tri); });
  w.toggleCutTris(P.material, tris);
}

/**
 * «Отделить»: выделенное ножницами - в отдельную часть
 *
 * Выделение живёт во вьювере (он его рисует и знает меш), номера
 * треугольников уходят в Python. Зеркальную половину Python добирает сам -
 * об этом говорим: иначе человек выделил одну сторону, а покрасились обе.
 */
export async function applyCut() {
  const w = viewer();
  const sel = w && w.cutSelection ? w.cutSelection() : null;
  if (!sel || !sel.triangles.length) {
    hintParts('Сперва выдели на модели, что отделить');
    return;
  }
  await usePartsMaterial(sel.material);
  // Переключение могло не случиться (занято другим или Python ответил
  // ошибкой) - тогда номера треугольников ушли бы в ЧУЖОЙ материал
  if (P.material !== partsTarget(sel.material)) {
    hintParts('Не удалось перейти к материалу выделения - попробуй ещё раз');
    return;
  }
  hintParts('Отделяю…');
  const res = await api.addPartRegion(P.material, sel.triangles);
  if (res.error) { hintParts(res.error); return; }
  w.clearCutSelection();
  applyView(res);
  await refreshParts();
  hintParts(res.mirrored
    ? 'Отделено. Зеркальная половина отделилась вместе: у неё те же пиксели'
    : 'Отделено в новую часть. Вернуть - «−» на её чипе или Ctrl+Z');
}

export function resetCut() {
  const w = viewer();
  if (w && w.clearCutSelection) w.clearCutSelection();
}

//: Что делает щелчок каждым способом выделения - подсказка к нему
const CUT_HINTS = {
  detail: 'Щёлкай по модели: берётся гладкая поверхность до острых рёбер. '
        + 'Повторный щелчок снимает',
  brush: 'Веди по модели с зажатой кнопкой - выделяется всё под кистью. '
       + 'Мимо модели - крутит камеру',
  island: 'Щёлкай по модели: берётся остров развёртки целиком',
};

/** Блок выделенного - только когда оно есть, и подсказка по нему */
export function showCutCount(count) {
  document.getElementById('cut-sel').hidden = !count;
  document.getElementById('cut-count').textContent = t(`Выделено: ${count}`);
  if (!P.cutMode) return;
  hintParts(count
    ? `Выделено треугольников: ${count}. «Отделить» или Enter - в отдельную часть`
    : CUT_HINTS[cutOpts.tool]);
}

/** Способ выделения: у каждого свой ползунок, лишние прячем */
function setCutTool(name) {
  cutOpts.tool = name;
  document.querySelectorAll('#cut-modes [data-cut]').forEach((b) => {
    b.classList.toggle('is-active', b.dataset.cut === name);
  });
  document.getElementById('cut-angle-box').hidden = name !== 'detail';
  document.getElementById('cut-radius-box').hidden = name !== 'brush';
  document.getElementById('cut-erase-box').hidden = name !== 'brush';
  withViewer((w) => w.setCutOptions && w.setCutOptions(cutOpts));
  hintParts(CUT_HINTS[name]);
}

document.querySelectorAll('#cut-modes [data-cut]').forEach((b) => {
  b.addEventListener('click', () => setCutTool(b.dataset.cut));
});
document.getElementById('cut-angle').addEventListener('input', (e) => {
  cutOpts.angle = Number(e.target.value);
  withViewer((w) => w.setCutOptions && w.setCutOptions(cutOpts));
});
/**
 * Радиус кисти ножниц в долях размера модели по положению ползунка 0..100:
 * от 0,1% до 30%, логарифмически. Линейная шкала от 1% отдавала мелким
 * размерам крохотный ход, и на плотной сетке кисть всё равно брала много.
 */
const brushRadius = (v) => 0.001 * 300 ** (Number(v) / 100);
document.getElementById('cut-radius').addEventListener('input', (e) => {
  cutOpts.radius = brushRadius(e.target.value);
  withViewer((w) => w.setCutOptions && w.setCutOptions(cutOpts));
});
document.getElementById('cut-erase').addEventListener('change', (e) => {
  cutOpts.erase = e.target.checked;
  withViewer((w) => w.setCutOptions && w.setCutOptions(cutOpts));
});
document.getElementById('cut-apply').addEventListener('click', applyCut);
document.getElementById('cut-reset').addEventListener('click', resetCut);

/** Кнопка «−» на отрезанной части: вернуть её в кусок, из которого вырезали */
export function chunkStep(part, glyph, title) {
  const btn = document.createElement('button');
  btn.className = 'parts__cut';
  btn.type = 'button';
  btn.textContent = glyph;
  btn.title = t(title);
  btn.addEventListener('click', (e) => {
    e.stopPropagation();          // щелчок по чипу красит - здесь этого не надо
    uncutPart(part);
  });
  return btn;
}

/**
 * Режим резки
 *
 * Выключает покраску щелчком нарочно: иначе щелчок, которым режут кусок,
 * открывал бы ещё и выбор картинки. Один щелчок - один ответ
 *
 * Включает и выключает его САМ значок ножниц (см. showToolGroup): своей кнопки
 * у режима нет - два выключателя у одного режима рано или поздно разъезжаются,
 * и тогда один из них молча проигрывает.
 */
export function setCutMode(on) {
  P.cutMode = !!on;
  withViewer((w) => {
    if (w.setCutOptions) w.setCutOptions(cutOpts);
    if (w.setCutMode) w.setCutMode(P.cutMode);
  });
  showCutCount(0);
  if (P.cutMode) {
    hintParts('Выдели на модели, что отрезать, и нажми «Отделить». '
            + 'Щелчок по чипу берёт часть целиком - так части сводят в одну');
  } else {
    hintParts('');
  }
}
