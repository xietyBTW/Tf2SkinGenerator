/*
 * Текстуры эффекта: карточки материалов там, где у оружия альбом текстур.
 *
 * Двойной клик или перетаскивание картинки — своя текстура, правая кнопка —
 * остальное. Разница между «своей картинкой» и «материалом игры» важна:
 * первая добавляет в мод новый файл, и в казуале обход sv_pure его не берёт.
 */

import * as api from '../api.js';
import { t } from '../i18n.js';
import { ask } from '../ask.js';
import { chooseImage } from '../util.js';
import { contextMenu } from '../menu.js';
import { stage, say, withParticles } from '../stage.js';
import { bindAlbum } from '../album.js';
import { pSystem } from './state.js';

// ── Текстуры эффекта ─────────────────────────────────────────────────────
// Карточки материалов в той же половине сцены, где у оружия альбом текстур.
// Двойной клик или перетаскивание картинки — своя текстура, правая кнопка —
// остальное. Разница между «своей картинкой» и «материалом игры» важна:
// первая добавляет в мод новый файл, и в казуале обход sv_pure его не берёт.

/** Загружает картинку на диск и ставит её материалу. */
export async function applyTexture(material, file, sheet) {
  if (!file) return;
  // Покадровая анимация: одна картинка вместо листа кадров остановит её.
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
  const res = await api.setParticleTexture(material, path);
  if (res.error) { say(res.error); return; }
  withParticles((w) => w.loadParticleData({ ...res, rootName: pSystem }));
  await showParticleMaterials();
  say('');
}

/** Меню материала — то же, что было на карточке в 2D приложения. */
export async function materialMenu(e, mat) {
  const chosen = await contextMenu(e, [
    { label: 'Своя картинка…', value: 'image' },
    { label: 'Игровая текстура из списка…', value: 'game' },
    null,
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
    if (res.error) { say(res.error); return; }
    withParticles((w) => w.loadParticleData({ ...res, rootName: pSystem }));
    await showParticleMaterials();
    return;
  }
  if (chosen === 'rename') {
    const name = await ask({ title: 'Новый путь материала', value: mat.name });
    if (!name || name === mat.name) return;
    const res = await api.renameParticleMaterial(mat.name, name);
    if (res.error) { say(res.error); return; }
    withParticles((w) => w.loadParticleData({ ...res, rootName: pSystem }));
    await showParticleMaterials();
    return;
  }
  if (chosen === 'reset') {
    const res = await api.resetParticleTexture(mat.name);
    if (res.error) { say(res.error); return; }
    withParticles((w) => w.loadParticleData({ ...res, rootName: pSystem }));
    await showParticleMaterials();
  }
}

/** Рисует карточки материалов эффекта. */
export async function showParticleMaterials() {
  // Материалы ВЫБРАННОГО эффекта, а не всего файла: в PCF систем десятки,
  // и чужая карточка предлагала бы заменить не ту текстуру.
  const mats = await api.particleMaterials(pSystem);
  stage.tabs.innerHTML = '';
  stage.album.innerHTML = '';

  for (const mat of mats) {
    const tab = document.createElement('button');
    tab.className = 'mattab';
    // Заменённую текстуру отмечаем так же, как у оружия: точкой у имени.
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
