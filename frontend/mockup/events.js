/*
 * События воркеров.
 *
 * Порядок важен. У ОДНОМАТЕРИАЛЬНОЙ модели текстура приезжает прямо в
 * model_ready, и события materials не будет вовсе; у многоматериальной
 * materials придёт следом и перепишет альбом.
 */

import * as api from './api.js';
import { say, sayBusy, withViewer } from './stage.js';
import { setStatus } from './layout.js';
import { ask } from './ask.js';
import { showReport } from './diagnostics.js';
import { askForTexture } from './build.js';
import {
  refreshView,
  showModel,
  rememberModel,
  showMaterials,
  showSkins,
  showFirstPerson,
  showFpActions, applyFpClip,
  showSpecialScene,
  showSkybox,
  addFrame,
  setCardTitles,
} from './preview.js';

// ── События воркеров ─────────────────────────────────────────────────────
// Порядок важен. У ОДНОМАТЕРИАЛЬНОЙ модели текстура приезжает прямо в
// model_ready и события materials не будет вовсе; у многоматериальной
// materials придёт следом и перепишет альбом. Поэтому один кадр — не особый
// случай, а тот же альбом длиной в единицу.

api.subscribe((ev) => {
  switch (ev.event) {
    // Ход работы — с задержкой: короткая загрузка успеет закончиться, и
    // подпись не мигнёт (см. sayBusy).
    case 'progress':
      sayBusy(ev.text);
      break;

    case 'model_ready':
      // Альбом наполняется ТОЛЬКО из applyView: два источника расходились —
      // кадр из события затирался пустым состоянием и обратно.
      rememberModel(ev);
      showModel(ev);
      break;

    // Материалы, командные текстуры и вариант меняют то, ЧТО показывать.
    // Пересчитывает это Python, поэтому спрашиваем состояние целиком.
    case 'materials':
    case 'blu_materials':
    case 'blu_ready':
    case 'australium':
    // «Синий есть, но он равен красному» меняет только подпись кнопки —
    // состояние уже знает об этом (blu_matches_red).
    case 'blu_same_as_red':
      refreshView();
      break;

    case 'animated':
      // Многокадровый VTF: анимацию крутит сам вьювер.
      withViewer((w) => w.loadAnimatedTexture(
        ev.frames.map(api.fileUrl), ev.fps, ''));
      showMaterials(['текстура'], { 'текстура': ev.frames[0] });
      break;

    case 'render_hints':
      withViewer((w) => w.setMaterialHints(ev.hints));
      break;

    case 'skins':
      showSkins(ev.info);
      break;

    // Вид от первого лица: сцена приходит либо мешем, либо со скелетом.
    // Текстуры к ней приезжают обычным materials, поэтому здесь только меш.
    case 'fp_ready':
      showFirstPerson(ev.obj, ev.rig);
      break;

    case 'fp_animated':
      withViewer((w) => {
        // Риг СТРОГО до сцены: applyTransform читает его при показе модели,
        // иначе камера встаёт орбитой и кадр оказывается пустым.
        w.setViewRig(ev.rig);
        w.loadViewmodelAnimated(ev.scene, 0);
      });
      say('');
      break;

    // Какие анимации есть у этого оружия — знает только воркер: список
    // приходит из QC модели, общего перечня не существует.
    // Сменили анимацию у показанной сцены: приехали ТОЛЬКО дорожки.
    case 'fp_clip':
      applyFpClip(ev.clip);
      break;

    case 'fp_actions':
      showFpActions(ev.actions);
      break;

    case 'fp_editable':
      // Правится только оружие: руки в сцене стоковые и чужие.
      withViewer((w) => w.setEditableMeshNames(ev.names));
      break;

    // Спец-режимы. У спрея модели нет вовсе, у крита и эффектов смерти есть
    // сцена с персонажем — её строит вьювер.
    case 'texture_only':
      showSpecialScene(ev);
      refreshView();
      break;

    case 'skybox':
      showSkybox(ev.faces);
      break;

    case 'build_progress':
      setStatus(ev.text || 'Сборка…', true);
      break;

    // Сборке не хватило текстуры для материала: она СТОИТ и ждёт ответа.
    // Пока человек думает, воркер держит паузу (300 секунд), поэтому вопрос
    // задаём сразу и не копим.
    case 'need_texture':
      askForTexture(ev.material);
      break;

    case 'build_done':
      setStatus(ev.message || (ev.ok ? 'Готово' : 'Ошибка сборки'), false);
      break;

    case 'uv_ready':
      if (!ev.ok || !ev.path) { say(ev.message || 'UV-шаблон не построен'); break; }
      // Кладём рядом с текстурами: сравнивать развёртку с текстурой удобнее
      // в одном ряду, чем в отдельном окне.
      // У многоматериальной модели разметок несколько: у каждого материала
      // своя текстура и своя развёртка в тех же координатах.
      const uvFiles = (ev.paths && ev.paths.length) ? ev.paths : [ev.path];
      say(uvFiles.length > 1 ? 'UV-шаблоны: ' + uvFiles.length + ' шт.'
                             : 'UV-шаблон: ' + uvFiles[0]);
      uvFiles.forEach((file, index) => addFrame(
        uvFiles.length > 1 ? 'UV-шаблон ' + (index + 1) : 'UV-шаблон', file));
      break;

    // Файлы декомпиляции готовы: пока выбор не сделан, за ними числится
    // временная папка — отказ тоже надо отправить, иначе она останется.
    case 'extract_files':
      if (!ev.ok) { say(ev.message || 'Модель не извлечена'); break; }
      ask({ title: 'Что сохранить в папку экспорта', list: ev.files,
            multi: true, chosen: ev.selected || [], ok: 'Сохранить' })
        .then(async (picked) => {
          const res = await api.exportModelFiles(picked || []);
          if (res.error) say(res.error);
          else if (res.cancelled) say('Извлечение отменено');
        });
      break;

    // Мод из VPK: карточки строятся из его VTF, а не из материалов игровой
    // модели. Подписи запоминаем — дальше альбом рисуется обычным путём.
    case 'mod_cards':
      setCardTitles(Object.fromEntries(
        ev.cards.map((c) => [c.name, c.display_name || c.name])));
      refreshView();
      break;

    // Режим «только геометрия»: пришла игровая текстура, а модель на экране
    // остаётся пользовательской — красим её глобально.
    case 'cards_ready':
      if (ev.texture) withViewer((w) => w.updateTextureFromDataUrl(api.fileUrl(ev.texture)));
      break;

    case 'diagnostics':
      showReport(ev);
      break;

    case 'tool_done':
      say(ev.message || (ev.ok ? 'Готово' : 'Не получилось'));
      break;

    case 'failed':
      say(ev.error);
      break;

    default:
      break;
  }
});
