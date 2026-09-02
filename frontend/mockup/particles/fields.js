/*
 * Поля редактора: ползунок, число, цвет, атрибут экспертного режима.
 *
 * Крутилки описаны в Python (services/simple_params) — здесь только поля и
 * отправка значений. Список параметров, границы и подписи приходят готовыми:
 * схема одна на панель приложения и на эту страницу.
 */

import * as api from '../api.js';
import { curveFraction, curveValue } from '../curve.js';
import { say, particles, withParticles } from '../stage.js';
import { pSystem } from './state.js';
import { showParams } from './params.js';

/**
 * Дорожка ползунка. Границы у неё МЯГКИЕ (сколько нужно в 99% эффектов), а
 * поле рядом принимает и жёсткие: в стоке встречаются emission_rate под
 * миллион, и запрет на них молча испортил бы чужой эффект.
 */
export function sliderField(value, param, onLive, onDone) {
  const r = document.createElement('input');
  r.className = 'slider';
  r.type = 'range';
  r.min = 0; r.max = 1000; r.step = 1;
  r.value = Math.round(curveFraction(param, value) * 1000);
  const read = () => {
    const v = curveValue(param, Number(r.value) / 1000);
    return param.decimals ? Number(v.toFixed(param.decimals)) : Math.round(v);
  };
  // Пока тянут — только показываем; в Python уходит отпускание, иначе одно
  // перетаскивание давало бы сотню правок файла.
  r.addEventListener('input', () => onLive(read()));
  r.addEventListener('change', () => onDone(read()));
  return r;
}

/** Поле одного числа. Возвращает input; onEdit получает уже число. */
export function numberField(value, param, onEdit) {
  const i = document.createElement('input');
  i.className = 'input input--num';
  i.type = 'number';
  i.step = param.decimals ? String(10 ** -param.decimals) : '1';
  i.min = param.hard_min;
  i.max = param.hard_max;
  i.value = Number(value).toFixed(param.decimals);
  // Пока модуля под параметром нет, поле показывает умолчание Source бледным:
  // именно его эффект и получит, если правку не тронуть.
  i.classList.toggle('is-placeholder', param.value === null);
  i.addEventListener('change', () => {
    const v = Math.min(param.hard_max, Math.max(param.hard_min, Number(i.value)));
    i.value = v.toFixed(param.decimals);
    onEdit(v);
  });
  return i;
}

/**
 * Дорожка и поле на одно значение: тянуть удобнее, вписать точнее.
 *
 * Дорожка ходит по мягким границам, поле принимает и жёсткие — поэтому
 * значение из чужого эффекта (emission_rate под миллион) правится вручную,
 * а дорожка просто упирается в край.
 */
export function pairedField(value, param, onEdit) {
  const wrap = document.createElement('div');
  wrap.className = 'pair';
  const field = numberField(value, param, onEdit);
  const track = sliderField(value, param,
    (v) => { field.value = v.toFixed(param.decimals); },
    onEdit);
  field.addEventListener('input', () => {
    track.value = Math.round(curveFraction(param, Number(field.value)) * 1000);
  });
  wrap.append(track, field);
  return wrap;
}

/** Цвет как #rrggbb; альфу сохраняем — её правит отдельный параметр. */
export function colorField(rgba, onEdit) {
  const i = document.createElement('input');
  i.type = 'color';
  i.className = 'colorfield';
  const hex = (n) => Math.max(0, Math.min(255, n | 0)).toString(16).padStart(2, '0');
  i.value = '#' + hex(rgba[0]) + hex(rgba[1]) + hex(rgba[2]);
  i.addEventListener('change', () => {
    const n = parseInt(i.value.slice(1), 16);
    onEdit([(n >> 16) & 255, (n >> 8) & 255, n & 255, rgba[3] ?? 255]);
  });
  return i;
}

