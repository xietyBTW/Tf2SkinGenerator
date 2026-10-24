"""
Доп. текстуры и файлы по фиксированному игровому пути (HUD Звона
смерти: циферблат, .res-скрипты) - вне QC и модели
"""

import hashlib
import os
from pathlib import Path
from typing import List, Optional, Tuple

from src.services.texture_service import TextureService
from src.services.vmt_service import VMTService
from src.shared.file_utils import copy_file_safe, ensure_directory_exists
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def build_fixed_extra_textures(
    weapon_key: str,
    panel_extra_textures: Optional[dict],
    ctx,
    size: Tuple[int, int],
    format_type: str,
    flags: List[str],
    vtf_options: dict,
    misc_vpk: Optional[str] = None,
    textures_vpk: Optional[str] = None,
) -> set:
    """
    Записывает доп. текстуры предмета, заданные ФИКСИРОВАННЫМ путём
    (вне QC/модели) - см. WEAPON_EXTRA_TEXTURES. Пример: HUD-вставки Dead Ringer

    VTF и VMT кладутся по РЕАЛЬНОМУ игровому пути (без console-схемы): так VMT
    лежит в той же папке, что и VTF, и нет дублей vgui. Игровой VMT берётся
    по тому же пути (туда смотрит HUD), $basetexture - на наш VTF

    Возвращает множество обработанных имён - чтобы общий цикл panel_extra_textures
    не записал их повторно по cdmaterials-пути
    """
    handled: set = set()
    if not panel_extra_textures:
        return handled
    from src.data.weapon_quirks import WEAPON_EXTRA_TEXTURES

    # Кэш уже сконвертированных VTF по хэшу содержимого исходной картинки.
    # Если в fg и bg (или любые два слота) загружена ОДНА И ТА ЖЕ картинка
    # (по содержимому, даже из разных файлов) - конвертируем один раз,
    # для остальных просто копируем готовый VTF. Конвертация GIF->VTF дорогая
    # (извлечение кадров), так что это заметно ускоряет сборку
    vtf_cache: dict = {}   # {img_hash: (built_vtf_path, fps)}

    for ex in WEAPON_EXTRA_TEXTURES.get(weapon_key, []):
        name = ex["name"]
        img = panel_extra_textures.get(name)
        if not img or not os.path.isfile(img):
            continue
        try:
            vtf_rel = ex["vpk"].replace("\\", "/")               # materials/vgui/.../x.vtf
            base_no_mat = vtf_rel[len("materials/"):] if vtf_rel.startswith("materials/") else vtf_rel
            base_path = os.path.splitext(base_no_mat)[0]         # vgui/.../pocket_watch_fg (для $basetexture)

            # 1) VTF по реальному пути
            target_dir = _under_root(ctx.vpkroot_dir, os.path.dirname(vtf_rel))
            ensure_directory_exists(target_dir)
            stem = os.path.splitext(os.path.basename(vtf_rel))[0]
            vtf_flags, merged = TextureService.resolve_vtf_flags_and_options(
                flags, vtf_options, drop_normal=True)
            fps = _render_fixed_vtf(img, target_dir, stem, size, format_type,
                                    vtf_flags, merged, vtf_cache)

            # 2) VMT рядом с VTF ($basetexture -> реальный путь)
            _write_fixed_extra_vmt(ex, base_path, ctx, misc_vpk, textures_vpk)

            # Игровой VMT fg/bg уже содержит AnimatedTexture-прокси, но если
            # его не нашли (минимальный шаблон) - добавляем прокси для анимации
            if fps:
                vmt_target = _under_root(ctx.vpkroot_dir, ex["vmt"].replace("\\", "/"))
                if vmt_target.exists():
                    VMTService.enable_animated_basetexture(str(vmt_target), fps)

            handled.add(name)
            logger.info(f"Фикс. доп. текстура: {vtf_rel}; vmt={ex.get('vmt')}")
        except Exception as exc:
            logger.warning(f"Фикс. доп. текстура '{name}' - ошибка: {exc}", exc_info=True)
    return handled


def _under_root(root, rel: str):
    """Путь rel ('a/b/c') внутри root; пустые части пропускаются"""
    target = root
    for part in rel.split("/"):
        if part:
            target = target / part
    return target


def _render_fixed_vtf(img, target_dir, stem, size, format_type, vtf_flags, merged,
                      vtf_cache: dict) -> Optional[float]:
    """{stem}.vtf из картинки (или готового VTF). Возвращает fps анимации"""
    dest_vtf = target_dir / f"{stem}.vtf"
    img_hash = _file_content_hash(img)
    cached = vtf_cache.get(img_hash) if img_hash else None
    if str(img).lower().endswith('.vtf'):
        # Пользователь загрузил готовый VTF - копируем как есть
        copy_file_safe(img, dest_vtf)
        logger.info(f"Фикс. доп. текстура: готовый VTF скопирован → {stem}.vtf")
        return None
    if cached:
        # Та же картинка уже сконвертирована - переиспользуем готовый VTF
        src_vtf, fps = cached
        copy_file_safe(src_vtf, dest_vtf)
        logger.info(
            f"Доп. текстура переиспользована (идентичная картинка): "
            f"{stem}.vtf ← {Path(src_vtf).name}"
        )
        return fps
    if TextureService.is_animated_image(img):
        # Анимированный GIF -> многокадровый VTF (циферблат Dead Ringer
        # анимируется через AnimatedTexture-прокси в его игровом VMT)
        fps = TextureService.create_animated_vtf(
            img, str(dest_vtf), size, format_type, vtf_flags, merged
        )
        logger.info(f"Фикс. доп. текстура анимирована: {stem}.vtf @ {fps}fps")
    else:
        fps = None
        tmp_png = target_dir / f"{stem}.png"
        TextureService.process_image(img, str(tmp_png), size)
        TextureService.create_vtf(str(tmp_png), str(target_dir), format_type, vtf_flags, merged)
        if tmp_png.exists():
            tmp_png.unlink()
    if img_hash:
        vtf_cache[img_hash] = (dest_vtf, fps)
    return fps


