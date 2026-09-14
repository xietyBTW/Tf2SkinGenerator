"""
Панорама 360° в режиме неба: перенос фото должен что-то менять.

Нарезка панорамы на шесть граней и сборка из неё существовали давно
(`SkyboxService.split_equirect_to_faces`, `skybox_build_data`), но между ними
и страницей не было проводки: `set_texture('__pano__', …)` молча складывал
путь в домен, воркер нарезки никто не запускал, а в `BuildRequest` поля неба
не попадали. Со стороны это выглядело так: перенёс фото 360° — не изменилось
ничего.

Здесь проверяется именно проводка сеанса, а не арифметика нарезки (её держит
test_skybox_service) и не приоритет граней (test_texture_state).
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.app.session import AppSession
from src.data.skyboxes import SKY_PANO_KEY, SKYBOX_MODE


class SkyboxPanoWiringTests(unittest.TestCase):
    def setUp(self):
        self.session = AppSession()
        self.session._mode = SKYBOX_MODE

    def test_pano_starts_the_split(self):
        """Панорама одна на все шесть граней — её надо нарезать.

        До нарезки превью её не видит вовсе: грани показываются по
        `resolve_skybox_face`, а `skybox_split_faces` заполняет только воркер.
        """
        with patch.object(self.session.skybox, 'split') as split, \
             patch.object(self.session, '_put_skybox') as put:
            self.session._after_skybox_texture(SKY_PANO_KEY, 'C:/pano.png')

        split.assert_called_once_with('C:/pano.png')
        # Событие пошлёт сам воркер, когда нарежет: сейчас показывать нечего.
        put.assert_not_called()

    def test_removing_the_pano_forgets_the_split(self):
        """Снятая панорама не должна оставлять свои грани в кадре."""
        self.session.preview.textures.skybox_split_faces = {'up': 'C:/up.png'}

        with patch.object(self.session.skybox, 'stop_split') as stop, \
             patch.object(self.session, '_put_skybox') as put:
            self.session._after_skybox_texture(SKY_PANO_KEY, None)

        stop.assert_called_once()
        self.assertEqual(self.session.preview.textures.skybox_split_faces, {})
        put.assert_called_once()

    def test_face_only_refreshes_the_preview(self):
        """Своя грань уже в домене — её достаточно показать, резать нечего."""
        with patch.object(self.session.skybox, 'split') as split, \
             patch.object(self.session, '_put_skybox') as put:
            self.session._after_skybox_texture('lf', 'C:/lf.png')

        split.assert_not_called()
        put.assert_called_once()

    def test_foreign_material_is_not_our_business(self):
        """Материал модели в режиме неба — не грань и не панорама."""
        with patch.object(self.session.skybox, 'split') as split, \
             patch.object(self.session, '_put_skybox') as put:
            self.session._after_skybox_texture('c_scattergun', 'C:/x.png')

        split.assert_not_called()
        put.assert_not_called()

    def test_event_carries_pano_and_resolved_faces(self):
        """Странице нужны и грани, и панорама: у панорамы своя карточка.

        Без неё фото 360° некуда положить — грани принимают по одной картинке
        каждая.
        """
        t = self.session.preview.textures
        with patch.object(t, 'resolve_skybox_face',
                          side_effect=lambda f: f'C:/{f}.png'), \
             patch.object(t, 'skybox_pano', return_value='C:/pano.png'), \
             patch.object(self.session, '_put') as put:
            self.session._put_skybox()

        name, payload = put.call_args[0][0], put.call_args[1]
        self.assertEqual(name, 'skybox')
        self.assertEqual(payload['pano'], 'C:/pano.png')
        self.assertEqual(payload['pano_key'], SKY_PANO_KEY)
        self.assertEqual(sorted(payload['faces']),
                         ['bk', 'dn', 'ft', 'lf', 'rt', 'up'])


if __name__ == '__main__':
    unittest.main()
