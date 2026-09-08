"""
Dev-сервер макета: статика плюс вызовы прикладного API.

Только для разработки. В приложении фронт будет жить в окне WebView2, и мост
даст pywebview (`window.pywebview.api.<метод>`); здесь тот же набор методов
доставляется через HTTP, чтобы страницу можно было открыть в обычном браузере
и проверять на живых данных до того, как хост выбран окончательно.

Меняется при переезде ровно одно место — `frontend/mockup/api.js`, где
`call()` вместо fetch пойдёт в `window.pywebview.api`. Сам `src/app/api.py`
про транспорт не знает и не изменится.

Запуск:
    python frontend/devserver.py [порт]
"""

from __future__ import annotations

import json
import mimetypes
import sys
import tempfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from src.app import api  # noqa: E402  — после правки sys.path
from src.shared.paths import data_dir  # noqa: E402

STATIC = ROOT / "mockup"

#: Вьювер берём из приложения, а не копируем в макет.
VIEWER = (ROOT.parent / "src" / "static").resolve()

#: Разделитель сообщений SSE: пустая строка после данных.
SEP = bytes([10, 10])


#: Откуда разрешено отдавать файлы: временные папки воркеров и рабочие
#: каталоги проекта. Всё остальное — 403.
#:
#: Корни берём у src/shared/paths, а не от расположения этого файла: в
#: собранном приложении данные человека лежат в %LOCALAPPDATA%, а не рядом с
#: кодом, и жёсткое ROOT.parent отдавало бы 403 на собственные же файлы.
_FILE_ROOTS = [
    Path(tempfile.gettempdir()).resolve(),
    (data_dir() / "tools").resolve(),
    (data_dir() / "export").resolve(),
    # Библиотека чужих модов и их обложки.
    (data_dir() / "mods").resolve(),
    # Сохранённые правки человека: work/<ключ предмета>/files. Без этого корня
    # восстановленная текстура отдаётся 403 и карточка в альбоме битая.
    (data_dir() / "work").resolve(),
]


#: Разрешать ли чужому источнику читать ответы (`Access-Control-Allow-Origin`).
#: Включается ТОЛЬКО когда этот модуль запущен сам по себе как dev-сервер —
#: тогда макет открывают и с file://, и с другого порта, и это удобство.
#:
#: В приложении сервер тот же самый (frontend/app.py поднимает этот Handler и
#: грузит страницу по http://127.0.0.1:<порт>), но там `*` означал бы, что
#: любая открытая в браузере страница может перебрать порты, вызвать `build`
#: или `set_settings` и ПРОЧИТАТЬ ответ. Случайный порт — не защита.
DEV_CORS = False


def _same_origin(handler) -> bool:
    """
    Запрос пришёл от нашей же страницы?

    Две независимые проверки, обе — стандартные заголовки браузера:

      Origin           межисточниковый запрос обязан его прислать; свой шлёт
                       ровно наш адрес. Отсутствует — значит это не браузерный
                       кросс-запрос (навигация, <img> со своей же страницы,
                       SSE, curl).
      Sec-Fetch-Site   Chromium (а с ним WebView2 и Edge) шлёт его ВСЕГДА, в
                       том числе на простые POST с text/plain и на загрузку
                       картинок — то есть закрывает как раз те случаи, где
                       Origin может не появиться.

    Не-браузерный клиент на этой же машине сюда всё ещё дойдёт. Это осознанно:
    процесс, запущенный от того же пользователя, и так читает config напрямую,
    и токен в заголовке от него бы не спас.
    """
    site = handler.headers.get("Sec-Fetch-Site")
    if site is not None and site not in ("same-origin", "none"):
        return False
    origin = handler.headers.get("Origin")
    if origin is None:
        return True
    host = handler.headers.get("Host", "")
    return origin in (f"http://{host}", f"https://{host}")


