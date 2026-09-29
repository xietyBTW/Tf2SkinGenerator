"""
Перевод на границе показа: составные сообщения Python.

Итог сборки приходит одной строкой со списком предупреждений, ошибка VPK —
с подробностями по строкам, а причина вложена в шаблон («Гирлянда x не
собралась: {причина}»). Целиком таких строк в словаре нет, поэтому i18n.js
переводит построчно и переводит подстановки. Проверяется в Node на настоящем
модуле; тест пропускается, если node недоступен.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

I18N_JS = Path("frontend/mockup/i18n.js").resolve()

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node недоступен")

_DICT = {
    "Готово": "Done",
    "Гирлянда {} не собралась: {}": "The {} garland didn't build: {}",
    "{} нет в игре": "{} is not in the game",
    "Не найдена игровая текстура '{}' — фиолет.": "Game texture '{}' not found — purple.",
    "VPK файл: {}": "VPK file: {}",
}

_CASES = [
    # Точный ключ и незнакомая строка — как раньше.
    ("Готово", "Done"),
    ("Нечто незнакомое", "Нечто незнакомое"),
    # Причина внутри шаблона тоже переводится; имя файла остаётся как есть.
    ("Гирлянда lights не собралась: lights.mdl нет в игре",
     "The lights garland didn't build: lights.mdl is not in the game"),
    # Итог сборки: первая строка уже английская, пункты списка — по строке,
    # маркер «- » на месте.
    ("VPK successfully created: a.vpk\n\nWarnings:\n- Не найдена игровая текстура 'x' — фиолет.",
     "VPK successfully created: a.vpk\n\nWarnings:\n- Game texture 'x' not found — purple."),
    ("Готово\n  • VPK файл: tf2_misc_dir.vpk", "Done\n  • VPK file: tf2_misc_dir.vpk"),
]


def test_composite_messages_translate() -> None:
    script = f"""
globalThis.Node = {{ TEXT_NODE: 3, ELEMENT_NODE: 1 }};
globalThis.document = {{ body: {{ nodeType: 9 }} }};
globalThis.MutationObserver = class {{ observe() {{}} }};
const {{ useDict, t }} = await import({I18N_JS.as_uri()!r});
useDict({json.dumps(_DICT, ensure_ascii=False)});
console.log(JSON.stringify({json.dumps([c for c, _ in _CASES], ensure_ascii=False)}.map(t)));
"""
    out = subprocess.run(["node", "--input-type=module", "-e", script],
                         capture_output=True, text=True, encoding="utf-8", check=True)
    assert json.loads(out.stdout) == [want for _, want in _CASES]
