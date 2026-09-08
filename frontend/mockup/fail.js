/*
 * «Не получилось»: провал работы, объяснённый словами.
 *
 * Раньше сюда приходила одна техническая строка и уезжала в статус-строку:
 * `say(ev.error)`. Это текст исключения, вывод crowbar или сообщение Windows —
 * на неизвестном языке и, как правило, ни о чём человеку не говорящий. Тем
 * более если человек не русскоязычный: половина сообщений приложения написана
 * по-русски, а половина приходит от чужих инструментов по-английски.
 *
 * Теперь Python разбирает сообщение по СОДЕРЖИМОМУ (src/shared/error_classifier)
 * и присылает заголовок с объяснением на языке интерфейса. Здесь их только
 * показывают. Исходное сообщение никуда не девается — оно под «Техническими
 * деталями», для того, кто полезет разбираться, и для того, кому его пришлют.
 */

import * as api from './api.js';
import { t } from './i18n.js';

const dlg = document.getElementById('faildlg');
const titleBox = document.getElementById('fail-title');
const textBox = document.getElementById('fail-text');
const rawBox = document.getElementById('fail-raw');

/**
 * Показывает провал.
 *
 * `title` и `detail` присылает Python; если их почему-то нет (старое событие,
 * чужой воркер), показываем исходное сообщение — молчать нельзя.
 */
export function showFailure({ error, title, detail }) {
  titleBox.textContent = title || t('Не получилось');
  textBox.textContent = detail || error || '';
  textBox.hidden = !textBox.textContent;
  rawBox.textContent = error || '';
  // Технические детали прячем, если они совпали с объяснением: раскрывающийся
  // блок с тем же текстом — обман.
  dlg.querySelector('.fail__more').hidden = !error || error === detail;
  if (!dlg.open) dlg.showModal();
}

document.getElementById('fail-close').addEventListener('click', () => dlg.close());

document.getElementById('fail-copy').addEventListener('click', () => {
  // Копируем всё вместе: заголовок нужен тому, кому это пришлют, не меньше
  // самой строки ошибки.
  const text = [titleBox.textContent, textBox.textContent, '', rawBox.textContent]
    .filter(Boolean).join('\n');
  navigator.clipboard.writeText(text).catch(() => {});
});

document.getElementById('fail-log').addEventListener('click', () => {
  api.logFolder().catch(() => {});
});
