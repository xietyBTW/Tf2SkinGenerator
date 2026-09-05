/*
 * Действия над эффектом: модули, атрибуты, системы, дети, сборка мода.
 *
 * Один разбор ответа на всех: правка структуры отдаёт свежие systems и tree,
 * и после неё надо обновить и кадр, и каталог, и панель свойств.
 */

import * as api from '../api.js';
import { ask } from '../ask.js';
import { contextMenu } from '../menu.js';
import { say, withParticles } from '../stage.js';
import { setStatus } from '../layout.js';
import { pcfNodes, pcfTree, pSystem, setTree, setSystem } from './state.js';
import { fillTree } from './tree.js';
import { syncHistory } from './playback.js';
import { showParams } from './params.js';


// ── Действия над системой ────────────────────────────────────────────────
// Один разбор ответа на всех: правка структуры отдаёт свежие systems и tree,
// и после неё надо обновить и кадр, и каталог, и панель свойств.

export async function applyStructure(res, { reselect = null } = {}) {
  if (!res || res.error) { say(res?.error || 'не получилось'); return false; }
  if (res.tree) {
    setTree(res.tree);
    const keep = reselect || res.selected || pSystem;
    // Систему могли переименовать или удалить — тогда показываем первую.
    setSystem(pcfTree.some((n) => n.key === keep) ? keep
                : (pcfTree[0] ? pcfTree[0].key : ''));
    fillTree(pcfNodes, pSystem);
    document.querySelector('.title__name').textContent = pSystem;
  }
  if (res.systems) {
    withParticles((w) => w.updateSystems(res.systems, pSystem));
  }
  if (pSystem) await showParams(pSystem);
  await syncHistory();
  return true;
}

/** Выбор группы и модуля для «Модуль +». */
export async function askModule() {
  const group = await ask({
    title: 'В какую группу',
    list: [
      { label: 'operators — что делает с частицей по ходу жизни', value: 'operators' },
      { label: 'initializers — каким рождается', value: 'initializers' },
      { label: 'renderers — чем рисуется', value: 'renderers' },
      { label: 'emitters — как выпускаются', value: 'emitters' },
      { label: 'forces — что на неё давит', value: 'forces' },
      { label: 'constraints — что ограничивает', value: 'constraints' },
    ],
    ok: 'Дальше',
  });
  if (!group) return null;
  const names = await api.particleModules(group);
  const fn = await ask({
    title: 'Какой модуль',
    text: 'Сверху — ходовые, ниже всё, что встречается в эффектах игры.',
    list: names.map((n) => ({ label: n, value: n })),
    ok: 'Добавить',
  });
  return fn ? { group, fn } : null;
}

/** Адрес модуля для действий: тот узел, на котором открыли меню. */
export function currentModule() {
  if (ctxNode && ctxNode.index !== null) {
    return { group: ctxNode.group || null, index: ctxNode.index };
  }
  const open = document.querySelector('.expert__mod[open]');
  return open && open.dataset.group !== undefined
    ? { group: open.dataset.group || null, index: Number(open.dataset.index) }
    : null;
}

