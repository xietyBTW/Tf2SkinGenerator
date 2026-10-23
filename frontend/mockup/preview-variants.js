/*
 * Ряды вариантов модели под кадром: состояния (бодигруппы), праздничная
 * версия с гирляндой, вариантные стили (skinfamilies) и полоса стиля под
 * альбомом.
 */

import * as api from './api.js';
import { ask } from './ask.js';
import { t } from './i18n.js';
import { say, sayError, sayBusy, viewer, withViewer } from './stage.js';
import { work } from './layout.js';
import { closeParts, refreshParts } from './parts.js';
import { toggleDecorFit, isDecorFitOn, leaveDecorFit } from './custom-model.js';
import { applyView, refreshView } from './preview.js';
import { reloadSceneIfFp } from './preview-scenes.js';

/**
 * Переключатель состояний модели: ряд на каждую бодигруппу с вариантами
 *
 * Только показ - в мод уходят все состояния, игра переключает их сама. Ряд
 * прячется, когда переключать нечего (у большинства оружия один вариант).
 * Части закрываются: их номера считаны по геометрии в кадре.
 */
export function showBodygroups(groups) {
  const bar = document.getElementById('bodybar');
  bar.innerHTML = '';
  bar.hidden = !groups.length || work.dataset.scene !== 'item';
  if (bar.hidden) return;
  for (const g of groups) {
    const label = document.createElement('span');
    label.className = 'label label--inline';
    // Снаряд в оружии - не состояние, а деталь: виден, пока его правят
    label.textContent = g.projectile
      ? (g.custom ? 'Свой снаряд в оружии' : 'Снаряд в оружии')
      : groups.length > 1 ? `Состояние · ${g.name}` : 'Состояние модели';
    bar.appendChild(label);
    g.variants.forEach((name, i) => {
      const b = document.createElement('button');
      b.className = 'tag' + (i === g.chosen ? ' is-active' : '');
      b.textContent = name;
      b.addEventListener('click', async () => {
        if (i === g.chosen) return;
        closeParts();
        say('Собираю состояние…');
        const res = await api.setBodygroup(g.name, i);
        if (res.error) { sayError(res.error); return; }
        applyView(res);
      });
      bar.appendChild(b);
    });
  }
}

//: Подписи видов гирлянды. Ключи задаёт Python (festive_decor / items_game)
/** Гирлянду есть что подгонять: своя модель (оружия, мода из VPK или её
 *  самой) или уже правлена */
export const decorFittable = (st) => Boolean(st.custom_geometry || st.decor_fit
  || (st.decor_bends || []).length || (st.decor_models || []).includes(st.festive));

const FESTIVE_LABELS = { '': 'Обычная', xmas: 'Праздничная', festivizer: 'Фестивайзер' };

/**
 * Праздничная версия оружия: обычная, праздничная, фестивайзер
 *
 * Только показ: гирлянда висит поверх модели своим слоем вьювера и в мод не
 * идёт - поэтому и на своей модели она остаётся там, где её повесит игра.
 * Ряд есть в кадре предмета и в руках: игра показывает гирлянду и там, и там.
 */
