/*
 * Текстуры эффекта: карточки материалов там, где у оружия альбом текстур
 *
 * Двойной клик или перетаскивание картинки - своя текстура, правая кнопка -
 * остальное. Разница между «своей картинкой» и «материалом игры» важна:
 * первая добавляет в мод новый файл, и в казуале обход sv_pure его не берёт.
 */

import * as api from '../api.js';
import { t } from '../i18n.js';
import { ask } from '../ask.js';
import { chooseImage } from '../util.js';
import { contextMenu } from '../menu.js';
import { stage, say, sayError, withParticles, particles } from '../stage.js';
import { bindAlbum } from '../album.js';
import { pSystem } from './state.js';

// Текстуры эффекта в движке
// Файл приходит с текстурами только открытого эффекта (см. load_particles):
// все 96 текстур item_fx - это 8,5 МБ и полторы секунды распаковки. Другой
// эффект того же файла, новая дочерняя система или смена материала добирают
// своё - и только когда движок говорит, что ему чего-то не хватает

/** Даёт движку текстуры эффекта `system`, которых у него ещё нет */
export async function loadEffectMaterials(system) {
  const w = particles();
  if (w && w.missingMaterials && !w.missingMaterials(system).length) return;
  const more = await api.particleEffectMaterials(system);
  withParticles((x) => x.addMaterials && x.addMaterials(more.materials, more.names));
}

/**
 * После правки систем: если эффекту теперь нужна текстура, которой у движка
 * нет (сменили материал, добавили дочернюю), - добрать и перестроить эффект.
 * Без недостающих - ничего: ползунки шлют правки потоком.
 */
export async function ensureEffectMaterials() {
  const w = particles();
  const system = pSystem;
  if (!w || !w.missingMaterials || !w.missingMaterials(system).length) return;
  await loadEffectMaterials(system);
  if (system === pSystem) withParticles((x) => x.setRootSystem(system));
}

// Текстуры эффекта
// Карточки материалов в той же половине сцены, где у оружия альбом текстур.
// Двойной клик или перетаскивание картинки - своя текстура, правая кнопка -
// остальное. Разница между «своей картинкой» и «материалом игры» важна:
// первая добавляет в мод новый файл, и в казуале обход sv_pure его не берёт

//: Потолок размера своей картинки (256/512/1024) - общий на все материалы,
//: живёт в конфиге. Картинку меньше потолка не растягиваем
const TEX_SIZES = [256, 512, 1024];
let texSize = 512;

/** Ставит сохранённый потолок. Зовётся из настроек вместе с раскладкой */
export function setTexSize(px) {
  if (TEX_SIZES.includes(Number(px))) texSize = Number(px);
}

//: Последняя своя картинка каждого материала - чтобы смена разрешения
//: пересобрала текстуру сразу. Файлы живут до перезапуска страницы
const lastFile = new Map();

/** Загружает картинку на диск и ставит её материалу */
export async function applyTexture(material, file, sheet) {
  if (!file) return;
  // Покадровая анимация: одна картинка вместо листа кадров остановит её
  if (sheet) {
    const yes = await ask({
      title: 'У текстуры покадровая анимация',
      text: 'Своя картинка встанет одним кадром, и анимация пропадёт.',
      ok: 'Всё равно заменить',
    });
    if (!yes) return;
  }
  say('Замена текстуры…');
  const path = await api.upload(file);
  const res = await api.setParticleTexture(material, path, texSize);
  if (res.error) { sayError(res.error); return; }
  lastFile.set(material, file);
  withParticles((w) => w.loadParticleData({ ...res, rootName: pSystem }));
  ensureEffectMaterials();
  await showParticleMaterials();
  say('');
}

