/*
 * Точка входа страницы.
 *
 * Здесь нет логики — только сборка целого из модулей и старт. Каждый модуль
 * сам вешает свои обработчики при загрузке, поэтому порядок импортов задаёт
 * порядок подключения, а не порядок работы.
 *
 * Карта модулей (снизу вверх, от «ничего не знает» к «знает всё»):
 *
 *   api        мост к Python: единственное место, знающее о транспорте
 *   curve      кривая ползунка — порт services/simple_params
 *   util       мелочи: экранирование, склонение, выбор файла
 *   ask menu   окно вопроса и контекстное меню
 *   picker     свой выбор цвета вместо системного диалога Windows
 *   stage      кадр: вьювер моделей и движок частиц в своих iframe
 *   layout     раскладка окна, панели, строка состояния
 *   album      альбом текстур: кадры, вкладки, прокрутка
 *   catalog    левая панель: списки, фильтры, выбор предмета
 *   controls   что показывать при режиме + правка настроек материала
 *   preview    показ предмета: модель, текстуры, команды, стили
 *   parts      покраска кусков геометрии
 *   place      посадка картинки на часть
 *   particles  раздел эффектов: дерево систем, свойства, превью
 *   maps vmt   диалоги материала
 *   custom-model settings diagnostics tools build log   остальное окно
 *   events     поток событий от воркеров — он и оживляет всё вышеперечисленное
 */

import { group } from './util.js';
import './picker.js';
import './dropdown.js';
import './layout.js';
import './album.js';
import './controls.js';
import './preview.js';
import './parts.js';
import './place.js';
import './particles/index.js';
import './maps.js';
import './vmt.js';
import './custom-model.js';
import './settings.js';
import './diagnostics.js';
import './build.js';
import './tools.js';
import './events.js';
import { boot, els } from './catalog.js';
import { syncViewerTheme } from './log.js';
import { say } from './stage.js';

/*
 * Последняя сеть под всеми обработчиками.
 *
 * Обработчики кнопок асинхронные, а `api.call` бросает на ошибке Python и на
 * обрыве связи. Непойманное такой обработчик хоронил молча: кнопка просто не
 * срабатывала, а текст оставался в журнале — который может быть и закрыт.
 * Пусть лучше человек увидит, что именно сломалось.
 */
const shout = (err) => {
  const text = (err && err.message) || String(err || 'неизвестная ошибка');
  say(text);
  console.error(err);
};
window.addEventListener('unhandledrejection', (e) => shout(e.reason));
window.addEventListener('error', (e) => {
  // Не загрузилась картинка или иконка — это не поломка страницы: карточки
  // такие случаи разбирают сами (иконки предмета в игре может не быть).
  if (e.target && e.target !== window) return;
  shout(e.error || e.message);
});

// Взаимоисключающий выбор в рядах, где кнопка ничего не грузит: команда,
// вариант оружия, анимация вида от первого лица.
group('.title__side', '.tag');
group('#skinbar', '.tag');
group('#fpbar', '.tag');

boot().catch((err) => {
  els.note.hidden = false;
  els.note.textContent = 'Нет связи с Python: ' + err.message;
  console.error(err);
});

// Стартовые вызовы — в самом конце: до них должны отработать все модули.
syncViewerTheme();
