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

#: Сообщения Python, которые доходят до человека подписью на странице:
#: ответы API, прогресс и ошибки воркеров, отказы сборки. Слой целиком, а не
#: список файлов: список отставал — прогресс извлечения и ошибки VPK
#: оставались русскими у выбравшего English.
PY_DIRS = ("src/app", "src/services", "src/shared")
PY_SOURCES = (
    # Подписи разделов и событий каталога звуков: их видит человек,
    # а живут они у данных — страница только раскладывает.
    "src/data/sound_catalog.py",
    # Категории необычных эффектов и виды источников — те же
    # подписи каталога.
    "src/data/unusual_effects.py",
    "src/data/particle_sources.py")
#: Модули, которые сами отвечают на двух языках (пары ru/en в кортежах):
#: их русские строки до английского экрана не доходят.
PY_LANG_AWARE = {"error_classifier.py", "vmt_tint.py"}

CYRILLIC = re.compile("[А-яЁё]")
LITERAL = re.compile(r"'([^'\n]*)'|\"([^\"\n]*)\"|`((?:[^`\\]|\\.)*)`", re.S)
GLUED = (re.compile(r"'([^'\n]*)'\s*\+\s*'", re.S),
         re.compile(r'"([^"\n]*)"\s*\+\s*"', re.S))
ENTITIES = {"&lt;": "<", "&gt;": ">", "&amp;": "&", "&nbsp;": " "}

#: Строки, которых человек не видит: журнал разработчика, данные, заглушки.
#: Переводить их незачем, а тест иначе требовал бы.
NOT_SHOWN = {
    "битое событие", "битое событие:", "ё",
    # Таблица «ё → е» для поиска (session._YO), а не подпись.
    "е",
    # Имя языка пишется на нём самом.
    "Русский",
    # Отказ `set_ui_state`: ключи в него подставляет наш же код, и чужой
    # означает ошибку в странице, а не действие человека — на экран он не
    # попадает, его читает разработчик в журнале обмена.
    "неизвестная настройка: {}",
    # Регулярное выражение, а не подпись.
    "[^0-9a-zA-Zа-яёА-ЯЁ]+",
    # Метка и причины, которые уходят только в журнал (переменной, мимо
    # прямого вызова logger — поэтому их не отсеять по вызову).
    "[SKIN BUILD] вариант",
    "вторая строка скинов — стиль, а не пара команды",
    "нет материалов меша для команды (меш={})",
    "(портативно, в {})",
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

    files = [ROOT / name for name in PY_SOURCES]
    for folder in PY_DIRS:
        files += sorted((ROOT / folder).rglob("*.py"))
    for path in files:
        if path.name in PY_LANG_AWARE:
            continue
        source = path.name
        for text in _python_shown(path):
            add(text)
    return found


_LOG_LEVELS = {"debug", "info", "warning", "error", "critical", "exception"}


def _py_text(node):
    """Строка из литерала: у f-строки на месте подстановок `{}`."""
    import ast
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(str(v.value) if isinstance(v, ast.Constant) else "{}"
                       for v in node.values)
    return None


def _ru_test(test):
    """Русская ли ветка у условия: `x == 'ru'` → body (True), `x == 'en'` →
    orelse (False); не про язык — None."""
    import ast
    if isinstance(test, ast.Name) and test.id in ("is_ru", "ru"):
        return True
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        lang = _py_text(test.comparators[0])
        if lang in ("ru", "en") and isinstance(test.ops[0], (ast.Eq, ast.NotEq)):
            return (lang == "ru") == isinstance(test.ops[0], ast.Eq)
    return None


def _python_shown(path: Path) -> list:
    """
    Строки модуля, которые могут дойти до экрана.

    Не в счёт: докстринги, записи в журнал (их политика — в
    `_logger_messages`) и русская половина пар `{'ru': …, 'en': …}` —
    английская у такой пары уже есть.
    """
    import ast
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    skip = set()

    def drop(node):
        skip.update(id(n) for n in ast.walk(node))

    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in _LOG_LEVELS):
            drop(node)
        elif (isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                ast.AsyncFunctionDef))
              and node.body and isinstance(node.body[0], ast.Expr)
              and isinstance(node.body[0].value, ast.Constant)):
            drop(node.body[0])
        elif isinstance(node, ast.Dict):
            pairs = {_py_text(k): v for k, v in zip(node.keys, node.values) if k}
            if "ru" in pairs and "en" in pairs:
                drop(pairs["ru"])
        elif isinstance(node, (ast.If, ast.IfExp)) and _ru_test(node.test) is not None:
            # `… if lang == 'ru' else …`: русская ветка идёт только русским.
            ru_branch = node.body if _ru_test(node.test) else node.orelse
            for part in (ru_branch if isinstance(ru_branch, list) else [ru_branch]):
                drop(part)
    out = []
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        text = _py_text(node)
        if text is None:
            continue
        if isinstance(node, ast.JoinedStr):
            drop(node)                  # куски f-строки — не отдельные подписи
        out.append(text)
    return out


def _dictionary_keys() -> set:
    src = io.open(MOCKUP / "strings.js", encoding="utf-8").read()
    # `\n` в ключе — перевод строки, как и в тексте на экране.
    return {m.group(1).replace("\\'", "'").replace("\\n", "\n").replace("\\\\", "\\")
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
