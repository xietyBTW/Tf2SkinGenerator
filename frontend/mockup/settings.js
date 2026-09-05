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
import { relabel } from './catalog.js';
import { setTheme } from './log.js';
import { useDict, t } from './i18n.js';
import { EN } from './strings.js';
import { refreshView } from './preview.js';

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
  // Язык: ответы Python берут его из общего конфига сами, а вьюверу сказать
  // некому — он живёт отдельным документом и до конфига не дотягивается.
  api.setLang(values.language);
  withViewer((w) => w.setLanguage && w.setLanguage(api.lang()));
  // Подписи самой страницы: разметка и всё, что построит код (см. i18n.js).
  useDict(api.lang() === 'en' ? EN : null);
}

export async function openSettings() {
  const cfg = await api.settings();
  const v = cfg.values;

  document.getElementById('cfg-tf2').value = v.tf2_game_folder || '';
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
  document.getElementById('cfg-temp').checked = Boolean(v.keep_temp_files);
  document.getElementById('cfg-debug').checked = Boolean(v.debug_mode);
  document.getElementById('cfg-blacklist').value =
    (v.material_blacklist || []).join('\\n');
  document.getElementById('cfg-note').textContent =
    pinnedFits() ? '' : 'для закреплённых панелей нужно окно шире 1100 px';

  document.getElementById('cfg-cache-size').textContent =
    cfg.cache_mb ? cfg.cache_mb + ' ' + t('МБ') : t('пусто');
  showDrafts();
  const supp = document.getElementById('cfg-support');
  supp.href = cfg.support_url || '#';
  supp.hidden = !cfg.support_url;

  cfgDlg.showModal();
}

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
    keep_temp_files: document.getElementById('cfg-temp').checked,
    debug_mode: document.getElementById('cfg-debug').checked,
    material_blacklist: document.getElementById('cfg-blacklist').value,
    panels_pinned: document.getElementById('cfg-panels').checked,
  });
  if (res.error) { say(res.error); return; }
  cfgDlg.close();
  say('Настройки сохранены');
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

document.getElementById('cfg-cancel').addEventListener('click', () => cfgDlg.close());
document.getElementById('opencfg').addEventListener('click', openSettings);
