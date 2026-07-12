"""Тесты PreviewTextureState — единого источника правды о текстурах превью.

Фиксируют правила маршрутизации и разрешения, из-за нарушения которых раньше
случались рассинхроны 2D↔3D (затирание команды, потеря стиля, австралий).
"""

import tempfile
import unittest
from pathlib import Path

from src.shared.constants import Team
from src.ui.texture_state import (
    SINGLE_TEX_KEY,
    PreviewTextureState,
    team_priority,
)


class TextureStateBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.state = PreviewTextureState()

    def tearDown(self):
        self._tmp.cleanup()

    def png(self, name: str) -> str:
        """Создаёт файл-заглушку и возвращает путь (resolve проверяет exists)."""
        p = self.dir / f"{name}.png"
        p.write_bytes(b"x")
        return str(p)


class TeamPriorityTests(unittest.TestCase):
    def test_active_team_first(self):
        self.assertEqual(team_priority(Team.RED), [Team.RED, Team.BLU])
        self.assertEqual(team_priority(Team.BLU), [Team.BLU, Team.RED])


class NeutralityTests(TextureStateBase):
    def test_no_team_data_is_neutral(self):
        self.assertTrue(self.state.is_neutral("sniper_lens"))

    def test_name_map_marks_team_materials(self):
        self.state.blu_name_map = {"medic_red": "medic_blue"}
        self.assertFalse(self.state.is_neutral("medic_red"))
        self.assertFalse(self.state.is_neutral("medic_blue"))
        self.assertTrue(self.state.is_neutral("sniper_lens"))

    def test_single_blu_frame_makes_main_team_specific(self):
        # Одно-текстурное командное оружие: BLU одним кадром, маппинга нет.
        self.state.material_names = ["c_gun"]
        self.state.blu_frames = [self.png("blu_frame")]
        self.assertFalse(self.state.is_neutral("c_gun"))
        self.assertFalse(self.state.is_neutral(SINGLE_TEX_KEY))
        self.assertTrue(self.state.is_neutral("c_gun_extra"))

    def test_is_team_material(self):
        self.state.blu_name_map = {"hands_red": "hands_blue", "handL": "handL"}
        self.assertTrue(self.state.is_team_material("hands_red"))
        self.assertFalse(self.state.is_team_material("handL"))     # синее имя то же
        self.assertFalse(self.state.is_team_material("no_map_mat"))

    def test_is_team_material_via_blu_frames(self):
        # Без маппинга: главный материал командный, если есть BLU-кадр.
        self.state.material_names = ["balloon", "strap"]
        self.assertFalse(self.state.is_team_material("balloon"))
        self.state.blu_frames = [self.png("blu_frame")]
        self.assertTrue(self.state.is_team_material("balloon"))
        self.assertTrue(self.state.is_team_material(SINGLE_TEX_KEY))
        self.assertFalse(self.state.is_team_material("strap"))   # доп. слот нейтрален


class SetTextureTests(TextureStateBase):
    def test_neutral_written_to_both_teams(self):
        p = self.png("lens")
        self.state.set_texture("sniper_lens", p)
        self.assertEqual(self.state.textures[Team.RED]["sniper_lens"], p)
        self.assertEqual(self.state.textures[Team.BLU]["sniper_lens"], p)

    def test_team_material_written_to_active_team_only(self):
        self.state.blu_name_map = {"medic_red": "medic_blue"}
        p = self.png("red_tex")
        self.state.set_texture("medic_red", p)
        self.assertEqual(self.state.textures[Team.RED]["medic_red"], p)
        self.assertNotIn("medic_red", self.state.textures[Team.BLU])

    def test_teams_do_not_stomp_each_other_with_blu_frames(self):
        # Регресс-кейс: одно-текстурное командное оружие, загрузка на BLU
        # не должна затирать RED.
        self.state.material_names = ["c_gun"]
        self.state.blu_frames = [self.png("blu_frame")]
        red = self.png("red")
        blu = self.png("blu")
        self.state.set_texture("c_gun", red)
        self.state.active_team = Team.BLU
        self.state.set_texture("c_gun", blu)
        self.assertEqual(self.state.textures[Team.RED]["c_gun"], red)
        self.assertEqual(self.state.textures[Team.BLU]["c_gun"], blu)

    def test_variant_skin_routes_to_overrides(self):
        self.state.skin_info = {"num_skins": 2}
        self.state.active_skin = 1
        p = self.png("bloody")
        self.state.set_texture("blade", p)
        self.assertEqual(self.state.skin_overrides[1]["blade"], p)
        self.assertNotIn("blade", self.state.textures[Team.RED])

    def test_clear_removes_from_both_teams_for_neutral(self):
        p = self.png("lens")
        self.state.set_texture("sniper_lens", p)
        self.state.set_texture("sniper_lens", None)
        self.assertNotIn("sniper_lens", self.state.textures[Team.RED])
        self.assertNotIn("sniper_lens", self.state.textures[Team.BLU])

    def test_clear_skin_override(self):
        self.state.skin_info = {"num_skins": 2}
        self.state.active_skin = 1
        self.state.set_texture("blade", self.png("bloody"))
        self.state.set_texture("blade", None)
        self.assertNotIn("blade", self.state.skin_overrides[1])


