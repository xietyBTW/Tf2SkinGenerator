"""
Разделение модели на части и вклейка картинки в её место на развёртке.

Модели тут игрушечные, но проверяются ровно те решения, из-за которых фича
может тихо соврать пользователю: что считать одной частью, какие части в игре
неизбежно покрасятся вместе и куда именно ложится картинка.
"""

import os
import tempfile
import unittest
from unittest import mock

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

#: Два материала в одной модели: так устроены персонажи (у шпиона голова и
#: тело — разные текстуры со своими развёртками).
TWO_MATERIALS = """
v 0 0 0
v 1 0 0
v 1 1 0
v 5 0 0
v 6 0 0
v 6 1 0
vt 0.0 0.0
vt 0.4 0.0
vt 0.4 0.4
vt 0.6 0.6
vt 1.0 0.6
vt 1.0 1.0
usemtl head
f 1/1 2/2 3/3
usemtl body
f 4/4 5/5 6/6
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


#: Два материала, и у КАЖДОГО кусок из двух островов развёртки. Так устроены
#: персонажи: голова и тело — разные текстуры, и номера групп у них свои.
TWO_SEAMED_MATERIALS = """
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
v 2 0 0
v 2 1 0
v 9 0 0
v 10 0 0
v 10 1 0
v 11 0 0
v 11 1 0
vt 0.0 0.0
vt 0.3 0.0
vt 0.3 0.3
vt 0.0 0.3
vt 0.5 0.5
vt 0.8 0.5
vt 0.8 0.8
vt 0.5 0.8
usemtl head
f 1/1 2/2 3/3
f 1/1 3/3 4/4
f 2/5 5/6 6/7
f 2/5 6/7 3/8
usemtl body
f 7/1 8/2 9/3
f 7/1 9/3 10/4
f 8/5 10/6 11/7
f 8/5 11/7 9/8
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



