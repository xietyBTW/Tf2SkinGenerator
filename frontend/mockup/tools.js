/*
 * Меню инструментов над кадром.
 *
 * Набор пунктов зависит от раздела (`applyToolsMenu` в каталоге): у эффекта
 * свои, у предмета свои. Здесь только то, что пункты делают.
 */

import * as api from './api.js';
import { ask } from './ask.js';
import { chooseFile } from './util.js';
import { say } from './stage.js';
import { loadPcf, pSystem } from './particles/index.js';
import { floating, panel, closeCat } from './layout.js';

// Инструменты: пока подключён экспорт UV-шаблона — он нужен, чтобы глазами
// сверить, куда какой кусок текстуры садится на модель.
document.getElementById('tools').addEventListener('click', async (e) => {
  const item = e.target.closest('.menu__item');
  if (!item) return;

  if (item.dataset.tool === 'open') {
    // Файл с диска кладём во временную папку и грузим оттуда: Python берёт
    // путь, а страница пути к выбранному файлу не знает и знать не должна.
    const file = await chooseFile('.pcf');
    if (!file) return;
    say('Загрузка ' + file.name + '…');
    try {
      await loadPcf(await api.upload(file), file.name);
    } catch (err) {
      say('Не удалось открыть: ' + err.message);
    }
    return;
  }
  if (item.dataset.tool === 'save') {
    const path = await ask({ title: 'Куда сохранить PCF',
                             value: 'export/' + (pSystem || 'effect') + '.pcf' });
    if (!path) return;
    const res = await api.saveParticles(path);
    say(res.error || `Сохранено: ${res.path} (${res.size} Б)`);
    return;
  }
  if (item.dataset.tool === 'ref' || item.dataset.tool === 'ref-ai') {
    const forAi = item.dataset.tool === 'ref-ai';
    say('Сбор справочника…');
    const res = await api.particleReference('', forAi);
    say(res.error || `Справочник сохранён: ${res.path}`);
    return;
  }

  if (item.dataset.tool === 'uv') {
    say('Построение UV-шаблона…');
    const res = await api.exportUv(1024);
    if (res.error) say(res.error);
    return;
  }

  // Извлечение модели двухшаговое: сначала Python готовит файлы во временной
  // папке, потом человек выбирает, что сохранить (событие extract_files).
  if (item.dataset.tool === 'model') {
    say('Извлечение модели…');
    const res = await api.extractModel();
    if (res.error) say(res.error);
    return;
  }

  if (item.dataset.tool === 'texture') {
    const res = await api.extractTexture();
    if (res.error) { say(res.error); return; }
    // У тела персонажа текстур два десятка — какие брать, решает человек.
    if (res.need_textures) {
      const picked = await ask({
        title: 'Какие текстуры извлечь',
        list: res.need_textures, multi: true, chosen: res.need_textures,
        ok: 'Извлечь',
      });
      if (!picked || !picked.length) return;
      const again = await api.extractTexture(picked);
      if (again.error) say(again.error);
      return;
    }
    say('Извлечение текстуры…');
    return;
  }

  if (item.dataset.tool === 'merge') { await mergeMods(); return; }
});

/**
 * Объединение собранных модов в один VPK.
 *
 * Моды, трогающие одно оружие, друг друга затирают — про такие Python
 * предупреждает до запуска и ждёт подтверждения.
 */
export async function mergeMods() {
  const files = await api.exportVpks();
  if (!files.length) { say('В папке экспорта нет собранных модов'); return; }

  const picked = await ask({ title: 'Какие моды объединить', list: files,
                             multi: true, ok: 'Далее' });
  if (!picked || picked.length < 2) return;

  const name = await ask({ title: 'Имя выходного файла', value: 'merged_mod.vpk' });
  if (!name) return;

  let res = await api.mergeVpk(picked, name);
  if (res.duplicates) {
    const lines = Object.entries(res.duplicates)
      .map(([weapon, mods]) => `${weapon}: ${mods.join(', ')}`).join('\n');
    const go = await ask({
      title: 'Моды трогают одно оружие',
      text: lines + '\nОдин перекроет другой. Продолжить?',
      ok: 'Объединить',
    });
    if (!go) return;
    res = await api.mergeVpk(picked, name, true);
  }
  if (res.error) say(res.error);
  else say('Объединение…');
}

// ── Меню инструментов ───────────────────────────────────────────────────
export const tools = document.getElementById('tools');
document.getElementById('opentools').addEventListener('click', (e) => {
  e.stopPropagation();
  tools.hidden = !tools.hidden;
});
document.addEventListener('click', (e) => {
  if (!tools.hidden && !e.target.closest('.menu')) tools.hidden = true;
});

document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  if (!tools.hidden) { tools.hidden = true; return; }
  if (floating() && !panel().hidden) { panel().hidden = true; return; }
  closeCat();
});
