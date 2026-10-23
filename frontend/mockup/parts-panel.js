/*
 * Панель частей двигают за заголовок и тянут за угол
 *
 * Размер - штатный `resize` (уголок справа снизу), место - своей тягой: у
 * браузера её нет. Сетка внутри перекладывается сама (`auto-fill`), лишнее
 * по высоте прокручивается. Место и размер помнятся - это удобство одного
 * человека на одной машине, поэтому localStorage, и без него всё работает.
 * Двойной щелчок по заголовку возвращает панель на место.
 */

(function bindPartsPanel() {
  const bar = document.getElementById('partsbar');
  const head = bar.querySelector('.parts__head');
  const KEY = 'tf2sg.partsPanel';
  const save = () => {
    try {
      localStorage.setItem(KEY, JSON.stringify({
        left: bar.style.left, top: bar.style.top,
        width: bar.style.width, height: bar.style.height }));
    } catch (e) { /* приватный режим - просто не запомним */ }
  };
  try {
    const was = JSON.parse(localStorage.getItem(KEY) || 'null');
    if (was) Object.assign(bar.style, was);
  } catch (e) { /* испорченная запись - панель на месте по умолчанию */ }

  // Не дальше краёв кадра: иначе заголовок уехал бы туда, откуда его не
  // достать, - например после того, как окно сузили
  const clamp = (left, top) => {
    const box = bar.offsetParent;
    if (!box) return [left, top];
    return [Math.max(0, Math.min(left, box.clientWidth - bar.offsetWidth)),
            Math.max(0, Math.min(top, box.clientHeight - bar.offsetHeight))];
  };
  bar.addEventListener('parts:shown', () => {
    if (!bar.style.left) return;
    const [left, top] = clamp(bar.offsetLeft, bar.offsetTop);
    bar.style.left = left + 'px';
    bar.style.top = top + 'px';
  });

  let drag = null;
  head.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    drag = { x: e.clientX, y: e.clientY, left: bar.offsetLeft, top: bar.offsetTop };
    head.setPointerCapture(e.pointerId);
  });
  head.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const [left, top] = clamp(drag.left + e.clientX - drag.x, drag.top + e.clientY - drag.y);
    bar.style.left = left + 'px';
    bar.style.top = top + 'px';
  });
  const finish = (e) => {
    if (!drag) return;
    drag = null;
    if (head.hasPointerCapture(e.pointerId)) head.releasePointerCapture(e.pointerId);
    save();
  };
  head.addEventListener('pointerup', finish);
  head.addEventListener('pointercancel', finish);
  head.addEventListener('dblclick', () => {
    ['left', 'top', 'width', 'height'].forEach((k) => { bar.style[k] = ''; });
    try { localStorage.removeItem(KEY); } catch (e) { /* нечего забывать */ }
  });
  // Размер меняет браузер (уголок `resize`): запоминаем, когда он его задал
  new ResizeObserver(() => { if (bar.style.width || bar.style.height) save(); })
    .observe(bar);
})();
