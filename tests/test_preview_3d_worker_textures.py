"""
Извлечение текстур в воркере превью — против фейкового VPK.

Раньше эти 1800 строк проверялись только руками на установленной игре, и
ошибки в них всплывали как «у шапки не та текстура на линзе» через месяцы.
Здесь модель (QC на диске) и архивы (словарь путей) поддельные, поэтому
проверяется именно логика: какой материал берётся для команды и когда команда
вообще что-то меняет.

Тест пропускается, если PySide6 недоступен или подменён заглушкой соседних
worker-тестов (см. test_particles_cp_controls).
"""

import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_pyside = sys.modules.get("PySide6")
if _pyside is not None and not hasattr(_pyside, "__path__"):
    pytest.skip("PySide6 подменён заглушкой соседних тестов",
                allow_module_level=True)

pytest.importorskip("PySide6.QtWidgets")

from src.services.preview_3d_worker import Preview3DWorker   # noqa: E402
from tests.fake_vpk import fake_reader, vmt                   # noqa: E402

CD = "models/workshop/player/items/demo/hat"

#: Раскладка Alcoholic Automaton: четыре столбца, команда переключает два,
#: линза (столбцы 3-4) в обеих строках одна и та же.
QC_FOUR_COLUMNS = """
$modelname "hat.mdl"
$cdmaterials "models\\workshop\\player\\items\\demo\\hat\\"

$texturegroup "skinfamilies"
{
\t{ "auto_1"      "auto"      "auto_1_blue" "auto_blue" }
\t{ "auto_1_blue" "auto_blue" "auto_1_blue" "auto_blue" }
}
"""

QC_SIMPLE_TEAM = """
$modelname "hat.mdl"
$cdmaterials "models\\workshop\\player\\items\\demo\\hat\\"

$texturegroup "skinfamilies"
{
\t{ "hat" }
\t{ "hat_blue" }
}
"""


def _png_bytes(color=(20, 20, 20, 255)) -> bytes:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGBA", (4, 4), color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _stub_vtf_decoder():
    """«VTF-байты» в этих тестах — уже готовый PNG."""
    from src.services import vtf_preview_service as vps

    orig = vps.vtf_bytes_to_png

    def fake(data, out_png_path, tmp_dir=None):
        if not data:
            return None
        Path(out_png_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_png_path).write_bytes(data)
        return out_png_path

    def fake_frames(data, out_dir, base_name, tmp_dir=None):
        """Запасной путь просит ВСЕ кадры — у нас всегда один."""
        path = Path(out_dir) / f"{base_name}.png"
        return [p] if (p := fake(data, str(path))) else []

    orig_frames = vps.vtf_bytes_to_frame_pngs
    vps.vtf_bytes_to_png = fake
    vps.vtf_bytes_to_frame_pngs = fake_frames
    yield
    vps.vtf_bytes_to_png = orig
    vps.vtf_bytes_to_frame_pngs = orig_frames


def _worker(files, qc_text, tmp) -> tuple:
    """Воркер с поддельным VPK и QC на диске. → (worker, decomp_dir)."""
    decomp = Path(tmp) / "decomp"
    decomp.mkdir(parents=True, exist_ok=True)
    (decomp / "hat.qc").write_text(qc_text, encoding="utf-8")

    w = Preview3DWorker("hat", "hat", "", "")
    w._preview_dir = str(Path(tmp) / "preview")
    Path(w._preview_dir).mkdir(parents=True, exist_ok=True)
    w._reader = fake_reader(files)
    return w, str(decomp)


def _files(**materials) -> dict:
    """{материал: (basetexture, цвет)} → содержимое архива."""
    out = {}
    for mat, (base, color) in materials.items():
        out[f"materials/{CD}/{mat}.vmt"] = vmt(basetexture=base)
        out[f"materials/{base}.vtf"] = _png_bytes(color)
    return out


def test_hat_blu_is_per_material(app):
    """Команда переключает не все материалы: общие остаются собой.

    Именно из-за одной общей BLU-текстуры линза Alcoholic Automaton получала
    текстуру корпуса.
    """
    with TemporaryDirectory() as tmp:
        files = _files(
            auto_1=("models/hat/a1", (10, 0, 0, 255)),
            auto=("models/hat/a", (20, 0, 0, 255)),
            auto_1_blue=("models/hat/a1b", (0, 0, 10, 255)),
            auto_blue=("models/hat/ab", (0, 0, 20, 255)),
        )
        w, decomp = _worker(files, QC_FOUR_COLUMNS, tmp)
        mats = ["auto_1", "auto", "auto_1_blue", "auto_blue"]
        w._extract_hat_textures_via_qc_vmt(decomp, mats)
        raw = w._extract_hat_blu_textures(decomp, mats)

        # Меняются два материала…
        assert raw["auto_1"][1] == "auto_1_blue"
        assert raw["auto"][1] == "auto_blue"
        assert raw["auto_1"][0] and raw["auto"][0], "у них своя BLU-картинка"
        # …а общие столбцы ссылаются сами на себя и картинки не получают
        assert raw["auto_1_blue"] == (None, "auto_1_blue")
        assert raw["auto_blue"] == (None, "auto_blue")


