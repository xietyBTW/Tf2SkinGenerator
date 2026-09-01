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
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from frontend.devserver import Handler  # noqa: E402  — после правки sys.path

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


def _serve(port: int) -> ThreadingHTTPServer:
    """Поднимает локальный сервер в фоновом потоке."""
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _open_pywebview(url: str) -> bool:
    """Настоящее окно приложения. False — pywebview не установлен."""
    try:
        import webview
    except ImportError:
        return False
    webview.create_window(TITLE, url, width=1440, height=900, min_size=(900, 600))
    webview.start()
    return True


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
    url = f"http://127.0.0.1:{port}"
    print(f"{TITLE}: {url}")

    if _open_pywebview(url):
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
