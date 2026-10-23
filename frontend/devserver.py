"""
Dev-сервер макета: статика плюс вызовы прикладного API

Только для разработки. В приложении фронт будет жить в окне WebView2, и мост
даст pywebview (`window.pywebview.api.<метод>`), здесь тот же набор методов
доставляется через HTTP, чтобы страницу можно было открыть в обычном браузере
и проверять на живых данных до того, как хост выбран окончательно

Меняется при переезде ровно одно место - `frontend/mockup/api.js`, где
`call()` вместо fetch пойдёт в `window.pywebview.api`. Сам пакет `src/app/api/`
про транспорт не знает и не изменится

Запуск:
    python frontend/devserver.py [порт]
"""

from __future__ import annotations

import functools
import json
import mimetypes
import sys
import tempfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from src.app import api  # noqa: E402  - после правки sys.path
from src.shared.paths import data_dir  # noqa: E402

STATIC = ROOT / "mockup"

#: Вьювер берём из приложения, а не копируем в макет
VIEWER = (ROOT.parent / "src" / "static").resolve()

#: Разделитель сообщений SSE: пустая строка после данных
SEP = bytes([10, 10])


#: Откуда разрешено отдавать файлы: временные папки воркеров и рабочие
#: каталоги проекта. Всё остальное - 403
#:
#: Корни берём у src/shared/paths, а не от расположения этого файла: в
#: собранном приложении данные человека лежат в %LOCALAPPDATA%, а не рядом с
#: кодом, и жёсткое ROOT.parent отдавало бы 403 на собственные же файлы
_FILE_ROOTS = [
    Path(tempfile.gettempdir()).resolve(),
    (data_dir() / "tools").resolve(),
    (data_dir() / "export").resolve(),
    # Библиотека чужих модов и их обложки
    (data_dir() / "mods").resolve(),
    # Сохранённые правки человека: work/<ключ предмета>/files. Без этого корня
    # восстановленная текстура отдаётся 403 и карточка в альбоме битая
    (data_dir() / "work").resolve(),
    # Значки классов из игры (окно выбора классов) - только эта папка кэша
    (data_dir() / "cache" / "class_icons").resolve(),
]


#: Разрешать ли чужому источнику читать ответы (`Access-Control-Allow-Origin`).
#: Включается ТОЛЬКО когда этот модуль запущен сам по себе как dev-сервер -
#: тогда макет открывают и с file://, и с другого порта, и это удобство
#:
#: В приложении сервер тот же самый (frontend/app.py поднимает этот Handler и
#: грузит страницу по http://127.0.0.1:<порт>), но там `*` означал бы, что
#: любая открытая в браузере страница может перебрать порты, вызвать `build`
#: или `set_settings` и ПРОЧИТАТЬ ответ. Случайный порт - не защита
DEV_CORS = False

#: Имена, под которыми страница открывает сервер (Host без порта)
_LOCAL_HOSTS = ("127.0.0.1", "localhost", "[::1]")


def _same_origin(handler) -> bool:
    """
    Запрос пришёл от нашей же страницы?

    Две независимые проверки, обе - стандартные заголовки браузера:

      Origin           межисточниковый запрос обязан его прислать, свой шлёт
                       ровно наш адрес. Отсутствует - значит это не браузерный
                       кросс-запрос (навигация, <img> со своей же страницы,
                       SSE, curl).
      Sec-Fetch-Site   Chromium (а с ним WebView2 и Edge) шлёт его ВСЕГДА, в
                       том числе на простые POST с text/plain и на загрузку
                       картинок - то есть закрывает как раз те случаи, где
                       Origin может не появиться

    Не-браузерный клиент на этой же машине сюда всё ещё дойдёт. Это осознанно:
    процесс, запущенный от того же пользователя, и так читает config напрямую,
    и токен в заголовке от него бы не спас

    Третья проверка - Host. Порт у приложения постоянный (кэш браузера), и
    чужой сайт мог бы перепривязать своё имя на 127.0.0.1 (DNS rebinding):
    тогда для браузера запрос «свой», Origin и Host совпадают. Имя в Host у
    такого запроса чужое, а у нашей страницы - только локальное
    """
    host = handler.headers.get("Host", "")
    name, _, port = host.rpartition(":")
    if not (port.isdigit() and name):          # без порта: «127.0.0.1», «[::1]»
        name = host
    if name not in _LOCAL_HOSTS:
        return False
    site = handler.headers.get("Sec-Fetch-Site")
    if site is not None and site not in ("same-origin", "none"):
        return False
    origin = handler.headers.get("Origin")
    if origin is None:
        return True
    return origin in (f"http://{host}", f"https://{host}")


