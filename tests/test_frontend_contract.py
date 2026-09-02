"""
Договор между страницей и Python.

Страница зовёт методы по ИМЕНИ строкой, а dev-сервер раскрывает присланный
объект как `fn(**params)`. Значит, разъехаться можно тремя способами, и все
три уже случались: метод есть в api.js, но забыт в белом списке сервера;
метод переименован в Python; у параметра другое имя. Ошибка при этом видна
только в браузере и только когда до кнопки дошли руками.

Тест читает сам JS (регулярками — разбирать JS ради списка строк незачем) и
сверяет с настоящими сигнатурами.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from frontend.devserver import ALLOWED

ROOT = Path(__file__).resolve().parent.parent
#: Весь фронт целиком, с подпапками: вызовы разъехались по модулям
#: (`controls_for` живёт в controls.js, частицы — в particles/), и список
#: файлов пришлось бы дополнять после каждого распила.
_SOURCES = tuple(sorted((ROOT / "frontend" / "mockup").rglob("*.js")))

#: `call('метод', { ключ, ключ })` и `cached(...)` — в api.js через обёртки,
#: в app.js как `api.call(...)`. Тело объекта берём только без вложенности:
#: с ним ключи первого уровня регуляркой уже не выделить, а таких вызовов нет.
_CALL = re.compile(r"\b(?:api\.)?(?:call|cached)\(\s*'([a-z_0-9]+)'"
                   r"(?:\s*,\s*\{([^{}]*)\})?")


def _calls() -> list[tuple[str, str, list[str]]]:
    """(файл, метод, ключи) по всем вызовам с литеральным объектом."""
    found = []
    for path in _SOURCES:
        text = path.read_text(encoding="utf-8")
        for method, body in _CALL.findall(text):
            keys = []
            for part in body.split(","):
                name = part.split(":")[0].strip()
                if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                    keys.append(name)
            found.append((path.name, method, keys))
    return found


def test_calls_found() -> None:
    """Страховка на саму регулярку: молчаливый ноль обесценил бы тест."""
    assert len(_calls()) > 100


@pytest.mark.parametrize("source,method,keys", _calls(),
                         ids=lambda v: v if isinstance(v, str) else None)
def test_call_reaches_python(source: str, method: str, keys: list[str]) -> None:
    fn = ALLOWED.get(method)
    assert fn is not None, (
        f"{source}: метод '{method}' не в белом списке frontend/devserver.py — "
        f"страница получит 404")

    params = inspect.signature(fn).parameters
    takes_any = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
    if takes_any:
        return
    unknown = [k for k in keys if k not in params]
    assert not unknown, (
        f"{source}: {method}(...) не принимает {unknown}; "
        f"есть {sorted(params)}")


def test_allowed_methods_are_public_api() -> None:
    """Белый список ведёт в api.py, а не в случайную функцию."""
    from src.app import api

    for name, fn in ALLOWED.items():
        assert getattr(api, name, None) is fn, (
            f"'{name}' в белом списке указывает не на api.{name}")
