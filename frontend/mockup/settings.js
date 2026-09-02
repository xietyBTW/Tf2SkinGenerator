/*
 * Настройки приложения.
 *
 * Конфиг общий с окном приложения, поэтому здесь только показ и запись. Что
 * считать допустимым значением (пустая папка экспорта, разбор списка
 * исключений), решает Python.
 */

import * as api from './api.js';
import { fillSelect } from './util.js';
import { say } from './stage.js';
import { showTf2Path } from './layout.js';

// ── Настройки ───────────────────────────────────────────────────────────
// Конфиг общий с окном приложения, поэтому здесь только показ и запись: что
// считать допустимым значением (пустая папка экспорта, разбор списка
// исключений), решает Python.

const cfgDlg = document.getElementById('cfgdlg');


export async function openSettings() {
  const cfg = await api.settings();
  const v = cfg.values;

  document.getElementById('cfg-tf2').value = v.tf2_game_folder || '';
  document.getElementById('cfg-export').value = v.export_folder || '';
  fillSelect('cfg-format', cfg.formats, v.export_image_format);
  fillSelect('cfg-lang', cfg.languages, v.language);
  fillSelect('cfg-theme', cfg.themes, v.theme);
  fillSelect('cfg-bypass', cfg.bypass, v.sv_pure_bypass);
  document.getElementById('cfg-bypass-tip').textContent = cfg.bypass_tip || '';
  document.getElementById('cfg-save').checked = Boolean(v.save_edits);
  document.getElementById('cfg-tree').checked = Boolean(v.particles_group_tree);
  document.getElementById('cfg-temp').checked = Boolean(v.keep_temp_files);
  document.getElementById('cfg-debug').checked = Boolean(v.debug_mode);
  document.getElementById('cfg-blacklist').value =
    (v.material_blacklist || []).join('\\n');
  // Язык и тема относятся к ОКНУ приложения: страница живёт со своей темой,
  // и обещать её смену здесь было бы неправдой.
  document.getElementById('cfg-note').textContent = 'общие с приложением';

  cfgDlg.showModal();
}

document.getElementById('cfg-save').addEventListener('click', async () => {
  const res = await api.setSettings({
    tf2_game_folder: document.getElementById('cfg-tf2').value,
    export_folder: document.getElementById('cfg-export').value,
    export_image_format: document.getElementById('cfg-format').value,
    language: document.getElementById('cfg-lang').value,
    theme: document.getElementById('cfg-theme').value,
    sv_pure_bypass: document.getElementById('cfg-bypass').value,
    save_edits: document.getElementById('cfg-save').checked,
    particles_group_tree: document.getElementById('cfg-tree').checked,
    keep_temp_files: document.getElementById('cfg-temp').checked,
    debug_mode: document.getElementById('cfg-debug').checked,
    material_blacklist: document.getElementById('cfg-blacklist').value,
  });
  if (res.error) { say(res.error); return; }
  cfgDlg.close();
  say('Настройки сохранены');
  // Путь к игре мог измениться — подпись внизу обязана это показать.
  showTf2Path();
});

document.getElementById('cfg-cancel').addEventListener('click', () => cfgDlg.close());
document.getElementById('opencfg').addEventListener('click', openSettings);
