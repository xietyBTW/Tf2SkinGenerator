"""
Разделение модели на части и вклейка картинки в её место на развёртке.

Модели тут игрушечные, но проверяются ровно те решения, из-за которых фича
может тихо соврать пользователю: что считать одной частью, какие части в игре
неизбежно покрасятся вместе и куда именно ложится картинка.
"""

import os
import tempfile
import unittest

from PIL import Image

from src.services import mesh_parts_service as parts
from src.services import texture_compose_service as compose


def _obj(path: str, faces: str) -> str:
    """OBJ из готового текста: тесту важна геометрия, а не заголовки."""
    with open(path, 'w', encoding='utf-8') as f:
        f.write(faces)
    return path


#: Два не связанных квадрата одного материала: слева и справа на развёртке.
TWO_SQUARES = """
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
v 5 0 0
v 6 0 0
v 6 1 0
v 5 1 0
vt 0.0 0.0
vt 0.4 0.0
vt 0.4 0.4
vt 0.0 0.4
vt 0.6 0.6
vt 1.0 0.6
vt 1.0 1.0
vt 0.6 1.0
usemtl weapon
f 1/1 2/2 3/3
f 1/1 3/3 4/4
f 5/5 6/6 7/7
f 5/5 7/7 8/8
"""

#: Два РАЗНЫХ куска, положенных на одно место развёртки: так делают, когда
#: деталь повторяется (у w_stickybomb так лежат 21 кусок на 5 островах).
SHARED_UV = """
v 0 0 0
v 1 0 0
v 1 1 0
v 9 0 0
v 10 0 0
v 10 1 0
vt 0.0 0.0
vt 1.0 0.0
vt 1.0 1.0
usemtl weapon
f 1/1 2/2 3/3
f 4/1 5/2 6/3
"""


