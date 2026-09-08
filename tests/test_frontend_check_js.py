"""
Страница вообще собирается: разбор модулей и связи имён.

В `frontend/check.mjs` это уже написано — он гоняет tsc и валит проверку на
синтаксисе (TS1xxx), неизвестном имени, пропавшем экспорте. Не хватало одного:
никто его не звал. Сломанная кавычка в `strings.js` прошла весь набор тестов —
словарь-то проверяется чтением текста — и обнаружилась только глазами в окне,
где вместе со словарём отвалилась половина страницы.

Тест пропускается, если node или tsc не установлены: это проверка разработчика,
а не условие работы приложения.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

CHECK = Path("frontend/check.mjs")
TSC = Path("frontend/node_modules/typescript/bin/tsc")

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not CHECK.exists() or not TSC.exists(),
    reason="нет node или frontend/node_modules (npm install)")


def test_page_modules_parse_and_link():
    done = subprocess.run(["node", CHECK.name], cwd=str(CHECK.parent),
                          capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, (done.stdout or '') + (done.stderr or '')
