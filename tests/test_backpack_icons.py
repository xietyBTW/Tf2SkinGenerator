"""
Правило поиска иконки рюкзака: ключ каталога -> путь внутри VPK

Ключи в каталоге разные (путь из items_game, ключ оружия, путь к модели
шапки), а иконка одна и та же. Ошибка здесь не падает, а тихо показывает
чужую картинку, поэтому правило проверяется отдельно от VPK
"""

import unittest
import unittest.mock

from src.services import backpack_icons


class IconLookupTests(unittest.TestCase):
    def setUp(self):
        backpack_icons._index = {
            'c_scattergun': 'materials/backpack/weapons/c_models/c_scattergun.vtf',
            'w_minigun': 'materials/backpack/weapons/w_models/w_minigun.vtf',
            'soldier_officer':
                'materials/backpack/player/items/soldier/soldier_officer.vtf',
        }
        self.addCleanup(setattr, backpack_icons, '_index', None)

    def find(self, key):
        return backpack_icons.vpk_path_for(key, 'textures.vpk')

    def test_weapon_key(self):
        self.assertEqual(self.find('c_scattergun'),
                         'materials/backpack/weapons/c_models/c_scattergun.vtf')

    def test_stock_weapon_falls_back_to_world_model_icon(self):
        """У стоковых иконка объявлена под мировой моделью: c_minigun -> w_minigun"""
        self.assertEqual(self.find('c_minigun'),
                         'materials/backpack/weapons/w_models/w_minigun.vtf')

    def test_hat_key_is_a_model_path(self):
        self.assertEqual(
            self.find('models/player/items/soldier/soldier_officer.mdl'),
            'materials/backpack/player/items/soldier/soldier_officer.vtf')

    def test_declared_path_is_used_as_is(self):
        """image_inventory из items_game точен - индекс для него не нужен"""
        self.assertEqual(self.find('backpack/workshop/weapons/x/y'),
                         'materials/backpack/workshop/weapons/x/y.vtf')

    def test_declared_path_does_not_build_index(self):
        """Шапкам индекс не нужен - и строиться ради них он не должен"""
        backpack_icons._index = None
        with unittest.mock.patch.object(backpack_icons, '_build_index') as build:
            self.find('backpack/player/items/x/y')
        build.assert_not_called()

    def test_material_png_is_shrunk(self):
        """Произвольная текстура в 2048 px не уходит в карточку целиком"""
        import tempfile
        from pathlib import Path
        from PIL import Image

        def fake_png(_data, out):
            Image.new('RGBA', (1024, 512)).save(out)
            return out

        pak = {'materials/models/x/hands.vtf': unittest.mock.Mock()}
        with tempfile.TemporaryDirectory() as tmp, \
                unittest.mock.patch.object(backpack_icons, '_CACHE_DIR', Path(tmp)), \
                unittest.mock.patch('src.services.vpk_cache.open_vpk_cached',
                                    return_value=pak), \
                unittest.mock.patch('src.services.vtf_preview_service.vtf_bytes_to_png',
                                    side_effect=fake_png):
            png = backpack_icons.material_png('models/x/hands', 'textures.vpk')
            import io
            self.assertEqual(Image.open(io.BytesIO(png)).size, (256, 128))

    def test_backslashes_and_case(self):
        self.assertEqual(
            self.find(r'models\player\items\soldier\Soldier_Officer.mdl'),
            'materials/backpack/player/items/soldier/soldier_officer.vtf')

    def test_unknown_and_empty(self):
        for key in ('', 'c_nothing_like_this', 'models/x/nope.mdl'):
            self.assertIsNone(self.find(key), key)


if __name__ == '__main__':
    unittest.main()


class WeaponIconFromItemsGameTests(unittest.TestCase):
    """Иконка по items_game, когда её имя не совпадает с именем модели"""

    ITEMS_GAME = '''"items_game"
{
    "prefabs"
    {
        "sticky_defender" { "image_inventory" "backpack/weapons/w_models/w_stickybomb_defender" }
        "buff" { "image_inventory" "backpack/weapons/c_models/c_buffpack/c_buffpack"
                 "extra_wearable" "models/weapons/c_models/c_buffpack/c_buffpack.mdl" }
    }
    "items"
    {
        "129" { "prefab" "valve buff" }
        "130" { "prefab" "sticky_defender"
                "model_player" "models/weapons/c_models/c_scottish_resistance.mdl" }
        "230" { "image_inventory" "backpack/workshop/c_sydney_sleeper"
                "model_player" "models/workshop/c_sydney_sleeper.mdl" }
        "900" { "image_inventory" "backpack/gold_copy"
                "model_player" "models/weapons/c_models/c_scottish_resistance.mdl" }
    }
}'''

    def setUp(self):
        import tempfile
        from pathlib import Path
        from src.data import weapon_model_index as wmi

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        items = Path(tmp.name, 'tf', 'scripts', 'items')
        items.mkdir(parents=True)
        (items / 'items_game.txt').write_text(self.ITEMS_GAME, encoding='utf-8')
        self.root = tmp.name
        self.icon = wmi.weapon_icon
        self.addCleanup(wmi._icon_index.cache_clear)

    def test_icon_inherited_from_prefab_first_item_wins(self):
        self.assertEqual(self.icon('c_scottish_resistance', self.root),
                         'backpack/weapons/w_models/w_stickybomb_defender')

    def test_alias_and_extra_wearable(self):
        self.assertEqual(self.icon('c_dartgun', self.root),
                         'backpack/workshop/c_sydney_sleeper')
        self.assertEqual(self.icon('c_buffpack', self.root),
                         'backpack/weapons/c_models/c_buffpack/c_buffpack')

    def test_unknown(self):
        self.assertIsNone(self.icon('c_nothing', self.root))
        self.assertIsNone(self.icon('c_dartgun', ''))
