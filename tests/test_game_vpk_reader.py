import unittest

from src.services.game_vpk_reader import GameVpkReader


class _Entry:
    def __init__(self, data: bytes):
        self._data = data

    def read(self) -> bytes:
        return self._data


class _FakePak:
    """Имитация vpk-архива: dict путь→bytes, __getitem__ кидает KeyError при отсутствии."""

    def __init__(self, files: dict):
        self._files = files
        self.closed = False

    def __getitem__(self, key):
        return _Entry(self._files[key])  # KeyError если нет — как у vpklib

    def close(self):
        self.closed = True


def _reader(files: dict) -> GameVpkReader:
    r = GameVpkReader([])
    r._paks = [_FakePak(files)]   # инжектим, минуя реальный vpk.open
    return r


class GameVpkReaderTests(unittest.TestCase):
    def test_read_hit_and_miss(self):
        r = _reader({"materials/x/c_w.vtf": b"VTF"})
        self.assertEqual(r.read("materials/x/c_w.vtf"), b"VTF")
        self.assertIsNone(r.read("materials/x/missing.vtf"))

    def test_read_falls_through_multiple_paks(self):
        r = GameVpkReader([])
        r._paks = [_FakePak({}), _FakePak({"a.vtf": b"data"})]
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

    def test_find_vtf_for_basetexture_none(self):
        self.assertIsNone(_reader({}).find_vtf_for_basetexture(""))

    def test_close_clears_and_closes(self):
        r = _reader({"a": b"b"})
        pak = r._paks[0]
        r.close()
        self.assertTrue(pak.closed)
        self.assertIsNone(r._paks)

    def test_context_manager_closes(self):
        r = _reader({"a": b"b"})
        pak = r._paks[0]
        with r:
            pass
        self.assertTrue(pak.closed)


if __name__ == "__main__":
    unittest.main()
