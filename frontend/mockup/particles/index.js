/*
 * Раздел частиц: что от него видно снаружи.
 *
 * Отдельный источник каталога и отдельный движок в кадре. Внутри раздел
 * разложен по своим модулям; здесь собрана та горсть имён, за которой
 * обращаются каталог, инструменты и точка входа.
 */

import './playback.js';
import './resize.js';

export { pcfNodes, pSystem, setSystem } from './state.js';
export { fillTree, showParticleFrame, loadPcf, pickSystem } from './tree.js';
export { showParams } from './params.js';
export { showParticleMaterials } from './materials.js';
export { systemMenu, buildParticles } from './actions.js';
export { cpBox, cpFillIndexes } from './points.js';
