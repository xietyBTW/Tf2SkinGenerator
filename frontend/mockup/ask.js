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

export function ask({ title, text = '', value = null, list = null, multi = false,
               chosen = [], ok = 'Готово' }) {
  const titleEl = askEl.querySelector('.ask__title');
  const textEl = askEl.querySelector('.ask__text');
  const input = askEl.querySelector('.ask__input');
  const listEl = askEl.querySelector('.ask__list');
  const okBtn = askEl.querySelector('.ask__ok');
  const cancelBtn = askEl.querySelector('.ask__cancel');

  titleEl.textContent = title;
  textEl.textContent = text;
  textEl.hidden = !text;
  input.hidden = value === null;
  input.value = value ?? '';
  listEl.hidden = !list;
  listEl.innerHTML = '';
  askEl.querySelector('.ask__ok').textContent = ok;

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
      askEl.removeEventListener('cancel', onCancel);
      askEl.removeEventListener('close', onCancel);
      if (askEl.open) askEl.close();
      resolve(result);
    };
    const onOk = (e) => {
      e.preventDefault();
      if (list) { settle(multi ? [...marks] : picked); return; }
      settle(value === null ? true : input.value.trim());
    };
    const onCancel = () => settle(null);

    if (list) {
      for (const item of list) {
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
        });
        // Двойной клик — выбрать и закрыть: список длинный, тянуться к
        // кнопке ради каждого выбора незачем. При множественном выборе он
        // означал бы «отметил и передумал», поэтому там его нет.
        if (!multi) {
          b.addEventListener('dblclick', () => {
            picked = value;
            settle(picked);
          });
        }
        listEl.appendChild(b);
      }
    }

    okBtn.addEventListener('click', onOk);
    cancelBtn.addEventListener('click', onCancel);
    askEl.addEventListener('cancel', onCancel);      // Esc
    askEl.addEventListener('close', onCancel);
    askEl.showModal();
    if (value !== null) { input.focus(); input.select(); }
  });
}
