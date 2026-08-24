"""Командная окраска материала ($blendtintbybasealpha).

Разбор VMT и сама формула шейдера: на этом держится и правильный цвет шапки
в превью, и ответ на вопрос «отличаются ли команды вообще».
"""

import pytest

from src.services import vmt_tint

CRLF = "\r\n"


def _vmt(**params) -> str:
    """VMT в формате Valve: табы, кавычки и CRLF-концы строк."""
    lines = ['"VertexLitGeneric"', "{"]
    for key, value in params.items():
        lines.append(f'\t"${key}"\t\t"{value}"')
    lines.append("}")
    return CRLF.join(lines)


def test_parse_color_braces_and_brackets():
    assert vmt_tint.parse_color("{ 189 59 59 }") == (189, 59, 59)
    assert vmt_tint.parse_color("{194 45 48}") == (194, 45, 48)
    # Квадратные скобки — доли единицы, а не 0-255
    assert vmt_tint.parse_color("[1 1 1]") == (255, 255, 255)
    assert vmt_tint.parse_color("[.5 .25 0]") == (128, 64, 0)
    assert vmt_tint.parse_color("не цвет") is None
    assert vmt_tint.parse_color("") is None


def test_parse_tint_reads_team_color():
    """Тот самый случай Big Elfin Deal: цвет команды живёт только в VMT."""
    spec = vmt_tint.parse_tint(_vmt(
        basetexture="models/foo/bar_color",
        blendtintbybasealpha="1",
        blendtintcoloroverbase="0.990000",
        colortint_base="{ 189 59 59 }",
        color2="{ 189 59 59 }",
    ))
    assert spec is not None
    assert spec.color == (189, 59, 59)
    assert spec.over_base == pytest.approx(0.99)
    assert not spec.is_neutral


def test_parse_tint_without_blend_flag_is_none():
    """Без $blendtintbybasealpha альфа — это прозрачность, а не маска краски."""
    assert vmt_tint.parse_tint(_vmt(basetexture="x", color2="{ 200 50 50 }")) is None
    assert vmt_tint.parse_tint(_vmt(basetexture="x", blendtintbybasealpha="0",
                                    color2="{ 200 50 50 }")) is None
    assert vmt_tint.parse_tint("") is None


def test_parse_tint_skips_translucent_materials():
    """Прозрачный материал трогать нельзя: заливка альфы сделает его глухим."""
    for flag in ("translucent", "alphatest"):
        text = _vmt(**{"basetexture": "x", "blendtintbybasealpha": "1",
                       "colortint_base": "{ 189 59 59 }", flag: "1"})
        assert vmt_tint.parse_tint(text) is None, flag


def test_parse_tint_defaults_to_white_without_color():
    spec = vmt_tint.parse_tint(_vmt(basetexture="x", blendtintbybasealpha="1"))
    assert spec is not None and spec.color == (255, 255, 255)
    assert spec.is_neutral


def test_same_look():
    red = vmt_tint.TintSpec((189, 59, 59), 0.99)
    blu = vmt_tint.TintSpec((91, 122, 140), 0.99)
    assert not vmt_tint.same_look(red, blu)
    assert vmt_tint.same_look(red, vmt_tint.TintSpec((189, 59, 59), 0.99))
    assert vmt_tint.same_look(None, None)
    assert not vmt_tint.same_look(red, None)
    # Нейтральные краски одинаковы, даже если записаны по-разному
    assert vmt_tint.same_look(vmt_tint.TintSpec((255, 255, 255), 0.0),
                              vmt_tint.TintSpec((255, 255, 255), 0.0))


def _sample(tmp_path, rgb, alpha):
    Image = pytest.importorskip("PIL.Image")
    img = Image.new("RGBA", (2, 2), rgb + (alpha,))
    path = tmp_path / "tex.png"
    img.save(path)
    return str(path)


def test_apply_to_png_paints_masked_area(tmp_path):
    """Почти чёрный пиксель под маской становится цветом команды — ровно то,
    что в игре делает шейдер (в стоке 99% таких пикселей темнее 40)."""
    Image = pytest.importorskip("PIL.Image")
    path = _sample(tmp_path, (8, 8, 8), 255)
    assert vmt_tint.apply_to_png(path, vmt_tint.TintSpec((189, 59, 59), 0.99))
    with Image.open(path) as img:
        px = img.convert("RGBA").getpixel((0, 0))
    assert abs(px[0] - 189) < 6 and abs(px[1] - 59) < 6 and abs(px[2] - 59) < 6
    assert px[3] == 255, "альфа была маской краски, а не прозрачностью"


def test_apply_to_png_leaves_unmasked_area(tmp_path):
    """Там, где маски нет, цвет остаётся авторским."""
    Image = pytest.importorskip("PIL.Image")
    path = _sample(tmp_path, (20, 140, 60), 0)
    assert vmt_tint.apply_to_png(path, vmt_tint.TintSpec((189, 59, 59), 0.99))
    with Image.open(path) as img:
        px = img.convert("RGBA").getpixel((0, 0))
    assert px[:3] == (20, 140, 60)
    assert px[3] == 255


def test_apply_to_png_multiplies_without_over_base(tmp_path):
    """$blendtintcoloroverbase = 0 — краска умножается на базовый цвет."""
    Image = pytest.importorskip("PIL.Image")
    path = _sample(tmp_path, (255, 255, 255), 255)
    vmt_tint.apply_to_png(path, vmt_tint.TintSpec((100, 50, 25), 0.0))
    with Image.open(path) as img:
        px = img.convert("RGBA").getpixel((0, 0))
    assert px[:3] == (100, 50, 25)


def test_apply_to_png_noop_without_spec(tmp_path):
    assert not vmt_tint.apply_to_png(_sample(tmp_path, (1, 2, 3), 200), None)
    assert not vmt_tint.apply_to_png("", vmt_tint.TintSpec((1, 2, 3)))


def test_apply_to_png_neutral_still_flattens_alpha(tmp_path):
    """Белая краска цвет не меняет, но маску из альфы всё равно надо убрать —
    иначе шапка в превью выглядит дырявой."""
    Image = pytest.importorskip("PIL.Image")
    path = _sample(tmp_path, (30, 40, 50), 0)
    assert vmt_tint.apply_to_png(path, vmt_tint.TintSpec((255, 255, 255), 0.0))
    with Image.open(path) as img:
        px = img.convert("RGBA").getpixel((0, 0))
    assert px == (30, 40, 50, 255)


def test_same_material_look_compares_texture_and_paint():
    """Ответ на «отличаются ли команды»: сравниваем текстуру И краску.

    Big Elfin Deal — та же текстура, но разная краска: разница есть.
    46 стоковых шапок — совпадает и то, и другое: разницы нет.
    """
    red_tint = vmt_tint.TintSpec((189, 59, 59), 0.99)
    blu_tint = vmt_tint.TintSpec((91, 122, 140), 0.99)
    tex = "models/workshop/player/items/scout/elf/elf_color"

    assert not vmt_tint.same_material_look((tex, red_tint), (tex, blu_tint))
    assert vmt_tint.same_material_look((tex, red_tint), (tex, red_tint))
    # Разные текстуры — разница есть даже при одинаковой краске
    assert not vmt_tint.same_material_look((tex, red_tint), (tex + "_blue", red_tint))
    # Материалы без краски вообще: решает только текстура
    assert vmt_tint.same_material_look((tex, None), (tex, None))
    assert not vmt_tint.same_material_look(None, (tex, None))
    assert not vmt_tint.same_material_look((tex, None), None)
