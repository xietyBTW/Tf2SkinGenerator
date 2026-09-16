/*
 * Настройки приложения.
 *
 * Конфиг общий с окном приложения, поэтому здесь только показ и запись. Что
 * считать допустимым значением (пустая папка экспорта, разбор списка
 * исключений), решает Python.
 */

import * as api from './api.js';
import { fillSelect, fileSize, plural } from './util.js';
import { ask } from './ask.js';
import { say, withViewer } from './stage.js';
import { showTf2Path, setPinned, pinnedFits } from './layout.js';
import { setParamsWidth } from './particles/resize.js';
import { setSplit } from './split.js';
import { relabel } from './catalog.js';
import { setTheme, setConsoleWidth, setConsoleFilter } from './log.js';
import { useDict, t } from './i18n.js';
import { EN } from './strings.js';
import { refreshView, stopPartsAnimation } from './preview.js';

// ── Настройки ───────────────────────────────────────────────────────────
// Конфиг общий с окном приложения, поэтому здесь только показ и запись: что
// считать допустимым значением (пустая папка экспорта, разбор списка
// исключений), решает Python.

const cfgDlg = document.getElementById('cfgdlg');


/**
 * Ставит внешний вид по сохранённым настройкам: тему и закрепление панелей.
 *
 * Раньше обе жили кнопками в шапке и не переживали перезапуск — приложение
 * каждый раз открывалось светлым и с плавающими панелями. Зовётся и на старте,
 * и после сохранения.
 */
export function applyLook(values) {
  setTheme(values.theme || 'light');
  setPinned(Boolean(values.panels_pinned));
  // Ширина панели частиц и граница половин: их тянут мышью, а не выбирают в
  // этом окне, но читаются они тем же ответом — настройки внешнего вида
  // страница спрашивает один раз.
  setParamsWidth(values.params_width);
  setSplit(values.split_percent);
  // Консоль: ширина, которую тянули за край, и выбранные категории.
  setConsoleWidth(values.console_width);
  setConsoleFilter(values.console_filter);
  // Язык: ответы Python берут его из общего конфига сами, а вьюверу сказать
  // некому — он живёт отдельным документом и до конфига не дотягивается.
  api.setLang(values.language);
  withViewer((w) => w.setLanguage && w.setLanguage(api.lang()));
  // Подписи самой страницы: разметка и всё, что построит код (см. i18n.js).
  useDict(api.lang() === 'en' ? EN : null);
  // Особые флаги VTF: признак на корне, показом занимается CSS. Так галка
  // действует сразу и не требует перерисовки колонки — а скрытая галка в
  // сборку не уходит (см. build.js: невидимое не читается).
  document.documentElement.dataset.advflags =
    values.advanced_vtf_flags ? '1' : '';
  // Анимации: признак на корне гасит CSS-переходы страницы, вьюверу — своим
  // вызовом: перелёт камеры и проявление модели считает он сам.
  const motion = values.ui_animations !== false;
  document.documentElement.dataset.motion = motion ? '' : 'off';
  withViewer((w) => w.setMotion && w.setMotion(motion));
}

export async function openSettings() {
  const cfg = await api.settings();
  const v = cfg.values;

  document.getElementById('cfg-tf2').value = v.tf2_game_folder || '';
  // Кнопка автопоиска нужна, только пока игра не найдена: с рабочим путём
  // искать нечего. Годность решает Python (`tf2_ok`) той же проверкой, по
  // которой работает всё приложение.
  showFindTf2(!cfg.tf2_ok);
  document.getElementById('cfg-export').value = v.export_folder || '';
  fillSelect('cfg-format', cfg.formats, v.export_image_format);
  fillSelect('cfg-lang', cfg.languages, v.language);
  // Тема страницы — она же тема приложения: другого интерфейса больше нет.
  fillSelect('cfg-theme', cfg.themes, v.theme || 'light');
  document.getElementById('cfg-panels').checked = Boolean(v.panels_pinned);
  document.getElementById('cfg-panels').disabled = !pinnedFits();
  fillSelect('cfg-bypass', cfg.bypass, v.sv_pure_bypass);
  document.getElementById('cfg-bypass-tip').textContent = cfg.bypass_tip || '';
  document.getElementById('cfg-edits').checked = Boolean(v.save_edits);
  document.getElementById('cfg-tree').checked = Boolean(v.particles_group_tree);
  document.getElementById('cfg-advflags').checked = Boolean(v.advanced_vtf_flags);
  document.getElementById('cfg-motion').checked = v.ui_animations !== false;
  document.getElementById('cfg-temp').checked = Boolean(v.keep_temp_files);
  document.getElementById('cfg-parts-anim').checked = Boolean(v.parts_animation);
  document.getElementById('cfg-debug').checked = Boolean(v.debug_mode);
  document.getElementById('cfg-blacklist').value =
    (v.material_blacklist || []).join('\n');
  document.getElementById('cfg-note').textContent =
    pinnedFits() ? '' : 'для закреплённых панелей нужно окно шире 1100 px';

  showDrafts();
  const supp = document.getElementById('cfg-support');
  supp.href = cfg.support_url || '#';
  supp.hidden = !cfg.support_url;

  cfgDlg.showModal();

  // Размер кэша — ПОСЛЕ показа окна и без await: он считается обходом всей
  // папки со stat на каждый файл, и на большой библиотеке это секунды. Число
  // нужно только для подписи рядом с кнопкой «очистить», ждать его незачем.
  const cacheSize = document.getElementById('cfg-cache-size');
  cacheSize.textContent = t('считаю…');
  api.cacheSize()
    .then((r) => { cacheSize.textContent =
      r.cache_mb ? r.cache_mb + ' ' + t('МБ') : t('пусто'); })
    .catch(() => { cacheSize.textContent = t('пусто'); });

  // Обновление — тоже после показа окна и тоже без await: это запрос к GitHub,
  // и открытие настроек не должно ждать сеть.
  showUpdate();
}

