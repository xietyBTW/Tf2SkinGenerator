"""
Откуда берётся VMT для правки и как сохраняется правка (без Qt).

Раньше это жило в ``MainWindowVmtMixin`` вперемешку с показом предупреждений,
а сохранение — в теле диалога. Логика при этом не про виджеты: какой ключ у
предмета, где лежит оригинал в игровых VPK, что дописать при сохранении.
Вынесено сюда, чтобы тем же путём пользовалась веб-страница — иначе правила
пришлось бы написать второй раз и они разъехались бы.

Хранение правок остаётся в ``EditedVMTService``; здесь — их источник и
политика сохранения.
"""

from __future__ import annotations

import os
import re
from typing import List, Optional, Tuple

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Дописывается один раз при сохранении. Не косметика: по нему в чужом моде
#: видно, чем он собран.
WATERMARK = ("// made on Tf2SkinGenerator "
             "https://steamcommunity.com/id/sosatihackeri - Developer(xiety)")


def resolve_target(mode: str, hat_mdl: Optional[str] = None,
                   hat_display: Optional[str] = None) -> Optional[Tuple[str, str]]:
    """
    (ключ, отображаемое имя) для правки VMT — либо None, если режим не годится.

    Ключ у каждого вида предмета свой: у шапки — нормализованный путь MDL, у
    рук — модель предплечья, у персонажа — mdl_key, у оружия — ключ из режима.
    По нему же ищется сохранённая правка, поэтому ошибка тут означает «правка
    потерялась».
    """
    from src.data.player_characters import PLAYER_BODY_MODE_KEYS, PLAYER_CHARACTERS
    from src.data.player_hands import HAND_MODE_KEYS, HAND_MODES
    from src.data.weapons import weapon_key_from_mode

    if not mode:
        return None

    if mode == 'hat':
        if not hat_mdl:
            return None
        key = hat_mdl.replace('\\', '/').lower()
        return key, (hat_display or key)

    if mode in HAND_MODE_KEYS:
        arm = HAND_MODES.get(mode, {}).get('arm_model', '')
        return (arm, arm) if arm else None

    if mode in PLAYER_BODY_MODE_KEYS:
        mdl_key = PLAYER_CHARACTERS.get(mode, {}).get('mdl_key', '')
        return (mdl_key, mdl_key) if mdl_key else None

    key = weapon_key_from_mode(mode)
    return (key, key) if key else None


def extract_original(mode: str, weapon_key: str, tf2_root_dir: str,
                     material_name: Optional[str] = None,
                     language: str = 'en') -> Optional[str]:
    """Путь к извлечённому из игры оригиналу VMT (шапки и остальное)."""
    if mode == 'hat':
        return _extract_hat_vmt(weapon_key, tf2_root_dir, material_name)
    return extract_weapon_vmt(weapon_key, tf2_root_dir, material_name, language)


def original_content(mode: str, weapon_key: str, tf2_root_dir: str,
                     material_name: Optional[str] = None,
                     language: str = 'en') -> Optional[str]:
    """
    СОДЕРЖИМОЕ игрового оригинала.

    Нужно для «вернуть как в игре», когда открыта уже сохранённая правка: без
    него сбросом вернулась бы сама правка.
    """
    path = extract_original(mode, weapon_key, tf2_root_dir, material_name, language)
    if not (path and os.path.exists(path)):
        return None
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()
    except OSError:
        return None


def _extract_hat_vmt(hat_mdl: str, tf2_root_dir: str,
                     material_name: Optional[str] = None) -> Optional[str]:
    """
    VMT шапки через $cdmaterials из кэшированного QC (общий путь с оружием).
    """
    from src.services import decompile_cache, qc_skin_parser

    qc_path = decompile_cache.find_cached_qc_for_weapon(hat_mdl)
    if not qc_path:
        # Нет кэша — без декомпиляции путь к материалам неизвестен.
        return None

    rows = qc_skin_parser.parse_texturegroup_rows(qc_path)
    skin0_textures = list(rows[0]) if rows else []
    if not skin0_textures:
        stem = os.path.splitext(os.path.basename(hat_mdl))[0]
        stem = re.sub(
            r'_(heavy|scout|soldier|pyro|demoman|engineer|medic|sniper|spy)$',
            '', stem, flags=re.IGNORECASE,
        )
        skin0_textures = [stem]

    return _extract_from_qc(qc_path, tf2_root_dir,
                            _material_order(material_name, skin0_textures))


