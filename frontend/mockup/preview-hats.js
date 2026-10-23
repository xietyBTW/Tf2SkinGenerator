/*
 * Шапки в превью: покласcовые модели и модельные стили.
 */

import * as api from './api.js';
import { say, sayError } from './stage.js';
import { work } from './layout.js';
import { tauntClass, wearSlot } from './preview-scenes.js';

/** Покласcовые модели шапки: у стилевой они в стиле, у обычной - в предмете */
export function hatModels(item, index) {
  if (!item) return null;
  const style = ((item.styles || [])[index] || {}).per_class;
  const own = item.per_class;
  const models = (style && Object.keys(style).length) ? style : own;
  return (models && Object.keys(models).length) ? models : null;
}

//: Классы мультиклассовой шапки (у каждого своя модель). Для кого собирать,
//: спрашивает сборка (build.js) - отдельная строка кнопок перегружала экран
let hatClassList = [];

export function showHatClasses(item) {
  hatClassList = Object.keys((item && item.per_class) || {});
}

/** Классы показанной шапки, пусто - шапка не мультиклассовая */
export function hatClasses() {
  return hatClassList.length > 1 ? [...hatClassList] : [];
}

/**
 * Модельные стили шапки
 *
 * Это не skinfamilies: у стиля СВОЯ геометрия («Только камень» - та же шапка
 * без оправы), поэтому выбор перезагружает превью другой моделью и меняет то,
 * что уйдёт в сборку.
 */
export function showHatStyles(item, active = 0) {
  const bar = document.getElementById('hatstyles');
  bar.querySelectorAll('.tag').forEach((b) => b.remove());
  const styles = (item && item.styles) || [];
  bar.hidden = styles.length < 2;
  if (bar.hidden) return;

  styles.forEach((style, index) => {
    const b = document.createElement('button');
    b.className = 'tag' + (index === active ? ' is-active' : '');
    b.dataset.style = index;
    b.textContent = style.name;
    b.addEventListener('click', async () => {
      bar.querySelectorAll('.tag').forEach(
        (x) => x.classList.toggle('is-active', x === b));
      const models = hatModels(item, index) || {};
      showHatClasses({ per_class: models });
      const first = Object.values(models)[0] || item.key;
      say(`Загрузка стиля: ${style.name}…`);
      // Индекс нужен сеансу: по нему он и запоминает правки стиля, и понимает,
      // что это стиль ТОЙ ЖЕ шапки, а не новый предмет
      const res = await api.loadPreview('hat', null, first, models, index,
                                        false, item.key);
      if (res.error) { sayError(res.error); return; }
      markEditedStyles(res.edited_styles);
      // На «На персонаже» сцену надо собрать заново: загрузка стиля её погасила
      // (session.load_preview -> taunt.stop), а без пересборки на персонаже
      // оставался последний кадр прежнего стиля. Модели нового стиля сеанс
      // к этому моменту уже знает
      if (work.dataset.scene === 'wear') {
        const again = await api.loadWear(tauntClass, wearSlot);
        if (again.error) sayError(again.error);
      }
    });
    bar.appendChild(b);
  });
}

/**
 * Метка «стиль правлен»
 *
 * Правки соседних стилей уходят в тот же мод, и без метки о них вспоминают
 * уже в игре. Имя стиля берём из кнопки - список стилей здесь не нужен.
 */
export function markEditedStyles(indexes) {
  const edited = new Set((indexes || []).map(Number));
  document.querySelectorAll('#hatstyles .tag').forEach((b) => {
    const name = b.textContent.replace(/ ●$/, '');
    b.textContent = edited.has(Number(b.dataset.style)) ? name + ' ●' : name;
  });
}
