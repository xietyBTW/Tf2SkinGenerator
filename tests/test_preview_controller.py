"""Тесты Preview3DController: сигналы воркера → состояние сессии → события.

Проверяют ровно ту границу, ради которой контроллер появился: к моменту, когда
подписчик получает событие, сессия уже обновлена. Qt здесь не нужен.
"""

import unittest
from unittest.mock import Mock, patch

from src.app.preview_controller import (
    Preview3DController,
    split_blu_multi_material,
)
from src.domain.preview.session import PreviewSession
from src.services.base_worker import BaseWorker, Signal
from src.shared.constants import Team


class _FakeWorker(BaseWorker):
    """Подставной Preview3DWorker: те же сигналы, но ничего не делает."""

    progress = Signal(str)
    ready = Signal(str, str)
    animated = Signal(object, float)
    multi_material = Signal(object)
    blu_ready = Signal(object, float)
    blu_multi_material = Signal(object)
    blu_same_as_red = Signal()
    australium_ready = Signal(str, str)
    render_hints = Signal(object)
    failed = Signal(str)

    def __init__(self, **kwargs):
        super().__init__()
        self.kwargs = kwargs
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self, timeout_ms=5000):
        self.stopped = True
        return True

    def isRunning(self):
        return self.started and not self.stopped


def _controller():
    return Preview3DController(PreviewSession())


class SplitBluPayloadTests(unittest.TestCase):
    """Воркер шлёт то пару, то один словарь — разбор должен пережить оба."""

    def test_pair(self):
        tex, names = split_blu_multi_material(({"a": "a.png"}, {"a": "a_blue"}))
        self.assertEqual(tex, {"a": "a.png"})
        self.assertEqual(names, {"a": "a_blue"})

    def test_bare_dict_is_textures(self):
        tex, names = split_blu_multi_material({"a": "a.png"})
        self.assertEqual(tex, {"a": "a.png"})
        self.assertEqual(names, {})

    def test_empty_and_none(self):
        for payload in (None, {}, ()):
            self.assertEqual(split_blu_multi_material(payload), ({}, {}))

    def test_result_is_a_copy(self):
        """Словари воркера не должны утечь в сессию по ссылке."""
        src = {"a": "a.png"}
        tex, _ = split_blu_multi_material((src, {}))
        tex["b"] = "b.png"
        self.assertNotIn("b", src)


class ReadyTests(unittest.TestCase):
    def test_session_updated_before_event(self):
        """Подписчик обязан увидеть уже обновлённую сессию, а не гонку."""
        c = _controller()
        seen = {}
        c.model_ready.connect(
            lambda obj, tex: seen.update(
                team=c._session.textures.active_team,
                frames=list(c._session.textures.red_frames),
                cur=c._session.current_object,
            ))
        c._on_ready("m.obj", "t.png", "scout_c_scattergun")
        self.assertEqual(seen["team"], Team.RED)
        self.assertEqual(seen["frames"], ["t.png"])
        self.assertEqual(seen["cur"], ("scout_c_scattergun", "m.obj", "t.png"))

    def test_clears_per_mesh_edits_of_previous_model(self):
        c = _controller()
        c._session.per_mesh_active = True
        c._session.per_mesh_base_image = "old.png"
        c._on_ready("m.obj", "t.png", "mode")
        self.assertFalse(c._session.per_mesh_active)
        self.assertIsNone(c._session.per_mesh_base_image)

    def test_empty_texture_keeps_frames_untouched(self):
        c = _controller()
        c._session.textures.red_frames = ["kept.png"]
        c._on_ready("m.obj", "", "mode")
        self.assertEqual(c._session.textures.red_frames, ["kept.png"])


class AnimatedTests(unittest.TestCase):
    def test_records_frames_and_framerate(self):
        c = _controller()
        c._on_animated(["a.png", "b.png"], 15.0)
        self.assertEqual(c._session.textures.red_frames, ["a.png", "b.png"])
        self.assertEqual(c._session.team_framerate, 15.0)

    def test_empty_frames_are_ignored(self):
        c = _controller()
        fired = Mock()
        c.animated.connect(fired)
        c._on_animated([], 15.0)
        fired.assert_not_called()
        self.assertEqual(c._session.team_framerate, 0.0)


class BluTests(unittest.TestCase):
    def test_zero_framerate_does_not_clobber_rate_from_red(self):
        """Нулевая частота у BLU значит «кадр один», а не «сбрось скорость»."""
        c = _controller()
        c._session.team_framerate = 15.0
        c._on_blu_ready(["b.png"], 0.0)
        self.assertEqual(c._session.team_framerate, 15.0)
        self.assertEqual(c._session.textures.blu_frames, ["b.png"])

    def test_positive_framerate_wins(self):
        c = _controller()
        c._session.team_framerate = 15.0
        c._on_blu_ready(["b.png"], 30.0)
        self.assertEqual(c._session.team_framerate, 30.0)

    def test_same_as_red_is_remembered(self):
        c = _controller()
        c._on_blu_same_as_red()
        self.assertTrue(c._session.blu_matches_red)

    def test_name_map_recorded_without_textures(self):
        """Подписи карточек нужны даже когда синих VTF в VPK не нашлось."""
        c = _controller()
        c._on_blu_multi_material(({}, {"hands": "hands_blue"}))
        self.assertEqual(c._session.textures.blu_name_map, {"hands": "hands_blue"})
        self.assertEqual(c._session.textures.vpk_blu_tex_map, {})


