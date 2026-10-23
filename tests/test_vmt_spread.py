"""
Правка VMT во все материалы предмета (без шестерёнки)

Остальным материалам уходит не текст, а разбор правки: эффекты собираются
в каждом заново, ключи - без путей текстур, ключи вложенных блоков не трогаются
"""

import unittest
from types import SimpleNamespace

from src.app.materials_editor import MaterialsEditor
from src.services import vmt_effects as fx
from src.services import vmt_spread as vs

GAME = '''"VertexLitGeneric"
{
\t"$basetexture" "models/weapons/a"
\t"$phong" "1"
\t"$phongboost" "6"
\t">=DX90"
\t{
\t\t"$phongboost" "9"
\t}
\t"Proxies"
\t{
\t\t"AnimatedWeaponSheen"
\t\t{
\t\t\t"animatedtexturevar" "$sheenmapmask"
\t\t}
\t}
}
'''
OTHER = GAME.replace("models/weapons/a", "models/weapons/b")
SHEEN = {"color": "#ff0000", "bright": 1, "when": "game", "pattern": "game"}


class PlanTests(unittest.TestCase):
    def test_keys_move_but_texture_paths_stay(self):
        after = (GAME.replace('"$phongboost" "6"', '"$phongboost" "2"\n\t"$rimlight" "1"', 1)
                 .replace("models/weapons/a", "models/weapons/zzz")
                 .replace('\t"$phong" "1"\n', ''))
        text, problems = vs.apply_plan(vs.plan(GAME, after, GAME), OTHER, OTHER)
        self.assertEqual(problems, [])
        keys = vs.top_keys(text)
        self.assertEqual(keys["$basetexture"][1], '"models/weapons/b"')   # свой путь цел
        self.assertEqual(keys["$phongboost"][1], '"2"')
        self.assertEqual(keys["$rimlight"][1], '"1"')
        self.assertNotIn("$phong", keys)
        # Ключ во вложенном блоке - не корень, его правка не трогает
        self.assertIn('\t\t"$phongboost" "9"', text)

    def test_effect_is_rebuilt_from_the_other_materials_text(self):
        after = fx.apply(fx.SHEEN, SHEEN, GAME, GAME)["text"]
        plan = vs.plan(GAME, after, GAME)
        self.assertEqual([k for k, _v in plan.effects], [fx.SHEEN])
        self.assertEqual(plan.keys, {})          # всё, что дал эффект, - не ручное
        text, _ = vs.apply_plan(plan, OTHER, OTHER)
        self.assertTrue(fx.present(fx.SHEEN, text))
        self.assertEqual(fx.values(fx.SHEEN, text)["color"], "#ff0000")
        self.assertIn("models/weapons/b", text)
        self.assertEqual(text.count("// tf2sg sheen"), 1)

    def test_unchanged_effect_is_not_reapplied(self):
        with_fx = fx.apply(fx.SHEEN, SHEEN, GAME, GAME)["text"]
        plan = vs.plan(with_fx, with_fx.replace('"$phongboost" "6"', '"$phongboost" "3"', 1), GAME)
        self.assertEqual(plan.effects, [])
        self.assertEqual(plan.keys, {"$phongboost": '"3"'})

    def test_effect_that_does_not_fit_is_reported(self):
        no_sheen = GAME[:GAME.index('\t"Proxies"')] + "}\n"
        after = fx.apply(fx.SHEEN, SHEEN, GAME, GAME)["text"]
        text, problems = vs.apply_plan(vs.plan(GAME, after, GAME), no_sheen, no_sheen)
        self.assertEqual(len(problems), 1)
        self.assertEqual(text, no_sheen)

    def test_what_cannot_move_is_named(self):
        manual = GAME.replace('"animatedtexturevar"', '"animatedtextureframerate" "10"\n\t\t\t"animatedtexturevar"')
        self.assertEqual(vs.plan(GAME, manual, GAME).notes, ["proxies"])
        with_fx = fx.apply(fx.SHEEN, SHEEN, GAME, GAME)["text"]
        self.assertIn("effect_removed", vs.plan(with_fx, GAME, GAME).notes)

    def test_nothing_changed_is_an_empty_plan(self):
        self.assertTrue(vs.plan(GAME, GAME, GAME).empty)


class SaveAllTests(unittest.TestCase):
    """Сохранение без шестерёнки: какие материалы и как получают правку"""

    def setUp(self):
        self.store = {"a": GAME, "b": OTHER, "c": OTHER.replace("weapons/b", "weapons/c")}
        ed = MaterialsEditor.__new__(MaterialsEditor)
        ed.vmt_target = lambda m: ("w", m) if m in self.store else {"error": "нет"}
        ed.open_vmt = lambda m, lang="ru": {"material": m, "content": self.store[m],
                                            "original": GAME}
        ed.save_vmt = self._save
        self.ed = ed

    def _save(self, material, content, original="", lang="ru"):
        self.store[material] = content
        return {"material": material, "content": content, "edited": True}

    def test_edit_reaches_every_other_material(self):
        after = GAME.replace('"$phongboost" "6"', '"$phongboost" "1"', 1)
        res = self.ed.save_vmt_all("a", after, GAME, GAME, ["a", "b", "c", "zz"])
        self.assertEqual(res["spread"]["updated"], ["b", "c"])
        self.assertEqual(vs.top_keys(self.store["c"])["$phongboost"][1], '"1"')
        self.assertIn("weapons/c", self.store["c"])

    def test_untouched_materials_are_not_rewritten(self):
        res = self.ed.save_vmt_all("a", GAME, GAME, GAME, ["a", "b"])
        self.assertEqual(res["spread"]["updated"], [])


if __name__ == "__main__":
    unittest.main()
