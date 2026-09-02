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


#: Один связный кусок, но развёртка разрезана надвое: так у руки шпиона
#: устроены пальцы — геометрия сплошная, а острова UV отдельные.
SEAM_INSIDE_ONE_PIECE = """
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
v 2 0 0
v 2 1 0
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
f 2/5 5/6 6/7
f 2/5 6/7 3/8
"""


#: Кусок со швом развёртки И отдельный кусок без шва: на нём проверяется, что
#: дробление одного куска не трогает соседний.
SEAMED_PIECE_AND_PLAIN_ONE = """
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
v 2 0 0
v 2 1 0
v 9 0 0
v 10 0 0
v 10 1 0
vt 0.0 0.0
vt 0.3 0.0
vt 0.3 0.3
vt 0.0 0.3
vt 0.5 0.5
vt 0.8 0.5
vt 0.8 0.8
vt 0.5 0.8
vt 0.9 0.0
vt 1.0 0.0
vt 1.0 0.1
usemtl weapon
f 1/1 2/2 3/3
f 1/1 3/3 4/4
f 2/5 5/6 6/7
f 2/5 6/7 3/8
f 7/9 8/10 9/11
"""


#: Два ОТДЕЛЬНЫХ куска, лежащих на одной развёртке из двух островов — так
#: устроены левая и правая руки шпиона. В игре у них общие пиксели.
MIRRORED_PIECES = """
v 0 0 0
v 1 0 0
v 1 1 0
v 2 0 0
v 9 0 0
v 10 0 0
v 10 1 0
v 11 0 0
vt 0.0 0.0
vt 0.4 0.0
vt 0.4 0.4
vt 0.6 0.6
vt 1.0 0.6
vt 1.0 1.0
usemtl weapon
f 1/1 2/2 3/3
f 2/4 3/5 4/6
f 5/1 6/2 7/3
f 6/4 7/5 8/6
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

    def test_by_default_a_seam_inside_one_piece_is_not_a_border(self):
        """Список читают глазами: у револьвера 29 кусков против 106 островов,
        и по умолчанию часть — это кусок, который человек видит."""
        model = parts.load(_obj(os.path.join(self.tmp, 'f.obj'),
                                SEAM_INSIDE_ONE_PIECE))
        self.assertEqual(len(model.parts_of('weapon')), 1)

    def test_cutting_a_piece_follows_the_uv_seam(self):
        """Развёртка разрешает покрасить палец отдельно — значит, отрезанный
        остров обязан стать отдельной частью."""
        model = parts.load(_obj(os.path.join(self.tmp, 'g.obj'),
                                SEAM_INSIDE_ONE_PIECE), {0: [[0]]})
        found = model.parts_of('weapon')
        self.assertEqual(len(found), 2)
        # Разрез — измельчение прежнего: треугольники те же, просто в двух
        # частях вместо одной.
        self.assertEqual(sorted(t for p in found for t in p.triangles),
                         [0, 1, 2, 3])

    def test_cutting_never_breaks_a_piece_apart_across_the_model(self):
        """Куски, лежащие на ОДНОМ месте развёртки, дробление не сливает:
        часть обязана оставаться куском модели, иначе подсветка в 3D покажет
        два места вместо одного."""
        model = parts.load(_obj(os.path.join(self.tmp, 'h.obj'), SHARED_UV),
                           {0: [[0]]})
        self.assertEqual(len(model.parts_of('weapon')), 2)

    def test_each_piece_is_cut_on_its_own(self):
        """Ради этого всё и затевалось: руку разбираем до пальцев, а рукав
        рядом оставляем целым."""
        path = _obj(os.path.join(self.tmp, 'i.obj'), SEAMED_PIECE_AND_PLAIN_ONE)
        whole = parts.load(path)
        self.assertEqual(len(whole.parts_of('weapon')), 2)

        # Режем ТОЛЬКО ту группу, где есть шов; второй кусок остаётся целым.
        seamed = next(g for g, n in whole.group_islands['weapon'].items() if n > 1)
        model = parts.load(path, {seamed: [[0]]})
        found = model.parts_of('weapon')
        self.assertEqual(len(found), 3)
        self.assertEqual(sum(1 for p in found if p.group == seamed), 2)
        self.assertEqual(sum(1 for p in found if p.group != seamed), 1)

    def test_mirrored_pieces_are_cut_together(self):
        """Куски, делящие развёртку, — одна группа: в игре у них общие пиксели,
        и разрезать один без другого нельзя даже теоретически. Именно на этом
        ловилась прошлая версия: пальцы резались на левой руке, а на правой
        оставались целыми."""
        path = _obj(os.path.join(self.tmp, 'p.obj'), MIRRORED_PIECES)
        whole = parts.load(path)
        self.assertEqual(len(whole.parts_of('weapon')), 2)
        # Оба куска — одна группа с двумя островами.
        self.assertEqual(len({p.group for p in whole.parts_of('weapon')}), 1)
        self.assertEqual(list(whole.group_islands['weapon'].values()), [2])

        found = parts.load(path, {0: [[0]]}).parts_of('weapon')
        # Отрезали ОДИН остров — отделился он у ОБОИХ кусков.
        self.assertEqual(len(found), 4)
        self.assertEqual(len({p.chunk for p in found if p.islands == (0,)}), 2)

    def test_a_group_without_seams_has_nothing_to_cut(self):
        """У куска с одним островом резать нечего — служба обязана сказать это
        числом островов, а не промолчать."""
        model = parts.load(_obj(os.path.join(self.tmp, 'j.obj'), TWO_SQUARES))
        self.assertEqual(sorted(model.group_islands['weapon'].values()), [1, 1])

    def test_cutting_only_grows_the_list(self):
        """Больше отрезанных островов — не меньше частей."""
        path = _obj(os.path.join(self.tmp, 'k.obj'), SEAM_INSIDE_ONE_PIECE)
        counts = [len(parts.load(path, cut).parts_of('weapon'))
                  for cut in ({}, {0: [[0]]}, {0: [[0], [1]]})]
        self.assertEqual(counts, sorted(counts))

    def test_an_island_number_survives_other_cuts(self):
        """Номер острова — ключ настройки: съедет он после соседнего разреза, и
        «прирастить обратно» вернёт не то, что отрезали."""
        path = _obj(os.path.join(self.tmp, 'q.obj'), SEAM_INSIDE_ONE_PIECE)
        alone = {p.islands: p.uv_area
                 for p in parts.load(path, {0: [[1]]}).parts_of('weapon')
                 if p.islands}
        both = {p.islands: p.uv_area
                for p in parts.load(path, {0: [[0], [1]]}).parts_of('weapon')
                if p.islands}
        self.assertAlmostEqual(alone[(1,)], both[(1,)])

    def test_islands_of_one_bundle_become_one_part(self):
        """Развёртка режет вещи не так, как их видит человек: палец у неё
        нередко разложен на верх и низ. Сведённые в набор острова обязаны стать
        ОДНОЙ частью, иначе красить палец придётся дважды."""
        path = _obj(os.path.join(self.tmp, 'r.obj'), SEAM_INSIDE_ONE_PIECE)
        apart = parts.load(path, {0: [[0], [1]]}).parts_of('weapon')
        together = parts.load(path, {0: [[0, 1]]}).parts_of('weapon')
        self.assertEqual(len(apart), 2)
        self.assertEqual(len(together), 1)
        self.assertEqual(together[0].islands, (0, 1))
        # Геометрия та же — сменилось только то, что считается одной частью.
        self.assertEqual(sorted(t for p in together for t in p.triangles),
                         sorted(t for p in apart for t in p.triangles))

    def test_a_bundle_keeps_mirrored_pieces_apart(self):
        """Слияние островов — про развёртку, а не про модель: у зеркальных
        кусков набор отделяется на каждом СВОЕЙ частью, иначе левая рука
        склеилась бы с правой в один пункт списка."""
        path = _obj(os.path.join(self.tmp, 's.obj'), MIRRORED_PIECES)
        found = parts.load(path, {0: [[0, 1]]}).parts_of('weapon')
        self.assertEqual(len(found), 2)
        self.assertEqual({p.islands for p in found}, {(0, 1)})
        self.assertEqual(len({p.chunk for p in found}), 2)

    def test_an_island_belongs_to_one_bundle_only(self):
        """Остров в двух наборах означал бы часть с двумя ответами на вопрос
        «чем красить»; побеждает первый набор."""
        self.assertEqual(parts.bundles_of({0: [[0, 1], [1, 2]]}),
                         {0: [(0, 1), (2,)]})

    def test_bundle_order_does_not_change_the_result(self):
        """Канон нужен и ключу кэша: одно и то же, записанное иначе, обязано
        давать то же разбиение."""
        self.assertEqual(parts.bundles_of({0: [[2, 0]]}),
                         parts.bundles_of({0: [[0, 2]]}))

    def test_a_whole_piece_has_no_sub_number(self):
        """Подпись целого куска — просто его номер: «04·1» без «04·2» врало бы
        о том, что кусок разрезан."""
        model = parts.load(_obj(os.path.join(self.tmp, 'm.obj'), TWO_SQUARES))
        self.assertTrue(all(p.sub == 0 for p in model.parts_of('weapon')))

    def test_a_cut_piece_numbers_its_own_pieces(self):
        model = parts.load(_obj(os.path.join(self.tmp, 'n.obj'),
                                SEAM_INSIDE_ONE_PIECE), {0: [[0]]})
        found = model.parts_of('weapon')
        self.assertEqual(sorted(p.sub for p in found), [1, 2])

    def test_a_cut_inserts_in_place_instead_of_reshuffling(self):
        """Разрез не должен перетасовывать соседей: человек теряет из виду ту
        часть, с которой работал, если номера съезжают от каждого шага."""
        path = _obj(os.path.join(self.tmp, 'o.obj'), SEAMED_PIECE_AND_PLAIN_ONE)
        before = [p.chunk for p in parts.load(path).parts_of('weapon')]
        after = [p.chunk for p in parts.load(path, {0: [[0]]}).parts_of('weapon')]
        # Порядок кусков в списке тот же, у разрезанного просто стало две части.
        self.assertEqual(before, sorted(set(after), key=after.index))
        self.assertEqual(after, sorted(after, key=lambda c: before.index(c)))

    def test_piece_numbers_do_not_move_when_another_piece_is_cut(self):
        """Номер куска — ключ его настройки. Съедет он при разрезе соседа —
        и дробление молча переедет на чужой кусок."""
        path = _obj(os.path.join(self.tmp, 'l.obj'), SEAMED_PIECE_AND_PLAIN_ONE)
        before = {p.chunk for p in parts.load(path).parts_of('weapon')}
        after = {p.chunk for p in parts.load(path, {0: [[0]]}).parts_of('weapon')}
        self.assertEqual(before, after)


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
                           color='#ff0000', color2='#0000ff', angle=90)
        left_red, _, left_blue = image.getpixel((2, 50))
        right_red, _, right_blue = image.getpixel((61, 50))
        self.assertGreater(left_red, left_blue)
        self.assertGreater(right_blue, right_red)

    def test_gradient_runs_along_any_angle(self):
        """Направление задаёт человек, а не выбор из двух вариантов.

        Диагональ проверяем по УГЛАМ: на оси 45° первый цвет уходит в
        верхний левый, второй — в нижний правый, а перпендикулярные углы
        остаются серединой перехода. Ошибка нормировки (по стороне вместо
        размаха проекции) видна именно здесь: крайние цвета не доезжают.
        """
        image = self._tint(self._banded('band6.png'), 'grad3.png',
                           color='#ff0000', color2='#0000ff', angle=45)
        top_left = image.getpixel((2, 2))
        low_right = image.getpixel((61, 61))
        self.assertGreater(top_left[0], top_left[2])
        self.assertGreater(low_right[2], low_right[0])

    def test_old_works_read_the_two_way_flag(self):
        """Работы, записанные до угла, хранят флаг horizontal — их не ломаем."""
        from src.app.session import _paint_spec

        self.assertEqual(_paint_spec({'color': '#ff0000', 'horizontal': True})['angle'], 90.0)
        self.assertEqual(_paint_spec({'color': '#ff0000', 'horizontal': False})['angle'], 0.0)
        self.assertEqual(_paint_spec({'color': '#ff0000', 'angle': 137})['angle'], 137.0)
        self.assertNotIn('angle', _paint_spec('#ff0000'))

    def test_a_picture_keeps_its_proportions_by_default(self):
        """Растяжение по прямоугольнику корёжило логотипы, и заметно это
        становилось только в игре. Умолчание — вписать целиком."""
        from PIL import Image as PilImage

        wide = PilImage.new('RGBA', (100, 50), (255, 0, 0, 255))
        placed, at = compose.place_image(wide, (0, 0, 64, 64))
        self.assertEqual(placed.size, (64, 32))
        self.assertEqual(at, (0, 16))            # по центру места части

    def test_cover_fills_the_place_and_stretch_ignores_shape(self):
        from PIL import Image as PilImage

        wide = PilImage.new('RGBA', (100, 50), (255, 0, 0, 255))
        self.assertEqual(compose.place_image(wide, (0, 0, 64, 64), 'cover')[0].size,
                         (128, 64))
        self.assertEqual(compose.place_image(wide, (0, 0, 64, 64), 'stretch')[0].size,
                         (64, 64))

    def test_rotation_turns_the_picture_clockwise(self):
        """Остров развёртки нередко лежит боком, и без поворота надпись на
        детали читается вбок. По часовой — как у ручки направления градиента,
        чтобы два поворота в одном окне не спорили."""
        from PIL import Image as PilImage

        tall = PilImage.new('RGBA', (20, 80), (0, 0, 255, 255))
        tall.putpixel((0, 0), (255, 0, 0, 255))       # метка левого верха
        placed, _ = compose.place_image(tall, (0, 0, 64, 64), 'contain', angle=90)
        self.assertEqual(placed.size, (64, 16))
        # По часовой левый верх уезжает вправо вверх. Сравниваем углы, а не
        # точный цвет: масштабирование смешивает метку с фоном.
        right = placed.getpixel((placed.width - 1, 0))[0]
        left = placed.getpixel((0, 0))[0]
        self.assertGreater(right, left)

    def test_scale_and_offset_move_the_picture(self):
        from PIL import Image as PilImage

        square = PilImage.new('RGBA', (64, 64), (255, 0, 0, 255))
        big, _ = compose.place_image(square, (0, 0, 64, 64), scale=2.0)
        self.assertEqual(big.size, (128, 128))
        _, at = compose.place_image(square, (0, 0, 64, 64), offset=(0.5, 0.0))
        self.assertEqual(at, (32, 0))            # полширины места части

    def test_a_vanishing_scale_is_refused(self):
        """Ноль и минус — это исчезнувшая картинка; такой «результат» примут за
        поломку, а не за свою настройку."""
        from src.app.session import _image_spec

        self.assertGreater(_image_spec({'path': 'a.png', 'scale': 0})['scale'], 0)
        self.assertGreater(_image_spec({'path': 'a.png', 'scale': -3})['scale'], 0)

    def test_old_works_store_the_picture_as_a_plain_path(self):
        """Работы, записанные до настройки посадки, хранят строку — их не ломаем."""
        from src.app.session import _image_spec

        spec = _image_spec('C:/tmp/logo.png')
        self.assertEqual(spec['path'], 'C:/tmp/logo.png')
        self.assertEqual(spec['fit'], 'contain')
        self.assertEqual(spec['angle'], 0.0)

    def test_an_animated_picture_makes_the_composite_animated(self):
        """Гифка на части обязана дойти до игры: сборка узнаёт анимацию по
        самому файлу склейки (TextureService.is_animated_image)."""
        from PIL import Image as PilImage

        gif = os.path.join(self.tmp, 'anim.gif')
        shots = [PilImage.new('RGBA', (32, 32), c) for c in
                 ((255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255))]
        shots[0].save(gif, save_all=True, append_images=shots[1:],
                      duration=120, loop=0)

        square = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0))
        square2 = ((0.0, 0.0), (1.0, 1.0), (0.0, 1.0))
        out = os.path.join(self.tmp, 'moving.png')
        res = compose.compose(self._banded('for_gif.png'),
                              [compose.Layer(polygons=[square, square2], image=gif)],
                              out)
        with PilImage.open(res) as im:
            self.assertEqual(im.n_frames, 3)
            seen = []
            for k in range(3):
                im.seek(k)
                seen.append(im.convert('RGB').getpixel((32, 32)))
        self.assertEqual(len(set(seen)), 3)   # кадры и правда разные

    def test_a_plain_picture_stays_one_frame(self):
        """Обычная картинка не должна ни с того ни с сего стать анимацией: в
        моде это лишние килобайты и прокси AnimatedTexture в VMT."""
        from PIL import Image as PilImage

        png = os.path.join(self.tmp, 'plain.png')
        PilImage.new('RGBA', (32, 32), (200, 200, 0, 255)).save(png)
        square = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0))
        res = compose.compose(self._banded('for_png.png'),
                              [compose.Layer(polygons=[square], image=png)],
                              os.path.join(self.tmp, 'still.png'))
        with PilImage.open(res) as im:
            self.assertEqual(getattr(im, 'n_frames', 1), 1)

    def test_dense_bbox_ignores_far_flung_scraps(self):
        """Обычный габарит для приближения не годится: у половины частей острова
        разбросаны по развёртке, и прямоугольник вокруг них — почти вся
        текстура. У обреза это давало окну масштаб x0.87, то есть оно не
        приближало, а отдаляло."""
        # Основная масса в углу плюс один крошечный островок на другом краю.
        body = [((0.10, 0.10), (0.30, 0.10), (0.30, 0.30)),
                ((0.10, 0.10), (0.30, 0.30), (0.10, 0.30))]
        speck = [((0.97, 0.97), (0.98, 0.97), (0.98, 0.98))]

        plain = compose.dense_bbox(body + speck, cut=0.0)
        dense = compose.dense_bbox(body + speck)
        # Без отбрасывания габарит тянется до крошки, с отбрасыванием — нет.
        self.assertGreater(plain[2], 0.9)
        self.assertLess(dense[2], 0.9)
        # И основная масса из кадра не выпадает.
        self.assertLessEqual(dense[0], 0.11)
        self.assertGreaterEqual(dense[3], 0.29)

    def test_dense_bbox_weighs_area_not_points(self):
        """Площадь, а не число точек: иначе россыпь мелких треугольников
        перевесила бы одну крупную деталь и кадр уехал бы к ним."""
        big = [((0.10, 0.10), (0.60, 0.10), (0.60, 0.60))]
        crumbs = [((0.90 + i * 0.001, 0.90), (0.901 + i * 0.001, 0.90),
                   (0.901 + i * 0.001, 0.901)) for i in range(40)]
        dense = compose.dense_bbox(big + crumbs)
        self.assertLess(dense[2], 0.9)

    def test_dense_bbox_survives_an_empty_part(self):
        self.assertEqual(compose.dense_bbox([]), (0.0, 0.0, 1.0, 1.0))

    def test_frame_count_is_capped_by_memory(self):
        """Все кадры APNG живут в памяти одновременно: 64 кадра 2048x2048 — это
        гигабайт, и приложение легло бы на ровном месте."""
        self.assertLess(compose._frame_budget((2048, 2048), 64), 64)
        self.assertEqual(compose._frame_budget((512, 512), 64), 64)
        self.assertGreaterEqual(compose._frame_budget((4096, 4096), 64), 1)

    def test_the_shape_fingerprint_tells_bundles_apart(self):
        """Отпечаток решает, слать ли карты треугольников. Спутает два разных
        разбиения — вьювер останется со старой картой, и в 3D нельзя будет
        выбрать появившиеся части."""
        from src.app.session import AppSession

        app = AppSession.__new__(AppSession)
        app._obj_path = ''
        app.preview = type('P', (), {})()

        app.preview.part_cuts = {0: [[1], [2]]}
        apart = AppSession._shape_key(app, 'weapon')
        app.preview.part_cuts = {0: [[1, 2]]}
        together = AppSession._shape_key(app, 'weapon')
        self.assertNotEqual(apart, together)

        # Порядок записи на отпечаток влиять не должен.
        app.preview.part_cuts = {0: [[2, 1]]}
        self.assertEqual(together, AppSession._shape_key(app, 'weapon'))

    def test_the_edge_of_a_part_is_painted_too(self):
        """По краю части в игре оставалась полоска исходного цвета: остров
        растеризуется по центрам пикселей, а движок потом фильтрует текстуру и
        строит мипмапы. Одного пикселя запаса на это не хватало."""
        from PIL import Image as PilImage

        base = os.path.join(self.tmp, 'grey.png')
        PilImage.new('RGBA', (512, 512), (128, 128, 128, 255)).save(base)
        sq = [((0.25, 0.25), (0.75, 0.25), (0.75, 0.75)),
              ((0.25, 0.25), (0.75, 0.75), (0.25, 0.75))]
        out = compose.compose(base, [compose.Layer(polygons=sq, color='#ff0000')],
                              os.path.join(self.tmp, 'edge_paint.png'))
        im = PilImage.open(out).convert('RGB')
        painted = lambda x, y: im.getpixel((x, y))[0] > im.getpixel((x, y))[1] + 30
        # Идеальная граница на 128; краска обязана выходить ЗА неё.
        self.assertTrue(painted(126, 256), 'край части не докрашен')
        self.assertTrue(painted(256, 126), 'край части не докрашен')

    def test_the_bleed_grows_with_the_texture(self):
        """Запас в долях стороны, а не в пикселях: на 2048 одного пикселя не
        видно вовсе, на 256 восемь пикселей съели бы мелкие детали."""
        self.assertLess(compose._bleed_for((256, 256)),
                        compose._bleed_for((2048, 2048)))
        self.assertGreaterEqual(compose._bleed_for((256, 256)), 1)

    def test_the_highlight_shows_the_real_shape(self):
        """Подсветку расширять нельзя: она показывает, ГДЕ деталь кончается."""
        sq = [((0.25, 0.25), (0.75, 0.25), (0.75, 0.75))]
        wide = compose._mask(sq, (256, 256))
        exact = compose._mask(sq, (256, 256), bleed=0)
        self.assertGreater(wide.getbbox()[2], exact.getbbox()[2])

    def test_edging_lands_inside_the_part(self):
        """Наружу окантовка вылезла бы на соседнюю деталь и покрасила чужое."""
        from PIL import Image as PilImage

        base = os.path.join(self.tmp, 'grey2.png')
        PilImage.new('RGBA', (256, 256), (128, 128, 128, 255)).save(base)
        sq = [((0.25, 0.25), (0.75, 0.25), (0.75, 0.75)),
              ((0.25, 0.25), (0.75, 0.75), (0.25, 0.75))]
        out = compose.compose(
            base,
            [compose.Layer(polygons=sq, color='#3060ff', edge=0.02,
                           edge_color='#ffee00')],
            os.path.join(self.tmp, 'edged.png'))
        im = PilImage.open(out).convert('RGB')
        self.assertEqual(im.getpixel((66, 128)), (255, 238, 0))   # кайма
        self.assertEqual(im.getpixel((128, 128)), (48, 96, 255))  # середина
        self.assertEqual(im.getpixel((20, 128)), (128, 128, 128))  # чужое цело

    def test_no_edging_by_default(self):
        """Окантовка — намеренное решение, а не то, что случается само."""
        band = compose.edge_band(compose._mask(
            [((0.2, 0.2), (0.8, 0.2), (0.8, 0.8))], (128, 128)), 0)
        self.assertIsNone(band.getbbox())

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

    def test_old_composites_do_not_pile_up_on_disk(self):
        """Каждый мазок кистью писал новый файл и не удалял ни одного: за день
        работы во временной папке накопилось 1090 склеек на 248 МБ."""
        square = [0, 1]
        for step in range(10):
            self.session.set_part_colors('', {square[0]: '#%02x0000' % (step * 20)})
        alive = [p for p in self.session._compose_files if os.path.isfile(p)]
        self.assertLessEqual(len(self.session._compose_files),
                             self.session._KEEP_COMPOSITES)
        self.assertEqual(len(alive), len(self.session._compose_files))

    def test_the_shown_composite_is_never_deleted(self):
        """Путь склейки — это ещё и адрес картинки во вьювере: удалить только
        что показанную нельзя."""
        for step in range(6):
            self.session.set_part_colors('', {0: '#%02x0000' % (step * 30)})
        shown = self.session.preview.textures.uploaded_for_mat(
            self.session.preview.textures.storage_main_key())
        self.assertTrue(os.path.isfile(shown), shown)

    def test_a_forgotten_composite_is_still_known_as_ours(self):
        """Забыть ПУТЬ нельзя, даже удалив файл: по нему `_recompose` отличает
        свою склейку от пользовательской текстуры, иначе правки копились бы
        слоями."""
        for step in range(8):
            self.session.set_part_colors('', {0: '#%02x0000' % (step * 30)})
        self.assertGreater(len(self.session._composites),
                           self.session._KEEP_COMPOSITES)

    def _leave_and_return(self):
        """Возврат к предмету: путь склейки ведёт в work/, а множество путей
        помнит только файлы текущего запуска."""
        self.session._composites.clear()
        self.session._adopt_composites()

    def test_clearing_works_after_returning_to_the_item(self):
        """«Убрать всё» ничего не убирало: вернувшуюся с диска склейку
        приложение считало ЧУЖОЙ текстурой и не имело права её снять."""
        t = self.session.preview.textures
        self.session.set_part_colors('', {0: '#ff0000'})
        self.assertTrue(t.uploaded_for_mat(t.storage_main_key()))

        self._leave_and_return()
        self.session.clear_parts('')
        self.assertFalse(t.uploaded_for_mat(t.storage_main_key()))

    def test_repaint_does_not_stack_on_the_old_composite(self):
        """Прежняя склейка бралась ОСНОВОЙ следующей: под новым цветом
        просвечивал старый, и цвета грязнились с каждой перекраской."""
        t = self.session.preview.textures
        self.session.set_part_colors('', {0: '#ffee00'})
        self._leave_and_return()
        self.session.set_part_colors('', {0: '#0040ff'})
        after = Image.open(t.uploaded_for_mat(t.storage_main_key())).convert('RGB')

        self.session.clear_parts('')
        self.session.set_part_colors('', {0: '#0040ff'})
        clean = Image.open(t.uploaded_for_mat(t.storage_main_key())).convert('RGB')
        self.assertEqual(after.getpixel((32, 32)), clean.getpixel((32, 32)))

    def test_a_users_own_texture_is_not_mistaken_for_a_composite(self):
        """Одних данных частей мало: человек мог положить на материал свою
        текстуру поверх покраски, и стирать её нельзя."""
        t = self.session.preview.textures
        self.session.set_part_colors('', {0: '#ff0000'})
        mine = os.path.join(self.tmp, 'mine.png')
        Image.new('RGBA', (64, 64), (0, 255, 0, 255)).save(mine)
        t.set_texture(t.storage_main_key(), mine)

        self.session._composites.clear()
        self.session._adopt_composites()
        self.assertNotIn(mine, self.session._composites)

    def test_a_saved_composite_keeps_its_renamed_form(self):
        """work_store дописывает к имени хвост, когда рядом уже лежит файл от
        другого материала: на диске склейка зовётся parts_1_25.png. Без хвоста
        в шаблоне «Убрать всё» её не узнавало."""
        from src.app.session import _is_composite_name

        self.assertTrue(_is_composite_name('parts_1.png'))
        self.assertTrue(_is_composite_name('parts_1_25.png'))
        self.assertTrue(_is_composite_name(r'C:\work\keyiles\parts_7_2.png'))
        self.assertFalse(_is_composite_name('my_logo.png'))
        self.assertFalse(_is_composite_name('parts.png'))

    def test_a_scene_with_a_model_can_be_split(self):
        self.assertTrue(self.session.view_state()['can_split'])

    def test_a_scene_without_a_model_cannot(self):
        """Кнопка «разделить на части» не должна обещать того, чего нет: у
        скайбокса и спрея модели нет вовсе."""
        self.session._forget_model()
        self.assertFalse(self.session.view_state()['can_split'])

    def test_a_vanished_obj_is_not_splittable(self):
        """Временную папку воркера могли вычистить: путь есть, файла нет."""
        os.remove(self.session._obj_path)
        self.assertFalse(self.session.view_state()['can_split'])

    def test_parts_refuse_to_work_without_a_model(self):
        """Разбор ЧУЖОЙ модели опаснее отказа: путь от прошлого предмета дал бы
        части, которых на экране нет."""
        self.session._forget_model()
        self.assertIn('error', self.session.parts())

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