export function showFestive(st) {
  const bar = document.getElementById('festivebar');
  const options = st.festive_options || [];
  const scene = work.dataset.scene || 'item';
  const baked = st.festive_baked || '';
  bar.querySelectorAll('.tag, .festive__note').forEach((n) => n.remove());
  bar.hidden = !options.length || !(scene === 'item' || scene === 'fp');
  showBakeButton(st, options);
  withViewer((w) => w.setDecorTeam && w.setDecorTeam(st.team));
  if (bar.hidden) return;

  // Правки гирлянды живут и при выключенном показе - метка на кнопке
  // говорит, что в мод уйдёт своя гирлянда (как метка правленого стиля).
  // Вшитая гирлянда одна: выбора версии нет, две разом игра не повесит
  const edited = new Set(st.festive_edited || []);
  if (baked) {
    const note = document.createElement('span');
    note.className = 'label label--inline festive__note';
    note.textContent = t('Вшита в модель: {}').replace('{}', t(FESTIVE_LABELS[baked] || baked));
    bar.appendChild(note);
  }
  for (const kind of baked ? [] : ['', ...options]) {
    const b = document.createElement('button');
    b.className = 'tag' + (kind === (st.festive || '') ? ' is-active' : '');
    b.dataset.kind = kind;
    b.textContent = t(FESTIVE_LABELS[kind] || kind) + (edited.has(kind) ? ' ●' : '');
    b.addEventListener('click', async () => {
      if (b.classList.contains('is-active')) return;
      bar.querySelectorAll('.tag[data-kind]').forEach(
        (x) => x.classList.toggle('is-active', x === b));
      // Первое включение - разбор модели гирлянды, около секунды, повторное
      // из памяти, и подпись тогда не мигнёт (sayBusy отложенная)
      if (kind) sayBusy('Загрузка гирлянды…');
      // Подгонку прошлой гирлянды - записать и закрыть: отложенная запись
      // иначе легла бы уже на новую (или потерялась бы на «Обычная»)
      await leaveDecorFit();
      try {
        applyView(await api.setFestive(kind));
      } catch (err) {
        sayError(err.message);
        refreshView();
      }
    });
    bar.appendChild(b);
  }
  // Подгонка гирлянды под модель - тем же инструментом, что и своя модель.
  // Только при своей модели: на стоковой гирлянда уже стоит на месте. Уже
  // сделанную подгонку оставляем доступной и без неё - иначе, убрав свою
  // модель, сдвинутую гирлянду было бы не вернуть, и она ушла бы в мод
  if (st.festive && scene === 'item' && decorFittable(st)) {
    const fit = document.createElement('button');
    fit.className = 'tag festive__fit' + (isDecorFitOn() ? ' is-active' : '');
    fit.textContent = 'Подогнать гирлянду';
    fit.title = t('Сдвинуть, повернуть и растянуть гирлянду под свою модель (G/R/S)');
    fit.addEventListener('click', () => {
      toggleDecorFit();
      fit.classList.toggle('is-active', isDecorFitOn());
    });
    bar.appendChild(fit);
  }
  // На своей модели гирлянда стоит по стоковой, пока её не подогнали: так её
  // и повесит игра, и огоньки будут висеть мимо
  if (st.festive && st.custom_geometry && !st.decor_fit && !(st.decor_bends || []).length) {
    const note = document.createElement('span');
    note.className = 'label label--inline festive__note';
    note.textContent = 'Висит как на стоковой модели - подгоните под свою';
    bar.appendChild(note);
  }
}

/** «Сделать праздничным» / «Снять гирлянду»: есть у оружия с гирляндами,
 *  кроме мода из VPK (его модель собирается своим конвейером) */
function showBakeButton(st, options) {
  const btn = document.getElementById('makefestive');
  btn.hidden = !options.length || !st.can_bake_festive || work.dataset.scene !== 'item';
  btn.textContent = t(st.festive_baked ? 'Снять гирлянду' : 'Сделать праздничным');
  btn.dataset.baked = st.festive_baked || '';
  btn.dataset.options = options.join(',');
}

document.getElementById('makefestive').addEventListener('click', async (e) => {
  const { baked, options } = e.currentTarget.dataset;
  let kind = '';
  if (!baked) {
    const kinds = options.split(',').filter(Boolean);
    kind = kinds.length > 1
      ? await ask({ title: 'Какую гирлянду вшить?', ok: 'Вшить',
                    list: kinds.map((k) => ({ label: FESTIVE_LABELS[k] || k, value: k })) })
      : kinds[0];
    if (!kind) return;
    sayBusy('Загрузка гирлянды…');
  }
  await leaveDecorFit();
  const res = await api.bakeFestive(kind);
  if (res.error) { sayError(res.error); return; }
  applyView(res);
  say(kind ? 'Гирлянда войдёт в модель оружия' : 'Гирлянда снята');
});

/**
 * Гирлянда приехала (или её выключили): слой вьювера и, если открыт вид от
 * первого лица, сцена в руках - там гирлянда собирается вместе с оружием.
 */
//: Номер последнего события гирлянды: OBJ качается отдельно, и за это время
//: гирлянду могли выключить или уйти к другому предмету - старая не должна
//: встать поверх
let decorSeq = 0;

/** Гирлянда прошлого предмета, если ещё качается, не нужна */
export function forgetDecor() { decorSeq++; }

