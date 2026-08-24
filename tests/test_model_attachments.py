"""Разбор точек крепления модели (QC + бинд-поза SMD).

Матрицы — порт мат-библиотеки Source, и ошибка в порядке осей не падает, а
тихо разворачивает эффект в игре: проверяем и математику, и склейку цепочки
костей на маленькой синтетической модели.
"""

import math

from src.services.model_attachments import (
    angle_matrix, attachments_from_qc, concat_transforms, matrix_angles,
    parse_qc_attachments, parse_smd_bind_pose,
)

#: Кость arm висит на root со сдвигом по X и разворотом на 90 градусов по Z
_SMD = """version 1
nodes
  0 "root" -1
  1 "arm" 0
end
skeleton
  time 0
    0 0.000000 0.000000 0.000000 0.000000 0.000000 0.000000
    1 10.000000 0.000000 0.000000 0.000000 0.000000 1.570796
  time 1
    0 99.000000 0.000000 0.000000 0.000000 0.000000 0.000000
    1 99.000000 0.000000 0.000000 0.000000 0.000000 0.000000
end
triangles
end
"""

_QC = """$modelname "test.mdl"
$body studio "test.smd"
$attachment "tip" "arm" 5 0 0 rotate 0 0 0
$attachment "unusual_0" "root" 0 0 20
$attachment "orphan" "nosuchbone" 1 2 3 rotate 10 20 30
"""


def test_angle_matrix_round_trip():
    for angles in [(0, 0, 0), (-90, 0, 0), (38.29, -155.64, 110.31),
                   (0, 133.32, 90)]:
        got = matrix_angles(angle_matrix(*angles))
        for a, b in zip(got, angles):
            assert abs((a - b + 180) % 360 - 180) < 1e-3, (got, angles)


def test_angle_matrix_columns_are_forward_left_up():
    # Нулевые углы: forward=+X, left=+Y, up=+Z (конвенция Source)
    m = angle_matrix(0, 0, 0)
    assert [m[0][0], m[1][0], m[2][0]] == [1.0, 0.0, 0.0]
    assert [round(m[0][1]), round(m[1][1]), round(m[2][1])] == [0, 1, 0]
    assert [round(m[0][2]), round(m[1][2]), round(m[2][2])] == [0, 0, 1]
    # Поворот на 90 по yaw уводит forward в +Y
    fwd = angle_matrix(0, 90, 0)
    assert abs(fwd[1][0] - 1.0) < 1e-6, fwd


def test_concat_applies_second_first():
    move = [[1, 0, 0, 10], [0, 1, 0, 0], [0, 0, 1, 0]]
    turn = angle_matrix(0, 90, 0)
    out = concat_transforms(move, turn)
    assert [round(v, 6) for v in (out[0][3], out[1][3], out[2][3])] == [10, 0, 0]
    assert abs(out[1][0] - 1.0) < 1e-6      # forward повёрнут в +Y


def test_parse_qc_attachments_reads_optional_rotate():
    items = parse_qc_attachments(_QC)
    assert [i["name"] for i in items] == ["tip", "unusual_0", "orphan"]
    assert items[0]["bone"] == "arm"
    assert items[0]["offset"] == (5.0, 0.0, 0.0)
    assert items[0]["angles"] == (0.0, 0.0, 0.0)
    # Без «rotate» углы нулевые, а не отсутствуют
    assert items[1]["offset"] == (0.0, 0.0, 20.0)
    assert items[1]["angles"] == (0.0, 0.0, 0.0)
    assert items[2]["angles"] == (10.0, 20.0, 30.0)


def test_parse_smd_uses_only_first_frame():
    bones = parse_smd_bind_pose(_SMD)
    assert set(bones) == {"root", "arm"}
    arm = bones["arm"]
    # Позиция из кадра 0, а не из кадра 1 (там 99)
    assert [round(arm[i][3], 3) for i in range(3)] == [10.0, 0.0, 0.0]
    assert abs(matrix_angles(arm)[1] - 90.0) < 1e-3


