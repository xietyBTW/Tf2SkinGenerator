/*
 * Что страница знает о хозяине окна.
 *
 * В браузере этих полей нет — они появляются, только когда страницу открыл
 * pywebview. Отсюда и `?`: проверка `window.pywebview && ...` в api.js это не
 * перестраховка, а обычный путь для dev-сервера.
 */
interface Window {
  /** Мост pywebview: `api` — те же методы, что и у POST /api/<метод>. */
  pywebview?: {
    api?: Record<string, (params: object) => Promise<unknown>>;
  };
  /** Приёмник событий воркеров; pywebview зовёт его из Python. */
  __tf2Event?: (event: object) => void;
}