// ── Обновление приложения ───────────────────────────────────────────────
// Ставит СОБРАННОЕ приложение установщиком из релиза: он умеет закрыть нас,
// заменить файлы и починить ярлыки. Из репозитория обновляются через git —
// тогда Python отвечает can_install: false, и остаётся только ссылка.

//: Что делает кнопка обновления прямо сейчас. null — «проверить»; после
//: проверки это либо установка, либо открытие страницы релиза. Состояние
//: отдельной переменной, а не в onclick элемента: два обработчика на одной
//: кнопке разъезжаются при первой же правке.
let updateAction = null;

/** Показывает версию и, если есть, предложение обновиться. */
function showUpdate(force = false) {
  const line = document.getElementById('cfg-version');
  const note = document.getElementById('cfg-update-note');
  const btn = document.getElementById('cfg-update');

  line.textContent = force ? t('проверяю…') : '';
  note.hidden = true;
  btn.disabled = force;
  updateAction = null;

  api.updateStatus(force).then((u) => {
    btn.disabled = false;
    line.textContent = 'v' + u.current;
    if (!u.checked) {
      note.hidden = false;
      note.textContent = t('Не удалось проверить обновления — нет связи с GitHub.');
      return;
    }
    if (!u.available) {
      note.hidden = false;
      note.textContent = t('Установлена последняя версия.');
      return;
    }
    note.hidden = false;
    note.textContent = t('Доступна версия') + ' ' + u.version + '. '
      + (u.can_install
        ? t('Нажмите «Обновить» — приложение закроется и вернётся уже новым.')
        : t('Скачайте её со страницы релиза.'));
    btn.textContent = u.can_install ? t('Обновить') : t('Открыть страницу релиза');
    updateAction = u.can_install
      ? () => runUpdate(u)
      : () => window.open(u.page_url, '_blank', 'noreferrer');
  }).catch(() => {
    btn.disabled = false;
    note.hidden = false;
    note.textContent = t('Не удалось проверить обновления.');
  });
}

/** Качает установщик и отдаёт ему управление. Приложение после этого закроется. */
async function runUpdate(u) {
  const go = await ask({
    title: t('Обновить до') + ' ' + u.version,
    // eslint-disable-next-line max-len — ключ словаря должен быть одним литералом
    text: t('Приложение закроется, установщик заменит его на новую версию и запустит заново. Ваши работы, моды и настройки не тронутся — они хранятся отдельно от папки установки.'),
    ok: t('Обновить'),
  });
  if (!go) return;

  const note = document.getElementById('cfg-update-note');
  const btn = document.getElementById('cfg-update');
  note.hidden = false;
  note.textContent = t('Скачиваю установщик…');
  // Кнопку выключаем: скачивание уже идёт, второе нажатие ничего не ускорит.
  btn.disabled = true;
  updateAction = null;

  try {
    await api.installUpdate();
  } catch (err) {
    btn.disabled = false;
    note.textContent = t('Обновление не установлено') + ': ' + err.message;
    return;
  }
  watchUpdate();
}

