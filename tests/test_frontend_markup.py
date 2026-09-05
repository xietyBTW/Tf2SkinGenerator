"""
Разметка страницы: то, что ломается тихо.

Повторяющийся `id` — не ошибка ни для браузера, ни для проверки типов, а
`getElementById` молча отдаёт ПЕРВЫЙ совпавший. Так у настроек галка
«Сохранять правки предмета» и кнопка «Сохранить» получили общий `cfg-save`:
обработчик сохранения повис на галке, а кнопка не делала ничего — и заметить
это можно было только по тому, что настройки сохраняются от щелчка не туда.
"""

from __future__ import annotations

import collections
import re
import unittest
from pathlib import Path

_PAGE = Path(__file__).resolve().parent.parent / "frontend" / "mockup" / "index.html"

#: id="..." в разметке. Кавычки одинарные страница не использует.
_ID = re.compile(r'\bid="([^"]+)"')


class MarkupTests(unittest.TestCase):
    def test_every_id_is_unique(self):
        ids = _ID.findall(_PAGE.read_text(encoding="utf-8"))
        self.assertTrue(ids, "в разметке не нашлось ни одного id — сломан разбор")
        repeated = sorted(k for k, n in collections.Counter(ids).items() if n > 1)
        self.assertEqual(repeated, [],
                         "повторяющиеся id: getElementById отдаст первый, "
                         "и обработчик уедет не на тот элемент")

    def test_scripts_referenced_by_the_page_exist(self):
        """Точка входа одна, и она обязана существовать."""
        page = _PAGE.read_text(encoding="utf-8")
        for src in re.findall(r'<script[^>]+src="([^"]+)"', page):
            self.assertTrue((_PAGE.parent / src).is_file(), f"нет файла {src}")


if __name__ == "__main__":
    unittest.main()
