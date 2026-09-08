/*
 * Свой список вместо нативного попапа <select>.
 *
 * Тот же приём, что и у выбора цвета (picker.js): сам <select> остаётся на
 * месте, у него по-прежнему читают `.value`, ему выставляют опции
 * (`fillSelect`) и слушают `change`. Мы перехватываем ТОЛЬКО раскрытие и
 * рисуем список своей разметкой. Поэтому отказ этого кода означает возврат к
 * системному списку, а не сломанную страницу.
 *
 * Зачем вообще: раскрытый <select> рисует браузер, и настроить в нём можно
 * ровно цвет пунктов — ни рамок, ни отступов, ни анимации. В WebView2 он к
 * тому же оставался белым в тёмной теме.
 *
 * Список кладётся ВНУТРЬ обёртки `.select`, а не в body: половина полей живёт
 * в модальных окнах, а всё, что приложено к body, оказывается ПОД модальным
 * слоем и становится невидимым.
 */

const OPEN = 'is-open';

//: Открытый сейчас список — он один на страницу.
let current = null;

/** Закрывает открытый список. */
function close() {
  if (!current) return;
  const { box, select } = current;
  box.classList.remove(OPEN);
  select.setAttribute('aria-expanded', 'false');
  // Ждём конец перехода, иначе список исчезает рывком.
  const done = () => box.remove();
  box.addEventListener('transitionend', done, { once: true });
  setTimeout(done, 300);
  current = null;
}

/** Строит список по опциям ЖИВОГО select: их пересобирают на лету. */
function build(select) {
  const box = document.createElement('div');
  box.className = 'dropdown';
  for (const option of select.options) {
    const item = document.createElement('button');
    item.type = 'button';
    item.className = 'dropdown__item'
      + (option.value === select.value ? ' is-active' : '');
    item.textContent = option.text;
    item.dataset.value = option.value;
    if (option.disabled) item.disabled = true;
    box.appendChild(item);
  }
  return box;
}

function pick(select, value) {
  close();
  if (value === select.value) return;
  select.value = value;
  // Событие обязано быть настоящим: на `change` завязаны и каталог, и сборка.
  select.dispatchEvent(new Event('change', { bubbles: true }));
}

function open(select) {
  const wrap = select.closest('.select');
  if (!wrap || !select.options.length) return;
  close();

  const box = build(select);
  wrap.appendChild(box);
  current = { box, select, wrap };
  select.setAttribute('aria-expanded', 'true');

  // Вверх, если снизу не помещается: поля стоят и у нижнего края окна.
  // Чтение offsetHeight заодно ЗАСТАВЛЯЕТ браузер посчитать стили — без этого
  // класс лёг бы в том же кадре, что и вставка, и перехода не было бы вовсе.
  // Через requestAnimationFrame делать нельзя: у скрытого окна кадры не идут,
  // и список остался бы прозрачным, продолжая ловить щелчки.
  const room = window.innerHeight - wrap.getBoundingClientRect().bottom;
  box.classList.toggle('dropdown--up', room < box.offsetHeight + 12);
  box.classList.add(OPEN);

  box.addEventListener('click', (e) => {
    const item = e.target.closest('.dropdown__item');
    if (item) pick(select, item.dataset.value);
  });

  const active = box.querySelector('.is-active');
  if (active) active.scrollIntoView({ block: 'nearest' });
}

// Перехват в фазе ЗАХВАТА: отменённый здесь mousedown не даёт браузеру
// раскрыть системный список, и до обработчиков страницы событие не доходит.
document.addEventListener('mousedown', (e) => {
  const select = e.target.closest && e.target.closest('.select select');
  if (select && !select.disabled) {
    e.preventDefault();
    if (current && current.select === select) close();
    else open(select);
    return;
  }
  if (current && !e.target.closest('.dropdown')) close();
}, true);

// С клавиатуры список тоже должен открываться: поле остаётся фокусируемым.
document.addEventListener('keydown', (e) => {
  const select = e.target.closest && e.target.closest('.select select');
  if (select && (e.key === 'Enter' || e.key === ' ')) {
    e.preventDefault();
    open(select);
    return;
  }
  if (!current) return;
  if (e.key === 'Escape') { e.stopPropagation(); close(); return; }

  const items = [...current.box.querySelectorAll('.dropdown__item:not(:disabled)')];
  const at = items.findIndex((i) => i.classList.contains('is-active'));
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    const next = items[Math.max(0, Math.min(items.length - 1,
      at + (e.key === 'ArrowDown' ? 1 : -1)))];
    if (!next) return;
    items.forEach((i) => i.classList.toggle('is-active', i === next));
    next.scrollIntoView({ block: 'nearest' });
  } else if (e.key === 'Enter') {
    e.preventDefault();
    const chosen = current.box.querySelector('.is-active');
    if (chosen) pick(current.select, chosen.dataset.value);
  }
}, true);

// Список прибит к полю: при прокрутке и смене размера он уезжает.
window.addEventListener('resize', close);
window.addEventListener('scroll', (e) => {
  // ...но прокрутка САМОГО списка его не закрывает. У него max-height 240px и
  // `overflow: auto`, а в «Файле частиц» под сотню эффектов — колесо закрывало
  // список на первом же движении, и до нижних пунктов было не добраться.
  // Закрываем, только когда уехало то, к чему список прибит.
  if (current && !current.box.contains(e.target)) close();
}, true);
