"""
Конвертер SMD (Valve Model Data) → OBJ для 3D Preview.

SMD — текстовый формат Source Engine для хранения 3D-геометрии.
OBJ — универсальный текстовый формат, читаемый Three.js.

Формат вершины SMD:
    parent_bone  x y z  nx ny nz  u v  [links...]

UV:
    Source Engine SMD хранит UV в OpenGL convention (v=0 снизу) — флип НЕ нужен.
    Three.js TextureLoader по умолчанию делает flipY сам — ещё один флип сломает UV.

Система координат:
    Оружия (Z-up): правая система, Z-up (x=вправо, y=вперёд, z=вверх)
    Персонажи (Y-up): SMD уже в Y-up — $upaxis Y в QC, Crowbar экспортирует как есть.
    Three.js OBJ: правая система, Y-up (x=вправо, y=вверх, z=к зрителю)

    Конвертация Z-up → Y-up: (x, y, z) → (x, z, -y)   [оружия]
    Конвертация Y-up → Y-up: (x, y, z) → (x, y, -z)   [персонажи, зеркало Z для
                                                          корректной ориентации]
"""

import os
import re
from typing import Dict, List, Optional, Tuple

from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class SmdToObjService:
    """Конвертирует SMD файл в OBJ + MTL для Three.js."""

    @staticmethod
    def convert(
        smd_path: str,
        obj_path: str,
        include_mats: Optional[set] = None,
        extra_smd_paths: Optional[list] = None,
        source_zup: bool = True,
    ) -> Tuple[bool, List[str]]:
        """
        Конвертирует SMD → OBJ + MTL с поддержкой нескольких материалов.

        MTL файл создаётся рядом с OBJ.
        При одном материале — ссылается на «texture.png».
        При нескольких — каждый материал ссылается на «{mat_name}.png».

        Args:
            smd_path:     Путь к входному .smd файлу
            obj_path:     Путь к выходному .obj файлу
            include_mats: Если задан — оставляем только эти материалы.
                          Используется для моделей рук, чтобы исключить костюм
                          и оставить только нужные меши.
            source_zup:   True (по умолчанию) — применять конвертацию Z-up→Y-up
                          для оружий и рук. False — для персонажей ($upaxis Y),
                          SMD уже в Y-up и только зеркалим Z для Three.js.

        Returns:
            (success, material_names) где material_names — список уникальных
            имён материалов в том порядке, в котором они встречаются в SMD.
        """
        try:
            triangles_by_mat = SmdToObjService._parse_triangles_by_mat(smd_path)

            # Merge extra SMDs (bodygroups, etc.) into the same triangle dict
            for extra in (extra_smd_paths or []):
                if not os.path.exists(extra):
                    logger.warning(f"SMD→OBJ: extra SMD не найден: {extra}")
                    continue
                extra_tris = SmdToObjService._parse_triangles_by_mat(extra)
                for mat, tris in extra_tris.items():
                    if mat not in triangles_by_mat:
                        triangles_by_mat[mat] = []
                    triangles_by_mat[mat].extend(tris)
                logger.info(
                    f"SMD→OBJ: merged bodygroup '{os.path.basename(extra)}' "
                    f"({sum(len(v) for v in extra_tris.values())} треугольников)"
                )

            if include_mats is not None:
                triangles_by_mat = {
                    k: v for k, v in triangles_by_mat.items() if k in include_mats
                }
            if not triangles_by_mat:
                logger.warning(f"SMD→OBJ: нет треугольников в {smd_path}")
                return False, []

            obj_dir  = os.path.dirname(obj_path)
            obj_stem = os.path.splitext(os.path.basename(obj_path))[0]
            mtl_name = f"{obj_stem}.mtl"
            mtl_path = os.path.join(obj_dir, mtl_name)

            mat_names = list(triangles_by_mat.keys())
            multi     = len(mat_names) > 1

            # ── MTL ──────────────────────────────────────────────────────── #
            with open(mtl_path, "w", encoding="utf-8") as f:
                for mat in mat_names:
                    tex_file = f"{mat}.png" if multi else "texture.png"
                    f.write(f"newmtl {mat}\n")
                    f.write("Ka 1.0 1.0 1.0\n")
                    f.write("Kd 1.0 1.0 1.0\n")
                    f.write("Ks 0.1 0.1 0.1\n")
                    f.write("Ns 32.0\n")
                    f.write(f"map_Kd {tex_file}\n\n")

            # ── OBJ ──────────────────────────────────────────────────────── #
            positions : List[Tuple[float, float, float]] = []
            uvs       : List[Tuple[float, float]]        = []
            normals   : List[Tuple[float, float, float]] = []
            faces_by_mat: Dict[str, List[Tuple]] = {}

            for mat, triangles in triangles_by_mat.items():
                faces: List[Tuple] = []
                for tri in triangles:
                    face_idx = []
                    for vert in tri:
                        v_i  = len(positions) + 1
                        vt_i = len(uvs)       + 1
                        vn_i = len(normals)   + 1

                        x, y, z = vert["pos"]
                        nx, ny, nz = vert["nrm"]
                        if source_zup:
                            # Оружия/руки: Source Z-up → Three.js Y-up: (x,y,z) → (x, z, -y)
                            positions.append((x, z, -y))
                            normals.append((nx, nz, -ny))
                        else:
                            # Персонажи ($upaxis Y): SMD уже Y-up, только зеркалим Z
                            # чтобы персонаж смотрел на зрителя: (x,y,z) → (x, y, -z)
                            positions.append((x, y, -z))
                            normals.append((nx, ny, -nz))
                        # UV: не флипаем — Three.js сам делает flipY
                        uvs.append(vert["uv"])

                        face_idx.extend([v_i, vt_i, vn_i])
                    faces.append(tuple(face_idx))
                faces_by_mat[mat] = faces

            with open(obj_path, "w", encoding="utf-8") as f:
                f.write(f"# Converted from {os.path.basename(smd_path)}\n")
                f.write(f"mtllib {mtl_name}\n\n")

                for p in positions:
                    f.write(f"v {p[0]:.6f} {p[1]:.6f} {p[2]:.6f}\n")
                f.write("\n")

                for uv in uvs:
                    f.write(f"vt {uv[0]:.6f} {uv[1]:.6f}\n")
                f.write("\n")

                for n in normals:
                    f.write(f"vn {n[0]:.6f} {n[1]:.6f} {n[2]:.6f}\n")
                f.write("\n")

                for mat, faces in faces_by_mat.items():
                    f.write(f"g {mat}\n")
                    f.write(f"usemtl {mat}\n")
                    for face in faces:
                        v1, t1, n1, v2, t2, n2, v3, t3, n3 = face
                        f.write(
                            f"f {v1}/{t1}/{n1} {v2}/{t2}/{n2} {v3}/{t3}/{n3}\n"
                        )
                    f.write("\n")

            total = sum(len(v) for v in triangles_by_mat.values())
            logger.info(
                f"SMD→OBJ: {total} треугольников, "
                f"{len(mat_names)} матер. → {os.path.basename(obj_path)}"
            )
            return True, mat_names

        except Exception as exc:
            logger.error(f"Ошибка SMD→OBJ ({smd_path}): {exc}", exc_info=True)
            return False, []

    # ── Внутренние методы ─────────────────────────────────────────────────── #

    @staticmethod
    def _parse_triangles_by_mat(smd_path: str) -> Dict[str, List[List[dict]]]:
        """
        Парсит секцию triangles SMD файла.

        Returns:
            OrderedDict: {material_name: [triangles]} в порядке первого появления.
        """
        with open(smd_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        m = re.search(r"\btriangles\b(.*?)\bend\b", content, re.DOTALL | re.IGNORECASE)
        if not m:
            return {}

        lines = [ln.strip() for ln in m.group(1).splitlines() if ln.strip()]
        result: Dict[str, List[List[dict]]] = {}
        i = 0

        while i < len(lines):
            mat_name = lines[i]
            i += 1

            verts: List[dict] = []
            for _ in range(3):
                if i >= len(lines):
                    break
                vert = SmdToObjService._parse_vertex(lines[i])
                if vert is not None:
                    verts.append(vert)
                i += 1

            if len(verts) == 3:
                if mat_name not in result:
                    result[mat_name] = []
                result[mat_name].append(verts)

        logger.info(
            f"SMD материалы ({os.path.basename(smd_path)}): {list(result.keys())}"
        )
        # UV диагностика
        for mat, tris in result.items():
            us = [v["uv"][0] for tri in tris for v in tri]
            vs = [v["uv"][1] for tri in tris for v in tri]
            if us and vs:
                logger.info(
                    f"  UV[{mat}]: U=[{min(us):.3f}..{max(us):.3f}]  "
                    f"V=[{min(vs):.3f}..{max(vs):.3f}]"
                )
        return result

    @staticmethod
    def _parse_vertex(line: str) -> Optional[dict]:
        """
        Парсит строку вершины SMD.

        Формат: parent_bone  x y z  nx ny nz  u v  [links...]
        """
        parts = line.split()
        if len(parts) < 9:
            return None
        try:
            x,  y,  z  = float(parts[1]), float(parts[2]), float(parts[3])
            nx, ny, nz = float(parts[4]), float(parts[5]), float(parts[6])
            u,  v      = float(parts[7]), float(parts[8])
            return {"pos": (x, y, z), "nrm": (nx, ny, nz), "uv": (u, v)}
        except (ValueError, IndexError):
            return None
