"""
Экран модели (vgui-панель на attachment'ах controlpanel0) как геометрия

Циферблат Звона смерти в меше отсутствует: игра рисует его панелью между
двумя attachment'ами. Превью строит по ним квад фона и веер заполнения и
кладёт их отдельным SMD рядом с reference - дальше он идёт как бодигруппа
"""

from __future__ import annotations

import os
import tempfile
import unittest

from src.services import control_panel
from src.services.preview_3d_worker import Preview3DWorker

# bottom_left в начале координат, top_right на (2, 1, 0): экран 2×1 в XY, нормаль +Z
REFERENCE_SMD = (
    'version 1\nnodes\n0 "root" -1\n1 "bottom_left" 0\n2 "top_right" 0\nend\n'
    'skeleton\ntime 0\n0 0 0 0 0 0 0\n1 0 0 0 0 0 0\n2 2 1 0 0 0 0\nend\n'
    'triangles\nend\n')
QC = ('$modelname "weapons\\v_models\\v_watch_pocket_spy.mdl"\n'
      '$attachment "controlpanel0_ll" "bottom_left" 0 0 0 rotate 0 0 0\n'
      '$attachment "controlpanel0_ur" "top_right" 0 0 0 rotate 0 0 0\n')


class _Model:
    def __init__(self, qc_path):
        self.qc_path = qc_path


class ScreenSmdTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.tmp = self._dir.name
        self.ref = os.path.join(self.tmp, 'v_watch_pocket_spy.smd')
        self.qc = os.path.join(self.tmp, 'v_watch_pocket_spy.qc')
        with open(self.ref, 'w', encoding='utf-8') as f:
            f.write(REFERENCE_SMD)
        with open(self.qc, 'w', encoding='utf-8') as f:
            f.write(QC)

    def tearDown(self):
        self._dir.cleanup()

    def _vertices(self, path, material):
        out, cur = [], None
        with open(path, encoding='utf-8') as f:
            lines = f.read().split('triangles', 1)[1].splitlines()
        for ln in lines:
            parts = ln.split()
            if len(parts) == 1 and parts[0] != 'end':
                cur = parts[0]
            elif len(parts) > 8 and cur == material:
                out.append(tuple(float(x) for x in parts[1:4]))
        return out

    def test_screen_lies_between_the_attachments(self):
        paths = control_panel.screen_smds(self.tmp, self.ref)
        self.assertEqual([os.path.basename(p) for p in paths], ['__screen0.smd'])
        bg = self._vertices(paths[0], 'pocket_watch_bg')
        self.assertEqual(len(bg), 6)
        # Шкала занимает прямоугольник (10,10,260,80) панели 280×100
        xs, ys, zs = (sorted({round(v[i], 3) for v in bg}) for i in range(3))
        self.assertEqual(xs, [round(2 * 10 / 280, 3), round(2 * 270 / 280, 3)])
        self.assertEqual(ys, [0.1, 0.9])
        self.assertEqual(zs, [0.0])
        # Заполнение - половина круга, приподнята над фоном по нормали
        fg = self._vertices(paths[0], 'pocket_watch_fg')
        self.assertTrue(fg)
        self.assertEqual({round(v[2], 3) for v in fg}, {0.02})
        self.assertTrue(all(v[0] >= 1.0 - 1e-6 for v in fg))   # правая половина: по часовой от 12

    def test_nodes_are_copied_from_the_reference(self):
        path = control_panel.screen_smds(self.tmp, self.ref)[0]
        with open(path, encoding='utf-8') as f:
            text = f.read()
        self.assertIn('1 "bottom_left" 0', text)
        self.assertIn('2 "top_right" 0', text)
        # Вершины привязаны к кости нижнего левого угла
        self.assertIn('\n1 ', text.split('triangles', 1)[1])

    def test_unknown_model_or_missing_attachments_give_nothing(self):
        with open(self.qc, 'w', encoding='utf-8') as f:
            f.write('$modelname "weapons\\c_models\\c_bottle.mdl"\n')
        self.assertEqual(control_panel.screen_smds(self.tmp, self.ref), [])
        self.assertEqual(control_panel.screen_hints(self.tmp), {})
        with open(self.qc, 'w', encoding='utf-8') as f:
            f.write('$modelname "weapons\\v_models\\v_watch_pocket_spy.mdl"\n')
        self.assertEqual(control_panel.screen_smds(self.tmp, self.ref), [])
        self.assertEqual(control_panel.screen_smds(self.tmp, ''), [])

    def test_hints_draw_the_screen_with_alpha_from_both_sides(self):
        self.assertEqual(control_panel.screen_hints(self.tmp), {
            'pocket_watch_bg': {'blend': 'alpha', 'twoSided': True},
            'pocket_watch_fg': {'blend': 'alpha', 'twoSided': True}})

    def test_preview_worker_adds_the_screen_as_a_part(self):
        w = Preview3DWorker(weapon_key='c_pocket_watch', mode='spy_c_pocket_watch',
                            misc_vpk_path='m.vpk', textures_vpk_path='t.vpk')
        w._models[self.tmp] = _Model(self.qc)
        extra = w._find_bodygroup_smds(self.ref)
        self.assertEqual([os.path.basename(p) for p in extra], ['__screen0.smd'])


