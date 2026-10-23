/*
 * Карточка «Превью» конструктора блеска: запрос кадров у Python и
 * проигрыватель (кадр назад/вперёд, пауза, перемотка)
 *
 * Правка уходит сразу, не дожидаясь прошлого расчёта: Python бросает
 * устаревший ({cancelled}), а здесь показывается только ответ на последний
 * запрос.
 */

import * as api from './api.js';
import { t } from './i18n.js';
import { el, button, card } from './sheen-ui.js';
import { createTransform } from './sheen-transform.js';

export const FPS = 25;

/**
 * `pattern` - SheenPattern. `onDropImage(file)` - картинку бросили на превью,
 * `onSheet()` - пришли новые кадры, `onPlayhead(pos)` - где идёт проход
 * (0..1, -1 - пауза между проходами), `onTransform()` - картинку слоя
 * подвинули, повернули или изменили размер рамкой на плитке.
 */
export function createPlayer(pattern, { onDropImage, onSheet, onPlayhead, onTransform }) {
  let alive = true;          // этот показ окна: после закрытия всё молчит
  const maskBtn = button(t('Маска'), 'tag', t('Сама маска: белое - блеск ярче всего'));
  maskBtn.addEventListener('click', () => {
    pattern.mask = !pattern.mask;
    maskBtn.classList.toggle('is-active', pattern.mask);
  });
  const preview = card(t('Превью'), maskBtn);
  const stage = el('div', 'sheenb__stage');
  const canvas = el('canvas', 'sheenb__canvas');
  const busy = el('span', 'sheenb__busy', t('Считаю…'));
  busy.hidden = true;
  const dropHint = el('div', 'sheenb__drop', t('Отпустите - картинка станет слоем'));
  stage.append(canvas, busy, dropHint);
  const xform = createTransform(stage, canvas, pattern, { onCommit: onTransform });
  const note = el('p', 'sheenb__note');
  // Гамма узора: что из цветов слоёв игра покажет (sheen_palette.py)
  const gamutNote = el('p', 'sheenb__note sheenb__gamut');

  // Картинку можно бросить прямо на превью
  stage.addEventListener('dragover', (e) => {
    if (![...(e.dataTransfer?.types || [])].includes('Files')) return;
    e.preventDefault();
    stage.classList.add('is-over');
  });
  stage.addEventListener('dragleave', () => stage.classList.remove('is-over'));
  stage.addEventListener('drop', (e) => {
    e.preventDefault();
    stage.classList.remove('is-over');
    const file = [...(e.dataTransfer?.files || [])].find((f) => f.type.startsWith('image/'));
    if (file) onDropImage(file);
  });

  // Проигрыватель: кадр назад, играть, кадр вперёд и время прохода
  let sheet = null;          // {img, frames, cols, size, aspect}
  let clock = 0;
  let playing = true;
  const play = button('', 'sheenb__play');
  const syncPlay = () => {
    play.textContent = playing ? '❚❚' : '▶';
    play.title = playing ? t('Пауза (пробел)') : t('Играть (пробел)');
  };
  const togglePlay = () => { playing = !playing; syncPlay(); };
  play.addEventListener('click', togglePlay);
  syncPlay();
  const stepBack = button('◀', 'textbtn sheenb__step', t('Кадр назад'));
  const stepFwd = button('▶', 'textbtn sheenb__step', t('Кадр вперёд'));
  const step = (d) => {
    playing = false;
    syncPlay();
    if (!sheet) return;
    const pass = sheet.frames / FPS;
    clock = Math.max(1 / FPS, Math.min(pass - 1e-3, (Math.floor(clock * FPS) + d + 0.5) / FPS));
  };
  stepBack.addEventListener('click', () => step(-1));
  stepFwd.addEventListener('click', () => step(1));
  const clockOut = el('span', 'mono sheenb__clock');
  const transport = el('div', 'sheenb__transport');
  const buttons = el('div', 'sheenb__transportbtns');
  buttons.append(stepBack, play, stepFwd);
  transport.append(el('span'), buttons, clockOut);
  preview.content.append(stage, transport, note, gamutNote);

  /** Перемотка в долю прохода `f` (0..1) с паузой. Без кадров - false */
  function seek(f) {
    if (!sheet) return false;
    playing = false;
    syncPlay();
    const passSec = sheet.frames / FPS;
    clock = Math.max(1 / FPS, Math.min(passSec - 1e-3, 1 / FPS + f * (passSec - 2 / FPS)));
    return true;
  }

  // Кадры: запрос
  let timer = null;
  let latest = 0;

  function refresh() {
    clearTimeout(timer);
    timer = setTimeout(request, 160);
  }

  async function request() {
    const mine = ++latest;
    busy.hidden = false;
    let res;
    try {
      // Гамму решает весь узор, даже когда в превью один слой «соло»
      res = await api.sheenPatternPreview(
        { layers: pattern.previewLayers(), quality: pattern.quality }, pattern.length,
        pattern.spec());
    } catch (err) {
      res = { error: err.message };
    }
    if (!alive || mine !== latest || res.cancelled) return;
    busy.hidden = true;
    if (res.error) { note.textContent = res.error; return; }
    const img = new Image();
    img.onload = () => {
      if (!alive || mine !== latest) return;
      sheet = { img, ...res };
      shownFrame = -1;
      showGamut();
      onSheet();              // пропорция оружия известна точно только теперь
      note.textContent = res.weapon
        ? t('Плитка в пропорциях оружия: узор ляжет на его бок так же.')
        : t('Оружие не выбрано: показана обычная пропорция ствола.');
      sizeCanvas();
    };
    img.src = api.fileUrl(res.image);
  }

  /** Строка о гамме: какая она и какие слои в игре пропадут */
  function showGamut() {
    const lost = (sheet.lost || []).map((i) => pattern.layerName(i));
    gamutNote.classList.toggle('is-warn', lost.length > 0);
    if (lost.length) {
      gamutNote.textContent = t(`Не будет видно в игре: ${lost.join(', ')}. Чёрный, синий, голубой и зелёный не уживаются в одном узоре с белым, жёлтым и красным.`);
    } else {
      gamutNote.textContent = sheet.palette === 'cold'
        ? t('Гамма с чёрным: слои могут быть чёрными, синими, голубыми, зелёными.')
        : t('Гамма со светлыми: слои могут быть белыми, жёлтыми, красными, розовыми.');
    }
  }

  // Плитка - всегда по ширине своей колонки (постоянная ширина наезжала бы
  // на слои в узком окне), высота - по пропорции оружия
  function sizeCanvas() {
    if (!sheet) return;
    const room = stage.clientWidth - 2;
    if (room <= 0) return;
    let w = room;
    let h = Math.round(w / sheet.aspect);
    if (h > 260) { h = 260; w = Math.round(h * sheet.aspect); }
    if (h < 60) h = 60;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    canvas.style.width = `${w}px`;
    canvas.style.height = `${h}px`;
  }
  const resizer = new ResizeObserver(() => sizeCanvas());
  resizer.observe(stage);

  // Проигрыватель
  // Кадр маски - на маленьком холсте, и там же смешивание как в игре
  // (weapon_sheen_pass): непрозрачность - красный канал маски, цвет -
  // маска x оттенок гаммы. В холодной гамме оттенок без красного: красный
  // канал несёт форму слоя, а цвет - зелёный и синий (чёрный слой темнит)
  const tint = document.createElement('canvas');
  let shownFrame = -1;
  function blendLikeGame(tc, cw, ch) {
    const px = tc.getImageData(0, 0, cw, ch);
    const d = px.data;
    const cold = sheet.palette === 'cold';
    for (let i = 0; i < d.length; i += 4) {
      d[i + 3] = d[i];
      if (cold) d[i] = 0;
    }
    tc.putImageData(px, 0, 0);
  }
  let last = performance.now();
  function draw(now) {
    if (!alive) return;
    const dt = (now - last) / 1000;
    last = now;
    if (playing) clock += dt;
    const ctx = canvas.getContext('2d');
    const w = canvas.width;
    const h = canvas.height;
    ctx.globalCompositeOperation = 'source-over';
    if (pattern.mask) {
      ctx.fillStyle = '#000';
    } else {
      const grad = ctx.createLinearGradient(0, 0, 0, h);
      grad.addColorStop(0, '#4a4f55');
      grad.addColorStop(1, '#2c2f33');
      ctx.fillStyle = grad;
    }
    ctx.fillRect(0, 0, w, h);
    let pos = -1;
    let shown = '';
    if (sheet) {
      const passSec = sheet.frames / FPS;
      const cycle = passSec + Math.max(0, 5 - pattern.streak);
      if (playing) clock %= cycle;
      const frame = clock < passSec ? Math.min(sheet.frames - 1, Math.floor(clock * FPS)) : 0;
      shown = clock < passSec ? t(`${clock.toFixed(1)} / ${passSec.toFixed(1)} с`)
        : t(`пауза ${(cycle - clock).toFixed(1)} с`);
      if (frame > 0) {
        const cw = sheet.cell_w;
        const ch = sheet.cell_h;
        const col = frame % sheet.cols;
        const row = Math.floor(frame / sheet.cols);
        // Тот же кадр и вид - холст уже готов (на паузе это каждый кадр)
        const want = frame * 2 + (pattern.mask ? 1 : 0);
        if (want !== shownFrame) {
          shownFrame = want;
          tint.width = cw;
          tint.height = ch;
          const tc = tint.getContext('2d', { willReadFrequently: true });
          tc.drawImage(sheet.img, col * cw, row * ch, cw, ch, 0, 0, cw, ch);
          if (!pattern.mask) blendLikeGame(tc, cw, ch);
        }
        ctx.globalCompositeOperation = 'source-over';
        ctx.drawImage(tint, 0, 0, cw, ch, 0, 0, w, h);
        pos = (frame - 1) / Math.max(1, sheet.frames - 2);
      }
    }
    clockOut.textContent = shown;
    xform.sync();
    onPlayhead(pos);
    requestAnimationFrame(draw);
  }

  return {
    box: preview.box,
    get sheet() { return sheet; },
    refresh,
    seek,
    togglePlay,
    /** Строка под превью: подсказка или ошибка */
    say(text) { note.textContent = text; },
    start() { requestAnimationFrame((now) => { last = now; draw(now); }); },
    dispose() {
      alive = false;
      clearTimeout(timer);
      resizer.disconnect();
    },
  };
}
