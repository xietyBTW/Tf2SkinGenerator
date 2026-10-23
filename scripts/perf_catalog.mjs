/*
 * Замер скорости каталога в настоящем окне приложения (или в любом Chromium)
 *
 * Окно WebView2 ведёт себя не так, как браузер, и мерить его надо им самим.
 * Порт отладки WebView2 открывается переменной окружения до запуска:
 *
 *   set WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9333
 *   run.bat
 *   node scripts/perf_catalog.mjs 9333
 *
 * Для сравнения с браузером: msedge --remote-debugging-port=9444
 * --user-data-dir=<пустая папка> http://127.0.0.1:5173/ и тот же скрипт с 9444.
 * Размер окна должен совпадать: на узком экране карточек в разы меньше
 *
 * Фильтр Halloween щёлкается чётное число раз, общий конфиг остаётся как был
 */

const port = process.argv[2] || '9333';

async function bench() {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const now = () => performance.now();
  const med = (a) => { const s = a.slice().sort((x, y) => x - y); return Math.round(s[s.length >> 1]); };
  const api = await import('/api.js');
  const g = document.getElementById('grid');
  const cat = () => document.querySelector('.catalog');
  let lt = [];
  new PerformanceObserver((l) => { for (const e of l.getEntries()) lt.push(e.duration); })
    .observe({ type: 'longtask' });
  const takeLt = () => { const s = Math.round(lt.reduce((a, b) => a + b, 0)); lt = []; return s; };
  const visImgs = () => [...g.querySelectorAll('img.pick__icon')].filter((i) => {
    const r = i.getBoundingClientRect(), b = g.getBoundingClientRect();
    return r.bottom > b.top && r.top < b.bottom;
  });
  const screenDone = () => { const v = visImgs(); return v.length > 1 && v.every((i) => i.classList.contains('is-loaded')); };
  const until = async (cond, limit = 10000) => {
    const t0 = now();
    while (now() - t0 < limit) { if (cond()) return now() - t0; await sleep(2); }
    return limit;
  };
  const listIs = (hats) => () => {
    const p = g.querySelector('.pick');
    return p && (p.dataset.mode === 'hat') === hats
      && !document.getElementById('cat-count').textContent.startsWith('Чита');
  };
  const section = async (name) => {
    const t0 = now();
    document.querySelector(`.chrome__nav [data-section="${name}"]`).click();
    await until(listIs(name === 'hats'));
    return now() - t0;
  };
  const openCat = async () => {
    if (getComputedStyle(cat()).display !== 'none') return;
    document.querySelector('.title__item').click();
    await until(() => getComputedStyle(cat()).display !== 'none');
    await sleep(300);
  };
  const halloween = () => [...document.querySelectorAll('#f-hat .underlined')]
    .find((b) => /Halloween|Хэллоуин/.test(b.textContent));
  const R = {};

  // Прогрев: одни и те же места списка, чтобы иконки лежали в кэше одинаково
  await section('hats'); await openCat();
  for (const f of [0, 0.3, 0.6]) { g.scrollTop = g.scrollHeight * f; await until(screenDone); await sleep(200); }
  g.scrollTop = 0; await section('weapons'); await sleep(500); takeLt();

  const toW = [], toH = [], toHi = [];
  for (let i = 0; i < 5; i++) {
    toW.push(await section('weapons')); await sleep(400);
    const t0 = now(); await section('hats'); toH.push(now() - t0);
    await openCat(); await until(screenDone); toHi.push(now() - t0); await sleep(400);
  }
  R['оружие, список'] = med(toW);
  R['косметика, список'] = med(toH);
  R['косметика, иконки экрана'] = med(toHi);
  R['  длинные задачи'] = takeLt();

  const sc = [];
  for (const f of [0.3, 0.6, 0, 0.3, 0.6]) { await sleep(300); g.scrollTop = g.scrollHeight * f; sc.push(await until(screenDone)); }
  R['прокрутка к виденному'] = med(sc);

  // Ждём счётчик, а не число карточек: в документе только ряды у экрана
  const count = () => document.getElementById('cat-count').textContent;
  const fl = [];
  for (let i = 0; i < 4; i++) {
    await sleep(300);
    const c0 = count(); const t0 = now();
    halloween().click();
    await until(() => count() !== c0); fl.push(now() - t0);
  }
  R['фильтр Halloween'] = med(fl);
  R['  длинные задачи '] = takeLt();

  const ai = [];
  for (let i = 0; i < 20; i++) { const t0 = now(); await api.call('hat_filters'); ai.push(now() - t0); }
  R['API в простое'] = med(ai);

  // Шапка открывается второй раз: модель уже в кэше, меряется окно, а не декомпиляция
  const openHat = async (idx) => {
    await openCat(); g.scrollTop = 0; await sleep(300);
    const t0 = now(); g.querySelectorAll('.pick')[idx].click();
    const calls = [];
    while (now() - t0 < 2500) { const s = now(); await api.call('hat_filters'); calls.push(now() - s); await sleep(15); }
    return calls;
  };
  await openHat(12); await sleep(1500); takeLt();
  const hc = await openHat(12);
  R['API при открытии шапки, худший'] = Math.round(Math.max(...hc));
  R['окно'] = `${innerWidth}x${innerHeight}`;
  R['движок'] = (navigator.userAgent.match(/(Edg|Chrome)\/[\d.]+/g) || []).join(' ');
  return R;
}

let targets;
for (const host of ['[::1]', '127.0.0.1']) {
  try { targets = await (await fetch(`http://${host}:${port}/json`)).json(); break; } catch { /* другой адрес */ }
}
if (!targets) { console.error(`Порт отладки ${port} не отвечает`); process.exit(1); }
const page = targets.find((t) => t.type === 'page' && /^http:\/\/127\.0\.0\.1:\d+\//.test(t.url)
  && !t.url.includes('/viewer/'));
if (!page) { console.error('Страница приложения не найдена'); process.exit(1); }

const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener('open', r));
const res = await new Promise((r) => {
  ws.addEventListener('message', (e) => r(JSON.parse(e.data)));
  ws.send(JSON.stringify({ id: 1, method: 'Runtime.evaluate',
    params: { expression: `(${bench})()`, awaitPromise: true, returnByValue: true } }));
});
ws.close();
const value = res.result?.result?.value;
if (!value) { console.error(JSON.stringify(res.result?.exceptionDetails ?? res)); process.exit(1); }
for (const [k, v] of Object.entries(value)) console.log(k.padEnd(32), typeof v === 'number' ? `${v} мс` : v);
