/*
 * Предупреждения при первом входе в раздел
 *
 * Не тур: обучение можно пропустить во встречающем окне или пройти заново, а
 * предупреждение должно дойти до каждого и один раз. Поэтому у него своя
 * отметка в конфиге (`notices_done`, битовая маска, как у туров), а тур
 * раздела ждёт, пока предупреждение закрыто (см. noticePending в tour.js)
 */

import * as api from './api.js';
import { ask } from './ask.js';

const root = document.documentElement;

const NOTICES = {
  particles: {
    bit: 1,
    title: 'Редактор частиц в тестовом режиме',
    text: 'Некоторые эффекты в превью выглядят не так, как в игре. Проверяйте результат в игре.',
  },
};

//: Маска из настроек; до неё показывать нельзя - не знаем, что уже видели
let done = null;
//: Какое предупреждение сейчас на экране
let open = '';

/** Маска из настроек. Зовётся при старте (applyLook) */
export function setNoticesDone(mask) {
  done = Number(mask) || 0;
  check();
}

/** Предупреждение раздела ещё впереди или на экране - туру рано */
export function noticePending(section) {
  const notice = NOTICES[section];
  return Boolean(notice) && (done === null || !(done & notice.bit) || open === section);
}

async function check() {
  const section = root.dataset.section;
  const notice = NOTICES[section];
  if (!notice || done === null || (done & notice.bit) || open) return;
  open = section;
  await ask({ title: notice.title, text: notice.text, ok: 'Понятно', cancel: false });
  // Закрыли хоть кнопкой, хоть Esc - прочитано
  done |= notice.bit;
  api.setUiState('notices_done', done);
  open = '';
}

new MutationObserver(check).observe(root, { attributes: true, attributeFilter: ['data-section'] });