def _drop_alpha(path: Path) -> bytes:
    """
    PNG без альфа-канала

    Альфа в игровых VTF - чаще маска для бликов и прозрачности материала, а не
    прозрачность самой картинки: у пулемёта она не превышает 120 из 255, и на
    плоском показе текстура выглядит призраком. В 3D альфа нужна по-настоящему,
    поэтому убираем её только здесь, по запросу

    Альбом спрашивает одну и ту же картинку на каждое обновление вида, а
    перекодировать 2048 стоит четверть секунды под GIL, поэтому результат
    запоминается, пока файл не изменился
    """
    st = path.stat()
    return _opaque_png(str(path), st.st_mtime_ns, st.st_size)


@functools.lru_cache(maxsize=24)
def _opaque_png(path: str, _mtime_ns: int, _size: int) -> bytes:
    import io

    from PIL import Image

    with Image.open(path) as im:
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGB")
        buf = io.BytesIO()
        # Файл живёт в памяти и уходит по локальному сокету: размер не важен,
        # а сжатие по умолчанию втрое медленнее
        im.save(buf, format="PNG", compress_level=1)
        return buf.getvalue()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False

#: Белый список: сервер зовёт только эти функции. Иначе POST на /api/<что
#: угодно> дотянулся бы до любого имени в модуле. Список ведёт сам пакет api:
#: функция попадает сюда декоратором `@endpoint`
ALLOWED = api.ENDPOINTS


