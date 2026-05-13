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
    Source Engine: правая система, Z-up (x=вправо, y=вперёд, z=вверх)
    Three.js OBJ:  правая система, Y-up (x=вправо, y=вверх, z=к зрителю)
    Конвертация позиции/нормали: (x, y, z) → (x, z, -y)
"""

import os
import re
from typing import Dict, List, Optional, Tuple

from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class SmdToObjService:
    """Конвертирует SMD файл в OBJ + MTL для Three.js."""

    @staticmethod
    def convert(smd_path: str, obj_path: str) -> bool:
        """
        Конвертирует SMD → OBJ + MTL.

        MTL файл создаётся рядом с OBJ и ссылается на «texture.png»
        (ожидается в той же папке).

        Args:
            smd_path: Путь к входному .smd файлу
            obj_path:  Путь к выходному .obj файлу

        Returns:
            True при успешной конвертации.
        """
        try:
            triangles = SmdToObjService._parse_triangles(smd_path)
            if not triangles:
                logger.warning(f"SMD→OBJ: нет треугольников в {smd_path}")
                return False

            obj_dir  = os.path.dirname(obj_path)
            obj_stem = os.path.splitext(os.path.basename(obj_path))[0]
            mtl_name = f"{obj_stem}.mtl"
            mtl_path = os.path.join(obj_dir, mtl_name)

            # ── MTL ───────────────────────────────────────────────────────── #
            with open(mtl_path, "w", encoding="utf-8") as f:
                f.write("newmtl weapon\n")
                f.write("Ka 1.0 1.0 1.0\n")
                f.write("Kd 1.0 1.0 1.0\n")
                f.write("Ks 0.1 0.1 0.1\n")
                f.write("Ns 32.0\n")
                f.write("map_Kd texture.png\n")

            # ── OBJ ───────────────────────────────────────────────────────── #
            positions : List[Tuple[float, float, float]] = []
            uvs       : List[Tuple[float, float]]        = []
            normals   : List[Tuple[float, float, float]] = []
            # Каждый face — tuple из 9 int (v/vt/vn для трёх вершин)
            faces: List[Tuple] = []

            for tri in triangles:
                face_idx = []
                for vert in tri:
                    v_i  = len(positions) + 1
                    vt_i = len(uvs)       + 1
                    vn_i = len(normals)   + 1

                    # Координаты: Source Z-up → Three.js Y-up: (x,y,z) → (x, z, -y)
                    x, y, z = vert["pos"]
                    positions.append((x, z, -y))
                    nx, ny, nz = vert["nrm"]
                    normals.append((nx, nz, -ny))
                    # UV: не флипаем — Three.js сам делает flipY при загрузке текстуры
                    uvs.append(vert["uv"])

                    face_idx.extend([v_i, vt_i, vn_i])
                faces.append(tuple(face_idx))

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

                f.write("usemtl weapon\n")
                for face in faces:
                    v1, t1, n1, v2, t2, n2, v3, t3, n3 = face
                    f.write(
                        f"f {v1}/{t1}/{n1} {v2}/{t2}/{n2} {v3}/{t3}/{n3}\n"
                    )

            logger.info(
                f"SMD→OBJ: {len(triangles)} треугольников → {os.path.basename(obj_path)}"
            )
            return True

        except Exception as exc:
            logger.error(f"Ошибка SMD→OBJ ({smd_path}): {exc}", exc_info=True)
            return False

    # ── Внутренние методы ─────────────────────────────────────────────────── #

    @staticmethod
    def _parse_triangles(smd_path: str) -> List[List[dict]]:
        """Парсит секцию triangles SMD файла."""
        with open(smd_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        m = re.search(r"\btriangles\b(.*?)\bend\b", content, re.DOTALL | re.IGNORECASE)
        if not m:
            return []

        lines = [ln.strip() for ln in m.group(1).splitlines() if ln.strip()]
        triangles: List[List[dict]] = []
        i = 0

        while i < len(lines):
            # Имя материала (пропускаем — у нас одна MTL запись «weapon»)
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
                triangles.append(verts)

        return triangles

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
