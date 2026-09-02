/*
 * Диагностика мода.
 *
 * Проверяет СОБРАННЫЙ файл, а не состояние сеанса: смотреть можно любой VPK, в
 * том числе чужой. Отчёт приходит событием — проверка идёт в своём потоке.
 */

import * as api from './api.js';
import { chooseFile } from './util.js';

// ── Диагностика мода ────────────────────────────────────────────────────
// Проверяет СОБРАННЫЙ файл, а не состояние сеанса: смотреть можно любой VPK,
// в том числе чужой. Отчёт приходит событием — проверка идёт в своём потоке.

export const diagDlg = document.getElementById('diagdlg');

export function diagSay(text, kind = '') {
  const el = document.getElementById('diag-status');
  el.textContent = text;
  el.className = 'label vmt__status' + (kind ? ' is-' + kind : '');
}

async function pickForDiagnosis() {
  const file = await chooseFile('.vpk');
  if (!file) return;
  document.getElementById('diag-file').textContent = file.name;
  document.getElementById('diag-list').innerHTML = '';
  diagSay('Проверка…');
  const res = await api.diagnose(await api.upload(file));
  if (res.error) diagSay(res.error, 'bad');
}

/** Раскладывает отчёт: сначала итог, потом находки в порядке важности. */
export function showReport(ev) {
  const list = document.getElementById('diag-list');
  list.innerHTML = '';
  if (!ev.ok) { diagSay(ev.message || 'Проверка не удалась', 'bad'); return; }

  const r = ev.report;
  diagSay(r.healthy
    ? 'Проблем не найдено'
    : `Ошибок: ${r.errors} · предупреждений: ${r.warnings}`,
    r.healthy ? 'good' : 'bad');

  for (const f of r.findings) {
    const row = document.createElement('div');
    row.className = 'finding finding--' + f.severity;

    const title = document.createElement('div');
    title.className = 'finding__title';
    title.textContent = f.title;
    row.append(title);

    if (f.location) {
      const where = document.createElement('span');
      where.className = 'mono finding__where';
      where.textContent = f.location;
      row.append(where);
    }
    if (f.detail) {
      const detail = document.createElement('p');
      detail.className = 'finding__detail';
      detail.textContent = f.detail;
      row.append(detail);
    }
    if (f.fix) {
      const fix = document.createElement('p');
      fix.className = 'finding__fix';
      fix.textContent = 'Что делать: ' + f.fix;
      row.append(fix);
    }
    list.append(row);
  }
}

document.getElementById('diag-pick').addEventListener('click', pickForDiagnosis);
document.getElementById('diag-close').addEventListener('click', () => diagDlg.close());
