/*
 * Раскладка окна: три панели, каталог и правая панель раздела.
 *
 * Единственная настройка, меняющая раскладку, — «прибить панели». Всё
 * остальное здесь про видимость: что показано в плавающем режиме, а что в
 * прибитом. Ниже 1100 px прибитый режим не помещается и выключается
 * принудительно — честнее сказать «не влезает», чем показать сломанный экран.
 */

import * as api from './api.js';
import { t } from './i18n.js';

export const root = document.documentElement;
export const catalog = document.getElementById('catalog');
//: Половина сцены: слева текстуры, справа модель. Что из них видно,
//: переключают «Текстура / Модель / Вместе».
export const work = document.querySelector('.work');
export const build = document.getElementById('build');
//: Правая панель раздела частиц: крутилки эффекта вместо параметров VTF.
export const pbuild = document.getElementById('pbuild');
export const plist = document.getElementById('plist');
export const pnote = document.getElementById('pnote');

/** Какая из правых панелей сейчас в деле. */
export function panel() {
  return root.dataset.section === 'particles' ? pbuild : build;
}

/** Показывает панель своего раздела; вторая скрыта всегда.
 *  Отдельно от applyPanels: смена раздела не должна закрывать каталог. */
export function applyRightPanel() {
  const particlesSection = root.dataset.section === 'particles';
  const pinned = root.dataset.panels === 'pinned';
  build.hidden = particlesSection || !pinned;
  // Крутилки эффекта нужны РЯДОМ с эффектом, а не по вызову: правку смотрят
  // тут же, в кадре. Поэтому в этом разделе панель открыта всегда.
  pbuild.hidden = !particlesSection;
}

// ── Панели: прибиты к краям или вызываются поверх ────────────────────────
// Единственная настройка, которая меняет раскладку. Каталог и параметры
// нарисованы по одному разу; здесь только их видимость в плавающем режиме —
// в прибитом они видны всегда.

// Ниже этого порога три прибитые панели в строку не встают — они налезали бы
// друг на друга. Режим тогда принудительно плавающий, а кнопка гаснет: честнее
// сказать «не помещается», чем показать сломанный экран.
const narrow = matchMedia('(max-width: 1100px)');

//: Выбор пользователя. Хранится ОТДЕЛЬНО от действующего режима, иначе узкое
//: окно затирало бы его: сузил, вернул — а панели не вернулись.
let wantPinned = false;

function applyPanels() {
  const pinned = wantPinned && !narrow.matches;
  root.dataset.panels = pinned ? 'pinned' : 'float';
  // В прибитом режиме оба блока на экране всегда; в плавающем их показывают
  // по требованию, поэтому в покое они скрыты.
  catalog.hidden = !pinned;
  applyRightPanel();

}

/**
 * Закрепить панели или отпустить. Значение приходит из настроек и там же
 * хранится: кнопкой в шапке оно не переживало перезапуск, а раскладка — не то,
 * что хочется выбирать заново каждый раз.
 */
export function setPinned(on) {
  wantPinned = Boolean(on);
  applyPanels();
}

/** Влезают ли прибитые панели в это окно. Узкому окну их не предлагаем. */
export function pinnedFits() {
  return !narrow.matches;
}

// Слушаем и медиазапрос, и resize: change у MediaQueryList приходит не во
// всех окружениях (проверено — в эмулированном вьюпорте не пришёл), а
// applyPanels идемпотентна, лишний вызов ничего не стоит.
narrow.addEventListener('change', applyPanels);
addEventListener('resize', applyPanels);
applyPanels();

// ── Каталог: вошёл, выбрал, вышел ───────────────────────────────────────
export const floating = () => root.dataset.panels === 'float';
export const openCat = () => {
  if (!floating()) return;          // прибитый каталог и так на экране
  catalog.hidden = false;
  catalog.querySelector('.catalog__search').focus();
};
export const closeCat = () => { if (floating()) catalog.hidden = true; };

document.getElementById('opencat').addEventListener('click', openCat);
document.getElementById('closecat').addEventListener('click', closeCat);

// ── Параметры сборки ────────────────────────────────────────────────────
document.getElementById('opensettings').addEventListener('click', () => {
  if (floating()) { const el = panel(); el.hidden = !el.hidden; }
});

// Поле гаммы имеет смысл только когда она включена.
const gamma = document.getElementById('gamma');
gamma.addEventListener('change', () => {
  document.getElementById('gammaval').disabled = !gamma.checked;
});

/** Строка состояния внизу окна; занятость гасит кнопку сборки. */
/**
 * Разворот кадра на всё окно и обратно.
 *
 * Эффект частиц смотрят целиком, а на обычном экране под него отведена
 * половина. Прячем всё, кроме сцены: каталог, панели, альбом, шапку и низ.
 * Выход — тем же F11 или Esc, как в окне приложения.
 */
export function toggleExpanded(on) {
  const want = on === undefined ? root.dataset.expanded !== '1' : Boolean(on);
  if (want) root.dataset.expanded = '1';
  else delete root.dataset.expanded;
  // Вьювер живёт в iframe и о смене размера сам не узнает.
  const frames = [document.getElementById('viewer'),
                  document.getElementById('particles')];
  for (const f of frames) {
    const w = f && f.contentWindow;
    if (w && typeof w.resize === 'function') w.resize();
  }
}

document.addEventListener('keydown', (e) => {
  if (e.key === 'F11') { e.preventDefault(); toggleExpanded(); return; }
  // Esc сворачивает только развёрнутое: в обычном виде он закрывает окна и
  // меню, и перехватывать его здесь нельзя.
  if (e.key === 'Escape' && root.dataset.expanded === '1') {
    e.stopPropagation();
    toggleExpanded(false);
  }
}, true);

export function setStatus(text, busy) {
  document.querySelector('.dock__state').textContent = text;
  // Пока идёт сборка, кнопка сборки уступает место отмене: собрать второй раз
  // всё равно нельзя, а бросить начатое — надо.
  const build = document.getElementById('buildvpk');
  const stop = document.getElementById('buildstop');
  build.disabled = Boolean(busy);
  build.hidden = Boolean(busy);
  stop.hidden = !busy;
}

/**
 * Подпись внизу: где найдена игра.
 *
 * Не украшение — без пути к TF2 не работает ничего, и узнать об этом лучше
 * сразу, а не по ошибке на первой же загрузке модели.
 */
export async function showTf2Path() {
  const el = document.querySelector('.dock__tf2');
  const paths = await api.call('tf2_paths');
  if (paths.error) { el.textContent = 'TF2 не найдена — укажите папку игры в настройках'; return; }
  // Crowbar — вторая обязательная половина: без него модель не разобрать, а
  // узнать об этом раньше было можно только по ошибке сборки.
  // Через t(): строка собирается из трёх кусков, и целиком её в словаре не
  // найти — переводим каждый кусок отдельно.
  el.textContent = t('TF2 найдена · ') + paths.root
    + (paths.crowbar ? t(' · Crowbar готов') : t(' · Crowbar НЕ НАЙДЕН'));
}