if __name__ == '__main__':
    unittest.main()


class WatchScreensTests(unittest.TestCase):
    """Экраны Quäckenbirdt и Enthusiast's Timepiece - как у Звона смерти"""

    def test_known_by_model_name(self):
        for qc_name, bg in (('weapons/v_models/v_ttg_watch_spy.mdl', 'ttg_watch_bg'),
                            ('workshop_partner/weapons/v_models/v_hm_watch/v_hm_watch.mdl',
                             'hm_watch_bg')):
            with tempfile.TemporaryDirectory() as tmp:
                qc = os.path.join(tmp, 'm.qc')
                with open(qc, 'w', encoding='utf-8') as f:
                    f.write(f'$modelname "{qc_name}"\n')
                self.assertEqual(control_panel.screen_spec(qc)['bg'], bg)


class WatchScreenResTests(unittest.TestCase):
    """.res экрана часов в моде: заменённое - из мода, остальное - игры"""

    def setUp(self):
        from src.services.texture_build.fixed_extras import watch_screen_res
        self.res = watch_screen_res

    def test_untouched_face_needs_no_res(self):
        self.assertIsNone(self.res('v_hm_watch', set()))
        self.assertIsNone(self.res('c_spy_watch', {'x'}))

    def test_replaced_image_comes_from_the_mod_the_other_from_the_game(self):
        text = self.res('v_hm_watch', {'hm_watch_fg'})
        self.assertIn('"fg_image"\t"replay/thumbnails/hmwatch/hm_watch_fg"', text)
        self.assertIn('"bg_image"\t"workshop_partner/hm_watch/hm_watch_bg"', text)

    def test_dead_ringer_keeps_its_paths(self):
        text = self.res('c_pocket_watch', {'pocket_watch_fg', 'pocket_watch_bg'})
        self.assertIn('"fg_image"\t"replay/thumbnails/deadringer/pocket_watch_fg"', text)
        self.assertIn('"bg_image"\t"replay/thumbnails/deadringer/pocket_watch_bg"', text)


class FlippedPanelTests(unittest.TestCase):
    """Угол ur в минус X и минус Y кости: игра рисует панель развёрнутой"""

    def test_panel_is_built_in_the_negative_quadrant(self):
        ref_text = REFERENCE_SMD.replace('2 2 1 0 0 0 0', '2 -2 -1 0 0 0 0')
        with tempfile.TemporaryDirectory() as tmp:
            ref = os.path.join(tmp, 'v_watch_pocket_spy.smd')
            with open(ref, 'w', encoding='utf-8') as f:
                f.write(ref_text)
            with open(os.path.join(tmp, 'v_watch_pocket_spy.qc'), 'w', encoding='utf-8') as f:
                f.write(QC)
            paths = control_panel.screen_smds(tmp, ref)
            self.assertEqual(len(paths), 1)
            xs, ys = [], []
            with open(paths[0], encoding='utf-8') as f:
                for ln in f.read().split('triangles', 1)[1].splitlines():
                    parts = ln.split()
                    if len(parts) > 8:
                        xs.append(float(parts[1]))
                        ys.append(float(parts[2]))
            self.assertLessEqual(max(xs), 0.0)
            self.assertLessEqual(max(ys), 0.0)
            self.assertLess(min(xs), -1.5)
