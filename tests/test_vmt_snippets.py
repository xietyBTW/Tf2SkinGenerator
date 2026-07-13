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
