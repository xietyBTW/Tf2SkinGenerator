/*
 * Одно окно на три вопроса: ввести текст, выбрать из списка, подтвердить.
 *
 * Модуль ничего не знает о том, кто спрашивает: возвращает значение или null,
 * если отказались. Разметка лежит в index.html (#ask) — окно одно на всё
 * приложение, второго такого не заводить.
 */

// ── Диалог ───────────────────────────────────────────────────────────────
// Три вида в одном окне: спросить текст, выбрать из списка, подтвердить.
// Возвращает значение или null, если отменили.

const askEl = document.getElementById('ask');

//: С какой длины списку нужен поиск.
const SEARCH_FROM = 8;

export function ask({ title, text = '', value = null, list = null, multi = false,
               chosen = [], ok = 'Готово', check = '' }) {
  const titleEl = askEl.querySelector('.ask__title');
  const textEl = askEl.querySelector('.ask__text');
  const input = askEl.querySelector('.ask__input');
  const search = askEl.querySelector('.ask__search');
  const listEl = askEl.querySelector('.ask__list');
  const checkBox = askEl.querySelector('.ask__check');
  const checkInput = checkBox.querySelector('input');
  const okBtn = askEl.querySelector('.ask__ok');
  const cancelBtn = askEl.querySelector('.ask__cancel');

  titleEl.textContent = title;
  textEl.textContent = text;
  textEl.hidden = !text;
  input.hidden = value === null;
  input.value = value ?? '';
  listEl.hidden = !list;
  listEl.innerHTML = '';
  // Поиск — только когда список не охватить взглядом.
  search.hidden = !(list && list.length > SEARCH_FROM);
  search.value = '';
  askEl.querySelector('.ask__ok').textContent = ok;
  // Галка-приписка к ответу: с ней окно отдаёт {value, checked}, без неё —
  // просто значение, как и раньше.
  checkBox.hidden = !check;
  checkInput.checked = false;
  checkBox.querySelector('span').textContent = check || '';

  return new Promise((resolve) => {
    // Один выбор — значение; множественный — набор отмеченного.
    const marks = new Set(multi ? chosen : []);
    let picked = null;
    let done = false;

    // Событие close тут ненадёжно: отправка формы method="dialog" закрывает
    // окно, но события не шлёт — цепочка из двух вопросов подряд на этом
    // молча обрывалась. Поэтому ответ отдаём из обработчиков кнопок, а
    // close/cancel держим только для Esc.
    const settle = (result) => {
      if (done) return;
      done = true;
      okBtn.removeEventListener('click', onOk);
      cancelBtn.removeEventListener('click', onCancel);
      search.removeEventListener('input', onSearch);
      search.removeEventListener('keydown', onSearchKey);
      askEl.removeEventListener('cancel', onCancel);
      askEl.removeEventListener('close', onCancel);
      if (askEl.open) askEl.close();
      resolve(result);
    };
    const wrap = (result) => (check
      ? { value: result, checked: checkInput.checked } : result);
    const onOk = (e) => {
      e.preventDefault();
      if (list) { settle(wrap(multi ? [...marks] : picked)); return; }
      settle(wrap(value === null ? true : input.value.trim()));
    };
    const onCancel = () => settle(null);
    // Фильтр по подстроке имени. Отмеченное при множественном выборе не
    // теряется: прячутся кнопки, а не набор.
    const onSearch = () => {
      const q = search.value.trim().toLowerCase();
      for (const b of listEl.querySelectorAll('.ask__item')) {
        b.hidden = Boolean(q) && !b.textContent.toLowerCase().includes(q);
      }
      // Заголовок группы без видимых пунктов — лишний
      for (const h of listEl.querySelectorAll('.ask__group')) {
        let el = h.nextElementSibling, any = false;
        while (el && !el.classList.contains('ask__group')) {
          if (!el.hidden) { any = true; break; }
          el = el.nextElementSibling;
        }
        h.hidden = !any;
      }
    };
    // Enter в поиске — это не «отправить форму» (окно закрылось бы без
    // ответа), а выбрать первое из найденного.
    const onSearchKey = (e) => {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      const first = listEl.querySelector('.ask__item:not([hidden])');
      if (first) first.dispatchEvent(new MouseEvent(multi ? 'click' : 'dblclick'));
    };
    // Один выбор из списка: пока ничего не выбрано, отвечать нечем — кнопка
    // выключена, иначе «Ответить» без выбора выглядел бы как ответ.
    okBtn.disabled = Boolean(list && !multi);

    if (list) {
      let lastGroup = null;
      for (const item of list) {
        // Заголовок группы — когда список длинный и разнородный (модели:
        // игроки, косметика, оружие). Сам не выбирается; при поиске
        // прячется вместе с пунктами.
        if (item.group && item.group !== lastGroup) {
          const h = document.createElement('p');
          h.className = 'label ask__group';
          h.textContent = item.group;
          listEl.appendChild(h);
          lastGroup = item.group;
        }
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'ask__item';
        b.textContent = item.label ?? item;
        b.title = item.hint || '';
        const value = item.value ?? item;
        if (multi && marks.has(value)) b.classList.add('is-active');
        b.addEventListener('click', () => {
          if (multi) {
            // Отмеченных может быть сколько угодно: подсветку с других не
            // снимаем, иначе список вёл бы себя как выбор одного.
            if (marks.has(value)) marks.delete(value);
            else marks.add(value);
            b.classList.toggle('is-active', marks.has(value));
            return;
          }
          listEl.querySelectorAll('.ask__item')
                .forEach((x) => x.classList.remove('is-active'));
          b.classList.add('is-active');
          picked = value;
          okBtn.disabled = false;
        });
        // Двойной клик — выбрать и закрыть: список длинный, тянуться к
        // кнопке ради каждого выбора незачем. При множественном выборе он
        // означал бы «отметил и передумал», поэтому там его нет.
        if (!multi) {
          b.addEventListener('dblclick', () => {
            picked = value;
            settle(wrap(picked));
          });
        }
        listEl.appendChild(b);
      }
    }

    okBtn.addEventListener('click', onOk);
    cancelBtn.addEventListener('click', onCancel);
    askEl.addEventListener('cancel', onCancel);      // Esc
    askEl.addEventListener('close', onCancel);
    search.addEventListener('input', onSearch);
    search.addEventListener('keydown', onSearchKey);
    askEl.showModal();
    if (value !== null) { input.focus(); input.select(); }
    else if (!search.hidden) search.focus();
  });
}