class ResolveTests(TextureStateBase):
    def test_user_texture_of_active_team_wins(self):
        p = self.png("user")
        self.state.vpk_red_tex_map = {"mat": self.png("game")}
        self.state.set_texture("mat", p)
        self.assertEqual(self.state.resolve_base("mat"), p)

    def test_neutral_falls_back_to_other_team(self):
        p = self.png("user")
        self.state.textures[Team.BLU]["mat"] = p     # загружена только в BLU
        self.assertEqual(self.state.resolve_base("mat"), p)

    def test_team_specific_does_not_leak_between_teams(self):
        self.state.blu_name_map = {"mat": "mat_blue"}
        self.state.textures[Team.BLU]["mat"] = self.png("blu_only")
        self.assertIsNone(self.state.resolve_base("mat"))   # RED не видит BLU

    def test_vpk_original_fallback_per_team(self):
        red_g = self.png("red_game")
        blu_g = self.png("blu_game")
        self.state.vpk_red_tex_map = {"mat": red_g}
        self.state.vpk_blu_tex_map = {"mat": blu_g}
        self.assertEqual(self.state.resolve_base("mat"), red_g)
        self.state.active_team = Team.BLU
        self.assertEqual(self.state.resolve_base("mat"), blu_g)

    def test_blu_shows_red_original_for_neutral(self):
        red_g = self.png("red_game")
        self.state.vpk_red_tex_map = {"misc_mat": red_g}
        self.state.active_team = Team.BLU
        self.assertEqual(self.state.resolve_base("misc_mat"), red_g)

    def test_main_material_frame_fallback(self):
        self.state.material_names = ["c_gun"]
        red_f = self.png("red_frame")
        blu_f = self.png("blu_frame")
        self.state.red_frames = [red_f]
        self.state.blu_frames = [blu_f]
        self.assertEqual(self.state.resolve_base("c_gun"), red_f)
        self.state.active_team = Team.BLU
        self.assertEqual(self.state.resolve_base("c_gun"), blu_f)

    def test_multimaterial_hat_blu_frame_beats_red_original(self):
        # Регресс-кейс «A head full of hot air»: мульти-материальная шапка,
        # per-material RED-оригиналы в vpk_red_tex_map, BLU одним кадром.
        # Раньше на BLU главный материал показывал RED-оригинал (fallback для
        # «нейтральных»), хотя 3D показывал синий кадр.
        self.state.material_names = ["balloon", "strap"]
        red_balloon = self.png("red_balloon")
        red_strap = self.png("red_strap")
        blu_f = self.png("blu_frame")
        self.state.vpk_red_tex_map = {"balloon": red_balloon, "strap": red_strap}
        self.state.blu_frames = [blu_f]

        self.state.active_team = Team.BLU
        self.assertEqual(self.state.resolve_base("balloon"), blu_f)
        # Доп. материал нейтрален — RED-оригинал (единственный) остаётся.
        self.assertEqual(self.state.resolve_base("strap"), red_strap)
        # На RED — свои оригиналы, как раньше.
        self.state.active_team = Team.RED
        self.assertEqual(self.state.resolve_base("balloon"), red_balloon)

    def test_user_red_does_not_leak_to_blu_with_blu_frame(self):
        # Пользовательская RED-текстура главного материала не должна
        # показываться на BLU (материал командный из-за blu_frames).
        self.state.material_names = ["balloon"]
        blu_f = self.png("blu_frame")
        self.state.blu_frames = [blu_f]
        self.state.textures[Team.RED]["balloon"] = self.png("user_red")
        self.state.active_team = Team.BLU
        self.assertEqual(self.state.resolve_base("balloon"), blu_f)

    def test_missing_file_is_skipped(self):
        self.state.textures[Team.RED]["mat"] = str(self.dir / "deleted.png")
        self.assertIsNone(self.state.resolve_base("mat"))

    def test_resolve_card_variant_skin_shows_only_override(self):
        self.state.skin_info = {"num_skins": 2}
        self.state.textures[Team.RED]["blade"] = self.png("base")
        self.state.active_skin = 1
        self.assertIsNone(self.state.resolve_card("blade"))   # нет переопределения
        p = self.png("bloody")
        self.state.skin_overrides[1] = {"blade": p}
        self.assertEqual(self.state.resolve_card("blade"), p)

    def test_resolve_card_hands_blu_neutral_empty_until_blue_set(self):
        self.state.blu_name_map = {"handL": "handL"}   # нейтральный
        self.state.textures[Team.RED]["handL"] = self.png("red_hand")
        self.state.active_team = Team.BLU
        self.assertIsNone(self.state.resolve_card("handL", hands_blu_view=True))
        blu = self.png("blu_hand")
        self.state.textures[Team.BLU]["handL"] = blu
        self.assertEqual(self.state.resolve_card("handL", hands_blu_view=True), blu)


