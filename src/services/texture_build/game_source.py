"""
Оригиналы игры и общие записи VMT: VTF/VMT материала из игровых VPK,
$basetexture родного VMT, правка VMT человека поверх записанного
"""

import os
from pathlib import Path
from typing import Callable, Optional, Tuple

from src.services import qc_skin_parser
from src.services.tf2_vpk_extract_service import TF2VPKExtractService
from src.services.vmt_service import VMTService
from src.shared.file_utils import copy_file_safe
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def write_material_vmt(target_vmt_path, base_vmt_path, cdmaterials_path: str, tex_name: str) -> None:
    """
    Записывает VMT вторичного материала (extra / variant / shared / BLU)

    Если базовый VMT существует - копирует его и переставляет $basetexture
    на tex_name; иначе создаёт VMT из шаблона по $cdmaterials
    """
    if base_vmt_path.exists():
        copy_file_safe(base_vmt_path, target_vmt_path)
        VMTService.update_vmt_basetexture_path(str(target_vmt_path), cdmaterials_path, tex_name)
    else:
        VMTService.create_vmt_template_from_cdmaterials(str(target_vmt_path), cdmaterials_path, tex_name)
    logger.info(f"Создан VMT вторичного материала: {target_vmt_path.name}")


def get_original_vtf_bytes(
    mat_name: str,
    cdmaterials_paths,          # str | list[str] | None
    textures_vpk: Optional[str],
    misc_vpk: Optional[str],
    log_not_found: bool = True,
) -> Optional[bytes]:
    """
    Извлекает оригинальный VTF из игровых VPK-файлов

    Crowbar добавляет префикс ``console\\`` ко всем $cdmaterials путям.
    В реальных VPK этого префикса нет, поэтому мы его снимаем.
    Пути вида ``console\\..\\..\\effects`` (для частиц) пропускаются

    Args:
        mat_name:          Имя материала (без расширения).
        cdmaterials_paths: Один путь или список путей из $cdmaterials QC.
                           Crowbar-префикс ``console/`` снимается автоматически.
        textures_vpk:      Путь к tf2_textures_dir.vpk.
        misc_vpk:          Путь к tf2_misc_dir.vpk

    Returns:
        Байты VTF или None если не найдено
    """
    try:
        from src.services.tf2_vpk_extract_service import _open_vpk_cached

        mat_lower = mat_name.lower()

        # Нормализуем cdmaterials_paths в список
        if cdmaterials_paths is None:
            raw_paths: list = []
        elif isinstance(cdmaterials_paths, str):
            raw_paths = [cdmaterials_paths]
        else:
            raw_paths = list(cdmaterials_paths)

        candidates: list = []

        # Кандидаты из QC ($cdmaterials) - общей нормализацией: она же
        # разрешает относительные пути ('../../effects' рядом с
        # 'models/player/spy' - это 'models/effects', где лежит убер-эффект)
        cdmats = qc_skin_parser.resolve_cdmaterials(raw_paths)
        candidates += [f"materials/{cdmat}/{mat_lower}.vtf" for cdmat in cdmats]

        # Стандартные fallback-пути для оружий и персонажей
        candidates += [
            f"materials/models/weapons/c_models/{mat_lower}/{mat_lower}.vtf",
            f"materials/models/weapons/c_items/{mat_lower}.vtf",
            f"materials/models/workshop_partner/weapons/c_models/{mat_lower}/{mat_lower}.vtf",
            f"materials/models/workshop/weapons/c_models/{mat_lower}/{mat_lower}.vtf",
            f"materials/models/player/{mat_lower}/{mat_lower}.vtf",
        ]

        for vpk_path in filter(None, [textures_vpk, misc_vpk]):
            if not os.path.exists(vpk_path):
                continue
            try:
                pak = _open_vpk_cached(vpk_path)
                if pak is None:
                    continue
                for vtf_path in candidates:
                    try:
                        data = pak[vtf_path].read()
                        logger.debug(f"Оригинальный VTF из игры: {vtf_path}")
                        return data
                    except KeyError:
                        continue
            except Exception as _e:
                logger.debug(f"VPK ошибка при поиске оригинала {mat_name}: {_e}")

        # Прямые пути угадывают не всё: у служебных материалов персонажей
        # (глаза, убер-скин, зомби) VTF лежит не рядом со своим VMT, а в
        # общей папке - `models/player/spy/eyeball_r.vmt` указывает на
        # `models/player/shared/eyeball_r`. Знает об этом только сам VMT,
        # поэтому последним шагом идём общей цепочкой VMT -> $basetexture
        data, has_own_texture = vtf_via_vmt(
            mat_lower, cdmats, textures_vpk, misc_vpk)
        if data:
            return data
        if not has_own_texture:
            # Не потеря, а неверный вопрос: у EyeRefract (глаза персонажей)
            # $basetexture нет вовсе - картинка собирается из $Iris и
            # $CorneaTexture. Копировать в мод тут нечего
            logger.info(
                f"У материала '{mat_name}' нет своей текстуры "
                f"($basetexture в VMT отсутствует) - оригинал не нужен"
            )
            return None

        if log_not_found:
            logger.warning(
                f"Оригинальный VTF не найден в игре для '{mat_name}' "
                f"(cdmaterials={cdmaterials_paths})"
            )
        else:
            logger.debug(
                f"Shared texture не в основном cdmaterials, пропускаем: '{mat_name}'"
            )
        return None

    except Exception as exc:
        logger.warning(f"get_original_vtf_bytes: {exc}")
        return None


