"""
Праздничное оружие: гирлянда и пушка, на которой она висит.

`c_scattergun_xmas` — не отдельная пушка, а навесные огоньки: в items_game
модель записана в `attached_models`, а `model_player` предмета остаётся
обрезом. В 3D-превью грузилась одна гирлянда, и оружия в кадре не было вовсе.

Проверяется, кого считаем носителем, и правило сессии: носитель в кадре есть,
но предмету не принадлежит — карточек по нему не строится, а текстура ложится
ПОДЛОЖКОЙ. Плюс два места, где эта подложка терялась: возврат из вида от
первого лица и подстановка своей модели.

Qt здесь не нужен: воркеры давно на своих сигналах.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from src.app.preview_controller import Preview3DController
from src.app.session import AppSession
from src.domain.preview.session import PreviewSession
from src.domain.preview.texture_state import SINGLE_TEX_KEY
from src.services import carrier_model
from src.services.model_decompile_service import Decompiled
from src.services.preview_3d_worker import Preview3DWorker

#: Пути к игре для сеанса: настоящая установка тестам не нужна.
PATHS = {"root": "D:/Game", "tf_dir": "D:/Game/tf",
         "misc_vpk": "D:/Game/tf/tf2_misc_dir.vpk",
         "textures_vpk": "D:/Game/tf/tf2_textures_dir.vpk"}


def _worker(weapon_key: str, mode: str = "scout_c_scattergun_xmas"):
    return Preview3DWorker(
        weapon_key=weapon_key, mode=mode,
        misc_vpk_path="tf2_misc_dir.vpk", textures_vpk_path="tf2_textures_dir.vpk",
    )


class _Info:
    """Ровно то из WeaponAnimInfo, что нужно этому решению."""

    def __init__(self, carried_on: str = ""):
        self.carried_on = carried_on


def _decompiled(directory="/tmp/carrier"):
    return patch("src.services.model_decompile_service.ensure_decompiled",
                 return_value=Decompiled(directory, "x.mdl", True))


def _reference(path):
    return patch("src.services.smd_service.find_reference_smd", return_value=path)


def _bodygroups(paths=()):
    return patch("src.services.carrier_model._bodygroups", return_value=list(paths))


def _hangs_on(base):
    return patch("src.data.viewmodel_anims.anim_info", return_value=_Info(base))


class CarrierLookupTests(unittest.TestCase):
    """Кого считаем носителем и когда вообще его ищем."""

    def test_festive_weapon_pulls_the_gun_it_hangs_on(self):
        ref = "/tmp/carrier/c_scattergun_reference.smd"
        with _hangs_on("c_scattergun"), _decompiled(), _reference(ref), _bodygroups():
            found = carrier_model.find("c_scattergun_xmas", "misc.vpk", "D:/Game")
        self.assertEqual(found.smds, [ref])
        self.assertEqual(found.key, "c_scattergun")
        # Папка нужна ради `$cdmaterials`: они у носителя свои, и без них
        # пушка в кадре осталась бы серой.
        self.assertEqual(found.directory, "/tmp/carrier")
        self.assertTrue(found)

    def test_carrier_bodygroups_come_along(self):
        """Шланг медигана — бодигруппа: без неё пушка в кадре обрублена."""
        ref = "/tmp/carrier/c_medigun_reference.smd"
        hose = "/tmp/carrier/c_medigun_hose_reference.smd"
        with _hangs_on("c_medigun"), _decompiled(), _reference(ref), _bodygroups([hose]):
            found = carrier_model.find("c_medigun_xmas", "misc.vpk", "D:/Game")
        self.assertEqual(found.smds, [ref, hose])

    def test_carrier_is_looked_up_by_name(self):
        """Имя носителя — подсказка поиску меша.

        Без неё у медигана брался первый попавшийся `*_reference.smd`, и в
        кадр попадал ОДИН ШЛАНГ (`c_medigun_hose_reference.smd`) вместо пушки.
        """
        seen = {}

        def _find(directory, prefer=""):
            seen["prefer"] = prefer
            return "/tmp/carrier/c_medigun_reference.smd"

        with _hangs_on("c_medigun"), _decompiled(), _bodygroups(), \
                patch("src.services.smd_service.find_reference_smd", _find):
            carrier_model.find("c_medigun_xmas", "misc.vpk", "D:/Game")
        self.assertEqual(seen.get("prefer"), "c_medigun")

    def test_plain_weapon_has_no_carrier(self):
        with _hangs_on(""):
            found = carrier_model.find("c_scattergun", "misc.vpk", "D:/Game")
        self.assertFalse(found)
        self.assertEqual(found.smds, [])

    def test_carrier_that_did_not_decompile_is_not_fatal(self):
        """Носитель не достали — показываем гирлянду, а не падаем."""
        with _hangs_on("c_scattergun"), \
                patch("src.services.model_decompile_service.ensure_decompiled",
                      return_value=None):
            self.assertFalse(
                carrier_model.find("c_scattergun_xmas", "misc.vpk", "D:/Game"))

    def test_hat_never_looks_for_a_carrier(self):
        """У шапки weapon_key — путь к MDL, и носителя у неё не бывает."""
        w = _worker("models/player/items/scout/hat.mdl", mode="hat")
        with patch("src.services.carrier_model.find",
                   side_effect=AssertionError("носителя у шапки не ищут")):
            self.assertEqual(w._carrier_smds(), [])


class _WithFiles(unittest.TestCase):
    """Пути в состоянии разрешаются только для СУЩЕСТВУЮЩИХ файлов.

    `_existing` в texture_state молча отдаёт None на выдуманное имя, и тест
    на несуществующих путях проверял бы не то.
    """

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)

    def _png(self, name: str) -> str:
        path = os.path.join(self._dir.name, name)
        with open(path, "wb") as f:
            f.write(b"png")
        return path


class SceneExtraTests(_WithFiles):
    """Носитель в кадре — подложка, а не состав предмета."""

    def setUp(self):
        super().setUp()
        self.session = PreviewSession()
        self.controller = Preview3DController(self.session)

    def _festive(self):
        """Праздничный обрез: гирлянда предмета плюс подложка носителя."""
        lights, gun = self._png("lights.png"), self._png("gun.png")
        self.session.textures.material_names = [SINGLE_TEX_KEY]
        self.session.textures.vpk_red_tex_map = {SINGLE_TEX_KEY: lights}
        self.controller._on_scene_extra(
            ({"c_scattergun": gun}, ["xms_colored_lights"]))
        return lights, gun

    def test_carrier_texture_paints_the_mesh_but_makes_no_card(self):
        _lights, gun = self._festive()
        self.assertEqual(self.session.scene_textures().get("c_scattergun"), gun)
        # Карточки — только предмет: красить базовый обрез, собирая мод на
        # праздничный, человек не должен.
        self.assertEqual(self.session.card_materials(), [SINGLE_TEX_KEY])

    def test_item_texture_lands_on_the_real_mesh_name(self):
        """Служебный ключ — имя ХРАНЕНИЯ, меша с ним в сцене нет.

        Пока предмет был один в кадре, текстуру клали глобально. Теперь рядом
        стоит чужая пушка, и глобальная легла бы и на неё, — поэтому имя меша
        приходит от воркера вместе с подложкой.
        """
        lights, _gun = self._festive()
        scene = self.session.scene_textures()
        self.assertEqual(scene.get("xms_colored_lights"), lights)
        self.assertNotIn(SINGLE_TEX_KEY, scene)

    def test_item_texture_wins_over_the_backing(self):
        """Подложка лежит ПОД предметом: правка предмета её перебивает."""
        s = self.session
        game, carrier = self._png("game.png"), self._png("carrier.png")
        s.textures.material_names = ["gun"]
        s.textures.vpk_red_tex_map = {"gun": game}

        self.controller._on_scene_extra(({"gun": carrier}, []))

        self.assertEqual(s.scene_textures().get("gun"), game)

    def test_empty_payload_changes_nothing(self):
        self.controller._on_scene_extra(({}, []))
        self.assertEqual(self.session.scene_extra_textures, {})
        self.assertEqual(self.session.scene_item_materials, [])


class FirstPersonRootTests(unittest.TestCase):
    """Какой корень игры уезжает в воркер вида от первого лица."""

    def test_items_game_root_not_the_tf_folder(self):
        """Корень ИГРЫ, а не `tf`.

        По нему воркер читает items_game (`viewmodel_anims.anim_info`) —
        оттуда слот анимаций, подмена активностей и пушка-носитель. С `tf_dir`
        items_game не находился, anim_info молча отдавал None, и кунай играл
        анимации ножа-бабочки, а в руке висели огоньки без пушки.
        """
        s = AppSession()
        s._mode = "scout_c_scattergun_xmas"
        seen = {}

        def _load(key, mode, misc, textures, tf2_root, **kw):
            seen["tf2_root"] = tf2_root

        with patch.object(AppSession, "tf2_paths", staticmethod(lambda: PATHS)), \
                patch.object(s.viewmodel, "shows", lambda *a: False), \
                patch.object(s.viewmodel, "load", _load), \
                patch.object(s.controller, "stop", lambda: None):
            s.load_first_person("IDLE")

        self.assertEqual(seen.get("tf2_root"), "D:/Game")


class LeaveFirstPersonTests(_WithFiles):
    """Выход из вида от первого лица не должен уносить подложку модели."""

    def setUp(self):
        super().setUp()
        self.session = AppSession()

    def test_carrier_backing_survives_the_round_trip(self):
        """Гирлянда не должна краситься на всю модель после возврата.

        Поля подложки общие у вида от первого лица и обычной модели. Выход
        чистит их за руками класса — и уносил заодно пушку-носителя. В сцене
        оставалась ОДНА запись под служебным ключом, а такую вьювер кладёт
        ГЛОБАЛЬНО: текстура гирлянды оказывалась и на оружии.
        """
        p = self.session.preview
        lights, gun = self._png("lights.png"), self._png("gun.png")
        p.textures.material_names = [SINGLE_TEX_KEY]
        p.textures.vpk_red_tex_map = {SINGLE_TEX_KEY: lights}
        self.session.controller._on_scene_extra(
            ({"c_scattergun": gun}, ["xms_colored_lights"]))

        # Вид от первого лица кладёт СВОЮ подложку — руки класса.
        p.scene_extra_textures = {"scout_hands": self._png("hands.png")}
        p.scene_item_materials = ["xms_colored_lights"]

        with patch.object(self.session.viewmodel, "stop", lambda: None):
            self.session.leave_first_person()

        scene = p.scene_textures()
        self.assertEqual(scene.get("c_scattergun"), gun)
        self.assertEqual(scene.get("xms_colored_lights"), lights)
        # Руки — часть ТОЙ сцены, в обычной их быть не должно.
        self.assertNotIn("scout_hands", scene)
        # И ни одной записи под служебным ключом: такую кладут глобально.
        self.assertNotIn(SINGLE_TEX_KEY, scene)

    def test_plain_weapon_keeps_nothing_after_the_round_trip(self):
        """У обычного оружия носителя нет — возвращать нечего."""
        p = self.session.preview
        p.scene_extra_textures = {"scout_hands": self._png("hands.png")}
        p.scene_item_materials = ["c_scattergun"]

        with patch.object(self.session.viewmodel, "stop", lambda: None):
            self.session.leave_first_person()

        self.assertEqual(p.scene_extra_textures, {})
        self.assertEqual(p.scene_item_materials, [])

    def test_new_model_forgets_the_previous_carrier(self):
        """Подложка прошлого предмета к новому не относится."""
        c = self.session.controller
        c._on_scene_extra(({"c_scattergun": self._png("gun.png")}, ["lights"]))
        with patch("src.services.preview_3d_worker.Preview3DWorker"):
            c.load_game_model("c_soda_popper", "scout_c_soda_popper",
                              "misc.vpk", "textures.vpk")
        self.assertEqual(c._scene_extra, ({}, []))


class CustomModelTests(_WithFiles):
    """Своя модель у праздничного оружия заменяет ГИРЛЯНДУ, а не пушку."""

    def setUp(self):
        super().setUp()
        self.session = AppSession()
        self.smd = os.path.join(self._dir.name, "my.smd")
        with open(self.smd, "w", encoding="utf-8") as f:
            f.write("version 1\n")

    def _load(self, carrier, produced, carrier_mats=()):
        """Прогоняет замену модели: (что ушло в конвертер, что вышло наружу)."""
        seen = {}

        def _convert(src, obj, extra_smd_paths=(), **kw):
            seen["extra"] = list(extra_smd_paths)
            with open(obj, "w", encoding="utf-8") as f:
                f.write("# obj\n")
            return True, list(produced)

        self.session.preview.weapon_key = "c_scattergun_xmas"
        with patch.object(AppSession, "tf2_paths", staticmethod(lambda: PATHS)), \
                patch("src.services.carrier_model.find", return_value=carrier), \
                patch("src.services.carrier_model.materials",
                      return_value=set(carrier_mats)), \
                patch("src.services.smd_to_obj_service.SmdToObjService.convert",
                      _convert), \
                patch.object(self.session.controller, "stop", lambda: None), \
                patch.object(self.session, "_on_model_ready",
                             lambda *a, **k: None):
            asked = self.session.load_custom_model(self.smd)
            done = self.session.load_custom_model(self.smd, keep=True)
        return seen, asked, done

    def test_carrier_stays_in_the_frame(self):
        """Пушка под гирляндой остаётся: её меш едет в ту же сборку OBJ."""
        ref = "/tmp/c_scattergun_reference.smd"
        carrier = carrier_model.Carrier(smds=[ref], directory="/tmp",
                                        key="c_scattergun")
        seen, asked, _ = self._load(carrier, ["my_lights", "c_scattergun"],
                                    carrier_mats={"c_scattergun"})

        self.assertEqual(seen["extra"], [ref])
        # Карточка только у СВОЕЙ модели: материал носителя предмету не
        # принадлежит, и красить базовый обрез человек не должен.
        self.assertEqual(asked["materials"], ["my_lights"])

    def test_plain_weapon_is_untouched(self):
        """У обычного оружия носителя нет — сборка та же, что и была."""
        seen, asked, _ = self._load(carrier_model.NONE, ["my_gun"])
        self.assertEqual(seen["extra"], [])
        self.assertEqual(asked["materials"], ["my_gun"])


class ClipOnlyTests(unittest.TestCase):
    """Смена анимации не должна пересобирать сцену целиком."""

    def setUp(self):
        self.session = AppSession()
        self.session._mode = "spy_c_shogun_kunai"

    def _calls(self, *, shown: bool, full: bool = False):
        got = {"load": 0, "clip": 0}

        def _count(key):
            return lambda *a, **k: got.__setitem__(key, got[key] + 1)

        with patch.object(AppSession, "tf2_paths", staticmethod(lambda: PATHS)), \
                patch.object(self.session.viewmodel, "shows", lambda *a: shown), \
                patch.object(self.session.viewmodel, "load", _count("load")), \
                patch.object(self.session.viewmodel, "load_clip", _count("clip")), \
                patch.object(self.session.controller, "stop", lambda: None):
            res = self.session.load_first_person("DRAW", full=full)
        return got, res

    def test_same_scene_gets_only_the_clip(self):
        got, res = self._calls(shown=True)
        self.assertEqual((got["load"], got["clip"]), (0, 1))
        self.assertTrue(res.get("clip_only"))

    def test_new_scene_is_built_whole(self):
        got, res = self._calls(shown=False)
        self.assertEqual((got["load"], got["clip"]), (1, 0))
        self.assertNotIn("clip_only", res)

    def test_full_forces_a_rebuild(self):
        """Отход назад для страницы: дорожки не легли — собрать целиком.

        Без флага мы бы снова ответили дорожками, и страница ходила бы по
        кругу: сцены в кадре нет, а ей всё шлют кадры для неё.
        """
        got, _ = self._calls(shown=True, full=True)
        self.assertEqual((got["load"], got["clip"]), (1, 0))


if __name__ == "__main__":
    unittest.main()
