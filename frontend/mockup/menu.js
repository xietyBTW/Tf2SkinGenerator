/*
 * Контекстное меню по правой кнопке.
 *
 * Список пунктов даёт вызывающий — модуль решает только, где меню встанет и
 * как закроется. Пункт со значением null рисуется разделителем.
 */

// ── Контекстные меню ─────────────────────────────────────────────────────
// Как в панели приложения: набор пунктов зависит от того, на чём щёлкнули.
// Правая кнопка на системе даёт одно, на модуле — другое, на параметре —
// третье. Разделитель — пункт со значением null.

const menuEl = document.createElement('div');
menuEl.className = 'menu__list ctx';
menuEl.hidden = true;
document.body.append(menuEl);

/** Показывает меню в точке события; отдаёт значение пункта или null. */
export function contextMenu(e, items) {
  e.preventDefault();
  menuEl.innerHTML = '';
  return new Promise((resolve) => {
    const close = (value) => {
      menuEl.hidden = true;
      document.removeEventListener('mousedown', onAway, true);
      document.removeEventListener('keydown', onKey, true);
      resolve(value);
    };
    const onAway = (ev) => { if (!menuEl.contains(ev.target)) close(null); };
    const onKey = (ev) => { if (ev.key === 'Escape') close(null); };

    for (const item of items) {
      if (!item) {
        const hr = document.createElement('div');
        hr.className = 'ctx__sep';
        menuEl.append(hr);
        continue;
      }
      const b = document.createElement('button');
      b.className = 'menu__item';
      b.type = 'button';
      b.textContent = item.label;
      b.disabled = Boolean(item.disabled);
      b.addEventListener('click', () => close(item.value));
      menuEl.append(b);
    }

    menuEl.hidden = false;
    // Меню не должно уезжать за край: у нижних строк дерева места вниз нет.
    const box = menuEl.getBoundingClientRect();
    const x = Math.min(e.clientX, innerWidth - box.width - 8);
    const y = Math.min(e.clientY, innerHeight - box.height - 8);
    menuEl.style.left = Math.max(8, x) + 'px';
    menuEl.style.top = Math.max(8, y) + 'px';

    document.addEventListener('mousedown', onAway, true);
    document.addEventListener('keydown', onKey, true);
  });
}