class SplitTests(unittest.TestCase):
    """Что считается одной частью."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.tmp = self._dir.name

    def tearDown(self):
        self._dir.cleanup()

    def test_disconnected_pieces_are_separate_parts(self):
        model = parts.load(_obj(os.path.join(self.tmp, 'a.obj'), TWO_SQUARES))
        self.assertEqual(len(model.parts_of('weapon')), 2)

    def test_parts_are_sorted_from_the_largest(self):
        """Крупное — сверху: список частей читают глазами, а не по номеру."""
        model = parts.load(_obj(os.path.join(self.tmp, 'b.obj'), TWO_SQUARES))
        areas = [p.uv_area for p in model.parts_of('weapon')]
        self.assertEqual(areas, sorted(areas, reverse=True))

    def test_pieces_sharing_the_uv_are_marked(self):
        """В игре у них общий пиксель — покрасить по-разному нельзя, и об этом
        нужно сказать, а не молча покрасить обе."""
        model = parts.load(_obj(os.path.join(self.tmp, 'c.obj'), SHARED_UV))
        found = model.parts_of('weapon')
        self.assertEqual(len(found), 2)
        self.assertTrue(all(p.shared for p in found))

    def test_ordinary_parts_are_not_marked_as_shared(self):
        model = parts.load(_obj(os.path.join(self.tmp, 'd.obj'), TWO_SQUARES))
        self.assertTrue(all(not p.shared for p in model.parts_of('weapon')))

    def test_triangle_numbers_follow_the_obj(self):
        """По этим номерам вьювер подсвечивает часть: разойдутся — подсветится
        не то, на что навели."""
        model = parts.load(_obj(os.path.join(self.tmp, 'e.obj'), TWO_SQUARES))
        first, second = model.parts_of('weapon')
        self.assertEqual(sorted(first.triangles + second.triangles), [0, 1, 2, 3])

    def test_missing_file_is_not_a_crash(self):
        self.assertIsNone(parts.load(os.path.join(self.tmp, 'нет.obj')))


class ComposeTests(unittest.TestCase):
    """Куда ложится картинка части."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.tmp = self._dir.name
        self.base = os.path.join(self.tmp, 'base.png')
        Image.new('RGBA', (64, 64), (0, 0, 0, 255)).save(self.base)
        self.patch = os.path.join(self.tmp, 'patch.png')
        Image.new('RGBA', (8, 8), (255, 0, 0, 255)).save(self.patch)

    def tearDown(self):
        self._dir.cleanup()

    def _compose(self, polygons):
        out = os.path.join(self.tmp, 'out.png')
        return compose.compose(
            self.base, [compose.Layer(polygons=polygons, image=self.patch)], out)

    def test_patch_lands_on_the_part_and_nowhere_else(self):
        # Треугольник в левом НИЖНЕМ углу развёртки (v растёт вверх).
        result = self._compose([(((0.0, 0.0), (0.4, 0.0), (0.0, 0.4)))])
        image = Image.open(result).convert('RGB')
        self.assertEqual(image.getpixel((4, 60)), (255, 0, 0))   # внутри части
        self.assertEqual(image.getpixel((60, 4)), (0, 0, 0))     # чужое место

    def test_v_axis_is_not_mirrored(self):
        """Развёртка считает v снизу, картинка — строки сверху. Ошибка на этом
        месте переворачивает текстуру и замечается только в игре."""
        result = self._compose([(((0.0, 0.6), (0.4, 0.6), (0.0, 1.0)))])
        image = Image.open(result).convert('RGB')
        self.assertEqual(image.getpixel((4, 4)), (255, 0, 0))    # верх картинки
        self.assertEqual(image.getpixel((4, 60)), (0, 0, 0))

    def test_nothing_to_paste_leaves_no_file(self):
        out = os.path.join(self.tmp, 'empty.png')
        self.assertIsNone(compose.compose(self.base, [], out))
        self.assertFalse(os.path.exists(out))

    def test_missing_base_is_an_empty_answer_not_a_crash(self):
        out = os.path.join(self.tmp, 'none.png')
        self.assertIsNone(compose.compose(
            'нет.png', [compose.Layer(polygons=[], image=self.patch)], out))

    def _banded(self, name: str) -> str:
        """Текстура из тёмной и светлой полос — по ним видно, жива ли деталь."""
        image = Image.new('RGBA', (64, 64), (60, 60, 60, 255))
        image.paste(Image.new('RGBA', (64, 32), (190, 190, 190, 255)), (0, 32))
        path = os.path.join(self.tmp, name)
        image.save(path)
        return path

    def _tint(self, base: str, out: str, **kwargs) -> Image.Image:
        square = (((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)))
        square2 = (((0.0, 0.0), (1.0, 1.0), (0.0, 1.0)))
        res = compose.compose(base, [compose.Layer(polygons=[square, square2],
                                                   **kwargs)],
                              os.path.join(self.tmp, out))
        return Image.open(res).convert('RGB')

    def test_tint_paints_the_part_in_its_colour(self):
        image = self._tint(self._banded('band.png'), 'tint.png', color='#ff0000')
        red, green, blue = image.getpixel((32, 10))
        self.assertGreater(red, green + 60)
        self.assertGreater(red, blue + 60)

    def test_tint_keeps_the_detail_of_the_original(self):
        """Цвет должен ложиться краской, а не заливкой: тёмное остаётся тёмным.
        Умножение гасило тёмную текстуру в чёрное, раскраска по яркости — в
        мутное пятно; поэтому overlay."""
        image = self._tint(self._banded('band2.png'), 'tint2.png', color='#ff0000')
        dark = sum(image.getpixel((32, 10)))
        light = sum(image.getpixel((32, 50)))
        self.assertGreater(light, dark + 90)

    def test_weak_tint_only_shifts_the_colour(self):
        image = self._tint(self._banded('band3.png'), 'tint3.png',
                           color='#ff0000', strength=0.3)
        red, green, blue = image.getpixel((32, 50))
        self.assertGreater(green, 100)      # светлая полоса ещё светлая
        self.assertGreater(red, green)      # но уже краснее

    def test_gradient_runs_between_the_two_colours(self):
        """Одним цветом деталь выглядит плоской; в настоящих скинах переход
        есть почти всегда."""
        image = self._tint(self._banded('band4.png'), 'grad.png',
                           color='#ff0000', color2='#0000ff')
        top_red, _, top_blue = image.getpixel((32, 2))
        low_red, _, low_blue = image.getpixel((32, 61))
        self.assertGreater(top_red, top_blue)
        self.assertGreater(low_blue, low_red)

    def test_gradient_can_run_across(self):
        image = self._tint(self._banded('band5.png'), 'grad2.png',
                           color='#ff0000', color2='#0000ff', horizontal=True)
        left_red, _, left_blue = image.getpixel((2, 50))
        right_red, _, right_blue = image.getpixel((61, 50))
        self.assertGreater(left_red, left_blue)
        self.assertGreater(right_blue, right_red)

    def test_broken_colour_paints_nothing(self):
        """Мусорный цвет не должен превращаться в чёрную деталь."""
        out = os.path.join(self.tmp, 'bad.png')
        square = (((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)))
        self.assertIsNone(compose.compose(
            self.base, [compose.Layer(polygons=[square], color='синий')], out))


