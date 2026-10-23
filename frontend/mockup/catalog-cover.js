/*
 * Обложка карточки каталога: иконка из рюкзака или значок спец-режима
 *
 * Отдельно от каталога, потому что обложки нужны и выбору модели для точек
 * частиц (makePick), а загрузка иконок со своей очередью - отдельная забота.
 */

import * as api from './api.js';

/*
 * Обложки специальных режимов
 *
 * Иконки в рюкзаке у них нет и быть не может - спрей и эффекты смерти не
 * предметы, - а пустая рамка не отличала одну карточку от другой: пять
 * одинаковых квадратов, и узнать «Лёд» можно было только по подписи
 *
 * Рисунок живёт здесь, а не в разметке: карточки строит код, и значок
 * выбирается по ключу режима. Тот же приём, что у шестерёнки кадра
 * (preview-frames.js -> GEAR)
 *
 * Сетка 32, линия волосяная, заливка только у капель баллончика - как у всех
 * значков окна. Толщину задаёт CSS (`.pick__art`), потому что она не должна
 * расти вместе с обложкой: в плавающем каталоге та около 190 точек, а в
 * прибитой панели 26.
 */
const SPECIAL_ART = {
  // Крит - вспышка попадания: восемь лучей, центр пуст
  critHIT: '<path d="M16 2v7M16 23v7M2 16h7M23 16h7"/>'
         + '<path d="M6.2 6.2 11 11M21 21l4.8 4.8M25.8 6.2 21 11M11 21l-4.8 4.8"/>',
  // Спрей - единственный из пяти, что рисуют рукой: баллончик и три капли
  spray: '<path d="M11 11h9v18h-9z"/><path d="M13.5 7.5h4V11h-4z"/>'
       + '<path d="M11 15h9"/>'
       + '<circle class="pick__drop" cx="24" cy="6" r="1"/>'
       + '<circle class="pick__drop" cx="27.5" cy="3.5" r="1"/>'
       + '<circle class="pick__drop" cx="27" cy="8.5" r="1"/>',
  // Лёд - кристалл. Огранка нужна, чтобы он не путался со вспышкой крита:
  // снежинка из тех же лучей была бы на неё похожа
  death_ice: '<path d="M16 3 24 9.5 21.5 24 16 29 10.5 24 8 9.5Z"/>'
           + '<path d="M16 3v26M8 9.5 16 14l8-4.5"/>',
  // Золото - слиток. Блик обязателен: без него слиток читается коробкой
  death_gold: '<path d="M6 26h20l-3.5-9.5h-13Z"/><path d="M9.5 16.5h13"/>'
            + '<path d="M11.5 21.5h9"/>'
            + '<path d="M24 3 25.2 6.3 28.5 7.5 25.2 8.7 24 12 22.8 8.7 19.5 7.5 22.8 6.3Z"/>',
  // Огонь - язык пламени со внутренним: самый однозначный силуэт из пяти
  death_fire: '<path d="M16 2.5c5 5.5 7.5 9 7.5 13.5A7.5 7.5 0 0 1 8.5 16c0-3 '
            + '1.5-5.5 3.5-7.5 0 2.5 1 4 2.5 4.5-.5-4 .5-7.5 1.5-10.5Z"/>'
            + '<path d="M16 16.5c1.9 3 3.8 4.4 3.8 6.8 0 2.3-1.7 4-3.8 4s-3.8-1.7-3.8-4'
            + 'c0-2.4 1.9-3.8 3.8-6.8Z"/>',
};

/** Значок специального режима в обложку. Незнакомый режим - пустая рамка */
function specialArt(box, mode) {
  const art = SPECIAL_ART[mode];
  if (!art) return;
  box.insertAdjacentHTML('beforeend',
    '<svg class="pick__art" viewBox="0 0 32 32" aria-hidden="true">' + art + '</svg>');
}

//: Обложки приходят пачками (api.icons) и ставятся картинкам как blob-адреса.
//: Пока страницу крутят колесом, WebView2 придерживает каждый сетевой запрос
//: на сотни миллисекунд, и иконки по одной шли цепочкой: 13 штук за полторы
//: секунды прокрутки. Картинку из памяти он не держит, так что ждёт только
//: запрос пачки
//:
//: Просим иконки, пока карточка у окна. Запас - scrollMargin, а не
//: rootMargin: список прокручивается внутри своего контейнера, а rootMargin
//: расширяет только окно страницы, не обрезку контейнера
//:
//: Пачек в полёте не больше двух. У браузера шесть соединений на сервер, одно
//: держит поток событий, и вызовам API должно оставаться место. Холодную
//: иконку сервер декодирует 25-60 мс, поэтому пачка небольшая: видимые не
//: ждут, пока расшифруется весь запас
const BATCH = 16;
const IN_FLIGHT = 2;
let inFlight = 0;
const waiting = new Set();
//: blob-адрес по ключу иконки, null - в игре её нет. Держится весь сеанс:
//: WebView2 выбрасывает картинки снятой сетки из памяти, и без этого возврат
//: к уже виденному месту снова ждал бы сервер
//:
//: Не сам data-URL: под курсором страница отправляет процессу браузера адрес
//: картинки, и data-URL уходил целиком, двадцать килобайт на каждое движение
//: мыши. Браузер разбирал каждое сообщение по 11 мс и был занят на 95%, а
//: ответы сервера ждали за ним секундами
const known = new Map();