class BuildOutputsTests(TextureStateBase):
    def test_red_main_no_blu_fallback(self):
        self.state.material_names = ["c_gun"]
        self.state.textures[Team.BLU]["c_gun"] = self.png("blu")
        self.assertIsNone(self.state.red_main())
        red = self.png("red")
        self.state.textures[Team.RED]["c_gun"] = red
        self.assertEqual(self.state.red_main(), red)

    def test_blu_main_prefers_main_slot(self):
        self.state.material_names = ["c_gun"]
        main = self.png("main_blu")
        other = self.png("other_blu")
        self.state.textures[Team.BLU] = {"extra": other, "c_gun": main}
        self.assertEqual(self.state.blu_main(), main)

    def test_uploaded_for_mat_red_name_never_returns_blu(self):
        self.state.blu_name_map = {"medic_red": "medic_blue"}
        self.state.textures[Team.BLU]["medic_red"] = self.png("blu")
        self.assertIsNone(self.state.uploaded_for_mat("medic_red"))

    def test_uploaded_for_mat_blu_name_reverse_lookup(self):
        self.state.blu_name_map = {"medic_red": "medic_blue"}
        blu = self.png("blu")
        self.state.textures[Team.BLU]["medic_red"] = blu
        self.assertEqual(self.state.uploaded_for_mat("medic_blue"), blu)

    def test_uploaded_for_mat_force_team_blue_suffix(self):
        # Force-team: сборка спрашивает '{mat}_blue', BLU хранится под 'mat'.
        blu = self.png("blu")
        self.state.textures[Team.BLU]["shell"] = blu
        self.assertEqual(self.state.uploaded_for_mat("shell_blue"), blu)

    def test_uploaded_for_mat_blue_suffix_direct_base_hit(self):
        # '{mat}_blue' → прямой хит по базе textures[BLU][mat].
        self.state.material_names = ["c_gun"]
        main_blu = self.png("main_blu")
        self.state.textures[Team.BLU]["c_gun"] = main_blu
        self.assertEqual(self.state.uploaded_for_mat("c_gun_blue"), main_blu)

    def test_uploaded_for_mat_blue_suffix_falls_back_to_main_blu(self):
        # Базы под именем нет → fallback на главную BLU (одноматериальный
        # случай: BLU хранится под SINGLE_TEX_KEY).
        main_blu = self.png("main_blu")
        self.state.textures[Team.BLU][SINGLE_TEX_KEY] = main_blu
        self.assertEqual(self.state.uploaded_for_mat("somemat_blue"), main_blu)

    def test_slot_paths_skip_single_key_and_prefer_active_team(self):
        red = self.png("red")
        blu = self.png("blu")
        self.state.textures[Team.RED] = {"mat": red, SINGLE_TEX_KEY: red}
        self.state.textures[Team.BLU] = {"mat": blu}
        self.assertEqual(self.state.uploaded_slot_paths(), {"mat": red})
        self.state.active_team = Team.BLU
        self.assertEqual(self.state.uploaded_slot_paths(), {"mat": blu})

    def test_blu_uploaded_paths(self):
        blu = self.png("blu")
        self.state.textures[Team.BLU] = {"mat": blu, SINGLE_TEX_KEY: blu,
                                         "gone": str(self.dir / "gone.png")}
        self.assertEqual(self.state.blu_uploaded_paths(), {"mat": blu})


