"""
Поиск ОРИГИНАЛЬНОЙ игровой текстуры материала (что кладётся в мод как есть).

Раньше искали только по угадываемым путям `materials/{cdmaterials}/{имя}.vtf`,
и служебные материалы персонажей уходили в мод без оригинала: у них VTF лежит
не рядом со своим VMT (`models/player/spy/eyeball_invun.vmt` →
`models/player/shared/eyeball_invun`), а строки $cdmaterials с '..' и вовсе
выбрасывались. Проверяем обе дыры и то, что прямой путь по-прежнему в приоритете.
"""

import unittest
from unittest.mock import patch

from src.services.vpk_texture_builder import VpkTextureBuilder
from tests.fake_vpk import FakePak, fake_reader, vmt

SPY_CD = ["\\..\\..\\effects", "models\\player\\spy\\"]


def _patched(files):
    """Подменяет оба входа в архив: прямые пути и цепочку через VMT.

    Читатель строится ДО патча: fake_reader сам создаёт GameVpkReader, и с
    уже подменённым классом он подменил бы сам себя.
    """
    reader = fake_reader(files)
    return (
        patch("src.services.tf2_vpk_extract_service._open_vpk_cached",
              return_value=FakePak(files)),
        patch("src.services.game_vpk_reader.GameVpkReader", return_value=reader),
        patch("os.path.exists", return_value=True),
    )


def _run(files, mat_name, cdmaterials):
    """_get_original_vtf_bytes против фейкового архива."""
    direct, reader, exists = _patched(files)
    with direct, reader, exists:
        return VpkTextureBuilder._get_original_vtf_bytes(
            mat_name, cdmaterials, "textures.vpk", "misc.vpk")


def _via_vmt(files, mat_name, cdmaterials):
    direct, reader, exists = _patched(files)
    with direct, reader, exists:
        return VpkTextureBuilder._vtf_via_vmt(
            mat_name, cdmaterials, "textures.vpk", "misc.vpk")


class OriginalVtfTests(unittest.TestCase):

    def test_texture_next_to_the_material_wins(self):
        """Прямой путь дешевле и точнее — порядок менять нельзя."""
        files = {
            "materials/models/player/spy/spy_red.vtf": b"DIRECT",
            "materials/models/player/spy/spy_red.vmt": vmt(basetexture="other/thing"),
            "materials/other/thing.vtf": b"VIA_VMT",
        }
        self.assertEqual(_run(files, "spy_red", ["models\\player\\spy\\"]), b"DIRECT")

    def test_texture_that_lives_elsewhere_is_found_through_the_vmt(self):
        """Глаза и убер-скины лежат в общей папке — знает об этом только VMT."""
        files = {
            "materials/models/player/spy/eyeball_invun.vmt":
                vmt(basetexture="models/player/shared/eyeball_invun"),
            "materials/models/player/shared/eyeball_invun.vtf": b"SHARED",
        }
        self.assertEqual(_run(files, "eyeball_invun", SPY_CD), b"SHARED")

    def test_relative_cdmaterials_are_resolved_not_dropped(self):
        """'../../effects' рядом с 'models/player/spy' — это 'models/effects'."""
        files = {
            "materials/models/effects/invulnfx_red.vmt": vmt(basetexture="effects/red"),
            "materials/effects/red.vtf": b"UBER",
        }
        self.assertEqual(_run(files, "invulnfx_red", SPY_CD), b"UBER")

    def test_shader_without_a_basetexture_is_not_a_miss(self):
        """У EyeRefract своей текстуры нет вовсе — копировать в мод нечего."""
        files = {
            "materials/models/player/spy/eyeball_r.vmt":
                vmt(shader="EyeRefract", Iris="models/player/shared/eye-iris-blue"),
        }
        data, has_own = _via_vmt(files, "eyeball_r", ["models/player/spy"])
        self.assertIsNone(data)
        self.assertFalse(has_own, "материал без $basetexture не «потерянный»")

    def test_genuinely_missing_material_still_reports_a_miss(self):
        data, has_own = _via_vmt({}, "nothing_like_this", ["models/player/spy"])
        self.assertIsNone(data)
        self.assertTrue(has_own, "VMT нет — это настоящий промах, о нём и пишем")


if __name__ == "__main__":
    unittest.main()
