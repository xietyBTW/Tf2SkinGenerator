"""
Геометрия из MDL/VVD/VTX там, где Crowbar её теряет (mdl_mesh).

Бинарный разбор проверен на игре вручную (Air Head, Sheriff's Stetson, тело
пиромана: первые группы совпадают с выводом Crowbar до шестого знака); здесь
— правила сопоставления и дописывания, которые не требуют игры.
"""

import os
import unittest
from tempfile import TemporaryDirectory
from unittest import mock

from src.services import mdl_mesh

QC = '''
$modelname "player/pyro.mdl"
$bodygroup "Body"
{
	studio "pyro_reference.smd"
}
$bodygroup "head"
{
	studio "pyro_head_bodygroup.smd"
	blank
}
$model "default" "extra.smd" {
	eyeball right "bip_head" -1.5 -3.5 68 "eyeball_r" 1 4 "pupil_r" 0.58
}
'''

SMD = '''version 1
nodes
  0 "root" -1
end
skeleton
  time 0
    0 0 0 0 0 0 0
end
triangles
mat
  0 0 0 0 0 0 1 0 0 1 0 1.000000
  0 1 0 0 0 0 1 1 0 1 0 1.000000
  0 0 1 0 0 0 1 0 1 1 0 1.000000
end
'''


def _tri(mat='mat'):
    v = ((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.5, 0.5), [(0, 1.0)])
    return mdl_mesh.Tri(mat, [v, v, v])


class QcTests(unittest.TestCase):
    def test_studios_follow_qc_order_with_blanks(self):
        self.assertEqual(mdl_mesh._qc_studios(QC), [
            'pyro_reference.smd', 'pyro_head_bodygroup.smd', '', 'extra.smd'])


class StripTests(unittest.TestCase):
    def test_strip_alternates_winding_and_skips_degenerate(self):
        self.assertEqual(list(mdl_mesh._unstrip([0, 1, 2, 3, 3, 4])),
                         [(0, 1, 2), (2, 1, 3)])

    def test_triangle_is_written_like_crowbar(self):
        lines = mdl_mesh.format_tri(_tri()).split('\n')
        self.assertEqual(lines[0], 'mat')
        self.assertEqual(lines[1], '  0 0.000000 0.000000 0.000000 0.000000 0.000000 1.000000 '
                                   '0.500000 0.500000 1 0 1.000000')


class RepairTests(unittest.TestCase):
    def _fake(self, groups):
        model = mdl_mesh.ModelMesh(0, 0, 'm', [[_tri() for _ in range(n)] for n in groups])
        return mock.patch.object(mdl_mesh, 'read_meshes', return_value=[model])

    def test_missing_groups_are_appended_after_crowbar_ones(self):
        with TemporaryDirectory() as tmp:
            qc = os.path.join(tmp, 'a.qc')
            open(qc, 'w', encoding='utf-8').write('$model "default" "a.smd"')
            smd = os.path.join(tmp, 'a.smd')
            open(smd, 'w', encoding='utf-8').write(SMD)
            with self._fake([1, 3]):
                self.assertEqual(mdl_mesh.repair_smd(qc, b'', b'', b''), {'a.smd': 3})
            self.assertEqual(mdl_mesh.smd_triangle_count(smd), 4)
            text = open(smd, encoding='utf-8').read()
            self.assertTrue(text.rstrip().endswith('end'))
            self.assertEqual(text.count('\nmat\n'), 4)

    def test_complete_or_unexplained_smd_is_left_alone(self):
        with TemporaryDirectory() as tmp:
            qc = os.path.join(tmp, 'a.qc')
            open(qc, 'w', encoding='utf-8').write('$model "default" "a.smd"')
            smd = os.path.join(tmp, 'a.smd')
            open(smd, 'w', encoding='utf-8').write(SMD)
            with self._fake([1]):
                self.assertEqual(mdl_mesh.repair_smd(qc, b'', b'', b''), {})
            # Один треугольник в SMD, а группы по 2 — не сходится: не трогаем.
            with self._fake([2, 2]):
                self.assertEqual(mdl_mesh.repair_smd(qc, b'', b'', b''), {})
            self.assertEqual(mdl_mesh.smd_triangle_count(smd), 1)


if __name__ == '__main__':
    unittest.main()
