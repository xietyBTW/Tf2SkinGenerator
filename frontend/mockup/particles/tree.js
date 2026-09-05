/*
 * Каталог систем PCF: дерево слева и загрузка файла.
 *
 * Разбор PCF идёт ОТВЕТОМ, а не событием: он занимает около секунды, зато
 * приезжает целиком (системы, материалы с развёрнутыми в PNG текстурами и
 * дерево вложенности), и показывать до этого всё равно нечего.
 */

import * as api from '../api.js';
import { t } from '../i18n.js';
import { stage, say, withParticles } from '../stage.js';
import { closeCat } from '../layout.js';
import { els } from '../catalog.js';
import { pcfNodes, pcfTree, pcfCollapsed, pSystem, setTree } from './state.js';
import { systemMenu } from './actions.js';
import { showParams } from './params.js';
import { syncHistory } from './playback.js';
import { showParticleMaterials } from './materials.js';
import { cpBox, cpFillIndexes } from './points.js';

/**
 * Рисует дерево систем.
 *
 * Ребёнок стоит под родителем с отступом, у родителя — треугольник. Плоским
 * списком 104 системы class_fx читаются как свалка, а вложенность в PCF
 * настоящая: родитель тянет детей за собой.
 */
export function fillTree(nodes, selected) {
  els.grid.innerHTML = '';

  const walk = (list, depth) => {
    for (const node of list) {
      const row = document.createElement('div');
      row.className = 'tree__row';
      row.style.setProperty('--depth', depth);

      const twist = document.createElement('button');
      twist.className = 'tree__twist';
      twist.type = 'button';
      if (node.kids.length) {
        const open = !pcfCollapsed.has(node.key);
        twist.textContent = open ? '−' : '+';
        twist.title = open ? 'Свернуть' : 'Развернуть';
        twist.addEventListener('click', (e) => {
          e.stopPropagation();
          if (open) pcfCollapsed.add(node.key);
          else pcfCollapsed.delete(node.key);
          fillTree(pcfNodes, pSystem);
        });
      } else {
        twist.disabled = true;
      }

      const name = document.createElement('button');
      name.className = 'tree__name' + (node.key === selected ? ' is-active' : '');
      name.type = 'button';
      name.textContent = node.name;
      name.title = node.kids.length
        ? `${node.name} · дочерних: ${node.kids.length}` : node.name;
      name.addEventListener('click', () => pickSystem(name, node));
      name.addEventListener('contextmenu', (e) => systemMenu(e, node.key));

      row.append(twist, name);
      els.grid.append(row);

      if (node.kids.length && !pcfCollapsed.has(node.key)) {
        walk(node.kids, depth + 1);
      }
    }
  };

  walk(nodes, 0);
}

/** Переводит кадр на движок частиц (или обратно на вьювер моделей). */
export function showParticleFrame(on) {
  // Адрес ставим при первом входе: второй three.js на неоткрытой вкладке
  // грузить незачем.
  if (on && !stage.pframe.src) stage.pframe.src = '/viewer/particles3d.html';
  stage.pframe.hidden = !on;
  stage.frame.hidden = on;
}

/** Загружает PCF и показывает первый эффект. */
export async function loadPcf(source, label = '') {
  const short = label || source.replace(/^particles\//, '');
  say('Разбор ' + short + '…');
  els.grid.innerHTML = '';
  const data = await api.loadParticles(source);
  if (data.error) { say(data.error); return; }

  setTree(data.tree || []);
  // Новый файл — свои узлы; старое состояние свёрнутости к ним не относится.
  pcfCollapsed.clear();
  // Дочерние сворачиваем сразу: сверху видно корни эффектов, а не всё подряд.
  for (const n of pcfNodes) if (n.kids.length) pcfCollapsed.add(n.key);

  withParticles((w) => {
    w.setLanguage && w.setLanguage(api.lang());
    w.loadParticleData(data);
  });
  document.querySelector('.title__name').textContent =
    short.replace(/\.pcf$/, '');
  document.querySelector('.title__meta').textContent =
    short + ' · ' + pcfTree.length + t(' систем, корней ') + pcfNodes.length;

  fillTree(pcfNodes, data.rootName);
  els.note.hidden = pcfTree.length > 0;
  els.note.textContent = 'В этом файле систем нет.';
  say('');
  await syncHistory();
  if (data.rootName) await showParams(data.rootName);
  await showParticleMaterials();
}

/** Выбор системы: движок строит эффект от названного узла. */
export function pickSystem(button, item) {
  els.grid.querySelectorAll('.tree__name, .pick')
          .forEach((b) => b.classList.remove('is-active'));
  button.classList.add('is-active');
  document.querySelector('.title__name').textContent = item.name;
  closeCat();
  withParticles((w) => w.setRootSystem(item.key));
  showParams(item.key);
  showParticleMaterials();
  if (!cpBox.hidden) cpFillIndexes();
}