class Server(ThreadingHTTPServer):
    """
    Очередь входящих соединений побольше стандартных пяти

    На старте страница тянет полсотни модулей, каждый - отдельным соединением
    (HTTP/1.0), а поток сервера в это время делит GIL с прогревом items_game.
    Windows на переполненную очередь отвечает отказом, модуль не грузится, и
    вместе с ним не запускается весь интерфейс: пустой каталог и ни одного
    вызова в Python
    """
    request_queue_size = 128
    #: HTTPServer ставит SO_REUSEADDR, а на Windows он разрешает второму
    #: процессу сесть на тот же порт ПОВЕРХ живого (проверено): второй
    #: экземпляр приложения делил бы порт с первым вместо ошибки и запасного
    allow_reuse_address = sys.platform != "win32"

    def handle_error(self, request, client_address) -> None:
        # Браузер оборвал запрос (картинку заменили раньше, чем она доехала,
        # страницу перезагрузили) - это не ошибка сервера, и трейсбек в окне
        # консоли только пугает. Остальное печатаем как обычно
        import sys
        if isinstance(sys.exc_info()[1], ConnectionError):
            return
        super().handle_error(request, client_address)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def do_GET(self) -> None:  # noqa: N802 - имя задано базовым классом
        # Свои файлы страницы не кэшируем (см. end_headers), игровые - да.
        # Флаг живёт на запрос: обработчик один на всё соединение, и значение
        # с прошлого запроса приезжало в следующий
        self._no_store = True
        if not _same_origin(self):
            self.send_error(403, "cross-origin request")
            return
        if self.path == "/events":
            self._events()
            return
        if self.path.startswith("/file?"):
            self._file()
            return
        if self.path.startswith("/icon?"):
            self._no_store = False
            self._icon()
            return
        if self.path.startswith("/sound?"):
            self._no_store = False
            self._sound()
            return
        # Вьювер и его модули лежат в приложении и отдаются как есть: это тот
        # же viewer3d.html, что работает в окне, - второй копии быть не должно
        if self.path.startswith("/viewer/"):
            self.directory = str(VIEWER)
            self.path = self.path[len("/viewer"):]
            try:
                super().do_GET()
            finally:
                self.directory = str(STATIC)
            return
        super().do_GET()

    def _file(self) -> None:
        """
        Отдаёт файл, который сделал воркер (модель, текстура)

        Воркеры пишут во временную папку, а странице нужен URL. Отдаём только
        то, что лежит ВНУТРИ разрешённых каталогов: сервер локальный, но
        превращать его в чтение произвольного диска всё равно незачем
        """
        from urllib.parse import parse_qs, urlparse

        raw = parse_qs(urlparse(self.path).query).get("path", [""])[0]
        try:
            path = Path(raw).resolve(strict=True)
        except OSError:
            self.send_error(404)
            return

        if not any(_is_within(path, root) for root in _FILE_ROOTS):
            self.send_error(403, "path outside allowed roots")
            return

        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if "opaque=1" in self.path:
            data, ctype = _drop_alpha(path), "image/png"
        else:
            data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _icon(self) -> None:
        """
        Иконка предмета из рюкзака, прямо из VPK игры

        Отдельная ручка, а не /api/: ответ - картинка, и её должен кэшировать
        браузер. Нет иконки - 404, карточка в каталоге остаётся текстовой
        """
        from urllib.parse import parse_qs, unquote, urlparse

        key = unquote(parse_qs(urlparse(self.path).query).get("key", [""])[0])
        try:
            data = api.icon_png(key)
        except Exception as exc:                      # noqa: BLE001
            self.log_message("icon %s: %s", key, exc)
            data = None
        if not data:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data)))
        # Иконка из игры не меняется, а меняется то, как её рисуем, - это
        # `v=` в адресе (api.iconUrl). Месяц, а не сутки: валидаторов у ответа
        # нет, и по истечении срока браузер скачивал бы всё заново
        self.send_header("Cache-Control", "max-age=2592000, immutable")
        self.end_headers()
        self.wfile.write(data)

    def _sound(self) -> None:
        """
        Игровой звук прямо из VPK - странице его проигрывать

        Отдельная ручка по той же причине, что и у иконки: ответ не JSON, а
        файл, и отдавать его через /api/ значило бы гонять сотни килобайт в
        base64
        """
        from urllib.parse import parse_qs, unquote, urlparse

        wave = unquote(parse_qs(urlparse(self.path).query).get("wave", [""])[0])
        try:
            data = api.sound_wave(wave)
        except Exception as exc:                      # noqa: BLE001
            self.log_message("sound %s: %s", wave, exc)
            data = None
        if not data:
            self.send_error(404)
            return
        kind = "audio/mpeg" if wave.lower().endswith(".mp3") else "audio/wav"
        # Перемотка в <audio> требует байтовых диапазонов: без них Chrome
        # считает поток неперематываемым, и ползунок возвращается на место
        rng = self.headers.get("Range", "")
        partial = rng.startswith("bytes=")
        head, _, tail = rng[len("bytes="):].partition("-") if partial else ("", "", "")
        start = int(head) if head.isdigit() else 0
        end = int(tail) if tail.isdigit() else len(data) - 1
        start, end = min(start, len(data) - 1), min(end, len(data) - 1)
        body = data[start:end + 1]

        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", kind)
        self.send_header("Accept-Ranges", "bytes")
        if partial:
            self.send_header("Content-Range",
                             f"bytes {start}-{end}/{len(data)}")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=3600")
        self.end_headers()
        self.wfile.write(body)

    def _events(self) -> None:
        """
        Поток событий воркеров (Server-Sent Events)

        Долгоживущий GET: очередь сеанса разбирается и отдаётся строками
        ``data: {...}``. Пустой ответ drain() - таймаут, шлём комментарий,
        чтобы соединение не сочли мёртвым

        В окне приложения этого не будет: pywebview толкает события сам через
        evaluate_js. Здесь SSE только потому, что страница живёт в браузере
        """
        from src.app.session import session

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        app = session()
        mine = app.subscribe()
        try:
            while True:
                events = app.drain(mine, timeout=20.0)
                if not events:
                    self.wfile.write(b": keep-alive" + SEP)
                else:
                    for ev in events:
                        line = json.dumps(ev, ensure_ascii=False)
                        self.wfile.write(b"data: " + line.encode("utf-8") + SEP)
                self.wfile.flush()
        except ConnectionError:
            # Страницу закрыли или перезагрузили - это нормально. Именно общий
            # класс: закрытое окно WebView2 даёт ConnectionAbortedError, и он
            # уходил мимо, трейсбеком в консоль
            pass
        finally:
            app.unsubscribe(mine)

    def do_POST(self) -> None:  # noqa: N802 - имя задано базовым классом
        # Чужая страница не должна вызывать ни `build`, ни `set_settings`, ни
        # загрузку файла. Проверка - самая первая: у POST есть побочный эффект,
        # и его нельзя выполнить «сначала, а отказать потом»
        if not _same_origin(self):
            self.send_error(403, "cross-origin request")
            return

        # Загрузка файла идёт своим путём - проверять её ДО отсечки по /api/,
        # иначе запрос отвергается раньше, чем доходит до обработчика
        if self.path.startswith("/upload"):
            self._upload()
            return

        if not self.path.startswith("/api/"):
            self.send_error(404)
            return

        name = self.path[len("/api/"):]
        fn = ALLOWED.get(name)
        if fn is None:
            self._json({"error": f"неизвестный метод: {name}"}, status=404)
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
            params = json.loads(self.rfile.read(length) or b"{}")
            self._json({"result": fn(**params)})
        except TypeError as exc:              # не те аргументы - вина вызова
            self._json({"error": f"{name}: {exc}"}, status=400)
        except Exception as exc:              # noqa: BLE001 - граница транспорта
            self._json({"error": f"{name}: {exc}"}, status=500)

    def _upload(self) -> None:
        """
        Принимает файл текстуры и кладёт его во временную папку

        Тело - сами байты, имя в query: разбирать multipart ради одного файла
        незачем. Путь возвращается странице, чтобы она передала его в
        set_texture - сама сборка работает с файлами на диске
        """
        from urllib.parse import parse_qs, urlparse

        query = parse_qs(urlparse(self.path).query)
        raw = (query.get("name", ["texture.png"])[0] or "texture.png")
        # Имя приходит от пользователя: берём только базовую часть, чтобы
        # «../» не увёл запись за пределы папки
        safe = Path(raw).name or "texture.png"

        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            self._json({"error": "пустой файл"}, status=400)
            return

        # Папка по содержимому: два разных файла с одним именем (у брошенных
        # из браузера это часто «image.png») иначе писались в один путь, и
        # второй тихо подменял первый там, где тот уже выбран. Имя файла
        # остаётся прежним - его показывают подписи
        import hashlib
        body = self.rfile.read(length)
        out_dir = Path(tempfile.gettempdir()) / "tf2sg_uploads" / hashlib.sha1(body).hexdigest()[:12]
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / safe
        if not dest.is_file():
            dest.write_bytes(body)
        self._json({"result": {"path": str(dest)}})

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # Макет открывают и с file://, и с другого порта - на dev-сервере это
        # не риск, а удобство. В приложении сервер тот же самый, и там `*`
        # означал бы, что чужая страница ЧИТАЕТ наши ответы (см. DEV_CORS)
        if DEV_CORS:
            self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self) -> None:
        # Иначе браузер закэширует правленый CSS и покажет вчерашний макет.
        # Картинки и звуки - исключение: они из игры и не меняются, свой срок
        # жизни ставят сами, и второй, противоречащий заголовок им ни к чему
        if not getattr(self, "_no_store", True):
            super().end_headers()
            return
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args) -> None:
        # str(): у ошибок первым аргументом приходит HTTPStatus, и проверка «в
        # строке» на нём валилась - сама запись в лог роняла обработку запроса
        if "/api/" in str(args[0] if args else ""):
            super().log_message(fmt, *args)


