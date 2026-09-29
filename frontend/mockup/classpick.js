/*
 * Выбор классов плитками: значок класса из игры и его название.
 *
 * Отдельное окно, а не общий #ask: там список строк с поиском, а классов
 * девять и их узнают по эмблеме, а не по английскому имени.
 */

import * as api from './api.js';
import { t } from './i18n.js';

const dlg = document.getElementById('classdlg');
const grid = dlg.querySelector('.classpick__grid');
const count = dlg.querySelector('.classpick__count');
const okBtn = dlg.querySelector('.ask__ok');

//: Порядок и названия — как в меню выбора класса игры.
export const CLASS_ORDER = ['scout', 'soldier', 'pyro', 'demoman', 'heavy',
                            'engineer', 'medic', 'sniper', 'spy'];
const NAMES = {
  scout: 'Разведчик', soldier: 'Солдат', pyro: 'Поджигатель',
  demoman: 'Подрывник', heavy: 'Пулемётчик', engineer: 'Инженер',
  medic: 'Медик', sniper: 'Снайпер', spy: 'Шпион',
};

//: Значки из игры — один запрос за сеанс.
let icons = null;

async function loadIcons() {
  // Пустой ответ (игра ещё не найдена) не запоминаем — спросим в следующий раз.
  if (icons && Object.keys(icons).length) return icons;
  try {
    icons = (await api.classIcons()).icons || {};
  } catch {
    icons = {};
  }
  return icons;
}

/**
 * Спрашивает классы. Возвращает отмеченные в порядке игры или null (отмена).
 *
 * classes — какие классы вообще предлагать; chosen — отмеченные сразу.
 */
export async function pickClasses({ classes, chosen = classes, ok = 'Собрать' }) {
  const have = CLASS_ORDER.filter((c) => classes.includes(c))
    .concat(classes.filter((c) => !CLASS_ORDER.includes(c)));
  const marks = new Set(chosen.filter((c) => have.includes(c)));
  const got = await loadIcons();

  grid.innerHTML = '';
  const tiles = have.map((cls) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'classpick__tile';
    b.dataset.cls = cls;
    b.setAttribute('aria-pressed', 'false');
    if (got[cls]) {
      const img = document.createElement('img');
      img.src = api.fileUrl(got[cls]);
      img.alt = '';
      img.draggable = false;
      b.appendChild(img);
    }
    const name = document.createElement('span');
    name.textContent = t(NAMES[cls] || cls);
    b.appendChild(name);
    b.addEventListener('click', () => {
      if (marks.has(cls)) marks.delete(cls); else marks.add(cls);
      sync();
    });
    grid.appendChild(b);
    return b;
  });

  function sync() {
    for (const b of tiles) {
      const on = marks.has(b.dataset.cls);
      b.classList.toggle('is-active', on);
      b.setAttribute('aria-pressed', String(on));
    }
    count.textContent = t('Выбрано {} из {}')
      .replace('{}', marks.size).replace('{}', have.length);
    okBtn.disabled = !marks.size;
    okBtn.textContent = marks.size ? `${t(ok)} · ${marks.size}` : t(ok);
  }
  sync();

  return new Promise((resolve) => {
    let done = false;
    const all = dlg.querySelector('.classpick__all');
    const none = dlg.querySelector('.classpick__none');
    const cancel = dlg.querySelector('.ask__cancel');
    const onAll = () => { have.forEach((c) => marks.add(c)); sync(); };
    const onNone = () => { marks.clear(); sync(); };
    const finish = (result) => {
      if (done) return;
      done = true;
      all.removeEventListener('click', onAll);
      none.removeEventListener('click', onNone);
      okBtn.removeEventListener('click', onOk);
      cancel.removeEventListener('click', onCancel);
      dlg.removeEventListener('cancel', onCancel);
      if (dlg.open) dlg.close();
      resolve(result);
    };
    const onOk = (e) => { e.preventDefault(); finish(have.filter((c) => marks.has(c))); };
    const onCancel = () => finish(null);
    all.addEventListener('click', onAll);
    none.addEventListener('click', onNone);
    okBtn.addEventListener('click', onOk);
    cancel.addEventListener('click', onCancel);
    dlg.addEventListener('cancel', onCancel);
    dlg.showModal();
    tiles[0]?.focus();
  });
}