def extract_weapon_vmt(weapon_key: str, tf2_root_dir: str,
                       material_name: Optional[str] = None,
                       language: str = 'en') -> Optional[str]:
    """
    Оригинальный VMT оружия через $cdmaterials из QC.

    Папки материалов берём из декомпилированной модели (авторитетно), а не
    угадываем: QC обычно уже в кэше после превью, иначе декомпилируем на месте.
    """
    import glob

    from src.services import decompile_cache, qc_skin_parser

    qc_path = decompile_cache.find_cached_qc_for_weapon(weapon_key)
    if not qc_path:
        # Класс в имени режима здесь не важен — нужна только модель.
        try:
            from src.services.extract_model_service import ExtractModelService
            ok, _msg, _cancel, data = (
                ExtractModelService.prepare_decompiled_model_files_with_progress(
                    tf2_root_dir, f'scout_{weapon_key}', weapon_key, language=language,
                )
            )
            if ok and data and data.get('decompile_dir'):
                qcs = glob.glob(os.path.join(data['decompile_dir'], '*.qc'))
                qc_path = qcs[0] if qcs else None
        except Exception as exc:
            logger.debug(f"VMT: декомпиляция для {weapon_key} не удалась: {exc}")
            qc_path = None
    if not qc_path:
        return None

    rows = qc_skin_parser.parse_texturegroup_rows(qc_path)
    skin0 = list(rows[0]) if rows else []
    names = _material_order(material_name, skin0)
    if material_name and not skin0:
        names.append(weapon_key)
    if not names:
        names = [weapon_key]
    return _extract_from_qc(qc_path, tf2_root_dir, names)


def _material_order(material_name: Optional[str], skin0: List[str]) -> List[str]:
    """
    Порядок поиска VMT: сначала свой материал, потом материалы skin0.

    Так работает правило наследования: у добавленной пользователем текстуры
    своего VMT в игре нет, и основой становится VMT главного материала.
    """
    if not material_name:
        return list(skin0)
    others = [m for m in skin0 if m.lower() != material_name.lower()]
    return [material_name] + others


def _extract_from_qc(qc_path: str, tf2_root_dir: str,
                     mat_names: List[str]) -> Optional[str]:
    """Ищет VMT в игровых VPK по $cdmaterials модели и кладёт во временный файл."""
    from src.services import qc_skin_parser
    from src.services.game_vpk_reader import GameVpkReader
    from src.services.tf2_paths import TF2Paths

    if not qc_path or not os.path.exists(qc_path):
        return None
    cdmaterials = qc_skin_parser.parse_cdmaterials(qc_path)
    if not cdmaterials or not mat_names:
        return None

    try:
        _, misc_vpk, _ = TF2Paths.resolve(tf2_root_dir)
    except Exception:
        misc_vpk = None
    textures_vpk = TF2Paths.resolve_textures_vpk(tf2_root_dir)

    # Хэндлы VPK берутся из общего кэша: каталог парсится один раз на поток,
    # повторные открытия редактора мгновенны. Закрывать их нельзя.
    vmt_content: Optional[str] = None
    vmt_filename = 'material.vmt'
    with GameVpkReader([misc_vpk, textures_vpk]) as reader:
        if not reader.paks:
            return None
        for mat_name in mat_names:
            info = reader.find_vmt(cdmaterials, mat_name.lower())
            if info:
                vmt_content = info[1]
                vmt_filename = os.path.basename(info[0])
                break
    if not vmt_content:
        return None

    temp_dir = os.path.join('tools', 'temp_vmt_extract')
    os.makedirs(temp_dir, exist_ok=True)
    out_path = os.path.join(temp_dir, vmt_filename)
    try:
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(vmt_content)
        return out_path
    except OSError:
        return None


def save_edit(edit_key: str, content: str,
              original: Optional[str] = None) -> Tuple[bool, str, str]:
    """
    Сохраняет правку VMT.

    Сломанный синтаксис не сохраняем: в игре такой материал становится
    невидимым, а причина находится далеко от места ошибки.

    Игровой оригинал фиксируется бэкапом ОДИН раз — иначе «вернуть как в игре»
    после второй правки вернуло бы первую.

    Returns:
        (успех, сообщение об ошибке, содержимое с ватермарком).
    """
    from src.services.edited_vmt_service import EditedVMTService
    from src.services.vmt_service import VMTService

    valid, error, line = VMTService.validate_vmt_syntax(content)
    if not valid:
        return False, (f'{error} (строка {line})' if line else error), content

    if WATERMARK.strip() not in content:
        content = content.rstrip() + '\n' + WATERMARK + '\n'

    if edit_key:
        if original is not None and not EditedVMTService.has_original_backup(edit_key):
            EditedVMTService.save_original_backup(edit_key, original)
        EditedVMTService.save_edited_vmt(edit_key, content)
    return True, '', content
