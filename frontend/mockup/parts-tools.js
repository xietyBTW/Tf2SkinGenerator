/*
 * Инструменты режима частей: колонка значков (картинка, кисть, пипетка,
 * ножницы, окантовка, материал), курсор инструмента и пипетка по кадру слева.
 */

import { t } from './i18n.js';
import { stage, withViewer } from './stage.js';
import { pickInto, armDrop } from './picker.js';
import { colorAt } from './sample.js';
import { P, hintParts } from './parts-state.js';
import { setCutMode } from './parts-cut.js';
import { colorField } from './parts-palette.js';

//: Как называется выбранный значок. Значок без слова запоминается со второго
//: раза, а не с первого, поэтому имя стоит над его настройками
const TOOL_NAMES = { image: 'Картинка', brush: 'Кисть', pick: 'Пипетка',
                     cut: 'Нарезка', edge: 'Окантовка', material: 'Материал' };

//: У кого есть значок-приставка к курсору. Курсору («положить картинку») и
//: ножницам она не нужна: у первого дело и есть «показать», у вторых
//: перекрестие само говорит про разрез
const TOOL_BADGE = new Set(['brush', 'pick', 'edge', 'material']);

/**
 * Значок инструмента из разметки: одна копия рисунка на всё приложение
 *
 * Ищем по всей палитре, а не в колонке: у пипетки кнопка стоит в самом выборе
 * цвета - там, где цвет и подбирают.
 */
function toolIcon(name) {
  return document.querySelector('#partspaint [data-tool="' + name + '"] svg');
}

/**
 * Курсор: САМА СТРЕЛКА плюс значок дела у неё справа-снизу
 *
 * Стрелка остаётся, потому что она показывает ТОЧКУ - по ней целятся в кусок
 * размером с винтик, и значок вместо неё отнимал бы прицел. Значок только
 * называет дело, поэтому висит сбоку и острия не имеет
 *
 * Рисунки берём из разметки, а не повторяем их здесь: две копии одного значка
 * расходятся, и курсор начинает обещать не тот инструмент, что горит в
 * колонке. Стрелка - тот же значок «курсор», только залитый белым
 *
 * Тёмный контур под светлым: курсор ходит и по белой текстуре, и по чёрной, и
 * однотонный на одной из них исчезает.
 */
function toolCursor(name) {
  if (!TOOL_BADGE.has(name)) return '';
  const badge = toolIcon(name);
  const arrow = toolIcon('image');
  if (!badge || !arrow) return '';
  const art = '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"'
    + ' viewBox="0 0 32 32" fill="none" stroke-linecap="round"'
    + ' stroke-linejoin="round">'
    + '<g transform="translate(-3.4 -2.2) scale(1.5)" fill="#fff" stroke="#000"'
    + ' stroke-width=".9">' + arrow.innerHTML + '</g>'
    + '<g transform="translate(16 15)">'
    + '<g stroke="#000" stroke-width="2.6" opacity=".55">' + badge.innerHTML + '</g>'
    + '<g stroke="#fff" stroke-width="1.2">' + badge.innerHTML + '</g></g></svg>';
  // Острие - у стрелки, в её собственном кончике: значок сбоку ничего не
  // показывает, и «горячей точкой» ему быть нельзя
  return 'url("data:image/svg+xml,' + encodeURIComponent(art) + '") 1 1, auto';
}

/**
 * Показывает инструмент курсором - там, где он работает
 *
 * Вьювер знает про инструмент ровно две вещи: каким курсором показать и надо
 * ли брать цвет вместо покраски, - поэтому одна передача, а не две.
 * Пипетка работает и по кадру слева, и курсор ей нужен там же, остальные
 * инструменты кадра не касаются, и обещать над ним кисть было бы враньём
 *
 * Здесь же взводится пипетка у поповера выбора цвета: владелец этого
 * состояния один - выбранный инструмент, иначе кнопка в палитре и значок в
 * колонке разъехались бы.
 */
function showToolCursor(name) {
  const css = toolCursor(name);
  withViewer((w) => w.setPartsTool && w.setPartsTool(name || '', css));
  stage.album.style.cursor = name === 'pick' ? css : '';
  armDrop(name === 'pick');
}

/**
 * Какой инструмент выбран: кисть, пипетка, ножницы или окантовка
 *
 * Настройки видны только у него: человек в момент времени делает что-то одно,
 * а показ всего разом давал четыре строки под моделью - с «Толщиной»,
 * оторванной переносом от своей же «Окантовки»
 *
 * Ножницы - это и есть режим резки: выбрал значок, и щелчок по модели режет.
 * Уход с них его гасит, иначе щелчок молча делал бы не то, что показано.
 */
export function showToolGroup(name) {
  P.tool = name;
  document.querySelectorAll('.ptools__btn[data-tool]').forEach((b) => {
    b.classList.toggle('is-active', b.dataset.tool === name);
  });
  let shown = false;
  document.querySelectorAll('.parts__group').forEach((g) => {
    g.hidden = g.dataset.group !== name;
    shown = shown || !g.hidden;
  });
  // У картинки настроек нет: пустая панель с одним заголовком закрывала бы
  // кадр, ничего не сообщая
  document.getElementById('parts-opts').hidden = !shown;
  document.getElementById('parts-tool').textContent = t(TOOL_NAMES[name] || '');
  showToolCursor(name);
  if ((name === 'cut') !== P.cutMode) setCutMode(name === 'cut');
  if (name === 'image') {
    hintParts('Щёлкай по частям модели или тащи на них картинку - она ляжет '
            + 'на кусок');
  }
  if (name === 'pick') {
    hintParts('Зажми на модели или на текстуре - цвет виден под курсором, '
            + 'а берётся там, где отпустишь');
  }
  // Про Alt говорим у кисти: пипетка в палитре, и найти её оттуда - два
  // движения, а посреди покраски цвет подбирают чаще всего
  if (name === 'brush') {
    hintParts('Щёлкай по частям - покрасятся. Alt при щелчке берёт цвет '
            + 'с модели или с текстуры');
  }
  if (name === 'material') {
    hintParts('Щёлкай по частям: они уйдут в выбранный материал, повторный '
            + 'щелчок вернёт часть в общий');
  }
}

