import tempfile
import unittest
from pathlib import Path

from src.services.smd_service import SMDService


class SMDServiceTests(unittest.TestCase):
    def test_parse_and_merge_triangles(self):
        content = "\n".join([
            "version 1",
            "nodes",
            "0 \"root\" -1",
            "end",
            "skeleton",
            "time 0",
            "0 0 0 0 0 0 0",
            "end",
            "triangles",
            "mat1",
            "0 0 0 0 0 0 0 0 0",
            "0 0 0 0 0 0 0 0 0",
            "0 0 0 0 0 0 0 0 0",
        ])
        parsed = SMDService._parse_smd_file(content)
        self.assertTrue(parsed["version"])
        self.assertTrue(parsed["nodes"])
        self.assertTrue(parsed["skeleton"])
        self.assertEqual(parsed["material_names"], ["mat1"])
        merged = SMDService._merge_triangles(parsed["triangles_data"], ["orig"])
        self.assertIn("orig", merged)

    def test_replace_model_sections(self):
        user_content = "\n".join([
            "version 1",
            "nodes",
            "0 \"user\" -1",
            "end",
            "skeleton",
            "time 0",
            "0 0 0 0 0 0 0",
            "end",
            "triangles",
            "user_mat",
            "0 0 0 0 0 0 0 0 0",
            "0 0 0 0 0 0 0 0 0",
            "0 0 0 0 0 0 0 0 0",
        ])
        original_content = "\n".join([
            "version 1",
            "nodes",
            "0 \"orig\" -1",
            "end",
            "skeleton",
            "time 0",
            "0 0 0 0 0 0 0",
            "end",
            "triangles",
            "orig_mat",
            "0 0 0 0 0 0 0 0 0",
            "0 0 0 0 0 0 0 0 0",
            "0 0 0 0 0 0 0 0 0",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            user_path = base / "user.smd"
            orig_path = base / "orig.smd"
            out_path = base / "out.smd"
            user_path.write_text(user_content, encoding="utf-8")
            orig_path.write_text(original_content, encoding="utf-8")
            result = SMDService.replace_model_sections(str(user_path), str(orig_path), str(out_path))
            self.assertEqual(result, str(out_path))
            output = out_path.read_text(encoding="utf-8")
            self.assertIn("\"orig\"", output)
            self.assertIn("orig_mat", output)

    def test_replace_model_sections_keep_user_materials_lowercases(self):
        # keep_user_materials: имя материала меша сохраняется, но в нижнем
        # регистре (иначе фиолетовые текстуры из-за рассинхрона с группой/файлами).
        user_content = "\n".join([
            "version 1", "nodes", "0 \"user\" -1", "end",
            "skeleton", "time 0", "0 0 0 0 0 0 0", "end",
            "triangles",
            "Material.001",
            "0 0 0 0 0 0 0 0 0",
            "0 0 0 0 0 0 0 0 0",
            "0 0 0 0 0 0 0 0 0",
        ])
        original_content = "\n".join([
            "version 1", "nodes", "0 \"orig\" -1", "end",
            "skeleton", "time 0", "0 0 0 0 0 0 0", "end",
            "triangles", "orig_mat",
            "0 0 0 0 0 0 0 0 0",
            "0 0 0 0 0 0 0 0 0",
            "0 0 0 0 0 0 0 0 0",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            user_path = base / "user.smd"
            orig_path = base / "orig.smd"
            out_path = base / "out.smd"
            user_path.write_text(user_content, encoding="utf-8")
            orig_path.write_text(original_content, encoding="utf-8")
            SMDService.replace_model_sections(
                str(user_path), str(orig_path), str(out_path),
                keep_user_materials=True,
            )
            output = out_path.read_text(encoding="utf-8")
            # lowercase + точка→'_' (studiomdl обрезает имя после точки)
            self.assertIn("material_001", output)
            self.assertNotIn("Material.001", output)     # верхнего регистра нет
            self.assertNotIn("material.001", output)     # точки нет
            self.assertNotIn("orig_mat", output)         # имена пользователя, не игровые

    def test_ordered_unique_materials(self):
        content = "\n".join([
            "version 1", "nodes", "0 \"b\" -1", "end",
            "skeleton", "time 0", "0 0 0 0 0 0 0", "end",
            "triangles",
            "matB", "0 0 0 0 0 0 0 0 0", "0 0 0 0 0 0 0 0 0", "0 0 0 0 0 0 0 0 0",
            "matA", "0 0 0 0 0 0 0 0 0", "0 0 0 0 0 0 0 0 0", "0 0 0 0 0 0 0 0 0",
            "matB", "0 0 0 0 0 0 0 0 0", "0 0 0 0 0 0 0 0 0", "0 0 0 0 0 0 0 0 0",
            "end",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "m.smd"
            p.write_text(content, encoding="utf-8")
            # порядок первого появления, без дублей
            self.assertEqual(SMDService.ordered_unique_materials(str(p)), ["matB", "matA"])

    def test_ordered_unique_materials_missing(self):
        self.assertEqual(SMDService.ordered_unique_materials("/no/file.smd"), [])

    def test_replace_model_sections_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            user_path = base / "user.smd"
            orig_path = base / "orig.smd"
            user_path.write_text("x", encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                SMDService.replace_model_sections(str(user_path), str(orig_path))
    
    def test_replace_model_sections_invalid_smd(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            user_path = base / "user.smd"
            orig_path = base / "orig.smd"
            user_path.write_text("bad", encoding="utf-8")
            orig_path.write_text("bad", encoding="utf-8")
            result = SMDService.replace_model_sections(str(user_path), str(orig_path))
            self.assertEqual(result, str(user_path))
            self.assertEqual(user_path.read_text(encoding="utf-8"), "triangles")

    def test_find_reference_smd(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "weapon_reference.smd").write_text("x", encoding="utf-8")
            found = SMDService.find_reference_smd(str(base), "weapon")
            self.assertTrue(found.endswith("weapon_reference.smd"))
    
    def test_find_reference_smd_fallbacks(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "weapon_anim.smd").write_text("x", encoding="utf-8")
            (base / "weapon_reference_custom.smd").write_text("x", encoding="utf-8")
            found = SMDService.find_reference_smd(str(base), "weapon")
            self.assertTrue(found.endswith("weapon_reference_custom.smd"))
    
    def test_find_reference_smd_non_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "weapon_physics.smd").write_text("x", encoding="utf-8")
            (base / "weapon_anim.smd").write_text("x", encoding="utf-8")
            (base / "weapon_mesh.smd").write_text("x", encoding="utf-8")
            found = SMDService.find_reference_smd(str(base), "weapon")
            self.assertTrue(found.endswith("weapon_mesh.smd"))
    
    def test_merge_triangles_without_original_names(self):
        merged = SMDService._merge_triangles([("mat", ["1 2 3"])], [])
        self.assertIn("mat", merged)
    
    def test_merge_triangles_empty(self):
        merged = SMDService._merge_triangles([], [])
        self.assertEqual(merged.strip(), "triangles")


if __name__ == "__main__":
    unittest.main()


# ── Сопоставление костей по имени ────────────────────────────────────────── #
#
# Сборка берёт таблицу костей из ИГРОВОЙ модели, а из пользовательского SMD
# переносит треугольники. Номера костей у риггера свои, и совпасть с игровыми
# они не могут: порядок в декомпиляции произвольный (у Детонатора weapon_bone,
# weapon_bone_3, weapon_bone_4, weapon_bone_2). Пока переносились номера,
# модель, зарриганная под игровые ИМЕНА, садилась на чужие кости.

def _smd(nodes, tris) -> str:
    lines = ["version 1", "nodes"]
    lines += [f'{i} "{name}" {parent}' for i, name, parent in nodes]
    lines += ["end", "skeleton", "time 0"]
    lines += [f"{i} 0 0 0 0 0 0" for i, _n, _p in nodes]
    lines += ["end", "triangles"]
    for material, verts in tris:
        lines.append(material)
        for bone in verts:
            lines.append(f"{bone} 0 0 0 0 0 1 0.5 0.5 1 {bone} 1.0")
    lines += ["end", ""]
    return "\n".join(lines)


#: Порядок как у Детонатора: угадать его риггер не может.
GAME = _smd([(0, "weapon_bone", -1), (1, "weapon_bone_3", 0),
             (2, "weapon_bone_2", 0)],
            [("c_game", [0, 0, 2])])


def _merge(tmp, user_smd: str) -> list:
    """Строки вершин после слияния."""
    base = Path(tmp)
    (base / "user.smd").write_text(user_smd, encoding="utf-8")
    (base / "game.smd").write_text(GAME, encoding="utf-8")
    SMDService.replace_model_sections(
        str(base / "user.smd"), str(base / "game.smd"), str(base / "out.smd"))
    text = (base / "out.smd").read_text(encoding="utf-8")
    body = text[text.index("triangles"):]
    return [ln.split()[0] for ln in body.splitlines()
            if ln[:1].isdigit() or ln[:1] == "-"]


def test_bones_are_matched_by_name_not_by_number():
    """Кость `weapon_bone_2` у пользователя вторая, а в игре — третья."""
    user = _smd([(0, "weapon_bone", -1), (1, "weapon_bone_2", 0)],
                [("my", [0, 0, 1])])
    with tempfile.TemporaryDirectory() as tmp:
        assert _merge(tmp, user) == ["0", "0", "2"]


def test_unknown_bone_falls_back_to_the_one_carrying_the_mesh():
    """«Только геометрия» из Blender приходит с единственной костью `root`.

    В игровой таблице такой нет, и раньше вершины садились на кость номер
    ноль — а это не всегда хват: у медигана там `weapon_bone_L`, у
    Фалломорфера узел по имени модели, который к руке не крепится.
    """
    user = _smd([(0, "root", -1)], [("my", [0, 0, 0])])
    with tempfile.TemporaryDirectory() as tmp:
        assert _merge(tmp, user) == ["0", "0", "0"]


def _grip(nodes, used_bones):
    lines = [f'{i} "{name}" {parent}\n' for i, name, parent in nodes]
    tris = [("m", [f"{b} 0 0 0 0 0 1 0.5 0.5 1 {b} 1.0\n" for b in used_bones])]
    return SMDService._node_names(lines)[SMDService._grip_bone(lines, tris)]


def test_grip_is_the_topmost_grip_named_bone_the_mesh_uses():
    """У минигана больше всего вершин несёт вращающийся `barrel`.

    Приварить к нему «только геометрию» значило бы раскрутить всю модель.
    """
    assert _grip([(0, "weapon_bone", -1), (1, "barrel", 0)],
                 [0, 1, 1, 1, 1, 1]) == "weapon_bone"


def test_grip_may_be_a_left_hand_bone():
    """У медигана корень — `weapon_bone_L`, и весь меш висит на нём."""
    assert _grip([(0, "weapon_bone_L", -1), (1, "weapon_bone", 0)],
                 [0, 0, 0]) == "weapon_bone_L"


def test_model_named_root_is_not_a_grip():
    """У Фалломорфера корень зовётся по имени модели и к руке не крепится."""
    assert _grip([(0, "c_drg_phlogistinator", -1), (1, "weapon_bone", 0)],
                 [0, 1, 1]) == "weapon_bone"


def test_without_grip_names_the_topmost_used_bone_wins():
    """У Ганслингера костей-хватов нет вовсе, есть только рука."""
    assert _grip([(0, "bip_lowerArm_R", -1), (1, "arm_attach_R", 0)],
                 [1, 1, 1]) == "arm_attach_R"


def test_every_link_of_a_blended_vertex_is_remapped():
    """Вершина может висеть на нескольких костях сразу."""
    mapping = {0: 0, 1: 2}
    line = "1 0 0 0 0 0 1 0.5 0.5 2 1 0.7 0 0.3\n"
    out = SMDService._remap_vertex_line(line, mapping, fallback=0)
    assert out == "2 0 0 0 0 0 1 0.5 0.5 2 2 0.7 0 0.3\n"


def test_line_that_is_not_a_vertex_is_left_alone():
    assert SMDService._remap_vertex_line("мусор\n", {0: 1}, 0) == "мусор\n"