/** Отправляет правку и переливает результат в живое превью. */
export async function editParam(param, value) {
  const res = await api.setParticleParam(pSystem, param.key, value);
  if (res.error) { say(res.error); return; }
  withParticles((w) => w.updateSystems(res.systems, pSystem));
  // Значение могло создать модуль — перечитываем, чтобы бледные поля стали
  // обычными, а соседние крутилки показали то, что теперь в файле.
  await showParams(pSystem);
}

/** Редактор одного атрибута экспертного режима — по типу из PCF. */
export function attrField(attr, onEdit) {
  const box = document.createElement('div');
  box.className = 'params__in';

  // Атрибут с фиксированным набором значений — список, а не голое число.
  if (attr.enum) {
    const sel = document.createElement('select');
    sel.className = 'input';
    for (const [v, label] of Object.entries(attr.enum)) sel.append(new Option(label || v, v));
    sel.value = String(attr.v);
    sel.addEventListener('change', () => onEdit(Number(sel.value)));
    box.append(sel);
    return box;
  }

  if (attr.t === 'bool') {
    const i = document.createElement('input');
    i.type = 'checkbox';
    i.checked = Boolean(attr.v);
    i.addEventListener('change', () => onEdit(i.checked));
    box.append(i);
    return box;
  }

  if (attr.t === 'color') {
    // Цвет и прозрачность — разными полями: альфа в PCF четвёртая компонента,
    // а <input type="color"> о ней не знает.
    const rgba = attr.v.slice();
    const hex = (n) => Math.max(0, Math.min(255, n | 0)).toString(16).padStart(2, '0');
    const c = document.createElement('input');
    c.type = 'color';
    c.className = 'colorfield';
    c.value = '#' + hex(rgba[0]) + hex(rgba[1]) + hex(rgba[2]);
    const alpha = document.createElement('input');
    alpha.className = 'input input--num input--tiny';
    alpha.type = 'number'; alpha.min = 0; alpha.max = 255; alpha.step = 1;
    alpha.value = rgba[3] ?? 255;
    const push = () => {
      const n = parseInt(c.value.slice(1), 16);
      onEdit([(n >> 16) & 255, (n >> 8) & 255, n & 255, Number(alpha.value)]);
    };
    c.addEventListener('change', push);
    alpha.addEventListener('change', push);
    box.append(c, alpha);
    return box;
  }

  if (attr.t === 'string') {
    const i = document.createElement('input');
    i.className = 'input';
    i.type = 'text';
    i.value = attr.v ?? '';
    i.addEventListener('change', () => onEdit(i.value));
    box.append(i);
    return box;
  }

  if (Array.isArray(attr.v)) {
    // vec2/vec3/vec4 — по полю на компоненту, значение уходит целиком.
    const vals = attr.v.slice();
    vals.forEach((v, n) => {
      const i = document.createElement('input');
      i.className = 'input input--num input--tiny';
      i.type = 'number'; i.step = '0.01';
      i.value = v;
      i.addEventListener('change', () => {
        vals[n] = Number(i.value);
        onEdit(vals.slice());
      });
      box.append(i);
    });
    return box;
  }

  const i = document.createElement('input');
  i.className = 'input input--num';
  i.type = 'number';
  i.step = attr.t === 'integer' ? '1' : '0.01';
  // В PCF числа float32, и 0.1 приезжает как 0.10000000149011612. Показываем
  // округлённо: значение в файле не трогаем, пока его не правят.
  i.value = attr.t === 'integer' ? attr.v : Number(Number(attr.v).toPrecision(7));
  i.addEventListener('change',
    () => onEdit(attr.t === 'integer' ? parseInt(i.value, 10) : Number(i.value)));
  box.append(i);
  return box;
}

/** Проверка «умеет ли движок этот модуль», либо null — движок ещё молчит. */
export function supportedModules() {
  const w = particles();
  if (!w || typeof w.implementedModules !== 'function') return null;
  const impl = w.implementedModules();
  const aliases = impl.aliases || {};
  return (group, fn) => {
    const name = String(fn || '').trim().toLowerCase();
    const real = aliases[name] || name;
    return (impl[group] || []).some((x) => String(x).toLowerCase() === real);
  };
}
