"""
Гирлянда, вшитая в модель оружия («Сделать праздничным»)

Игра рисует гирлянду только у праздничной версии или с Фестивайзером:
отдельной моделью костями оружия. Вшитая - часть меша самого оружия, её видят
все, кто поставил мод. Проверено в игре на обрезе: гирлянда на месте и мигает

1. Гирлянда разбирается со всеми правками формы (decor_build.prepare).
2. Её треугольники дописываются в главный меш оружия, номера костей
   переносятся по ИМЕНАМ (скелеты гирлянд повторяют скелет оружия).
3. Материалы - в свою папку (`models/tf2sg_decor/<гирлянда>`), как у
   гирлянды своей моделью: материалы гирлянд общие у сотни оружий.
4. Командные огоньки - столбцом $texturegroup: у оружия строка 0 - RED,
   1 - BLU, дальше парами, строка гирлянды берётся по той же чётности.
5. Родные гирлянды оружия собираются пустыми: у владельца праздничной версии
   игра повесила бы свою поверх вшитой
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Iterable, List, Optional

from src.services import decor_build
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Пустая гирлянда: один крошечный треугольник с невидимым материалом
EMPTY_DIR = f"{decor_build.DECOR_MATERIALS_ROOT}\\empty"
EMPTY_MATERIAL = "tf2sg_empty"
_EMPTY_VMT = ('"VertexLitGeneric"\n{\n\t"$basetexture" "tools/toolsnodraw"\n'
              '\t"$no_draw" "1"\n\t"$alpha" "0"\n\t"$translucent" "1"\n}\n')
_EMPTY_TRIANGLES = (f"triangles\n{EMPTY_MATERIAL}\n"
                    "  0 0 0 0 0 0 1 0 0 1 0 1.0\n"
                    "  0 0.01 0 0 0 0 1 1 0 1 0 1.0\n"
                    "  0 0 0.01 0 0 0 1 0 1 1 0 1.0\nend\n")
_RE_CDMATERIALS = re.compile(r'^[ \t]*\$cdmaterials\b', re.IGNORECASE | re.MULTILINE)


def bake_entry(entries: Optional[Iterable[dict]]) -> Optional[dict]:
    """Гирлянда, которую надо вшить в оружие, из списка гирлянд сборки"""
    return next((e for e in entries or () if e.get('bake')), None)


def bake(ctx, entry: dict, qc_path: str, weapon_key: str, *, misc_vpk: str,
         textures_vpk: str, studiomdl_exe: str, tf_dir: str, size, format_type,
         flags, vtf_options, bypass_prefix: str) -> None:
    """Вшивает гирлянду `entry` в QC оружия до его компиляции и кладёт в мод
    пустые родные гирлянды (`entry['empty']` - их пути в VPK)"""
    from src.services.model_build_service import ModelBuildService

    mdl = entry['mdl'].replace('\\', '/').lower()
    stem = Path(mdl).stem
    work, model, ref = decor_build.prepare(ctx, entry, mdl, stem, misc_vpk)
    body = ModelBuildService.extract_main_body_smd(qc_path, weapon_key)
    if not body:
        raise FileNotFoundError(f"в QC {weapon_key} нет меша для гирлянды")
    append_triangles(body, ref)

    patched = ModelBuildService.apply_cdmaterials_prefix(
        f"{decor_build.DECOR_MATERIALS_ROOT}\\{stem}", bypass_prefix)
    add_to_qc(qc_path, patched, ModelBuildService._parse_texturegroup_rows(model.qc_path))
    decor_build.write_materials(
        ctx.vpkroot_dir, entry, model, ref, list(model.cdmaterials), patched, work,
        misc_vpk=misc_vpk, textures_vpk=textures_vpk, size=size,
        format_type=format_type, flags=flags, vtf_options=vtf_options)
    for native in entry.get('empty') or ():
        build_empty(ctx, native, misc_vpk=misc_vpk, studiomdl_exe=studiomdl_exe,
                    tf_dir=tf_dir, bypass_prefix=bypass_prefix)
    logger.info(f"[гирлянда] {stem} вшита в {weapon_key}, пустых родных: "
                f"{len(entry.get('empty') or ())}")


def append_triangles(body_smd: str, garland_smd: str) -> None:
    """Дописывает треугольники гирлянды в меш оружия, кости - по именам"""
    from src.services.smd_service import SMDService

    body = Path(body_smd).read_text(encoding='utf-8', errors='replace').splitlines(True)
    garland = Path(garland_smd).read_text(encoding='utf-8', errors='replace').splitlines(True)
    mapping = SMDService._bone_mapping(SMDService._parse_smd_lines(garland)['nodes'],
                                       SMDService._parse_smd_lines(body)['nodes'])
    start = _section(garland, 'triangles') + 1
    tris = [SMDService._remap_vertex_line(line, mapping, 0) for line in
            garland[start:_last_end(garland)]]
    end = _last_end(body)
    if _section(body, 'triangles') < 0:
        tris = ['triangles\n', *tris, 'end\n']
        end = len(body)
    Path(body_smd).write_text(''.join(body[:end] + tris + body[end:]), encoding='utf-8')


def add_to_qc(qc_path: str, cd_dir: str, garland_rows: List[List[str]]) -> None:
    """Папка материалов гирлянды и её командный столбец в QC оружия"""
    from src.services.model_build_service import ModelBuildService

    text = Path(qc_path).read_text(encoding='utf-8', errors='replace')
    line = f'$cdmaterials "{cd_dir}\\"\n'
    m = _RE_CDMATERIALS.search(text)
    text = text[:m.start()] + line + text[m.start():] if m else line + text
    Path(qc_path).write_text(text, encoding='utf-8')
    rows = skin_rows(ModelBuildService._parse_texturegroup_rows(qc_path), garland_rows)
    if rows:
        block = '$texturegroup "skinfamilies"\n{\n' + ''.join(
            '\t{ ' + ' '.join(f'"{name}"' for name in row) + ' }\n' for row in rows) + '}\n'
        ModelBuildService.replace_texturegroup_in_qc(qc_path, block)


def skin_rows(weapon: List[List[str]], garland: List[List[str]]) -> List[List[str]]:
    """Строки скинов оружия со столбцами гирлянды, пусто - менять нечего

    У гирлянды без скинов (одна строка) материалы одни на все скины - столбец
    не нужен. У оружия без скинов строки - сами строки гирлянды
    """
    if len(garland) < 2:
        return []
    if not weapon:
        return [list(row) for row in garland]
    # Скинов у оружия меньше, чем у гирлянды (у револьвера строка одна):
    # синему игра ставит скин 1, и без своей строки огоньки остались бы красными
    weapon = list(weapon) + [weapon[0]] * (len(garland) - len(weapon))
    return [list(row) + list(garland[i % len(garland)]) for i, row in enumerate(weapon)]


def build_empty(ctx, mdl: str, *, misc_vpk: str, studiomdl_exe: str, tf_dir: str,
                bypass_prefix: str) -> None:
    """Родная гирлянда по своему пути, но без видимой геометрии"""
    from src.services import model_decompile_service as mds
    from src.services.model_build_service import ModelBuildService
    from src.services.model_service import ModelService

    mdl = mdl.replace('\\', '/').lower()
    stem = Path(mdl).stem
    work = Path(ctx.temp_dir) / f"decor_empty_{stem}"
    found = mds.ensure_decompiled(stem, misc_vpk, [mdl])
    if found is None:
        raise FileNotFoundError(f"{mdl} нет в игре")
    shutil.copytree(found.directory, work / "decompile", dirs_exist_ok=True)
    qc = next((work / "decompile").glob("*.qc"))
    for smd in ModelBuildService.extract_all_mesh_smds(str(qc)):
        lines = Path(smd).read_text(encoding='utf-8', errors='replace').splitlines(True)
        start = _section(lines, 'triangles')
        Path(smd).write_text(''.join(lines[:start if start >= 0 else len(lines)])
                             + _EMPTY_TRIANGLES, encoding='utf-8')
    decor_build._set_cdmaterials(str(qc), EMPTY_DIR)
    ModelBuildService.replace_texturegroup_in_qc(str(qc), '')
    ModelBuildService.patch_qc_file(str(qc), bypass_prefix)
    comp = work / "compile"
    comp.mkdir(parents=True, exist_ok=True)
    ModelBuildService.compile(str(qc), str(comp), studiomdl_exe, tf_dir)
    sub = type('SubCtx', (), {'compile_dir': comp, 'vpkroot_dir': ctx.vpkroot_dir})()
    ModelService.copy_compiled_models_to_vpkroot(sub, str(qc))
    patched = ModelBuildService.apply_cdmaterials_prefix(EMPTY_DIR, bypass_prefix)
    out = Path(ctx.vpkroot_dir, "materials", *patched.replace('\\', '/').split('/'))
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{EMPTY_MATERIAL}.vmt").write_text(_EMPTY_VMT, encoding='utf-8')


def _section(lines: List[str], name: str) -> int:
    return next((i for i, line in enumerate(lines) if line.strip() == name), -1)


def _last_end(lines: List[str]) -> int:
    return max(i for i, line in enumerate(lines) if line.strip() == 'end')