def _write_fixed_extra_vmt(ex: dict, base_texture_path: str, ctx,
                           misc_vpk: Optional[str], textures_vpk: Optional[str]) -> None:
    """
    Кладёт VMT фиксированной доп. текстуры В ТУ ЖЕ папку, что и её VTF
    (реальный игровой путь, без console-схемы)

    Берёт игровой VMT (если найден в VPK) и патчит $basetexture ->
    base_texture_path; если игрового нет - создаёт минимальный UnlitGeneric
    """
    vmt_rel = ex.get("vmt")
    if not vmt_rel:
        return
    vmt_rel = vmt_rel.replace("\\", "/")

    # Игровой VMT ищем по тому же пути, что и в моде (реальный путь к материалу)
    content = None
    try:
        import vpk as vpklib
        for vpk_path in (misc_vpk, textures_vpk):
            if not vpk_path or not os.path.exists(vpk_path):
                continue
            try:
                pak = vpklib.open(vpk_path)
                content = pak[vmt_rel].read().decode("utf-8", errors="replace")
                break
            except Exception:
                continue
    except Exception as exc:
        logger.debug(f"Не удалось прочитать игровой VMT {vmt_rel}: {exc}")

    if content:
        content = VMTService._set_vmt_param(content, "$basetexture", base_texture_path)
    else:
        content = (
            '"UnlitGeneric"\n{\n'
            f'\t"$basetexture" "{base_texture_path}"\n'
            '\t"$translucent" "1"\n'
            '\t"$vertexalpha" "1"\n}\n'
        )

    target = ctx.vpkroot_dir
    for part in vmt_rel.split("/"):
        if part:
            target = target / part
    ensure_directory_exists(target.parent)
    with open(target, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info(f"Фикс. доп. VMT записан: {vmt_rel} ($basetexture → {base_texture_path})")


def watch_screen_res(weapon_key: str, handled: set) -> Optional[str]:
    """
    Текст .res экрана часов: заменённая картинка - из мода, остальные - игры

    None - часы не те или на циферблате ничего не меняли: тогда игра
    обходится своим .res. Прежде .res писался всегда и вёл обе картинки в
    мод - нетронутая показывалась в игре отсутствующей текстурой
    """
    from src.data.weapon_quirks import WATCH_SCREEN_RES, WEAPON_EXTRA_TEXTURES
    if weapon_key not in WATCH_SCREEN_RES or not handled:
        return None
    images = {}
    for ex in WEAPON_EXTRA_TEXTURES.get(weapon_key, []):
        path = ex["vpk"] if ex["name"] in handled else ex["game"]
        # Картинку шкалы игра ищет от materials/vgui и без расширения
        images[ex["role"]] = os.path.splitext(path)[0][len("materials/vgui/"):]
    return (
        '"InvisProgress.res"\n{\n'
        '\t"InvisProgress"\n\t{\n'
        '\t\t"ControlName"\t"CircularProgressBar"\n'
        '\t\t"fieldName"\t"InvisProgress"\n'
        '\t\t"xpos"\t"10"\n\t\t"ypos"\t"10"\n\t\t"zpos"\t"1"\n'
        '\t\t"wide"\t"260"\n\t\t"tall"\t"80"\n'
        '\t\t"autoResize"\t"0"\n\t\t"pinCorner"\t"0"\n'
        '\t\t"visible"\t"1"\n\t\t"enabled"\t"1"\n'
        f'\t\t"fg_image"\t"{images["fg"]}"\n'
        f'\t\t"bg_image"\t"{images["bg"]}"\n'
        '\t}\n}\n'
    )


def write_watch_screen(weapon_key: str, ctx, handled: set) -> None:
    """
    Кладёт в мод .res экрана часов (см. watch_screen_res) и info.vdf

    info.vdf с ui_version 3 нужен, чтобы игра вообще читала файлы интерфейса
    из папки мода
    """
    from src.data.weapon_quirks import WATCH_SCREEN_RES
    content = watch_screen_res(weapon_key, handled)
    if content is None:
        return
    for rel, text in ((WATCH_SCREEN_RES[weapon_key], content),
                      ("info.vdf", '"tf2sg-watch" { "ui_version" "3" }\n')):
        try:
            target = _under_root(ctx.vpkroot_dir, rel)
            ensure_directory_exists(target.parent)
            with open(target, "w", encoding="utf-8") as out:
                out.write(text)
            logger.info(f"Доп. файл мода записан: {rel}")
        except Exception as exc:
            logger.warning(f"Не удалось записать доп. файл '{rel}': {exc}", exc_info=True)


def _file_content_hash(path: str) -> Optional[str]:
    """
    Быстрый хэш содержимого файла (для дедупликации одинаковых картинок).
    Возвращает hex-строку MD5 или None при ошибке чтения.
    Сравнение по содержимому ловит идентичные картинки даже из разных файлов
    """
    try:
        with open(path, "rb") as f:
            return hashlib.file_digest(f, "md5").hexdigest()
    except OSError:
        return None