class AustraliumTests(unittest.TestCase):
    """Вариантный кадр (Australium/Festive) должен попасть В СЕССИЮ.

    Кнопка варианта показывается по australium_frame. Пока сигнал воркера
    просто пересылался дальше, состояние о нём не знало — и кнопки не было
    ни у одного оружия, хотя золотой кадр приезжал.
    """

    def test_frame_and_material_are_stored(self):
        c = _controller()
        c._on_australium_ready("gold.png", "c_rocketlauncher_gold")
        self.assertEqual(c._session.textures.australium_frame, "gold.png")
        self.assertEqual(c._session.textures.australium_mat_name,
                         "c_rocketlauncher_gold")

    def test_session_updated_before_event(self):
        c = _controller()
        seen = {}
        c.australium_ready.connect(
            lambda png, mat: seen.update(
                frame=c._session.textures.australium_frame))
        c._on_australium_ready("gold.png", "mat")
        self.assertEqual(seen["frame"], "gold.png")

    def test_empty_path_changes_nothing(self):
        c = _controller()
        fired = Mock()
        c.australium_ready.connect(fired)
        c._on_australium_ready("", "mat")
        self.assertIsNone(c._session.textures.australium_frame)
        fired.assert_not_called()

    def test_worker_signal_reaches_the_session(self):
        c = _controller()
        with patch("src.services.preview_3d_worker.Preview3DWorker", _FakeWorker):
            c.load_game_model("wk", "mode", "misc.vpk", "tex.vpk")
        c._worker.australium_ready.emit("gold.png", "mat")
        self.assertEqual(c._session.textures.australium_frame, "gold.png")


class MultiMaterialTests(unittest.TestCase):
    def test_real_names_replace_the_single_texture_placeholder(self):
        """
        Порядок как у воркера: сначала ready с текстурой, потом материалы.

        В ready ставится служебный ключ на случай одноматериальной модели —
        он ОБЯЗАН уступить настоящим именам, иначе у многоматериальной модели
        в превью осталась бы одна текстура из нескольких.
        """
        from src.domain.preview.texture_state import SINGLE_TEX_KEY

        c = _controller()
        c._on_ready('m.obj', 'texture.png', 'heavy_c_minigun')
        self.assertEqual(c._session.textures.material_names, [SINGLE_TEX_KEY])

        c._on_multi_material({'mat_a': 'a.png', 'mat_b': 'b.png'})
        self.assertEqual(c._session.textures.material_names, ['mat_a', 'mat_b'])
        self.assertNotIn(SINGLE_TEX_KEY, c._session.textures.vpk_red_tex_map)

    def test_single_texture_placeholder_only_when_nothing_else(self):
        """Если материалы уже известны, ready их не подменяет."""
        from src.domain.preview.texture_state import SINGLE_TEX_KEY

        c = _controller()
        c._on_multi_material({'mat_a': 'a.png'})
        c._on_ready('m.obj', 'texture.png', 'mode')
        self.assertEqual(c._session.textures.material_names, ['mat_a'])
        self.assertNotIn(SINGLE_TEX_KEY, c._session.textures.material_names)


    def test_records_red_originals_once(self):
        c = _controller()
        c._on_multi_material({"a": "first.png"})
        c._on_multi_material({"a": "second.png"})
        self.assertEqual(c._session.textures.vpk_red_tex_map, {"a": "first.png"})

    def test_does_not_record_while_on_blu(self):
        """На BLU сюда приходят синие текстуры — они затёрли бы красные."""
        c = _controller()
        c._session.textures.active_team = Team.BLU
        c._on_multi_material({"a": "blue.png"})
        self.assertEqual(c._session.textures.vpk_red_tex_map, {})


class WorkerLifecycleTests(unittest.TestCase):
    def _load(self, c, **kw):
        with patch("src.services.preview_3d_worker.Preview3DWorker", _FakeWorker):
            c.load_game_model("scout_c_scattergun", "mode", "misc.vpk",
                              "tex.vpk", **kw)
        return c._worker

    def test_start_passes_params_and_starts(self):
        c = _controller()
        w = self._load(c, lang="ru")
        self.assertTrue(w.started)
        self.assertEqual(w.kwargs["weapon_key"], "scout_c_scattergun")
        self.assertEqual(w.kwargs["lang"], "ru")

    def test_second_load_stops_the_first(self):
        """Две загрузки разом смешали бы свои сигналы в одной сессии."""
        c = _controller()
        first = self._load(c)
        second = self._load(c)
        self.assertTrue(first.stopped)
        self.assertIsNot(first, second)

    def test_stop_is_safe_without_a_worker(self):
        c = _controller()
        c.stop()
        self.assertFalse(c.is_running)

    def test_worker_signals_reach_controller_events(self):
        c = _controller()
        w = self._load(c)
        got = Mock()
        c.failed.connect(got)
        w.failed.emit("нет модели")
        got.assert_called_once_with("нет модели")

    def test_render_hints_none_becomes_empty(self):
        """Пустой набор тоже доезжает: он сбрасывает свойства прошлой модели."""
        c = _controller()
        w = self._load(c)
        got = Mock()
        c.render_hints.connect(got)
        w.render_hints.emit(None)
        got.assert_called_once_with({})


if __name__ == "__main__":
    unittest.main()