def test_identical_blu_reports_no_difference(app):
    """BLU-материал есть, но он копия RED — панель должна об этом узнать."""
    with TemporaryDirectory() as tmp:
        files = _files(
            hat=("models/hat/color", (30, 30, 30, 255)),
            hat_blue=("models/hat/color", (30, 30, 30, 255)),   # та же текстура
        )
        w, decomp = _worker(files, QC_SIMPLE_TEAM, tmp)
        fired = []
        w.blu_same_as_red.connect(lambda: fired.append(1))

        w._extract_hat_textures_via_qc_vmt(decomp, ["hat"])
        raw = w._extract_hat_blu_textures(decomp, ["hat"])

        assert raw == {}, "различий нет — карту не отдаём"
        assert fired, "но сообщаем, что команды выглядят одинаково"


def test_different_blu_texture_is_a_real_difference(app):
    with TemporaryDirectory() as tmp:
        files = _files(
            hat=("models/hat/red", (40, 0, 0, 255)),
            hat_blue=("models/hat/blue", (0, 0, 40, 255)),
        )
        w, decomp = _worker(files, QC_SIMPLE_TEAM, tmp)
        fired = []
        w.blu_same_as_red.connect(lambda: fired.append(1))

        w._extract_hat_textures_via_qc_vmt(decomp, ["hat"])
        raw = w._extract_hat_blu_textures(decomp, ["hat"])

        assert raw["hat"][0], "своя BLU-текстура"
        assert not fired


def test_single_blu_fallback_still_works(app):
    """Запасной путь (одна BLU-текстура на модель) не должен падать.

    Он сравнивает BLU с RED, и когда вид RED стал объектом ResolvedMaterial,
    сравнение молча роняло путь в except — BLU пропадал целиком.
    """
    with TemporaryDirectory() as tmp:
        files = _files(
            hat=("models/hat/red", (40, 0, 0, 255)),
            hat_blue=("models/hat/blue", (0, 0, 40, 255)),
        )
        w, decomp = _worker(files, QC_SIMPLE_TEAM, tmp)
        w._extract_hat_textures_via_qc_vmt(decomp, ["hat"])

        frames, fps = w._extract_blu_via_qc(decomp, 0.0)
        assert frames and Path(frames[0]).is_file()


def test_team_tint_from_vmt_makes_blu_different(app):
    """Одна текстура на обе команды, цвет — только в VMT: разница есть."""
    from PIL import Image

    with TemporaryDirectory() as tmp:
        files = {
            f"materials/{CD}/hat.vmt": vmt(
                basetexture="models/hat/color", blendtintbybasealpha="1",
                blendtintcoloroverbase="0.99", colortint_base="{ 189 59 59 }"),
            f"materials/{CD}/hat_blue.vmt": vmt(
                basetexture="models/hat/color", blendtintbybasealpha="1",
                blendtintcoloroverbase="0.99", colortint_base="{ 91 122 140 }"),
            "materials/models/hat/color.vtf": _png_bytes((8, 8, 8, 255)),
        }
        w, decomp = _worker(files, QC_SIMPLE_TEAM, tmp)
        fired = []
        w.blu_same_as_red.connect(lambda: fired.append(1))

        red = w._extract_hat_textures_via_qc_vmt(decomp, ["hat"])
        raw = w._extract_hat_blu_textures(decomp, ["hat"])

        assert not fired, "цвета команд разные — это настоящая разница"
        with Image.open(red["hat"]) as img:
            red_px = img.convert("RGB").getpixel((0, 0))
        with Image.open(raw["hat"][0]) as img:
            blu_px = img.convert("RGB").getpixel((0, 0))
        assert red_px[0] > blu_px[0], f"RED краснее: {red_px} vs {blu_px}"
        assert blu_px[2] > red_px[2], f"BLU синее: {blu_px} vs {red_px}"


def test_styles_are_not_a_team(app):
    """Второй скин — стиль (bloody), а не команда: BLU не собираем."""
    qc = QC_SIMPLE_TEAM.replace('"hat_blue"', '"hat_bloody"')
    with TemporaryDirectory() as tmp:
        files = _files(
            hat=("models/hat/red", (40, 0, 0, 255)),
            hat_bloody=("models/hat/bloody", (0, 40, 0, 255)),
        )
        w, decomp = _worker(files, qc, tmp)
        w._extract_hat_textures_via_qc_vmt(decomp, ["hat"])
        assert w._extract_hat_blu_textures(decomp, ["hat"]) == {}