def vtf_via_vmt(mat_lower: str, cdmaterials: list,
                 textures_vpk: str, misc_vpk: str) -> Tuple[Optional[bytes], bool]:
    """Сырые байты VTF через цепочку VMT -> $basetexture -> VTF

    Та же единая цепочка, что у превью (MaterialResolver), но БЕЗ краски и
    без PNG: в мод должен лечь ровно тот файл, что лежит в игре - командный
    цвет из VMT движок накладывает сам

    Returns:
        (байты | None, есть ли у материала своя текстура). Второе нужно
        ради лога: у шейдеров вроде EyeRefract $basetexture нет вовсе, и
        «оригинал не найден» для них - не потеря, а неверный вопрос
    """
    try:
        from src.services.game_vpk_reader import GameVpkReader
        from src.services.material_resolver import MaterialResolver
        reader = GameVpkReader([textures_vpk, misc_vpk])
        try:
            resolver = MaterialResolver(reader, "", apply_tint=False)
            info = resolver.describe(mat_lower, list(cdmaterials))
            if info.vmt_path and not info.basetexture:
                return None, False
            return resolver.vtf_bytes(mat_lower, list(cdmaterials)), True
        finally:
            reader.close()
    except Exception as exc:                       # noqa: BLE001
        logger.debug(f"VTF через VMT не найден для '{mat_lower}': {exc}")
        return None, True


def extract_original_vmt(
    cdmaterials_path: Optional[str],
    texture_filename: str,
    tf2_textures_vpk: Optional[str],
    tf2_misc_vpk: str,
    decompile_dir,
) -> Optional[str]:
    """
    Извлекает оригинальный VMT текстуры из игровых VPK

    Порядок: tf2_textures_dir.vpk -> tf2_misc_dir.vpk (Valve кладёт текстуры
    то туда, то туда). Возвращает путь к извлечённому VMT или None
    """
    if not cdmaterials_path:
        return None
    if tf2_textures_vpk:
        vmt = TF2VPKExtractService.extract_vmt_file(
            tf2_textures_vpk, cdmaterials_path, texture_filename, decompile_dir
        )
        if vmt:
            logger.info(f"Извлечен VMT файл: {vmt}")
            return vmt
    vmt = TF2VPKExtractService.extract_vmt_file(
        tf2_misc_vpk, cdmaterials_path, texture_filename, str(decompile_dir)
    )
    if vmt:
        logger.info(f"Извлечен VMT файл из misc: {vmt}")
    return vmt


def read_vmt_basetexture(vmt_path: str) -> Optional[str]:
    """Читает $basetexture из VMT (путь к VTF без расширения, как в файле)

    Нужно для «use game original»: у головы/варианта имя VTF ≠ имя материала
    (demoman_head_red -> $basetexture "models/player/demo/demoman_head"), поэтому
    реальный VTF резолвим именно по $basetexture, а не по имени материала"""
    try:
        import re as _re_bt
        with open(vmt_path, encoding='utf-8', errors='ignore') as _f:
            _txt = _f.read()
        m = _re_bt.search(r'"?\$basetexture"?\s+"([^"]+)"', _txt, _re_bt.IGNORECASE)
        return m.group(1).strip() if m else None
    except Exception:
        return None


def find_original_vmt(name, ctx, slots):
    """Родной VMT материала по путям $cdmaterials модели (или None)

    Пути разрешённые, как у поиска VTF (get_original_vtf_bytes): у тела
    шпиона убер-эффект invulnfx лежит по `..\\..\\effects` рядом с
    `models\\player\\spy`, и по сырому пути его VMT не находился
    """
    for _cd in qc_skin_parser.resolve_cdmaterials(
            list(slots.original_cdmaterials_paths or [])):
        found = extract_original_vmt(
            _cd, name, slots.tf2_textures_vpk, slots.tf2_misc_vpk,
            ctx.decompile_dir)
        if found and os.path.exists(found):
            return found
    return None