def _hexes(colors):
    """Цвета частей без настроек кисти: {часть: '#rrggbb'}."""
    return {part: spec['color'] for part, spec in (colors or {}).items()}


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

    def test_a_region_cuts_inside_a_single_island(self):
        """Ножницы режут и там, где остров развёртки один на весь кусок: у
        обреза приклад с корпусом — один остров, и по островам резать нечего.
        По линии разреза у области с остатком общие вершины, но не пиксели —
        «делит развёртку» говорить нельзя."""
        path = _obj(os.path.join(self.tmp, 'r.obj'), TWO_SQUARES)
        model = parts.load(path, regions={'weapon': [[1]]})
        found = model.parts_of('weapon')
        self.assertEqual(len(found), 3)
        cut = [p for p in found if p.region == 0]
        self.assertEqual(len(cut), 1)
        self.assertEqual(cut[0].triangles, (1,))
        self.assertFalse(any(p.shared for p in found))
        # Остаток квадрата — тот же кусок, что и область.
        rest = next(p for p in found if 0 in p.triangles)
        self.assertEqual(rest.chunk, cut[0].chunk)

    def test_a_region_overlapping_another_piece_is_still_shared(self):
        """Исключение для линии разреза — только внутри своего куска. С чужим
        куском, у которого общие вершины развёртки, пиксели общие по-прежнему,
        даже если треугольники там разбиты иначе."""
        partial = """
v 0 0 0
v 1 0 0
v 1 1 0
v 9 0 0
v 10 0 0
v 9 1 0
vt 0.0 0.0
vt 1.0 0.0
vt 1.0 1.0
vt 0.0 1.0
usemtl weapon
f 1/1 2/2 3/3
f 4/1 5/2 6/4
"""
        path = _obj(os.path.join(self.tmp, 'r4.obj'), partial)
        found = parts.load(path, regions={'weapon': [[0]]}).parts_of('weapon')
        cut = next(p for p in found if p.region == 0)
        self.assertTrue(cut.shared, 'область не сказала, что делит пиксели')

    def test_a_later_region_takes_triangles_from_an_earlier_one(self):
        path = _obj(os.path.join(self.tmp, 'r2.obj'), TWO_SQUARES)
        model = parts.load(path, regions={'weapon': [[0, 1], [1]]})
        by_region = {p.region: p.triangles for p in model.parts_of('weapon')}
        self.assertEqual(by_region[0], (0,))
        self.assertEqual(by_region[1], (1,))

    def test_a_region_beyond_the_model_is_ignored(self):
        """Работа могла пережить смену модели: чужие номера не роняют разбор."""
        path = _obj(os.path.join(self.tmp, 'r3.obj'), TWO_SQUARES)
        model = parts.load(path, regions={'weapon': [[99, 100]]})
        self.assertEqual(len(model.parts_of('weapon')), 2)

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

    def test_a_flipped_picture_is_mirrored_in_the_composite(self):
        """Отражение, сделанное в окне посадки, доезжает до склейки: левое и
        правое меняются местами, верх остаётся верхом."""
        patch = Image.new('RGBA', (8, 8), (0, 0, 255, 255))
        for y in range(8):
            for x in range(4):
                patch.putpixel((x, y), (255, 0, 0, 255))       # левая половина — красная
        patch.save(self.patch)
        square = [((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)), ((0.0, 0.0), (1.0, 1.0), (0.0, 1.0))]
        out = os.path.join(self.tmp, 'flip.png')
        compose.compose(self.base, [compose.Layer(polygons=square, image=self.patch,
                                                  fit='stretch', image_flip_x=True)], out)
        image = Image.open(out).convert('RGB')
        self.assertEqual(image.getpixel((4, 32)), (0, 0, 255))   # слева теперь синее
        self.assertEqual(image.getpixel((60, 32)), (255, 0, 0))

    def test_cached_windows_match_a_fresh_compose(self):
        """Готовые окна слоёв берутся из кэша между мазками. Правка слоя A
        должна дойти до C и через посредника: B пересекается с обоими, а в
        «точном цвете» он берёт среднее по всей своей маске, в том числе там,
        где под ним лежит A. Ключ по одному B без его соседей отдал бы C
        устаревшим."""
        import numpy as np

        rng = np.random.default_rng(3)
        noise = rng.integers(0, 255, (64, 64, 4), dtype=np.uint8)
        noise[..., 3] = 255
        Image.fromarray(noise, 'RGBA').save(self.base)

        def square(u0, v0, u1, v1):
            return [((u0, v0), (u1, v0), (u1, v1)), ((u0, v0), (u1, v1), (u0, v1))]

        def layers(first):
            return [compose.Layer(polygons=square(0.0, 0.0, 0.5, 0.5), color=first, exact=True),
                    compose.Layer(polygons=square(0.4, 0.4, 0.8, 0.8), color='#2040ff', exact=True),
                    compose.Layer(polygons=square(0.7, 0.3, 0.95, 0.6), color='#20ff40', exact=True)]

        out = os.path.join(self.tmp, 'out.png')
        compose.clear_caches()
        compose.compose(self.base, layers('#ff0000'), out, frames=1)
        compose.compose(self.base, layers('#ffffff'), out, frames=1)
        cached = np.asarray(Image.open(out))
        compose.clear_caches()
        compose.compose(self.base, layers('#ffffff'), out, frames=1)
        self.assertTrue((cached == np.asarray(Image.open(out))).all())

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

    def test_an_anchor_keeps_the_picture_where_it_was(self):
        """После разреза наклейка должна остаться на месте развёртки.

        Без якоря каждая половинка вписывала картинку в СВОЙ габарит: одна
        наклейка превращалась на модели в две уменьшенные копии. Якорь — это
        габарит той части, на которую её клали изначально.
        """
        # Картинка-указатель: левая половина красная, правая синяя.
        wide = os.path.join(self.tmp, 'half.png')
        pointer = Image.new('RGBA', (16, 16), (255, 0, 0, 255))
        pointer.paste((0, 0, 255, 255), (8, 0, 16, 16))
        pointer.save(wide)
        # Часть — квадрат в правой половине развёртки.
        square = [((0.6, 0.0), (1.0, 0.0), (1.0, 0.4)),
                  ((0.6, 0.0), (1.0, 0.4), (0.6, 0.4))]

        def reds(anchor):
            out = os.path.join(self.tmp, f'a{anchor is not None}.png')
            path = compose.compose(self.base, [compose.Layer(
                polygons=square, image=wide, anchor=anchor)], out)
            pixels = Image.open(path).convert('RGB').getcolors(65536)
            return sum(n for n, c in pixels if c[0] > c[2] + 60)

        # Без якоря картинка вписана в саму часть: её красная половина внутри.
        self.assertGreater(reds(None), 50)
        # С якорем на весь холст часть попадает в СИНЮЮ половину картинки.
        self.assertEqual(reds((0.0, 0.0, 1.0, 1.0)), 0)

    def test_the_highlight_keeps_the_shape_of_the_texture(self):
        """Квадратными текстуры бывают не всегда.

        У тела шпиона она 1024×512. Подсветка, нарисованная в квадрат, ложилась
        на кадр растянутой по вертикали: контуры уезжали с деталей, а сверху и
        снизу кадра — поля, а не текстура."""
        square = [((0.0, 0.0), (0.4, 0.0), (0.0, 0.4))]
        wide = compose.outline_png(square, os.path.join(self.tmp, 'w.png'),
                                   shape=(1024, 512))
        plain = compose.outline_png(square, os.path.join(self.tmp, 'p.png'))
        self.assertEqual(Image.open(wide).size, (512, 256))
        self.assertEqual(Image.open(plain).size, (512, 512))

    def test_width_and_height_stretch_apart(self):
        """Картинку тянут за сторону рамки: своя ось — свой множитель.

        Одним множителем наклейку было не вытянуть под длинную деталь: она
        росла целиком и вылезала за кусок."""
        square = [((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)),
                  ((0.0, 0.0), (1.0, 1.0), (0.0, 1.0))]
        out = os.path.join(self.tmp, 'wide.png')
        path = compose.compose(self.base, [compose.Layer(
            polygons=square, image=self.patch, fit='contain',
            image_scale=0.5, image_scale_y=0.25)], out)
        red = Image.open(path).convert('RGB').getbbox()
        image = Image.open(path).convert('RGB')
        pixels = image.load()
        # Ширина красного пятна вдвое больше высоты — как и просили множители.
        xs = [x for x in range(image.width) if pixels[x, image.height // 2][0] > 150]
        ys = [y for y in range(image.height) if pixels[image.width // 2, y][0] > 150]
        self.assertTrue(xs and ys, red)
        self.assertAlmostEqual(len(xs) / max(1, len(ys)), 2.0, delta=0.35)

    def test_exact_colour_lands_as_chosen(self):
        """«Точный цвет»: средний тон детали совпадает с тем, что в палитре.

        Обычная тонировка считает цвет ОТ ЯРКОСТИ оригинала — на тёмной
        текстуре выбранный #cc5522 выходит бурым, и человек видит в палитре
        одно, а на модели другое."""
        want = (0xcc, 0x55, 0x22)
        square = [((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)),
                  ((0.0, 0.0), (1.0, 1.0), (0.0, 1.0))]

        def mean_of(exact):
            out = os.path.join(self.tmp, f'tint{exact}.png')
            path = compose.compose(self.base, [compose.Layer(
                polygons=square, color='#cc5522', exact=exact)], out)
            data = Image.open(path).convert('RGB')
            pixels = [c for _, c in data.getcolors(65536)]
            counts = [n for n, _ in data.getcolors(65536)]
            total = sum(counts)
            return tuple(sum(n * c[i] for n, c in zip(counts, pixels)) / total
                         for i in range(3))

        # База тёмная — как игровой металл: overlay считает цвет от неё и
        # уводит его в бурый, а «точный» так и остаётся выбранным.
        Image.new('RGBA', (64, 64), (60, 60, 60, 255)).save(self.base)
        for got, target in zip(mean_of(True), want):
            self.assertAlmostEqual(got, target, delta=6)
        soft = mean_of(False)
        self.assertGreater(abs(soft[0] - want[0]) + abs(soft[1] - want[1]), 20)

    def test_exact_colour_keeps_the_shading(self):
        """Фактура остаётся: тёмное место детали остаётся тёмным."""
        band = Image.new('RGBA', (64, 64), (60, 60, 60, 255))
        band.paste((200, 200, 200, 255), (0, 32, 64, 64))
        band.save(self.base)
        square = [((0.0, 0.0), (1.0, 0.0), (1.0, 1.0)),
                  ((0.0, 0.0), (1.0, 1.0), (0.0, 1.0))]
        out = os.path.join(self.tmp, 'shade.png')
        path = compose.compose(self.base, [compose.Layer(
            polygons=square, color='#cc5522', exact=True)], out)
        image = Image.open(path).convert('RGB')
        # В базе светлая полоса лежит в НИЖНИХ строках картинки.
        light = image.getpixel((32, 50))
        dark = image.getpixel((32, 10))
        self.assertGreater(sum(light), sum(dark) + 60)

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

    def test_gradient_edges_leave_pure_colour_outside(self):
        """Края перехода: за ними лежит чистый цвет, а не продолжение перелива.

        Ими человек говорит, сколько детали занимает сам перелив: сдвинул к
        середине — переход резче, а верх и низ остаются своими цветами."""
        image = self._tint(self._banded('band7.png'), 'grad4.png',
                           color='#ff0000', color2='#0000ff',
                           start=0.4, end=0.6)
        top = image.getpixel((32, 2))
        low = image.getpixel((32, 61))
        self.assertGreater(top[0], top[2] + 100)     # выше перехода — первый
        self.assertGreater(low[2], low[0] + 100)     # ниже — второй

    def test_gradient_middle_shifts_the_balance(self):
        """Середина — где цвета смешаны поровну. Сдвинутая к началу, она
        отдаёт второму цвету больше места: в точке 0.25 уже ровно смесь."""
        image = self._tint(self._banded('band8.png'), 'grad5.png',
                           color='#ff0000', color2='#0000ff', mid=0.25)
        quarter = image.getpixel((32, 16))           # четверть высоты части
        self.assertLess(abs(quarter[0] - quarter[2]), 40)

    def test_old_works_read_the_two_way_flag(self):
        """Работы, записанные до угла, хранят флаг horizontal — их не ломаем."""
        from src.domain.preview.part_specs import color_spec as _paint_spec

        self.assertEqual(_paint_spec({'color': '#ff0000', 'horizontal': True})['angle'], 90.0)
        self.assertEqual(_paint_spec({'color': '#ff0000', 'horizontal': False})['angle'], 0.0)
        self.assertEqual(_paint_spec({'color': '#ff0000', 'angle': 137})['angle'], 137.0)
        # Строка из старой работы — сплошной цвет сверху вниз, без второго.
        self.assertEqual(_paint_spec('#ff0000')['angle'], 0.0)
        self.assertIsNone(_paint_spec('#ff0000')['color2'])

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
        from src.domain.preview.part_specs import image_spec as _image_spec

        self.assertGreater(_image_spec({'path': 'a.png', 'scale': 0})['scale'], 0)
        self.assertGreater(_image_spec({'path': 'a.png', 'scale': -3})['scale'], 0)

    def test_old_works_store_the_picture_as_a_plain_path(self):
        """Работы, записанные до настройки посадки, хранят строку — их не ломаем."""
        from src.domain.preview.part_specs import image_spec as _image_spec

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

    def _gif(self, name, count, size=(16, 16)):
        from PIL import Image as PilImage

        gif = os.path.join(self.tmp, name)
        shots = [PilImage.new('RGBA', size, (k * 4 % 256, 0, 255 - k * 4 % 256, 255))
                 for k in range(count)]
        shots[0].save(gif, save_all=True, append_images=shots[1:],
                      duration=50, loop=0)
        return gif

    def test_the_build_gets_every_frame(self):
        """Гифка в 60 кадров обязана доехать до игры целиком. Раньше склейка
        держала все кадры в памяти и потому резала их по бюджету — на текстуре
        2048×2048 оставалось 20. Теперь кадры пишутся по одному."""
        from PIL import Image as PilImage

        square = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0))
        square2 = ((0.0, 0.0), (1.0, 1.0), (0.0, 1.0))
        res = compose.compose(self._banded('for_long.png'),
                              [compose.Layer(polygons=[square, square2],
                                             image=self._gif('long.gif', 60))],
                              os.path.join(self.tmp, 'long.png'))
        with PilImage.open(res) as im:
            self.assertEqual(im.n_frames, 60)
            self.assertEqual(im.info.get('duration'), 50)
            im.seek(59)
            last = im.convert('RGB').getpixel((32, 32))
        self.assertEqual(last, (59 * 4, 0, 255 - 59 * 4))

    def test_the_preview_takes_only_the_first_frame(self):
        """Превью показывает один кадр (3D APNG не крутит), и на каждый мазок
        собирать шестьдесят кадров по 16 МБ незачем: frames=1 даёт обычный PNG."""
        from PIL import Image as PilImage

        square = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0))
        res = compose.compose(self._banded('for_still.png'),
                              [compose.Layer(polygons=[square],
                                             image=self._gif('short.gif', 5))],
                              os.path.join(self.tmp, 'still.png'), frames=1)
        with PilImage.open(res) as im:
            self.assertEqual(getattr(im, 'n_frames', 1), 1)
            self.assertEqual(im.convert('RGB').getpixel((40, 20)), (0, 0, 255))

    def test_the_frame_cap_still_holds(self):
        self.assertEqual(compose._MAX_FRAMES, 64)
        square = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0))
        res = compose.compose(self._banded('for_cap.png'),
                              [compose.Layer(polygons=[square],
                                             image=self._gif('cap.gif', 70))],
                              os.path.join(self.tmp, 'cap.png'))
        from PIL import Image as PilImage
        with PilImage.open(res) as im:
            self.assertEqual(im.n_frames, 64)

    def test_the_shape_fingerprint_tells_bundles_apart(self):
        """Отпечаток решает, слать ли карты треугольников. Спутает два разных
        разбиения — вьювер останется со старой картой, и в 3D нельзя будет
        выбрать появившиеся части."""
        from src.app.session import AppSession

        from src.app.parts_editor import PartsEditor
        host = type('Host', (), {})()
        host._obj_path = ''
        host.preview = type('P', (), {})()
        host.preview.part_regions = {}
        app = PartsEditor(host)

        # Разрезы хранятся ПО МАТЕРИАЛУ: отпечаток берёт только свои.
        app.preview.part_cuts = {'weapon': {0: [[1], [2]]}}
        apart = app._shape_key('weapon')
        app.preview.part_cuts = {'weapon': {0: [[1, 2]]}}
        together = app._shape_key('weapon')
        self.assertNotEqual(apart, together)

        # Порядок записи на отпечаток влиять не должен.
        app.preview.part_cuts = {'weapon': {0: [[2, 1]]}}
        self.assertEqual(together, app._shape_key('weapon'))

        # Разрез СОСЕДНЕГО материала на этот отпечаток не влияет.
        app.preview.part_cuts = {'weapon': {0: [[2, 1]]}, 'head': {0: [[3]]}}
        self.assertEqual(together, app._shape_key('weapon'))

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
            self.session.parts.set_part_colors('', {square[0]: '#%02x0000' % (step * 20)})
        alive = [p for p in self.session.parts._compose_files if os.path.isfile(p)]
        self.assertLessEqual(len(self.session.parts._compose_files),
                             self.session.parts._KEEP_COMPOSITES)
        self.assertEqual(len(alive), len(self.session.parts._compose_files))

    def test_the_shown_composite_is_never_deleted(self):
        """Путь склейки — это ещё и адрес картинки во вьювере: удалить только
        что показанную нельзя."""
        for step in range(6):
            self.session.parts.set_part_colors('', {0: '#%02x0000' % (step * 30)})
        shown = self.session.preview.textures.uploaded_for_mat(
            self.session.preview.textures.storage_main_key())
        self.assertTrue(os.path.isfile(shown), shown)

    def test_a_gif_on_a_part_is_one_frame_in_preview_and_whole_in_the_build(self):
        """Превью держит от гифки один кадр — иначе каждый мазок собирал
        десятки кадров по 16 МБ и покраска приходила через десять секунд.
        Все кадры печёт сборка, по плану `_bake_plan`, и печёт ЦЕЛИКОМ: раньше
        потолок по памяти резал 60 кадров до 20."""
        gif = os.path.join(self.tmp, 'anim.gif')
        shots = [Image.new('RGBA', (8, 8), (k * 4, 0, 0, 255)) for k in range(60)]
        shots[0].save(gif, save_all=True, append_images=shots[1:],
                      duration=40, loop=0)
        self.session.parts.set_part_texture('weapon', 0, gif)
        self.session.parts.set_part_texture('weapon', 1, gif)
        self.session.parts.set_part_colors('weapon', {'1': '#00ff00'})

        t = self.session.preview.textures
        shown = t.uploaded_for_mat(t.storage_main_key())
        with Image.open(shown) as im:
            self.assertEqual(getattr(im, 'n_frames', 1), 1)

        plan = self.session.parts.bake_plan([shown, None, self.patch])
        self.assertEqual(list(plan), [shown])
        self.session.parts.bake(plan, lambda pct, text: None)
        full = plan[shown][2]
        with Image.open(full) as im:
            self.assertEqual(im.n_frames, 60)
            self.assertEqual(im.info.get('duration'), 40)

        # Без гифки печь нечего: склейка превью и так полная. Гифку на части 0
        # ЗАМЕНЯЕМ (слой 0): новая картинка без слоя легла бы поверх неё.
        self.session.parts.set_part_texture('weapon', 0, self.patch, layer=0)
        self.session.parts.set_part_texture('weapon', 1, None)
        still = t.uploaded_for_mat(t.storage_main_key())
        self.assertEqual(self.session.parts.bake_plan([still]), {})

    def test_the_viewer_gets_the_gif_frames_only_when_asked(self):
        """Гифка в 3D — настройка, по умолчанию выключенная: кадры считаются
        фоном после каждого мазка и приезжают событием parts_animated, а без
        настройки ничего не считается."""
        import threading
        from unittest import mock

        gif = os.path.join(self.tmp, 'anim.gif')
        shots = [Image.new('RGBA', (8, 8), (k * 8, 0, 0, 255)) for k in range(6)]
        shots[0].save(gif, save_all=True, append_images=shots[1:],
                      duration=50, loop=0)
        got = self.session.subscribe()

        # Настройка читается из конфига машины — тест на него не смотрит.
        with mock.patch.object(type(self.session.parts), '_parts_animation_on',
                               staticmethod(lambda: False)):
            self.session.parts.set_part_texture('weapon', 0, gif)
        self.assertEqual(sum(1 for t in threading.enumerate()
                             if t.name.startswith('parts-anim')), 0)
        self.assertTrue(got.empty())

        with mock.patch.object(type(self.session.parts), '_parts_animation_on',
                               staticmethod(lambda: True)):
            self.session.parts.set_part_colors('weapon', {'1': '#00ff00'})
            for t in threading.enumerate():
                if t.name.startswith('parts-anim'):
                    t.join(10)
        ev = got.get_nowait()
        self.assertEqual(ev['event'], 'parts_animated')
        self.assertEqual(ev['mesh'], 'weapon')
        self.assertEqual(len(ev['frames']), 6)
        self.assertEqual(ev['fps'], 20)
        still = self.session.preview.textures.uploaded_for_mat(
            self.session.preview.textures.storage_main_key())
        self.assertEqual(ev['still'], still)
        with Image.open(ev['frames'][0]) as a, Image.open(ev['frames'][5]) as b:
            self.assertNotEqual(a.tobytes(), b.tobytes(), 'кадры одинаковые')

    def test_cuts_travel_with_the_work(self):
        """Разрезы — часть работы: без них покраска вернулась бы на чужие куски.

        Номера частей зависят от разбиения. Работа помнила цвета, но забывала
        разрезы, и после переоткрытия «часть 2» означала уже другой кусок."""
        self.session._obj_path = _obj(os.path.join(self.tmp, 'seam.obj'),
                                      SEAMED_PIECE_AND_PLAIN_ONE)
        whole = len(parts.load(self.session._obj_path).parts_of('weapon'))
        self.session.parts.set_part_detail('weapon', 1.0)          # разрезали по швам
        cut = len(parts.load(self.session._obj_path,
                             self.session.preview.part_cuts).parts_of('weapon'))
        self.assertGreater(cut, whole, 'разрез не состоялся')

        edits = self.session.preview.user_edits()
        self.assertTrue(edits.get('part_cuts'), 'разрезы не попали в работу')

        # Работа вернулась с диска: разбиение обязано быть тем же.
        self.session.preview.part_cuts = {}
        self.session.preview.apply_user_edits(edits)
        back = len(parts.load(self.session._obj_path,
                              self.session.preview.part_cuts).parts_of('weapon'))
        self.assertEqual(back, cut)

    def test_cutting_one_material_leaves_the_other_alone(self):
        """Номера групп считаются ВНУТРИ материала.

        У головы шпиона и у его тела есть своя «группа 1», а разрезы лежали в
        общем словаре: отрезав воротник на теле, человек заодно перекраивал
        голову — её части получали новые номера, и покраска уезжала на чужие
        куски или пропадала вовсе."""
        t = self.session.preview.textures
        other = os.path.join(self.tmp, 'game2.png')
        Image.new('RGBA', (64, 64), (0, 0, 0, 255)).save(other)
        self.session._obj_path = _obj(os.path.join(self.tmp, 'two.obj'),
                                      TWO_SEAMED_MATERIALS)
        t.material_names = ['head', 'body']
        t.vpk_red_tex_map = {'head': self.base, 'body': other}

        self.session.parts.set_part_colors('head', {0: '#ff0000'})
        before = [(p.chunk, p.sub) for p in
                  parts.load(self.session._obj_path,
                             self.session.preview.part_cuts).parts_of('head')]

        # Режем группу 0 ТЕЛА — такая же есть и у головы. Дважды: разрезы
        # уже лежат в словаре по МАТЕРИАЛАМ, и план второго разреза читает их
        # заново — с плоским чтением он спотыкался об имя материала вместо
        # номера группы («invalid literal for int(): 'body'»).
        self.session.parts.toggle_part_island('body', 0, 0)
        self.assertNotIn('error', self.session.parts.toggle_part_island('body', 0, 1))

        after = [(p.chunk, p.sub) for p in
                 parts.load(self.session._obj_path,
                            self.session.preview.part_cuts).parts_of('head')]
        self.assertEqual(before, after, 'разбиение головы поехало от чужого разреза')
        self.assertEqual(_hexes(self.session.preview.part_colors.get('head')),
                         {0: '#ff0000'})

    def test_a_second_material_keeps_its_own_composite(self):
        """Склейка у каждого материала своя, а очередь на удаление была общей.

        Покрасив голову шпиона, а потом тело, человек тремя мазками выталкивал
        из очереди ещё ЖИВУЮ склейку головы: файл удалялся, назначенный путь
        оставался, и материал молча возвращался к игровой текстуре — со
        стороны это выглядело как «цвета сами сбрасываются»."""
        t = self.session.preview.textures
        other = os.path.join(self.tmp, 'game2.png')
        Image.new('RGBA', (64, 64), (0, 0, 0, 255)).save(other)
        self.session._obj_path = _obj(os.path.join(self.tmp, 'two.obj'),
                                      TWO_MATERIALS)
        t.material_names = ['head', 'body']
        t.vpk_red_tex_map = {'head': self.base, 'body': other}

        self.session.parts.set_part_colors('head', {0: '#ff0000'})
        self.session.parts.set_part_colors('body', {0: '#00ff00'})
        head_paint = t.uploaded_for_mat('head')

        # Мазки по одному материалу не должны стирать склейку соседнего.
        for step in range(6):
            self.session.parts.set_part_colors('body', {0: '#%02x8000' % (step * 30)})

        self.assertEqual(t.uploaded_for_mat('head'), head_paint)
        self.assertTrue(os.path.isfile(head_paint), head_paint)

    def test_a_painted_slot_stays_ours_after_its_files_are_gone(self):
        """Признак «склейка наша» — запись основы, а не путь и не файл: старые
        файлы склеек удаляются, а слот обязан оставаться покрашенным."""
        t = self.session.preview.textures
        for step in range(8):
            self.session.parts.set_part_colors('', {0: '#%02x0000' % (step * 30)})
        self.assertIn(t.storage_main_key(), self.session.preview.part_bases)

    def _leave_and_return(self, legacy: bool = False):
        """Возврат к предмету через работу. ``legacy`` — работа записана до
        явной основы: её надо перевести по именам файлов."""
        p = self.session.preview
        edits = p.user_edits()
        if legacy:
            edits.pop('part_bases')
        p.forget_user_edits()
        p.apply_user_edits(edits)

    def test_clearing_works_after_returning_to_the_item(self):
        """«Убрать всё» ничего не убирало: вернувшуюся с диска склейку
        приложение считало ЧУЖОЙ текстурой и не имело права её снять."""
        t = self.session.preview.textures
        for legacy in (False, True):
            self.session.parts.set_part_colors('', {0: '#ff0000'})
            self.assertTrue(t.uploaded_for_mat(t.storage_main_key()))
            self._leave_and_return(legacy)
            self.session.parts.clear_parts('')
            self.assertFalse(t.uploaded_for_mat(t.storage_main_key()), legacy)

    def test_repaint_does_not_stack_on_the_old_composite(self):
        """Прежняя склейка бралась ОСНОВОЙ следующей: под новым цветом
        просвечивал старый, и цвета грязнились с каждой перекраской."""
        t = self.session.preview.textures
        self.session.parts.set_part_colors('', {0: '#ffee00'})
        self._leave_and_return(legacy=True)
        self.session.parts.set_part_colors('', {0: '#0040ff'})
        after = Image.open(t.uploaded_for_mat(t.storage_main_key())).convert('RGB')

        self.session.parts.clear_parts('')
        self.session.parts.set_part_colors('', {0: '#0040ff'})
        clean = Image.open(t.uploaded_for_mat(t.storage_main_key())).convert('RGB')
        self.assertEqual(after.getpixel((32, 32)), clean.getpixel((32, 32)))

    def test_own_texture_on_a_painted_card_goes_under_the_strokes(self):
        """Своя текстура на покрашенную карточку раньше ЗАМЕНЯЛА склейку:
        чипы говорили «покрашено», а на модели мазков не было. Теперь она
        ложится основой под них, а «Убрать всё» возвращает именно её."""
        t = self.session.preview.textures
        key = t.storage_main_key()
        self.session.parts.set_part_colors('', {0: '#ff0000'})
        mine = os.path.join(self.tmp, 'mine.png')
        Image.new('RGBA', (64, 64), (0, 255, 0, 255)).save(mine)

        self.session.set_texture(key, mine)
        shown = t.uploaded_for_mat(key)
        self.assertNotEqual(shown, mine, 'мазки пропали с модели')
        colors = {c for _, c in Image.open(shown).convert('RGB').getcolors(65536)}
        self.assertIn((0, 255, 0), colors, 'своя текстура не легла основой')

        self.session.parts.clear_parts('')
        self.assertEqual(t.uploaded_for_mat(key), mine)

    def test_an_old_work_with_own_texture_over_strokes_keeps_it(self):
        """Перевод старой работы: своя текстура поверх мазков (не склейка по
        имени) становится основой, а не теряется."""
        t = self.session.preview.textures
        key = t.storage_main_key()
        self.session.parts.set_part_colors('', {0: '#ff0000'})
        mine = os.path.join(self.tmp, 'mine.png')
        Image.new('RGBA', (64, 64), (0, 255, 0, 255)).save(mine)
        t.set_texture(key, mine)

        self._leave_and_return(legacy=True)
        self.assertEqual(self.session.preview.part_bases.get(key), mine)

    def test_an_old_hanging_composite_is_dropped(self):
        """Склейка без мазков — след старого бага «Убрать всё не сработало»:
        перевод работы её снимает."""
        t = self.session.preview.textures
        key = t.storage_main_key()
        self.session.parts.set_part_colors('', {0: '#ff0000'})
        edits = self.session.preview.user_edits()
        edits.pop('part_bases')
        edits['part_colors'] = {}
        self.session.preview.forget_user_edits()
        self.session.preview.apply_user_edits(edits)
        self.assertFalse(t.uploaded_for_mat(key))

    def test_a_saved_composite_keeps_its_renamed_form(self):
        """work_store дописывает к имени хвост, когда рядом уже лежит файл от
        другого материала: на диске склейка зовётся parts_1_25.png. Без хвоста
        в шаблоне «Убрать всё» её не узнавало."""
        from src.domain.preview.part_specs import is_composite_name as _is_composite_name

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
        self.assertIn('error', self.session.parts.describe())

    def _painted(self):
        return self.session.preview.textures.textures[self.Team.RED].get('weapon')

    def test_parts_are_listed_with_a_number_for_every_triangle(self):
        """Вьювер возвращает попадание номером треугольника — без этой карты
        клик не с чем связать."""
        res = self.session.parts.describe()
        self.assertEqual(len(res['parts']), 2)
        self.assertEqual(len(res['tri_part']), 4)

    def test_painting_a_part_produces_the_material_texture(self):
        """Склейка ложится туда же, куда обычная своя текстура: дальше по
        конвейеру про части никто не знает."""
        self.session.parts.set_part_texture('weapon', 0, self.patch)
        painted = self._painted()
        self.assertTrue(painted and os.path.isfile(painted))
        self.assertNotEqual(painted, self.base)

    def test_clearing_the_last_part_returns_the_game_texture(self):
        self.session.parts.set_part_texture('weapon', 0, self.patch)
        self.session.parts.set_part_texture('weapon', 0, None)
        self.assertIsNone(self._painted())
        self.assertEqual(self.session.preview.part_textures, {})

    def test_second_part_is_composed_over_the_game_texture_not_the_previous_glue(self):
        """Иначе правки копились бы слоями и часть нельзя было бы перекрасить."""
        self.session.parts.set_part_texture('weapon', 0, self.patch)
        first = self._painted()
        green = os.path.join(self.tmp, 'green.png')
        Image.new('RGBA', (8, 8), (0, 255, 0, 255)).save(green)
        self.session.parts.set_part_texture('weapon', 0, green)
        second = self._painted()
        self.assertNotEqual(first, second)
        colors = {c for _, c in Image.open(second).convert('RGB').getcolors(4096)}
        self.assertNotIn((255, 0, 0), colors)

    def test_colour_paints_the_part(self):
        self.session.parts.set_part_colors('weapon', {'0': '#ff0000'})
        painted = self._painted()
        self.assertTrue(painted and os.path.isfile(painted))

    def test_brush_settings_freeze_at_the_stroke(self):
        """Настройки кисти запоминает МАЗОК, а не предмет.

        Иначе переключатель «точный цвет» или окантовка перекрашивали задним
        числом всё, что человек уже сделал, — а он менял кисть для следующего
        мазка, как в любом редакторе."""
        from src.domain.preview.part_specs import color_spec as _paint_spec

        self.session.parts.set_part_colors('weapon', {0: {'color': '#ff0000',
                                                    'exact': False}})
        self.session.parts.set_part_colors('weapon', {1: {'color': '#00ff00',
                                                    'exact': True}})
        kept = self.session.preview.part_colors['weapon']
        self.assertFalse(_paint_spec(kept[0])['exact'])
        self.assertTrue(_paint_spec(kept[1])['exact'])

        # Переключатель окантовки трогает КИСТЬ, а не сделанное.
        self.session.parts.set_part_edge('weapon', 0.01, '#000000')
        after = self.session.preview.part_colors['weapon']
        self.assertEqual(_paint_spec(after[0])['edge'], 0.0)
        self.assertEqual(_paint_spec(after[1])['edge'], 0.0)

    def test_an_old_work_takes_the_current_brush(self):
        """У работ до этой правки настроек в мазке нет — им достаются общие."""
        from src.domain.preview.part_specs import color_spec as _paint_spec

        spec = _paint_spec('#ff0000', {'strength': 0.4, 'exact': True,
                                       'edge': 0.02, 'edge_color': '#111111'})
        self.assertAlmostEqual(spec['strength'], 0.4)
        self.assertTrue(spec['exact'])
        self.assertAlmostEqual(spec['edge'], 0.02)

    def test_colour_and_image_live_together_on_one_part(self):
        """Это РАЗНЫЕ слои, а не два ответа на один вопрос.

        Цвет тонирует игровую текстуру (детали под ним остаются), картинка
        ложится на деталь сверху. Раньше второе действие молча стирало первое:
        покрасил корпус, наклеил на него знак — и покраска исчезала."""
        self.session.parts.set_part_texture('weapon', 0, self.patch)
        self.session.parts.set_part_colors('weapon', {'0': '#00ff00'})
        self.assertIn(0, self.session.preview.part_textures.get('weapon', {}))
        self.assertIn(0, self.session.preview.part_colors.get('weapon', {}))

        self.session.parts.set_part_texture('weapon', 0, self.patch)
        self.assertIn(0, self.session.preview.part_colors.get('weapon', {}))

    def test_cutting_keeps_both_layers_of_a_part(self):
        """Разрез переносит покраску на новые части — обе её половины.

        Перенос делался через `elif` (наследие правила «либо цвет, либо
        картинка»): у части с картинкой цвет при первом же разрезе исчезал —
        со стороны «порезал ножницами, и цвет слетел»."""
        self.session.parts.set_part_colors('weapon', {'0': '#2266ff'})
        self.session.parts.set_part_texture('weapon', 0, self.patch, {'scale': 0.5})
        self.session.parts.set_part_detail('weapon', 1.0)      # разрезать по всем швам

        colors = self.session.preview.part_colors.get('weapon', {})
        images = self.session.preview.part_textures.get('weapon', {})
        self.assertTrue(colors, 'цвет не пережил разрез')
        self.assertTrue(images, 'картинка не пережила разрез')
        # Обе половины достались одним и тем же частям — это один кусок модели.
        self.assertEqual(sorted(colors), sorted(images))

    def test_a_cut_picture_stays_anchored_when_it_is_re_placed(self):
        """Окно посадки двигает картинку ВНУТРИ её якоря.

        Якорь — габарит части, на которую наклейку клали; после разреза он
        единственный говорит, где она была. Потеряв его при первой же правке
        посадки, картинка прыгнула бы в габарит половинки."""
        from src.domain.preview.part_specs import image_list as _image_specs, image_spec as _image_spec

        images = lambda part: [_image_spec(v) for v in _image_specs(
            self.session.preview.part_textures['weapon'][part])]
        self.session.parts.set_part_texture('weapon', 0, self.patch)
        self.session.parts.set_part_detail('weapon', 1.0)          # разрезали
        part = sorted(self.session.preview.part_textures['weapon'])[0]
        anchor = images(part)[0]['anchor']
        self.assertIsNotNone(anchor, 'разрез не поставил якорь')

        self.session.parts.set_part_texture('weapon', part, None, {'scale': 1.5})
        spec = images(part)[0]
        self.assertEqual(spec['anchor'], anchor)
        self.assertAlmostEqual(spec['scale'], 1.5)

        # А новая картинка начинает с чистого листа: она про ЭТУ часть.
        self.session.parts.set_part_texture('weapon', part, self.patch)
        fresh = images(part)[-1]
        self.assertIsNone(fresh['anchor'])

    def test_images_stack_on_a_part(self):
        """Картинок на части может быть несколько — слоями, снизу вверх:
        новая ложится поверх, а не стирает предыдущую."""
        from src.domain.preview.part_specs import image_list as _image_specs

        green = os.path.join(self.tmp, 'green.png')
        Image.new('RGBA', (8, 8), (0, 255, 0, 255)).save(green)
        self.session.parts.set_part_texture('weapon', 0, self.patch, {'scale': 0.5})
        self.session.parts.set_part_texture('weapon', 0, green, {'scale': 0.2})
        stack = _image_specs(self.session.preview.part_textures['weapon'][0])
        self.assertEqual([s['path'] for s in stack], [self.patch, green])
        # Верхняя — зелёная и мельче: снизу видна и красная.
        colors = {c for _, c in
                  Image.open(self._painted()).convert('RGB').getcolors(65536)}
        self.assertIn((255, 0, 0), colors)
        self.assertIn((0, 255, 0), colors)

    def test_a_named_layer_is_edited_replaced_and_removed(self):
        from src.domain.preview.part_specs import image_list as _image_specs, image_spec as _image_spec

        green = os.path.join(self.tmp, 'green.png')
        Image.new('RGBA', (8, 8), (0, 255, 0, 255)).save(green)
        self.session.parts.set_part_texture('weapon', 0, self.patch)
        self.session.parts.set_part_texture('weapon', 0, green)
        stack = lambda: _image_specs(self.session.preview.part_textures['weapon'][0])

        # Посадка — у названного слоя, верхний не трогаем.
        self.session.parts.set_part_texture('weapon', 0, None, {'scale': 2.0}, layer=0)
        self.assertAlmostEqual(_image_spec(stack()[0])['scale'], 2.0)
        self.assertAlmostEqual(_image_spec(stack()[1])['scale'], 1.0)
        # Без слоя правится верхняя.
        self.session.parts.set_part_texture('weapon', 0, None, {'scale': 3.0})
        self.assertAlmostEqual(_image_spec(stack()[1])['scale'], 3.0)
        # Замена картинки слоя — на его месте.
        self.session.parts.set_part_texture('weapon', 0, green, layer=0)
        self.assertEqual([_image_spec(s)['path'] for s in stack()], [green, green])
        self.assertIn('error', self.session.parts.set_part_texture(
            'weapon', 0, None, {'scale': 1.0}, layer=5))
        # Снять один слой — остаётся другой; снять без слоя — все.
        self.session.parts.set_part_texture('weapon', 0, None, layer=0)
        self.assertEqual(len(stack()), 1)
        self.session.parts.set_part_texture('weapon', 0, None)
        self.assertNotIn(0, self.session.preview.part_textures.get('weapon', {}))

    def test_a_layer_moved_up_the_stack_shows_on_top(self):
        """Порядок стопки и есть наложение: переставил выше — легла поверх."""
        from src.domain.preview.part_specs import image_list as _image_specs

        green = os.path.join(self.tmp, 'green.png')
        Image.new('RGBA', (8, 8), (0, 255, 0, 255)).save(green)
        self.session.parts.set_part_texture('weapon', 0, self.patch)
        self.session.parts.set_part_texture('weapon', 0, green)
        pixels = lambda: {c for _, c in
                          Image.open(self._painted()).convert('RGB').getcolors(65536)}
        self.assertIn((0, 255, 0), pixels())
        self.assertNotIn((255, 0, 0), pixels())

        self.session.parts.move_part_texture('weapon', 0, 0, -1)     # красную наверх
        stack = _image_specs(self.session.preview.part_textures['weapon'][0])
        self.assertEqual([s['path'] for s in stack], [green, self.patch])
        self.assertIn((255, 0, 0), pixels())
        self.assertNotIn((0, 255, 0), pixels())
        self.assertIn('error', self.session.parts.move_part_texture('weapon', 0, 0, 7))

    def test_a_cut_moves_every_layer(self):
        from src.domain.preview.part_specs import image_list as _image_specs

        self.session.parts.set_part_texture('weapon', 0, self.patch)
        self.session.parts.set_part_texture('weapon', 0, self.patch)
        self.session.parts.set_part_detail('weapon', 1.0)
        part = sorted(self.session.preview.part_textures['weapon'])[0]
        self.assertEqual(len(_image_specs(
            self.session.preview.part_textures['weapon'][part])), 2)

    def test_placement_window_sees_the_other_layers_but_not_the_edited_one(self):
        """Основа для окна посадки — материал со всем, что на нём лежит, кроме
        правимого слоя: иначе под живой картинкой лежала бы её же копия."""
        Image.new('RGBA', (64, 64), (0, 0, 0, 255)).save(self.base)
        green = os.path.join(self.tmp, 'green.png')
        Image.new('RGBA', (8, 8), (0, 255, 0, 255)).save(green)
        self.session.parts.set_part_texture('weapon', 0, self.patch, {'scale': 0.5})
        self.session.parts.set_part_texture('weapon', 1, green)
        shape = self.session.parts.part_shape('weapon', 0, layer=0)
        self.assertEqual(shape['layer'], 0)
        self.assertEqual(shape['image']['path'], self.patch)
        colors = {c for _, c in
                  Image.open(shape['base']).convert('RGB').getcolors(65536)}
        self.assertIn((0, 255, 0), colors, 'соседний слой не виден')
        self.assertNotIn((255, 0, 0), colors, 'правимый слой запечён в основу')
        # Новая картинка: посадки нет, основа — со всеми слоями.
        fresh = self.session.parts.part_shape('weapon', 0)
        self.assertIsNone(fresh['image'])
        colors = {c for _, c in
                  Image.open(fresh['base']).convert('RGB').getcolors(65536)}
        self.assertIn((255, 0, 0), colors)

    def test_parts_paint_the_variant_card_while_australium_is_shown(self):
        """Части красят то, что в кадре: с включённым австралием — его карточку,
        поверх его gold-кадра; главная остаётся нетронутой."""
        gold = os.path.join(self.tmp, 'gold.png')
        Image.new('RGBA', (64, 64), (200, 170, 40, 255)).save(gold)
        t = self.session.preview.textures
        t.australium_frame = gold
        t.australium_mat_name = 'weapon_gold'

        t.australium_active = True
        self.session.parts.set_part_colors('', {'0': '#ff0000'})
        self.assertIn('weapon_gold', self.session.preview.part_colors)
        self.assertNotIn('weapon', self.session.preview.part_colors)
        painted = t.uploaded_for_mat('weapon_gold')
        self.assertTrue(painted and os.path.isfile(painted))
        self.assertIsNone(self._painted())
        # Странице — ключ геометрии, а не карточка варианта.
        self.assertEqual(self.session.parts.describe('')['material'], 'weapon')
        # Основа склейки — gold-кадр, не игровая текстура главной.
        colors = {c for _, c in Image.open(painted).convert('RGB').getcolors(65536)}
        self.assertNotIn((0, 0, 0), colors)

        t.australium_active = False
        self.session.parts.set_part_colors('', {'1': '#00ff00'})
        self.assertIn('weapon', self.session.preview.part_colors)
        self.assertEqual(_hexes(self.session.preview.part_colors['weapon_gold']), {0: '#ff0000'})
        # По имени карточка варианта достижима и без переключателя.
        self.assertEqual(self.session.parts.describe('weapon_gold')['parts'][0]['color']['color'], '#ff0000')

    def test_a_style_keeps_its_own_strokes_over_its_own_game_texture(self):
        """Мазки стиля — свои: покрасил Bloody, вернулся на базовый — там
        чисто. И склейка стиля ложится на ЕГО игровую текстуру, а не на базу."""
        bloody = os.path.join(self.tmp, 'bloody.png')
        Image.new('RGBA', (64, 64), (120, 0, 0, 255)).save(bloody)
        t = self.session.preview.textures
        t.skin_info = {'num_skins': 2}
        t.style_game_tex = {1: {'weapon': bloody}}
        self.session.preview.skin_chosen = {1: {'weapon'}}

        t.active_skin = 1
        self.session.parts.set_part_colors('weapon', {'0': '#00ff00'})
        styled = t.skin_overrides.get(1, {}).get('weapon')
        self.assertTrue(styled and os.path.isfile(styled), 'склейка не в стиле')
        colors = {c for _, c in Image.open(styled).convert('RGB').getcolors(65536)}
        self.assertIn((120, 0, 0), colors, 'основа стиля — не его текстура')
        self.assertNotIn((0, 0, 0), colors)

        t.active_skin = 0
        self.assertIsNone(self._painted())
        self.assertFalse([p for p in self.session.parts.describe('weapon')['parts'] if p['color']])
        self.session.parts.set_part_colors('weapon', {'1': '#0000ff'})
        self.assertEqual(_hexes(self.session.preview.part_colors['weapon']), {1: '#0000ff'})
        self.assertEqual(_hexes(self.session.preview.part_colors['weapon@style1']), {0: '#00ff00'})
        # Склейка стиля от базового мазка не пострадала.
        self.assertEqual(t.skin_overrides[1]['weapon'], styled)

    def test_a_style_composite_survives_strokes_on_another_style(self):
        """Склейка стиля живёт в `skin_overrides`, а уборка старых склеек
        смотрела только в `textures`: пять мазков на базовом стиле удаляли
        файл Bloody, путь к нему оставался — и стиль молча терял покраску."""
        t = self.session.preview.textures
        t.skin_info = {'num_skins': 2}
        self.session.preview.skin_chosen = {1: {'weapon'}}
        t.active_skin = 1
        self.session.parts.set_part_colors('weapon', {'0': '#00ff00'})
        styled = t.skin_overrides[1]['weapon']

        t.active_skin = 0
        for step in range(self.session.parts._KEEP_COMPOSITES + 2):
            self.session.parts.set_part_colors('weapon', {'1': '#%02x0000' % (step * 30)})
        self.assertTrue(os.path.isfile(styled), 'склейку стиля удалили')

    def test_brush_change_does_not_delete_a_draft(self):
        """Предмет открыт без своего черновика, человек сдвинул силу кисти —
        пустое сохранение стёрло бы черновик, которого он даже не вернул."""
        from src.services import work_keeper, work_store

        self.session.preview.weapon_key = 'c_scattergun'     # у работы есть ключ
        with mock.patch.object(work_keeper, 'is_enabled', return_value=True), \
                mock.patch.object(work_store, 'forget') as forget, \
                mock.patch.object(work_store, 'has', return_value=True):
            self.session.parts.set_part_colors('weapon', {}, strength=0.4)
        forget.assert_not_called()

    def test_brush_change_does_not_repaint_fresh_strokes(self):
        """Сила и «точный цвет» едут внутри мазка, а смена ползунка всё равно
        пересобирала склейку: секунда на 2048 и холостой шаг Ctrl+Z."""
        t = self.session.preview.textures
        self.session.parts.set_part_colors('weapon', {'0': {'color': '#ff0000',
                                                      'strength': 1.0,
                                                      'exact': False}})
        painted = t.uploaded_for_mat(t.storage_main_key())
        steps = len(self.session._edit_history)

        self.session.parts.set_part_colors('weapon', {}, strength=0.3, exact=True)
        self.assertEqual(t.uploaded_for_mat(t.storage_main_key()), painted)
        self.assertEqual(len(self.session._edit_history), steps)
        self.assertEqual(self.session.preview.part_tint, 0.3)

    def test_a_pasted_picture_keeps_its_size_on_the_texture(self):
        """Вставка «того же размера» — того же на ТЕКСТУРЕ: масштаб считается
        от габарита части, и тот же масштаб на другой детали дал бы другую
        картинку. Часть 0 — квадрат 0.4 текстуры (25.6 px из 64), картинка 8×8
        вписывается в него целиком; четверть текстуры (16 px) — масштаб 0.625."""
        self.session.parts.set_part_texture(
            'weapon', 0, self.patch, {'fit': 'contain', 'size_uv': [0.25, 0.25],
                                      'flip_x': True})
        spec = self.session.preview.part_textures['weapon'][0][-1]
        self.assertAlmostEqual(spec['scale'], 0.625, places=3)
        self.assertAlmostEqual(spec['scale_y'], 0.625, places=3)
        self.assertTrue(spec['flip_x'])
        self.assertNotIn('size_uv', spec)

    def test_scissors_cut_a_region_and_keep_the_paint(self):
        """Выделенное ножницами становится частью; покраска куска, из которого
        вырезали, остаётся и на ней — перенос идёт по треугольникам."""
        ed = self.session.parts
        ed.set_part_colors('weapon', {'0': '#ff0000'})
        out = ed.add_part_region('weapon', [1])
        self.assertNotIn('error', out)
        listed = ed.describe('weapon')['parts']
        cut = [p for p in listed if p['region'] == 0]
        self.assertEqual(len(cut), 1)
        self.assertEqual(len(listed), 3)
        self.assertEqual(cut[0]['color']['color'], '#ff0000')

        # «Вернуть» снимает область: частей снова две, покраска на месте.
        ed.remove_part_region('weapon', 0)
        listed = ed.describe('weapon')['parts']
        self.assertEqual(len(listed), 2)
        self.assertFalse(self.session.preview.part_regions)

    def test_scissors_take_the_mirrored_half_along(self):
        """Зеркальная половина с теми же пикселями красится вместе в игре —
        часть обязана её включать, а страница — об этом сказать."""
        self.session._obj_path = _obj(os.path.join(self.tmp, 'mirror.obj'), SHARED_UV)
        out = self.session.parts.add_part_region('weapon', [0])
        self.assertEqual(out['mirrored'], 1)
        self.assertEqual(self.session.preview.part_regions['weapon'], [[0, 1]])

    def test_scissors_with_nothing_selected_say_so(self):
        self.assertIn('error', self.session.parts.add_part_region('weapon', []))

    def test_scissors_are_undone_like_any_edit(self):
        ed = self.session.parts
        ed.set_part_colors('weapon', {'0': '#ff0000'})
        ed.add_part_region('weapon', [1])
        self.session.undo_edits(-1)
        self.assertFalse(self.session.preview.part_regions)

    def test_an_overtaken_composite_is_thrown_away(self):
        """Склейка считается вне замка сеанса. Результат, который обогнала
        более свежая правка, не должен лечь поверх неё — даже если досчитался
        позже."""
        from src.domain.preview.part_specs import color_spec

        ed = self.session.parts
        t = self.session.preview.textures
        model, obj_mat, card = ed._parts_model('weapon')
        slot = ed._slot(card)
        self.session.preview.part_colors[slot] = {0: color_spec('#ff0000')}
        with self.session._lock:
            old = ed._plan(model, obj_mat, card)
        self.session.preview.part_colors[slot] = {0: color_spec('#0000ff')}
        with self.session._lock:
            new = ed._plan(model, obj_mat, card)

        self.assertTrue(ed._finish([new]))
        self.assertFalse(ed._finish([old]))
        self.assertEqual(t.uploaded_for_mat(t.storage_main_key()), new['out'])
        self.assertFalse(os.path.exists(old['out']), 'обогнанный файл остался')

    def test_a_composite_does_not_land_on_a_replaced_state(self):
        """Пересборка досчиталась после «Забыть правки» (или отмены, или
        другого предмета) — её результат не должен вернуть забытую покраску."""
        from src.domain.preview.part_specs import color_spec

        ed = self.session.parts
        t = self.session.preview.textures
        model, obj_mat, card = ed._parts_model('weapon')
        self.session.preview.part_colors[ed._slot(card)] = {0: color_spec('#ff0000')}
        with self.session._lock:
            job = ed._plan(model, obj_mat, card)
        self.session.preview.forget_user_edits()

        self.assertFalse(ed._finish([job]))
        self.assertFalse(t.uploaded_for_mat(t.storage_main_key()))

    def test_force_team_keeps_a_base_per_team(self):
        """Под «сделать командным» у нейтральной карточки RED и BLU правят
        порознь: синяя склейка не должна собираться на красной основе."""
        from src.shared.constants import Team

        t = self.session.preview.textures
        key = t.storage_main_key()
        red = os.path.join(self.tmp, 'red.png')
        blue = os.path.join(self.tmp, 'blue.png')
        Image.new('RGBA', (64, 64), (200, 0, 0, 255)).save(red)
        Image.new('RGBA', (64, 64), (0, 0, 200, 255)).save(blue)
        t.force_team = True
        t.set_texture(key, red)
        t.active_team = Team.BLU
        t.set_texture(key, blue)

        t.active_team = Team.RED
        self.session.parts.set_part_colors('weapon', {'0': '#00ff00'})
        t.active_team = Team.BLU
        self.session.parts.set_part_colors('weapon', {'0': '#00ff00'})
        painted = t.textures[Team.BLU][key]
        colors = {c for _, c in Image.open(painted).convert('RGB').getcolors(65536)}
        self.assertIn((0, 0, 200), colors, 'синяя склейка легла на красную основу')
        self.assertNotIn((200, 0, 0), colors)

    def test_own_texture_while_the_model_is_switched_is_refused(self):
        """Пересобрать нельзя (включена бодигруппа) — основу не трогаем и
        говорим об этом, а не оставляем на экране склейку на прежней основе."""
        t = self.session.preview.textures
        key = t.storage_main_key()
        self.session.parts.set_part_colors('weapon', {'0': '#ff0000'})
        shown = t.uploaded_for_mat(key)
        mine = os.path.join(self.tmp, 'mine.png')
        Image.new('RGBA', (64, 64), (0, 255, 0, 255)).save(mine)

        self.session._bodygroups = {'bottle': 1}
        self.assertIn('error', self.session.set_texture(key, mine))
        self.assertEqual(self.session.preview.part_bases.get(key), '')
        self.assertEqual(t.uploaded_for_mat(key), shown)

    def test_blu_strokes_do_not_leak_into_red(self):
        from src.shared.constants import Team

        blue = os.path.join(self.tmp, 'blue.png')
        Image.new('RGBA', (64, 64), (0, 0, 120, 255)).save(blue)
        t = self.session.preview.textures
        t.blu_frames = [blue]                       # командный материал
        t.active_team = Team.BLU
        self.session.parts.set_part_colors('weapon', {'0': '#ff0000'})
        painted = t.textures[Team.BLU].get('weapon')
        self.assertTrue(painted and os.path.isfile(painted))
        self.assertNotIn('weapon', t.textures[Team.RED])
        colors = {c for _, c in Image.open(painted).convert('RGB').getcolors(65536)}
        self.assertIn((0, 0, 120), colors, 'основа синей склейки — не синий кадр')

        t.active_team = Team.RED
        self.assertFalse([p for p in self.session.parts.describe('weapon')['parts'] if p['color']])

    def test_a_cut_moves_the_strokes_of_every_style(self):
        t = self.session.preview.textures
        t.skin_info = {'num_skins': 2}
        self.session.preview.skin_chosen = {1: {'weapon'}}
        t.active_skin = 1
        self.session.parts.set_part_colors('weapon', {'0': '#00ff00'})
        t.active_skin = 0
        self.session.parts.set_part_colors('weapon', {'0': '#ff0000'})
        self.session.parts.set_part_detail('weapon', 1.0)
        self.assertTrue(self.session.preview.part_colors.get('weapon'))
        self.assertTrue(self.session.preview.part_colors.get('weapon@style1'))

    def test_the_image_lies_on_top_of_the_colour(self):
        """Порядок слоёв: сперва тонировка, потом наклейка. Наоборот картинка
        уходила бы под цвет и красилась им же."""
        Image.new('RGBA', (64, 64), (128, 128, 128, 255)).save(self.base)
        self.session.parts.set_part_colors('weapon', {'0': '#00ff00'})
        # Картинка мельче части: рядом с ней должна остаться видна тонировка.
        self.session.parts.set_part_texture('weapon', 0, self.patch, {'scale': 0.4})
        pixels = [c for _, c in
                  Image.open(self._painted()).convert('RGB').getcolors(65536)]
        self.assertTrue(any(r > g + 40 for r, g, _ in pixels), 'картинки не видно')
        self.assertTrue(any(g > r + 40 for r, g, _ in pixels), 'тонировки не видно')

    def test_clearing_everything_returns_the_game_texture(self):
        self.session.parts.set_part_colors('weapon', {'0': '#ff0000', '1': '#00ff00'})
        self.session.parts.clear_parts('weapon')
        self.assertIsNone(self._painted())
        self.assertEqual(self.session.preview.part_colors, {})

    def test_tint_strength_is_remembered(self):
        self.session.parts.set_part_colors('weapon', {'0': '#ff0000'}, strength=0.4)
        self.assertAlmostEqual(self.session.preview.part_tint, 0.4)

    def test_undo_returns_the_previous_painting(self):
        """Красят на ощупь: без отмены каждый щелчок приходится обдумывать."""
        self.session.parts.set_part_colors('weapon', {'0': '#ff0000'})
        self.session.parts.set_part_colors('weapon', {'1': '#00ff00'})
        self.session.undo_edits(-1)
        self.assertEqual(_hexes(self.session.preview.part_colors['weapon']),
                         {0: '#ff0000'})

    def test_undo_walks_back_to_the_clean_texture(self):
        self.session.parts.set_part_colors('weapon', {'0': '#ff0000'})
        self.session.undo_edits(-1)
        self.assertIsNone(self._painted())

    def test_nothing_to_undo_is_said_plainly(self):
        self.assertIn('error', self.session.undo_edits(-1))

    def test_undo_returns_the_strength_too(self):
        """Ползунок силы — тоже правка. Без него отмена была холостой."""
        self.session.parts.set_part_colors('weapon', {'0': '#ff0000'}, strength=1.0)
        self.session.parts.set_part_colors('weapon', {}, strength=0.4)
        self.session.undo_edits(-1)
        self.assertAlmostEqual(self.session.preview.part_tint, 1.0)

    def test_undo_returns_the_outline_too(self):
        self.session.parts.set_part_colors('weapon', {'0': '#ff0000'})
        self.session.parts.set_part_edge('weapon', 0.01, '#000000')
        self.session.undo_edits(-1)
        self.assertAlmostEqual(self.session.preview.part_edge, 0.0)

    def test_redo_puts_the_undone_step_back(self):
        self.session.parts.set_part_colors('weapon', {'0': '#ff0000'})
        self.session.parts.set_part_colors('weapon', {'1': '#00ff00'})
        self.session.undo_edits(-1)
        self.session.undo_edits(1)
        self.assertEqual(_hexes(self.session.preview.part_colors['weapon']),
                         {0: '#ff0000', 1: '#00ff00'})

    def test_a_new_stroke_forgets_the_way_forward(self):
        """Вернуться в ветку, которой уже не будет, нельзя."""
        self.session.parts.set_part_colors('weapon', {'0': '#ff0000'})
        self.session.undo_edits(-1)
        self.session.parts.set_part_colors('weapon', {'1': '#00ff00'})
        self.assertIn('error', self.session.undo_edits(1))

    def test_unknown_file_is_an_error(self):
        self.assertIn('error', self.session.parts.set_part_texture('weapon', 0, 'нет.png'))

    def test_without_a_model_there_are_no_parts(self):
        from src.app.session import AppSession
        self.assertIn('error', AppSession().parts.describe())


if __name__ == '__main__':
    unittest.main()


def test_leaving_a_custom_model_forgets_its_parts():
    """Номера частей и области были треугольниками СВОЕЙ модели: на игровой
    они легли бы на случайные куски."""
    from src.domain.preview.session import PreviewSession

    p = PreviewSession()
    p.custom_smd_path = 'own.smd'
    p.part_regions = {'weapon': [[1, 2]]}
    p.part_cuts = {'weapon': {0: [[1]]}}
    p.part_colors = {'weapon': {0: {'color': '#ff0000'}}}
    p.begin_game_model()
    assert not (p.part_regions or p.part_cuts or p.part_colors)


def test_a_weapon_with_styles_keeps_its_parts_on_reload():
    """У оружия со стилями `has_custom_model` верен и без своей геометрии —
    по нему покраска частей стиралась при каждом открытии предмета."""
    from src.domain.preview.session import PreviewSession

    p = PreviewSession()
    p.textures.skin_info = {'num_skins': 2}
    p.part_colors = {'weapon': {0: {'color': '#ff0000'}}}
    p.begin_game_model()
    assert p.part_colors
