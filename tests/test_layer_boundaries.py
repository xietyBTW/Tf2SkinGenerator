"""
Границы слоёв: представление → app → services / domain, и никак иначе.

Переезд состоялся: представление теперь веб-страница (`frontend/`), Qt из
проекта убран целиком. Правило от этого не исчезло — оно и позволило переезд:
всё, что ниже, собиралось и проверялось без тулкита. Запреты на `src.ui` и
`PySide6` остаются СТОРОЖЕМ: вернуть их в сервис проще, чем кажется, и тест
скажет об этом в тот же день.

Импорты ищутся разбором AST, а не импортом модулей: тянуть сюда весь пакет
незачем.
"""

import ast
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"

#: Слой → что ему запрещено импортировать (префиксы модулей).
_FORBIDDEN = {
    "domain": ("src.ui", "src.app", "src.services", "PySide6"),
    "app": ("src.ui", "PySide6"),
    "services": ("src.ui", "src.app", "PySide6"),
}


def _imported_modules(path: Path):
    """Все имена модулей, импортируемые файлом (включая импорты внутри функций)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            # level > 0 — относительный импорт, слой не пересекает
            if node.level == 0 and node.module:
                yield node.module


def _violations(layer: str, forbidden: tuple):
    layer_dir = _SRC / layer
    for path in sorted(layer_dir.rglob("*.py")):
        for module in _imported_modules(path):
            for bad in forbidden:
                if module == bad or module.startswith(bad + "."):
                    yield f"{path.relative_to(_SRC.parent)}: import {module}"


class LayerBoundaryTests(unittest.TestCase):
    def test_domain_is_pure(self):
        """Домен — только правила: ни Qt, ни воркеров, ни виджетов."""
        found = list(_violations("domain", _FORBIDDEN["domain"]))
        self.assertEqual(found, [], "домен не должен зависеть от слоёв выше:\n"
                         + "\n".join(found))

    def test_app_does_not_know_the_view(self):
        """Прикладной слой владеет воркерами, но про UI не знает."""
        found = list(_violations("app", _FORBIDDEN["app"]))
        self.assertEqual(found, [], "app не должен зависеть от представления:\n"
                         + "\n".join(found))

    def test_services_are_free_of_qt(self):
        """Воркеры — фоновая работа; тулкит представления им ни к чему."""
        found = list(_violations("services", _FORBIDDEN["services"]))
        self.assertEqual(found, [], "services не должен зависеть от Qt/UI:\n"
                         + "\n".join(found))

    def test_the_check_itself_can_fail(self):
        """Страховка: правило ловит нарушение, а не молчит на пустом списке.

        Раньше контролем служил живой `src/ui` — там PySide6 был заведомо. Его
        больше нет, поэтому нарушение делаем сами: без такой проверки тест
        зеленел бы и на сломанном `_violations`.
        """
        import tempfile

        with tempfile.TemporaryDirectory(dir=_SRC) as tmp:
            layer = Path(tmp)
            (layer / "offender.py").write_text(
                "from PySide6.QtWidgets import QWidget\n", encoding="utf-8")
            found = list(_violations(layer.name, ("PySide6",)))
        self.assertEqual(len(found), 1, f"нарушение не поймано: {found}")


if __name__ == "__main__":
    unittest.main()