export async function showDecor(ev) {
  const w = viewer();
  if (!w || !w.setDecor) return;
  const seq = ++decorSeq;
  // Гирлянда пересобирается во вьювере - её подгонка там гаснет, страница
  // обязана погасить свою половину, иначе панель висела бы без гизмо
  await leaveDecorFit();
  if (!ev.kind) {
    w.clearDecor();
  } else {
    try {
      const obj = await (await fetch(api.fileUrl(ev.obj))).text();
      if (seq !== decorSeq) return;
      const urls = (list) => (list || []).map(api.fileUrl);
      const mats = Object.fromEntries(Object.entries(ev.materials || {}).map(
        ([name, m]) => [name, { ...m, red: urls(m.red), blu: urls(m.blu) }]));
      w.setDecor(obj, mats, ev.hints || {}, ev.groups || {});
    } catch (err) {
      sayError(`Не удалось показать гирлянду: ${err.message}`);
      return;
    }
  }
  say('');
  refreshView();
  await reloadSceneIfFp();
}

/** Гирлянду собрать не вышло: кнопка возвращается на «Обычная» */
export function festiveFailed() {
  sayError('Гирлянду этой версии не удалось загрузить');
  refreshView();
}

/**
 * Кнопки вариантных стилей (skinfamilies)
 *
 * Один стиль означает, что стилей НЕТ: «Skin 0» - это сама модель, и
 * предлагать выбор из одного варианта незачем.
 */
export function showSkins(info) {
  const row = document.getElementById('skinbar');
  row.querySelectorAll('.tag').forEach((b) => b.remove());

  // Стили - это ДОПОЛНИТЕЛЬНЫЕ скины (bloody/clean и т.п.), а не команда и не
  // вариант: у тех свои тумблеры. Строить ряд по num_skins/roles было нельзя -
  // у командного оружия он повторял RED/BLU, а клик по такому «стилю» уходил
  // с ПОЗИЦИОННЫМ индексом и попадал в другую строку $texturegroup (у
  // праздничного гранатомёта - в Festive). Картинка не менялась
  const styles = (info && info.styles) || [];
  // Что нарисовано - для сверки с ответом Python (applyView)
  row.dataset.styles = JSON.stringify(styles);
  row.hidden = styles.length === 0;
  if (row.hidden) return;

  // Базовый стиль - первой кнопкой. Без него из варианта не выйти: в списке
  // styles его нет (там только варианты), и полоса становилась ловушкой
  for (const entry of [['Базовый', 0], ...styles]) {
    // (подпись, сырой индекс скина в модели) - индекс именно сырой, по нему
    // выбирают скин и превью, и сборка
    const [label, index] = Array.isArray(entry) ? entry : [String(entry), 0];
    const b = document.createElement('button');
    b.className = 'tag';
    b.dataset.skin = index;
    b.textContent = label;
    b.addEventListener('click', async () => {
      applyView(await api.setSkin(index));
      // Мазки у стиля свои: полоса частей должна показать его покраску
      if (!document.getElementById('partsbar').hidden) await refreshParts();
    });
    row.appendChild(b);
  }
}

/**
 * Полоса вариантного стиля под альбомом
 *
 * Стиль переопределяет базу ВЫБОРОЧНО: у него нет своих карточек, пока человек
 * не скажет, какой материал в нём меняет. Пустой альбом здесь - не поломка, но
 * молчать о нём нельзя: именно так это и выглядело - «текстура пропала».
 * Модель при этом показывает базу, а не пустоту.
 */
export function showStyleBar(st) {
  const bar = document.getElementById('stylebar');
  const style = st.style || 0;
  bar.hidden = !style;
  if (!style) return;

  const add = document.getElementById('style-add');
  const candidates = st.style_candidates || [];
  add.hidden = candidates.length === 0;

  document.getElementById('style-note').textContent = st.materials.length
    ? 'Материалы стиля: остальные наследуют базовую текстуру.'
    : 'Стиль пока целиком наследует базу. Добавьте материал, чтобы дать ему свою текстуру.';

  add.onclick = async () => {
    const material = await ask({
      title: 'Какой материал меняет этот стиль',
      list: candidates,
      ok: 'Добавить',
    });
    if (!material) return;
    applyView(await api.addToStyle(material));
  };
}