class VariantTests(TextureStateBase):
    def test_inactive_variant_returns_none(self):
        self.state.australium_frame = self.png("gold")
        self.assertIsNone(self.state.variant_display_texture())

    def test_active_variant_prefers_user_texture(self):
        gold = self.png("gold")
        user = self.png("user_gold")
        self.state.australium_frame = gold
        self.state.australium_active = True
        self.assertEqual(self.state.variant_display_texture(), gold)
        self.state.australium_user_tex = user
        self.assertEqual(self.state.variant_display_texture(), user)

    def test_missing_user_texture_falls_back_to_frame(self):
        gold = self.png("gold")
        self.state.australium_frame = gold
        self.state.australium_user_tex = str(self.dir / "deleted.png")
        self.state.australium_active = True
        self.assertEqual(self.state.variant_display_texture(), gold)


class SnapshotTests(TextureStateBase):
    def _filled_state(self) -> PreviewTextureState:
        s = self.state
        s.set_texture("mat", self.png("tex"))
        s.material_names = ["mat", "extra"]
        s.main_material = "mat"
        s.active_team = Team.BLU
        s.blu_name_map = {"mat": "mat_blue"}
        s.vpk_red_tex_map = {"mat": self.png("red_g")}
        s.vpk_blu_tex_map = {"mat": self.png("blu_g")}
        s.red_frames = [self.png("rf")]
        s.blu_frames = [self.png("bf")]
        s.australium_frame = self.png("gold")
        s.australium_mat_name = "gold_mat"
        s.australium_user_tex = self.png("user_gold")
        s.australium_active = True
        return s

    def test_snapshot_restore_roundtrip(self):
        s = self._filled_state()
        snap = s.snapshot()
        fresh = PreviewTextureState()
        fresh.restore(snap)
        self.assertEqual(fresh.textures, s.textures)
        self.assertEqual(fresh.material_names, s.material_names)
        self.assertEqual(fresh.main_material, s.main_material)
        self.assertEqual(fresh.active_team, s.active_team)
        self.assertEqual(fresh.blu_name_map, s.blu_name_map)
        self.assertEqual(fresh.vpk_red_tex_map, s.vpk_red_tex_map)
        self.assertEqual(fresh.vpk_blu_tex_map, s.vpk_blu_tex_map)
        self.assertEqual(fresh.red_frames, s.red_frames)
        self.assertEqual(fresh.blu_frames, s.blu_frames)
        self.assertEqual(fresh.australium_frame, s.australium_frame)
        self.assertEqual(fresh.australium_mat_name, s.australium_mat_name)
        self.assertEqual(fresh.australium_user_tex, s.australium_user_tex)
        # Австралий после восстановления всегда выключен.
        self.assertFalse(fresh.australium_active)

    def test_snapshot_is_deep_copy(self):
        s = self._filled_state()
        snap = s.snapshot()
        s.textures[Team.RED]["mat"] = "changed"
        s.material_names.append("new")
        self.assertNotEqual(snap['textures'][Team.RED].get("mat"), "changed")
        self.assertNotIn("new", snap['material_names'])

    def test_restore_from_partial_snapshot_uses_defaults(self):
        self.state.restore({})
        self.assertEqual(self.state.textures, {})
        self.assertEqual(self.state.active_team, Team.RED)
        self.assertIsNone(self.state.australium_frame)
        self.assertFalse(self.state.australium_active)

    def test_restore_resets_stale_skin_state(self):
        # Залипший вариантный стиль не должен пережить восстановление —
        # иначе карточки оружия резолвились бы в чужие override'ы.
        self.state.skin_info = {"num_skins": 2}
        self.state.active_skin = 1
        self.state.skin_overrides = {1: {"mat": "p"}}
        self.state.restore(PreviewTextureState().snapshot())
        self.assertIsNone(self.state.skin_info)
        self.assertEqual(self.state.active_skin, 0)
        self.assertEqual(self.state.skin_overrides, {})