/** blob-адрес из data-URL пачки. Отзывать незачем: живёт до конца сеанса */
function toBlobUrl(dataUrl) {
  const bin = atob(dataUrl.slice(dataUrl.indexOf(',') + 1));
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return URL.createObjectURL(new Blob([bytes], { type: 'image/png' }));
}
//: Обложки на экране, пачка набирается с них. Кто виден, узнаём от
//: наблюдателя. getBoundingClientRect после каждой пришедшей иконки заставлял
//: бы браузер пересчитывать стили всей страницы, 4-5 мс на иконку
const onScreen = new Set();

//: Создаётся раньше iconLoader. Колбэки наблюдателей приходят в порядке
//: создания, и к первому pump() видимые уже отмечены. Иначе очередь начала бы
//: с запаса над окном
const screenWatch = new IntersectionObserver((entries) => {
  for (const { target: img, isIntersecting } of entries) {
    if (isIntersecting) onScreen.add(img);
    else onScreen.delete(img);
  }
  pump();
});

const iconLoader = new IntersectionObserver((entries) => {
  for (const { target: img, isIntersecting } of entries) {
    if (!isIntersecting) waiting.delete(img);
    else if (!img.getAttribute('src')) {
      if (known.has(img.dataset.key)) show(img);
      else waiting.add(img);
    }
  }
  pump();
}, { rootMargin: '300px 0px', scrollMargin: '900px 0px' });

//: Картинки, которым уже поставили адрес, но они ещё не загрузились. Это
//: тоже задачи загрузки, и в одной очереди с ними стоят вызовы API
const loading = new Set();

/** Отправляет пачки: сперва видимые, потом запас у окна */
function pump() {
  while (inFlight < IN_FLIGHT && waiting.size) {
    const want = new Map();
    const take = (img) => {
      const key = img.dataset.key;
      if (!want.has(key)) {
        if (want.size >= BATCH) return;
        want.set(key, []);
      }
      want.get(key).push(img);
    };
    for (const img of waiting) if (onScreen.has(img)) take(img);
    for (const img of waiting) if (!onScreen.has(img)) take(img);
    for (const imgs of want.values()) for (const img of imgs) waiting.delete(img);
    inFlight++;
    api.icons([...want.keys()]).then((got) => {
      for (const [key, imgs] of want) {
        known.set(key, got[key] ? toBlobUrl(got[key]) : null);
        for (const img of imgs) if (img.isConnected) show(img);
      }
    }, () => {
      // Пачка не дошла: картинки остаются пустыми рамками, а следующая
      // прокрутка попросит их снова
    }).finally(() => {
      inFlight--;
      pump();
    });
  }
}

/** Ставит картинке пришедшую иконку. Иконки в игре есть не у всего
 *  (стоковые ножи, часть праздничных) - тогда пустая рамка */
function show(img) {
  const url = known.get(img.dataset.key);
  if (url) {
    loading.add(img);
    img.src = url;
  } else {
    forget(img);
    img.remove();
  }
}

/** Снимает картинку со всех наблюдений */
function forget(img) {
  iconLoader.unobserve(img);
  screenWatch.unobserve(img);
  onScreen.delete(img);
}

/** Очищает сетку карточек */
export function clearCovers(grid) {
  dropCovers(grid);
  grid.replaceChildren();
}

/** Отпускает обложки внутри `root`, сам узел остаётся
 *
 *  Наблюдатель сам не отпускает удалённую картинку, если она в этот момент
 *  была за краем окна, и в нём копились бы отцепленные карточки. Из очереди
 *  тоже: смена фильтра просила бы иконки, которых на экране уже не будет
 *
 *  Начатую загрузку снимаем адресом: убранная картинка всё равно догружается,
 *  и при прокрутке колесом копился хвост загрузок уехавших карточек, за
 *  которым ждали вызовы API */
export function dropCovers(root) {
  for (const img of root.querySelectorAll('img.pick__icon')) {
    waiting.delete(img);
    if (loading.delete(img)) img.removeAttribute('src');
    forget(img);
  }
}

/** Кладёт в рамку `box` обложку предмета */
export function fillCover(box, item) {
  // Обложка: иконка из рюкзака, а у кого её нет - текстура самой модели
  // (см. api.icon_png). Грузится, только пока карточка у окна (iconLoader).
  // У частиц и спец-режимов картинки в игре нет вовсе - спрей и эффекты
  // смерти не предметы, и стучаться за 404 на каждую карточку незачем.
  // Спец-режимам обложку рисуем сами (см. SPECIAL_ART)
  const noIcon = item.type === 'particle' || item.type === 'special';
  const key = noIcon ? '' : (item.icon || item.key);
  // У спец-режима вместо картинки свой значок: что это за режим, видно на
  // обложке, а не только в подписи
  if (item.type === 'special') specialArt(box, item.mode);
  if (key) {
    const img = document.createElement('img');
    img.className = 'pick__icon';
    img.alt = '';
    img.decoding = 'async';
    img.addEventListener('error', () => {
      loading.delete(img);
      forget(img);
      img.remove();
    });
    img.addEventListener('load', () => {
      loading.delete(img);
      img.classList.add('is-loaded');
      forget(img);
    }, { once: true });
    img.dataset.key = key;
    screenWatch.observe(img);
    iconLoader.observe(img);
    box.appendChild(img);
  }
}
