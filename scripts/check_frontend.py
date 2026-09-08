"""
Сверка страницы саму с собой: id, методы моста и события Python.

Зачем. Страница, транспорт и прикладной API правятся по отдельности, и связь
между ними держится на строках: `getElementById('vmt-save')`, `api.saveVmt`,
`call('save_vmt')`, `case 'need_texture'`. Опечатка в любой из них не ломает
сборку и не роняет тесты — она молча выключает кусок интерфейса.

Здесь всё это сверяется в лоб:
  • каждый id, который ищет app.js, есть в index.html;
  • каждый `api.<метод>` экспортирован из api.js;
  • каждый `call('<метод>')` есть в белом списке dev-сервера и в src/app/api.py;
  • каждый `data-cond` имеет ключ в COND_KEY;
  • каждое событие, которое шлёт Python, обрабатывается страницей.

Запуск:
  python scripts/check_frontend.py

Код возврата 2 — есть расхождения.
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def read(path: str) -> str:
    return io.open(path, encoding="utf-8").read()


def code_only(text: str) -> str:
    """Текст без комментариев: в них полно упоминаний методов и id."""
    # Блочный комментарий начинается со СВОЕЙ строки. Без этой оговорки
    # `chooseFile('audio/*')` сходил за его начало, и до ближайшего `*/`
    # вырезался живой код — вместе с именами, ради которых всё это.
    text = re.sub(r"(?ms)^[ 	]*/\*.*?\*/", "", text)
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


def page_code() -> str:
    """Весь код страницы одной строкой, без комментариев.

    Раньше здесь читался ОДИН app.js, и это молча сломалось, когда страницу
    разложили по модулям: COND_KEY уехал в controls.js, разбор событий — в
    events.js, и проверка начала ругаться на каждый data-cond и каждое
    событие разом. Сорок семь выдуманных расхождений — это то же самое, что
    ни одного: их перестают читать.
    """
    root = os.path.join("frontend", "mockup")
    files = sorted(os.path.join(base, name)
                   for base, _, names in os.walk(root)
                   for name in names if name.endswith(".js"))
    return "\n".join(code_only(read(p)) for p in files)


def check() -> list:
    app = page_code()
    html = read("frontend/mockup/index.html")
    api_js = read("frontend/mockup/api.js")
    server = read("frontend/devserver.py")
    api_py = read("src/app/api.py")
    session = read("src/app/session.py")

    problems = []

    ids_in_html = set(re.findall(r'id="([^"]+)"', html))
    for used in sorted(set(re.findall(r"getElementById\('([^']+)'\)", app))):
        if used not in ids_in_html:
            problems.append(f"нет id в разметке: {used}")

    # Мост экспортирует и стрелки (`export const`), и обычные функции.
    exported = (set(re.findall(r"export const (\w+)", api_js))
                | set(re.findall(r"export (?:async )?function (\w+)", api_js)))
    for used in sorted(set(re.findall(r"\bapi\.(\w+)\(", app))):
        if used not in exported:
            problems.append(f"нет в api.js: api.{used}")

    whitelist = dict(re.findall(r'"(\w+)":\s*api\.(\w+)', server))
    functions = set(re.findall(r"^def (\w+)\(", api_py, re.M))
    for called in sorted(set(re.findall(r"call\('(\w+)'", api_js))):
        if called not in whitelist:
            problems.append(f"нет в белом списке dev-сервера: {called}")
        elif whitelist[called] not in functions:
            problems.append(f"белый список ссылается в никуда: api.{whitelist[called]}")

    cond_keys = set(re.findall(r"^\s*(\w+):\s*'[\w_]+',", app, re.M))
    for cond in sorted(set(re.findall(r'data-cond="([^"]+)"', html))):
        if cond not in cond_keys:
            problems.append(f"data-cond без ключа в COND_KEY: {cond}")

    # События: имя из _put(...) плюс имена, которые уезжают параметром
    # (у инструментов общий обработчик с done='tool_done').
    emitted = (set(re.findall(r"_put\('(\w+)'", session))
               | set(re.findall(r"done: str = '(\w+)'", session)))
    handled = set(re.findall(r"case '(\w+)':", app))
    for event in sorted(emitted - handled):
        # Событие без обработчика — не всегда ошибка: страница может не
        # интересоваться им (blu_same_as_red меняет только подпись кнопки).
        problems.append(f"событие Python без обработчика на странице: {event}")
    for event in sorted(handled - emitted):
        problems.append(f"обработчик события, которого никто не шлёт: {event}")

    return problems


def main() -> int:
    problems = check()
    if not problems:
        print("расхождений нет")
        return 0
    print("\n".join(problems))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
