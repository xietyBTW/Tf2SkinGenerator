"""Тесты общего хелпера превью VTF (дедупликация VPK→VTF→PNG)."""

import unittest

from src.services import vtf_preview_service as vps


class _FakeEntry:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


class _FakePak:
    """Минимальный stub VPK: pak[path] → объект с .read(), иначе KeyError."""
    def __init__(self, files: dict):
        self._files = files

    def __getitem__(self, path):
        if path in self._files:
            return _FakeEntry(self._files[path])
        raise KeyError(path)


class VtfPreviewServiceTests(unittest.TestCase):
    def test_open_vpks_skips_missing(self):
        # Несуществующие пути не роняют и не попадают в результат.
        self.assertEqual(vps.open_vpks([None, "", "/no/such/file.vpk"]), [])

    def test_read_from_vpks_first_hit(self):
        p1 = _FakePak({"a/b.vtf": b"AAA"})
        p2 = _FakePak({"x/y.vtf": b"BBB"})
        self.assertEqual(vps.read_from_vpks([p1, p2], "x/y.vtf"), b"BBB")
        self.assertEqual(vps.read_from_vpks([p1, p2], "a/b.vtf"), b"AAA")

    def test_read_from_vpks_miss_returns_none(self):
        p = _FakePak({"a/b.vtf": b"AAA"})
        self.assertIsNone(vps.read_from_vpks([p], "nope/none.vtf"))

    def test_vtf_bytes_to_png_empty_is_none(self):
        self.assertIsNone(vps.vtf_bytes_to_png(None, "/tmp/x.png"))
        self.assertIsNone(vps.vtf_bytes_to_png(b"", "/tmp/x.png"))

    def test_vtf_bytes_to_frame_pngs_empty_is_list(self):
        self.assertEqual(vps.vtf_bytes_to_frame_pngs(None, "/tmp", "x"), [])
        self.assertEqual(vps.vtf_bytes_to_frame_pngs(b"", "/tmp", "x"), [])


if __name__ == "__main__":
    unittest.main()
