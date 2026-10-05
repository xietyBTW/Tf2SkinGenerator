/*
 * Сборка в нижней полосе: линия прогресса по её верхнему краю, текст этапа,
 * счётчик, кнопка «Остановить», финал, ошибка и звук.
 *
 * Как именно — выбирают в настройках, раздел «Кастомизация». Варианты и
 * умолчания живут здесь, Python только хранит выбор (`build_fx`). Движок один:
 * им играет и настоящая сборка (build.js, events.js), и пример в окне
 * настроек — у каждого свой набор элементов (createFx).
 *
 * Без анимаций интерфейса (настройка или системное «уменьшить движение»)
 * остаётся простая полоса: текст встаёт сразу, финал и ошибка — без
 * движения. Звук — своя настройка: от анимаций он не зависит.
 */

import * as api from './api.js';
import { t } from './i18n.js';

/** Варианты по группам: [ключ, подпись группы, [[значение, подпись], …]].
 *  Подписи русские — словарь страницы переводит их сам. */
export const FX_GROUPS = [
  ['text', 'Текст этапа', [
    ['decode', 'Перебор букв'], ['type', 'Печать с кареткой'],
    ['cursor', 'Курсор-проявка'], ['ticker', 'Смена строкой вверх'],
    ['slide', 'Смена вбок'], ['flap', 'Табло-перевёртыш'], ['wave', 'Волна букв'],
    ['drop', 'Буквы падают'], ['glitch', 'Глитч в цветах команд']]],
  ['line', 'Линия', [
    ['head', 'Дышащий край'], ['pulse', 'Импульсы'],
    ['teams', 'Красный и синий наперегонки'], ['sparks', 'Искры с края'],
    ['scanner', 'Сканер на долгих этапах'], ['ants', 'Бегущий пунктир'],
    ['spring', 'Рывки с отдачей'], ['heart', 'Сердцебиение на долгих этапах']]],
  ['pct', 'Счётчик', [
    ['count', 'Счёт процентов'], ['roll', 'Барабан'], ['steps', 'Номер этапа'],
    ['hex', 'Шестнадцатеричный'], ['none', 'Без счётчика']]],
  ['btn', 'Кнопка «Остановить»', [
    ['stop', 'Обычная'], ['fill', 'Заполняется'], ['ring', 'С кольцом']]],
  ['fx', 'Полоса', [
    ['none', 'Спокойная'], ['beam', 'Луч сканера'],
    ['flash', 'Вспышка на каждом этапе'], ['tint', 'Фон заливается следом']]],
  ['end', 'Финал', [
    ['meet', 'Цвета навстречу'], ['split', 'Расхождение'], ['sweep', 'Пробег вспышки'],
    ['collapse', 'Линия втягивается'], ['rise', 'Свет поднимается'], ['stamp', 'Штамп'],
    ['confetti', 'Конфетти команд'], ['assemble', 'Слово собирается']]],
  ['err', 'Ошибка', [
    ['shake', 'Линия вздрагивает'], ['shatter', 'Линия рассыпается'],
    ['flicker', 'Линия мигает']]],
  ['sound', 'Звук', [
    ['none', 'Без звука'], ['ticks', 'Щелчки на этапах'], ['chime', 'Сигнал в конце'],
    ['both', 'Щелчки и сигнал']]],
];

/** Как выглядит сборка, пока человек ничего не выбрал. */
export const FX_DEFAULTS = {
  text: 'decode', line: 'head', pct: 'roll', btn: 'stop',
  fx: 'none', end: 'meet', err: 'shake', sound: 'both',
};

/** Сохранённый выбор, сверенный со списком: чужое значение — умолчание. */
export function fxChoice(saved) {
  const out = { ...FX_DEFAULTS };
  for (const [key, , values] of FX_GROUPS) {
    const value = saved && saved[key];
    if (values.some(([v]) => v === value)) out[key] = value;
  }
  return out;
}

//: Цвета команд — те же, что у черт под знаком на заставке.
const RED = '#b8383b';
const BLU = '#5885a2';
const EASE = 'cubic-bezier(.3, 0, .2, 1)';
//: Буквы перебора: кириллица у русского интерфейса, латиница у английского.
//: Кодами, а не строкой: строка кириллицы просилась бы в словарь перевода.
const CYRILLIC = String.fromCharCode(...Array.from({ length: 32 }, (_, i) => 0x410 + i));
const LATIN = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
//: Этап, который длится дольше, — «долгий»: на нём линия показывает, что
//: сборка жива (сканер, сердцебиение, импульсы, искры). Сколько продлится
//: этап, заранее не знает никто — смотрим, не пришёл ли следующий.
const LONG_MS = 1200;
//: Пример в настройках: этапы настоящей сборки оружия, второй с конца долгий.
const DEMO = [[5, 'Подготовка сборки…', 800], [10, 'Извлечение модели…', 800],
              [25, 'Декомпиляция модели…', 2200], [40, 'Обработка текстуры…', 800],
              [60, 'Компиляция модели…', 2200], [80, 'Упаковка VPK…', 900]];