class ResetTests(TextureStateBase):
    def test_reset_skins(self):
        self.state.skin_info = {"num_skins": 2}
        self.state.active_skin = 1
        self.state.skin_overrides = {1: {"mat": "p"}}
        self.state.reset_skins()
        self.assertIsNone(self.state.skin_info)
        self.assertEqual(self.state.active_skin, 0)
        self.assertEqual(self.state.skin_overrides, {})

    def test_reset_team_data(self):
        self.state.red_frames = ["r"]
        self.state.blu_frames = ["b"]
        self.state.vpk_red_tex_map = {"m": "p"}
        self.state.vpk_blu_tex_map = {"m": "p"}
        self.state.blu_name_map = {"a": "b"}
        self.state.active_team = Team.BLU
        self.state.reset_team_data()
        self.assertEqual(self.state.red_frames, [])
        self.assertEqual(self.state.blu_frames, [])
        self.assertEqual(self.state.vpk_red_tex_map, {})
        self.assertEqual(self.state.vpk_blu_tex_map, {})
        self.assertEqual(self.state.blu_name_map, {})
        self.assertEqual(self.state.active_team, Team.RED)

    def test_reset_australium(self):
        self.state.australium_frame = "f"
        self.state.australium_active = True
        self.state.australium_user_tex = "u"
        self.state.australium_mat_name = "gold"
        self.state.reset_australium()
        self.assertIsNone(self.state.australium_frame)
        self.assertFalse(self.state.australium_active)
        self.assertIsNone(self.state.australium_user_tex)
        self.assertIsNone(self.state.australium_mat_name)

    def test_stable_main_prefers_main_material(self):
        self.state.material_names = ["misc_swapped"]   # режим «Прочее»
        self.state.main_material = "c_gun"
        self.assertEqual(self.state.stable_main(), "c_gun")
        self.state.main_material = None
        self.assertEqual(self.state.stable_main(), "misc_swapped")

    def test_storage_main_key_falls_back_to_sentinel(self):
        self.assertEqual(self.state.storage_main_key(), SINGLE_TEX_KEY)
        self.state.material_names = ["c_gun"]
        self.assertEqual(self.state.storage_main_key(), "c_gun")