export const PACTS = {
  async module() {
    // Меню открыто на группе — она и есть ответ на первый вопрос.
    const group = ctxNode && ctxNode.group && ctxNode.group !== 'children'
      ? ctxNode.group : null;
    let pick;
    if (group) {
      const names = await api.particleModules(group);
      const fn = await ask({
        title: 'Какой модуль',
        text: 'Сверху — ходовые, ниже всё, что встречается в эффектах игры.',
        list: names.map((n) => ({ label: n, value: n })),
        ok: 'Добавить',
      });
      pick = fn ? { group, fn } : null;
    } else {
      pick = await askModule();
    }
    if (!pick) return;
    await applyStructure(
      await api.addParticleModule(pSystem, pick.group, pick.fn));
  },

  async delmodule() {
    const mod = currentModule();
    if (!mod) return;
    const yes = await ask({ title: 'Удалить модуль?', ok: 'Удалить' });
    if (yes) {
      await applyStructure(
        await api.removeParticleModule(pSystem, mod.group, mod.index));
    }
  },

  async delattr() {
    if (!ctxNode || !ctxNode.attr) return;
    await applyStructure(await api.removeParticleAttr(
      pSystem, ctxNode.group || null, ctxNode.index, ctxNode.attr));
  },

  async detach() {
    if (!ctxNode || ctxNode.index === null) return;
    await applyStructure(
      await api.removeParticleChild(pSystem, ctxNode.index));
  },

  async attr() {
    // Параметр добавляют В МОДУЛЬ: какой именно — тот, что раскрыт в дереве.
    const mod = currentModule();
    if (!mod) {
      say('Раскройте модуль в экспертном режиме — параметр добавляется в него');
      return;
    }
    const missing = await api.particleMissingAttrs(pSystem, mod.group, mod.index);
    if (!missing.length) { say('Все известные параметры уже заданы'); return; }
    const name = await ask({
      title: 'Какой параметр',
      text: 'Значение подставится такое, как в эффектах игры.',
      list: missing.map((a) => ({ label: a.name, value: a.name, hint: a.help })),
      ok: 'Добавить',
    });
    if (!name) return;
    const attr = missing.find((a) => a.name === name);
    await applyStructure(await api.addParticleAttr(
      pSystem, mod.group, mod.index, attr.name, attr.t, attr.v));
  },

  /** Копирует ровно то, на чём открыли меню: параметр, модуль или группу. */
  async copyone() {
    const n = ctxNode || {};
    return PACTS.copy({ group: n.group || null, index: n.index, attr: n.attr });
  },

  async copy(scope = {}) {
    const res = await api.copyParticleParams(
      pSystem, scope.group ?? null, scope.index ?? null, scope.attr ?? null);
    if (res.error) { say(res.error); return; }
    const text = JSON.stringify({ tf2sgParticleParams: res.payload });
    try {
      await navigator.clipboard.writeText(text);
      say('Параметры скопированы — можно вставить в другую систему или отдать ИИ');
    } catch {
      // Доступ к буферу может быть закрыт настройками браузера — тогда
      // показываем набор, чтобы его можно было выделить и скопировать самому.
      await ask({ title: 'Скопируйте набор параметров', value: text,
                  text: 'Буфер обмена недоступен — выделите и скопируйте.' });
    }
  },

  async paste() {
    let text = '';
    try { text = await navigator.clipboard.readText(); } catch { text = ''; }
    // Чтение буфера может быть запрещено — тогда просим вставить руками.
    if (!text) {
      text = await ask({ title: 'Вставьте набор параметров', value: '',
                         text: 'JSON с ключом tf2sgParticleParams' });
      if (!text) return;
    }
    let payload = null;
    try {
      payload = JSON.parse(text).tf2sgParticleParams;
    } catch (e) { say('В буфере не JSON: ' + e.message); return; }
    if (!payload) { say('В JSON нет раздела tf2sgParticleParams'); return; }

    // Полный набор можно влить поверх или заменить систему целиком.
    let mode = 'overwrite';
    if (payload.full) {
      mode = await ask({
        title: 'Как вставить',
        list: [
          { label: 'Поверх — совпадающие параметры заменить', value: 'overwrite' },
          { label: 'Без замены — дописать только недостающее', value: 'keep' },
          { label: 'Полная замена — снести модули системы', value: 'replace' },
        ],
        ok: 'Вставить',
      });
      if (!mode) return;
    }
    const res = await api.pasteParticleParams(pSystem, payload, mode);
    if (await applyStructure(res) && res.report?.length) {
      say('Вставлено, но часть пропущена: ' + res.report[0]);
    }
  },

  async duplicate() {
    const name = await ask({ title: 'Имя копии', value: pSystem + '_copy' });
    if (!name) return;
    await applyStructure(await api.duplicateParticleSystem(pSystem, name),
                         { reselect: name });
  },

  async rename() {
    const name = await ask({ title: 'Новое имя системы', value: pSystem });
    if (!name || name === pSystem) return;
    await applyStructure(await api.renameParticleSystem(pSystem, name),
                         { reselect: name });
  },

  async child() {
    // Дочернюю можно подцепить и отцепить — обе операции об одном списке.
    const kids = await api.particleChildren(pSystem);
    const what = await ask({
      title: 'Дочерние системы',
      text: kids.length ? kids.map((k) => k.name).join(', ') : 'Пока ни одной.',
      list: [
        { label: 'Подцепить существующую…', value: 'add' },
        ...(kids.length ? [{ label: 'Отцепить…', value: 'remove' }] : []),
      ],
      ok: 'Дальше',
    });
    if (what === 'add') {
      const child = await ask({
        title: 'Какую систему подцепить',
        list: pcfTree.filter((n) => n.key !== pSystem)
                     .map((n) => ({ label: n.key, value: n.key })),
        ok: 'Подцепить',
      });
      if (child) await applyStructure(await api.addParticleChild(pSystem, child));
    } else if (what === 'remove') {
      const idx = await ask({
        title: 'Какую отцепить',
        list: kids.map((k) => ({ label: k.name, value: String(k.index) })),
        ok: 'Отцепить',
      });
      if (idx !== null) {
        await applyStructure(
          await api.removeParticleChild(pSystem, Number(idx)));
      }
    }
  },

  async layer() {
    const res = await api.addParticleLayer(pSystem);
    await applyStructure(res, { reselect: res.selected });
    if (!res.error) say('Слой добавлен — задайте ему параметры и текстуру');
  },

  /** Родные цвета текстур: у системы и детей снимаются модули тинта. */
  async natural() {
    const yes = await ask({
      title: 'Показать родные цвета текстур?',
      text: 'У этой системы и её дочерних будут удалены модули цвета, '
          + 'а базовый цвет станет белым.',
      ok: 'Убрать подкраску',
    });
    if (!yes) return;
    const res = await api.useParticleTextureColors(pSystem);
    if (res.error) { say(res.error); return; }
    withParticles((w) => w.loadParticleData({ ...res, rootName: pSystem }));
    await showParams(pSystem);
    say(res.removed ? `Удалено модулей цвета: ${res.removed}`
                    : 'Модулей цвета не было — текстуры уже в родных цветах');
  },

  async remove() {
    const yes = await ask({ title: 'Удалить систему?', text: pSystem,
                            ok: 'Удалить' });
    if (!yes) return;
    await applyStructure(await api.removeParticleSystem(pSystem));
  },
};

