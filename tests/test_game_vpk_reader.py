"""Тесты кэширующего читателя игровых VPK (поиск VMT/VTF)."""

import unittest

from src.services.game_vpk_reader import GameVpkReader
from tests.fake_vpk import FakePak, fake_reader as _reader

class GameVpkReaderTests(unittest.TestCase):
    def test_read_hit_and_miss(self):
        r = _reader({"materials/x/c_w.vtf": b"VTF"})
        self.assertEqual(r.read("materials/x/c_w.vtf"), b"VTF")
        self.assertIsNone(r.read("materials/x/missing.vtf"))

    def test_read_falls_through_multiple_paks(self):
        r = GameVpkReader([])
        r._paks = [FakePak({}), FakePak({"a.vtf": b"data"})]
        self.assertEqual(r.read("a.vtf"), b"data")

    def test_find_vmt_basic(self):
        r = _reader({"materials/models/weapons/c_models/c_w.vmt": b'"VertexLitGeneric"{}'})
        res = r.find_vmt(["models/weapons/c_models"], "c_w")
        self.assertIsNotNone(res)
        self.assertTrue(res[0].endswith("c_w.vmt"))

    def test_find_vmt_workshop_swap(self):
        # VMT лежит по workshop-пути, а cdmaterials указывает на обычный player/items.
        r = _reader({
            "materials/models/workshop_partner/player/items/hat/c_hat.vmt": b'"x"{}',
        })
        res = r.find_vmt(["models/player/items/hat"], "c_hat")
        self.assertIsNotNone(res)
        self.assertIn("workshop_partner", res[0])

    def test_find_vmt_skips_backpack(self):
        r = _reader({"materials/backpack/c_w.vmt": b'"x"{}'})
        self.assertIsNone(r.find_vmt(["backpack"], "c_w"))

    def test_find_vmt_none_when_absent(self):
        self.assertIsNone(_reader({}).find_vmt(["models/x"], "c_w"))

    def test_parse_basetexture_quoted(self):
        # В реальном VMT путь с одинарными бэкслешами: models\weapons\c_w
        vmt = '"VertexLitGeneric"\n{\n"$basetexture" "models\\weapons\\c_w"\n}'
        self.assertEqual(GameVpkReader.parse_basetexture(vmt), "models/weapons/c_w")

    def test_parse_basetexture_bare_key_and_value(self):
        self.assertEqual(GameVpkReader.parse_basetexture("$baseTexture models/x/c_w"), "models/x/c_w")

    def test_parse_basetexture_missing(self):
        self.assertIsNone(GameVpkReader.parse_basetexture('"VertexLitGeneric"\n{\n}'))

    def test_find_vtf_for_basetexture_normalizes_path(self):
        r = _reader({"materials/models/x/c_w.vtf": b"VTF"})
        self.assertEqual(r.find_vtf_for_basetexture("models\\x\\c_w"), b"VTF")

    def test_source_extension_in_the_vmt_is_ignored(self):
        """У праздничного Правосудия и Уберпилы Valve оставила `.psd`.

        Движок читает такой путь без расширения, и без этого у них не было
        текстуры вовсе — ни в превью, ни в сборке.
        """
        r = _reader({"materials/models/weapons/c_items/c_ubersaw_xms.vtf": b"VTF"})
        self.assertEqual(
            r.find_vtf_for_basetexture("models/weapons/c_items/c_ubersaw_xms.psd"),
            b"VTF")
        self.assertEqual(
            r.find_vtf_for_basetexture("models/weapons/c_items/c_ubersaw_xms.vtf"),
            b"VTF")

    def test_dot_in_a_folder_name_is_not_an_extension(self):
        r = _reader({"materials/models/v1.5/c_w.vtf": b"VTF"})
        self.assertEqual(r.find_vtf_for_basetexture("models/v1.5/c_w"), b"VTF")

    def test_find_vtf_for_basetexture_none(self):
        self.assertIsNone(_reader({}).find_vtf_for_basetexture(""))

    def test_close_clears_ref_but_keeps_handle_open(self):
        # Хэндлами владеет общий потоко-локальный кэш (vpk_cache) — close() лишь
        # сбрасывает локальную ссылку, сам pak НЕ закрывает.
        r = _reader({"a": b"b"})
        pak = r._paks[0]
        r.close()
        self.assertFalse(pak.closed)
        self.assertIsNone(r._paks)

    def test_context_manager_does_not_close_handle(self):
        r = _reader({"a": b"b"})
        pak = r._paks[0]
        with r:
            pass
        self.assertFalse(pak.closed)
        self.assertIsNone(r._paks)


if __name__ == "__main__":
    unittest.main()
