"""
Работа с VPK файлами: распаковка, сборка, конвертация текстур.
"""

import os
import shutil
from pathlib import Path
from dataclasses import dataclass
from typing import Tuple, Optional, Callable
from .build_context import BuildContext
from .build_request import BuildRequest
from .build_service import BuildService
from .texture_service import TextureService
from .packaging_service import PackagingService
from .model_service import ModelService
from .model_build_service import ModelBuildService
from .vpk_texture_builder import VpkTextureBuilder
from .vpk_model_pipeline import VpkModelPipeline
from .tf2_paths import TF2Paths
from .debug_service import DebugService
from .smd_service import SMDService
from .decompile_cache import save_to_cache
from src.data.weapons import SPECIAL_MODES
from src.data.player_hands import HAND_MODE_KEYS
from src.data.player_characters import (
    PLAYER_BODY_MODE_KEYS,
    SPY_MASK_MODE_KEY,
    SPY_MDL_PATH,
    SPY_DISGUISE_MASKS,
)
from src.shared.logging_config import get_logger
from src.shared.constants import DirectoryPaths, EXTRA_TEX_USE_GAME_ORIGINAL
from src.shared.file_utils import ensure_directory_exists, copy_file_safe
from src.shared.validators import validate_build_params

logger = get_logger(__name__)


@dataclass
class _MaterialPlan:
    """План материалов сборки: что и под какими именами строить (результат
    анализа $texturegroup + изоляции плеч + подавления для кастомных моделей).
    QC к этому моменту уже пропатчен/синхронизирован (side effect _plan_materials)."""
    tg_structure: dict
    blu_row: list
    extra_materials: list
    blu_is_team: bool
    blacklisted_extra: list
    texture_filename: str
    blu_mode: str
    has_skins: bool
    shoulder_iso: list
    image_path: object
    skin_build_data: object
    game_vmt_name: str


