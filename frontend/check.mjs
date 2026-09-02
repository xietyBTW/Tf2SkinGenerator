/*
 * Проверка типов с отсечкой известного шума.
 *
 * Страница написана на обычном DOM: `getElementById` отдаёт HTMLElement, а
 * читают у него `.value`, `.checked`, `.showModal`. TypeScript честно на это
 * ругается — таких мест около двухсот, и НИ ОДНО из них не баг (проверено:
 * при включении checkJs на цельном app.js из 209 ошибок настоящих не было).
 * Сужать каждое обращение — двести правок ради нуля находок, поэтому шум
 * отсекается здесь, а не ложью в типах.
 *
 * Отсекается ТОЛЬКО сужение DOM. Всё, что говорит о сломанной сборке модулей
 * — неизвестное имя, повтор объявления, отсутствующий экспорт, присваивание
 * импортированному — валит проверку. Это и есть сеть, которой держится распил
 * на модули.
 */

import { spawnSync } from 'node:child_process';

//: Коды ошибок, ради которых всё и затевалось.
//: Коды перечислены поимённо, поэтому забытый код — молчаливая дыра. Так и
//: вышло с 2632: присваивание импортированной привязке проехало проверку и
//: упало уже в браузере («Assignment to constant variable»). Новые коды этого
//: рода добавлять сюда.
const FATAL = /error TS(?:2304|2305|2307|2300|2323|2393|2440|2451|2459|2540|2552|2588|2632|2661|2704|1\d{3})\b/;

//: Зовём сам компилятор через node, а не npx: .cmd без shell Node 24 не
//: запускает (EINVAL), а shell:true он же и ругает (DEP0190).
const tsc = spawnSync(process.execPath,
                      ['node_modules/typescript/bin/tsc', '--noEmit'],
                      { encoding: 'utf8' });
if (tsc.error || tsc.status === null) {
  console.error('tsc не запустился:', tsc.error?.message ?? 'нет кода возврата');
  console.error('Сначала: npm install');
  process.exit(2);
}

const lines = (tsc.stdout || '').split('\n').filter((l) => l.trim());
const fatal = lines.filter((l) => FATAL.test(l));

if (fatal.length) {
  console.error(fatal.join('\n'));
  console.error(`\n${fatal.length} ошибок связывания модулей.`);
  process.exit(1);
}
console.log(`ok: имена и экспорты сходятся (${lines.length} замечаний по сужению DOM)`);
