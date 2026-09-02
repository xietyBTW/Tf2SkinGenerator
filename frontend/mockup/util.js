/*
 * Мелочи, которыми пользуются все части страницы.
 *
 * Сюда попадает только то, что ничего не знает ни о каталоге, ни о превью, ни
 * о частицах: подсветка выбранного в ряду, экранирование, склонение, чтение
 * картинки, выбор файла. Всё остальное живёт в своём модуле — иначе util
 * превращается в свалку, куда стекается общее состояние.
 */

/** Делает элементы внутри контейнера взаимоисключающими. */
export function groupIn(root, itemSelector) {
  if (!root) return;
  root.addEventListener('click', (e) => {
    const target = e.target.closest(itemSelector);
    if (!target || !root.contains(target)) return;
    root.querySelectorAll(itemSelector).forEach((el) => el.classList.remove('is-active'));
    target.classList.add('is-active');
  });
}

/** То же по селектору контейнера. */
export function group(selector, itemSelector) {
  groupIn(document.querySelector(selector), itemSelector);
}

//: Кавычки экранируем наравне со скобками: тот же текст уходит в атрибут
//: title, и незакрытая кавычка ломала бы разметку зеркала.
export const escapeHtml = (text) => String(text).replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;',
            '"': '&quot;', "'": '&#39;' }[c]));

export function fillSelect(id, options, value) {
  const el = document.getElementById(id);
  el.innerHTML = '';
  for (const o of options) el.append(new Option(o.label ?? o, o.value ?? o));
  el.value = value;
}

/** Размер файла человеческим языком: точность тут не нужна, порядок — да. */
export function fileSize(bytes) {
  const mb = bytes / (1024 * 1024);
  return mb >= 1 ? mb.toFixed(1) + ' МБ' : Math.max(1, Math.round(bytes / 1024)) + ' КБ';
}

/** Русское склонение по числу: 1 часть, 2 части, 5 частей. */
export function plural(n, one, few, many) {
  const t = n % 100;
  if (t >= 11 && t <= 14) return many;
  const d = n % 10;
  return d === 1 ? one : (d >= 2 && d <= 4 ? few : many);
}

export function loadImage(src) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = src;
  });
}

//: Скрытый выбор файла — один на все карточки.
const pickFile = document.createElement('input');
pickFile.type = 'file';
pickFile.accept = 'image/*';
pickFile.hidden = true;
document.body.append(pickFile);

export function chooseFile(accept = 'image/*') {
  return new Promise((resolve) => {
    pickFile.value = '';
    pickFile.accept = accept;
    pickFile.onchange = () => resolve(pickFile.files[0] || null);
    pickFile.click();
  });
}

export const chooseImage = () => chooseFile('image/*');
