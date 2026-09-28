import unittest

from src.data.vmt_snippets import (
    VMT_PARAM_DOCS,
    VMT_PARAM_DOCS_EN,
    param_doc,
    all_param_names,
)


class VmtSnippetsTests(unittest.TestCase):
    def test_en_and_ru_docs_cover_same_params(self):
        # Английский и русский словари должны описывать одни и те же параметры —
        # иначе тултип пропадёт при смене языка.
        self.assertEqual(set(VMT_PARAM_DOCS), set(VMT_PARAM_DOCS_EN))

    def test_param_doc_selects_language(self):
        self.assertEqual(param_doc("$basetexture", "en"), VMT_PARAM_DOCS_EN["$basetexture"])
        self.assertEqual(param_doc("$basetexture", "ru"), VMT_PARAM_DOCS["$basetexture"])

    def test_param_doc_defaults_to_english(self):
        # Английская версия приложения не должна получать русские подсказки.
        self.assertEqual(param_doc("$phong"), VMT_PARAM_DOCS_EN["$phong"])
        self.assertNotEqual(param_doc("$phong", "en"), VMT_PARAM_DOCS["$phong"])

    def test_param_doc_unknown_returns_empty(self):
        self.assertEqual(param_doc("$definitely_not_a_param", "en"), "")
        self.assertEqual(param_doc("", "ru"), "")

    def test_all_param_names_sorted_and_complete(self):
        names = all_param_names()
        self.assertEqual(names, sorted(VMT_PARAM_DOCS.keys()))


if __name__ == "__main__":
    unittest.main()


def test_australium_snippet_matches_valve_gold_vmts():
    """Набор — общий у c_*_gold.vmt Valve: золотая кубмапа, ровный phong,
    лайтварп оружия, маска блеска в альфе. Мешающие ключи гасятся слиянием."""
    from src.data.vmt_snippets import VMT_MERGE_REMOVES, VMT_SNIPPETS
    label = "Австралий — золотой металл"
    snippet = next(sn for lb, sn, _ in VMT_SNIPPETS["Эффекты"] if lb == label)
    for key in ('"$envmap" "cubemaps/cubemap_gold001"', '"$envmaptint" "[2.5 2.5 1.15]"',
                '"$phongexponent"', '"$basemapalphaphongmask" "1"',
                '"$lightwarptexture" "models/lightwarps/weapon_lightwarp"'):
        assert key in snippet
    assert "$phongexponenttexture" in VMT_MERGE_REMOVES[label]


def test_reference_keys_are_lowercase_params():
    """Ключи справочника — имена в нижнем регистре: так их ищут подсказки."""
    from src.data.vmt_snippets import VMT_PARAM_DOCS
    for name in VMT_PARAM_DOCS:
        assert name.startswith("$") and name == name.lower(), name


def test_param_doc_ignores_case():
    """В VMT игры пишут и $cloakPassEnabled — подсказка не должна пропадать."""
    from src.data.vmt_snippets import VMT_PARAM_DOCS, param_doc
    assert param_doc("$cloakPassEnabled", "ru") == VMT_PARAM_DOCS["$cloakpassenabled"]


def test_every_menu_entry_has_english():
    """Меню «Готовые эффекты» на английском не должно остаться русским."""
    from src.data.vmt_snippets import VMT_SNIPPETS, VMT_SNIPPETS_EN
    for category, items in VMT_SNIPPETS.items():
        assert category in VMT_SNIPPETS_EN, category
        for label, _, _ in items:
            assert isinstance(VMT_SNIPPETS_EN.get(label), tuple), label


def test_param_reference_keeps_group_order():
    from src.data.vmt_snippets import VMT_PARAM_GROUPS, param_reference
    ref = param_reference("en")
    assert [g["group"] for g in ref] == [g_en for _, g_en, _ in VMT_PARAM_GROUPS]
    assert ref[0]["params"][0]["param"] == "$basetexture"