const RING = '<svg class="bfx__ring" viewBox="0 0 14 14" aria-hidden="true">'
  + '<circle cx="7" cy="7" r="5.5"/><circle class="bfx__arc" cx="7" cy="7" r="5.5"'
  + ' transform="rotate(-90 7 7)"/></svg>';

const rnd = (n) => Math.random() * n;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const still = () => document.documentElement.dataset.motion === 'off'
  || matchMedia('(prefers-reduced-motion: reduce)').matches;
function glyph() {
  const set = (api.lang() === 'en' ? LATIN : CYRILLIC) + '0123456789#%&*';
  return set[Math.random() * set.length | 0];
}

let audio = null;
/** Короткий тон WebAudio — щелчок или сигнал. Звук — украшение: не вышло, и ладно. */
function tone(freq, dur, vol, type = 'sine') {
  try {
    audio = audio || new (window.AudioContext || window.webkitAudioContext)();
    if (audio.state === 'suspended') audio.resume();
    const osc = audio.createOscillator();
    const gain = audio.createGain();
    const at = audio.currentTime;
    osc.type = type;
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(vol, at);
    gain.gain.exponentialRampToValueAtTime(0.0001, at + dur);
    osc.connect(gain);
    gain.connect(audio.destination);
    osc.start(at);
    osc.stop(at + dur);
  } catch { /* без звука */ }
}

/**
 * Движок на одном наборе элементов.
 *
 * `els`: host — полоса (в ней искры, луч, подсветка); line — контейнер линии
 * по её верхнему краю; state — текст этапа; pct и time — счётчик и время;
 * prog — их общий контейнер, rest — что он заслоняет на время сборки (сводка
 * параметров); button — кнопка «Остановить» (или её макет) с `.btn__label` и
 * `.btn__fill`; idleLabel — подпись кнопки в покое.
 */
