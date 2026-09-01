"""
Границы слоёв: ui → app → services / domain, и никак иначе.

Правило держится не на договорённости, а на этом тесте: при переезде
представления на другой стек всё, что ниже `src/ui`, должно собираться и
проверяться без Qt и без единой строчки про виджеты. Один случайный
`from src.ui...` в сервисе — и слой снова слипается.

Импорты ищутся разбором AST, а не импортом модулей: тянуть сюда весь пакет
незачем, а PySide6 в headless-окружении может и не загрузиться.
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
        """Страховка: правило ловит нарушение, а не молчит на пустом списке."""
        self.assertTrue(list(_violations("ui", ("PySide6",))),
                        "в src/ui обязан быть PySide6 — иначе тест ничего не проверяет")


if __name__ == "__main__":
    unittest.main()