class SessionPartsTests(unittest.TestCase):
    """Что делает сеанс, когда картинку кладут на часть."""

    def setUp(self):
        from src.app.session import AppSession
        from src.shared.constants import Team

        self.Team = Team
        self._dir = tempfile.TemporaryDirectory()
        self.tmp = self._dir.name
        self.base = os.path.join(self.tmp, 'game.png')
        Image.new('RGBA', (64, 64), (0, 0, 0, 255)).save(self.base)
        self.patch = os.path.join(self.tmp, 'patch.png')
        Image.new('RGBA', (8, 8), (255, 0, 0, 255)).save(self.patch)

        self.session = AppSession()
        self.session._mode = 'scout_c_scattergun'
        self.session._obj_path = _obj(os.path.join(self.tmp, 'm.obj'), TWO_SQUARES)
        t = self.session.preview.textures
        t.material_names = ['weapon']
        t.vpk_red_tex_map = {'weapon': self.base}

    def tearDown(self):
        self._dir.cleanup()

    def _painted(self):
        return self.session.preview.textures.textures[self.Team.RED].get('weapon')

    def test_parts_are_listed_with_a_number_for_every_triangle(self):
        """Вьювер возвращает попадание номером треугольника — без этой карты
        клик не с чем связать."""
        res = self.session.parts()
        self.assertEqual(len(res['parts']), 2)
        self.assertEqual(len(res['tri_part']), 4)

    def test_painting_a_part_produces_the_material_texture(self):
        """Склейка ложится туда же, куда обычная своя текстура: дальше по
        конвейеру про части никто не знает."""
        self.session.set_part_texture('weapon', 0, self.patch)
        painted = self._painted()
        self.assertTrue(painted and os.path.isfile(painted))
        self.assertNotEqual(painted, self.base)

    def test_clearing_the_last_part_returns_the_game_texture(self):
        self.session.set_part_texture('weapon', 0, self.patch)
        self.session.set_part_texture('weapon', 0, None)
        self.assertIsNone(self._painted())
        self.assertEqual(self.session.preview.part_textures, {})

    def test_second_part_is_composed_over_the_game_texture_not_the_previous_glue(self):
        """Иначе правки копились бы слоями и часть нельзя было бы перекрасить."""
        self.session.set_part_texture('weapon', 0, self.patch)
        first = self._painted()
        green = os.path.join(self.tmp, 'green.png')
        Image.new('RGBA', (8, 8), (0, 255, 0, 255)).save(green)
        self.session.set_part_texture('weapon', 0, green)
        second = self._painted()
        self.assertNotEqual(first, second)
        colors = {c for _, c in Image.open(second).convert('RGB').getcolors(4096)}
        self.assertNotIn((255, 0, 0), colors)

    def test_colour_paints_the_part(self):
        self.session.set_part_colors('weapon', {'0': '#ff0000'})
        painted = self._painted()
        self.assertTrue(painted and os.path.isfile(painted))

    def test_colour_and_image_do_not_fight_over_one_part(self):
        """Два ответа на «чем красить» означали бы, что один молча проиграл."""
        self.session.set_part_texture('weapon', 0, self.patch)
        self.session.set_part_colors('weapon', {'0': '#00ff00'})
        self.assertEqual(self.session.preview.part_textures.get('weapon', {}), {})
        self.session.set_part_texture('weapon', 0, self.patch)
        self.assertEqual(self.session.preview.part_colors.get('weapon', {}), {})

    def test_clearing_everything_returns_the_game_texture(self):
        self.session.set_part_colors('weapon', {'0': '#ff0000', '1': '#00ff00'})
        self.session.clear_parts('weapon')
        self.assertIsNone(self._painted())
        self.assertEqual(self.session.preview.part_colors, {})

    def test_tint_strength_is_remembered(self):
        self.session.set_part_colors('weapon', {'0': '#ff0000'}, strength=0.4)
        self.assertAlmostEqual(self.session.preview.part_tint, 0.4)

    def test_undo_returns_the_previous_painting(self):
        """Красят на ощупь: без отмены каждый щелчок приходится обдумывать."""
        self.session.set_part_colors('weapon', {'0': '#ff0000'})
        self.session.set_part_colors('weapon', {'1': '#00ff00'})
        self.session.undo_parts('weapon')
        self.assertEqual(self.session.preview.part_colors['weapon'],
                         {0: '#ff0000'})

    def test_undo_walks_back_to_the_clean_texture(self):
        self.session.set_part_colors('weapon', {'0': '#ff0000'})
        self.session.undo_parts('weapon')
        self.assertIsNone(self._painted())

    def test_nothing_to_undo_is_said_plainly(self):
        self.assertIn('error', self.session.undo_parts('weapon'))

    def test_unknown_file_is_an_error(self):
        self.assertIn('error', self.session.set_part_texture('weapon', 0, 'нет.png'))

    def test_without_a_model_there_are_no_parts(self):
        from src.app.session import AppSession
        self.assertIn('error', AppSession().parts())


if __name__ == '__main__':
    unittest.main()
