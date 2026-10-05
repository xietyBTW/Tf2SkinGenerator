"""
Сцены «На модели» и насмешки без лишнего Crowbar.

Модель анимаций класса распаковывается до полуминуты и весит 120-165 МБ, а
кэш декомпиляции (1 ГБ на всё) вытеснял её первой: сцена снова ждала Crowbar,
даже после перезапуска. Использованные последовательности теперь лежат своей
копией (anim_store). Плюс одна распаковка на модель: превью и поиск стилей
открывали одну модель двумя Crowbar разом, а модель класса лежала в кэше под
тремя ключами.
"""

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.services import anim_store, decompile_cache
from src.services import model_decompile_service as mds
from src.services.weapon_anim_catalog import AnimSequence

QC = ('$upaxis Y\n'
      '$sequence "stand_PRIMARY" {\n\t"stand_PRIMARY.smd"\n\tactivity "ACT_MP_STAND_PRIMARY" 1\n'
      '\tfps 30\n\tloop\n}\n'
      '$sequence "stand_MELEE" {\n\t"stand_MELEE.smd"\n\tactivity "ACT_MP_STAND_MELEE" 1\n'
      '\tfps 24\n}\n')


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.vpk = self.root / "misc.vpk"
        self.vpk.write_bytes(b"x")
        self.smd = self.root / "taunt.smd"
        self.smd.write_text("version 1\n")
        p = patch.object(anim_store, "_ROOT", self.root / "store")
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_round_trip_and_game_update(self):
        seq = AnimSequence(name="layer_taunt_x", smd_path=str(self.smd), activity="",
                           fps=24.0, loop=True, hide_events=((3, True), (9, False)))
        kept = anim_store.put("taunt/medic/x/", str(self.vpk), seq, 1.5)
        self.assertNotEqual(kept.smd_path, seq.smd_path)          # своя копия
        got, rotation = anim_store.get("taunt/medic/x/", str(self.vpk))
        self.assertEqual((got.name, got.fps, got.loop, got.hide_events, rotation),
                         ("layer_taunt_x", 24.0, True, ((3, True), (9, False)), 1.5))
        self.assertIsNone(anim_store.get("taunt/medic/y/", str(self.vpk)))
        os.utime(self.vpk, (time.time() + 100, time.time() + 100))   # игра обновилась
        self.assertIsNone(anim_store.get("taunt/medic/x/", str(self.vpk)))


class StanceTests(StoreTests):
    def test_all_slot_stances_come_from_one_unpack(self):
        from src.services.hat_scene_worker import HatScenePreviewWorker

        anims = self.root / "anims"
        anims.mkdir()
        (anims / "scout_animations.qc").write_text(QC)
        for name in ("stand_PRIMARY", "stand_MELEE"):
            (anims / f"{name}.smd").write_text("version 1\n")
        w = HatScenePreviewWorker({"scout": "hat.mdl"}, str(self.vpk), "", "", "scout")
        weapons = [SimpleNamespace(anim="PRIMARY"), SimpleNamespace(anim="MELEE")]
        calls = []
        with patch.object(w, "_decompile", side_effect=lambda *a, **k: calls.append(a) or str(anims)):
            seq, _ = w._stance_of("scout", "scout", weapons[0], weapons)
            self.assertEqual(seq.name, "stand_PRIMARY")
            # Другой слот и новый воркер — без распаковки.
            seq, rotation = w._stance_of("scout", "scout", weapons[1], weapons)
        self.assertEqual((seq.name, seq.fps, rotation, len(calls)), ("stand_MELEE", 24.0, 0.0, 1))


class OneUnpackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.vpk = str(root / "misc.vpk")
        Path(self.vpk).write_bytes(b"x")
        crowbar = root / "crowbar.exe"
        crowbar.write_bytes(b"")
        self.src = root / "decompiled"
        self.src.mkdir()
        (self.src / "heavy.qc").write_text('$modelname "heavy.mdl"\n')
        self.runs = []
        for p in (patch.object(decompile_cache, "_CACHE_DIR", root / "cache"),
                  patch.object(mds.TF2Paths, "get_crowbar_path", staticmethod(lambda: str(crowbar))),
                  patch.object(mds, "_first_existing", lambda vpk, cands, stop: cands[0]),
                  patch.object(mds, "_extract_and_decompile", self.fake_crowbar),
                  patch.object(decompile_cache, "enforce_cache_limit", lambda *a: 0)):
            p.start()
            self.addCleanup(p.stop)

    def fake_crowbar(self, key, vpk, rel, crowbar, stop, progress):
        self.runs.append(key)
        time.sleep(0.1)                       # пока он идёт, приходят остальные
        cached = decompile_cache.save_to_cache(key, vpk, rel, str(self.src))
        return mds.Decompiled(directory=cached, mdl_rel=rel, cached=True)

    def test_parallel_callers_run_crowbar_once(self):
        got = []
        threads = [threading.Thread(target=lambda: got.append(mds.ensure_decompiled(
            "c_wrench", self.vpk, ["models/player/heavy.mdl"]))) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(self.runs, ["c_wrench"])
        self.assertEqual(len({g.directory for g in got}), 1)

    def test_same_model_under_another_key_is_copied(self):
        mds.ensure_decompiled("heavy", self.vpk, ["models/player/heavy.mdl"])
        got = mds.ensure_decompiled("__player_heavy", self.vpk, ["models/player/heavy.mdl"])
        self.assertEqual(self.runs, ["heavy"])
        self.assertTrue(os.path.isfile(os.path.join(got.directory, "heavy.qc")))


if __name__ == "__main__":
    unittest.main()
