/*
 * Карточки альбома: кадр на каждый материал, подписи и вкладки.
 */

import * as api from './api.js';
import { t } from './i18n.js';
import { stage } from './stage.js';
import { bindAlbum, goTo, SINGLE_TEX } from './album.js';
import { lastView } from './preview.js';

/**
 * Пустой кадр альбома
 *
 * Шестерёнка тут не для красоты: она переводит панель сборки в правку
 * настроек ЭТОГО материала (разрешение и формат бывают нужны свои - например
 * мелкой детали ни к чему 2048).
 */
//: Значок настроек кадра. Не шестерня U+2699: системный шрифт рисует её
//: сплошным пятном, чужим рядом с волосяными линиями. Две дорожки с ползунками -
//: та же толщина линии, что у рамок, и честнее по смыслу: за кнопкой параметры
//: сборки, а не механизм.
//: Рисуем 1:1 - единица `viewBox` равна точке экрана, а дорожки стоят на
//: половинах (4.5, 9.5). Линия толщиной 1 ложится тогда РОВНО в пиксельный
//: ряд, при 12 точках из шестнадцатеричной сетки она попадала между рядами и
//: размывалась неравномерно - значок выглядел косым
const GEAR = `<svg viewBox="0 0 14 14" width="14" height="14" fill="none"
                   stroke="currentColor" stroke-width="1" stroke-linecap="round"
                   aria-hidden="true">
                <path d="M1.5 4.5h11M1.5 9.5h11"/>
                <circle cx="4.5" cy="4.5" r="1.75" fill="var(--surface)"/>
                <circle cx="9.5" cy="9.5" r="1.75" fill="var(--surface)"/>
              </svg>`;

//: Какая картинка стояла на карточке при прошлой сборке альбома: проявляем
//: только сменившиеся, иначе каждое обновление состояния мигало бы всем рядом
const shownSrc = new Map();

/** <img> карточки, помечен `is-new`, если картинка не та, что была */
function frameImage(name, png) {
  const img = document.createElement('img');
  img.src = api.opaqueUrl(png);
  img.alt = name;
  if (shownSrc.get(name) !== img.src) img.classList.add('is-new');
  shownSrc.set(name, img.src);
  return img;
}

export function frameNode(name) {
  const fig = document.createElement('figure');
  fig.className = 'frame';
  fig.dataset.mat = name;
  fig.innerHTML = `<div class="frame__img">
                     <div class="frame__tools">
                       <button class="frame__tool" type="button"
                               title="Настройки этой текстуры">${GEAR}</button>
                       <button class="frame__tool frame__off" type="button" hidden
                               title="Убрать материал из стиля">×</button>
                     </div>
                   </div>
                   <figcaption class="frame__name"></figcaption>`;
  return fig;
}

/** Добавляет один кадр в конец альбома, не трогая остальные */
export function addFrame(name, png) {
  const tab = document.createElement('button');
  tab.className = 'mattab';
  tab.textContent = name;
  stage.tabs.appendChild(tab);

  const fig = frameNode(name);
  fig.querySelector('.frame__name').textContent = name;
  fig.querySelector('.frame__img').appendChild(frameImage(name, png));
  stage.album.appendChild(fig);

  bindAlbum();
  goTo(frames.length - 1);        // сразу показываем то, что построили
}

//: {имя_карточки: подпись} - мод из VPK называет текстуры по VTF, а человеку
//: показывает понятное имя. Пусто у обычных моделей
export let cardTitles = {};

/** Подписи карточек мода из VPK: он называет текстуры по VTF, а человеку
 *  показывает понятное имя */
export function setCardTitles(titles) { cardTitles = titles; }

/** Как подписать карточку: служебный ключ и имена мода - особые случаи */
export function cardTitle(name) {
  if (name === SINGLE_TEX) return 'текстура';
  // Карточка гирлянды: `deco:<вид>/<материал>` - вид подписью, материал как есть
  const decor = /^deco:([^/]+)\/(.+)$/.exec(name || '');
  if (decor) return t('Гирлянда: {}').replace('{}', decor[2]);
  // Карточка варианта встаёт на место главной, пока он включён: подпись
  // называет вариант, а не материал - имя материала есть в подсказке
  if (/_(gold|australium)$/i.test(name)) return 'Australium';
  // Материал части: номер тот же, что метка на её чипах в списке частей;
  // имя материала (оно нужно для VMT) - в подсказке
  for (const spec of Object.values(lastView?.part_materials || {})) {
    const at = (spec.parts || []).findIndex((p) => p.name === name);
    if (at >= 0) return t('Материал части {}').replace('{}', at + 1);
  }
  return cardTitles[name] || name;
}

/** Перерисовывает вкладки и альбом под материалы, пришедшие от воркера */
export function showMaterials(names, textures = {}, inStyle = false) {
  stage.tabs.innerHTML = '';
  stage.album.innerHTML = '';

  for (const name of names) {
    const tab = document.createElement('button');
    tab.className = 'mattab';
    tab.textContent = cardTitle(name);
    stage.tabs.appendChild(tab);
    // Убрать из стиля можно только то, что в стиль добавляли

    const fig = frameNode(name);
    const png = textures[name];
    // Служебный ключ одноматериальной модели показывать как имя нельзя
    const label = fig.querySelector('.frame__name');
    label.textContent = cardTitle(name);
    // Подпись бывает не именем материала (вариант): имя - в подсказке
    if (name !== SINGLE_TEX && label.textContent !== name) label.title = name;
    if (png) fig.querySelector('.frame__img').appendChild(frameImage(name, png));
    fig.querySelector('.frame__off').hidden = !inStyle;
    stage.album.appendChild(fig);
  }
  bindAlbum();
}
