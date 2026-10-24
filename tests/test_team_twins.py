"""Правило «синий выглядит как красный» по пикселям под развёрткой"""

from PIL import Image

from src.services.team_twins import largest_patch, same_on_mesh

#: Весь квадрат развёртки - два треугольника
FULL = [((0, 0), (1, 0), (0, 1)), ((1, 0), (1, 1), (0, 1))]
RED = (120, 0, 0, 255)


def _png(tmp_path, name, pixels=(), color=RED):
    """64x64 серая картинка, пиксели (x, y) из списка окрашены"""
    img = Image.new("RGBA", (64, 64), (128, 128, 128, 255))
    for xy in pixels:
        img.putpixel(xy, color)
    path = tmp_path / f"{name}.png"
    img.save(path)
    return str(path)


def _row(n, y=8):
    return [(x, y) for x in range(n)]


def test_scattered_dxt_noise_is_not_a_difference(tmp_path):
    """Разрозненные пиксели на стыках блоков DXT - не командная деталь"""
    noise = [(x, y) for x in range(0, 64, 8) for y in range(0, 64, 16)]
    assert same_on_mesh(_png(tmp_path, "red"), _png(tmp_path, "blu", noise), FULL)


def test_patch_bigger_than_a_dxt_block_is_a_difference(tmp_path):
    """Нашивка 5x5 - уже деталь команды"""
    patch = [(x, y) for x in range(30, 35) for y in range(30, 35)]
    assert not same_on_mesh(_png(tmp_path, "red"), _png(tmp_path, "blu", patch), FULL)


def test_small_diff_within_dxt_step_is_ignored(tmp_path):
    red = _png(tmp_path, "red")
    blu = _png(tmp_path, "blu", _row(64), color=(134, 128, 128, 255))
    assert same_on_mesh(red, blu, FULL)


def test_wrapped_uv_is_read_from_the_repeated_texture(tmp_path):
    """Развёртка за пределами [0,1]: текстура повторяется

    Окрашена восьмая строка синей картинки, а модель смотрит в нижнюю
    половину - через повтор, v от -0.9 до -0.6
    """
    bottom = [((0, -0.9), (1, -0.9), (0, -0.6)), ((1, -0.9), (1, -0.6), (0, -0.6))]
    assert same_on_mesh(_png(tmp_path, "red"), _png(tmp_path, "blu", _row(64)), bottom)
    top = [((0, -0.3), (1, -0.3), (0, 0)), ((1, -0.3), (1, 0), (0, 0))]
    assert not same_on_mesh(_png(tmp_path, "red"), _png(tmp_path, "blu", _row(64)), top)


def test_largest_patch_counts_diagonal_neighbours():
    assert largest_patch([(0, 0), (1, 1), (2, 2), (9, 9)]) == 3
    assert largest_patch([]) == 0
