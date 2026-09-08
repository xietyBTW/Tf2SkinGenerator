"""
Английские подписи страницы: словарь не должен отставать от интерфейса.

Перевод сделан на границе показа (`frontend/mockup/i18n.js`), а ключом служит
сам русский текст. Значит, стоит кому-то добавить кнопку — и она молча
останется русской у того, кто выбрал English. Тест ловит именно это: собирает
видимые строки из разметки, кода страницы и сообщений Python и сверяет их со
словарём.

Строки собираются в том виде, в каком доходят до экрана: соседние литералы,
склеенные плюсом, объединяются, а подстановки приводятся к `{}` — по таким
ключам словарь и ищет.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOCKUP = ROOT / "frontend" / "mockup"

#: Сообщения Python, которые доходят до человека подписью на странице.
PY_SOURCES = ("src/app/api.py", "src/app/session.py",
              "src/services/build_worker.py",
              # Подписи разделов и событий каталога звуков: их видит человек,
              # а живут они у данных — страница только раскладывает.
              "src/data/sound_catalog.py")

CYRILLIC = re.compile("[А-яЁё]")
LITERAL = re.compile(r"'([^'\n]*)'|\"([^\"\n]*)\"|`((?:[^`\\]|\\.)*)`", re.S)
GLUED = (re.compile(r"'([^'\n]*)'\s*\+\s*'", re.S),
         re.compile(r'"([^"\n]*)"\s*\+\s*"', re.S))
ENTITIES = {"&lt;": "<", "&gt;": ">", "&amp;": "&", "&nbsp;": " "}

#: Строки, которых человек не видит: журнал разработчика, данные, заглушки.
#: Переводить их незачем, а тест иначе требовал бы.
NOT_SHOWN = {
    "битое событие", "битое событие:", "ё",
    # Имя языка пишется на нём самом.
    "Русский",
    # Записи в лог-файл (logger), а не подписи на странице.
    "api.items: категория {} ещё не подключена",
    "не прочитать OBJ для габаритов: {}",
    "режим без модели: {}",
    "мод из VPK: {}",
    "своя модель: {} keep={} материалов={}",
    "черновиков удалено: {}",
    "работа сохранена: {}",
    "работа предмета возвращена: {}",
    "Получена доп. текстура: {}",
    "Получена доп. модель: {}",
    "Решение пользователя по несовпадению текстур: {} → continue={}",
    "[звук] сборка не удалась: {}",
    "[звук] собрано: {}",
    "[звук] сохранено из игры: {} в {}",
    "[звук] не достали {}",
    "[звук] записей: {} {}, ",
    "с предметом: {}",
    "api.set_ui_state: неизвестный ключ {}",
    # Отказ `set_ui_state`: ключи в него подставляет наш же код, и чужой
    # означает ошибку в странице, а не действие человека — на экран он не
    # попадает, его читает разработчик в журнале обмена.
    "неизвестная настройка: {}",
    # Регулярное выражение, а не подпись.
    "[^0-9a-zA-Zа-яёА-ЯЁ]+",
}

#: Файлы, где русские строки — это сам словарь и его разбор.
SKIP_FILES = {"strings.js", "i18n.js"}


def _no_block_comments(src: str) -> str:
    """JS без блочных комментариев.

    Комментарий начинается со СВОЕЙ строки. Без этой оговорки `'audio/*'`
    сходил за его начало, и всё до ближайшего `*/` вырезалось вместе с живыми
    подписями: три строки страницы молча не попадали в проверку.
    """
    return re.sub(r"(?ms)^[ 	]*/\*.*?\*/", "", src)


def _markup_strings(html: str, add) -> None:
    """Тексты и подписи атрибутов из разметки (в том числе из шаблона в коде)."""
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    for chunk in re.findall(r">([^<>]+)<", html):
        add(chunk.strip())
    for attr in re.findall(r'(?:title|placeholder|aria-label)="([^"]*)"', html):
        add(attr.strip())


def _visible_strings() -> dict:
    """Строка → откуда взялась."""
    found: dict = {}
    source = ""

    def add(text: str) -> None:
        text = text.replace("\\n", "\n")
        for entity, char in ENTITIES.items():
            text = text.replace(entity, char)
        if not CYRILLIC.search(text):
            return
        # Подстановки: `${x}` в JS и `{x}` в f-строках Python.
        text = re.sub(r"\$\{[^}]*\}", "{}", text)
        text = re.sub(r"(?<!\{)\{[^{}]+\}(?!\})", "{}", text)
        if text.strip() and text != "{}":
            found.setdefault(text, source)

    source = "index.html"
    _markup_strings(io.open(MOCKUP / "index.html", encoding="utf-8").read(), add)

    for path in sorted(MOCKUP.rglob("*.js")):
        if path.name in SKIP_FILES:
            continue
        source = path.name
        src = io.open(path, encoding="utf-8").read()
        src = _no_block_comments(src)
        src = re.sub(r"(?m)^\s*//.*$", "", src)
        previous = None
        while previous != src:                    # 'а' + 'б' → 'аб'
            previous = src
            for glue in GLUED:
                src = glue.sub(lambda m: m.group(0)[0] + m.group(1), src)
        for one, two, three in LITERAL.findall(src):
            literal = one or two or three
            # Шаблон разметки внутри кода: проверяем его тексты, а не его сам.
            if "<" in literal and ">" in literal:
                _markup_strings(literal, add)
            else:
                add(literal)

    for name in PY_SOURCES:
        source = Path(name).name
        src = io.open(ROOT / name, encoding="utf-8").read()
        src = re.sub(r'"""(?:.|\n)*?"""', "", src)
        src = re.sub(r"(?m)^\s*#.*$", "", src)
        for one, two, three in LITERAL.findall(src):
            add(one or two or three)
    return found


def _dictionary_keys() -> set:
    src = io.open(MOCKUP / "strings.js", encoding="utf-8").read()
    return {m.group(1).replace("\\'", "'").replace("\\\\", "\\")
            for m in re.finditer(r"^\s*'((?:[^'\\]|\\.)*)':", src, re.M)}


def test_every_visible_string_has_a_translation() -> None:
    keys = _dictionary_keys()
    missing = {text: where for text, where in _visible_strings().items()
               if text not in keys and text.strip() not in keys
               and text not in NOT_SHOWN and text.strip() not in NOT_SHOWN}
    assert not missing, (
        "Нет английского перевода (frontend/mockup/strings.js):\n"
        + "\n".join(f"  [{where}] {text!r}" for text, where in
                    sorted(missing.items(), key=lambda kv: kv[1]))
        + "\n\nЕсли строку человек не видит (журнал, данные) — впишите её в "
          "NOT_SHOWN этого теста.")


def _logger_messages() -> set:
    """
    Тексты вызовов логгера во всём src/.

    Консоль в окне показывает журнал Python (см. frontend/mockup/log.js), и
    переводится он тем же способом — на границе показа. Значит такие строки
    ЗАКОННЫ как ключи словаря. Требовать перевода для всех нельзя: их около
    семисот, и INFO/DEBUG — диагностика для автора, а не подписи для человека.
    Поэтому они участвуют только в проверке на мусор, но не в проверке
    полноты.
    """
    import ast

    levels = {"debug", "info", "warning", "error", "critical", "exception"}
    found = set()

    def literal(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.JoinedStr):
            return "".join(str(v.value) if isinstance(v, ast.Constant) else "{}"
                           for v in node.values)
        return None

    for path in (ROOT / "src").rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in levels and node.args):
                text = literal(node.args[0])
                if text:
                    found.add(text)
    return found


def test_dictionary_has_no_stale_keys() -> None:
    """Ключ, которого больше нет в интерфейсе, — мусор: подписи он не найдёт."""
    visible = set(_visible_strings()) | _logger_messages()
    stripped = {text.strip() for text in visible}
    stale = [key for key in _dictionary_keys()
             if key not in visible and key not in stripped]
    assert not stale, ("Ключи словаря, которых нет в интерфейсе:\n  "
                       + "\n  ".join(sorted(map(repr, stale))))