def test_qc_is_parsed_once_per_run(app):
    """Разбор QC кэшируется: раньше один и тот же файл читался по 11 раз."""
    from src.services import qc_skin_parser

    calls = []
    orig = qc_skin_parser.parse_texturegroup_rows
    qc_skin_parser.parse_texturegroup_rows = lambda p: (calls.append(p) or orig(p))
    try:
        with TemporaryDirectory() as tmp:
            files = _files(hat=("models/hat/red", (40, 0, 0, 255)),
                           hat_blue=("models/hat/blue", (0, 0, 40, 255)))
            w, decomp = _worker(files, QC_SIMPLE_TEAM, tmp)
            for _ in range(3):
                w._extract_hat_textures_via_qc_vmt(decomp, ["hat"])
                w._extract_hat_blu_textures(decomp, ["hat"])
    finally:
        qc_skin_parser.parse_texturegroup_rows = orig
    assert len(calls) == 1, calls

def test_single_material_hat_also_emits_a_blu_frame(app):
    """Одноматериальная шапка: карточек нет, и панель ищет BLU кадром.

    Battle Balaclava «No Gloves» — ровно этот случай: покомпонентная карта
    есть, а поле синей команды в панели оставалось пустым.
    """
    with TemporaryDirectory() as tmp:
        files = _files(
            hat=("models/hat/red", (40, 0, 0, 255)),
            hat_blue=("models/hat/blue", (0, 0, 40, 255)),
        )
        w, decomp = _worker(files, QC_SIMPLE_TEAM, tmp)
        w._hat_decomp_dir = decomp
        frames = []
        maps = []
        w.blu_ready.connect(lambda f, fps: frames.append(list(f)))
        w.blu_multi_material.connect(lambda p: maps.append(p))
        w.ready.connect(lambda *_: None)

        w._emit_hat_textures("model.obj", ["hat"])

        assert maps, "покомпонентная карта тоже нужна (имена для карточек)"
        assert frames and Path(frames[0][0]).is_file(), "и кадр для панели"


def test_multi_material_hat_does_not_emit_a_single_frame(app):
    """У многоматериальной шапки одиночный кадр лёг бы на все меши сразу."""
    with TemporaryDirectory() as tmp:
        files = _files(
            auto_1=("models/hat/a1", (10, 0, 0, 255)),
            auto=("models/hat/a", (20, 0, 0, 255)),
            auto_1_blue=("models/hat/a1b", (0, 0, 10, 255)),
            auto_blue=("models/hat/ab", (0, 0, 20, 255)),
        )
        w, decomp = _worker(files, QC_FOUR_COLUMNS, tmp)
        w._hat_decomp_dir = decomp
        frames = []
        w.blu_ready.connect(lambda f, fps: frames.append(list(f)))
        w.ready.connect(lambda *_: None)

        w._emit_hat_textures("model.obj", ["auto_1", "auto"])

        assert not frames, "только покомпонентная карта"

def test_missing_blu_texture_is_treated_as_shared(app):
    """BLU-материал есть в QC, а его текстуры в игре нет.

    Показать нечего; пометить материал командным — значит оставить у синей
    команды пустое поле. Считаем его общим и оставляем RED-картинку.
    """
    with TemporaryDirectory() as tmp:
        files = _files(hat=("models/hat/red", (40, 0, 0, 255)))
        # VMT синего есть, а VTF, на который он ссылается, — нет
        files[f"materials/{CD}/hat_blue.vmt"] = vmt(basetexture="models/hat/nope")
        w, decomp = _worker(files, QC_SIMPLE_TEAM, tmp)
        w._extract_hat_textures_via_qc_vmt(decomp, ["hat"])

        raw = w._extract_hat_blu_textures(decomp, ["hat"])
        assert raw == {}, "различий показать не можем — карты нет"


def test_missing_blu_texture_among_several_materials(app):
    """Тот же случай, но материалов несколько: остальные не страдают."""
    with TemporaryDirectory() as tmp:
        files = _files(
            auto_1=("models/hat/a1", (10, 0, 0, 255)),
            auto=("models/hat/a", (20, 0, 0, 255)),
            auto_1_blue=("models/hat/a1b", (0, 0, 10, 255)),
        )
        # У второго материала синий VMT ссылается на несуществующий VTF
        files[f"materials/{CD}/auto_blue.vmt"] = vmt(basetexture="models/hat/nope")
        w, decomp = _worker(files, QC_FOUR_COLUMNS, tmp)
        mats = ["auto_1", "auto"]
        w._extract_hat_textures_via_qc_vmt(decomp, mats)
        raw = w._extract_hat_blu_textures(decomp, mats)

        assert raw["auto_1"][0], "у первого своя BLU-текстура"
        assert raw["auto"] == (None, "auto"), "второй — общий, а не пустой"