//: Копирование есть у всего, кроме детей: там ссылки, а не параметры. Первый
//: пункт зависит от узла — копируют либо то, на чём щёлкнули, либо всё.
export function copyItems(label) {
  return [
    ...(label ? [{ label, value: 'copyone' }] : []),
    { label: 'Копировать все параметры системы', value: 'copy' },
    { label: 'Вставить параметры', value: 'paste' },
  ];
}

/** Меню системы — то же, что было на дереве систем в приложении. */
export async function systemMenu(e, name) {
  setSystem(name);
  const chosen = await contextMenu(e, [
    { label: 'Добавить слой со своей текстурой…', value: 'layer' },
    null,
    { label: 'Переименовать систему…', value: 'rename' },
    { label: 'Дублировать систему…', value: 'duplicate' },
    { label: 'Добавить дочернюю…', value: 'child' },
    { label: 'Удалить систему', value: 'remove' },
    null,
    { label: 'Цвета текстуры (снять подкраску)', value: 'natural' },
    null,
    ...copyItems(null),
  ]);
  if (chosen) await PACTS[chosen]();
}

/** Меню в дереве свойств. Что предложить — решает узел под курсором. */
export async function expertMenu(e, node) {
  const { group, index, attr } = node;
  let items;
  if (group === 'children') {
    items = index === null
      ? [{ label: 'Добавить дочернюю…', value: 'child' }]
      : [{ label: 'Отцепить дочернюю', value: 'detach' }];
  } else if (index === null) {
    // Заголовок группы: сюда добавляют модуль, отсюда копируют её целиком.
    const label = group ? `Копировать группу «${group}»` : null;
    items = [...copyItems(label), null,
             { label: 'Добавить модуль…', value: 'module' }];
  } else if (attr) {
    items = [...copyItems(`Копировать параметр «${attr}»`), null,
             { label: 'Добавить параметр…', value: 'attr' },
             { label: 'Удалить параметр (вернуть умолчание)', value: 'delattr' }];
  } else {
    items = [...copyItems('Копировать этот модуль'), null,
             { label: 'Добавить параметр…', value: 'attr' },
             { label: 'Удалить модуль', value: 'delmodule' }];
  }

  const chosen = await contextMenu(e, items);
  if (!chosen) return;
  // Узел под курсором и есть адрес: кнопке «Параметр +» иначе пришлось бы
  // угадывать, в какой модуль добавлять.
  ctxNode = node;
  await PACTS[chosen]();
  ctxNode = null;
}

//: Узел, на котором открыли меню — адрес для действий над модулем.
export let ctxNode = null;

/**
 * Сборка мода с эффектом.
 *
 * Сначала проверка: типовые поломки (нет рендерера, нулевой максимум частиц)
 * видно только в игре, и находить их там — это заново собирать и перезапускать
 * TF2. Часть находок чинится сама.
 */
export async function buildParticles() {
  setStatus('Проверка эффекта…', true);
  const lint = await api.particleLint(pSystem);
  if (lint.error) { setStatus(lint.error, false); return; }

  const bad = lint.findings || [];
  if (bad.length) {
    const fixable = bad.filter((f) => f.fixable).length;
    const answer = await ask({
      title: 'Проверка перед сборкой',
      text: bad.slice(0, 5).map((f) => (f.system ? f.system + ': ' : '') + f.message)
               .join('\n') + (bad.length > 5 ? `\n…и ещё ${bad.length - 5}` : ''),
      list: [
        ...(fixable ? [{ label: `Исправить (${fixable}) и собрать`, value: 'fix' }] : []),
        { label: 'Собрать как есть', value: 'as_is' },
      ],
      ok: 'Дальше',
    });
    if (!answer) { setStatus('Готово', false); return; }
    if (answer === 'fix') {
      const fixed = await api.fixParticleLint(pSystem);
      await applyStructure(fixed);
    }
  }

  const name = await ask({ title: 'Имя файла мода',
                           value: (pSystem || 'particles') + '.vpk' });
  if (!name) { setStatus('Готово', false); return; }

  setStatus('Сборка VPK…', true);
  const res = await api.exportParticlesVpk(name);
  if (res.error) { setStatus(res.error, false); return; }

  // Обход sv_pure в казуале не грузит PCF больше оригинального: выросший
  // файл просто не заработает, и знать об этом надо до похода в игру.
  const over = res.overflow;
  setStatus(over && over > 0
    ? `Собрано, но PCF на ${over} Б больше оригинала — в казуале не загрузится`
    : `Собрано: ${res.path}`, false);
}