/**
 * Пипетка: взятый цвет становится цветом кисти
 *
 * Через то же поле, что и выбор цвета: у кисти цвет живёт в нём, и второй
 * путь к нему разъехался бы с первым - задним квадратом градиента и открытым
 * поповером. `pickInto` нужен затем, что цвет могли брать при открытом
 * выборе: щелчок по модели идёт внутри iframe, и поповер остаётся на месте.
 */
export function takeColor(hex) {
  if (!hex) return;
  const field = colorField();
  field.value = hex;
  field.dispatchEvent(new Event('input', { bubbles: true }));
  pickInto(field);
  hintParts(`Взят цвет ${hex}`);
}

/**
 * Берут ли этим щелчком цвет
 *
 * Alt при кисти - пипетка «на минуту»: так это устроено в редакторах
 * изображений. Держать её отдельным инструментом ради одного цвета значит
 * дважды сходить за значком, а подбирают цвет как раз посреди покраски
 *
 * Решает НАЧАЛО протяжки: Alt, отпущенный по дороге, цвет не отменяет - рука
 * уже ведёт пипетку, и обрывать её на полпути было бы неожиданно.
 */
const sampling = (e) => P.tool === 'pick' || (e.altKey && P.tool === 'brush');

/**
 * Образец под пипеткой: цвет пикселя, на котором стоит курсор
 *
 * Один на страницу и на вьювер. В 3D цвет берут внутри iframe, но рисовать
 * образец там значило бы держать вторую копию этого окошка - а вьювер про
 * палитру ничего не знает и знать не должен. Пустой цвет убирает образец:
 * курсор ушёл с модели, и показывать нечего.
 */
let spot = null;

export function showSample(hex, x, y) {
  if (!spot) {
    spot = document.createElement('div');
    spot.className = 'pickspot';
    spot.innerHTML = '<i></i><b></b>';
    document.body.appendChild(spot);
  }
  spot.hidden = !hex;
  if (!hex) return;
  spot.querySelector('i').style.background = hex;
  spot.querySelector('b').textContent = hex;
  // Справа-снизу от курсора, как подсказка, у края окна - по другую сторону,
  // иначе образец уезжает за экран ровно там, где текстура и кончается
  const box = spot.getBoundingClientRect();
  spot.style.left = Math.min(x + 18, window.innerWidth - box.width - 6) + 'px';
  spot.style.top = Math.min(y + 18, window.innerHeight - box.height - 6) + 'px';
}

/**
 * Пипетка по кадру слева - с зажатой кнопкой, как в редакторах изображений
 *
 * Цвет видно, пока держат, и он берётся там, где отпустили: попасть в нужный
 * пиксель с первого щелчка нельзя - на кадре 2048 точек текстуры сжаты до
 * четырёхсот, и соседние пиксели там разного цвета
 *
 * Всё в фазе перехвата: у кадра свой щелчок, он листает альбом, - и без этого
 * пипетка сперва уводила бы текстуру из-под курсора.
 */
(function bindFramePick() {
  const album = stage.album;
  let img = null;          // картинка, с которой сейчас берут цвет

  const sample = (e) => {
    const hex = img ? colorAt(img, e.clientX, e.clientY) : '';
    showSample(hex, e.clientX, e.clientY);
    return hex;
  };

  const stop = (e) => {
    if (album.hasPointerCapture(e.pointerId)) album.releasePointerCapture(e.pointerId);
    img = null;
    showSample('');
  };

  album.addEventListener('pointerdown', (e) => {
    if (!sampling(e)) return;
    const box = e.target.closest('.frame__img');
    // Не `img` вообще: поверх текстуры лежит подсветка части (`.frame__uv`), и
    // цвет надо брать из самой текстуры, а не из разметки над ней
    img = box && box.querySelector('img:not(.frame__uv)');
    if (!img) return;
    e.preventDefault();     // иначе кадр уезжает перетаскиванием картинки
    album.setPointerCapture(e.pointerId);
    sample(e);
  }, true);

  album.addEventListener('pointermove', (e) => { if (img) sample(e); }, true);

  album.addEventListener('pointerup', (e) => {
    if (!img) return;
    const hex = sample(e);
    stop(e);
    takeColor(hex);         // пустой - отпустили мимо текстуры, и брать нечего
  }, true);

  album.addEventListener('pointercancel', (e) => { if (img) stop(e); }, true);

  album.addEventListener('click', (e) => {
    if (sampling(e)) e.stopPropagation();
  }, true);
})();

// Пипетка в палитре - обычный инструмент: кнопка его выбирает, а подсветку ей
// ставит showToolGroup по `data-tool`, как значкам в колонке. Повторный щелчок
// её снимает - иначе выйти из пипетки можно было бы только через другой
// инструмент, а вернуться к покраске хочется тем же движением
document.getElementById('parts-drop').addEventListener('click',
  () => showToolGroup(P.tool === 'pick' ? null : 'pick'));

document.querySelector('.ptools__bar').addEventListener('click', (e) => {
  const btn = e.target.closest('[data-tool]');
  if (btn) showToolGroup(btn.dataset.tool);
});
