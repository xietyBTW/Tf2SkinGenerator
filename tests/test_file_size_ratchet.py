"""
Храповик размера файлов: god-файлы не должны расти обратно

Новый код по привычке кладут разделом в большой класс, и разрезанный файл
снова дорастает. Тест закрепляет то, что уже разрезано (план -
docs/dev/god-files-plan.md):

- файл логики длиннее LIMIT строк - ошибка, если его нет в BASELINE;
- файл из BASELINE может вырасти не больше чем на SLACK (мелкая правка),
  дальше - новая область уходит в свой модуль, а не в этот файл;
- файл из BASELINE, который заметно похудел, тоже роняет тест: опустите
  его число, иначе запас незаметно съест следующая правка

Таблицы данных и словари (DATA) не проверяются: их размер ничего не ломает
"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIMIT = 900
SLACK = 0.05
SHRUNK = 0.15

#: Данные и чужой код, а не логика
DATA = {
    "src/data/particle_sources_table.py",
    "src/data/translations.py",
    "frontend/mockup/strings.js",
    "frontend/mockup/three.module.js",
    "src/static/js/three.module.js",
}

#: Сколько строк сейчас у файлов длиннее LIMIT. Число можно только уменьшать
BASELINE = {
    "src/app/session.py": 2188,
    "src/app/parts_editor.py": 1864,
    "src/app/particles_editor.py": 1433,
    "src/services/vpk_service.py": 1360,
    "src/services/preview_3d_worker.py": 1289,
    "src/services/model_build_service.py": 1263,
    "src/domain/preview/session.py": 1160,
    "src/services/qc_skin_parser.py": 1015,
    "src/services/texture_compose_service.py": 974,
    "src/services/preview_vpk_mod_worker.py": 952,
    "src/services/vpk_model_pipeline.py": 940,
    "src/services/vmt_effects.py": 921,
    "src/static/viewer3d.html": 3274,
    "src/static/js/particles/engine.js": 2455,
    "src/static/particles3d.html": 1747,
}


def _files():
    """Файлы логики проекта: Python в src/ и frontend/, скрипты и стили страницы,
    3D-превью и частицы (src/static)"""
    for pattern in ("src/**/*.py", "frontend/*.py", "frontend/mockup/*.js",
                    "frontend/mockup/*.css", "src/static/*.html", "src/static/js/**/*.js"):
        for path in ROOT.glob(pattern):
            rel = path.relative_to(ROOT).as_posix()
            if (rel not in DATA and "__pycache__" not in rel
                    and not rel.startswith("src/static/js/addons/")):
                yield rel, path


def _lines(path: Path) -> int:
    with open(path, encoding="utf-8", errors="replace") as f:
        return sum(1 for _ in f)


class FileSizeRatchetTests(unittest.TestCase):
    def test_no_new_god_files(self):
        big = {rel: n for rel, path in _files()
               if rel not in BASELINE and (n := _lines(path)) > LIMIT}
        self.assertEqual(big, {}, f"Файл длиннее {LIMIT} строк: разделите его по "
                         "ответственности (docs/dev/god-files-plan.md)")

    def test_big_files_do_not_grow(self):
        grown = {}
        for rel, limit in BASELINE.items():
            path = ROOT / rel
            if path.is_file() and (n := _lines(path)) > limit * (1 + SLACK):
                grown[rel] = f"{limit} -> {n}"
        self.assertEqual(grown, {}, "Большой файл растёт: новую область - в свой модуль "
                         "(src/app/<имя>_editor.py, отдельный сервис), а не сюда")

    def test_baseline_follows_the_shrinking(self):
        stale = {}
        for rel, limit in BASELINE.items():
            path = ROOT / rel
            n = _lines(path) if path.is_file() else 0
            if n < limit * (1 - SHRUNK):
                stale[rel] = f"{limit} -> {n}"
        self.assertEqual(stale, {}, "Файл похудел: опустите его число в BASELINE "
                         "(или уберите строку, если он короче LIMIT)")


if __name__ == "__main__":
    unittest.main()
