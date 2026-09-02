/*
 * Своя модель и её QC.
 *
 * Замена включается самим фактом загрузки — отдельной галочки нет ни здесь, ни
 * в приложении. Тип модели («готова» / «только геометрия») решает всё
 * дальнейшее, поэтому спрашиваем до показа.
 */

import * as api from './api.js';
import { ask } from './ask.js';
import { chooseFile } from './util.js';
import { say } from './stage.js';
import { refreshView } from './preview.js';

// ── Своя модель и её QC ─────────────────────────────────────────────────
// Замена включается самим фактом загрузки: отдельной галочки нет ни здесь, ни
// в приложении. Тип модели («готова» / «только геометрия») решает всё
// дальнейшее, поэтому спрашиваем до показа.

export async function replaceModel() {
  const file = await chooseFile('.smd');
  if (!file) return;

  say('Конвертация ' + file.name + '…');
  const path = await api.upload(file);
  const first = await api.loadCustomModel(path);
  if (first.error) { say(first.error); return; }

  let keep = true;
  if (first.ask_keep) {
    const answer = await ask({
      title: 'Что это за модель',
      text: first.materials.length
        ? 'Материалы модели: ' + first.materials.join(', ')
        : 'Материалов в модели не нашлось.',
      list: [
        { label: 'Готовая — со своими материалами',
          value: 'keep',
          hint: 'Карточки возьмутся из самой модели, будет доступна правка QC' },
        { label: 'Только геометрия — текстуры игровые',
          value: 'geometry',
          hint: 'На экране ваша геометрия, карточки из игрового QC' },
      ],
      ok: 'Загрузить',
    });
    if (!answer) return;
    keep = answer === 'keep';
  }

  const res = await api.loadCustomModel(path, keep);
  if (res.error) { say(res.error); return; }
  say(keep ? 'Своя модель: материалы её собственные'
           : 'Своя модель: геометрия ваша, текстуры игровые');
  refreshView();
}

// ── Редактор QC ─────────────────────────────────────────────────────────
const qcDlg = document.getElementById('qcdlg');
const qcText = document.getElementById('qc-text');

function qcSay(text, kind = '') {
  const el = document.getElementById('qc-status');
  el.textContent = text;
  el.className = 'label vmt__status' + (kind ? ' is-' + kind : '');
}

export async function openQcEditor() {
  const res = await api.qcText();
  if (res.error) { say(res.error); return; }
  qcText.value = res.text;
  document.getElementById('qc-state').textContent =
    res.edited ? 'своя правка' : 'авто-QC';
  qcSay(res.edited ? 'Показана ваша правка' : 'Показан исправленный авто-QC');
  document.getElementById('qc-reset').hidden = !res.edited;
  qcDlg.showModal();
  qcText.scrollTop = 0;
  qcText.setSelectionRange(0, 0);
}

document.getElementById('qc-save').addEventListener('click', async () => {
  const res = await api.saveQc(qcText.value);
  if (res.error) { qcSay(res.error, 'bad'); return; }
  document.getElementById('qc-reset').hidden = !res.edited;
  document.getElementById('qc-state').textContent = res.edited ? 'своя правка' : 'авто-QC';
  qcSay('Сохранено', 'good');
});

document.getElementById('qc-reset').addEventListener('click', async () => {
  await api.saveQc('');
  const res = await api.qcText();
  qcText.value = res.text || '';
  document.getElementById('qc-reset').hidden = true;
  document.getElementById('qc-state').textContent = 'авто-QC';
  qcSay('Возвращён авто-QC');
});

document.getElementById('qc-close').addEventListener('click', () => qcDlg.close());

qcText.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
    e.preventDefault();
    document.getElementById('qc-save').click();
  }
});

// Действия над моделью под вьюпортом.
document.getElementById('model-acts').addEventListener('click', (e) => {
  const btn = e.target.closest('.textbtn');
  if (!btn) return;
  if (btn.dataset.cond === 'replace') replaceModel();
  else if (btn.dataset.cond === 'qc') openQcEditor();
});