class VPKService:
    """Главный конвейер сборки VPK файлов. Детали ошибок — в логах."""
    
    @staticmethod
    def build_with_progress(
        request,
        *,
        model_file_callback: Optional[Callable[[], Optional[str]]] = None,
        extra_texture_callback: Optional[Callable[[str, str], Optional[str]]] = None,
        extra_model_callback: Optional[Callable[[str, str], Optional[str]]] = None,
        texture_mismatch_callback: Optional[Callable[[str], bool]] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        sub_progress_callback: Optional[Callable[[int, str], None]] = None,
        cancel_callback: Optional[Callable[[], bool]] = None,
    ) -> Tuple[bool, str, bool]:
        # Здесь нужны лишь те поля, что используются ДО build_vpk (ветка custom,
        # выбор спец-режима, гейтинг колбэка). Остальное распакует сам build_vpk.
        r = request
        mode = r.mode
        image_path = r.image_path
        size = r.size
        format_type = r.format_type
        flags = r.flags or []
        vtf_options = r.vtf_options or {}
        export_folder = r.export_folder
        filename = r.filename
        language = r.language
        custom_vtf_path = r.custom_vtf_path
        custom_vpk_source_path = r.custom_vpk_source_path
        hat_mdl_path = r.hat_mdl_path
        replace_model_enabled = r.replace_model_enabled
        logger.info(f"[BUILD] режим={r.mode!r}, isolate_shoulders={r.isolate_shoulders}, force_team={r.force_team}")

        from src.data.translations import TRANSLATIONS
        t = TRANSLATIONS.get(language, TRANSLATIONS['en'])

        def emit_progress(value: int, message: str) -> None:
            if progress_callback:
                progress_callback(value, message)

        def emit_sub(pct: int, label: str) -> None:
            if sub_progress_callback:
                sub_progress_callback(pct, label)

        def is_cancelled() -> bool:
            return bool(cancel_callback and cancel_callback())
        
        try:
            logger.info(f"Начало сборки VPK: {filename}")
            emit_progress(5, t.get('build_init', 'Initializing build...'))

            # ── Кастомный мод (пользователь загрузил готовый VPK) ───────── #
            if mode == "custom":
                from src.services.custom_vpk_service import CustomVPKService
                if not custom_vpk_source_path:
                    return False, t.get('error_no_custom_vpk', 'No custom VPK file loaded.'), False

                emit_progress(10, t.get('build_extracting', 'Extracting model...'))
                success, message = CustomVPKService.build_custom_mod(
                    custom_vpk_source_path=custom_vpk_source_path,
                    image_path=image_path,
                    size=size,
                    format_type=format_type,
                    flags=flags,
                    vtf_options=vtf_options,
                    export_folder=export_folder,
                    filename=filename,
                    extra_texture_callback=extra_texture_callback,
                    language=language,
                    sub_progress_callback=emit_sub,
                    custom_vtf_path=custom_vtf_path,
                    hat_mdl_path=hat_mdl_path,
                )
                emit_progress(100 if success else 0,
                              t.get('build_completed', 'Build completed') if success
                              else t.get('build_error_status', 'Build error'))
                return success, message, False

            # ── Скайбокс: свой пайплайн (панорама/грани → materials/skybox) ─ #
            # Ранняя ветка как у custom: _validate_build_params требует
            # image_path/TF2 и не знает про 6 граней — валидация своя.
            from src.data.skyboxes import SKYBOX_MODE
            if mode == SKYBOX_MODE:
                from src.services.skybox_service import SkyboxService
                emit_progress(10, t.get('build_skybox_faces', 'Building sky faces...'))
                success, message = SkyboxService.build_skybox_vpk(
                    request,
                    sub_progress_callback=emit_sub,
                    cancel_callback=cancel_callback,
                )
                if is_cancelled():
                    return False, t.get('build_cancelled', 'Build cancelled by user'), True
                emit_progress(100 if success else 0,
                              t.get('build_completed', 'Build completed') if success
                              else t.get('build_error_status', 'Build error'))
                return success, message, False

            is_special_mode = mode in SPECIAL_MODES.values()

            _sub_label_init = "Preparing..." if language == "en" else "Подготовка..."
            emit_sub(-1, _sub_label_init)

            # Прогресс эмитится самим build_vpk на реальных границах стадий
            # (декомпиляция / текстуры / компиляция / упаковка) — без
            # потока-имитатора с фиксированными процентами.
            if is_special_mode:
                emit_progress(20, t.get('build_processing', 'Processing texture...'))
            else:
                emit_progress(10, t.get('build_extracting', 'Extracting model...'))

            # Параметры сборки целиком в request; build_vpk сам их распакует.
            # Колбэки — runtime UI-потока, передаём отдельно. model_file_callback
            # имеет смысл только при включённой замене модели.
            success, message = VPKService.build_vpk(
                request,
                model_file_callback=model_file_callback if replace_model_enabled else None,
                extra_texture_callback=extra_texture_callback,
                extra_model_callback=extra_model_callback,
                texture_mismatch_callback=texture_mismatch_callback,
                sub_progress_callback=emit_sub,
                progress_callback=progress_callback,
                cancel_callback=cancel_callback,
            )

            if is_cancelled():
                return False, t.get('build_cancelled', 'Build cancelled by user'), True

            if success:
                emit_sub(100, "Done" if language == "en" else "Готово")
                emit_progress(100, t.get('build_completed', 'Build completed'))
                return True, message, False

            emit_progress(0, t.get('build_error_status', 'Build error'))
            return False, message, False
        except Exception as e:
            error_msg = str(e)
            logger.critical(f"Критическая ошибка при сборке: {error_msg}", exc_info=True)
            emit_progress(0, t.get('build_critical_error', 'Critical error'))
            return False, error_msg, False

    @staticmethod
    def _ready_model_texture_mismatch(
        model_ready_path: Optional[str],
        qc_path: str,
        weapon_key: str,
        decompile_dir: str,
        language: str,
    ) -> Optional[str]:
        """
        Режим «готовая модель»: возвращает текст предупреждения, если материалы
        пользовательского SMD не совпадают с оригиналом, иначе None.
        Чистая проверка (только сравнение + лог) — решение продолжать/отменить
        принимает вызывающий код через texture_mismatch_callback.
        """
        if not (model_ready_path and os.path.exists(model_ready_path)
                and model_ready_path.lower().endswith('.smd')):
            return None
        try:
            user_materials = SMDService.extract_unique_materials(model_ready_path)
            if not user_materials:
                return None
            original_smd = VpkModelPipeline._find_decompiled_reference_smd(
                qc_path, weapon_key, decompile_dir)
            if not original_smd:
                return None
            original_materials = SMDService.extract_unique_materials(original_smd)
            if not original_materials:
                return None
            if user_materials == original_materials:
                logger.info(f"[MODEL READY] Текстуры SMD совпадают с оригиналом: {user_materials}")
                return None

            missing_in_user = original_materials - user_materials
            extra_in_user = user_materials - original_materials
            lines = []
            if language == "ru":
                lines.append("Текстуры в вашем SMD файле не совпадают с оригинальной моделью.\n")
                if missing_in_user:
                    lines.append("Отсутствуют (есть в оригинале, нет у вас):")
                    lines += [f"  • {m}" for m in sorted(missing_in_user)]
                if extra_in_user:
                    lines.append("Лишние (есть у вас, нет в оригинале):")
                    lines += [f"  • {m}" for m in sorted(extra_in_user)]
                lines.append("\nПродолжить сборку с этими текстурами?")
            else:
                lines.append("Textures in your SMD file do not match the original model.\n")
                if missing_in_user:
                    lines.append("Missing (in original, not in yours):")
                    lines += [f"  • {m}" for m in sorted(missing_in_user)]
                if extra_in_user:
                    lines.append("Extra (in yours, not in original):")
                    lines += [f"  • {m}" for m in sorted(extra_in_user)]
                lines.append("\nContinue building with these textures?")

            warning_msg = "\n".join(lines)
            logger.warning(f"[MODEL READY] Несовпадение текстур SMD:\n{warning_msg}")
            return warning_msg
        except Exception as exc:
            logger.warning(f"[MODEL READY] Ошибка проверки текстур SMD: {exc}", exc_info=True)
            return None

    @staticmethod
    def _write_hand_mirror_vmts(ctx, mode: str, weapon_key: str,
                                original_cdmaterials_path: Optional[str],
                                vtf_output_path) -> None:
        """
        Для рук и MIRROR_VMT_WEAPON_KEYS дублирует VMT по ОРИГИНАЛЬНОМУ пути из
        $cdmaterials. Причина: эти модели ссылаются на оригинальный путь
        (materials/models/player/spy/...), а не на пропатченный console\\-путь,
        иначе мод игнорируется. VTF не дублируются — зеркальный VMT указывает на
        те же файлы (по console\\-пути внутри мод-VPK).
        """
        from src.data.player_hands import HAND_MODE_KEYS as _HAND_MODE_KEYS
        from src.data.weapons import MIRROR_VMT_WEAPON_KEYS as _MIRROR_KEYS
        if not ((mode in _HAND_MODE_KEYS or weapon_key in _MIRROR_KEYS)
                and original_cdmaterials_path):
            return
        orig_mat_rel = "materials/" + original_cdmaterials_path.replace('\\', '/').strip().rstrip('/')
        orig_vtf_dir = ctx.vpkroot_dir
        for _part in orig_mat_rel.rstrip('/').split('/'):
            orig_vtf_dir = orig_vtf_dir / _part
        if orig_vtf_dir == vtf_output_path:
            logger.debug("Оригинальный и пропатченный пути совпадают, зеркало не нужно")
            return
        ensure_directory_exists(orig_vtf_dir)
        for _vmt_src in vtf_output_path.glob("*.vmt"):
            _vmt_mirror = orig_vtf_dir / _vmt_src.name
            if not _vmt_mirror.exists():
                copy_file_safe(_vmt_src, _vmt_mirror)
                logger.info(f"Зеркальный VMT по оригинальному пути: {_vmt_mirror.name}")

    @staticmethod
    def _purge_dir_contents(directory: Path, label: str) -> None:
        """
        Удаляет всё содержимое директории (файлы и поддиректории), не трогая саму
        папку. Для очистки временных папок после сборки. Ошибки не фатальны — лог.
        """
        if not directory.exists():
            return
        try:
            for entry in directory.iterdir():
                try:
                    if entry.is_file() or entry.is_symlink():
                        entry.unlink()
                    elif entry.is_dir():
                        shutil.rmtree(entry)
                except Exception as e:
                    logger.warning(f"Не удалось удалить {entry}: {e}", exc_info=True)
            logger.debug(f"Очищена папка {label}")
        except Exception as e:
            logger.warning(f"Не удалось очистить папку {label}: {e}", exc_info=True)

    @staticmethod
    def _finalize_build_success(ctx, vpk_path: str, vmt_to_delete, language: str,
                                debug_mode: bool, t: dict) -> str:
        """
        Постобработка успешной сборки: удаляет отредактированный пользователем VMT,
        чистит временные папки редактора, удаляет temp-директорию сборки и собирает
        итоговое сообщение (с накопленными предупреждениями ctx.warnings).
        """
        if vmt_to_delete:
            from src.services.edited_vmt_service import EditedVMTService
            if EditedVMTService.delete_edited_vmt(vmt_to_delete):
                logger.info(f"Удален отредактированный VMT файл: {vmt_to_delete}")

        # Чистим временные папки редактора VMT (мусор от достанных из игры VMT).
        VPKService._purge_dir_contents(DirectoryPaths.TEMP_VMT_EXTRACT_DIR, "temp_vmt_extract")
        VPKService._purge_dir_contents(Path("tools/backupVMT"), "backupVMT")

        ctx.cleanup(on_error=False, keep_on_error=False, debug_mode=debug_mode)

        success_message = t.get('vpk_success', 'VPK successfully created: {path}').format(path=vpk_path)
        # Показываем накопленные предупреждения (напр. не найденную игровую
        # текстуру) — иначе пользователь узнает о фиолете только в игре.
        if ctx.warnings:
            _hdr = ("\n\nВнимание:" if language == "ru" else "\n\nWarnings:")
            success_message += _hdr + "".join(f"\n- {w}" for w in ctx.warnings)
        return success_message

    @staticmethod
    def _resolve_weapon_key(mode: str, hat_mdl_path: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """
        Определяет weapon_key (ключ модели/файлов) по режиму сборки.

        Для оружия — суффикс mode (scout_c_scattergun → c_scattergun); для рук —
        ключ arm-модели; для тела/масок шпиона — стем MDL; для шапки — стем
        hat_mdl_path.

        Returns:
            (weapon_key, None) при успехе либо (None, error_message), если для
            режима рук не задана arm-модель.
        """
        if mode == "hat" and hat_mdl_path:
            weapon_key = Path(hat_mdl_path).stem
            logger.info(f"[HAT] hat_mdl_path={hat_mdl_path!r}  →  weapon_key={weapon_key!r}")
            return weapon_key, None
        if mode in HAND_MODE_KEYS:
            from src.data.player_hands import HAND_MODES as _HAND_MODES
            arm_key = _HAND_MODES.get(mode, {}).get('arm_model', '')
            if not arm_key:
                return None, f"No arm_model defined for hand mode: {mode}"
            return arm_key, None
        if mode in PLAYER_BODY_MODE_KEYS:
            from src.data.player_characters import PLAYER_CHARACTERS as _PC
            mdl_path = _PC.get(mode, {}).get('mdl_path', '')
            return (Path(mdl_path).stem if mdl_path else mode), None
        if mode == SPY_MASK_MODE_KEY:
            # Маски маскировки: тот же MDL, что и для скина шпиона
            return Path(SPY_MDL_PATH).stem, None
        return (mode.split('_', 1)[1] if '_' in mode else mode), None

    @staticmethod
    def _apply_shoulder_isolation(
        ctx, mode, qc_path, weapon_key, tg_structure,
        orig_main_pre_restrict, image_path, blu_image_path,
        panel_extra_textures, panel_blu_textures, isolate_shoulders,
    ):
        """
        Изоляция плеч/тела вьюмодели рук + команд-промоушен нейтральных
        материалов. Переименовывает общий с миром материал плеч в vm_* в
        $texturegroup и в самих SMD (reference + bodygroup) ДО компиляции,
        плюс синтезирует командные варианты. Только для режимов рук.

        Returns:
            (shoulder_iso, image_path) — список [(new_name, orig_name,
            source_path|None)] для записи материалов ниже и (возможно
            перенаправленный) image_path главной текстуры.
        """
        _shoulder_iso = []   # [(new_name, orig_name, source_path|None)]
        if mode not in HAND_MODE_KEYS:
            return _shoulder_iso, image_path
        from src.data.player_hands import get_hand_textures as _ght_hands
        from src.services.qc_skin_parser import detect_shoulder_materials
        from src.data.material_filter import is_editable_material as _is_edit_sh
        _whitelist = [n for _, n in _ght_hands(mode)]
        # Материалы РЕАЛЬНОГО меша (из reference SMD), а не полная
        # skin-таблица red_row (там варианты/ганслингер/blue).
        _ref_smd = VpkModelPipeline._find_decompiled_reference_smd(
            qc_path, weapon_key, ctx.decompile_dir
        )
        _mesh_mats = SMDService.ordered_unique_materials(_ref_smd) if _ref_smd else []
        _shoulders = detect_shoulder_materials(
            _mesh_mats or tg_structure.get('red_row', []), _whitelist
        )
        _shoulders = [s for s in _shoulders if _is_edit_sh(s)]

        # Источник текстуры каждого плеча: карточка из panel_extra
        # ИЛИ image_path (если плечи были col0/«главной» — тогда их
        # текстура ушла в from_path и была выкинута из panel_extra).
        _pet = panel_extra_textures or {}
        def _shoulder_src(s):
            v = _pet.get(s)
            if not v:
                _sl = s.lower()
                v = next((vv for kk, vv in _pet.items() if kk.lower() == _sl), None)
            if v and os.path.isfile(v):
                return v
            if (s.lower() == str(orig_main_pre_restrict).lower()
                    and image_path and image_path != EXTRA_TEX_USE_GAME_ORIGINAL
                    and os.path.isfile(str(image_path))):
                return image_path
            return None
        _srcs = {s: _shoulder_src(s) for s in _shoulders}
        _has_user_shoulder = any(_srcs.values())
        _do_iso = bool(_shoulders) and (isolate_shoulders or _has_user_shoulder)
        logger.info(
            f"[SHOULDER ISO] флаг={isolate_shoulders}, плечи={_shoulders}, "
            f"источники={ {s: bool(p) for s, p in _srcs.items()} }, изолируем={_do_iso}"
        )
        if not _do_iso:
            _shoulders = []

        # ── Команд-промоушен нейтральных материалов (через RED/BLU
        # переключатель = групповая логика): синие переопределения
        # из skin_build_data → командные варианты. ──
        _promo = {}            # {mat_lower: variant_name}
        _variant_entries = []  # [(variant, orig_mat, src_path)]
        _shoulder_blue_user = {}  # {red_shoulder_lower: blue_path} — правка синих плеч (из главной BLU)
        # Промоушен: НЕЙТРАЛЬНЫЙ материал (нет своего blue-варианта в
        # blu_row) с загруженной СИНЕЙ текстурой → делаем командным.
        # Уже-командные (medic_hands_red→medic_hands_blue в blu_row) и
        # плечи — НЕ трогаем (их ведёт нативный BLU-блок / изоляция).
        if panel_blu_textures:
            from src.services import qc_skin_parser as _qsp
            _rows_now = ModelBuildService._parse_texturegroup_rows(qc_path) or []
            _neutral = {m.lower() for m in _qsp.neutral_materials(_rows_now)}
            _sh_set = {s.lower() for s in _shoulders}
            for _m, _bp in panel_blu_textures.items():
                _ml = _m.lower()
                if (_ml in _neutral and _ml not in _sh_set
                        and _bp and os.path.isfile(str(_bp))):
                    _var = (_m[:-4] + '_blue') if _ml.endswith('_red') else (_m + '_blue')
                    _var = SMDService._sanitize_material_name(_var)
                    _promo[_ml] = _var
                    _variant_entries.append((_var, _m, _bp))
            if _promo:
                logger.info(f"[TEAM PROMO] нейтральные → командные: {_promo}")

        if _shoulders or _promo:
            _rename = {
                s: SMDService._sanitize_material_name(f"vm_{s}")
                for s in _shoulders
            }
            # ── Синяя команда: BLU-вариант плеча по соглашению имён
            # (engineer_red → engineer_blue); фолбэк — та же колонка
            # blu-строки texturegroup. Тоже изолируем (vm_engineer_blue),
            # иначе синий игрок увидит оригинал/фиолет. ──
            _red_row = tg_structure.get('red_row', []) or []
            _blu_row = tg_structure.get('blu_row', []) or []
            _blue_iso = []   # [(vm_blue, orig_blue, is_main, red_shoulder)]
            for s in _shoulders:
                _sl = s.lower()
                _bv = None
                if _sl.endswith('_red'):
                    _bv = s[:-4] + '_blue'
                else:
                    _col = next((i for i, m in enumerate(_red_row) if m.lower() == _sl), None)
                    if _col is not None and _col < len(_blu_row):
                        _cand = _blu_row[_col]
                        if _cand and _cand.lower() != _sl:
                            _bv = _cand
                if not _bv or _bv.lower() == _sl:
                    continue   # команд-нейтральный материал
                _rename[_bv] = SMDService._sanitize_material_name(f"vm_{_bv}")
                _blue_iso.append((_rename[_bv], _bv,
                                  s.lower() == str(orig_main_pre_restrict).lower(),
                                  s))

            _rows = ModelBuildService._parse_texturegroup_rows(qc_path) \
                or [tg_structure.get('red_row', [])]
            # Промоушен нейтральных в командные (синие строки → варианты),
            # затем переименование плеч на vm_*.
            if _promo:
                from src.services.qc_skin_parser import apply_team_promotions
                _rows = apply_team_promotions(_rows, _promo)
            _tg = ModelBuildService.generate_renamed_texturegroup(_rows, _rename)
            if _tg:
                ModelBuildService.replace_texturegroup_in_qc(qc_path, _tg)
            # ГЛАВНОЕ: studiomdl берёт имя материала skin 0 из SMD,
            # поэтому переименовываем материал в самих SMD (reference
            # + bodygroup), иначе модель ссылается на старое имя и
            # текстура становится фиолетовой.
            _smds = []
            if _ref_smd:
                _smds.append(_ref_smd)
            try:
                _smds += ModelBuildService.extract_extra_body_smds(qc_path, weapon_key) or []
            except Exception as _e:
                logger.debug(f"[SHOULDER ISO] не удалось собрать доп. body-SMD: {_e}")
            _rmap_smd = {s.lower(): _rename[s] for s in _shoulders}
            for _sp in _smds:
                try:
                    _n = SMDService.rename_materials_in_smd(_sp, _rmap_smd)
                    if _n:
                        logger.info(f"[SHOULDER ISO] SMD {os.path.basename(_sp)}: заменено {_n} материалов")
                except Exception as _e:
                    logger.warning(f"[SHOULDER ISO] не удалось переименовать в {_sp}: {_e}")
            _shoulder_iso = [(_rename[s], s, _srcs[s]) for s in _shoulders]
            # Синие плечи: источник — пользовательская BLU-картинка
            # (если плечи были главной) либо оригинал {orig_blue} из игры.
            _blue_main_src = (
                blu_image_path
                if (blu_image_path and blu_image_path != EXTRA_TEX_USE_GAME_ORIGINAL
                    and os.path.isfile(str(blu_image_path)))
                else None
            )
            for _vm_blue, _orig_blue, _is_main, _red_sh in _blue_iso:
                # Приоритет: правка синих плеч из карточки (skin_build_data)
                # → главная BLU-картинка → оригинал {orig_blue} из игры.
                _bsrc = _shoulder_blue_user.get(_red_sh.lower())
                if not _bsrc and _is_main:
                    _bsrc = _blue_main_src
                _shoulder_iso.append((_vm_blue, _orig_blue, _bsrc))
            if _blue_iso:
                logger.info(f"[SHOULDER ISO] синие плечи: {[b[0] for b in _blue_iso]}")
            # Командные варианты нейтральных (из «+») — пишем их VTF/VMT.
            for _var, _orig_m, _vsrc in _variant_entries:
                _shoulder_iso.append((_var, _orig_m, _vsrc))
            if _variant_entries:
                logger.info(f"[TEAM PROMO] варианты записаны: {[v[0] for v in _variant_entries]}")
            logger.info(f"[SHOULDER ISO] переименованы плечи: {_rename}")
            # Если текстура плеч пришла как image_path (главная) —
            # НЕ даём записать её на руку: главная уйдёт на оригинал.
            if any(p is not None and p == image_path for p in _srcs.values()):
                image_path = EXTRA_TEX_USE_GAME_ORIGINAL
                logger.info("[SHOULDER ISO] главная текстура (плечи) перенаправлена в vm_*; руке — оригинал")
        return _shoulder_iso, image_path

    @staticmethod
    def _apply_force_team(force_team, mode, qc_path, weapon_key, ctx) -> None:
        """
        «Сделать командным»: для оружия БЕЗ нативной команды синтезирует BLU-строку
        в $texturegroup (skin 1 = {material}_blue по материалам reference-SMD), чтобы
        дальше весь командный путь отработал как у нативно-командного. Мутирует QC.
        """
        if force_team and mode not in HAND_MODE_KEYS:
            try:
                _pre = ModelBuildService.extract_skin_info(qc_path)
                if not _pre.get('is_team') and not _pre.get('has_australium'):
                    from src.services.smd_service import SMDService as _SMDft
                    from src.data.material_filter import is_editable_material as _ed
                    _ref = _SMDft.find_reference_smd(str(ctx.decompile_dir), weapon_key)
                    _mesh = _SMDft.ordered_unique_materials(_ref) if _ref else []
                    _team_mats = [m for m in _mesh if _ed(m)]
                    if _team_mats:
                        _ov = {1: {m: f"{m}_blue" for m in _team_mats}}
                        _tgb = ModelBuildService.generate_texturegroup_block(_team_mats, _ov)
                        ModelBuildService.replace_texturegroup_in_qc(qc_path, _tgb)
                        logger.info(
                            f"[FORCE TEAM] добавлена BLU-строка: "
                            f"{[m + '_blue' for m in _team_mats]}"
                        )
                    else:
                        logger.info("[FORCE TEAM] нет редактируемых материалов меша — пропуск")
                else:
                    logger.info(
                        "[FORCE TEAM] оружие уже командное или с австралием — пропуск"
                    )
            except Exception as _fte:
                logger.warning(f"[FORCE TEAM] не удалось синтезировать команду: {_fte}")

    @staticmethod
    def _plan_materials(
        qc_path, mode, weapon_key, ctx, texture_filename, image_path, blu_image_path,
        panel_extra_textures, panel_blu_textures, isolate_shoulders, blu_mode,
        skin_build_data, replace_keep_materials, custom_qc_text, original_cdmaterials_path,
        bypass_prefix: str = "console",
    ) -> "_MaterialPlan":
        """
        Анализирует $texturegroup и решает, какие материалы строить: BLU-строка,
        доп. материалы, служебные/ЧС (пишутся оригиналом), фильтр для рук, изоляция
        плеч, подавление игровой группы для кастомных моделей. Финализирует QC
        (patch_qc_file, инъекция/удаление $texturegroup, пользовательский QC-текст).
        Мутирует файл qc_path. Возвращает _MaterialPlan со всеми выходными именами.
        """
        tg_structure = ModelBuildService.extract_texturegroup_structure(qc_path)
        blu_row = tg_structure.get('blu_row', [])
        extra_materials = tg_structure.get('extra_materials', [])
        # Настоящая ли команда вторая строка (c_xxx_blue), а не вариант
        # (австралий/gold/festive). У вариант-онли оружия команды нет —
        # значит {texture}_blue не нужен.
        blu_is_team = bool(tg_structure.get('blu_is_team', False))

        # Оружие с одной общей текстурой (напр. часы шпиона) — BLU не нужен.
        # Иначе в мод попадёт лишняя _blue текстура.
        from src.data.weapons import NO_BLU_WEAPON_KEYS
        if weapon_key in NO_BLU_WEAPON_KEYS:
            if blu_row:
                logger.info(f"[{weapon_key}] BLU-row подавлен (одиночная текстура)")
            blu_row = []

        # ── Для режимов рук: фильтруем $texturegroup до актуальных текстур рук ─────────
        # Проблема: QC руки инженера (c_engineer_arms) в column 0 содержит "engineer_red"
        # (текстуру ТЕЛА), а не текстуру руки — без фильтрации картинка
        # пользователя заменила бы всё тело персонажа.
        _orig_main_pre_restrict = texture_filename  # col0 (может быть плечи)
        if mode in HAND_MODE_KEYS:
            from src.data.player_hands import get_hand_textures as _ght_hands
            from src.services.qc_skin_parser import restrict_to_materials
            _h_list = _ght_hands(mode)  # [(folder, vtf_name), ...]

            texture_filename, extra_materials, blu_row = restrict_to_materials(
                main_texture=texture_filename,
                red_row=tg_structure.get('red_row', []),
                blu_row=tg_structure.get('blu_row', []),
                allowed_names=[n for _, n in _h_list],
            )
            logger.info(
                f"[HANDS] texture_filename={texture_filename!r}, "
                f"extra_materials={extra_materials}, blu_row={blu_row}"
            )

        # ── Изоляция плеч вьюмодели (опционально) ────────────────────
        # Материал плеч/тела arms-модели общий с мировым персонажем.
        # Переименовываем его на уникальный (engineer_red → vm_engineer_red)
        # в $texturegroup ДО компиляции: перекомпилированная модель станет
        # ссылаться на новый материал, а мир останется на старом. Позже
        # запишем переименованный материал отдельным блоком.
        shoulder_iso, image_path = VPKService._apply_shoulder_isolation(
            ctx, mode, qc_path, weapon_key, tg_structure,
            _orig_main_pre_restrict, image_path, blu_image_path,
            panel_extra_textures, panel_blu_textures, isolate_shoulders,
        )

        # Исключаем служебные материалы (глаза/зубы/sheen-оверлеи) —
        # для них не нужно спрашивать текстуру при сборке. Тот же фильтр,
        # что и для карточек 2D (единый источник). Делаем ПОСЛЕ hands-блока,
        # т.к. он переназначает extra_materials/blu_row.
        from src.data.material_filter import (
            is_editable_material as _is_edit,
            is_user_blacklisted as _is_hidden,
        )
        # Служебные (глаза/зубы/убер/зомби/эффекты) И материалы из
        # пользовательского ЧС: НЕ показываем карточками и НЕ редактируем,
        # но ПИШЕМ в мод оригинальной игровой текстурой ниже — иначе из-за
        # console\-cdmaterials они стали бы фиолетовыми.
        # ВАЖНО: источник — ВЕСЬ $texturegroup (все строки/колонки), а НЕ
        # extra_materials. Служебные варианты (invun/zombie) обычно не в
        # геометрии и не в extra_materials, но модель ссылается на них в
        # других скинах (убер/зомби) — без записи они фиолетовые.
        _all_tg_mats: list = []
        _seen_tg: set = set()
        for _row in (tg_structure.get('all_rows') or []):
            for _m in _row:
                _ml = (_m or '').lower()
                if _ml and _ml not in _seen_tg:
                    _seen_tg.add(_ml)
                    _all_tg_mats.append(_m)
        blacklisted_extra = [m for m in _all_tg_mats
                              if (not _is_edit(m)) or _is_hidden(m)]
        if blacklisted_extra:
            logger.info(f"Служебные/ЧС материалы (без карточек, пишем оригиналом): {blacklisted_extra}")
        extra_materials = [m for m in extra_materials
                           if _is_edit(m) and not _is_hidden(m)]
        # blu_row НЕ фильтруем удалением — он индексируется по колонкам
        # вместе с red_row. Служебные blu-материалы пропускаются ВНУТРИ
        # цикла (по col_idx), чтобы не сместить выравнивание.

        # ── Стили (skinfamilies) кастомной модели ──────────────────
        # Если пользователь определил доп-стили, ИГРОВОЙ $texturegroup
        # неприменим: его имена (c_sd_cleaver_bloody, _blue …) относятся
        # к игровой модели, а не к мешу пользователя. Подавляем
        # производные из него BLU/extra-материалы и команду — мы
        # сгенерируем свою группу и варианты ниже. Меш-материалы базы
        # приходят отдельно через panel_extra_textures.
        # Для рук $texturegroup уже сгенерирован выше (изоляция плеч +
        # промоушен): vm_* для плеч + _blu варианты в синих строках.
        # Старый «кастомный» SKIN BUILD путь его перезатёр бы — отключаем.
        has_skins = (bool(skin_build_data and skin_build_data.get('tg_overrides'))
                      and mode not in HAND_MODE_KEYS)
        # Для «готовой» кастомной модели (keep_materials) ИГРОВОЙ
        # $texturegroup неприменим ВСЕГДА — у меша свои материалы
        # (c_sd_cleaver/mouth/lefteye…), а игровые имена (c_scattergun,
        # c_scattergun_gold) к нему отношения не имеют. Иначе сборка
        # начнёт спрашивать текстуры для игровых слотов, которых нет
        # в карточках. Базовые меш-материалы идут через panel_extra_textures.
        if has_skins or replace_keep_materials:
            logger.info(
                "[SKIN BUILD] кастомная модель → подавляем игровой "
                f"texturegroup (blu_row={blu_row}, extra={extra_materials})"
            )
            blu_row = []
            extra_materials = []
            blacklisted_extra = []  # у кастомного меша свои материалы — не пишем
            blu_mode = 'none'   # не плодим {texture}_blue

        if blu_row:
            logger.info(f"Найдена BLU команда: {blu_row}")
        if extra_materials:
            logger.info(f"Найдены дополнительные материалы модели: {extra_materials}")

        # Пропатчиваем QC файл: перенаправляем $cdmaterials в whitelisted-папку
        # обхода sv_pure (console\ или vgui\replay\thumbnails\), удаляем $lod.
        ModelBuildService.patch_qc_file(qc_path, bypass_prefix)

        # Игровое имя текстуры/VMT (источник ОРИГИНАЛЬНОГО кода VMT из игры).
        # Для кастомной модели texture_filename станет именем материала SMD,
        # но оригинальный VMT тащим по игровому имени (c_sd_cleaver),
        # затем лишь переставим $basetexture на материал модели.
        game_vmt_name = texture_filename

        # ── Кастомная модель: имена ведём от ФАКТИЧЕСКИХ материалов SMD ──
        # Имена VTF/VMT, $texturegroup и $basetexture обязаны совпадать с
        # материалом, с которым реально компилируется модель (из reference-SMD).
        # UI-имена могли разойтись с SMD (другой экспорт/регистр) → текстура
        # не находилась (фиолетовая). Картинки скинов мапим по индексу.
        if replace_keep_materials:
            _ref_smd = VpkModelPipeline._find_decompiled_reference_smd(
                qc_path, weapon_key, ctx.decompile_dir
            )
            _smd_mats = SMDService.ordered_unique_materials(_ref_smd) if _ref_smd else []
            if _smd_mats:
                logger.info(f"[SKIN BUILD] материалы SMD (истина): {_smd_mats}")
                if has_skins:
                    skin_build_data = VpkTextureBuilder._remap_skin_data_to_smd(
                        skin_build_data, _smd_mats
                    )
                if texture_filename != _smd_mats[0]:
                    logger.info(
                        f"[SKIN BUILD] main texture_filename: "
                        f"{texture_filename!r} → {_smd_mats[0]!r} (материал SMD)"
                    )
                    texture_filename = _smd_mats[0]

        # ── $texturegroup кастомной модели ──
        _tg_block = ''
        if has_skins:
            # Свои стили: генерируем группу (имена выровнены по SMD).
            _tg_block = ModelBuildService.generate_texturegroup_block(
                skin_build_data.get('mesh_materials', []),
                skin_build_data.get('tg_overrides', {}),
            )
            ModelBuildService.replace_texturegroup_in_qc(qc_path, _tg_block)
            logger.info(f"[SKIN BUILD] $texturegroup инъектирован в QC:\n{_tg_block}")
        elif replace_keep_materials:
            # Одно-скиновая кастомная модель: убираем игровую группу — её
            # имена относятся к игровой модели, не к мешу (иначе пустые
            # skin-строки ремапят материал в пустоту → фиолет).
            ModelBuildService.replace_texturegroup_in_qc(qc_path, '')
            logger.info("[SKIN BUILD] игровой $texturegroup удалён (одно-скиновая кастомная модель)")

        # ── Отредактированный пользователем QC ───────────────────────
        # Заменяем QC текстом пользователя, синхронизировав $texturegroup
        # с актуальными стилями (правки человека не теряются). Делается
        # ДО извлечения cdmaterials — дальше всё читается из этого QC.
        if replace_keep_materials and custom_qc_text and custom_qc_text.strip():
            _final_qc = ModelBuildService.replace_texturegroup_in_text(
                custom_qc_text, _tg_block
            )
            with open(qc_path, 'w', encoding='utf-8') as _qf:
                _qf.write(_final_qc)
            logger.info("[QC EDIT] QC заменён пользовательским (texturegroup синхронизирован)")
        return _MaterialPlan(
            tg_structure=tg_structure, blu_row=blu_row, extra_materials=extra_materials,
            blu_is_team=blu_is_team, blacklisted_extra=blacklisted_extra,
            texture_filename=texture_filename, blu_mode=blu_mode, has_skins=has_skins,
            shoulder_iso=shoulder_iso, image_path=image_path,
            skin_build_data=skin_build_data, game_vmt_name=game_vmt_name,
        )

    @staticmethod
    def _stage_locate_tools(
        ctx, mode: str, weapon_key: str, hat_mdl_path, tf2_root_dir, t: dict,
        keep_temp_on_error: bool, debug_mode: bool,
    ):
        """
        Стадия 1 модельного конвейера: инструменты и пути.

        Проверяет TF2/Crowbar, резолвит studiomdl/misc-VPK/tf-папку и строит
        список кандидатов MDL.

        Returns:
            (error_result, None) — ошибка, ctx очищен; error_result — готовый
            ответ build_vpk (False, message);
            (None, (studiomdl_exe, tf2_misc_vpk, tf_dir, crowbar_exe,
                    paths_to_try)) — успех.
        """
        def _fail(message: str):
            ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
            return (False, message), None

        # Без пути к TF2 продолжать нельзя — нужны VPK файлы игры
        if not tf2_root_dir:
            logger.error("Путь к TF2 не указан")
            return _fail(t['error_tf2_not_specified'])

        # Crowbar нужен для декомпиляции, без него никак
        crowbar_exists, crowbar_error = TF2Paths.check_crowbar()
        if not crowbar_exists:
            return _fail(crowbar_error)

        try:
            studiomdl_exe, tf2_misc_vpk, tf_dir = TF2Paths.resolve(tf2_root_dir)
        except FileNotFoundError as e:
            return _fail(str(e))

        paths_to_try, _mdl_path_error = VpkModelPipeline._build_mdl_search_paths(
            mode, weapon_key, hat_mdl_path, t, tf2_root_dir
        )
        if _mdl_path_error:
            return _fail(_mdl_path_error)

        crowbar_exe = TF2Paths.get_crowbar_path()
        return None, (studiomdl_exe, tf2_misc_vpk, tf_dir, crowbar_exe, paths_to_try)

    @staticmethod
    def _stage_find_and_decompile(
        ctx, mode: str, weapon_key: str, hat_mdl_path, paths_to_try,
        tf2_misc_vpk: str, crowbar_exe: str, draw_uv_layout: bool, size,
        export_folder: str, keep_temp_on_error: bool, debug_mode: bool,
        language: str, t: dict, emit_progress, emit_sub, is_cancelled,
        cancelled_result,
    ):
        """
        Стадия 2 модельного конвейера: MDL в игровом VPK + декомпиляция.

        Находит MDL по кандидатам, для %s-шапок обновляет weapon_key на
        реальный стем, получает декомпилированный QC (через кэш декомпиляции),
        рисует UV-шаблон (по запросу), чистит LOD и пополняет кэш.

        Returns:
            (error_result, '', weapon_key, '') — ошибка/отмена, ctx очищен
            (для отмены — cancelled_result);
            (None, found_mdl_path, weapon_key, qc_path) — успех.
        """
        def _fail(message_result):
            return message_result, '', weapon_key, ''

        found_mdl_path, _mdl_find_error = VpkModelPipeline._find_existing_mdl(
            paths_to_try, tf2_misc_vpk, weapon_key, t
        )
        if _mdl_find_error:
            ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
            return _fail((False, _mdl_find_error))

        # Для шапок с %s-плейсхолдером: обновляем weapon_key на реальный стем
        # (all_domination_%s → all_domination_heavy), иначе кэш и имена файлов сломаются
        if mode == "hat" and hat_mdl_path and "%s" in hat_mdl_path:
            weapon_key = Path(found_mdl_path).stem
            logger.info(f"Hat weapon_key обновлён: {weapon_key}")

        if is_cancelled():
            return _fail(cancelled_result(ctx))
        emit_progress(25, t.get('build_decompiling', 'Decompiling model...'))

        # === Кэш декомпила — проверяем ДО extraction ===
        # Ключ: weapon_key + vpk_path + mdl_rel_path + mtime(vpk).
        # mtime VPK меняется при каждом обновлении TF2 → авто-инвалидация.
        # При cache hit: пропускаем extract_file_set (3-10 сек) + Crowbar (10-30 сек).
        qc_path, cached_decompile, _decomp_error = VpkModelPipeline._obtain_decompiled_qc(
            ctx, found_mdl_path, weapon_key, tf2_misc_vpk, crowbar_exe,
            debug_mode, language, t, emit_sub,
        )
        if _decomp_error:
            ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
            return _fail((False, _decomp_error))

        if draw_uv_layout:
            ModelService.generate_uv_layout(ctx, weapon_key, size, export_folder, language)

        # Удаляем LOD файлы до кэширования — чтобы в кэше лежали уже чистые файлы
        ModelBuildService.remove_lod_files(ctx.decompile_dir)

        # Сохраняем в кэш после очистки — следующая сборка пропустит extraction + decompile
        if not cached_decompile:
            save_to_cache(weapon_key, tf2_misc_vpk, found_mdl_path, ctx.decompile_dir)

        return None, found_mdl_path, weapon_key, qc_path

    @staticmethod
    def _build_model_mode_vpk(
        ctx: BuildContext,
        r: BuildRequest,
        weapon_key: str,
        t: dict,
        *,
        model_file_callback=None,
        extra_texture_callback=None,
        extra_model_callback=None,
        texture_mismatch_callback=None,
        parent_window=None,
        emit_progress,
        emit_sub,
        is_cancelled,
        cancelled_result,
    ) -> Tuple[bool, str]:
        """
        Конвейер МОДЕЛЬНОГО мода (оружие/шапка/руки/тело): поиск MDL в игровом
        VPK -> декомпиляция (cache-aware) -> замена модели -> план материалов ->
        рендер всех текстур (параллельно с компиляцией) -> сборка доп. моделей
        (классы/стили шапок). Спец-режимы (critHIT/спрей/маски) сюда не заходят.

        Returns:
            (False, error_message)  — ошибка/отмена, ctx уже очищен;
            (True, vmt_to_delete)   — успех; vmt_to_delete — имя
                                      отредактированного VMT ('' если нет),
                                      упаковку VPK выполняет вызывающий.
        """
        # Локальные имена = поля запроса (тело стадий работает с ними).
        mode = r.mode
        image_path = r.image_path
        size = r.size
        format_type = r.format_type
        flags = r.flags or []
        vtf_options = r.vtf_options or {}
        tf2_root_dir = r.tf2_root_dir
        export_folder = r.export_folder
        keep_temp_on_error = r.keep_temp_on_error
        debug_mode = r.debug_mode
        replace_model_enabled = r.replace_model_enabled
        model_ready_path = r.model_ready_path
        draw_uv_layout = r.draw_uv_layout
        replace_model_path = r.replace_model_path
        hat_mdl_path = r.hat_mdl_path
        hat_apply_game_paints = r.hat_apply_game_paints
        hat_class_models = r.hat_class_models
        hat_style_builds = r.hat_style_builds
        language = r.language
        custom_vtf_path = r.custom_vtf_path
        blu_mode = r.blu_mode
        # Папка обхода sv_pure для $cdmaterials (console\ или vgui\replay\thumbnails\).
        from src.shared.constants import bypass_prefix as _resolve_bypass_prefix
        _bypass_prefix = _resolve_bypass_prefix(getattr(r, 'bypass_method', 'console'))
        blu_image_path = r.blu_image_path
        panel_extra_textures = r.panel_extra_textures or {}
        material_maps = r.material_maps or {}
        material_settings = r.material_settings or {}
        skin_build_data = r.skin_build_data
        replace_keep_materials = r.replace_keep_materials
        custom_qc_text = r.custom_qc_text
        isolate_shoulders = r.isolate_shoulders
        panel_blu_textures = r.panel_blu_textures
        force_team = r.force_team

        # Для рук замена SMD-модели не поддерживается.
        if mode in HAND_MODE_KEYS:
            replace_model_enabled = False

        # ── Стадия 1: инструменты и пути (TF2/Crowbar/studiomdl/кандидаты MDL) ──
        err, tools = VPKService._stage_locate_tools(
            ctx, mode, weapon_key, hat_mdl_path, tf2_root_dir, t,
            keep_temp_on_error, debug_mode,
        )
        if err is not None:
            return err
        studiomdl_exe, tf2_misc_vpk, tf_dir, crowbar_exe, paths_to_try = tools

        try:
            # ── Стадия 2: поиск MDL в игровом VPK + декомпиляция (cache-aware) ──
            err, found_mdl_path, weapon_key, qc_path = VPKService._stage_find_and_decompile(
                ctx, mode, weapon_key, hat_mdl_path, paths_to_try,
                tf2_misc_vpk, crowbar_exe, draw_uv_layout, size, export_folder,
                keep_temp_on_error, debug_mode, language, t,
                emit_progress, emit_sub, is_cancelled, cancelled_result,
            )
            if err is not None:
                return err

            if is_cancelled():
                return cancelled_result(ctx)
            emit_progress(40, t.get('build_processing', 'Processing texture...'))

            # Заменяем модель, если включен режим замены
            # Пропускаем если model_ready_path задан — пользователь уже указал готовый файл
            # Диалог выбора файла показываем здесь, после декомпиляции (чтобы знать куда копировать)
            replace_model_smd_path = VpkModelPipeline._resolve_replace_model_smd(
                replace_model_enabled, model_ready_path, replace_model_path,
                model_file_callback, parent_window,
            )

            VpkModelPipeline._apply_model_replacement(
                ctx, qc_path, weapon_key, replace_model_smd_path,
                extra_model_callback, language, emit_sub,
                keep_user_materials=replace_keep_materials,
            )

            # Извлекаем путь из $cdmaterials в QC файле (до патчинга, потому что потом мы его изменим)
            original_cdmaterials_path = ModelBuildService.extract_cdmaterials_path_from_qc(qc_path)
            # Все $cdmaterials пути (для поиска оригинальных VTF в VPK игры)
            original_cdmaterials_paths = ModelBuildService.extract_all_cdmaterials_paths_from_qc(qc_path)

            if not original_cdmaterials_path:
                ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                return False, t['error_cdmaterials_not_extracted'].format(qc_path=qc_path)

            # Извлекаем имя файла из $texturegroup (до патчинга, потому что потом мы его изменим)
            texture_filename = ModelBuildService.extract_texturegroup_filename(qc_path)
            if not texture_filename:
                ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                return False, t['error_texturegroup_not_extracted'].format(qc_path=qc_path)

            if mode == "hat":
                logger.info(
                    f"[HAT BUILD NAMES]  qc={qc_path!r}\n"
                    f"  weapon_key          = {weapon_key!r}\n"
                    f"  texture_filename    = {texture_filename!r}\n"
                    f"  cdmaterials_path    = {original_cdmaterials_path!r}\n"
                    f"  replace_smd_path    = {replace_model_smd_path!r}"
                )
                # Показываем пользователю оригинальные имена из игры (не имена файла-замены)
                _repl_name = os.path.basename(replace_model_smd_path) if replace_model_smd_path else None
                if _repl_name:
                    emit_sub(-1,
                        f"Original game names: model={weapon_key}, texture={texture_filename}"
                        if language == "en" else
                        f"Оригинальные имена из игры: модель={weapon_key}, текстура={texture_filename}"
                    )

            # Извлекаем полную структуру $texturegroup для поддержки:
            # 1. BLU команды (отдельная строка/row в texturegroup)
            # 2. Дополнительных материалов (shell, scope и т.д. - столбцы/columns)
            # ── «Сделать командным»: синтез BLU-строки для оружия БЕЗ
            # нативной команды. Делаем ДО извлечения tg_structure — тогда
            # весь командный путь (blu_row, генерация BLU, рекомпиляция)
            # сработает как у нативно-командного оружия. Материалы меша
            # берём из reference SMD (skin 0), skin 1 = {material}_blue. ──
            VPKService._apply_force_team(force_team, mode, qc_path, weapon_key, ctx)

            _plan = VPKService._plan_materials(
                qc_path, mode, weapon_key, ctx, texture_filename, image_path,
                blu_image_path, panel_extra_textures, panel_blu_textures,
                isolate_shoulders, blu_mode, skin_build_data,
                replace_keep_materials, custom_qc_text, original_cdmaterials_path,
                bypass_prefix=_bypass_prefix,
            )
            tg_structure = _plan.tg_structure
            blu_row = _plan.blu_row
            extra_materials = _plan.extra_materials
            _blu_is_team = _plan.blu_is_team
            _blacklisted_extra = _plan.blacklisted_extra
            texture_filename = _plan.texture_filename
            blu_mode = _plan.blu_mode
            _has_skins = _plan.has_skins
            _shoulder_iso = _plan.shoulder_iso
            image_path = _plan.image_path
            skin_build_data = _plan.skin_build_data
            _game_vmt_name = _plan.game_vmt_name

            # Извлекаем путь из $cdmaterials после патчинга (теперь с префиксом console\)
            patched_cdmaterials_path = ModelBuildService.extract_cdmaterials_path_from_qc(qc_path)
            if not patched_cdmaterials_path:
                ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                return False, t['error_cdmaterials_patched_not_extracted'].format(qc_path=qc_path)

            # Конвертируем путь из $cdmaterials в путь для материалов
            # Путь теперь в формате: console\models\weapons\v_bonesaw
            # Конвертируем в: materials/console/models/weapons/v_bonesaw/ (потому что VPK требует такую структуру)
            materials_rel_path = "materials/" + patched_cdmaterials_path.replace('\\', '/').strip().rstrip('/')
            if not materials_rel_path.endswith('/'):
                materials_rel_path += '/'

            vmt_filename = f"{texture_filename}.vmt"
            vtf_filename = f"{texture_filename}.vtf"

            # Подготавливаем пути в vpkroot (создаем структуру папок как в VPK)
            vtf_output_path = ctx.vpkroot_dir.joinpath(*materials_rel_path.rstrip('/').split('/'))
            vmt_path = vtf_output_path / vmt_filename
            vtf_temp_png = vtf_output_path / vtf_filename.replace(".vtf", ".png")

            try:
                ensure_directory_exists(vtf_output_path)
            except OSError as e:
                if "path too long" in str(e).lower():
                    logger.error(f"Путь слишком длинный для режима {mode}")
                    ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                    return False, t['error_path_too_long'].format(mode=mode)
                else:
                    raise

            # ── Проверка текстур в пользовательском SMD (режим «Модель уже готова») ──
            _mismatch_msg = VPKService._ready_model_texture_mismatch(
                model_ready_path, qc_path, weapon_key, ctx.decompile_dir, language)
            if (_mismatch_msg and texture_mismatch_callback
                    and not texture_mismatch_callback(_mismatch_msg)):
                logger.info("[MODEL READY] Пользователь отменил сборку из-за несовпадения текстур")
                ctx.cleanup(on_error=False, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                return False, (
                    "Сборка отменена: несовпадение текстур в SMD файле."
                    if language == "ru" else
                    "Build cancelled: texture mismatch in SMD file."
                )

            if is_cancelled():
                return cancelled_result(ctx)
            emit_progress(60, t.get('build_compiling', 'Compiling model...'))

            # ── Компиляция модели в фоне: обычная / SMD-замена / готовый MDL ──
            _compile_thread, _compile_exc = VpkModelPipeline._start_model_compile(
                model_ready_path, qc_path, weapon_key, ctx,
                studiomdl_exe, tf_dir, debug_mode, language, emit_sub,
            )

            # Эффективные настройки на материал: пер-текстурный оверрайд
            # поверх глобальных (size/format/flags/options); без оверрайда —
            # глобальные. Замыкание нужно и для главной текстуры, и для
            # panel-extra текстур дальше по коду.
            from src.data.texture_overrides import effective_settings as _eff_settings
            _global_tex = {'size': size, 'format': format_type,
                           'flags': flags or [], 'options': vtf_options or {}}

            def _eff(_mat):
                e = _eff_settings(_global_tex, (material_settings or {}).get(_mat))
                return e['size'], e['format'], e['flags'], e['options']

            # Игровой tf2_textures_dir.vpk — резолвим один раз (RED-оригинал
            # и извлечение оригинального VMT).
            tf2_textures_vpk = TF2Paths.resolve_textures_vpk(tf2_root_dir)

            # Главная текстура: RED-резолв → VTF (custom/готовый/рендер) →
            # оригинальный VMT с перенаправлением $basetexture.
            image_path, animated_fps, is_normal_map, vmt_to_delete = (
                VpkTextureBuilder._build_main_material(
                    image_path, texture_filename, vtf_filename, vtf_temp_png,
                    vmt_path, original_cdmaterials_path, original_cdmaterials_paths,
                    _game_vmt_name, patched_cdmaterials_path, mode, hat_apply_game_paints,
                    ctx, vtf_output_path, tf2_textures_vpk, tf2_misc_vpk,
                    extra_texture_callback, weapon_key, custom_vtf_path, _eff,
                )
            )

            # Пер-текстурные файловые карты (detail/selfillum/phong) применяются
            # ПОЗЖЕ — после создания VMT доп. материалов и BLU (см. ниже),
            # чтобы карты ложились в VMT именно своего материала.

            # ── BLU Team Texture (командная раскраска) ───────────────────────────
            # Для оружия с одной общей текстурой (часы шпиона) BLU не создаём,
            # даже если в BLU-слот случайно попала картинка — иначе появится
            # лишний {texture}_blue.vtf/vmt.
            VpkTextureBuilder._maybe_build_blu_team_texture(
                weapon_key, blu_row, _blu_is_team, blu_mode, blu_image_path,
                vtf_output_path, vtf_filename, vmt_path, texture_filename,
                patched_cdmaterials_path, size, format_type, flags, vtf_options,
            )

            # === Создаем текстуры для дополнительных материалов модели (shell, scope и т.д.) ===
            # Это столбцы 1+ из RED строки $texturegroup
            # Словарь для хранения путей к VTF дополнительных материалов (нужно для BLU копий)
            extra_materials_vtf_paths = VpkTextureBuilder._build_extra_material_textures(
                extra_materials, weapon_key, ctx, vtf_output_path, vmt_path,
                patched_cdmaterials_path, original_cdmaterials_paths,
                tf2_textures_vpk, tf2_misc_vpk, extra_texture_callback,
                custom_vtf_path, size, format_type, flags, vtf_options, animated_fps,
            )

            # === Блэклист/служебные материалы: запись ОРИГИНАЛЬНОГО VMT ===
            # Глаза/убер/зомби и т.п. не редактируются (нет карточек), но из-за
            # console\-cdmaterials модель ищет их VMT по новому пути — без него
            # материал фиолетовый. Копируем оригинальный VMT материала в
            # console\-путь: его текстурные ссылки АБСОЛЮТНЫЕ (eyeball→shared,
            # invun/zombie→models/player/...), поэтому отдельный VTF не нужен —
            # игровые текстуры находятся по абсолютным путям. На случай
            # относительного $basetexture дополнительно кладём VTF, если он есть.
            VpkTextureBuilder._write_blacklisted_materials(
                _blacklisted_extra, panel_extra_textures, ctx, vtf_output_path,
                vmt_path, patched_cdmaterials_path, original_cdmaterials_paths,
                tf2_textures_vpk, tf2_misc_vpk,
            )

            # === Изолированные плечи вьюмодели ===
            # Пишем переименованный материал плеч (vm_<orig>) под главным
            # console-путём. Источник: пользовательская текстура (ключ —
            # ОРИГИНАЛЬНОЕ имя материала) либо оригинал тела из игры.
            VpkTextureBuilder._write_shoulder_iso_materials(
                _shoulder_iso, ctx, vtf_output_path, vmt_path,
                patched_cdmaterials_path, original_cdmaterials_paths,
                tf2_textures_vpk, tf2_misc_vpk, size, format_type, flags, vtf_options,
            )

            # === Создаем текстуры для BLU команды ===
            # BLU - это отдельная строка (row 1) в $texturegroup
            # Для каждого материала в BLU строке спрашиваем отдельное изображение,
            # если пользователь отказывается — копируем соответствующую RED текстуру
            VpkTextureBuilder._build_blu_row_textures(
                blu_row, tg_structure, texture_filename, vtf_filename, ctx,
                vtf_output_path, vmt_path, patched_cdmaterials_path,
                original_cdmaterials_paths, tf2_textures_vpk, tf2_misc_vpk,
                extra_texture_callback, weapon_key, custom_vtf_path,
                size, format_type, flags, vtf_options, animated_fps,
                is_normal_map, extra_materials_vtf_paths,
            )

            # Зеркальные VMT по оригинальному пути (руки / spy-watch и т.п.).
            # Для all-class %s-шапок зеркало НЕ создаём (его заменила пер-классовая
            # сборка; иначе затёрлась бы текстура у невыбранных классов).
            VPKService._write_hand_mirror_vmts(
                ctx, mode, weapon_key, original_cdmaterials_path, vtf_output_path)

            if debug_mode:
                DebugService.save_patched_stage(ctx, ctx.decompile_dir)

            # ── Текстуры из 2D панели (c_arrow, sniper_lens и т.п.) ──────── #
            # Материалы из SMD модели которые НЕ в QC skinfamilies →
            # extra_texture_callback их не покрывает → добавляем здесь.
            # Фиксированные доп. текстуры (vgui-вставки и т.п.) — пишем по
            # их зашитому пути, не по cdmaterials. Возвращает обработанные имена.
            VpkTextureBuilder._build_secondary_textures(
                weapon_key, panel_extra_textures, ctx, vtf_output_path, vmt_path,
                patched_cdmaterials_path, size, format_type, flags, vtf_options,
                material_maps, texture_filename, image_path, is_normal_map,
                _has_skins, skin_build_data, _eff,
            )

            # Ждём завершения компиляции (шла параллельно с текстурами)
            _compile_thread.join()
            if _compile_exc[0] is not None:
                raise _compile_exc[0]

            # Копируем скомпилированные файлы в vpkroot (VMT файл уже скопирован ранее)
            # Используем путь из $modelname в QC файле (чтобы структура папок была правильной).
            # Для material-only оружия (Dead Ringer) модель в мод НЕ кладём —
            # его показывает родная игровая модель (viewmodel), а скин и карты
            # находятся через зеркальный VMT по оригинальному пути, который
            # ссылается на console-VTF. Папку console при этом ОСТАВЛЯЕМ.
            from src.data.weapons import MATERIAL_ONLY_WEAPON_KEYS as _MAT_ONLY
            if weapon_key in _MAT_ONLY:
                logger.info(f"[{weapon_key}] Material-only: модель в мод не включается (console сохраняется)")
            else:
                ModelService.copy_compiled_models_to_vpkroot(ctx, qc_path)

            # Мультиклассовая шапка с заменой модели: собираем модель для
            # ОСТАЛЬНЫХ выбранных классов (основная сборка делает только один).
            # Источник: явный список выбранных классов (model_player_per_class)
            # либо legacy %s-шаблон в hat_mdl_path.
            if mode == "hat" and replace_model_smd_path:
                _extra_targets = None
                if hat_class_models and len(hat_class_models) > 1:
                    # Все выбранные классы, КРОМЕ primary (он уже собран).
                    _extra_targets = [
                        m for m in hat_class_models.values() if m != hat_mdl_path
                    ]
                _is_pct_tmpl = bool(hat_mdl_path and "%s" in hat_mdl_path)
                if _extra_targets or _is_pct_tmpl:
                    VpkModelPipeline._build_extra_class_hat_models(
                        ctx, hat_mdl_path, found_mdl_path, replace_model_smd_path,
                        replace_keep_materials, tf2_misc_vpk, studiomdl_exe,
                        crowbar_exe, tf_dir, language, emit_sub,
                        target_mdl_paths=_extra_targets,
                        bypass_prefix=_bypass_prefix,
                    )

            # Этап 3: доп. ИЗМЕНЁННЫЕ стили-модели шапки — каждый своей
            # моделью и своей текстурой в тот же мод (активный стиль уже
            # собран основным пайплайном выше).
            if mode == "hat" and hat_style_builds:
                VpkModelPipeline._build_extra_style_models(
                    ctx, hat_style_builds, tf2_misc_vpk, studiomdl_exe,
                    crowbar_exe, tf_dir, language, emit_sub,
                    size, format_type, flags, vtf_options, vmt_path,
                    bypass_prefix=_bypass_prefix,
                )

            # Подстраховка: удаляем любые {texture}_blue.*, если их успел
            # создать другой путь, а настоящей команды у предмета нет
            # (одиночная текстура ИЛИ вариант-онли без c_xxx_blue в группе).
            from src.data.weapons import NO_BLU_WEAPON_KEYS as _NO_BLU2
            if weapon_key in _NO_BLU2 or not _blu_is_team:
                for _blue in vtf_output_path.glob(f"{texture_filename}_blue.*"):
                    try:
                        _blue.unlink()
                        logger.info(f"[{weapon_key}] Удалён лишний BLU-файл: {_blue.name}")
                    except OSError:
                        pass

        except Exception as e:
            error_msg = str(e)
            if hasattr(e, 'stderr') and e.stderr:
                error_msg += f"\nSTDERR: {e.stderr}"
            if hasattr(e, 'stdout') and e.stdout:
                error_msg += f"\nSTDOUT: {e.stdout}"

            if keep_temp_on_error:
                error_msg += f"\n\nВременные файлы сохранены в: {ctx.temp_dir}"

            ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
            return False, t['error_model_work'].format(error=error_msg)

        return True, vmt_to_delete or ''

    @staticmethod
    def build_vpk(
        request: Optional[BuildRequest] = None,
        *,
        parent_window=None,  # Окно для диалогов (если нужно показать что-то юзеру)
        model_file_callback=None,  # Колбэк для запроса файла из UI потока (потому что Qt не любит мультипоточность)
        extra_texture_callback=None,  # Колбэк для запроса одной доп. текстуры: callback(material_name, weapon_key) -> Optional[str]
        extra_model_callback=None,  # Колбэк для запроса доп. модели: callback(smd_name, weapon_key) -> Optional[str]
        texture_mismatch_callback=None,  # Колбэк для предупреждения о несовпадении текстур: callback(msg) -> bool
        sub_progress_callback: Optional[Callable[[int, str], None]] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,  # Главный прогресс (проценты стадий)
        cancel_callback: Optional[Callable[[], bool]] = None,  # True = пользователь запросил отмену
        **legacy_kwargs,  # Совместимость: build_vpk(image_path=..., mode=...) собирает BuildRequest
    ) -> Tuple[bool, str]:
        """
        Главная функция: делает из картинки VPK файл.
        Возвращает (success, message); при ошибке message содержит описание.
        Здесь весь конвейер: модель → текстуры → компиляция → упаковка.

        Параметры сборки берутся из ``request`` (BuildRequest). Для обратной
        совместимости (и тестов) допускается старый вызов через kwargs —
        тогда BuildRequest собирается из них. Колбэки и parent_window — это
        runtime-функции UI-потока, они всегда передаются отдельно.
        """
        if request is None:
            request = BuildRequest(**legacy_kwargs)

        # Распаковываем только то, что нужно оркестратору (валидация, спец-режимы,
        # упаковка). Модельный конвейер распаковывает запрос сам —
        # см. _build_model_mode_vpk.
        r = request
        image_path = r.image_path
        mode = r.mode
        filename = r.filename
        size = r.size
        format_type = r.format_type
        flags = r.flags or []
        vtf_options = r.vtf_options or {}
        tf2_root_dir = r.tf2_root_dir
        export_folder = r.export_folder
        keep_temp_on_error = r.keep_temp_on_error
        debug_mode = r.debug_mode
        hat_mdl_path = r.hat_mdl_path
        language = r.language
        custom_vtf_path = r.custom_vtf_path

        from src.data.translations import TRANSLATIONS
        t = TRANSLATIONS.get(language, TRANSLATIONS['en'])

        def emit_sub(pct: int, label: str) -> None:
            if sub_progress_callback:
                sub_progress_callback(pct, label)

        def emit_progress(value: int, message: str) -> None:
            if progress_callback:
                progress_callback(value, message)

        def is_cancelled() -> bool:
            return bool(cancel_callback and cancel_callback())

        def cancelled_result(ctx) -> Tuple[bool, str]:
            """Очистка ctx и стандартный ответ при отмене пользователем."""
            if ctx is not None:
                ctx.cleanup(on_error=False, keep_on_error=False, debug_mode=debug_mode)
            logger.info("Сборка отменена пользователем")
            return False, t.get('build_cancelled', 'Build cancelled by user')

        ctx = None
        try:
            # Проверяем что все на месте, иначе потом будет больно (валидация параметров)
            validation_error = validate_build_params(
                image_path, mode, filename, size, format_type, tf2_root_dir, t, custom_vtf_path
            )
            if validation_error:
                return False, validation_error

            # weapon_key — ключ модели/файлов: для рук это arm-модель, для тела/
            # масок шпиона — стем MDL, для шапки — стем hat_mdl_path, иначе суффикс mode.
            weapon_key, _wk_error = VPKService._resolve_weapon_key(mode, hat_mdl_path)
            if _wk_error:
                return False, _wk_error

            # Запоминаем какой VMT надо будет удалить после сборки (если юзер его редактировал через редактор)
            vmt_to_delete = None
            
            ctx = BuildContext.create(mode, weapon_key, debug_mode=debug_mode)
            
            # ── Маски маскировки шпиона ──────────────────────────────────────── #
            # Не нужен MDL, QC-патчинг или компиляция.
            # Просто кладём mask_*.vtf/vmt по оригинальному пути игры:
            #   materials/models/player/spy/mask_*.vtf
            # Это прямой override, как у SPECIAL_MODES.
            if mode == SPY_MASK_MODE_KEY:
                result = VPKService._build_spy_masks_vpk(
                    ctx=ctx,
                    image_path=image_path,
                    size=size,
                    format_type=format_type,
                    flags=flags or [],
                    vtf_options=vtf_options,
                    filename=filename,
                    export_folder=export_folder,
                    language=language,
                    extra_texture_callback=extra_texture_callback,
                    tf2_root_dir=tf2_root_dir,
                    keep_temp_on_error=keep_temp_on_error,
                    debug_mode=debug_mode,
                    t=t,
                )
                return result

            # Для critHIT и прочих спец режимов - просто текстуры, без всей этой возни с моделями
            if mode in SPECIAL_MODES.values():
                result = BuildService.build_special_mode_vpk(
                    ctx, mode, image_path, size, format_type, flags, vtf_options,
                    keep_temp_on_error, debug_mode, language, custom_vtf_path
                )
                if not result[0]:
                    return result[0], result[1]
                # Если юзер редактировал VMT, запомним чтобы потом удалить
                if len(result) > 2 and result[2]:
                    vmt_to_delete = result[2]
                else:
                    vmt_to_delete = None

            else:
                ok, payload = VPKService._build_model_mode_vpk(
                    ctx, request, weapon_key, t,
                    model_file_callback=model_file_callback,
                    extra_texture_callback=extra_texture_callback,
                    extra_model_callback=extra_model_callback,
                    texture_mismatch_callback=texture_mismatch_callback,
                    parent_window=parent_window,
                    emit_progress=emit_progress,
                    emit_sub=emit_sub,
                    is_cancelled=is_cancelled,
                    cancelled_result=cancelled_result,
                )
                if not ok:
                    return False, payload
                vmt_to_delete = payload or None

            
            # Собираем VPK файл (финальный этап - упаковываем все в один файл)
            if is_cancelled():
                return cancelled_result(ctx)
            emit_progress(80, t.get('build_packing', 'Creating VPK file...'))
            emit_sub(-1, "Packing VPK..." if language == "en" else "Упаковка VPK...")
            # Содержимое vpkroot: краткая сводка всегда, полный список — только в
            # debug-режиме (сотни строк на сборку засоряли tf2sg.log).
            if ctx.vpkroot_dir.exists():
                vpkroot_files = []
                for _root, _dirs, _files in os.walk(ctx.vpkroot_dir):
                    for _f in _files:
                        rel = os.path.relpath(os.path.join(_root, _f), ctx.vpkroot_dir).replace('\\', '/')
                        vpkroot_files.append(rel)
                logger.info(f"[VPK CONTENTS] файлов в VPK: {len(vpkroot_files)}")
                if debug_mode:
                    logger.info("[VPK CONTENTS]\n" +
                                "\n".join(f"  {f}" for f in vpkroot_files))
            vpk_path = PackagingService.create_vpk_file(ctx, filename, export_folder, language)

            success_message = VPKService._finalize_build_success(
                ctx, vpk_path, vmt_to_delete, language, debug_mode, t
            )
            return True, success_message
            
        except Exception as e:
            from src.data.translations import TRANSLATIONS
            t = TRANSLATIONS.get(language, TRANSLATIONS['en'])
            error_msg = t['error_vpk_creation'].format(error=str(e))
            if ctx:
                if keep_temp_on_error:
                    error_msg += f"\n\n{t.get('temp_files_saved', 'Temporary files saved in')}: {ctx.temp_dir}"
                ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
            return False, error_msg
    
    @staticmethod
    def _build_spy_masks_vpk(
        ctx,
        image_path,
        size,
        format_type,
        flags,
        vtf_options,
        filename,
        export_folder,
        language,
        extra_texture_callback,
        tf2_root_dir,
        keep_temp_on_error,
        debug_mode,
        t,
    ):
        """
        Строит VPK-мод с кастомными масками маскировки шпиона.

        В отличие от player skin, здесь НЕТ деcompile/patch/compile — только
        VTF+VMT файлы по оригинальному пути materials/models/player/spy/.
        Это гарантирует что body-текстуры шпиона остаются из игры.
        """
        try:
            # Папка для текстур масок внутри vpkroot
            masks_dir = ctx.vpkroot_dir / "materials" / "models" / "player" / "spy"
            ensure_directory_exists(masks_dir)

            tf2_textures_vpk = TF2Paths.resolve_textures_vpk(tf2_root_dir)
            try:
                _, tf2_misc_vpk_path, _ = TF2Paths.resolve(tf2_root_dir)
            except Exception:
                tf2_misc_vpk_path = None

            # Оригинальный cdmaterials — нужен для VMT $basetexture
            spy_cdmat = "models/player/spy"

            any_created = False

            for cls_key, vtf_name, name_en, name_ru, btn in SPY_DISGUISE_MASKS:
                mask_vtf_path = masks_dir / f"{vtf_name}.vtf"
                mask_vmt_path = masks_dir / f"{vtf_name}.vmt"

                # Спрашиваем пользователя через стандартный callback
                mask_img = extra_texture_callback(vtf_name, "spy") if extra_texture_callback else None

                if mask_img == EXTRA_TEX_USE_GAME_ORIGINAL:
                    # Берём оригинал из VPK
                    orig = VpkTextureBuilder._get_original_vtf_bytes(
                        vtf_name, [spy_cdmat],
                        tf2_textures_vpk, tf2_misc_vpk_path, log_not_found=False
                    )
                    if orig:
                        with open(mask_vtf_path, "wb") as f:
                            f.write(orig)
                        logger.info(f"Маска из VPK: {vtf_name}.vtf")
                    else:
                        logger.debug(f"Маска не найдена в VPK, пропускаем: {vtf_name}")
                        continue
                elif mask_img and str(mask_img).lower().endswith('.vtf'):
                    # В карточку маски загрузили готовый VTF — копируем как есть
                    copy_file_safe(mask_img, mask_vtf_path)
                    logger.info(f"Маска: готовый VTF скопирован → {vtf_name}.vtf")
                elif mask_img and os.path.isfile(mask_img):
                    # Конвертируем изображение пользователя.
                    # ВАЖНО: имя PNG должно совпадать с именем VTF (без _tmp),
                    # иначе VTFCmd создаст файл с неправильным именем.
                    tmp_png = masks_dir / f"{vtf_name}.png"
                    TextureService.process_image(mask_img, tmp_png, size)
                    vtf_flags, merged = TextureService.resolve_vtf_flags_and_options(flags, vtf_options, drop_normal=True)
                    TextureService.create_vtf(str(tmp_png), str(masks_dir), format_type, vtf_flags, merged)
                    if tmp_png.exists():
                        tmp_png.unlink()
                    logger.info(f"Создан VTF маски: {vtf_name}.vtf")
                else:
                    # Пользователь пропустил — не включаем
                    logger.debug(f"Маска пропущена: {vtf_name}")
                    continue

                # VMT — простой VertexLitGeneric по оригинальному пути
                if mask_vtf_path.exists():
                    vmt_content = (
                        '"VertexLitGeneric"\n'
                        '{\n'
                        f'\t"$basetexture" "{spy_cdmat}/{vtf_name}"\n'
                        '}\n'
                    )
                    with open(mask_vmt_path, 'w', encoding='utf-8') as f:
                        f.write(vmt_content)
                    logger.info(f"Создан VMT маски: {vtf_name}.vmt")
                    any_created = True

            if not any_created:
                ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                return False, t.get('error_no_textures', 'No mask textures were provided.')

            # Пакуем VPK
            vpk_path = PackagingService.create_vpk_file(ctx, filename, export_folder, language)
            ctx.cleanup(on_error=False, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
            logger.info(f"VPK масок шпиона готов: {vpk_path}")
            return True, vpk_path

        except Exception as exc:
            logger.error(f"_build_spy_masks_vpk: {exc}", exc_info=True)
            if ctx:
                ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
            return False, str(exc)
