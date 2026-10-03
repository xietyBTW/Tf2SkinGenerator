"""
Запуск нового интерфейса как приложения — в своём окне, без браузера.

Что происходит: локальный сервер поднимается на свободном порту в фоновом
потоке, а страница открывается в окне без адресной строки, вкладок и закладок.
Внешне это обычное приложение; внутри — тот же движок Edge (WebView2), который
и так стоит в Windows.

Окно даёт, по порядку предпочтения:

1. pywebview — настоящий хост (`pip install pywebview`). Именно он останется,
   когда мост Python↔страница переедет с HTTP на `window.pywebview.api`.
2. Edge или Chrome в режиме `--app` — окно без обвязки браузера. Ничего
   доустанавливать не нужно, поэтому это рабочий вариант уже сегодня.
3. Браузер по умолчанию — если не нашлось ни того, ни другого. Тогда это
   честно вкладка, а не окно приложения.

Запуск:
    run.bat ui           (или python frontend/app.py)
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from frontend.devserver import Handler, Server  # noqa: E402  — после правки sys.path
from src.app import api  # noqa: E402

TITLE = "TF2 Skin Generator"

#: Где искать браузер для режима «окно приложения». Edge есть в Windows 11
#: всегда, Chrome — как повезёт.
_BROWSERS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)


def _free_port() -> int:
    """Свободный порт у системы: фиксированный мог быть занят прошлым запуском."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(port: int) -> Server:
    """Поднимает локальный сервер в фоновом потоке."""
    server = Server(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _look() -> dict:
    """
    Тема и анимации из конфига — для первого кадра окна.

    Страница узнаёт настройки только запросом в Python, а до ответа рисуется
    светлой. Тема в адресе (index.html читает её до первого кадра) и цвет фона
    окна убирают и это мигание, и белый кадр WebView2 до загрузки страницы.
    """
    try:
        from src.config.app_config import AppConfig
        cfg = AppConfig.load_config()
    except Exception:  # noqa: BLE001 — без конфига окно просто светлое
        cfg = {}
    dark = cfg.get('theme') == 'dark'
    return {
        'theme': 'dark' if dark else 'light',
        'motion': 'off' if cfg.get('ui_animations') is False else '',
        # --bg тем из base.css: фон окна до первого кадра страницы.
        'background': '#0f0f0e' if dark else '#f2f1ee',
    }


def _open_pywebview(url: str, background: str) -> bool:
    """Настоящее окно приложения. False — pywebview не установлен."""
    try:
        import webview
    except ImportError:
        return False
    from src.shared.paths import data_dir

    window = webview.create_window(TITLE, url, width=1440, height=900,
                                   min_size=(900, 600),
                                   background_color=background)
    api.set_folder_picker(lambda start: _pick_folder(window, start))
    # Профиль WebView2 — в своей папке данных. Без storage_path pywebview
    # заводит его в %TEMP%\tmpXXXXXXXX (сотни файлов) и удаляет только при
    # штатном закрытии окна: после выхода на обновление, краша или занятых
    # файлов папка оставалась, и каждый запуск добавлял новую. Здесь папка
    # одна и та же: приватный режим её по-прежнему чистит, а остаток прошлого
    # раза просто перезапишется.
    webview.start(storage_path=str(data_dir() / 'cache' / 'webview'))
    return True


def _pick_folder(window, start: str) -> str:
    """
    Системный выбор папки поверх окна. Отмена — пустая строка.

    Вызов приходит из потока сервера, а диалог WinForms обязан открываться в
    потоке окна: pywebview сам туда не переходит, и `create_file_dialog` из
    чужого потока может намертво подвесить окно (pywebview #1823). Переходим
    через Invoke — тем же путём, каким pywebview показывает и прячет окно.
    """
    from System import Action  # pythonnet: есть везде, где есть WinForms
    from webview import FileDialog
    from webview.platforms.winforms import BrowserView

    window.events.shown.wait(20)         # форма регистрируется при показе
    form = BrowserView.instances.get(window.uid)
    if form is None:
        return ''
    box = {}
    form.Invoke(Action(lambda: box.update(
        path=window.create_file_dialog(FileDialog.FOLDER, directory=start))))
    chosen = box.get('path')
    return str(chosen[0]) if chosen else ''


def _open_browser_app(url: str) -> bool:
    """Окно браузера без адресной строки и вкладок. False — браузер не найден."""
    exe = next((p for p in _BROWSERS if os.path.isfile(p)), None)
    if exe is None:
        return False
    # Свой профиль: иначе окно прилипает к уже открытому браузеру пользователя
    # и закрывается вместе с ним.
    profile = Path(os.environ.get("LOCALAPPDATA", ".")) / "tf2skingen" / "webview"
    profile.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen([
        exe, f"--app={url}",
        f"--user-data-dir={profile}",
        "--no-first-run", "--no-default-browser-check",
        "--window-size=1440,900",
    ])
    proc.wait()          # окно закрыли — закрываем и приложение
    return True


def main() -> None:
    port = _free_port()
    _serve(port)
    # Индексы архивов игры греются, пока открывается окно.
    api.warm_up()
    look = _look()
    url = f"http://127.0.0.1:{port}/?theme={look['theme']}&motion={look['motion']}"
    print(f"{TITLE}: {url}")

    if _open_pywebview(url, look['background']):
        return
    if _open_browser_app(url):
        return

    # Ни того, ни другого: открываем как обычную страницу и ждём Ctrl+C.
    print("Окно приложения недоступно — открываю в браузере. "
          "Для своего окна: pip install pywebview")
    webbrowser.open(url)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