/**
 * Опрашивает ход обновления и пишет его в подпись.
 *
 * Опрос, а не поток событий: установщик носит приложение внутри себя, это
 * десятки мегабайт, и всё, что нужно показать, — сколько уже скачано.
 * Заводить ради одной строки подписку не за чем.
 */
function watchUpdate() {
  const note = document.getElementById('cfg-update-note');
  const btn = document.getElementById('cfg-update');
  const mb = (bytes) => (bytes / 1048576).toFixed(1);

  const tick = async () => {
    let p;
    try {
      p = await api.updateProgress();
    } catch (err) {
      // Приложение уже закрывается — опрос обрывается, и это норма.
      return;
    }
    if (p.state === 'downloading') {
      note.textContent = p.total
        ? t('Скачиваю установщик…') + ' ' + mb(p.done) + ' / ' + mb(p.total) + ' ' + t('МБ')
        : t('Скачиваю установщик…');
      setTimeout(tick, 500);
      return;
    }
    if (p.state === 'launching' || p.state === 'done') {
      note.textContent = t('Установщик запущен, приложение закрывается…');
      return;
    }
    if (p.state === 'error') {
      btn.disabled = false;
      note.textContent = t('Обновление не установлено') + ': ' + (p.error || '');
      return;
    }
    setTimeout(tick, 500);
  };
  tick();
}

document.getElementById('cfg-update').addEventListener('click', () => {
  // Пока проверки не было — кнопка спрашивает заново, минуя ответ,
  // запомненный на сеанс. После — делает то, что предложила.
  if (updateAction) updateAction();
  else showUpdate(true);
});

// Обслуживание: после обновления игры старые разобранные модели остаются в
// кэше и собираются с прежней геометрией. Спрашиваем — очистка не бесплатна:
// первая сборка каждого оружия после неё будет медленнее.
document.getElementById('cfg-cache').addEventListener('click', async () => {
  const size = document.getElementById('cfg-cache-size').textContent;
  const go = await ask({
    title: 'Очистить кэш моделей',
    text: 'Сейчас в кэше ' + size + '. Кэш ускоряет повторную сборку того же '
        + 'оружия — после очистки первая сборка каждого будет медленнее.',
    ok: 'Очистить',
  });
  if (!go) return;
  const res = await api.clearModelCache();
  document.getElementById('cfg-cache-size').textContent = 'пусто';
  say('Кэш очищен, записей удалено: ' + (res.removed ?? 0));
});

/**
 * Сколько черновиков лежит на диске.
 *
 * Спрашиваем при открытии настроек, а не в общем ответе `settings`: обход
 * папки работ считает размер каждой, и платить за это на каждый чих незачем.
 */
let draftList = [];

async function showDrafts() {
  const label = document.getElementById('cfg-drafts-size');
  const btn = document.getElementById('cfg-drafts');
  draftList = await api.drafts();
  const bytes = draftList.reduce((sum, d) => sum + (d.size || 0), 0);
  btn.disabled = draftList.length === 0;
  label.textContent = draftList.length
    ? draftList.length + ' ' + plural(draftList.length, 'черновик', 'черновика',
                                      'черновиков') + ', ' + fileSize(bytes)
    : 'нет';
}

// Черновик пишется молча на каждое движение, и в библиотеке его нет намеренно:
// иначе «просто открыл предмет» становилось модом. Но копии текстур остаются
// на диске, и добраться до них было можно только заново открыв тот же предмет.
// Список даём отметить: удалять всё разом человек может и не хотеть.
document.getElementById('cfg-drafts').addEventListener('click', async () => {
  if (!draftList.length) { say('Черновиков нет'); return; }
  const picked = await ask({
    title: 'Удалить черновики',
    text: 'Это молчаливые записи автосохранения — работы, сохранённые кнопкой, '
        + 'здесь не показаны и не пострадают. Снимите отметку с того, что '
        + 'нужно оставить.',
    list: draftList.map((d) => ({
      label: d.name + ' — ' + fileSize(d.size || 0),
      value: d.key,
      hint: d.key,
    })),
    multi: true,
    chosen: draftList.map((d) => d.key),
    ok: 'Удалить',
  });
  if (!picked || !picked.length) return;
  const res = await api.forgetDrafts(picked);
  if (res.error) { say(res.error); return; }
  say('Черновиков удалено: ' + (res.removed ?? 0));
  // Ушёл черновик открытого предмета — вместе с ним ушли и правки на экране.
  if (res.reset) refreshView();
  showDrafts();
});

