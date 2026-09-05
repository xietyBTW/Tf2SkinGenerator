"""
Сцена спец-режимов: солдат умирает нужной смертью.

Крит и эффекты смерти показывали кубики-заглушку. Теперь это настоящая модель
класса с настоящей анимацией смерти из `soldier_animations.mdl`, и держать надо
две вещи: какому режиму какая смерть досталась и кому текстуры персонажа
вообще не нужны.
"""

from __future__ import annotations

import unittest

from src.data.weapons import SPECIAL_MODES, VTF_ONLY_SPECIAL_MODES
from src.services import death_scene_worker as dsw


class SequenceTests(unittest.TestCase):

    def test_every_special_mode_but_spray_has_a_death(self):
        """Спрей — это одна картинка, персонажа в нём нет."""
        self.assertEqual(sorted(dsw.SEQUENCES),
                         sorted(m for m in SPECIAL_MODES if m != 'spray'))

    def test_ice_and_gold_share_the_backstab(self):
        """Золотая статуя и ледяная — это застывшее тело, смерть одна."""
        self.assertEqual(dsw.SEQUENCES['death_ice'],
                         dsw.SEQUENCES['death_gold'])

    def test_crit_dies_of_a_headshot(self):
        self.assertEqual(dsw.SEQUENCES['critHIT'], 'primary_death_headshot')

    def test_burning_is_not_a_death_at_all(self):
        """Горящий игрок жив: стоит с оружием и вздрагивает от каждого тика
        урона. Стойка и вздрагивание в игре лежат порознь, и второе — разность
        (в SMD нули вместо поз), поэтому кладётся слоем поверх первой."""
        self.assertEqual(dsw.SEQUENCES['death_fire'], 'stand_PRIMARY')
        self.assertEqual(dsw.LAYERS['death_fire'], 'a_flinch01')
        self.assertNotIn('critHIT', dsw.LAYERS)


class FreezeTests(unittest.TestCase):
    """Где игра замораживает тело, там превью обязано показать статую."""

    def test_only_ice_and_gold_freeze(self):
        """Спайсикл и золотая сковорода не дают жертве упасть куклой: она
        доигрывает свою смерть и застывает. У горения и крита такого нет."""
        self.assertEqual(sorted(dsw.FROZEN), ['death_gold', 'death_ice'])

    def test_pause_is_longer_than_the_death_itself(self):
        """Смерть от удара в спину — чуть больше секунды. Если держать позу
        меньше, статую в кадре не разглядеть."""
        self.assertGreater(dsw.STATUE_HOLD, 2.0)

    def test_body_freezes_before_the_fall_ends(self):
        """Статуя стоит там, где тело было в тот миг.

        Дай падению доиграть — и вместо статуи на земле лежит солдат.
        """
        self.assertLess(dsw.FREEZE_AT, dsw.DEATH_SECONDS)


class MaterialTests(unittest.TestCase):
    """Кому текстуры персонажа доставать, а кому они лягут поверх."""

    def _emitted(self, mode: str):
        worker = dsw.DeathScenePreviewWorker.__new__(
            dsw.DeathScenePreviewWorker)
        worker.mode = mode
        sent = []
        worker.animated_ready = _Spy(sent, 'scene')
        worker.multi_material = _Spy(sent, 'textures')
        worker.render_hints = _Spy(sent, 'hints')
        worker._preview_dir = ''
        worker._emit_scene(None, {'parts': []}, '')
        return [name for name, _ in sent]

    def test_death_effect_skips_the_players_own_textures(self):
        """Лёд, золото и огонь ЗАМЕНЯЮТ материалы трупа целиком.

        Родные текстуры под ними не видны, а их поиск — лишняя работа и гонка
        за то, какая картинка ляжет последней.
        """
        for mode in VTF_ONLY_SPECIAL_MODES:
            self.assertEqual(self._emitted(mode), ['scene'], mode)


class _Spy:
    def __init__(self, log, name):
        self._log, self._name = log, name

    def emit(self, value):
        self._log.append((self._name, value))


if __name__ == '__main__':
    unittest.main()