class ForceTeamTests(TextureStateBase):
    """«Сделать командным» (+ Команда) для оружия без нативной команды.

    Регрессия: у такого оружия нет blu_name_map/blu_frames → материал считается
    нейтральным, и set_texture дублировал загрузку в ОБЕ команды. Из-за этого
    загрузка BLU затирала RED, и 2D/3D показывали одинаковые текстуры.
    """

    def setUp(self):
        super().setUp()
        self.state.material_names = ["c_gun"]
        self.state.force_team = True

    def test_blu_upload_does_not_overwrite_red(self):
        red = self.png("red")
        blu = self.png("blu")
        # Загружаем RED, затем переключаемся на BLU и загружаем ДРУГУЮ текстуру.
        self.state.active_team = Team.RED
        self.state.set_texture("c_gun", red)
        self.state.active_team = Team.BLU
        self.state.set_texture("c_gun", blu)
        # Ключевая проверка: команды РАЗНЫЕ (раньше обе были = blu).
        self.assertEqual(self.state.textures[Team.RED].get("c_gun"), red)
        self.assertEqual(self.state.textures[Team.BLU].get("c_gun"), blu)
        # Резолв каждой команды возвращает свою текстуру.
        self.state.active_team = Team.RED
        self.assertEqual(self.state.resolve_base("c_gun"), red)
        self.state.active_team = Team.BLU
        self.assertEqual(self.state.resolve_base("c_gun"), blu)

    def test_red_only_blu_defaults_to_red(self):
        # Пока своя синяя не задана, BLU наследует RED (дефолт «как RED»).
        red = self.png("red")
        self.state.active_team = Team.RED
        self.state.set_texture("c_gun", red)
        self.assertNotIn("c_gun", self.state.textures[Team.BLU])  # не продублировано
        self.state.active_team = Team.BLU
        self.assertEqual(self.state.resolve_base("c_gun"), red)   # но показывается RED

    def test_without_force_team_dual_write_preserved(self):
        # Контроль: без force_team нейтральная по-прежнему пишется в обе команды.
        self.state.force_team = False
        tex = self.png("t")
        self.state.active_team = Team.RED
        self.state.set_texture("c_gun", tex)
        self.assertEqual(self.state.textures[Team.BLU].get("c_gun"), tex)

    def test_uploaded_for_mat_blue_defaults_to_red_under_force_team(self):
        # Сборка синего скина: своей синей нет → берём базовую RED («как RED»),
        # иначе {mat}_blue остался бы без VTF (фиолетовый в игре).
        red = self.png("red")
        self.state.active_team = Team.RED
        self.state.set_texture("c_gun", red)
        self.assertEqual(self.state.uploaded_for_mat("c_gun_blue"), red)

    def test_uploaded_for_mat_blue_prefers_own_blue(self):
        red, blu = self.png("red"), self.png("blu")
        self.state.active_team = Team.RED
        self.state.set_texture("c_gun", red)
        self.state.active_team = Team.BLU
        self.state.set_texture("c_gun", blu)
        # Своя синяя задана → она приоритетнее RED-дефолта.
        self.assertEqual(self.state.uploaded_for_mat("c_gun_blue"), blu)

    def test_reset_team_data_clears_force_team(self):
        self.assertTrue(self.state.force_team)
        self.state.reset_team_data()
        self.assertFalse(self.state.force_team)

    def test_snapshot_restore_roundtrips_force_team(self):
        red, blu = self.png("red"), self.png("blu")
        self.state.active_team = Team.RED
        self.state.set_texture("c_gun", red)
        self.state.active_team = Team.BLU
        self.state.set_texture("c_gun", blu)
        snap = self.state.snapshot()
        fresh = PreviewTextureState()
        fresh.restore(snap)
        self.assertTrue(fresh.force_team)
        self.assertEqual(fresh.textures[Team.RED].get("c_gun"), red)
        self.assertEqual(fresh.textures[Team.BLU].get("c_gun"), blu)


class SkyboxStateTests(TextureStateBase):
    def test_resolve_priority_user_over_split_over_stock(self):
        user = self.png("user_up")
        split = self.png("split_up")
        stock = self.png("stock_up")
        self.state.skybox_stock_faces = {"up": stock}
        self.assertEqual(self.state.resolve_skybox_face("up"), stock)
        self.state.skybox_split_faces = {"up": split}
        self.assertEqual(self.state.resolve_skybox_face("up"), split)
        self.state.set_texture("up", user)
        self.assertEqual(self.state.resolve_skybox_face("up"), user)

    def test_resolve_skips_missing_files(self):
        self.state.skybox_split_faces = {"up": str(self.dir / "gone.png")}
        stock = self.png("stock_up2")
        self.state.skybox_stock_faces = {"up": stock}
        self.assertEqual(self.state.resolve_skybox_face("up"), stock)

    def test_build_data_contains_pano_and_overrides_only(self):
        from src.data.skyboxes import SKY_PANO_KEY
        pano = self.png("pano")
        face = self.png("face_lf")
        split = self.png("split_lf")
        self.state.set_texture(SKY_PANO_KEY, pano)
        self.state.set_texture("lf", face)
        self.state.skybox_split_faces = {"rt": split}   # нарезка НЕ в сборку
        data = self.state.skybox_build_data()
        self.assertEqual(data["equirect"], pano)
        self.assertEqual(data["face_overrides"], {"lf": face})

    def test_reset_skybox_clears_derived_but_keeps_user(self):
        face = self.png("face_up")
        self.state.set_texture("up", face)
        self.state.skybox_stock_faces = {"up": self.png("stock_up3")}
        self.state.skybox_split_faces = {"up": self.png("split_up3")}
        self.state.reset_skybox()
        self.assertEqual(self.state.skybox_stock_faces, {})
        self.assertEqual(self.state.skybox_split_faces, {})
        # Пользовательская грань живёт в textures — её чистит общий сброс.
        self.assertEqual(self.state.resolve_skybox_face("up"), face)


if __name__ == "__main__":
    unittest.main()