export function createFx(els) {
  //: Выбор из настроек. Действует со следующей сборки: смена посреди идущей
  //: оставила бы на полосе куски прежнего варианта.
  let want = { ...FX_DEFAULTS };
  let opt = want;
  //: Номер сборки: всё, что начала прошлая (таймеры, кадры), гасит новая.
  let run = 0;
  let shown = 0;
  let target = 0;
  //: Сборка, чей цикл счёта сейчас крутится: цикл один, цель он берёт свежую.
  let counting = -1;
  let peak = 0;
  let steps = 0;
  let t0 = 0;
  let text = '';
  let lastDetail = 0;
  let detailTimer = null;
  let pending = '';
  //: Сколько событий сборки пришло. Ответ на «Собрать» может прийти позже
  //: событий и даже позже конца сборки (см. build.js).
  let heard = 0;
  let timers = [];
  let junk = [];
  let teams = null;
  let ants = null;
  let tint = null;
  let fill = null;
  let head = null;
  let longTimer = null;
  let keepTimer = null;
  let clock = null;
  let restTimer = null;
  //: Идёт ли сборка: шаг без старта (страницу подняли посреди сборки)
  //: заводит её сам.
  let active = false;

  const every = (fn, ms) => { const id = setInterval(fn, ms); timers.push(id); return id; };
  const own = (el) => { junk.push(el); return el; };
  //: Снятый элемент свои анимации не останавливает: бесконечные крутились бы
  //: дальше, а финал, ждущий их конца, проснулся бы уже в чужой сборке.
  const drop = (el) => { el.getAnimations({ subtree: true }).forEach((a) => a.cancel()); el.remove(); };
  const edge = (p) => els.line.offsetWidth * p / 100;

  function seg(css) {
    const d = own(document.createElement('div'));
    d.className = 'bfx__seg';
    d.style.cssText = css;
    els.line.appendChild(d);
    return d;
  }
  function overlay(css, parent = els.host) {
    const d = own(document.createElement('div'));
    d.className = 'bfx__over';
    d.style.cssText = css;
    parent.appendChild(d);
    return d;
  }
  function ensureLine() {
    if (fill && fill.isConnected) return;
    fill = document.createElement('div');
    fill.className = 'bfx__fill';
    head = document.createElement('div');
    head.className = 'bfx__head';
    els.line.replaceChildren(fill, head);
  }

  // ── Текст этапа ─────────────────────────────────────────────────────────
  function textBox() {
    let box = els.state.querySelector(':scope > .bfx__text');
    if (!box) {
      box = document.createElement('span');
      box.className = 'bfx__text';
      els.state.replaceChildren(box);
    }
    return box;
  }
  function letters(span, value) {
    span.replaceChildren();
    return [...value].map((c) => {
      const e = document.createElement('span');
      e.className = 'bfx__ch';
      e.textContent = c;
      span.appendChild(e);
      return e;
    });
  }
  /** Текст этапа выбранным способом. Переводим сразу: словарь страницы
   *  переводит только целиком добавленный текст, и перебор шёл бы к русскому. */
  function say(raw, tok, color = '') {
    const value = t(String(raw || ''));
    // Строку мог переписать и setStatus (layout.js): тогда текст «уже на
    // экране» только у нас в памяти.
    if (value === text && !color && els.state.querySelector(':scope > .bfx__text')) return;
    text = value;
    const box = textBox();
    box.style.color = color;
    const mode = still() ? 'plain' : opt.text;
    if (mode === 'ticker' || mode === 'slide') {
      const axis = mode === 'slide' ? 'X' : 'Y';
      const far = mode === 'slide' ? '2em' : '100%';
      const old = box.lastElementChild;
      const nu = document.createElement('span');
      nu.textContent = value;
      box.appendChild(nu);
      nu.animate([{ transform: `translate${axis}(${far})`, opacity: 0 },
                  { transform: 'none', opacity: 1 }], { duration: 320, easing: EASE });
      if (old) {
        old.animate([{ transform: 'none', opacity: 1 },
                     { transform: `translate${axis}(-${far})`, opacity: 0 }],
                    { duration: 320, easing: EASE }).onfinish = () => old.remove();
      }
      return;
    }
    const s = document.createElement('span');
    box.replaceChildren(s);
    const alive = () => tok === run && s.isConnected;
    if (mode === 'plain') {
      s.textContent = value;
    } else if (mode === 'type') {
      let i = 0;
      (function tick() {
        if (!alive()) return;
        i += 1;
        s.textContent = value.slice(0, i) + '▍';
        if (i < value.length) { setTimeout(tick, 22); return; }
        let on = true;
        const id = every(() => {
          if (!alive()) { clearInterval(id); return; }
          on = !on;
          s.textContent = value + (on ? '▍' : '');
        }, 450);
      })();
    } else if (mode === 'cursor') {
      const done = document.createElement('span');
      const caret = document.createElement('span');
      caret.textContent = '█';
      caret.className = 'bfx__caret';
      s.append(done, caret);
      let i = 0;
      (function tick() {
        if (!alive()) return;
        i += 1;
        done.textContent = value.slice(0, i);
        if (i < value.length) setTimeout(tick, 16); else caret.remove();
      })();
    } else if (mode === 'flap') {
      letters(s, value).forEach((e, i) => {
        const c = e.textContent;
        if (c === ' ') return;
        let n = 0;
        const flips = 3 + i % 4;
        e.textContent = glyph();
        setTimeout(function step() {
          if (!alive()) return;
          n += 1;
          e.textContent = n >= flips ? c : glyph();
          e.animate([{ transform: 'scaleY(1)' }, { transform: 'scaleY(.15)' },
                     { transform: 'scaleY(1)' }], { duration: 110 });
          if (n < flips) setTimeout(step, 80);
        }, i * 22);
      });
    } else if (mode === 'wave' || mode === 'drop') {
      const from = mode === 'wave' ? [{ transform: 'translateY(.8em)', opacity: 0 }]
        : [{ transform: 'translateY(-1.2em)', opacity: 0 },
           { transform: 'translateY(.15em)', opacity: 1, offset: 0.7 }];
      letters(s, value).forEach((e, i) => e.animate(
        [...from, { transform: 'none', opacity: 1 }],
        { duration: mode === 'wave' ? 280 : 380, delay: i * (mode === 'wave' ? 16 : 18),
          easing: mode === 'wave' ? EASE : 'ease-out', fill: 'backwards' }));
    } else if (mode === 'glitch') {
      s.textContent = value;
      s.style.position = 'relative';
      const ghost = (c) => {
        const g = document.createElement('span');
        g.className = 'bfx__ghost';
        g.textContent = value;
        g.style.color = c;
        s.appendChild(g);
        return g;
      };
      const r = ghost(RED);
      const b = ghost(BLU);
      let n = 0;
      const id = every(() => {
        n += 1;
        if (!alive() || n > 8) {
          clearInterval(id);
          r.remove();
          b.remove();
          s.style.clipPath = '';
          return;
        }
        r.style.transform = `translate(${rnd(6) - 3}px, ${rnd(2) - 1}px)`;
        b.style.transform = `translate(${rnd(6) - 3}px, ${rnd(2) - 1}px)`;
        s.style.clipPath = n % 3 === 0 ? `inset(${rnd(5) | 0}px 0 ${rnd(5) | 0}px 0)` : '';
      }, 45);
    } else {
      let f = 0;
      const frames = 14;
      (function tick() {
        if (!alive()) return;
        f += 1;
        s.textContent = [...value].map((c, k) => (c === ' ' ? ' '
          : k < value.length * f / frames ? c : glyph())).join('');
        if (f < frames) requestAnimationFrame(tick);
      })();
    }
  }

  // ── Счётчик и время ─────────────────────────────────────────────────────
  function count(p) {
    const el = els.pct;
    if (!el) return;
    if (opt.pct === 'none') { el.textContent = ''; return; }
    if (opt.pct === 'steps') { el.textContent = t(`этап ${steps}`); return; }
    if (opt.pct === 'roll' && !still()) { roll(el, p); return; }
    const hex = opt.pct === 'hex';
    const draw = (v) => {
      el.textContent = hex ? '0x' + v.toString(16).toUpperCase().padStart(2, '0') + ' / 0x64'
                           : v + '%';
    };
    target = p;
    if (still()) { shown = p; draw(p); return; }
    if (counting === run) return;           // идущий цикл сам дойдёт до новой цели
    const tok = counting = run;
    (function tick() {
      if (tok !== run) return;
      shown += (target - shown) * 0.18;
      if (Math.abs(target - shown) < 0.5) shown = target;
      draw(Math.round(shown));
      if (shown !== target) requestAnimationFrame(tick); else counting = -1;
    })();
  }
  function roll(el, p) {
    if (!el.querySelector('.bfx__digit')) {
      el.replaceChildren();
      for (let k = 0; k < 3; k += 1) {
        const d = document.createElement('span');
        d.className = 'bfx__digit';
        for (let n = 0; n <= 9; n += 1) {
          const c = document.createElement('span');
          c.textContent = String(n);
          d.appendChild(c);
        }
        el.appendChild(d);
      }
      el.append('%');
    }
    const s = String(Math.round(p)).padStart(3, ' ');
    el.querySelectorAll('.bfx__digit').forEach((d, k) => {
      d.style.display = s[k] === ' ' ? 'none' : '';
      d.style.transform = `translateY(${-(s[k] === ' ' ? 0 : Number(s[k])) * 1.25}em)`;
    });
  }
  function tickClock() {
    if (!els.time) return;
    const s = Math.floor((performance.now() - t0) / 1000);
    els.time.textContent = String(Math.floor(s / 60)).padStart(2, '0') + ':'
      + String(s % 60).padStart(2, '0');
  }

  // ── Линия ───────────────────────────────────────────────────────────────
  function stopHead() {
    if (!head) return;
    head.getAnimations().forEach((a) => a.cancel());
    head.style.opacity = '0';
  }
  function packet(p) {
    const pk = seg(`width:40px;background:var(--ink);opacity:.75`);
    pk.animate([{ transform: 'translateX(-40px)' },
                { transform: `translateX(${edge(p) - 40}px)` }],
               { duration: 420, easing: 'cubic-bezier(.5, 0, .3, 1)' }).onfinish = () => pk.remove();
  }
  function sparks(p) {
    const x = edge(p);
    for (let i = 0; i < 7; i += 1) {
      const s = overlay(`left:${x}px;top:-1px;width:2px;height:2px;`
        + `background:${i % 2 ? 'var(--accent)' : 'var(--ink)'}`);
      s.animate([{ transform: 'none', opacity: 1 },
                 { transform: `translate(${rnd(40) - 20}px, ${-(8 + rnd(26))}px)`, opacity: 0 }],
                { duration: 500 + rnd(300), easing: 'cubic-bezier(.2, .6, .4, 1)' })
        .onfinish = () => s.remove();
    }
  }
  function draw(p, tok) {
    ensureLine();
    clearTimeout(longTimer);
    clearInterval(keepTimer);
    els.line.getAnimations().forEach((a) => a.cancel());       // сердцебиение
    if (head) head.getAnimations().filter((a) => a.id === 'scan').forEach((a) => a.cancel());
    if (still()) {
      fill.style.transition = 'none';
      fill.style.width = p + '%';
      stopHead();
      return;
    }
    fill.style.transition = `width .45s ${opt.line === 'spring'
      ? 'cubic-bezier(.34, 1.7, .64, 1)' : EASE}`;
    fill.style.width = p + '%';
    if (opt.line === 'teams') {
      fill.style.opacity = '0';
      if (!teams) {
        teams = [seg(`height:1px;background:${RED};transition:width .4s ${EASE}`),
                 seg(`top:1px;height:1px;background:${BLU};transition:width .4s ${EASE} .18s`)];
      }
      const lines = teams;     // к кадру clear() мог их уже обнулить
      requestAnimationFrame(() => lines.forEach((x) => { x.style.width = p + '%'; }));
    } else if (opt.line === 'ants') {
      fill.style.opacity = '0';
      if (!ants) {
        ants = seg(`overflow:hidden;transition:width .45s ${EASE}`);
        ants.innerHTML = '<svg class="bfx__ants" width="4000" height="2" aria-hidden="true">'
          + '<line x1="0" y1="1" x2="4000" y2="1"/></svg>';
        ants.querySelector('line').animate([{ strokeDashoffset: 0 }, { strokeDashoffset: -28 }],
                                           { duration: 450, iterations: Infinity });
      }
      const dash = ants;
      requestAnimationFrame(() => { dash.style.width = p + '%'; });
    } else {
      fill.style.opacity = '';
    }
    if (['head', 'sparks', 'scanner'].includes(opt.line)) {
      head.style.left = `calc(${p}% - 28px)`;
      if (!head.getAnimations().some((a) => a.id === 'breath')) {
        head.animate([{ opacity: 0.2 }, { opacity: 0.75 }, { opacity: 0.2 }],
                     { duration: 1200, iterations: Infinity, id: 'breath' });
      }
    } else {
      stopHead();
    }
    if (opt.line === 'pulse') packet(p);
    if (opt.line === 'sparks') sparks(p);
    longTimer = setTimeout(() => { if (tok === run) slow(p); }, LONG_MS);
  }
  /** Этап затянулся — линия показывает, что сборка жива. */
  function slow(p) {
    if (opt.line === 'scanner' && head) {
      const w = edge(p) - 28;
      if (w > 0) {
        head.animate([{ transform: `translateX(${-w}px)` }, { transform: 'none' }],
                     { duration: 900, direction: 'alternate', iterations: Infinity,
                       easing: 'ease-in-out', id: 'scan' });
      }
    }
    if (opt.line === 'heart') {
      els.line.animate([{ transform: 'scaleY(1)' }, { transform: 'scaleY(2.6)', offset: 0.12 },
                        { transform: 'scaleY(1)', offset: 0.25 },
                        { transform: 'scaleY(1.9)', offset: 0.37 },
                        { transform: 'scaleY(1)', offset: 0.5 }, { transform: 'scaleY(1)' }],
                       { duration: 1100, iterations: Infinity });
    }
    if (opt.line === 'pulse' || opt.line === 'sparks') {
      keepTimer = every(() => (opt.line === 'pulse' ? packet(p) : sparks(p)), 600);
    }
  }

  // ── Кнопка «Остановить» ─────────────────────────────────────────────────
  function button(busy, p = 0) {
    const b = els.button;
    if (!b) return;
    const label = b.querySelector('.btn__label');
    const bar = b.querySelector('.btn__fill');
    let ring = b.querySelector('.bfx__ring');
    const filling = busy && opt.btn === 'fill';
    b.classList.toggle('is-busy', busy);
    if (bar) bar.style.width = filling ? p + '%' : '0';
    if (busy && opt.btn === 'ring') {
      if (!ring) {
        b.insertAdjacentHTML('afterbegin', RING);
        ring = b.querySelector('.bfx__ring');
      }
      const arc = ring.querySelector('.bfx__arc');
      requestAnimationFrame(() => { arc.style.strokeDashoffset = String(34.6 * (1 - p / 100)); });
    } else if (ring) {
      ring.remove();
    }
    if (label) {
      label.textContent = !busy ? t(els.idleLabel)
        : filling ? t('Остановить') + ' · ' + Math.round(p) + '%' : t('Остановить');
    }
  }

  // ── Звук ────────────────────────────────────────────────────────────────
  function sound(kind) {
    const s = opt.sound;
    if (kind === 'tick' && (s === 'ticks' || s === 'both')) tone(2200, 0.025, 0.035, 'square');
    if (kind === 'done' && (s === 'chime' || s === 'both')) {
      tone(784, 0.22, 0.07);
      setTimeout(() => tone(1175, 0.32, 0.07), 110);
    }
    if (kind === 'fail' && (s === 'chime' || s === 'both')) tone(196, 0.34, 0.08, 'triangle');
  }

  // ── Финал и ошибка ──────────────────────────────────────────────────────
  /** Всё, что двигалось по ходу сборки, — стоп: финалу и ошибке оно мешает. */
  function halt() {
    clearInterval(clock);
    clearTimeout(longTimer);
    clearInterval(keepTimer);
    clearTimeout(detailTimer);
    detailTimer = null;
    stopHead();
    els.line.getAnimations().forEach((a) => a.cancel());
    junk.filter((e) => e.dataset.fx === 'beam').forEach(drop);
    // Пунктир замирает: красный бегущий после ошибки читался бы как «ещё идёт».
    if (ants) ants.querySelector('line').getAnimations().forEach((a) => a.cancel());
  }
  function fadeFill() {
    return fill.animate([{ opacity: 1 }, { opacity: 0 }],
                        { duration: 500, delay: 300, fill: 'forwards' }).finished;
  }
  async function finale(message, tok) {
    ensureLine();
    if (tint) tint.animate([{ opacity: 0.06 }, { opacity: 0 }], { duration: 500, fill: 'forwards' });
    for (const g of [teams, ants]) {
      if (!g) continue;
      fill.style.opacity = '';
      fill.style.width = '100%';
      (Array.isArray(g) ? g : [g]).forEach((x) => x.animate([{ opacity: 1 }, { opacity: 0 }],
                                                            { duration: 200, fill: 'forwards' }));
    }
    if (still()) {
      say(message, tok);
      await fadeFill();
      return;
    }
    const box = textBox();
    if (['stamp', 'assemble'].includes(opt.end)) {
      text = t(message);
      box.style.overflow = 'visible';
      const s = document.createElement('span');
      box.replaceChildren(s);
      if (opt.end === 'stamp') {
        s.textContent = text;
        s.style.transformOrigin = 'left center';
        seg('width:100%;background:var(--ink)')
          .animate([{ opacity: 1 }, { opacity: 0 }], { duration: 500, fill: 'forwards' });
        s.animate([{ transform: 'scale(1.7) rotate(-3deg)', opacity: 0 },
                   { transform: 'scale(.95)', opacity: 1, offset: 0.7 },
                   { transform: 'none', opacity: 1 }],
                  { duration: 380, easing: 'cubic-bezier(.2, .8, .3, 1)' });
        els.host.animate([{ transform: 'none' }, { transform: 'translateY(2px)' },
                          { transform: 'none' }], { duration: 180, delay: 260 });
      } else {
        letters(s, text).forEach((e, i) => e.animate(
          [{ transform: `translate(${rnd(80) - 40}px, ${rnd(40) - 20}px) rotate(${rnd(90) - 45}deg)`,
             opacity: 0 }, { transform: 'none', opacity: 1 }],
          { duration: 520, delay: i * 14, easing: 'cubic-bezier(.2, .8, .3, 1)', fill: 'backwards' }));
      }
      await fadeFill();
      return;
    }
    say(message, tok);
    const line = els.line;
    if (opt.end === 'meet') {
      // Красный слева, синий справа — встретились, линия вздрогнула и
      // схлопнулась к середине.
      const halves = [seg(`width:50%;background:${RED};transform-origin:left`),
                      seg(`left:50%;width:50%;background:${BLU};transform-origin:right`)];
      await Promise.all(halves.map((x) => x.animate(
        [{ transform: 'scaleX(0)' }, { transform: 'scaleX(1)' }],
        { duration: 480, easing: EASE, fill: 'forwards' }).finished));
      if (tok !== run) return;
      line.style.transformOrigin = 'center';
      await line.animate([{ transform: 'scaleY(1)' }, { transform: 'scaleY(2.5)' },
                          { transform: 'scaleY(1)' }], { duration: 260, easing: 'ease-out' }).finished;
      if (tok !== run) return;
      await line.animate([{ transform: 'scaleX(1)' }, { transform: 'scaleX(0)' }],
                         { duration: 520, delay: 240, easing: 'cubic-bezier(.6, 0, .4, 1)',
                           fill: 'forwards' }).finished;
    } else if (opt.end === 'split') {
      fill.style.opacity = '0';
      const halves = [seg(`width:50%;background:${RED};transform-origin:left`),
                      seg(`left:50%;width:50%;background:${BLU};transform-origin:right`)];
      await Promise.all(halves.map((x) => x.animate(
        [{ transform: 'scaleX(1)', opacity: 1 }, { transform: 'scaleX(.12)', opacity: 1, offset: 0.7 },
         { transform: 'scaleX(.12)', opacity: 0 }],
        { duration: 1000, delay: 400, easing: EASE, fill: 'forwards' }).finished));
    } else if (opt.end === 'collapse') {
      line.style.transformOrigin = 'left';
      await line.animate([{ transform: 'scaleX(1)' }, { transform: 'scaleX(0)' }],
                         { duration: 600, easing: 'cubic-bezier(.6, 0, .3, 1)',
                           fill: 'forwards' }).finished;
      const css = getComputedStyle(document.documentElement);
      box.animate([{ color: css.getPropertyValue('--accent').trim() },
                   { color: css.getPropertyValue('--ink').trim() }], { duration: 600 });
    } else if (opt.end === 'rise') {
      overlay('left:0;right:0;bottom:100%;height:80px;background:var(--accent);'
              + 'transform-origin:bottom')
        .animate([{ transform: 'scaleY(0)', opacity: 0.18 }, { transform: 'scaleY(1)', opacity: 0 }],
                 { duration: 950, easing: 'cubic-bezier(.2, .7, .3, 1)', fill: 'forwards' });
      await fadeFill();
    } else if (opt.end === 'confetti') {
      const cx = els.host.offsetWidth / 2;
      const colors = [RED, BLU, 'var(--accent)', 'var(--ink)'];
      for (let i = 0; i < 30; i += 1) {
        const vx = rnd(300) - 150;
        const vy = -(50 + rnd(70));
        const turn = rnd(720) - 360;
        overlay(`left:${cx}px;top:-1px;width:7px;height:2px;background:${colors[i % 4]}`)
          .animate([{ transform: 'none', opacity: 1 },
                    { transform: `translate(${vx * 0.6}px, ${vy}px) rotate(${turn / 2}deg)`,
                      opacity: 1, offset: 0.45 },
                    { transform: `translate(${vx}px, ${vy + 80}px) rotate(${turn}deg)`, opacity: 0 }],
                   { duration: 1300 + rnd(400), easing: 'cubic-bezier(.2, .7, .4, 1)', fill: 'forwards' });
      }
      await fadeFill();
    } else {
      const flare = seg('width:90px;background:var(--ink)');
      await flare.animate([{ transform: 'translateX(-90px)' },
                           { transform: `translateX(${line.offsetWidth}px)` }],
                          { duration: 650, easing: 'cubic-bezier(.5, 0, .3, 1)' }).finished;
      if (tok !== run) return;
      flare.remove();
      await fadeFill();
    }
  }
  function fail(message, tok) {
    halt();
    ensureLine();
    const p = peak;
    fill.style.opacity = '';
    fill.classList.add('is-error');
    if (teams) teams.forEach((x) => { x.style.background = RED; });
    if (ants) ants.querySelector('line').style.stroke = RED;
    if (!still()) {
      if (opt.err === 'shatter') {
        const w = edge(p);
        const n = 7;
        fill.style.opacity = '0';
        if (teams) teams.forEach((x) => { x.style.opacity = '0'; });
        if (ants) ants.style.opacity = '0';
        for (let k = 0; k < n; k += 1) {
          overlay(`top:-1px;height:2px;left:${k * w / n}px;width:${Math.max(1, w / n - 3)}px;`
                  + `background:${RED}`)
            .animate([{ transform: 'none', opacity: 1 },
                      { transform: `translate(${rnd(10) - 5}px, ${18 + rnd(22)}px) rotate(${rnd(50) - 25}deg)`,
                        opacity: 0 }],
                     { duration: 700 + rnd(300), delay: k * 25, easing: 'cubic-bezier(.5, 0, .8, .6)',
                       fill: 'forwards' });
        }
      } else if (opt.err === 'flicker') {
        els.line.animate([{ opacity: 1 }, { opacity: 0.15 }, { opacity: 1 }, { opacity: 0.3 },
                          { opacity: 1 }, { opacity: 0 }, { opacity: 1 }], { duration: 650 });
      } else {
        els.line.animate([{ transform: 'none' }, { transform: 'translateX(-8px)' },
                          { transform: 'translateX(6px)' }, { transform: 'translateX(-3px)' },
                          { transform: 'none' }], { duration: 340 });
      }
    }
    say(message, tok, 'var(--bfx-error)');
    button(false);
    sound('fail');
  }

  // ── Снаружи ─────────────────────────────────────────────────────────────
  function clear() {
    run += 1;
    opt = want;
    active = false;
    shown = 0;
    target = 0;
    peak = 0;
    steps = 0;
    text = '';
    timers.forEach(clearInterval);
    timers = [];
    clearTimeout(longTimer);
    clearInterval(keepTimer);
    clearTimeout(restTimer);
    clearTimeout(detailTimer);
    detailTimer = null;
    junk.forEach(drop);
    junk = [];
    teams = null;
    ants = null;
    tint = null;
    els.host.getAnimations().forEach((a) => a.cancel());
    // Линия — заново: заливка и край прошлой сборки уехали бы к началу
    // анимацией, а их ждущие финалы проснулись бы на новой.
    els.line.getAnimations({ subtree: true }).forEach((a) => a.cancel());
    els.line.replaceChildren();
    fill = null;
    head = null;
    const box = els.state.querySelector(':scope > .bfx__text');
    if (box) box.style.overflow = '';
    if (els.pct) {
      els.pct.replaceChildren();
      els.pct.classList.toggle('is-roll', opt.pct === 'roll' && !still());
    }
    if (els.time) els.time.textContent = '';
    button(false);
  }

  /** Начало сборки. Уже идущую не перезапускает: первый этап мог прийти
   *  раньше, чем ответ на «Собрать». */
  function start(label = 'Сборка…') {
    if (active) return;
    clear();
    active = true;
    const tok = run;
    t0 = performance.now();
    tickClock();
    clock = every(tickClock, 250);
    if (els.prog) els.prog.hidden = false;
    if (els.rest) els.rest.hidden = true;
    ensureLine();
    if (!still() && opt.fx === 'beam') {
      const beam = overlay('top:0;bottom:0;left:0;width:1px;background:var(--ink);opacity:.12');
      beam.dataset.fx = 'beam';
      beam.animate([{ transform: 'none' }, { transform: `translateX(${els.host.offsetWidth}px)` }],
                   { duration: 1800, iterations: Infinity });
    }
    if (!still() && opt.fx === 'tint') {
      tint = overlay(`left:0;top:0;bottom:0;width:0;background:var(--accent);opacity:.06;`
                     + `transition:width .45s ${EASE}`);
    }
    button(true, 0);
    say(label, tok);
    // Звуку нужен жест человека: контекст заводим, пока щелчок «Собрать»
    // ещё свежий, — иначе первый щелчок этапа прозвучал бы с опозданием.
    if (opt.sound !== 'none') tone(1, 0.001, 0.0001);
  }

  function step(p, label) {
    if (!active) start();
    const tok = run;
    heard += 1;
    // Отложенная подпись подшага относится к прошлому этапу.
    clearTimeout(detailTimer);
    detailTimer = null;
    p = Math.max(peak, Math.min(100, Number(p) || 0));
    peak = p;
    steps += 1;
    draw(p, tok);
    count(p);
    button(true, p);
    if (label) say(label, tok);
    if (tint) tint.style.width = p + '%';
    if (!still() && opt.fx === 'flash') {
      overlay('inset:0;background:var(--accent)')
        .animate([{ opacity: 0.12 }, { opacity: 0 }], { duration: 550, fill: 'forwards' });
    }
    sound('tick');
  }

  /** Подшаг этапа (упаковка, замена модели): своя подпись, линия стоит.
   *  Приходят они пачкой — чаще четырёх раз в секунду текст не дёргаем,
   *  но последняя подпись пачки встаёт всё равно, с опозданием. */
  function detail(label) {
    if (!label) return;
    heard += 1;
    if (!active) start();
    pending = label;
    if (detailTimer) return;
    const show = () => {
      detailTimer = null;
      lastDetail = performance.now();
      say(pending, run);
    };
    const left = 250 - (performance.now() - lastDetail);
    if (left <= 0) show(); else detailTimer = setTimeout(show, left);
  }

  async function finish(ok, message, cancelled = false) {
    const tok = run;
    heard += 1;
    active = false;
    clearInterval(clock);
    if (els.prog && els.rest) {
      // Сводка параметров возвращается, когда итог уже прочитан.
      restTimer = setTimeout(() => {
        if (tok !== run) return;
        els.prog.hidden = true;
        els.rest.hidden = false;
      }, 6000);
    }
    if (cancelled) {
      halt();
      say(message, tok);
      button(false);
      // Гаснет всё, что рисовало линию. Не ждём: новая сборка прервёт
      // угасание, и ожидание упало бы ошибкой.
      for (const el of [fill, tint, ants, ...(teams || [])]) {
        if (el) el.animate({ opacity: 0 }, { duration: 400, fill: 'forwards' });
      }
      return;
    }
    if (!ok) { fail(message, tok); return; }
    draw(100, tok);
    count(100);
    button(true, 100);
    await wait(still() ? 0 : 480);
    if (tok !== run) return;
    halt();
    sound('done');
    try { await finale(message, tok); } catch { /* сборку оборвала новая */ }
    if (tok === run) button(false);
  }

  async function demo(failing = false) {
    clear();
    start();
    const tok = run;
    for (let i = 0; i < DEMO.length; i += 1) {
      if (tok !== run) return;
      const [p, label, ms] = DEMO[i];
      step(p, label);
      if (failing && i === 4) {
        await wait(900);
        if (tok === run) finish(false, 'Ошибка: studiomdl не принял модель');
        return;
      }
      await wait(ms);
    }
    if (tok === run) await finish(true, 'Мод собран · skin_mod.vpk');
  }

  return {
    set: (saved) => { want = fxChoice(saved); },
    heard: () => heard,
    start, step, detail, finish, demo, clear,
  };
}

//: Полоса внизу окна — её сборка.
export const dockFx = createFx({
  host: document.querySelector('.dock'),
  line: document.getElementById('dockline'),
  state: document.querySelector('.dock__state'),
  pct: document.getElementById('dockpct'),
  time: document.getElementById('docktime'),
  prog: document.getElementById('dockprog'),
  rest: document.getElementById('docksum'),
  button: document.getElementById('buildstop'),
  idleLabel: 'Остановить',
});
