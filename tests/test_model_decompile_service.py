"""Общий путь «кэш → VPK → Crowbar» (src/services/model_decompile_service.py)."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.services import decompile_cache as dc
from src.services import model_decompile_service as mds

WEAPON = "c_test"
DIRECT = "models/weapons/c_models/c_test/c_test.mdl"
WORKSHOP = "models/workshop/weapons/c_models/c_test/c_test.mdl"


class _Recorder:
    """Заглушки Crowbar и VPK: считают вызовы и пишут файлы, как настоящие."""

    def __init__(self, present_in_vpk):
        self.present = set(present_in_vpk)
        self.decompiles = 0
        self.stages = []

    def check_mdl_exists(self, _vpk, path):
        return path in self.present

    def extract_file_set(self, _vpk, mdl_rel, out_dir):
        mdl = Path(out_dir) / (Path(mdl_rel).stem + ".mdl")
        mdl.write_bytes(b"fake mdl")
        return [str(mdl)]

    def decompile(self, _mdl, out_dir, _crowbar):
        self.decompiles += 1
        qc = Path(out_dir) / f"{WEAPON}.qc"
        qc.write_text("$modelname x", encoding="utf-8")
        return str(qc)


class EnsureDecompiledTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.vpk = base / "tf2_misc_dir.vpk"
        self.vpk.write_bytes(b"fake vpk")
        self.crowbar = base / "CrowbarCommandLineDecomp.exe"
        self.crowbar.write_bytes(b"fake exe")

        self._patches = [patch.object(dc, "_CACHE_DIR", base / "cache")]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def _run(self, rec, candidates, **kwargs):
        with patch.object(mds.TF2Paths, "get_crowbar_path", return_value=str(self.crowbar)), \
             patch.object(mds.TF2VPKExtractService, "check_mdl_exists", rec.check_mdl_exists), \
             patch.object(mds.TF2VPKExtractService, "extract_file_set", rec.extract_file_set), \
             patch.object(mds.ModelBuildService, "decompile", rec.decompile):
            return mds.ensure_decompiled(
                WEAPON, str(self.vpk), candidates,
                on_progress=rec.stages.append, **kwargs
            )

    def test_decompiles_once_then_serves_from_cache(self):
        rec = _Recorder([DIRECT])

        first = self._run(rec, [DIRECT])
        self.assertIsNotNone(first)
        self.assertTrue(first.cached)
        self.assertEqual(first.mdl_rel, DIRECT)
        self.assertTrue((Path(first.directory) / f"{WEAPON}.qc").exists())

        second = self._run(rec, [DIRECT])
        self.assertEqual(second.directory, first.directory)
        self.assertEqual(rec.decompiles, 1, "второй прогон обязан идти из кэша")

    def test_cache_hit_when_model_lies_under_a_later_candidate(self):
        """Кэш ищется по КАЖДОМУ кандидату, а не только по первому.

        Запись сохраняется под тем путём, который реально нашёлся. Пока
        проверялся только первый кандидат, всё, что лежит не по прямому пути
        (шапки в workshop/), декомпилировалось заново при каждом показе.
        """
        rec = _Recorder([WORKSHOP])
        candidates = [DIRECT, WORKSHOP]

        first = self._run(rec, candidates)
        self.assertEqual(first.mdl_rel, WORKSHOP)

        second = self._run(rec, candidates)
        self.assertEqual(second.directory, first.directory)
        self.assertEqual(rec.decompiles, 1)

    def test_model_absent_from_vpk_is_not_an_error(self):
        rec = _Recorder([])
        self.assertIsNone(self._run(rec, [DIRECT]))
        self.assertEqual(rec.decompiles, 0)

    def test_progress_reports_both_long_steps(self):
        rec = _Recorder([DIRECT])
        self._run(rec, [DIRECT])
        self.assertEqual(rec.stages, [mds.Stage.EXTRACTING, mds.Stage.DECOMPILING])

    def test_cancellation_skips_decompile(self):
        rec = _Recorder([DIRECT])
        self.assertIsNone(self._run(rec, [DIRECT], cancelled=lambda: True))
        self.assertEqual(rec.decompiles, 0)

    def test_missing_vpk_raises(self):
        rec = _Recorder([DIRECT])
        with self.assertRaises(mds.DecompileError):
            with patch.object(mds.TF2Paths, "get_crowbar_path", return_value=str(self.crowbar)):
                mds.ensure_decompiled(WEAPON, str(self.vpk) + ".missing", [DIRECT])
        self.assertEqual(rec.decompiles, 0)

    def test_missing_crowbar_raises(self):
        with patch.object(mds.TF2Paths, "get_crowbar_path", return_value="nope.exe"):
            with self.assertRaises(mds.DecompileError):
                mds.ensure_decompiled(WEAPON, str(self.vpk), [DIRECT])

    def test_crowbar_failure_becomes_decompile_error(self):
        rec = _Recorder([DIRECT])

        def boom(*_a, **_k):
            raise RuntimeError("crowbar exited with 1")

        rec.decompile = boom
        with self.assertRaises(mds.DecompileError):
            self._run(rec, [DIRECT])


if __name__ == "__main__":
    unittest.main()