def _drop_alpha(path: Path) -> bytes:
    """
    PNG без альфа-канала.

    Альфа в игровых VTF — чаще маска для бликов и прозрачности материала, а не
    прозрачность самой картинки: у пулемёта она не превышает 120 из 255, и на
    плоском показе текстура выглядит призраком. В 3D альфа нужна по-настоящему,
    поэтому убираем её только здесь, по запросу.
    """
    import io

    from PIL import Image

    with Image.open(path) as im:
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGB")
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return buf.getvalue()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False

#: Белый список: сервер зовёт только эти функции. Иначе POST на /api/<что
#: угодно> дотянулся бы до любого имени в модуле.
ALLOWED = {
    "categories": api.categories,
    "classes": api.classes,
    "weapon_types": api.weapon_types,
    "items": api.items,
    "particle_files": api.particle_files,
    "load_particles": api.load_particles,
    "particle_params": api.particle_params,
    "particle_system": api.particle_system,
    "set_particle_attr": api.set_particle_attr,
    "particle_module_catalog": api.particle_module_catalog,
    "add_particle_module": api.add_particle_module,
    "remove_particle_module": api.remove_particle_module,
    "particle_missing_attrs": api.particle_missing_attrs,
    "add_particle_attr": api.add_particle_attr,
    "remove_particle_attr": api.remove_particle_attr,
    "copy_particle_params": api.copy_particle_params,
    "paste_particle_params": api.paste_particle_params,
    "duplicate_particle_system": api.duplicate_particle_system,
    "rename_particle_system": api.rename_particle_system,
    "remove_particle_system": api.remove_particle_system,
    "particle_children": api.particle_children,
    "add_particle_child": api.add_particle_child,
    "remove_particle_child": api.remove_particle_child,
    "add_particle_layer": api.add_particle_layer,
    "particle_history": api.particle_history,
    "undo_particles": api.undo_particles,
    "particle_control_points": api.particle_control_points,
    "particle_models": api.particle_models,
    "particle_model_scene": api.particle_model_scene,
    "particle_materials": api.particle_materials,
    "set_particle_texture": api.set_particle_texture,
    "reset_particle_texture": api.reset_particle_texture,
    "game_particle_materials": api.game_particle_materials,
    "set_particle_material_to_game": api.set_particle_material_to_game,
    "rename_particle_material": api.rename_particle_material,
    "use_particle_texture_colors": api.use_particle_texture_colors,
    "particle_lint": api.particle_lint,
    "fix_particle_lint": api.fix_particle_lint,
    "save_particles": api.save_particles,
    "export_particles_vpk": api.export_particles_vpk,
    "particle_param_reference": api.particle_param_reference,
    "set_particle_param": api.set_particle_param,
    "hats": api.hats,
    "hat_filters": api.hat_filters,
    "set_hat_filter": api.set_hat_filter,
    "mode_for": api.mode_for,
    "controls_for": api.controls_for,
    "tf2_paths": api.tf2_paths,
    "load_preview": api.load_preview,
    "stop_preview": api.stop_preview,
    "view_state": api.view_state,
    "set_team": api.set_team,
    "set_australium": api.set_australium,
    "toggle_misc": api.toggle_misc,
    "force_team": api.force_team,
    "extract_model": api.extract_model,
    "export_model_files": api.export_model_files,
    "extract_texture": api.extract_texture,
    "export_vpks": api.export_vpks,
    "merge_vpk": api.merge_vpk,
    "material_map_schema": api.material_map_schema,
    "texture_maps": api.texture_maps,
    "set_texture_maps": api.set_texture_maps,
    "work_state": api.work_state,
    "drafts": api.drafts,
    "forget_drafts": api.forget_drafts,
    "works": api.works,
    "keep_work": api.keep_work,
    "restore_work": api.restore_work,
    "forget_work": api.forget_work,
    "add_to_style": api.add_to_style,
    "drop_from_style": api.drop_from_style,
    "texture_settings": api.texture_settings,
    "set_texture_settings": api.set_texture_settings,
    "texture_badges": api.texture_badges,
    "parts": api.parts,
    "set_part_texture": api.set_part_texture,
    "set_part_colors": api.set_part_colors,
    "clear_parts": api.clear_parts,
    "set_part_edge": api.set_part_edge,
    "undo_parts": api.undo_parts,
    "redo_parts": api.redo_parts,
    "vmt_params": api.vmt_params,
    "mod_library": api.mod_library,
    "add_mod": api.add_mod,
    "mod_icon": api.mod_icon,
    "sounds": api.sounds,
    "sound_families": api.sound_families,
    "sound_sections": api.sound_sections,
    "set_sound": api.set_sound,
    "save_sound": api.save_sound,
    "build_sounds": api.build_sounds,
    "remove_mod": api.remove_mod,
    "load_vpk_mod": api.load_vpk_mod,
    "diagnose": api.diagnose,
    "settings": api.settings,
    "cache_size": api.cache_size,
    "update_status": api.update_status,
    "install_update": api.install_update,
    "update_progress": api.update_progress,
    "log_tail": api.log_tail,
    "clear_log": api.clear_log,
    "log_folder": api.log_folder,
    "clear_model_cache": api.clear_model_cache,
    "vmt_snippets": api.vmt_snippets,
    "set_settings": api.set_settings,
    "set_ui_state": api.set_ui_state,
    "load_custom_model": api.load_custom_model,
    "drop_custom_model": api.drop_custom_model,
    "qc_text": api.qc_text,
    "save_qc": api.save_qc,
    "open_vmt": api.open_vmt,
    "save_vmt": api.save_vmt,
    "reset_vmt": api.reset_vmt,
    "set_skin": api.set_skin,
    "load_first_person": api.load_first_person,
    "load_taunt": api.load_taunt,
    "leave_first_person": api.leave_first_person,
    "set_part_detail": api.set_part_detail,
    "toggle_part_island": api.toggle_part_island,
    "merge_part_islands": api.merge_part_islands,
    "part_shape": api.part_shape,
    "part_mask": api.part_mask,
    "load_skybox": api.load_skybox,
    "set_texture": api.set_texture,
    "build": api.build,
    "cancel_build": api.cancel_build,
    "vtf_estimate": api.vtf_estimate,
    "answer_texture": api.answer_texture,
    "export_uv": api.export_uv,
}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def do_GET(self) -> None:  # noqa: N802 — имя задано базовым классом
        # Свои файлы страницы не кэшируем (см. end_headers), игровые — да.
        # Флаг живёт на запрос: обработчик один на всё соединение, и значение
        # с прошлого запроса приезжало в следующий.
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
        # же viewer3d.html, что работает в окне, — второй копии быть не должно.
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
        Отдаёт файл, который сделал воркер (модель, текстура).

        Воркеры пишут во временную папку, а странице нужен URL. Отдаём только
        то, что лежит ВНУТРИ разрешённых каталогов: сервер локальный, но
        превращать его в чтение произвольного диска всё равно незачем.
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
        Иконка предмета из рюкзака, прямо из VPK игры.

        Отдельная ручка, а не /api/: ответ — картинка, и её должен кэшировать
        браузер. Нет иконки — 404, карточка в каталоге остаётся текстовой.
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
        self.send_header("Cache-Control", "max-age=86400")
        self.end_headers()
        self.wfile.write(data)

    def _sound(self) -> None:
        """
        Игровой звук прямо из VPK — странице его проигрывать.

        Отдельная ручка по той же причине, что и у иконки: ответ не JSON, а
        файл, и отдавать его через /api/ значило бы гонять сотни килобайт в
        base64.
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
        # считает поток неперематываемым, и ползунок возвращается на место.
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
        Поток событий воркеров (Server-Sent Events).

        Долгоживущий GET: очередь сеанса разбирается и отдаётся строками
        ``data: {...}``. Пустой ответ drain() — таймаут, шлём комментарий,
        чтобы соединение не сочли мёртвым.

        В окне приложения этого не будет: pywebview толкает события сам через
        evaluate_js. Здесь SSE только потому, что страница живёт в браузере.
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
        except (BrokenPipeError, ConnectionResetError):
            pass          # страницу закрыли или перезагрузили — это нормально
        finally:
            app.unsubscribe(mine)

    def do_POST(self) -> None:  # noqa: N802 — имя задано базовым классом
        # Чужая страница не должна вызывать ни `build`, ни `set_settings`, ни
        # загрузку файла. Проверка — самая первая: у POST есть побочный эффект,
        # и его нельзя выполнить «сначала, а отказать потом».
        if not _same_origin(self):
            self.send_error(403, "cross-origin request")
            return

        # Загрузка файла идёт своим путём — проверять её ДО отсечки по /api/,
        # иначе запрос отвергается раньше, чем доходит до обработчика.
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
        except TypeError as exc:              # не те аргументы — вина вызова
            self._json({"error": f"{name}: {exc}"}, status=400)
        except Exception as exc:              # noqa: BLE001 — граница транспорта
            self._json({"error": f"{name}: {exc}"}, status=500)

    def _upload(self) -> None:
        """
        Принимает файл текстуры и кладёт его во временную папку.

        Тело — сами байты, имя в query: разбирать multipart ради одного файла
        незачем. Путь возвращается странице, чтобы она передала его в
        set_texture — сама сборка работает с файлами на диске.
        """
        from urllib.parse import parse_qs, urlparse

        query = parse_qs(urlparse(self.path).query)
        raw = (query.get("name", ["texture.png"])[0] or "texture.png")
        # Имя приходит от пользователя: берём только базовую часть, чтобы
        # «../» не увёл запись за пределы папки.
        safe = Path(raw).name or "texture.png"

        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            self._json({"error": "пустой файл"}, status=400)
            return

        out_dir = Path(tempfile.gettempdir()) / "tf2sg_uploads"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / safe
        dest.write_bytes(self.rfile.read(length))
        self._json({"result": {"path": str(dest)}})

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # Макет открывают и с file://, и с другого порта — на dev-сервере это
        # не риск, а удобство. В приложении сервер тот же самый, и там `*`
        # означал бы, что чужая страница ЧИТАЕТ наши ответы (см. DEV_CORS).
        if DEV_CORS:
            self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self) -> None:
        # Иначе браузер закэширует правленый CSS и покажет вчерашний макет.
        # Картинки и звуки — исключение: они из игры и не меняются, свой срок
        # жизни ставят сами, и второй, противоречащий заголовок им ни к чему.
        if not getattr(self, "_no_store", True):
            super().end_headers()
            return
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args) -> None:
        # str(): у ошибок первым аргументом приходит HTTPStatus, и проверка «в
        # строке» на нём валилась — сама запись в лог роняла обработку запроса.
        if "/api/" in str(args[0] if args else ""):
            super().log_message(fmt, *args)


def main() -> None:
    global DEV_CORS
    # Логирование как в приложении. Без этого у логгера уровень унаследованный
    # (WARNING), и консоль на странице оставалась пустой: INFO-записи гасились
    # ДО того, как их видел кольцевой буфер. Плюс так dev-запуск и настоящий
    # ведут себя одинаково — расхождение здесь ловится позже всего.
    from src.shared.logging_config import setup_logging
    from src.shared.paths import ensure_data_dir

    setup_logging(log_file=ensure_data_dir() / "tf2sg.log")

    # Запуск руками — это и есть разработка: разрешаем чужому источнику читать
    # ответы. Приложение (frontend/app.py) поднимает Handler само и сюда не
    # заходит, поэтому там остаётся закрыто.
    DEV_CORS = True
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5173
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"макет: http://127.0.0.1:{port}   (API: POST /api/<метод>)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