def test_attachment_world_transform_follows_bone(tmp_path):
    (tmp_path / "test.smd").write_text(_SMD, encoding="utf-8")
    qc = tmp_path / "test.qc"
    qc.write_text(_QC, encoding="utf-8")

    by_name = {a.name: a for a in attachments_from_qc(str(qc))}
    assert set(by_name) == {"tip", "unusual_0", "orphan"}

    # Кость повёрнута на 90 по yaw, значит её локальный +X смотрит в мировой +Y:
    # точка на 5 юнитов «вперёд» уезжает в (10, 5, 0)
    tip = by_name["tip"]
    assert [round(v, 3) for v in tip.pos] == [10.0, 5.0, 0.0]
    assert abs(tip.angles[1] - 90.0) < 1e-3

    # Корневая кость единичная — трансформ проходит насквозь
    assert [round(v, 3) for v in by_name["unusual_0"].pos] == [0.0, 0.0, 20.0]

    # Кости нет в SMD: точку не выбрасываем, берём её локальный трансформ
    assert [round(v, 3) for v in by_name["orphan"].pos] == [1.0, 2.0, 3.0]


def test_attachments_ignore_physics_smd(tmp_path):
    """Reference-SMD выбирается по имени QC, физика рядом не сбивает разбор."""
    (tmp_path / "test_physics.smd").write_text(
        _SMD.replace('10.000000', '777.000000'), encoding="utf-8")
    (tmp_path / "test.smd").write_text(_SMD, encoding="utf-8")
    qc = tmp_path / "test.qc"
    qc.write_text(_QC, encoding="utf-8")
    tip = {a.name: a for a in attachments_from_qc(str(qc))}["tip"]
    assert abs(tip.pos[0] - 10.0) < 1e-3, tip


def test_radian_euler_matches_source_axis_order():
    """RadianEuler(x, y, z) в Source читается как QAngle(y, z, x)."""
    from src.services.model_attachments import radian_euler_matrix
    m = radian_euler_matrix(0.0, math.radians(30), 0.0, (0.0, 0.0, 0.0))
    pitch, yaw, roll = matrix_angles(m)
    assert abs(pitch - 30.0) < 1e-3, (pitch, yaw, roll)
    assert abs(yaw) < 1e-3 and abs(roll) < 1e-3


def test_keep_source_axes_leaves_coordinates_alone(tmp_path):
    """Превью частиц живёт в координатах Source (Z-up), поэтому меш модели для
    него конвертируется БЕЗ поворота осей — иначе эффект съедет с точки
    крепления, посчитанной в тех же координатах."""
    from src.services.smd_to_obj_service import SmdToObjService

    smd = tmp_path / "m.smd"
    smd.write_text(
        "version 1\n"
        "nodes\n  0 \"root\" -1\nend\n"
        "skeleton\n  time 0\n    0 0 0 0 0 0 0\nend\n"
        "triangles\n"
        "mat\n"
        "  0 1.000000 2.000000 3.000000 0.000000 0.000000 1.000000 0.10 0.20\n"
        "  0 1.000000 2.000000 4.000000 0.000000 0.000000 1.000000 0.10 0.20\n"
        "  0 1.000000 3.000000 3.000000 0.000000 0.000000 1.000000 0.10 0.20\n"
        "end\n", encoding="utf-8")

    def first_vertex(name, **kwargs):
        obj = tmp_path / f"{name}.obj"
        ok, _ = SmdToObjService.convert(str(smd), str(obj), **kwargs)
        assert ok
        line = next(ln for ln in obj.read_text(encoding="utf-8").splitlines()
                    if ln.startswith("v "))
        return [round(float(v), 3) for v in line.split()[1:]]

    assert first_vertex("source_axes", keep_source_axes=True) == [1.0, 2.0, 3.0]
    # Штатный режим для viewer3d по-прежнему разворачивает Z-up → Y-up
    assert first_vertex("yup", source_zup=True) == [1.0, 3.0, -2.0]


def test_cdmaterials_normalised_and_deduped():
    """$cdmaterials в QC бывают со слэшами в обе стороны, ведущим слэшем и
    пустые — иначе путь к VMT не соберётся."""
    from src.services.model_materials import cdmaterials_from_qc

    cds = cdmaterials_from_qc(
        '$cdmaterials "models\\weapons\\v_machete"\n'
        '$cdmaterials "\\models\\weapons\\v_machete\\\\"\n'
        '$cdmaterials ""\n')
    assert cds == ["models/weapons/v_machete/", ""], cds


def test_model_textures_need_game_path():
    """Без пути к игре текстуры не ищем — модель просто останется серой."""
    from src.services.model_materials import resolve_model_textures
    assert resolve_model_textures("nope.qc", ["mat"], "") == {}