def main() -> None:
    global DEV_CORS
    # Логирование как в приложении. Без этого у логгера уровень унаследованный
    # (WARNING), и консоль на странице оставалась пустой: INFO-записи гасились
    # ДО того, как их видел кольцевой буфер. Плюс так dev-запуск и настоящий
    # ведут себя одинаково - расхождение здесь ловится позже всего
    from src.shared.logging_config import setup_logging
    from src.shared.paths import ensure_data_dir

    setup_logging(log_file=ensure_data_dir() / "tf2sg.log")

    # Запуск руками - это и есть разработка: разрешаем чужому источнику читать
    # ответы. Приложение (frontend/app.py) поднимает Handler само и сюда не
    # заходит, поэтому там остаётся закрыто
    DEV_CORS = True
    args = sys.argv[1:]
    # `--work-dir <папка>` - черновики и работы dev-сервера отдельно от
    # приложения. В разработке оба пишут в work/ репозитория, и проверка на
    # dev-сервере, пока открыто приложение, перезаписывала бы живой черновик
    # человека своей правкой
    if '--work-dir' in args:
        at = args.index('--work-dir')
        from src.services import work_store
        work_store.WORK_DIR = Path(args[at + 1]).resolve()
        _FILE_ROOTS.append(work_store.WORK_DIR)
        del args[at:at + 2]
    port = int(args[0]) if args else 5173
    server = Server(("127.0.0.1", port), Handler)
    print(f"макет: http://127.0.0.1:{port}   (API: POST /api/<метод>)")
    api.warm_up()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
