/**
 * Что двигает гизмо перемещения: системы, модули и живые частицы
 *
 * «Весь эффект» едет точкой «начало эффекта» (оператор Effect origin, его
 * ставит src/services/particle_editor/origin.py): точка N = точка 0 +
 * смещение в осях точки 0, ссылки эффекта на место точки 0 ведут на N. Так
 * едет всё, что опирается на точку, а не только места рождения: вращение
 * вокруг оси, притяжение, привязка. «Эта система» двигает только место
 * рождения корня.
 */

//: Имена своих модулей - те же, что в origin.py
export const ORIGIN_OP = 'Effect origin';
export const ORIGIN_OFFSET = 'Effect origin offset';
const SLOTS = ['first', 'second', 'third', 'fourth'];
//: Базис точки, пока движок его не дал: тот же, что CP_DEFAULT_BASIS движка
const DEFAULT_BASIS = { fwd: [0, 1, 0], right: [1, 0, 0], up: [0, 0, 1] };

/** Атрибут модуля из systems_json ({"t","v"}), с дефолтом */
export function modAttr(mod, name, fallback) {
  const tv = mod.attrs && mod.attrs[name];
  return (tv === undefined || tv === null) ? fallback : tv.v;
}

export function moduleFn(mod) {
  return (mod.functionName || '').trim().toLowerCase();
}

export function findModule(def, fnLower) {
  const list = def.initializers || [];
  for (let i = 0; i < list.length; i++)
    if (moduleFn(list[i]) === fnLower) return i;
  return -1;
}

/** Номер оператора «начало эффекта» у корня, -1 - его нет */
export function findOrigin(def) {
  return (def?.operators || []).findIndex((m) => m.name === ORIGIN_OP);
}

/** Локальные координаты точки -> мир: x*Forward - y*Right + z*Up, как у Valve */
export function toWorld(b, v) {
  b = b || DEFAULT_BASIS;
  return [0, 1, 2].map((i) => v[0] * b.fwd[i] - v[1] * b.right[i] + v[2] * b.up[i]);
}

/** Обратно: оси ортонормированы, обратная матрица - транспонированная */
export function toLocal(b, w) {
  b = b || DEFAULT_BASIS;
  const dot = (a) => w[0] * a[0] + w[1] * a[1] + w[2] * a[2];
  return [dot(b.fwd), -dot(b.right), dot(b.up)];
}

/**
 * Системы эффекта от корня вниз: [имя, точки, которые ей ставят по своим
 * частицам предки (Set child control points from particle positions)]
 */
function walkEffect(systems, root, visit) {
  const seen = new Set([root]);
  const queue = [[root, new Set()]];
  while (queue.length) {
    const [name, driven] = queue.shift();
    const def = systems[name];
    if (!def) continue;
    const pass = visit(name, def, driven);
    if (!pass) continue;
    for (const ch of def.children || []) {
      if (!seen.has(ch.childName)) {
        seen.add(ch.childName);
        queue.push([ch.childName, pass]);
      }
    }
  }
}

/** Точки, которые система ставит детям по своим частицам, плюс полученные */
function passDown(def, driven) {
  const pass = new Set(driven);
  for (const op of def.operators || []) {
    if (moduleFn(op) !== 'set child control points from particle positions') continue;
    const first = modAttr(op, 'first control point to set', 0);
    const count = modAttr(op, '# of control points to set', 1);
    for (let i = 0; i < count; i++) pass.add(first + i);
  }
  return pass;
}

/** У какой точки система рождает частицы. Без своего модуля положения - у нулевой */
export function spawnPoint(def) {
  for (const mod of def.initializers || []) {
    const fn = moduleFn(mod);
    if (fn === 'position within sphere random') return modAttr(mod, 'control_point_number', 0);
    if (fn === 'position within box random') return modAttr(mod, 'control point number', 0);
  }
  return 0;
}

/**
 * Сдвиг мест рождения: movers - кому правим область (корень первым),
 * moving - движущиеся системы с точками, которые едут вместе с ними
 *
 * Кто и так едет за предком (рождается из его частиц или у точки, которую
 * предок ставит по своим частицам, Darkblaze), области не получает: второй
 * сдвиг увёз бы его вдвое дальше, внуков - втрое. whole - весь эффект, иначе
 * только корень и те, кто едет за ним
 */
export function effectScope(systems, root, whole) {
  const movers = [];
  const moving = new Map();
  const moves = new Map([[root, true]]);
  walkEffect(systems, root, (name, def, driven) => {
    const follows = name !== root
      && (findModule(def, 'position from parent particles') >= 0
          || driven.has(spawnPoint(def)));
    const parentMoves = moves.get(name) ?? true;
    const on = name === root || (follows ? parentMoves : whole);
    if (on && !follows) movers.push(name);
    if (on) moving.set(name, driven);
    for (const ch of def.children || []) if (!moves.has(ch.childName)) moves.set(ch.childName, on);
    return on ? passDown(def, driven) : new Set();
  });
  return { movers, moving };
}

/**
 * Сдвиг точкой «начало эффекта»: правим её смещение и смещения систем,
 * которые остались у точки 0 ради её осей (Effect origin offset). Всё
 * смещено в осях точки 0. Едут все системы эффекта
 */
export function originScope(systems, root) {
  const def = systems[root];
  const idx = findOrigin(def);
  const op = def.operators[idx];
  const cp = modAttr(op, 'first control point number', 0);
  const movers = [{
    name: root, group: 'operators', idx, local: true,
    pairs: SLOTS.map((s) => [`${s} control point location`,
                             [...modAttr(op, `${s} control point location`, [0, 0, 0])]]),
  }];
  const moving = new Map();
  walkEffect(systems, root, (name, d, driven) => {
    moving.set(name, new Set([...driven, cp]));
    (d.initializers || []).forEach((m, i) => {
      if (m.name !== ORIGIN_OFFSET) return;
      movers.push({ name, group: 'initializers', idx: i, local: true,
                    pairs: ['offset min', 'offset max'].map((a) => [a, [...modAttr(m, a, [0, 0, 0])]]) });
    });
    return passDown(d, driven);
  });
  return { movers, moving };
}

/** Состав эффекта строкой: корень и все потомки по порядку обхода */
export function effectNames(systems, root) {
  const out = [];
  walkEffect(systems, root, (name) => { out.push(name); return new Set(); });
  return out.join('|');
}

/**
 * Сдвигает уже живущие частицы движущихся систем: иначе за ручкой ехали бы
 * только новые, а бессмертный носитель (корень Darkblaze) стоял бы до
 * отпускания, и эффект прыгал. Вместе с частицами едут точки, выставленные
 * внутри эффекта, и память Lock to Control Point о прошлом положении этих
 * точек - без неё привязка добавила бы второй сдвиг
 */
export function shiftLive(rootInstance, moving, shift) {
  if (!rootInstance || (shift[0] === 0 && shift[1] === 0 && shift[2] === 0)) return;
  const add = (v) => { if (v) for (let i = 0; i < 3; i++) v[i] += shift[i]; };
  const walk = (inst) => {
    const cps = moving.get(inst.def.name);
    if (cps) {
      for (const p of inst.particles) { add(p.pos); add(p.prevPos); add(p.posInit); }
      for (const cp of cps) add(inst.cpOverrides[cp]);
      for (const op of inst.def.operators || []) {
        if (moduleFn(op) !== 'movement lock to control point') continue;
        if (!cps.has(modAttr(op, 'control_point_number', 0))) continue;
        add(inst._opState.get(op)?.prev);
      }
    }
    for (const child of inst.children) walk(child);
  };
  walk(rootInstance);
}
