"""
Разбор бодигрупп QC: что игра показывает по умолчанию.

`$bodygroup` — это ПЕРЕКЛЮЧАТЕЛЬ, игра рисует ровно один вариант. Превью
складывало все варианты в одну модель, и бутылка показывалась целой и
разбитой одновременно (в стоке так устроены 36 пушек из 295 и 6 шапок).
"""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.services.model_build_service import ModelBuildService

BS = chr(92)


class BodygroupParseTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _qc(self, text: str, smds=()) -> str:
        for name in smds:
            (self.dir / name).write_text("version 1\n", encoding="utf-8")
        path = self.dir / "model.qc"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def _names(self, paths):
        return [os.path.basename(p) for p in paths]

    def test_switchable_group_gives_only_the_default_variant(self):
        """Бутылка: нулевой вариант — целая, первый — разбитая."""
        qc = self._qc(
            '$bodygroup "broken"\n{\n\tstudio "c_bottle.smd"\n'
            '\tstudio "c_bottle_broken.smd"\n}\n',
            ["c_bottle.smd", "c_bottle_broken.smd"])
        groups = ModelBuildService.extract_bodygroup_groups(qc)
        self.assertEqual(len(groups), 1)
        self.assertEqual(self._names(groups[0]),
                         ["c_bottle.smd", "c_bottle_broken.smd"])
        self.assertEqual(self._names(ModelBuildService.extract_default_body_smds(qc)),
                         ["c_bottle.smd"])

    def test_several_groups(self):
        """Тело + переключаемая гильза: показываем тело и нулевую гильзу."""
        qc = self._qc(
            '$bodygroup "body"\n{\n\tstudio "c_flaregun.smd"\n}\n\n'
            '$bodygroup "shell"\n{\n\tstudio "c_flaregun_shell.smd"\n\tblank\n}\n',
            ["c_flaregun.smd", "c_flaregun_shell.smd"])
        self.assertEqual(
            self._names(ModelBuildService.extract_default_body_smds(qc)),
            ["c_flaregun.smd", "c_flaregun_shell.smd"])

    def test_blank_first_means_nothing_is_drawn(self):
        """Если нулевой вариант — blank, группа по умолчанию не рисуется."""
        qc = self._qc(
            '$bodygroup "body"\n{\n\tstudio "main.smd"\n}\n\n'
            '$bodygroup "extra"\n{\n\tblank\n\tstudio "extra.smd"\n}\n',
            ["main.smd", "extra.smd"])
        groups = ModelBuildService.extract_bodygroup_groups(qc)
        self.assertIsNone(groups[1][0], groups)
        self.assertEqual(
            self._names(ModelBuildService.extract_default_body_smds(qc)),
            ["main.smd"])

    def test_nine_class_variants(self):
        """id_badge: девять классовых вариантов одной бодигруппы."""
        classes = [f"badge_{c}.smd" for c in
                   ("scout", "soldier", "pyro", "demo", "heavy",
                    "engineer", "medic", "sniper", "spy")]
        body = '$bodygroup "Body"\n{\n\tstudio "badge_body.smd"\n}\n\n'
        group = '$bodygroup "class"\n{\n' + "".join(
            f'\tstudio "{c}"\n' for c in classes) + '}\n'
        qc = self._qc(body + group, ["badge_body.smd"] + classes)
        self.assertEqual(len(ModelBuildService.extract_bodygroup_groups(qc)[1]), 9)
        self.assertEqual(
            self._names(ModelBuildService.extract_default_body_smds(qc)),
            ["badge_body.smd", "badge_scout.smd"])

    def test_single_line_body_form(self):
        """Однострочная форма `$body studio "x.smd"` — тоже группа."""
        qc = self._qc('$body studio "main.smd"\n', ["main.smd"])
        self.assertEqual(
            self._names(ModelBuildService.extract_default_body_smds(qc)),
            ["main.smd"])

    def test_service_smds_are_skipped(self):
        qc = self._qc(
            '$bodygroup "body"\n{\n\tstudio "main.smd"\n}\n'
            '$bodygroup "phys"\n{\n\tstudio "main_physics.smd"\n}\n',
            ["main.smd", "main_physics.smd"])
        self.assertEqual(
            self._names(ModelBuildService.extract_default_body_smds(qc)),
            ["main.smd"])

    def test_missing_file_is_not_returned(self):
        qc = self._qc('$bodygroup "body"\n{\n\tstudio "нет.smd"\n}\n')
        self.assertEqual(ModelBuildService.extract_default_body_smds(qc), [])

    def test_broken_or_absent_qc(self):
        self.assertEqual(ModelBuildService.extract_bodygroup_groups("нет.qc"), [])
        self.assertEqual(ModelBuildService.extract_default_body_smds(
            self._qc("совсем не qc\n")), [])

    def test_all_mesh_smds_include_the_single_model_form(self):
        """Косметика часто объявляет меш через $model — не через $bodygroup."""
        qc = self._qc('$model "Body" "hat.smd"\n', ["hat.smd"])
        self.assertEqual(
            self._names(ModelBuildService.extract_all_mesh_smds(qc)), ["hat.smd"])

    def test_all_mesh_smds_include_hidden_variants(self):
        """«Из чего состоит модель» — это все варианты, а не только видимые."""
        qc = self._qc(
            '$bodygroup "broken"\n{\n\tstudio "c_bottle.smd"\n'
            '\tstudio "c_bottle_broken.smd"\n}\n',
            ["c_bottle.smd", "c_bottle_broken.smd"])
        self.assertEqual(self._names(ModelBuildService.extract_all_mesh_smds(qc)),
                         ["c_bottle.smd", "c_bottle_broken.smd"])

    def test_all_mesh_smds_skip_service_files(self):
        qc = self._qc('$model "Body" "hat.smd"\n'
                      '$model "Phys" "hat_physics.smd"\n',
                      ["hat.smd", "hat_physics.smd"])
        self.assertEqual(
            self._names(ModelBuildService.extract_all_mesh_smds(qc)), ["hat.smd"])

    def test_build_path_still_sees_every_variant(self):
        """Сборке нужны ВСЕ варианты: пользователь вправе заменить и разбитую."""
        qc = self._qc(
            '$bodygroup "broken"\n{\n\tstudio "c_bottle.smd"\n'
            '\tstudio "c_bottle_broken.smd"\n}\n',
            ["c_bottle.smd", "c_bottle_broken.smd"])
        extra = ModelBuildService.extract_extra_body_smds(qc, "c_bottle")
        self.assertIn("c_bottle_broken.smd", self._names(extra))


if __name__ == "__main__":
    unittest.main()