def game_texture(name, ctx, slots) -> Optional[str]:
    """$basetexture родного VMT материала, если такая текстура есть в игре
    (путь без materials/ и .vtf), иначе None"""
    from src.services.tf2_vpk_extract_service import _open_vpk_cached

    found = find_original_vmt(name, ctx, slots)
    bt = read_vmt_basetexture(found) if found else None
    if not bt:
        return None
    bt = bt.replace('\\', '/').strip().strip('/')
    want = f"materials/{bt.lower()}.vtf"
    for vpk_path in filter(None, (slots.tf2_textures_vpk, slots.tf2_misc_vpk)):
        try:
            pak = _open_vpk_cached(vpk_path) if os.path.exists(vpk_path) else None
        except Exception:   # noqa: BLE001 - нет архива: проверим следующий
            pak = None
        if pak is not None and want in pak:
            return bt
    return None


def basetexture_fps(vmt_path) -> Optional[float]:
    """Частота прокси AnimatedTexture, который листает $basetexture (или
    None). Только он: у тел есть и прокси огня по $detail"""
    from src.services import vmt_parse

    try:
        text = Path(vmt_path).read_text(encoding='utf-8', errors='replace')
    except OSError:
        return None
    for node in vmt_parse.blocks_named(vmt_parse.parse(text).root, "animatedtexture"):
        var = str(node.get("animatedtexturevar") or "").strip().lstrip("$").lower()
        if var == "basetexture":
            try:
                return float(node.get("animatedtextureframerate"))
            except (TypeError, ValueError):
                return None
    return None


def basetexture_chosen(edited_vmt, game_vmt) -> bool:
    """В правке $basetexture другой, чем в игровом VMT материала

    Без игрового VMT сравнить не с чем - считаем, что правили старый путь
    (как было до этой проверки)
    """
    def norm(path):
        base = read_vmt_basetexture(str(path)) if path else None
        if not base:
            return None
        base = base.replace('\\', '/').lower().strip('/')
        base = base[len('materials/'):] if base.startswith('materials/') else base
        return base[:-4] if base.endswith('.vtf') else base

    if not (game_vmt and Path(game_vmt).exists()):
        return False
    edited, game = norm(edited_vmt), norm(game_vmt)
    return bool(edited and game and edited != game)


def apply_edited_vmt(name, vmt_path, orig_vmt, slots, own_texture: bool,
                      strip_paints: bool = False) -> None:
    """
    Правка VMT из редактора поверх того, что записала сборка

    Доп. материалы (голова тела, «Прочее», второй материал шапки) правку
    не брали вовсе: редактор её сохранял, а в мод шёл игровой VMT. Правило
    то же, что у главного (_write_main_vmt): own_texture - VTF материала
    лежит в моде, и $basetexture правки переводится на него, если человек
    не выбрал в правке свой. strip_paints - шапка без «Красок из игры»:
    прокси краски снимаются и здесь, как у главного, иначе второй материал
    красился бы, а главный нет
    """
    from src.services.edited_vmt_service import EditedVMTService

    edited = EditedVMTService.get_edited_vmt(name)
    if edited and os.path.exists(edited):
        copy_file_safe(edited, vmt_path)
        if own_texture and not basetexture_chosen(edited, orig_vmt):
            VMTService.update_vmt_basetexture_path(
                str(vmt_path), slots.patched_cdmaterials_path, name)
        logger.info(f"Доп. материал '{name}': отредактированный VMT")
    if strip_paints and Path(vmt_path).exists():
        VMTService.remove_paint_proxies(str(vmt_path))


def texture_reader(local_root: Optional[Path], vpk_paths) -> Callable[[str], Optional[bytes]]:
    """Читалка текстур по пути из VMT: сначала файлы мода
    (`local_root`/materials), затем VPK игры"""
    from src.services.game_vpk_reader import GameVpkReader

    paks = [p for p in (vpk_paths or []) if p]
    reader = GameVpkReader(paks) if paks else None

    def read(texture: str) -> Optional[bytes]:
        from src.services.mod_textures import texture_key
        key = texture_key(texture)
        if local_root is not None:
            local = Path(local_root) / "materials" / f"{key}.vtf"
            if local.is_file():
                return local.read_bytes()
        return reader.find_vtf_for_basetexture(key) if reader else None

    return read
