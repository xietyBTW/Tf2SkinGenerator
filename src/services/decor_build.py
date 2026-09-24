"""
Сборка гирлянды поверх оружия (праздничная версия, фестивайзер) в тот же мод.

Гирлянда — отдельная модель (`c_*_xmas.mdl`, `c_*_festivizer.mdl`), которую
игра рисует костями оружия. Её правки собираются своей моделью, отдельно от
оружия:

1. разбор стоковой гирлянды (кэш декомпиляции общий с превью);
2. подгонка под свою модель оружия запекается в вершины — кости и веса
   остаются, и в игре гирлянда по-прежнему едет костями пушки;
3. `$cdmaterials` уводится в СВОЮ папку (`models/tf2sg_decor/<модель>`).
   Материалы гирлянд у всех оружий общие (`festive_lights_red` один на сотню
   моделей): подмени текстуру по игровому пути — и она легла бы на гирлянды
   всех оружий разом. В своей папке правка касается только этой модели;
4. каждый материал получает VMT в этой папке. Правленый — свою текстуру и
   копию игрового VMT с `$basetexture` на неё (самосвет, мигание и прочие
   прокси остаются игровыми). Неправленый — копию игрового VMT как есть:
   ссылки в нём от корня materials/, и стоковая текстура находится сама.

Ошибка одной гирлянды не валит сборку оружия: мод соберётся со стоковой.

Модуль без Qt.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Корень папок материалов гирлянд в моде: у каждой модели своя подпапка.
DECOR_MATERIALS_ROOT = "models\\tf2sg_decor"

_RE_CDMATERIALS_LINE = re.compile(r'^\s*\$cdmaterials\b.*$', re.IGNORECASE | re.MULTILINE)
_RE_BASETEXTURE = re.compile(r'("?\$basetexture"?\s+)"[^"]*"', re.IGNORECASE)


def build_decor_models(
    ctx,
    entries: Iterable[dict],
    *,
    misc_vpk: str,
    textures_vpk: str,
    studiomdl_exe: str,
    tf_dir: str,
    size: Tuple[int, int],
    format_type: str,
    flags: List[str],
    vtf_options: dict,
    bypass_prefix: str = "console",
    emit_sub: Optional[Callable[[int, str], None]] = None,
    language: str = "ru",
) -> int:
    """Собирает гирлянды в `ctx.vpkroot_dir`. Возвращает, сколько собрано.

    Элемент `entries`: {'kind', 'mdl' (путь в VPK), 'smd' (своя модель
    гирлянды или пусто), 'fit' (dict | None),
    'bends' ([{c, r, d}] — изгибы, festive_decor.apply_bends),
    'textures': {материал: {'red': png, 'blu': png}}}.
    """
    built = 0
    for entry in entries or ():
        mdl = (entry.get('mdl') or '').replace('\\', '/').lower()
        if not mdl:
            continue
        stem = Path(mdl).stem
        if emit_sub:
            emit_sub(-1, f"Lights: {stem}..." if language == "en"
                     else f"Гирлянда: {stem}...")
        try:
            _build_one(ctx, entry, mdl, stem, misc_vpk, textures_vpk,
                       studiomdl_exe, tf_dir, size, format_type, flags,
                       vtf_options, bypass_prefix)
            built += 1
        except Exception as exc:                              # noqa: BLE001
            logger.warning(f"[гирлянда] {stem}: не собрана — в моде останется "
                           f"стоковая: {exc}", exc_info=True)
            if hasattr(ctx, 'warn'):
                ctx.warn(f"Гирлянда {stem} не собралась: {exc}")
    return built


def _build_one(ctx, entry: dict, mdl: str, stem: str, misc_vpk: str,
               textures_vpk: str, studiomdl_exe: str, tf_dir: str,
               size, format_type, flags, vtf_options, bypass_prefix) -> None:
    from src.services import mesh_import_service, qc_skin_parser, smd_service
    from src.services import model_decompile_service as mds
    from src.services.game_vpk_reader import GameVpkReader
    from src.services.model_build_service import ModelBuildService
    from src.services.model_service import ModelService

    work = Path(ctx.temp_dir) / f"decor_{stem}"
    decomp_dir, comp_dir = work / "decompile", work / "compile"
    found = mds.ensure_decompiled(stem, misc_vpk, [mdl])
    if found is None:
        raise FileNotFoundError(f"{mdl} нет в игре")
    # Копия: правим QC и SMD, а кэш декомпиляции общий с превью.
    shutil.copytree(found.directory, decomp_dir, dirs_exist_ok=True)
    comp_dir.mkdir(parents=True, exist_ok=True)

    model = qc_skin_parser.load_model(str(decomp_dir))
    ref = smd_service.find_reference_smd(str(decomp_dir), stem)
    if model is None or not ref:
        raise FileNotFoundError(f"в разборе {stem} нет QC или меша")

    from src.services import festive_decor
    # Своя модель — на скелет стоковой, как в превью (festive_decor.build).
    if entry.get('smd'):
        festive_decor.own_on_stock(entry['smd'], ref, ref)
    # Сначала изгибы (по самой гирлянде), потом подгонка — как во вьювере.
    if entry.get('bends'):
        festive_decor.bend_smd(ref, ref, entry['bends'],
                               festive_decor.weapon_pose(entry.get('weapon') or '', ref))
    fit = mesh_import_service.Fit.from_dict(entry.get('fit'))
    if entry.get('fit') and fit != mesh_import_service.Fit():
        mesh_import_service.transform_smd(ref, ref, fit)

    original_cd = list(model.cdmaterials)
    materials = _all_materials(model, ref)
    team_map = {red.lower(): blu for red, blu in model.team_map.items()}

    own_dir = f"{DECOR_MATERIALS_ROOT}\\{stem}"
    _set_cdmaterials(model.qc_path, own_dir)
    ModelBuildService.patch_qc_file(model.qc_path, bypass_prefix)
    patched = ModelBuildService.apply_cdmaterials_prefix(own_dir, bypass_prefix)

    ModelBuildService.compile(model.qc_path, str(comp_dir), studiomdl_exe, tf_dir)
    sub = type('SubCtx', (), {'compile_dir': comp_dir, 'vpkroot_dir': ctx.vpkroot_dir})()
    ModelService.copy_compiled_models_to_vpkroot(sub, model.qc_path)

    out_dir = Path(ctx.vpkroot_dir, "materials", *patched.replace('\\', '/').split('/'))
    out_dir.mkdir(parents=True, exist_ok=True)
    images = _images_by_material(entry.get('textures') or {}, team_map)
    reader = GameVpkReader([textures_vpk, misc_vpk])
    try:
        for name in materials:
            found_vmt = reader.find_vmt(original_cd, name.lower())
            image = images.get(name.lower())
            if found_vmt:
                text = found_vmt[1]
            elif entry.get('smd'):
                # Материал своей модели: в игре его нет, VMT пишем сами; без
                # картинки — серый, как в превью (festive_decor._grey_png).
                text = '"VertexLitGeneric"\n{\n\t"$basetexture" ""\n}\n'
                image = image or festive_decor._grey_png(str(work), name)
            else:
                logger.info(f"[гирлянда] {stem}: VMT {name} не найден — пропуск")
                continue
            if image and os.path.isfile(image):
                # Лампочки мигают кадрами игровой текстуры — своя картинка
                # раскладывается на те же кадры (festive_decor.blink_like).
                stock = _stock_frames(reader, text, work / "stock", name)
                if len(stock) > 1:
                    _render_blinking_vtf(image, stock, out_dir, name, size,
                                         format_type, flags, vtf_options, work)
                else:
                    _render_vtf(image, out_dir, name, size, format_type, flags, vtf_options)
                texture = f"{patched}\\{name}".replace('\\', '/')
                text = _RE_BASETEXTURE.sub(lambda m: f'{m.group(1)}"{texture}"', text, count=1)
            (out_dir / f"{name}.vmt").write_text(text, encoding="utf-8")
    finally:
        reader.close()
    logger.info(f"[гирлянда] {stem}: собрана, подгонка={fit.to_dict()}, "
                f"изгибов {len(entry.get('bends') or [])}, "
                f"своих текстур {len(images)}, материалы в {patched}")


def _all_materials(model, ref_smd: str) -> List[str]:
    """Все материалы гирлянды: меш и все строки $texturegroup (команда в них)."""
    from src.services.smd_to_obj_service import SmdToObjService

    names: Dict[str, str] = {}
    for row in model.layout.all_rows or ():
        for name in row:
            if name:
                names.setdefault(name.lower(), name)
    for name in SmdToObjService.scan_material_names([ref_smd]):
        names.setdefault(name.lower(), name)
    return list(names.values())


def _images_by_material(textures: Dict[str, dict], team_map: Dict[str, str]) -> Dict[str, str]:
    """{материал в нижнем регистре: картинка}. Правка лежит под КРАСНЫМ
    материалом; синяя картинка уходит его командной паре из $texturegroup.

    Материал без командной пары один на обе команды — ему годится любая
    из двух картинок. У командного синяя пара без своей правки остаётся
    игровой: красные лампочки у синих были бы чужими."""
    out: Dict[str, str] = {}
    for red, teams in textures.items():
        red_img, blu_img = (teams or {}).get('red'), (teams or {}).get('blu')
        blu = team_map.get(red.lower())
        if not blu or blu.lower() == red.lower():
            if red_img or blu_img:
                out[red.lower()] = red_img or blu_img
            continue
        if red_img:
            out[red.lower()] = red_img
        if blu_img:
            out[blu.lower()] = blu_img
    return out


def _set_cdmaterials(qc_path: str, folder: str) -> None:
    """Все `$cdmaterials` QC → одна своя папка (обход sv_pure добавит patch_qc_file)."""
    text = Path(qc_path).read_text(encoding="utf-8", errors="replace")
    lines = _RE_CDMATERIALS_LINE.findall(text)
    if not lines:
        raise ValueError("в QC нет $cdmaterials")
    first = True

    def swap(_match):
        nonlocal first
        if first:
            first = False
            return f'$cdmaterials "{folder}\\"'
        return ''
    Path(qc_path).write_text(_RE_CDMATERIALS_LINE.sub(swap, text), encoding="utf-8")


def _stock_frames(reader, vmt_text: str, out_dir: Path, name: str) -> List[str]:
    """Кадры игровой базовой текстуры материала (PNG); пусто — не нашлась."""
    from src.services import vmt_parse
    from src.services.vtf_preview_service import vtf_bytes_to_frame_pngs

    base = vmt_parse.basetexture(vmt_text)
    data = reader.find_vtf_for_basetexture(base) if base else None
    return vtf_bytes_to_frame_pngs(data, str(out_dir), name) if data else []


def _render_blinking_vtf(image: str, stock: List[str], out_dir: Path, name: str,
                         size, format_type, flags, vtf_options, work: Path) -> None:
    """Своя картинка → многокадровый VTF с миганием игровой текстуры.

    Частоту задаёт игровой VMT (прокси AnimatedTexture), и он остаётся как
    есть — важно только число кадров и маска свечения в альфе.
    """
    from PIL import Image

    from src.services import festive_decor
    from src.services.texture_service import TextureService

    frames = festive_decor.blink_like(image, stock, str(work / "blink"), name)
    pictures = [Image.open(p) for p in frames]
    apng = work / f"{name}_blink.png"
    pictures[0].save(apng, save_all=True, append_images=pictures[1:],
                     duration=1000, loop=0)
    for pic in pictures:
        pic.close()
    vtf_flags, merged = TextureService.resolve_vtf_flags_and_options(
        flags or [], vtf_options, drop_normal=True)
    TextureService.create_animated_vtf(str(apng), str(out_dir / f"{name}.vtf"),
                                       tuple(size), format_type, vtf_flags, merged)
    if not (out_dir / f"{name}.vtf").is_file():
        raise RuntimeError(f"VTF для {name} не создался")


def _render_vtf(image: str, out_dir: Path, name: str, size, format_type,
                flags, vtf_options) -> None:
    """Своя картинка → VTF с именем материала рядом с его VMT."""
    from src.services.texture_service import TextureService

    png = out_dir / f"{name}.png"
    TextureService.process_image(image, png, size)
    vtf_flags, merged = TextureService.resolve_vtf_flags_and_options(
        flags or [], vtf_options, drop_normal=True)
    TextureService.create_vtf(str(png), str(out_dir), format_type, vtf_flags, merged)
    try:
        png.unlink()
    except OSError:
        pass
    if not (out_dir / f"{name}.vtf").is_file():
        raise RuntimeError(f"VTF для {name} не создался")