/** Меню материала - то же, что было на карточке в 2D приложения */
export async function materialMenu(e, mat) {
  const chosen = await contextMenu(e, [
    { label: 'Своя картинка…', value: 'image' },
    { label: 'Игровая текстура из списка…', value: 'game' },
    null,
    { label: t('Разрешение своей картинки: {}').replace('{}', texSize), value: 'size' },
    { label: 'Переименовать материал…', value: 'rename' },
    { label: 'Вернуть текстуру игры', value: 'reset', disabled: !mat.custom },
  ]);
  if (!chosen) return;

  if (chosen === 'image') {
    await applyTexture(mat.name, await chooseImage(), mat.sheet);
    return;
  }
  if (chosen === 'game') {
    const all = await api.gameParticleMaterials();
    const pickd = await ask({
      title: 'Текстура из эффектов игры',
      text: 'Такой материал уже есть в игре, поэтому мод работает в казуале.',
      list: all.map((n) => ({ label: n, value: n })),
      ok: 'Заменить',
    });
    if (!pickd) return;
    const res = await api.setParticleMaterialToGame(mat.name, pickd);
    if (res.error) { sayError(res.error); return; }
    withParticles((w) => w.loadParticleData({ ...res, rootName: pSystem }));
    ensureEffectMaterials();
    await showParticleMaterials();
    return;
  }
  if (chosen === 'size') {
    const size = await ask({
      title: 'Разрешение своей картинки',
      text: 'Больше - чётче вблизи, но тяжелее мод. У надписей крита в игре 256.',
      list: TEX_SIZES.map((n) => ({ label: `${n}×${n}`, value: n })),
      ok: 'Выбрать',
    });
    if (!size || size === texSize) return;
    texSize = size;
    api.setUiState('particle_tex_size', size).catch(() => {});
    // Своя картинка уже стоит - пересобираем её в новом размере. После
    // перезапуска файла под рукой нет: новый размер возьмёт следующая
    const file = lastFile.get(mat.name);
    if (mat.custom && file) await applyTexture(mat.name, file, false);
    else if (mat.custom) say(t('Разрешение {} возьмёт следующая картинка').replace('{}', size));
    return;
  }
  if (chosen === 'rename') {
    const name = await ask({ title: 'Новый путь материала', value: mat.name });
    if (!name || name === mat.name) return;
    const res = await api.renameParticleMaterial(mat.name, name);
    if (res.error) { sayError(res.error); return; }
    withParticles((w) => w.loadParticleData({ ...res, rootName: pSystem }));
    ensureEffectMaterials();
    await showParticleMaterials();
    return;
  }
  if (chosen === 'reset') {
    const res = await api.resetParticleTexture(mat.name);
    if (res.error) { sayError(res.error); return; }
    withParticles((w) => w.loadParticleData({ ...res, rootName: pSystem }));
    ensureEffectMaterials();
    await showParticleMaterials();
  }
}

/** Рисует карточки материалов эффекта */
export async function showParticleMaterials() {
  // Материалы ВЫБРАННОГО эффекта, а не всего файла: в PCF систем десятки,
  // и чужая карточка предлагала бы заменить не ту текстуру
  const mats = await api.particleMaterials(pSystem);
  stage.tabs.innerHTML = '';
  stage.album.innerHTML = '';

  for (const mat of mats) {
    const tab = document.createElement('button');
    tab.className = 'mattab';
    // Заменённую текстуру отмечаем так же, как у оружия: точкой у имени
    tab.innerHTML = mat.custom ? '<span class="mattab__mark"></span>' : '';
    tab.append(mat.name.split(/[\\/]/).pop());
    stage.tabs.append(tab);

    const fig = document.createElement('figure');
    fig.className = 'frame';
    fig.dataset.mat = mat.name;
    fig.innerHTML = '<div class="frame__img"></div>'
                  + '<figcaption class="frame__name"></figcaption>';
    fig.querySelector('.frame__name').textContent = mat.name;
    fig.title = `${mat.width}×${mat.height}`
              + (mat.sheet ? t(' · покадровая анимация') : '');
    if (mat.dataUrl) {
      const img = document.createElement('img');
      img.src = mat.dataUrl;
      img.alt = mat.name;
      fig.querySelector('.frame__img').append(img);
    }

    fig.addEventListener('dblclick',
      async () => applyTexture(mat.name, await chooseImage(), mat.sheet));
    fig.addEventListener('contextmenu', (e) => materialMenu(e, mat));
    fig.addEventListener('dragover', (e) => {
      e.preventDefault();
      fig.classList.add('is-drop');
    });
    fig.addEventListener('dragleave', () => fig.classList.remove('is-drop'));
    fig.addEventListener('drop', (e) => {
      e.preventDefault();
      fig.classList.remove('is-drop');
      applyTexture(mat.name, e.dataTransfer.files[0], mat.sheet);
    });

    stage.album.append(fig);
  }
  bindAlbum();
}
