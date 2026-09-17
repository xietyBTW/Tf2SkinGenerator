"""
Собирает канонический скелет игрока (src/data/player_skeleton.py).

Косметика в игре не стоит сама по себе — её кости сливаются с костями игрока
(bonemerge), и в кадре она оказывается там, где у игрока голова. В самом же
MDL шапка лежит как автору было удобно: у одних верх смотрит по +Y (собраны
против скелета игрока с `$upaxis Y`), у других по −Z, у третьих вообще как
попало. Превью, читающее вершины как есть, показывает такие шапки боком.

Здесь из reference-SMD одного из игроков берутся мировые матрицы всех его
костей в осях движка (Z вверх): по ним cosmetic_pose ставит косметику так,
как ставит её игра. Все, а не только `bip_*`: пингвин Tux висит на кости
`mvm`, и она у всех классов тоже есть. Класс не важен: ориентация головы у
всех девяти одна и та же, а разница в росте превью не мешает — модель
центрируется по габаритам.

Запуск (нужен разобранный Crowbar игрок — например, из кэша декомпиляции
~/.tf2skingen_cache/decompiled/<ключ>/soldier.qc):
    python scripts/player_skeleton_build.py <путь к QC или reference-SMD>
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.services import smd_pose  # noqa: E402
from src.services.model_attachments import reference_smd_for_qc  # noqa: E402

OUT = ROOT / "src" / "data" / "player_skeleton.py"

#: `$upaxis Y` → оси движка, как делает studiomdl: (x, y, z) → (x, −z, y).
_Y_UP_TO_ENGINE: smd_pose.Mat = (1.0, 0.0, 0.0, 0.0,
                                 0.0, 0.0, -1.0, 0.0,
                                 0.0, 1.0, 0.0, 0.0)


def bone_names(smd: str) -> dict:
    names = {}
    for line in smd_pose._section(smd, "nodes"):
        m = smd_pose._RE_NODE.match(line)
        if m:
            names[int(m.group(1))] = m.group(2)
    return names


def build(smd: str, y_up: bool) -> dict:
    names = bone_names(smd)
    world = smd_pose.world_matrices(smd_pose.parse_nodes(smd),
                                    smd_pose.parse_frame0(smd))
    out = {}
    for bone, mat in world.items():
        name = names.get(bone, "")
        if not name:
            continue
        out[name] = smd_pose.mul(_Y_UP_TO_ENGINE, mat) if y_up else mat
    return out


def main(argv) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    src = argv[1]
    y_up = False
    if src.lower().endswith(".qc"):
        with open(src, encoding="utf-8", errors="replace") as f:
            y_up = "$upaxis y" in f.read().lower()
        src = reference_smd_for_qc(src) or ""
    if not os.path.isfile(src):
        print(f"нет reference-SMD: {argv[1]}")
        return 1
    bones = build(src, y_up)
    if "bip_head" not in bones:
        print("в скелете нет bip_head — это не игрок")
        return 1

    lines = [
        '"""',
        "Канонический скелет игрока: мировые матрицы его костей в осях",
        "движка (Z вверх). Собрано scripts/player_skeleton_build.py из",
        f"{os.path.basename(src)}; руками не править.",
        "",
        "Матрица — 12 чисел (три строки по четыре), как в smd_pose.",
        '"""',
        "",
        "from typing import Dict, Tuple",
        "",
        "BONES: Dict[str, Tuple[float, ...]] = {",
    ]
    for name in sorted(bones):
        m = bones[name]
        rows = [", ".join(f"{v:.6f}" for v in m[r * 4:r * 4 + 4]) for r in range(3)]
        lines.append(f"    {name!r}: (")
        for row in rows:
            lines.append(f"        {row},")
        lines.append("    ),")
    lines.append("}")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"{OUT}: {len(bones)} костей из {src}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