document.getElementById('cfg-save').addEventListener('click', async () => {
  const res = await api.setSettings({
    tf2_game_folder: document.getElementById('cfg-tf2').value,
    export_folder: document.getElementById('cfg-export').value,
    export_image_format: document.getElementById('cfg-format').value,
    language: document.getElementById('cfg-lang').value,
    theme: document.getElementById('cfg-theme').value,
    sv_pure_bypass: document.getElementById('cfg-bypass').value,
    save_edits: document.getElementById('cfg-edits').checked,
    particles_group_tree: document.getElementById('cfg-tree').checked,
    advanced_vtf_flags: document.getElementById('cfg-advflags').checked,
    ui_animations: document.getElementById('cfg-motion').checked,
    keep_temp_files: document.getElementById('cfg-temp').checked,
    parts_animation: document.getElementById('cfg-parts-anim').checked,
    debug_mode: document.getElementById('cfg-debug').checked,
    material_blacklist: document.getElementById('cfg-blacklist').value,
    panels_pinned: document.getElementById('cfg-panels').checked,
  });
  if (res.error) { say(res.error); return; }
  cfgDlg.close();
  say('Настройки сохранены');
  // Гифки на модели: выключили — сцена перекрашивается неподвижной склейкой;
  // включили — кадры приедут событием parts_animated.
  if (!(res.values || {}).parts_animation) stopPartsAnimation();
  // Тема, раскладка и язык применяются сразу: ждать перезапуска ради галки —
  // не то, чего ждут от настроек.
  const before = api.lang();
  applyLook(res.values || {});
  // Путь к игре мог измениться — подпись внизу обязана это показать.
  showTf2Path();
  // Имена предметов приезжают с языком: справочники в кэше — от прошлого,
  // и список на экране тоже. Перерисовываем, сохраняя выбор.
  if (api.lang() !== before) {
    api.forgetCached();
    await relabel();
  }
});

//: Кнопка автопоиска: показываем её вместе с подписью-обёрткой, иначе от
//: скрытой кнопки остаётся пустая строка под полем.
function showFindTf2(show) {
  document.getElementById('cfg-findtf2').closest('.field__note').hidden = !show;
}

/**
 * Автопоиск игры: подставляет найденный путь в поле.
 *
 * Ищет Python (`find_tf2`) — реестром Steam и списком его библиотек, а не
 * обходом диска. Найденное заведомо годное: проверка та же, по которой
 * работает всё приложение.
 */
document.getElementById('cfg-findtf2').addEventListener('click', async (e) => {
  const btn = e.target;
  btn.disabled = true;
  try {
    const found = (await api.findTf2()).found || [];
    if (!found.length) {
      say(t('Игра не нашлась — укажите папку вручную'));
      return;
    }
    document.getElementById('cfg-tf2').value = found[0];
    // Копий больше одной — редкость (вторая библиотека Steam). Берём первую,
    // но молчать об этом нельзя: путь могли ждать другой.
    say(found.length > 1
      ? t('Найдено копий игры: ') + found.length + t(', взял первую')
      : t('Игра найдена: ') + found[0]);
  } finally {
    btn.disabled = false;
  }
});

/**
 * Первый запуск: предложить найденную игру или дать вставить путь руками.
 *
 * Без пути к игре не работает ничего, а узнать об этом человек мог только по
 * ошибке на первой же загрузке модели. Спрашиваем ОДИН раз — когда путь не
 * настроен; сохранённый путь окно вопроса не трогает.
 */
export async function offerTf2() {
  const paths = await api.call('tf2_paths');
  if (!paths.error) return;

  const found = (await api.findTf2()).found || [];
  const answer = await ask({
    title: t('Где установлена TF2?'),
    text: found.length
      ? t('Нашёл игру здесь. Сохранить этот путь?')
      : t('Найти игру сам не смог. Вставьте путь к папке игры.'),
    value: found[0] || '',
    ok: t('Сохранить'),
  });
  if (!answer || !String(answer).trim()) return;

  const res = await api.setSettings({ tf2_game_folder: String(answer).trim() });
  if (res.error) { say(res.error); return; }
  showTf2Path();
  // Обложки предметов приезжают из игры: список на экране нарисован без них.
  api.forgetCached();
  await relabel();
}

// Путь начали править руками: годность прежнего пути ничего уже не значит, и
// кнопка снова может понадобиться — проверять каждую букву в Python незачем.
document.getElementById('cfg-tf2').addEventListener('input', () => showFindTf2(true));

document.getElementById('cfg-cancel').addEventListener('click', () => cfgDlg.close());
document.getElementById('opencfg').addEventListener('click', openSettings);
