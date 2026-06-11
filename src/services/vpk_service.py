"""
Работа с VPK файлами: распаковка, сборка, конвертация текстур.
"""

import os
import shutil
import threading
from pathlib import Path
from typing import Tuple, List, Optional, Dict, Any, Callable
from .build_context import BuildContext, TextureBuildContext
from .vmt_service import VMTService
from .build_service import BuildService
from .texture_service import TextureService
from .packaging_service import PackagingService
from .model_service import ModelService
from .tf2_vpk_extract_service import TF2VPKExtractService
from .model_build_service import ModelBuildService
from .tf2_paths import TF2Paths, build_hat_mdl_candidates
from .debug_service import DebugService
from .smd_service import SMDService
from .decompile_cache import get_cached_decompile, restore_from_cache, save_to_cache
from src.data.weapons import SPECIAL_MODES, WEAPON_MDL_PATHS
from src.data.player_hands import HAND_MODE_KEYS
from src.data.player_characters import (
    PLAYER_BODY_MODE_KEYS,
    SPY_MASK_MODE_KEY,
    SPY_MDL_PATH,
    SPY_DISGUISE_MASKS,
    SPY_MASK_VTF_NAMES,
)
from src.shared.logging_config import get_logger
from src.shared.constants import ToolPaths, DirectoryPaths, EXTRA_TEX_USE_GAME_ORIGINAL
from src.shared.exceptions import VPKCreationError
from src.shared.file_utils import ensure_file_exists, ensure_directory_exists, copy_file_safe
from src.shared.validators import validate_build_params

logger = get_logger(__name__)


class VPKService:
    """Главный конвейер сборки VPK файлов. Детали ошибок — в логах."""
    
    @staticmethod
    def _get_vpk_tool() -> Path:
        return ToolPaths.get_vpk_tool()

    @staticmethod
    def _build_mdl_search_paths(
        mode: str,
        weapon_key: str,
        hat_mdl_path: Optional[str],
        t: dict,
    ) -> Tuple[List[str], Optional[str]]:
        """
        Строит список путей-кандидатов к MDL внутри игрового VPK.

        TF2 хранит модели в разных местах (workshop / workshop_partner /
        weapons/c_models / c_items / player/items), поэтому пробуем все
        вероятные варианты по порядку.

        Returns:
            (paths_to_try, error). error != None — фатальная ошибка режима
            (нет mdl_path для персонажа или оружие не найдено в конфиге);
            вызывающий код должен очистить ctx и вернуть ошибку.
        """
        # ── Шапка: путь из items_game.txt, возможно с %s-плейсхолдером ──── #
        if mode == "hat" and hat_mdl_path:
            # Единая логика кандидатов (%s, workshop-варианты, суффиксы класса)
            return build_hat_mdl_candidates(hat_mdl_path), None

        # ── Тело персонажа / маски шпиона: прямой путь к MDL ────────────── #
        if mode in PLAYER_BODY_MODE_KEYS or mode == SPY_MASK_MODE_KEY:
            if mode == SPY_MASK_MODE_KEY:
                _char_mdl = SPY_MDL_PATH
            else:
                from src.data.player_characters import PLAYER_CHARACTERS as _PC
                _char_mdl = _PC.get(mode, {}).get('mdl_path', '')
            if not _char_mdl:
                return [], f"No mdl_path defined for character mode: {mode}"
            return [_char_mdl], None

        # ── Обычное оружие: пробуем все вероятные места хранения ─────────── #
        if weapon_key not in WEAPON_MDL_PATHS:
            return [], t['error_weapon_not_found'].format(weapon_key=weapon_key)

        base_path = WEAPON_MDL_PATHS[weapon_key]
        _folder_suffix = f"/{weapon_key}/{weapon_key}.mdl"
        _flat_suffix = f"/{weapon_key}.mdl"
        paths_to_try = []

        # workshop_partner → workshop → стандарт → c_items: путь с папкой и без
        for _candidate in (
            base_path.replace("models/weapons/", "models/workshop_partner/weapons/"),
            base_path.replace("models/weapons/", "models/workshop/weapons/"),
            base_path,
            base_path.replace("models/weapons/c_models/", "models/weapons/c_items/"),
        ):
            paths_to_try.append(_candidate)
            if _folder_suffix in _candidate:
                paths_to_try.append(_candidate.replace(_folder_suffix, _flat_suffix))

        # Последний шанс — папки классов (там обычно старьё)
        if '_' in mode:
            class_name_lower = mode.split('_', 1)[0]
            paths_to_try.append(f"models/player/items/{class_name_lower}/{weapon_key}/{weapon_key}.mdl")
            paths_to_try.append(f"models/player/items/{class_name_lower}/{weapon_key}.mdl")

        return paths_to_try, None
    
    @staticmethod
    def _find_existing_mdl(
        paths_to_try: List[str],
        tf2_misc_vpk: str,
        weapon_key: str,
        t: dict,
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Ищет первый существующий MDL среди путей-кандидатов внутри VPK.

        Только проверяет наличие (check_mdl_exists), не распаковывая файлы —
        так быстрее, чем тащить всю папку.

        Returns:
            (found_path, error). Ровно одно из значений не None.
        """
        last_error = None
        for mdl_rel_path in paths_to_try:
            try:
                logger.debug(f"Проверяем наличие MDL по пути: {mdl_rel_path}")
                if TF2VPKExtractService.check_mdl_exists(tf2_misc_vpk, mdl_rel_path):
                    logger.info(f"MDL файл найден по пути: {mdl_rel_path}")
                    return mdl_rel_path, None
                logger.debug(f"MDL файл не найден по пути: {mdl_rel_path}")
            except Exception as e:
                logger.warning(f"Ошибка при проверке пути {mdl_rel_path}: {e}", exc_info=True)
                last_error = e

        paths_str = "\n".join([f"  - {path}" for path in paths_to_try])
        error_msg = t['error_mdl_not_found'].format(paths=paths_str, vpk_file=tf2_misc_vpk)
        if last_error:
            error_msg += f"\n{str(last_error)}"
        logger.error(f"Модель не найдена для {weapon_key}. Проверенные пути: {len(paths_to_try)}")
        return None, error_msg

    @staticmethod
    def _resolve_replace_model_smd(
        replace_model_enabled: bool,
        model_ready_path: Optional[str],
        replace_model_path: Optional[str],
        model_file_callback,
        parent_window,
    ) -> Optional[str]:
        """
        Определяет путь к пользовательскому SMD для режима «замена модели».

        Источники по приоритету: прямой путь (тесты) → callback (UI-поток) →
        диалог QFileDialog (если есть parent_window). Возвращает None, если
        режим выключен, задан model_ready_path или пользователь отменил выбор.
        """
        if not replace_model_enabled or model_ready_path:
            return None

        if replace_model_path and os.path.exists(replace_model_path):
            logger.info(f"Используется предустановленный файл для замены модели: {replace_model_path}")
            return replace_model_path

        if model_file_callback:
            # Qt не любит UI из рабочего потока — запрашиваем файл через callback главного потока
            file_path = model_file_callback()
            if file_path and os.path.exists(file_path):
                logger.info(f"Выбран файл для замены модели через callback: {file_path}")
                return file_path
            logger.info("Выбор SMD файла отменен, продолжаем без замены модели")
            return None

        if parent_window:
            from PySide6.QtWidgets import QFileDialog
            file_path, _ = QFileDialog.getOpenFileName(
                parent_window,
                "Выберите SMD файл модели для замены",
                "",
                "SMD Files (*.smd);;All Files (*)",
            )
            if file_path and os.path.exists(file_path):
                logger.info(f"Выбран файл для замены модели: {file_path}")
                return file_path
            logger.info("Выбор SMD файла отменен, продолжаем без замены модели")
            return None

        logger.warning("Режим замены модели включен, но путь к модели не указан и нет способа запросить файл")
        return None

    @staticmethod
    def _write_material_vmt(target_vmt_path, base_vmt_path, cdmaterials_path: str, tex_name: str) -> None:
        """
        Записывает VMT вторичного материала (extra / variant / shared / BLU).

        Если базовый VMT существует — копирует его и переставляет $basetexture
        на tex_name; иначе создаёт VMT из шаблона по $cdmaterials.
        """
        if base_vmt_path.exists():
            copy_file_safe(base_vmt_path, target_vmt_path)
            VMTService.update_vmt_basetexture_path(str(target_vmt_path), cdmaterials_path, tex_name)
        else:
            VMTService.create_vmt_template_from_cdmaterials(str(target_vmt_path), cdmaterials_path, tex_name)
        logger.info(f"Создан VMT вторичного материала: {target_vmt_path.name}")

    @staticmethod
    def _render_extra_texture(
        name: str,
        img: str,
        vtf_output_path: Path,
        vmt_path: Path,
        patched_cdmaterials_path: str,
        size: Tuple[int, int],
        format_type: str,
        flags: List[str],
        vtf_options: dict,
    ) -> bool:
        """
        Универсальный рендер доп. текстуры в VPK: {name}.vtf + {name}.vmt
        рядом с базовой текстурой.

        Источник:
          • .vtf      → копируется как есть (без переконвертации);
          • анимация  → анимированный VTF (+ AnimatedTexture-прокси в VMT);
          • картинка  → ресайз + обычный VTF.
        VMT строится на основе главного (vmt_path) с $basetexture → name.

        Возвращает True, если текстура создана; False — если img пуст/не файл.
        Единая точка для panel_extra_textures и вариантов стилей (skinfamilies).
        """
        if not img or not os.path.isfile(img):
            return False

        # Имя в нижний регистр: Source ищет материалы/текстуры в lowercase,
        # а лукап в VPK регистрозависим — иначе текстура не находится (фиолетовая).
        name = name.lower()

        ensure_directory_exists(vtf_output_path)
        out_vtf = vtf_output_path / f"{name}.vtf"
        out_vmt = vtf_output_path / f"{name}.vmt"
        vtf_flags, merged = TextureService.resolve_vtf_flags_and_options(
            flags, vtf_options, drop_normal=True
        )

        fps = None
        if str(img).lower().endswith('.vtf'):
            copy_file_safe(img, out_vtf)
        elif TextureService.is_animated_image(img):
            fps = TextureService.create_animated_vtf(
                img, str(out_vtf), size, format_type, vtf_flags, merged
            )
        else:
            tmp_png = vtf_output_path / f"{name}.png"
            VPKService._process_image(img, tmp_png, size)
            VPKService._create_vtf(str(tmp_png), str(vtf_output_path), format_type, vtf_flags, merged)
            if tmp_png.exists():
                tmp_png.unlink()

        if not out_vmt.exists():
            VPKService._write_material_vmt(out_vmt, vmt_path, patched_cdmaterials_path, name)
        if fps:
            VMTService.enable_animated_basetexture(str(out_vmt), fps)
        return True

    @staticmethod
    def _build_blu_team_texture(
        blu_mode: str,
        blu_image_path: Optional[str],
        vtf_output_path: Path,
        vtf_filename: str,
        vmt_path: Path,
        texture_filename: str,
        patched_cdmaterials_path: str,
        size: Tuple[int, int],
        format_type: str,
        flags: List[str],
        vtf_options: dict,
    ) -> None:
        """
        Создаёт BLU-командную текстуру (и VMT) рядом с RED.

        blu_mode == 'same'        → копия RED VTF;
        иначе при blu_image_path  → отдельное изображение → VTF.
        BLU VMT — копия RED VMT с обновлённым $basetexture. Ошибки не критичны
        (мод соберётся и без BLU-варианта).

        Примечание: BLU намеренно использует только UI-опции (vtf_options),
        не подмешивая опции из флагов — поведение сохранено как в оригинале.
        """
        if not blu_mode or blu_mode in ('none', ''):
            return
        try:
            red_vtf_path = vtf_output_path / vtf_filename
            blu_vtf_name = f"{texture_filename}_blue.vtf"
            blu_vtf_path = vtf_output_path / blu_vtf_name
            blu_created = False

            if blu_mode == 'same':
                if red_vtf_path.exists():
                    shutil.copy2(red_vtf_path, blu_vtf_path)
                    blu_created = True
                    logger.info(f"BLU текстура скопирована из RED: {blu_vtf_name}")
            elif blu_image_path and str(blu_image_path).lower().endswith('.vtf'):
                # В BLU-карточку загрузили готовый VTF — копируем как есть
                copy_file_safe(blu_image_path, blu_vtf_path)
                blu_created = blu_vtf_path.exists()
                if blu_created:
                    logger.info(f"BLU текстура: готовый VTF скопирован → {blu_vtf_name}")
            elif blu_image_path and os.path.exists(blu_image_path):
                blu_png_tmp = vtf_output_path / f"{texture_filename}_blue.png"
                VPKService._process_image(blu_image_path, str(blu_png_tmp), size)
                blu_vtf_flags, _ = TextureService.parse_vtf_flags_and_options(flags or [])
                blu_opts = dict(vtf_options or {})
                blu_opts.pop('normal', None)   # BLU — не normal map
                VPKService._create_vtf(
                    str(blu_png_tmp), str(vtf_output_path), format_type, blu_vtf_flags, blu_opts
                )
                if blu_png_tmp.exists():
                    blu_png_tmp.unlink()
                blu_created = blu_vtf_path.exists()
                if blu_created:
                    logger.info(f"BLU текстура создана: {blu_vtf_name}")

            # BLU VMT — копия RED с обновлённым $basetexture
            if blu_created and vmt_path.exists():
                blu_vmt_path = vtf_output_path / f"{texture_filename}_blue.vmt"
                shutil.copy2(vmt_path, blu_vmt_path)
                VMTService.update_vmt_basetexture_path(
                    str(blu_vmt_path), patched_cdmaterials_path, f"{texture_filename}_blue"
                )
                logger.info(f"BLU VMT создан: {blu_vmt_path.name}")
        except Exception as _blu_exc:
            logger.warning(
                f"Не удалось создать BLU текстуру (не критично): {_blu_exc}", exc_info=True
            )

    @staticmethod
    def _remap_skin_data_to_smd(skin_build_data: dict, smd_mats: list) -> dict:
        """
        Переименовывает материалы стилей под ФАКТИЧЕСКИЕ имена материалов SMD.

        UI собирает имена из превью-загрузки; к моменту сборки имена меша в SMD
        могут отличаться (другой экспорт/регистр). Сопоставляем UI↔SMD ПО ИНДЕКСУ
        (порядок появления материалов) и переписываем mesh_materials / tg_overrides /
        variant_files на SMD-имена. Картинки вариантов сохраняются.
        """
        ui_mats = skin_build_data.get('mesh_materials', [])
        if not ui_mats or not smd_mats:
            return skin_build_data

        name_map = {um: (smd_mats[i] if i < len(smd_mats) else um)
                    for i, um in enumerate(ui_mats)}

        old_variants = skin_build_data.get('variant_files', {})
        new_tg: dict = {}
        new_variants: dict = {}
        for skin_idx, mats in skin_build_data.get('tg_overrides', {}).items():
            for ui_mat, old_vname in mats.items():
                base = name_map.get(ui_mat, ui_mat)
                # суффикс роли = хвост старого имени варианта после "ui_mat_"
                prefix = (ui_mat + '_')
                suffix = old_vname[len(prefix):] if old_vname.lower().startswith(prefix.lower()) else old_vname
                new_vname = f"{base}_{suffix}"
                new_tg.setdefault(skin_idx, {})[base] = new_vname
                if old_vname in old_variants:
                    new_variants[new_vname] = old_variants[old_vname]

        return {
            'mesh_materials': [name_map.get(m, m) for m in ui_mats],
            'tg_overrides': new_tg,
            'variant_files': new_variants,
        }

    @staticmethod
    def _build_material_maps(
        material_maps: Optional[dict],
        vtf_output_path: Path,
        texture_filename: str,
        vmt_path: Path,
        patched_cdmaterials_path: str,
        size: Tuple[int, int],
        base_image_path: Optional[str] = None,
        is_normal_map: bool = False,
        panel_extra_textures: Optional[dict] = None,
    ) -> None:
        """
        Генерит файловые карты материала ПЕР-ТЕКСТУРНО.

        material_maps: {material_name: {map_id: spec}} — карты для каждого выбранного
        материала (а не глобально на главный). Карты каждого материала пишутся в
        ЕГО VMT:
          • главный (== texture_filename) → vmt_path, база = base_image_path;
          • прочие → {mat}.vmt (создан extra/panel_extra), база = panel_extra_textures[mat].
        Если есть {mat}_blue.vmt — параметры дублируются туда (команда наследует).
        Ошибка одной карты не валит сборку.
        """
        if not material_maps:
            return
        panel_extra_textures = panel_extra_textures or {}
        for mat, maps in material_maps.items():
            if not maps:
                continue
            # Пустой ключ '' = главный материал (UI не всегда знает texture_filename).
            if mat in ('', texture_filename):
                real_mat = texture_filename
                mat_vmt = vmt_path
                mat_base = base_image_path
            else:
                real_mat = mat
                mat_vmt = vtf_output_path / f"{mat}.vmt"
                mat_base = panel_extra_textures.get(mat)
                if not mat_vmt.exists():
                    logger.warning(f"Карты материала '{mat}': VMT не найден ({mat_vmt.name}), пропуск")
                    continue
            VPKService._apply_maps_for_material(
                maps, real_mat, mat_vmt, mat_base, vtf_output_path,
                patched_cdmaterials_path, size, is_normal_map,
            )
            _blu_vmt = vtf_output_path / f"{real_mat}_blue.vmt"
            if _blu_vmt.exists():
                VPKService._apply_maps_for_material(
                    maps, real_mat, _blu_vmt, mat_base, vtf_output_path,
                    patched_cdmaterials_path, size, is_normal_map, params_only=True,
                )

    @staticmethod
    def _apply_maps_for_material(
        material_maps: dict,
        mat: str,
        vmt_path: Path,
        base_image_path: Optional[str],
        vtf_output_path: Path,
        patched_cdmaterials_path: str,
        size: Tuple[int, int],
        is_normal_map: bool = False,
        params_only: bool = False,
    ) -> None:
        """
        Применяет набор карт к ОДНОМУ материалу: генерит VTF (имена {mat}{suffix})
        и вписывает параметры в его VMT. params_only=True — только параметры (VTF
        уже создан, напр. при дублировании в BLU-VMT).

        Источник карты: "image" (файл) либо "derive" (из базовой текстуры material'а).
        Для derive-phong доп. создаётся карта нормалей + $envmap («Авто-блеск»).
        """
        from src.data.material_maps import MATERIAL_MAPS, MAP_ORDER
        for map_id in MAP_ORDER:
            spec = material_maps.get(map_id)
            if not spec:
                continue
            cfg = MATERIAL_MAPS[map_id]
            map_key = f"{mat}{cfg['suffix']}"
            derive = bool(spec.get("derive")) and bool(cfg.get("derive_kind"))
            image = spec.get("image")

            if not derive and (not image or not os.path.isfile(image)):
                if not params_only:
                    logger.warning(f"Карта '{map_id}' [{mat}]: нет файла и не derive, пропуск")
                continue
            if derive and (not base_image_path or not os.path.isfile(base_image_path)):
                if not params_only:
                    logger.warning(f"Карта '{map_id}' [{mat}]: derive невозможен — нет базы, пропуск")
                continue

            if not params_only:
                try:
                    ensure_directory_exists(vtf_output_path)
                    temp_png = vtf_output_path / f"{map_key}.png"
                    _map_opts = dict(cfg.get("options", {}))
                    if derive:
                        threshold = spec.get("threshold")
                        threshold = int(threshold) if threshold not in (None, "") else None
                        TextureService.derive_effect_map(
                            base_image_path, str(temp_png), cfg["derive_kind"], size,
                            threshold=threshold,
                        )
                        VPKService._create_vtf(str(temp_png), str(vtf_output_path),
                                               cfg["format"], list(cfg["flags"]), _map_opts)
                    else:
                        VPKService._process_image(image, str(temp_png), size)
                        VPKService._create_vtf(str(temp_png), str(vtf_output_path),
                                               cfg["format"], list(cfg["flags"]), _map_opts)
                    if temp_png.exists():
                        temp_png.unlink()
                except Exception as e:
                    logger.warning(f"Не удалось создать VTF карты '{map_id}' [{mat}]: {e}", exc_info=True)
                    continue

            extra = dict(cfg["extra_vmt"])
            for k, v in spec.items():
                if isinstance(k, str) and k.startswith("$"):
                    extra[k] = str(v)
            if derive:
                extra.update(cfg.get("derive_extra_vmt", {}))
                if cfg.get("derive_auto_normal") and not params_only:
                    VPKService._ensure_derived_normal(
                        base_image_path, vtf_output_path, mat, vmt_path,
                        patched_cdmaterials_path, size, is_normal_map,
                    )

            VMTService.add_material_map_params(
                str(vmt_path), patched_cdmaterials_path, map_key, cfg["path_param"], extra
            )
            logger.info(f"Карта '{map_id}' [{mat}] → {map_key}.vtf ({'derive' if derive else 'file'})")

    @staticmethod
    def _ensure_derived_normal(
        base_image_path: str,
        vtf_output_path: Path,
        texture_filename: str,
        vmt_path: Path,
        patched_cdmaterials_path: str,
        size: Tuple[int, int],
        is_normal_map: bool,
    ) -> None:
        """
        Гарантирует наличие карты нормалей для phong (без неё блик не считается).

        Если normal уже сгенерирован (галочка Normal Map) или файл уже есть —
        ничего не делает. Иначе строит {texture}_normal.vtf из базовой текстуры
        (VTFCmd -normal, формат DXT5) и прописывает $bumpmap в VMT.
        """
        normal_vtf = vtf_output_path / f"{texture_filename}_normal.vtf"
        if is_normal_map or normal_vtf.exists():
            return
        try:
            norm_png = vtf_output_path / f"{texture_filename}_normal.png"
            VPKService._process_image(base_image_path, str(norm_png), size)
            VPKService._create_vtf(str(norm_png), str(vtf_output_path), "DXT5", [], {"normal": True})
            if norm_png.exists():
                norm_png.unlink()
            if normal_vtf.exists():
                VMTService.update_vmt_bumpmap_path(
                    str(vmt_path), patched_cdmaterials_path, f"{texture_filename}_normal"
                )
                logger.info(f"Авто-нормаль для phong создана: {normal_vtf.name}")
        except Exception as e:
            logger.warning(f"Не удалось создать авто-нормаль для phong: {e}", exc_info=True)

    @staticmethod
    def _file_content_hash(path: str) -> Optional[str]:
        """
        Быстрый хэш содержимого файла (для дедупликации одинаковых картинок).
        Возвращает hex-строку MD5 или None при ошибке чтения.
        Сравнение по содержимому ловит идентичные картинки даже из разных файлов.
        """
        import hashlib
        try:
            h = hashlib.md5()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 16), b""):
                    h.update(chunk)
            return h.hexdigest()
        except OSError:
            return None

    @staticmethod
    def _build_fixed_extra_textures(
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
        (вне QC/модели) — см. WEAPON_EXTRA_TEXTURES. Пример: HUD-вставки Dead Ringer.

        Схема «фикс консоль» (как у $cdmaterials):
          • VTF пишем под materials/console/<orig vtf>  — чтобы не клобберить глобально;
          • игровой VMT берём по оригинальному пути (туда смотрит HUD) и кладём в мод,
            пропатчив $basetexture → console/<orig basetexture>.

        Возвращает множество обработанных имён — чтобы общий цикл panel_extra_textures
        не записал их повторно по cdmaterials-пути.
        """
        handled: set = set()
        if not panel_extra_textures:
            return handled
        from src.data.weapons import WEAPON_EXTRA_TEXTURES
        cfg = WEAPON_EXTRA_TEXTURES.get(weapon_key, [])

        # Кэш уже сконвертированных VTF по хэшу содержимого исходной картинки.
        # Если в fg и bg (или любые два слота) загружена ОДНА И ТА ЖЕ картинка
        # (по содержимому, даже из разных файлов) — конвертируем один раз,
        # для остальных просто копируем готовый VTF. Конвертация GIF→VTF дорогая
        # (извлечение кадров), так что это заметно ускоряет сборку.
        _vtf_cache: dict = {}   # {img_hash: (built_vtf_path, fps)}

        for ex in cfg:
            name = ex["name"]
            img = panel_extra_textures.get(name)
            if not img or not os.path.isfile(img):
                continue
            try:
                # VTF и VMT кладём по РЕАЛЬНОМУ игровому пути (без console-схемы):
                # так VMT лежит в той же папке, что и VTF, и нет дублей vgui.
                vtf_rel = ex["vpk"].replace("\\", "/")               # materials/vgui/.../x.vtf
                base_no_mat = vtf_rel[len("materials/"):] if vtf_rel.startswith("materials/") else vtf_rel
                base_path = os.path.splitext(base_no_mat)[0]         # vgui/.../pocket_watch_fg (для $basetexture)

                # 1) VTF по реальному пути
                target_dir = ctx.vpkroot_dir
                for part in os.path.dirname(vtf_rel).split("/"):
                    if part:
                        target_dir = target_dir / part
                ensure_directory_exists(target_dir)
                stem = os.path.splitext(os.path.basename(vtf_rel))[0]
                dest_vtf = target_dir / f"{stem}.vtf"
                _flags, _merged = TextureService.resolve_vtf_flags_and_options(
                    flags, vtf_options, drop_normal=True
                )

                _img_hash = VPKService._file_content_hash(img)
                _cached = _vtf_cache.get(_img_hash) if _img_hash else None
                if str(img).lower().endswith('.vtf'):
                    # Пользователь загрузил готовый VTF — копируем как есть
                    copy_file_safe(img, dest_vtf)
                    _ex_fps = None
                    logger.info(f"Фикс. доп. текстура: готовый VTF скопирован → {stem}.vtf")
                elif _cached:
                    # Та же картинка уже сконвертирована — переиспользуем готовый VTF
                    _src_vtf, _ex_fps = _cached
                    copy_file_safe(_src_vtf, dest_vtf)
                    logger.info(
                        f"Доп. текстура переиспользована (идентичная картинка): "
                        f"{stem}.vtf ← {Path(_src_vtf).name}"
                    )
                elif TextureService.is_animated_image(img):
                    # Анимированный GIF → многокадровый VTF (циферблат Dead Ringer
                    # анимируется через AnimatedTexture-прокси в его игровом VMT).
                    _ex_fps = TextureService.create_animated_vtf(
                        img, str(dest_vtf), size, format_type, _flags, _merged
                    )
                    logger.info(f"Фикс. доп. текстура анимирована: {stem}.vtf @ {_ex_fps}fps")
                    if _img_hash:
                        _vtf_cache[_img_hash] = (dest_vtf, _ex_fps)
                else:
                    _ex_fps = None
                    tmp_png = target_dir / f"{stem}.png"
                    VPKService._process_image(img, str(tmp_png), size)
                    VPKService._create_vtf(str(tmp_png), str(target_dir), format_type, _flags, _merged)
                    if tmp_png.exists():
                        tmp_png.unlink()
                    if _img_hash:
                        _vtf_cache[_img_hash] = (dest_vtf, _ex_fps)

                # 2) VMT рядом с VTF ($basetexture → реальный путь)
                VPKService._write_fixed_extra_vmt(ex, base_path, ctx, misc_vpk, textures_vpk)

                # Игровой VMT fg/bg уже содержит AnimatedTexture-прокси, но если
                # его не нашли (минимальный шаблон) — добавляем прокси для анимации.
                if _ex_fps:
                    _vmt_target = ctx.vpkroot_dir
                    for _p in ex["vmt"].replace("\\", "/").split("/"):
                        if _p:
                            _vmt_target = _vmt_target / _p
                    if _vmt_target.exists():
                        VMTService.enable_animated_basetexture(str(_vmt_target), _ex_fps)

                handled.add(name)
                logger.info(f"Фикс. доп. текстура: {vtf_rel}; vmt={ex.get('vmt')}")
            except Exception as exc:
                logger.warning(f"Фикс. доп. текстура '{name}' — ошибка: {exc}", exc_info=True)
        return handled

    @staticmethod
    def _write_fixed_extra_vmt(ex: dict, base_texture_path: str, ctx,
                               misc_vpk: Optional[str], textures_vpk: Optional[str]) -> None:
        """
        Кладёт VMT фиксированной доп. текстуры В ТУ ЖЕ папку, что и её VTF
        (реальный игровой путь, без console-схемы).

        Берёт игровой VMT (если найден в VPK) и патчит $basetexture →
        base_texture_path; если игрового нет — создаёт минимальный UnlitGeneric.
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

    @staticmethod
    def _write_fixed_extra_files(weapon_key: str, ctx) -> None:
        """
        Пишет доп. статические файлы мода (HUD-скрипты .res, метаданные info.vdf
        и т.п.) по их зашитому пути в корень VPK — см. WEAPON_EXTRA_FILES.

        Содержимое фиксированное (из конфига). Пишется независимо от того,
        загрузил ли пользователь HUD-текстуры: эти файлы активируют мод
        (напр. кастомный циферблат Dead Ringer).
        """
        from src.data.weapons import WEAPON_EXTRA_FILES
        files = WEAPON_EXTRA_FILES.get(weapon_key, [])
        for f in files:
            rel = f.get("path", "").replace("\\", "/")
            content = f.get("content", "")
            if not rel:
                continue
            try:
                target = ctx.vpkroot_dir
                for part in rel.split("/"):
                    if part:
                        target = target / part
                ensure_directory_exists(target.parent)
                with open(target, "w", encoding="utf-8") as out:
                    out.write(content)
                logger.info(f"Доп. файл мода записан: {rel}")
            except Exception as exc:
                logger.warning(f"Не удалось записать доп. файл '{rel}': {exc}", exc_info=True)

    @staticmethod
    def _extract_original_vmt(
        cdmaterials_path: Optional[str],
        texture_filename: str,
        tf2_textures_vpk: Optional[str],
        tf2_misc_vpk: str,
        decompile_dir,
    ) -> Optional[str]:
        """
        Извлекает оригинальный VMT текстуры из игровых VPK.

        Порядок: tf2_textures_dir.vpk → tf2_misc_dir.vpk (Valve кладёт текстуры
        то туда, то туда). Возвращает путь к извлечённому VMT или None.
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

    @staticmethod
    def _find_decompiled_reference_smd(qc_path: str, weapon_key: str, decompile_dir) -> Optional[str]:
        """
        Находит основной reference-SMD декомпилированной модели.

        Сначала через QC-директивы ($body/studio) — надёжнее, т.к. Crowbar
        может назвать SMD иначе, чем weapon_key (особенно для шапок).
        Иначе — запасной поиск по имени файла.
        """
        smd = ModelBuildService.extract_main_body_smd(qc_path, weapon_key)
        if not smd:
            smd = SMDService.find_reference_smd(str(decompile_dir), weapon_key)
        return smd

    @staticmethod
    def _obtain_decompiled_qc(
        ctx,
        found_mdl_path: str,
        weapon_key: str,
        tf2_misc_vpk: str,
        crowbar_exe: str,
        debug_mode: bool,
        language: str,
        t: dict,
        emit_sub,
    ) -> Tuple[Optional[str], bool, Optional[str]]:
        """
        Возвращает QC-файл декомпилированной модели.

        Сначала пытается восстановить из кэша (cache hit — пропускает
        распаковку и Crowbar). Иначе извлекает MDL-набор из VPK и
        декомпилирует через Crowbar.

        Returns:
            (qc_path, was_cached, error). error != None → фатальная ошибка
            (MDL не извлёкся); вызывающий код чистит ctx и возвращает ошибку.
        """
        cached_decompile = get_cached_decompile(weapon_key, tf2_misc_vpk, found_mdl_path)
        if cached_decompile:
            # CACHE HIT — пропускаем extraction и decompile
            emit_sub(-1, "Restoring cache..." if language == "en" else "Восстановление кэша...")
            qc_path = restore_from_cache(cached_decompile, ctx.decompile_dir)
            return qc_path, True, None

        # CACHE MISS — извлекаем и декомпилируем
        emit_sub(-1, "Extracting model..." if language == "en" else "Извлечение модели...")
        logger.info(f"Извлекаем файлы модели: {found_mdl_path}")
        extracted_files = TF2VPKExtractService.extract_file_set(
            tf2_misc_vpk,
            found_mdl_path,
            str(ctx.extract_dir),
        )

        mdl_file = next((f for f in extracted_files if f.endswith('.mdl')), None)
        if not mdl_file:
            return None, False, t['error_mdl_not_extracted'].format(path=found_mdl_path)

        if debug_mode:
            DebugService.save_extracted_stage(ctx, extracted_files)

        emit_sub(-1, "Decompiling model..." if language == "en" else "Декомпиляция модели...")
        logger.info(f"Запускаем Crowbar для {weapon_key}...")
        qc_path = ModelBuildService.decompile(mdl_file, ctx.decompile_dir, crowbar_exe)
        if debug_mode:
            DebugService.save_decompiled_stage(ctx, ctx.decompile_dir)
        return qc_path, False, None

    @staticmethod
    def _apply_model_replacement(
        ctx,
        qc_path: str,
        weapon_key: str,
        replace_model_smd_path: Optional[str],
        extra_model_callback,
        language: str,
        emit_sub,
        keep_user_materials: bool = False,
    ) -> None:
        """
        Применяет пользовательскую замену модели поверх декомпилированных SMD.

        1. Главный reference-SMD: nodes/skeleton/материалы — из оригинала,
           данные треугольников — из пользовательского файла.
        2. Доп. части (shell, scope и т.п.): спрашивает каждую через
           extra_model_callback и заменяет по тому же принципу.

        Ошибки замены не прерывают сборку — логируются, сборка продолжается
        с оригинальной моделью.
        """
        if replace_model_smd_path and os.path.exists(replace_model_smd_path):
            try:
                # Ищем основной reference-SMD через QC-директивы ($body/studio).
                # Это надёжнее поиска по имени файла, т.к. Crowbar может назвать SMD
                # иначе чем weapon_key (особенно для шапок).
                _smd_files_in_decompile = [f for f in os.listdir(ctx.decompile_dir) if f.endswith('.smd')] if ctx.decompile_dir.exists() else []
                logger.info(f"[REPLACE] weapon_key={weapon_key!r}  decompile SMDs={_smd_files_in_decompile}")

                original_smd_path = VPKService._find_decompiled_reference_smd(
                    qc_path, weapon_key, ctx.decompile_dir
                )

                if original_smd_path:
                    logger.info(f"Заменяем модель: {replace_model_smd_path} -> {original_smd_path}")
                    emit_sub(-1, "Replacing model..." if language == "en" else "Замена модели...")
                    # Заменяем секции: nodes и skeleton из оригинального (иначе модель не скомпилируется),
                    # названия материалов из оригинального (иначе текстуры не загрузятся),
                    # данные треугольников из пользовательского (это то, что юзер хочет заменить)
                    SMDService.replace_model_sections(
                        replace_model_smd_path,
                        original_smd_path,
                        original_smd_path,  # Перезаписываем оригинальный файл под тем же именем
                        progress_cb=lambda pct: emit_sub(pct, "Replacing model..." if language == "en" else "Замена модели..."),
                        keep_user_materials=keep_user_materials,
                    )
                    logger.info(
                        f"Модель успешно заменена: {original_smd_path} "
                        f"(keep_user_materials={keep_user_materials})"
                    )
                else:
                    logger.warning(f"Не найден reference SMD файл для {weapon_key} в {ctx.decompile_dir}")
                    if ctx.decompile_dir.exists():
                        smd_files = [f for f in os.listdir(ctx.decompile_dir) if f.endswith('.smd')]
                        logger.debug(f"Доступные SMD файлы в директории: {smd_files}")
            except Exception as e:
                logger.error(f"Ошибка при замене модели: {e}", exc_info=True)
                # Не прерываем сборку, просто продолжаем с оригинальной моделью (лучше так, чем упасть)
                    
        # === Замена дополнительных частей модели (shell, scope и т.д.) ===
        # Проверяем, есть ли в QC файле дополнительные bodygroup SMD
        extra_body_smds = ModelBuildService.extract_extra_body_smds(qc_path, weapon_key)
        if extra_body_smds:
            extra_smd_names = [os.path.basename(s) for s in extra_body_smds]
            logger.info(f"Найдены дополнительные части модели: {extra_smd_names}")
                        
            if extra_model_callback:
                for extra_smd_path in extra_body_smds:
                    extra_smd_name = os.path.basename(extra_smd_path)
                    extra_smd_base = os.path.splitext(extra_smd_name)[0]
                                
                    try:
                        # Спрашиваем пользователя через callback
                        user_extra_smd = extra_model_callback(extra_smd_base, weapon_key)
                                    
                        if user_extra_smd and os.path.exists(user_extra_smd):
                            logger.info(f"Заменяем доп. часть модели: {user_extra_smd} -> {extra_smd_path}")
                            emit_sub(-1, f"Replacing {extra_smd_base}..." if language == "en" else f"Замена {extra_smd_base}...")
                            SMDService.replace_model_sections(
                                user_extra_smd,
                                extra_smd_path,
                                extra_smd_path,  # Перезаписываем оригинал
                                progress_cb=lambda pct: emit_sub(pct, f"Replacing {extra_smd_base}..." if language == "en" else f"Замена {extra_smd_base}..."),
                            )
                            logger.info(f"Доп. часть модели успешно заменена: {extra_smd_name}")
                        else:
                            logger.info(f"Пользователь пропустил замену доп. части: {extra_smd_name}")
                    except Exception as e:
                        logger.error(f"Ошибка при замене доп. части модели {extra_smd_name}: {e}", exc_info=True)
            else:
                logger.debug(f"Нет callback для замены доп. частей модели, пропускаем")

    @staticmethod
    def _copy_precompiled_model(
        model_ready_path: str,
        qc_path: str,
        weapon_key: str,
        ctx,
        language: str,
        emit_sub,
    ) -> None:
        """
        Копирует pre-compiled модель (.mdl/.vvd/.vtx/.phy) в compile_dir,
        переименовывая под $modelname из QC (а не под имя пользовательского
        файла) — иначе все файлы мода получат чужое имя. studiomdl не нужен.
        """
        emit_sub(-1, "Copying ready model..." if language == "en" else "Копирование готовой модели...")
        try:
            ready_dir   = os.path.dirname(model_ready_path)
            ready_stem  = os.path.splitext(os.path.basename(model_ready_path))[0]
            model_exts  = ('.mdl', '.vvd', '.vtx', '.phy', '.dx80.vtx', '.dx90.vtx', '.sw.vtx')
            # Целевое имя: $modelname из QC (совпадает с weapon_key).
            # Запрещено падать обратно на ready_stem (имя пользовательского файла) —
            # это приводит к тому, что все файлы мода переименовываются в имя
            # загруженной модели вместо оригинального имени шапки/оружия.
            qc_modelname = ModelBuildService.extract_modelname_path(qc_path)
            if qc_modelname:
                target_stem = os.path.splitext(os.path.basename(qc_modelname))[0]
            else:
                # Fallback на weapon_key (оригинальное имя из игры), а не на ready_stem
                target_stem = weapon_key
                logger.warning(
                    f"[MODEL READY] $modelname не найден в QC, используем weapon_key={weapon_key!r} "
                    f"вместо ready_stem={ready_stem!r}"
                )
            logger.info(
                f"[MODEL READY] ready_stem={ready_stem!r} → target_stem={target_stem!r}"
            )
            ensure_directory_exists(ctx.compile_dir)
            copied = 0
            for fname in os.listdir(ready_dir):
                base, ext = os.path.splitext(fname)
                # Простые расширения (os.path.splitext возвращает с точкой: '.mdl')
                if base == ready_stem and ext.lower() in ('.mdl', '.vvd', '.phy'):
                    dst_name = target_stem + ext
                    copy_file_safe(
                        os.path.join(ready_dir, fname),
                        str(ctx.compile_dir / dst_name)
                    )
                    copied += 1
                elif fname.startswith(ready_stem) and any(fname.endswith(e) for e in model_exts):
                    # Составные расширения: .dx90.vtx, .sw.vtx и т.п.
                    suffix  = fname[len(ready_stem):]
                    dst_name = target_stem + suffix
                    copy_file_safe(
                        os.path.join(ready_dir, fname),
                        str(ctx.compile_dir / dst_name)
                    )
                    copied += 1
            if copied == 0:
                logger.warning(
                    f"Не найдено ни одного файла модели рядом с {model_ready_path}. "
                    "Попробуем всё равно продолжить."
                )
            logger.info(f"Готовая модель: скопировано {copied} файлов в {ctx.compile_dir}")
        except Exception as _e:
            logger.error(f"Ошибка копирования готовой модели: {_e}", exc_info=True)

    @staticmethod
    def _start_model_compile(
        model_ready_path: Optional[str],
        qc_path: str,
        weapon_key: str,
        ctx,
        studiomdl_exe: str,
        tf_dir: str,
        debug_mode: bool,
        language: str,
        emit_sub,
    ) -> Tuple[threading.Thread, list]:
        """
        Запускает (в фоне) получение скомпилированной модели и возвращает
        (compile_thread, compile_exc). Вызывающий код делает join() и, если
        compile_exc[0] не None, поднимает исключение.

        Сценарии:
          • model_ready = .smd → заменяем reference SMD и компилируем studiomdl;
          • model_ready = .mdl → копируем pre-compiled файлы (без studiomdl);
          • обычная сборка → компилируем декомпилированный QC.
        Компиляция идёт в фоне параллельно генерации VTF/VMT в главном потоке.
        """
        compile_exc: list = [None]

        def _do_compile() -> None:
            try:
                emit_sub(-1, "Compiling model..." if language == "en" else "Компиляция модели...")
                ModelBuildService.compile(qc_path, ctx.compile_dir, studiomdl_exe, tf_dir)
                if debug_mode:
                    DebugService.save_compiled_stage(ctx, ctx.compile_dir)
            except Exception as _e:
                compile_exc[0] = _e

        if model_ready_path and os.path.exists(model_ready_path):
            if model_ready_path.lower().endswith('.smd'):
                # SMD: заменяем reference SMD оригинала и компилируем через studiomdl
                emit_sub(-1, "Replacing model SMD..." if language == "en" else "Замена SMD модели...")
                try:
                    original_smd_path = VPKService._find_decompiled_reference_smd(
                        qc_path, weapon_key, ctx.decompile_dir
                    )
                    if original_smd_path:
                        logger.info(f"[MODEL READY SMD] Копируем {model_ready_path} → {original_smd_path}")
                        copy_file_safe(model_ready_path, original_smd_path)
                    else:
                        logger.warning(
                            f"[MODEL READY SMD] Не найден reference SMD для {weapon_key}, "
                            f"копируем в decompile_dir как {weapon_key}_reference.smd"
                        )
                        copy_file_safe(model_ready_path, str(ctx.decompile_dir / f"{weapon_key}_reference.smd"))
                except Exception as _e:
                    logger.error(f"Ошибка замены SMD модели: {_e}", exc_info=True)
                thread = threading.Thread(target=_do_compile, daemon=True)
            else:
                # MDL: копируем готовые pre-compiled файлы, studiomdl не нужен
                VPKService._copy_precompiled_model(
                    model_ready_path, qc_path, weapon_key, ctx, language, emit_sub
                )
                thread = threading.Thread(target=lambda: None, daemon=True)
        else:
            # Обычная сборка: компилируем декомпилированный QC
            thread = threading.Thread(target=_do_compile, daemon=True)

        thread.start()
        return thread, compile_exc

    @staticmethod
    def _write_main_vmt(
        vmt_file: Optional[str],
        vmt_path,
        texture_filename: str,
        patched_cdmaterials_path: str,
        mode: str,
        hat_apply_game_paints: bool,
        animated_fps: Optional[float],
        is_normal_map: bool,
    ) -> Optional[str]:
        """
        Записывает главный VMT текстуры и возвращает vmt_to_delete
        (имя отредактированного VMT, который надо убрать из tools/edited_vmt
        после сборки), либо None.

        Приоритет источника: отредактированный пользователем VMT → извлечённый
        из игры → шаблон по $cdmaterials. Затем: снятие красок (шапки),
        анимация ($basetexture) и $bumpmap (normal-map).
        """
        vmt_to_delete = None
        # Проверяем, есть ли отредактированный VMT файл (приоритет 1 - юзер знает лучше)
        from src.services.edited_vmt_service import EditedVMTService
        edited_vmt_path = EditedVMTService.get_edited_vmt(texture_filename)
                    
        if edited_vmt_path and Path(edited_vmt_path).exists():
            # Используем отредактированный VMT файл (юзер его правил через редактор)
            copy_file_safe(edited_vmt_path, vmt_path)
            # Обновляем путь $baseTexture в отредактированном VMT файле на основе пути из QC
            # (потому что путь может измениться, а юзер редактировал старый)
            VMTService.update_vmt_basetexture_path(str(vmt_path), patched_cdmaterials_path, texture_filename)
            logger.info(f"Использован отредактированный VMT файл: {edited_vmt_path} -> {vmt_path}")
            vmt_to_delete = texture_filename
        elif vmt_file and Path(vmt_file).exists():
            # Если VMT файл извлечен, копируем его в нужную директорию и обновляем путь $baseTexture
            # (потому что путь в оригинале может быть другим)
            copy_file_safe(vmt_file, vmt_path)
            VMTService.update_vmt_basetexture_path(str(vmt_path), patched_cdmaterials_path, texture_filename)
            logger.info(f"Скопирован и обновлен извлеченный VMT файл: {vmt_file} -> {vmt_path}")
        else:
            # Если VMT файл не извлечен, создаем из шаблона (базовый VMT, ничего особенного)
            VMTService.create_vmt_template_from_cdmaterials(str(vmt_path), patched_cdmaterials_path, texture_filename)
            logger.info(f"Создан VMT файл из шаблона: {vmt_path}")

        # Для шапок: если пользователь не хочет красок из игры — удаляем прокси красок
        if mode == "hat" and not hat_apply_game_paints:
            VMTService.remove_paint_proxies(str(vmt_path))
            logger.info(f"Удалены прокси красок из VMT файла шапки: {vmt_path}")

        if animated_fps:
            VMTService.enable_animated_basetexture(str(vmt_path), animated_fps)
                    
        # Если normal map включена, обновляем VMT файл для добавления $bumpmap
        # (это нужно для бампмаппинга, иначе нормалмап не загрузится)
        if is_normal_map:
            normal_weapon_key = f"{texture_filename}_normal"
            VMTService.update_vmt_bumpmap_path(str(vmt_path), patched_cdmaterials_path, normal_weapon_key)
            logger.info(f"Обновлен VMT файл для добавления $bumpmap: {normal_weapon_key}")
        return vmt_to_delete

    @staticmethod
    def build_with_progress(
        image_path: str,
        mode: str,
        filename: str,
        size: Tuple[int, int],
        format_type: str = "DXT1",
        flags: List[str] = None,
        vtf_options: dict = None,
        tf2_root_dir: str = "",
        export_folder: str = "export",
        keep_temp_on_error: bool = False,
        debug_mode: bool = False,
        replace_model_enabled: bool = False,
        model_ready_path: Optional[str] = None,
        draw_uv_layout: bool = False,
        replace_model_path: str = None,
        model_file_callback: Optional[Callable[[], Optional[str]]] = None,
        extra_texture_callback: Optional[Callable[[str, str], Optional[str]]] = None,
        extra_model_callback: Optional[Callable[[str, str], Optional[str]]] = None,
        texture_mismatch_callback: Optional[Callable[[str], bool]] = None,
        language: str = "en",
        custom_vtf_path: str = None,
        blu_mode: str = "none",
        blu_image_path: Optional[str] = None,
        custom_vpk_source_path: Optional[str] = None,
        hat_mdl_path: Optional[str] = None,
        hat_apply_game_paints: bool = True,
        panel_extra_textures: Optional[dict] = None,
        material_maps: Optional[dict] = None,
        material_settings: Optional[dict] = None,
        skin_build_data: Optional[dict] = None,
        replace_keep_materials: bool = False,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        sub_progress_callback: Optional[Callable[[int, str], None]] = None,
        cancel_callback: Optional[Callable[[], bool]] = None
    ) -> Tuple[bool, str, bool]:
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

            is_special_mode = mode in SPECIAL_MODES.values()

            _sub_label_init = "Preparing..." if language == "en" else "Подготовка..."
            emit_sub(-1, _sub_label_init)

            # Аргументы build_vpk одинаковы для обоих режимов — собираем один раз.
            build_kwargs = dict(
                image_path=image_path,
                mode=mode,
                filename=filename,
                size=size,
                format_type=format_type,
                flags=flags,
                vtf_options=vtf_options,
                tf2_root_dir=tf2_root_dir,
                export_folder=export_folder,
                keep_temp_on_error=keep_temp_on_error,
                debug_mode=debug_mode,
                replace_model_enabled=replace_model_enabled,
                model_ready_path=model_ready_path,
                draw_uv_layout=draw_uv_layout,
                replace_model_path=replace_model_path,
                model_file_callback=model_file_callback if replace_model_enabled else None,
                extra_texture_callback=extra_texture_callback,
                extra_model_callback=extra_model_callback,
                texture_mismatch_callback=texture_mismatch_callback,
                language=language,
                custom_vtf_path=custom_vtf_path,
                blu_mode=blu_mode,
                blu_image_path=blu_image_path,
                sub_progress_callback=emit_sub,
                hat_mdl_path=hat_mdl_path,
                hat_apply_game_paints=hat_apply_game_paints,
                panel_extra_textures=panel_extra_textures,
                material_maps=material_maps,
                material_settings=material_settings,
                skin_build_data=skin_build_data,
                replace_keep_materials=replace_keep_materials,
                progress_callback=progress_callback,
                cancel_callback=cancel_callback,
            )

            # Прогресс эмитится самим build_vpk на реальных границах стадий
            # (декомпиляция / текстуры / компиляция / упаковка) — без
            # потока-имитатора с фиксированными процентами.
            if is_special_mode:
                emit_progress(20, t.get('build_processing', 'Processing texture...'))
            else:
                emit_progress(10, t.get('build_extracting', 'Extracting model...'))
            success, message = VPKService.build_vpk(**build_kwargs)

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
    def build_vpk(
        image_path: str,
        mode: str,
        filename: str,
        size: Tuple[int, int],
        format_type: str = "DXT1",
        flags: List[str] = None,
        vtf_options: dict = None,
        tf2_root_dir: str = "",
        export_folder: str = "export",
        keep_temp_on_error: bool = False,
        debug_mode: bool = False,
        replace_model_enabled: bool = False,
        model_ready_path: Optional[str] = None,
        draw_uv_layout: bool = False,
        parent_window=None,  # Окно для диалогов (если нужно показать что-то юзеру)
        replace_model_path: str = None,  # Путь к модели для замены (для тестов, обычно None)
        model_file_callback=None,  # Колбэк для запроса файла из UI потока (потому что Qt не любит мультипоточность)
        extra_texture_callback=None,  # Колбэк для запроса одной доп. текстуры: callback(material_name, weapon_key) -> Optional[str]
        extra_model_callback=None,  # Колбэк для запроса доп. модели: callback(smd_name, weapon_key) -> Optional[str]
        texture_mismatch_callback=None,  # Колбэк для предупреждения о несовпадении текстур: callback(msg) -> bool
        hat_mdl_path: Optional[str] = None,  # Прямой MDL-путь для шапок (обходит WEAPON_MDL_PATHS)
        hat_apply_game_paints: bool = True,  # True = сохранить краски игры, False = убрать прокси красок из VMT
        language: str = "en",  # Язык для ошибок
        custom_vtf_path: str = None,  # Если юзер сам сделал VTF - используем его вместо генерации из картинки
        blu_mode: str = "none",       # BLU-командная текстура: 'none' | 'same' | 'upload' | 'hue_shift'
        blu_image_path: str = None,   # Путь к BLU-изображению (для 'upload' / 'hue_shift')
        sub_progress_callback: Optional[Callable[[int, str], None]] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,  # Главный прогресс (проценты стадий)
        cancel_callback: Optional[Callable[[], bool]] = None,  # True = пользователь запросил отмену
        panel_extra_textures: Optional[dict] = None,  # {mat_name: img_path} из 2D панели
        material_maps: Optional[dict] = None,  # файловые карты материала (detail/selfillum/phongexp)
        material_settings: Optional[dict] = None,  # пер-текстурные настройки {material: {size,format,flags,options}}
        skin_build_data: Optional[dict] = None,  # стили кастомной модели → $texturegroup + варианты
        replace_keep_materials: bool = False,  # сохранить материалы пользовательской модели (многотекстурная/«готовая»)
    ) -> Tuple[bool, str]:
        """
        Главная функция: делает из картинки VPK файл.
        Возвращает (success, message); при ошибке message содержит описание.
        Здесь весь конвейер: модель → текстуры → компиляция → упаковка.
        """
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
            validation_error = VPKService._validate_build_params(
                image_path, mode, filename, size, format_type, tf2_root_dir, t, custom_vtf_path
            )
            if validation_error:
                return False, validation_error
            
            if flags is None:
                flags = []
            
            # Для режимов рук weapon_key — это ключ arm-модели (например "c_scout_arms"),
            # а не суффикс mode-строки (который дал бы бессмысленное "hands").
            # Для режимов скина персонажа weapon_key — это ключ MDL модели (например "player_scout").
            if mode == "hat" and hat_mdl_path:
                # Шапка: weapon_key берём из стема MDL-пути
                weapon_key = Path(hat_mdl_path).stem
                logger.info(f"[HAT] hat_mdl_path={hat_mdl_path!r}  →  weapon_key={weapon_key!r}")
            elif mode in HAND_MODE_KEYS:
                from src.data.player_hands import HAND_MODES as _HAND_MODES
                _arm_key = _HAND_MODES.get(mode, {}).get('arm_model', '')
                if not _arm_key:
                    return False, f"No arm_model defined for hand mode: {mode}"
                weapon_key = _arm_key
            elif mode in PLAYER_BODY_MODE_KEYS:
                from src.data.player_characters import PLAYER_CHARACTERS as _PC
                _mdl_path = _PC.get(mode, {}).get('mdl_path', '')
                weapon_key = Path(_mdl_path).stem if _mdl_path else mode
            elif mode == SPY_MASK_MODE_KEY:
                # Маски маскировки: используем тот же MDL что и для скина шпиона
                weapon_key = Path(SPY_MDL_PATH).stem  # = 'spy'
            else:
                weapon_key = mode.split('_', 1)[1] if '_' in mode else mode
            
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
                # Для обычного оружия и рук — декомпиляция + патч QC + компиляция.
                # Для рук замена SMD-модели не поддерживается.
                if mode in HAND_MODE_KEYS:
                    replace_model_enabled = False

                # Без пути к TF2 продолжать нельзя — нужны VPK файлы игры
                if not tf2_root_dir:
                    logger.error("Путь к TF2 не указан")
                    ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                    return False, t['error_tf2_not_specified']
                
                # Crowbar нужен для декомпиляции, без него никак
                crowbar_exists, crowbar_error = TF2Paths.check_crowbar()
                if not crowbar_exists:
                    ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                    return False, crowbar_error
                
                try:
                    studiomdl_exe, tf2_misc_vpk, tf_dir = TF2Paths.resolve(tf2_root_dir)
                except FileNotFoundError as e:
                    ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                    return False, str(e)
                
                # ── Строим список путей для поиска MDL ───────────────────────────── #
                paths_to_try, _mdl_path_error = VPKService._build_mdl_search_paths(
                    mode, weapon_key, hat_mdl_path, t
                )
                if _mdl_path_error:
                    ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                    return False, _mdl_path_error

                crowbar_exe = TF2Paths.get_crowbar_path()
                
                try:
                    found_mdl_path, _mdl_find_error = VPKService._find_existing_mdl(
                        paths_to_try, tf2_misc_vpk, weapon_key, t
                    )
                    if _mdl_find_error:
                        ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                        return False, _mdl_find_error
                    
                    # Для шапок с %s-плейсхолдером: обновляем weapon_key на реальный стем
                    # (all_domination_%s → all_domination_heavy), иначе кэш и имена файлов сломаются
                    if mode == "hat" and hat_mdl_path and "%s" in hat_mdl_path:
                        weapon_key = Path(found_mdl_path).stem
                        logger.info(f"Hat weapon_key обновлён: {weapon_key}")

                    if is_cancelled():
                        return cancelled_result(ctx)
                    emit_progress(25, t.get('build_decompiling', 'Decompiling model...'))

                    # === Кэш декомпила — проверяем ДО extraction ===
                    # Ключ: weapon_key + vpk_path + mdl_rel_path + mtime(vpk).
                    # mtime VPK меняется при каждом обновлении TF2 → авто-инвалидация.
                    # При cache hit: пропускаем extract_file_set (3-10 сек) + Crowbar (10-30 сек).
                    qc_path, cached_decompile, _decomp_error = VPKService._obtain_decompiled_qc(
                        ctx, found_mdl_path, weapon_key, tf2_misc_vpk, crowbar_exe,
                        debug_mode, language, t, emit_sub,
                    )
                    if _decomp_error:
                        ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                        return False, _decomp_error

                    if draw_uv_layout:
                        VPKService._generate_uv_layout(ctx, weapon_key, size, export_folder, language)

                    # Удаляем LOD файлы до кэширования — чтобы в кэше лежали уже чистые файлы
                    ModelBuildService.remove_lod_files(ctx.decompile_dir)

                    # Сохраняем в кэш после очистки — следующая сборка пропустит extraction + decompile
                    if not cached_decompile:
                        save_to_cache(weapon_key, tf2_misc_vpk, found_mdl_path, ctx.decompile_dir)

                    if is_cancelled():
                        return cancelled_result(ctx)
                    emit_progress(40, t.get('build_processing', 'Processing texture...'))
                    
                    # Заменяем модель, если включен режим замены
                    # Пропускаем если model_ready_path задан — пользователь уже указал готовый файл
                    # Диалог выбора файла показываем здесь, после декомпиляции (чтобы знать куда копировать)
                    replace_model_smd_path = VPKService._resolve_replace_model_smd(
                        replace_model_enabled, model_ready_path, replace_model_path,
                        model_file_callback, parent_window,
                    )
                    
                    VPKService._apply_model_replacement(
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
                    tg_structure = ModelBuildService.extract_texturegroup_structure(qc_path)
                    blu_row = tg_structure.get('blu_row', [])
                    extra_materials = tg_structure.get('extra_materials', [])

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

                    # Исключаем служебные материалы (глаза/зубы/sheen-оверлеи) —
                    # для них не нужно спрашивать текстуру при сборке. Тот же фильтр,
                    # что и для карточек 2D (единый источник). Делаем ПОСЛЕ hands-блока,
                    # т.к. он переназначает extra_materials/blu_row.
                    from src.data.material_filter import is_editable_material as _is_edit
                    _drop_extra = [m for m in extra_materials if not _is_edit(m)]
                    if _drop_extra:
                        logger.info(f"Служебные материалы исключены из сборки: {_drop_extra}")
                    extra_materials = [m for m in extra_materials if _is_edit(m)]
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
                    _has_skins = bool(skin_build_data and skin_build_data.get('tg_overrides'))
                    # Для «готовой» кастомной модели (keep_materials) ИГРОВОЙ
                    # $texturegroup неприменим ВСЕГДА — у меша свои материалы
                    # (c_sd_cleaver/mouth/lefteye…), а игровые имена (c_scattergun,
                    # c_scattergun_gold) к нему отношения не имеют. Иначе сборка
                    # начнёт спрашивать текстуры для игровых слотов, которых нет
                    # в карточках. Базовые меш-материалы идут через panel_extra_textures.
                    if _has_skins or replace_keep_materials:
                        logger.info(
                            "[SKIN BUILD] кастомная модель → подавляем игровой "
                            f"texturegroup (blu_row={blu_row}, extra={extra_materials})"
                        )
                        blu_row = []
                        extra_materials = []
                        blu_mode = 'none'   # не плодим {texture}_blue

                    if blu_row:
                        logger.info(f"Найдена BLU команда: {blu_row}")
                    if extra_materials:
                        logger.info(f"Найдены дополнительные материалы модели: {extra_materials}")

                    # Пропатчиваем QC файл: добавляем console\ к $cdmaterials (чтобы текстуры загружались из консольных команд),
                    # удаляем $lod (они нам не нужны, только мусорят)
                    ModelBuildService.patch_qc_file(qc_path, weapon_key, original_cdmaterials_path)

                    # Игровое имя текстуры/VMT (источник ОРИГИНАЛЬНОГО кода VMT из игры).
                    # Для кастомной модели texture_filename станет именем материала SMD,
                    # но оригинальный VMT тащим по игровому имени (c_sd_cleaver),
                    # затем лишь переставим $basetexture на материал модели.
                    _game_vmt_name = texture_filename

                    # ── Кастомная модель: имена ведём от ФАКТИЧЕСКИХ материалов SMD ──
                    # Имена VTF/VMT, $texturegroup и $basetexture обязаны совпадать с
                    # материалом, с которым реально компилируется модель (из reference-SMD).
                    # UI-имена могли разойтись с SMD (другой экспорт/регистр) → текстура
                    # не находилась (фиолетовая). Картинки скинов мапим по индексу.
                    if replace_keep_materials:
                        _ref_smd = VPKService._find_decompiled_reference_smd(
                            qc_path, weapon_key, ctx.decompile_dir
                        )
                        _smd_mats = SMDService.ordered_unique_materials(_ref_smd) if _ref_smd else []
                        if _smd_mats:
                            logger.info(f"[SKIN BUILD] материалы SMD (истина): {_smd_mats}")
                            if _has_skins:
                                skin_build_data = VPKService._remap_skin_data_to_smd(
                                    skin_build_data, _smd_mats
                                )
                            if texture_filename != _smd_mats[0]:
                                logger.info(
                                    f"[SKIN BUILD] main texture_filename: "
                                    f"{texture_filename!r} → {_smd_mats[0]!r} (материал SMD)"
                                )
                                texture_filename = _smd_mats[0]

                    # ── $texturegroup кастомной модели ──
                    if _has_skins:
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
                    materials_path_parts = materials_rel_path.rstrip('/').split('/')
                    vtf_output_path = ctx.vpkroot_dir
                    for part in materials_path_parts:
                        vtf_output_path = vtf_output_path / part
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
                    if (model_ready_path and os.path.exists(model_ready_path)
                            and model_ready_path.lower().endswith('.smd')):
                        try:
                            user_materials = SMDService.extract_unique_materials(model_ready_path)
                            if user_materials:
                                # Ищем оригинальный reference SMD для сравнения
                                original_smd_for_check = VPKService._find_decompiled_reference_smd(
                                    qc_path, weapon_key, ctx.decompile_dir
                                )

                                if original_smd_for_check:
                                    original_materials = SMDService.extract_unique_materials(original_smd_for_check)
                                    if original_materials and user_materials != original_materials:
                                        # Есть расхождение — формируем сообщение
                                        missing_in_user = original_materials - user_materials
                                        extra_in_user = user_materials - original_materials

                                        lines = []
                                        if language == "ru":
                                            lines.append("Текстуры в вашем SMD файле не совпадают с оригинальной моделью.\n")
                                            if missing_in_user:
                                                lines.append("Отсутствуют (есть в оригинале, нет у вас):")
                                                for m in sorted(missing_in_user):
                                                    lines.append(f"  • {m}")
                                            if extra_in_user:
                                                lines.append("Лишние (есть у вас, нет в оригинале):")
                                                for m in sorted(extra_in_user):
                                                    lines.append(f"  • {m}")
                                            lines.append("\nПродолжить сборку с этими текстурами?")
                                        else:
                                            lines.append("Textures in your SMD file do not match the original model.\n")
                                            if missing_in_user:
                                                lines.append("Missing (in original, not in yours):")
                                                for m in sorted(missing_in_user):
                                                    lines.append(f"  • {m}")
                                            if extra_in_user:
                                                lines.append("Extra (in yours, not in original):")
                                                for m in sorted(extra_in_user):
                                                    lines.append(f"  • {m}")
                                            lines.append("\nContinue building with these textures?")

                                        warning_msg = "\n".join(lines)
                                        logger.warning(f"[MODEL READY] Несовпадение текстур SMD:\n{warning_msg}")

                                        if texture_mismatch_callback:
                                            should_continue = texture_mismatch_callback(warning_msg)
                                            if not should_continue:
                                                logger.info("[MODEL READY] Пользователь отменил сборку из-за несовпадения текстур")
                                                ctx.cleanup(on_error=False, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
                                                cancel_msg = (
                                                    "Сборка отменена: несовпадение текстур в SMD файле."
                                                    if language == "ru" else
                                                    "Build cancelled: texture mismatch in SMD file."
                                                )
                                                return False, cancel_msg
                                    elif original_materials:
                                        logger.info(f"[MODEL READY] Текстуры SMD совпадают с оригиналом: {user_materials}")
                        except Exception as _tex_check_err:
                            logger.warning(f"[MODEL READY] Ошибка проверки текстур SMD: {_tex_check_err}", exc_info=True)
                            # Не блокируем сборку из-за ошибки проверки

                    if is_cancelled():
                        return cancelled_result(ctx)
                    emit_progress(60, t.get('build_compiling', 'Compiling model...'))

                    # ── Компиляция модели в фоне: обычная / SMD-замена / готовый MDL ──
                    _compile_thread, _compile_exc = VPKService._start_model_compile(
                        model_ready_path, qc_path, weapon_key, ctx,
                        studiomdl_exe, tf_dir, debug_mode, language, emit_sub,
                    )

                    is_normal_map = False
                    animated_fps = None

                    # spy_masks обрабатывается РАНЬШЕ (до MDL pipeline) через
                    # _build_spy_masks_vpk — сюда попасть не должен.

                    # RED не загружен — сначала спрашиваем пользователя
                    # через существующий extra_texture_callback (стандартный диалог).
                    # Если callback вернул EXTRA_TEX_USE_GAME_ORIGINAL или None —
                    # извлекаем оригинал из игрового VPK.
                    if image_path == EXTRA_TEX_USE_GAME_ORIGINAL:
                        if extra_texture_callback:
                            image_path = extra_texture_callback(texture_filename, weapon_key)
                            logger.info(f"Callback для основной RED текстуры: {image_path!r}")

                        if image_path == EXTRA_TEX_USE_GAME_ORIGINAL or not image_path:
                            # Пользователь выбрал «из игры» или ничего — берём оригинал
                            _tex_vpk_early = TF2Paths.resolve_textures_vpk(tf2_root_dir)
                            _orig_red = VPKService._get_original_vtf_bytes(
                                texture_filename, original_cdmaterials_paths,
                                _tex_vpk_early, tf2_misc_vpk
                            )
                            ensure_directory_exists(vtf_output_path)
                            vtf_file_path = vtf_output_path / vtf_filename
                            if _orig_red:
                                with open(vtf_file_path, "wb") as _f:
                                    _f.write(_orig_red)
                                logger.info(f"Оригинальная RED VTF из игры: {vtf_filename}")
                            else:
                                logger.warning(f"Не найден оригинальный RED VTF: '{texture_filename}'")
                            image_path = None  # VTF уже на месте, не передаём дальше

                    # Эффективные настройки на материал: пер-текстурный оверрайд
                    # поверх глобальных (size/format/flags/options). Нет оверрайда —
                    # возвращаются глобальные, поведение не меняется.
                    from src.data.texture_overrides import effective_settings as _eff_settings
                    _global_tex = {'size': size, 'format': format_type,
                                   'flags': flags or [], 'options': vtf_options or {}}

                    def _eff(_mat):
                        e = _eff_settings(_global_tex, (material_settings or {}).get(_mat))
                        return e['size'], e['format'], e['flags'], e['options']

                    if custom_vtf_path:
                        # Если юзер сам сделал VTF - просто копируем его, не генерируем из картинки
                        vtf_file_path = vtf_output_path / vtf_filename
                        ensure_directory_exists(vtf_output_path)
                        copy_file_safe(custom_vtf_path, vtf_file_path)
                        logger.info(f"Использован пользовательский VTF файл: {custom_vtf_path} -> {vtf_file_path}")
                    elif image_path and str(image_path).lower().endswith('.vtf'):
                        # В карточку главного материала загрузили готовый VTF —
                        # копируем как есть, без PIL-конвертации (иначе «cannot identify image»).
                        ensure_directory_exists(vtf_output_path)
                        copy_file_safe(image_path, vtf_output_path / vtf_filename)
                        logger.info(f"Главная текстура: готовый VTF скопирован → {vtf_filename}")
                    elif image_path:
                        _ms, _mf, _mfl, _mo = _eff(texture_filename)
                        animated_fps, is_normal_map = TextureService.render_image_to_vtf(
                            image_path,
                            vtf_output_path=vtf_output_path,
                            out_vtf_path=vtf_output_path / vtf_filename,
                            temp_png_path=vtf_temp_png,
                            normal_base=texture_filename,
                            size=_ms,
                            format_type=_mf,
                            flags=_mfl,
                            vtf_options=_mo,
                        )
                    
                    # Извлекаем оригинальный VMT по пути из QC (до патчинга) — в VPK он
                    # лежит по оригинальному пути. tf2_textures_vpk нужен и дальше по коду.
                    tf2_textures_vpk = TF2Paths.resolve_textures_vpk(tf2_root_dir)
                    # Оригинальный VMT берём по ИГРОВОМУ имени (c_sd_cleaver.vmt) —
                    # чтобы сохранить родной код материала (phong/прокси и т.п.).
                    # _write_main_vmt затем переставит $basetexture на texture_filename
                    # (имя материала меша).
                    vmt_file = VPKService._extract_original_vmt(
                        original_cdmaterials_path, _game_vmt_name,
                        tf2_textures_vpk, tf2_misc_vpk, ctx.decompile_dir,
                    )
                    
                    vmt_to_delete = VPKService._write_main_vmt(
                        vmt_file, vmt_path, texture_filename, patched_cdmaterials_path,
                        mode, hat_apply_game_paints, animated_fps, is_normal_map,
                    )

                    # Пер-текстурные файловые карты (detail/selfillum/phong) применяются
                    # ПОЗЖЕ — после создания VMT доп. материалов и BLU (см. ниже),
                    # чтобы карты ложились в VMT именно своего материала.

                    # ── BLU Team Texture (командная раскраска) ───────────────────────────
                    # Для оружия с одной общей текстурой (часы шпиона) BLU не создаём,
                    # даже если в BLU-слот случайно попала картинка — иначе появится
                    # лишний {texture}_blue.vtf/vmt.
                    from src.data.weapons import NO_BLU_WEAPON_KEYS as _NO_BLU
                    if weapon_key not in _NO_BLU:
                        VPKService._build_blu_team_texture(
                            blu_mode, blu_image_path, vtf_output_path, vtf_filename, vmt_path,
                            texture_filename, patched_cdmaterials_path, size, format_type, flags, vtf_options,
                        )
                    else:
                        logger.info(f"[{weapon_key}] BLU team texture пропущена (одиночная текстура)")

                    # === Создаем текстуры для дополнительных материалов модели (shell, scope и т.д.) ===
                    # Это столбцы 1+ из RED строки $texturegroup
                    # Словарь для хранения путей к VTF дополнительных материалов (нужно для BLU копий)
                    extra_materials_vtf_paths = {}
                    
                    for extra_mat_name in extra_materials:
                        logger.info(f"Создаем текстуры для дополнительного материала: {extra_mat_name}")

                        extra_vtf_filename = f"{extra_mat_name}.vtf"
                        extra_vmt_filename = f"{extra_mat_name}.vmt"
                        extra_vtf_path = vtf_output_path / extra_vtf_filename
                        extra_vmt_path = vtf_output_path / extra_vmt_filename
                        
                        # Спрашиваем пользователя — нужна ли отдельная текстура для этого материала
                        extra_image_path = extra_texture_callback(extra_mat_name, weapon_key) if extra_texture_callback else None
                        # «Использовать обычную» — берём VTF прямо из игрового VPK
                        if extra_image_path == EXTRA_TEX_USE_GAME_ORIGINAL:
                            logger.info(f"Извлекаем оригинал из игры для: {extra_mat_name}")
                            _game_vtf = VPKService._get_original_vtf_bytes(
                                extra_mat_name, original_cdmaterials_paths,
                                tf2_textures_vpk, tf2_misc_vpk
                            )
                            if _game_vtf:
                                with open(extra_vtf_path, "wb") as _f:
                                    _f.write(_game_vtf)
                                logger.info(f"VTF из игры скопирован: {extra_mat_name}.vtf")
                            else:
                                # Fallback: копируем основную текстуру
                                red_vtf_path = vtf_output_path / vtf_filename
                                if red_vtf_path.exists():
                                    copy_file_safe(red_vtf_path, extra_vtf_path)
                            extra_image_path = None  # VTF уже на месте, пропускаем if-блок ниже

                        if extra_image_path and not os.path.isfile(extra_image_path):
                            logger.warning(f"Файл не найден: {extra_image_path}")
                            extra_image_path = None

                        extra_animated_fps = None
                        if extra_image_path and os.path.isfile(extra_image_path):
                            # Пользователь предоставил отдельное изображение для этого материала
                            logger.info(f"Используем отдельное изображение для {extra_mat_name}: {extra_image_path}")

                            if custom_vtf_path or extra_image_path.lower().endswith('.vtf'):
                                # Пользователь загрузил готовый VTF (глобально или в эту
                                # карточку) — копируем как есть, без переконвертации.
                                copy_file_safe(extra_image_path, extra_vtf_path)
                            elif TextureService.is_animated_image(extra_image_path):
                                vtf_flags_extra, merged_extra = TextureService.resolve_vtf_flags_and_options(flags, vtf_options)
                                extra_animated_fps = TextureService.create_animated_vtf(
                                    extra_image_path, str(extra_vtf_path),
                                    size, format_type, vtf_flags_extra, merged_extra
                                )
                            else:
                                extra_temp_png = vtf_output_path / f"{extra_mat_name}.png"
                                VPKService._process_image(extra_image_path, extra_temp_png, size)
                                vtf_flags_extra, merged_extra = TextureService.resolve_vtf_flags_and_options(flags, vtf_options, drop_normal=True)
                                VPKService._create_vtf(str(extra_temp_png), str(vtf_output_path), format_type, vtf_flags_extra, merged_extra)
                                if extra_temp_png.exists():
                                    extra_temp_png.unlink()
                        else:
                            # Пользователь не предоставил изображение.
                            # В мод попадает ТОЛЬКО то, что пользователь явно загрузил
                            # или выбрал «использовать из игры». Всё остальное движок
                            # найдёт через другие $cdmaterials пути — не добавляем.
                            if not extra_vtf_path.exists():
                                logger.debug(f"Доп. материал пропускается (нет изображения): {extra_mat_name}")
                                continue
                        
                        extra_materials_vtf_paths[extra_mat_name] = extra_vtf_path
                        
                        # VMT для дополнительного материала
                        VPKService._write_material_vmt(extra_vmt_path, vmt_path, patched_cdmaterials_path, extra_mat_name)
                        
                        # Если пользователь загрузил свою extra-текстуру — используем её FPS.
                        # Если extra_image не было (скопирована основная VTF) — используем FPS основной.
                        # Если extra_image статична — не анимируем extra VMT вообще.
                        if extra_image_path and os.path.isfile(extra_image_path):
                            _extra_fps = extra_animated_fps
                        else:
                            _extra_fps = animated_fps
                        if _extra_fps:
                            VMTService.enable_animated_basetexture(str(extra_vmt_path), _extra_fps)
                    
                    # === Создаем текстуры для BLU команды ===
                    # BLU - это отдельная строка (row 1) в $texturegroup
                    # Для каждого материала в BLU строке спрашиваем отдельное изображение,
                    # если пользователь отказывается — копируем соответствующую RED текстуру
                    if blu_row:
                        red_row = tg_structure.get('red_row', [])
                        tex_ctx = TextureBuildContext(
                            vtf_output_path=vtf_output_path,
                            size=size,
                            format_type=format_type,
                            flags=flags,
                            vtf_options=vtf_options,
                            custom_vtf_path=custom_vtf_path,
                        )

                        for col_idx, blu_tex_name in enumerate(blu_row):
                            # Служебные материалы (sheen-оверлеи, глаза и т.п.) не
                            # включаем в мод. Пропускаем по col_idx, не удаляя из
                            # списка, чтобы сохранить выравнивание с red_row.
                            if not _is_edit(blu_tex_name):
                                continue
                            # Находим соответствующее RED имя для этого столбца
                            red_tex_name = red_row[col_idx] if col_idx < len(red_row) else None

                            if not red_tex_name:
                                # Скин-вариант (австралий, gold) имеет БОЛЬШЕ материалов, чем обычный.
                                # Например: normal { c_scattergun }, australian { c_scattergun, c_scattergun_gold }.
                                # c_scattergun_gold нет в RED-строке, но нам всё равно нужно его включить в мод.
                                # Спрашиваем пользователя и создаём текстуру (или копируем основную).
                                logger.info(
                                    f"Дополнительный материал варианта (нет RED аналога): {blu_tex_name} (col {col_idx})"
                                )
                                _variant_vtf_path = vtf_output_path / f"{blu_tex_name}.vtf"
                                _variant_vmt_path = vtf_output_path / f"{blu_tex_name}.vmt"

                                if not _variant_vtf_path.exists():
                                    _variant_img = extra_texture_callback(blu_tex_name, weapon_key) if extra_texture_callback else None
                                    if _variant_img == EXTRA_TEX_USE_GAME_ORIGINAL:
                                        logger.info(f"Извлекаем оригинал варианта из игры: {blu_tex_name}")
                                        _game_vtf = VPKService._get_original_vtf_bytes(
                                            blu_tex_name, original_cdmaterials_paths,
                                            tf2_textures_vpk, tf2_misc_vpk
                                        )
                                        if _game_vtf:
                                            with open(_variant_vtf_path, "wb") as _f:
                                                _f.write(_game_vtf)
                                        else:
                                            _main_vtf = vtf_output_path / vtf_filename
                                            if _main_vtf.exists():
                                                copy_file_safe(_main_vtf, _variant_vtf_path)
                                        _variant_img = None  # VTF на месте, пропускаем блок ниже
                                    if _variant_img and not os.path.isfile(_variant_img):
                                        _variant_img = None
                                    if _variant_img:
                                        tex_ctx.render_user_image_vtf(_variant_img, _variant_vtf_path, f"{blu_tex_name}.png")
                                        logger.info(f"Создан VTF варианта (отд. изображение): {blu_tex_name}.vtf")
                                    elif not _variant_vtf_path.exists():
                                        # Пользователь отказался или нет callback — копируем основную
                                        _main_vtf = vtf_output_path / vtf_filename
                                        if _main_vtf.exists():
                                            copy_file_safe(_main_vtf, _variant_vtf_path)
                                            logger.info(f"Создан VTF варианта (копия основной): {blu_tex_name}.vtf")
                                        else:
                                            logger.warning(f"Основной VTF не найден для варианта: {_main_vtf}")

                                if not _variant_vmt_path.exists():
                                    VPKService._write_material_vmt(_variant_vmt_path, vmt_path, patched_cdmaterials_path, blu_tex_name)
                                    if animated_fps:
                                        VMTService.enable_animated_basetexture(str(_variant_vmt_path), animated_fps)
                                continue
                            
                            # Если BLU имя совпадает с RED — shared/нейтральная текстура.
                            #
                            # Два типа:
                            #   1. СЛУЖЕБНЫЕ (eyeball, invulnfx, _invun, _zombie, sheen…) —
                            #      из единого блэклиста material_filter; пропускаем,
                            #      движок найдёт оригинал сам.
                            #   2. НАСТОЯЩИЕ СКИНОВЫЕ (sniper_lens, c_arrow и т.п.) — спрашиваем
                            #      пользователя через extra_texture_callback, как для extra_materials.
                            if blu_tex_name == red_tex_name:
                                if blu_tex_name == texture_filename:
                                    continue

                                from src.data.material_filter import is_editable_material as _is_edit_shared
                                _is_system_tex = not _is_edit_shared(blu_tex_name)

                                shared_vtf_path = vtf_output_path / f"{blu_tex_name}.vtf"
                                if not shared_vtf_path.exists():
                                    if _is_system_tex:
                                        # Системная — тихо пропускаем, движок обработает
                                        logger.debug(f"Системная shared texture пропускается: {blu_tex_name}")
                                        continue

                                    # Скиновая shared текстура — спрашиваем пользователя
                                    _shared_img = extra_texture_callback(blu_tex_name, weapon_key) if extra_texture_callback else None
                                    if _shared_img == EXTRA_TEX_USE_GAME_ORIGINAL:
                                        _game_vtf = VPKService._get_original_vtf_bytes(
                                            blu_tex_name, original_cdmaterials_paths,
                                            tf2_textures_vpk, tf2_misc_vpk, log_not_found=False
                                        )
                                        if _game_vtf:
                                            with open(shared_vtf_path, "wb") as _f:
                                                _f.write(_game_vtf)
                                            logger.info(f"Shared VTF из игры: {blu_tex_name}.vtf")
                                        else:
                                            logger.debug(f"Shared VTF не найден в игре, пропуск: {blu_tex_name}")
                                            continue
                                    elif _shared_img and str(_shared_img).lower().endswith('.vtf'):
                                        copy_file_safe(_shared_img, shared_vtf_path)
                                        logger.info(f"Shared: готовый VTF скопирован → {blu_tex_name}.vtf")
                                    elif _shared_img and os.path.isfile(_shared_img):
                                        _sh_flags, _sh_merged = TextureService.resolve_vtf_flags_and_options(flags, vtf_options, drop_normal=True)
                                        _sh_png = vtf_output_path / f"{blu_tex_name}.png"
                                        VPKService._process_image(_shared_img, _sh_png, size)
                                        VPKService._create_vtf(str(_sh_png), str(vtf_output_path), format_type, _sh_flags, _sh_merged)
                                        if _sh_png.exists():
                                            _sh_png.unlink()
                                        logger.info(f"Создан shared VTF: {blu_tex_name}.vtf")
                                    else:
                                        # Пользователь пропустил — не включаем
                                        logger.debug(f"Shared texture пропущена пользователем: {blu_tex_name}")
                                        continue

                                # VTF существует → создаём VMT если нет
                                shared_vmt_path = vtf_output_path / f"{blu_tex_name}.vmt"
                                if not shared_vmt_path.exists():
                                    VPKService._write_material_vmt(shared_vmt_path, vmt_path, patched_cdmaterials_path, blu_tex_name)
                                if animated_fps:
                                    VMTService.enable_animated_basetexture(str(shared_vmt_path), animated_fps)
                                continue
                            
                            logger.info(f"Создаем текстуры для BLU команды: {blu_tex_name} (RED: {red_tex_name})")
                            
                            blu_vtf_filename = f"{blu_tex_name}.vtf"
                            blu_vmt_filename = f"{blu_tex_name}.vmt"
                            blu_vtf_path = vtf_output_path / blu_vtf_filename
                            blu_vmt_path = vtf_output_path / blu_vmt_filename
                            
                            # Спрашиваем у пользователя отдельное изображение для BLU материала
                            _blu_mat_img = extra_texture_callback(blu_tex_name, weapon_key) if extra_texture_callback else None
                            if _blu_mat_img == EXTRA_TEX_USE_GAME_ORIGINAL:
                                _game_vtf = VPKService._get_original_vtf_bytes(
                                    blu_tex_name, original_cdmaterials_paths, tf2_textures_vpk, tf2_misc_vpk
                                )
                                if _game_vtf:
                                    with open(blu_vtf_path, "wb") as _f:
                                        _f.write(_game_vtf)
                                    logger.info(f"Извлечён VTF из игры для BLU текстуры: {blu_tex_name}.vtf")
                                else:
                                    if col_idx == 0:
                                        _red_src = vtf_output_path / f"{red_tex_name}.vtf"
                                    else:
                                        _red_src = extra_materials_vtf_paths.get(
                                            red_tex_name, vtf_output_path / f"{red_tex_name}.vtf"
                                        )
                                    if _red_src.exists():
                                        copy_file_safe(_red_src, blu_vtf_path)
                                _blu_mat_img = None
                            if _blu_mat_img and not os.path.isfile(_blu_mat_img):
                                _blu_mat_img = None

                            if _blu_mat_img and os.path.isfile(_blu_mat_img):
                                # Пользователь дал отдельное изображение для этого BLU материала
                                logger.info(f"Используем отдельное изображение для BLU {blu_tex_name}: {_blu_mat_img}")
                                tex_ctx.render_user_image_vtf(_blu_mat_img, blu_vtf_path, f"{blu_tex_name}.png")
                            elif not blu_vtf_path.exists():
                                # Пользователь не предоставил изображение для BLU —
                                # не включаем в мод, движок найдёт оригинал сам.
                                logger.debug(f"BLU текстура пропускается (нет изображения): {blu_tex_name}")
                                continue

                            # Создаем VMT для BLU (копируем RED VMT и обновляем $basetexture)
                            red_vmt_src = vtf_output_path / f"{red_tex_name}.vmt"
                            VPKService._write_material_vmt(blu_vmt_path, red_vmt_src, patched_cdmaterials_path, blu_tex_name)
                            
                            if animated_fps:
                                VMTService.enable_animated_basetexture(str(blu_vmt_path), animated_fps)
                            
                            # Normal map для BLU
                            if is_normal_map:
                                blu_normal_vtf = f"{blu_tex_name}_normal.vtf"
                                red_normal_vtf = vtf_output_path / f"{red_tex_name}_normal.vtf"
                                blu_normal_vtf_path = vtf_output_path / blu_normal_vtf
                                
                                if red_normal_vtf.exists():
                                    copy_file_safe(red_normal_vtf, blu_normal_vtf_path)
                                    logger.info(f"Скопирован normal VTF для BLU: {blu_normal_vtf}")
                                
                                blu_normal_key = f"{blu_tex_name}_normal"
                                VMTService.update_vmt_bumpmap_path(str(blu_vmt_path), patched_cdmaterials_path, blu_normal_key)
                                logger.info(f"Обновлен VMT $bumpmap для BLU: {blu_normal_key}")
                    
                    # ── Зеркальные VMT по оригинальному пути (для режимов рук) ────────────
                    # Проблема: модели оружий шпиона (Dead Ringer, Invis Watch и т.д.)
                    # ссылаются на текстуры по оригинальному пути materials/models/player/spy/,
                    # а не по пропатченному console\models\player\spy\. Из-за этого левая
                    # рука шпиона (slot 1 = spy_hands_blue) игнорирует мод.
                    # Аналогично могут быть устроены другие оружия других классов.
                    #
                    # Фикс: для режимов рук дополнительно создаём VMT-файлы по ОРИГИНАЛЬНОМУ
                    # пути из $cdmaterials (до патча). VMT указывает на те же VTF что и уже
                    # созданный мод (по console\ пути), т.е. VTF-файлы не дублируются.
                    from src.data.player_hands import HAND_MODE_KEYS as _HAND_MODE_KEYS
                    from src.data.weapons import MIRROR_VMT_WEAPON_KEYS as _MIRROR_KEYS
                    _need_mirror = (mode in _HAND_MODE_KEYS) or (weapon_key in _MIRROR_KEYS)
                    if _need_mirror and original_cdmaterials_path:
                        orig_mat_rel = "materials/" + original_cdmaterials_path.replace('\\', '/').strip().rstrip('/')
                        orig_vtf_dir = ctx.vpkroot_dir
                        for _part in orig_mat_rel.rstrip('/').split('/'):
                            orig_vtf_dir = orig_vtf_dir / _part

                        if orig_vtf_dir != vtf_output_path:
                            ensure_directory_exists(orig_vtf_dir)
                            # Для каждого VMT в console\ пути создаём зеркало по оригинальному пути.
                            # Содержимое зеркального VMT = копия console\ VMT:
                            # $basetexture в нём уже ссылается на console\ VTF — это ОК,
                            # Source Engine найдёт VTF по этому абсолютному пути в мод-VPK.
                            for _vmt_src in vtf_output_path.glob("*.vmt"):
                                _vmt_mirror = orig_vtf_dir / _vmt_src.name
                                if not _vmt_mirror.exists():
                                    copy_file_safe(_vmt_src, _vmt_mirror)
                                    logger.info(f"Зеркальный VMT по оригинальному пути: {_vmt_mirror.name}")
                        else:
                            logger.debug("Оригинальный и пропатченный пути совпадают, зеркало не нужно")

                    # ── Зеркальные VMT для all-class шапок ───────────────────────────────
                    # Проблема: у all-class шапок каждый класс имеет свою модель (%s-плейсхолдер).
                    # Инструмент компилирует модель только одного класса (первый найденный в VPK)
                    # с пропатченным $cdmaterials (console\ путь). Модели остальных восьми классов
                    # берутся из базового VPK игры и ссылаются на ОРИГИНАЛЬНЫЙ путь текстур.
                    # Из-за этого только один класс видит новую текстуру.
                    #
                    # Фикс: создаём зеркальные VMT по оригинальному пути из $cdmaterials.
                    # Зеркальные VMT ссылаются на те же VTF (по console\ пути) — дублировать их не нужно.
                    # Так все классы, использующие оригинальные модели, тоже найдут кастомную текстуру.
                    if mode == "hat" and hat_mdl_path and "%s" in hat_mdl_path and original_cdmaterials_path:
                        _hat_orig_rel = "materials/" + original_cdmaterials_path.replace('\\', '/').strip().rstrip('/')
                        _hat_orig_dir = ctx.vpkroot_dir
                        for _part in _hat_orig_rel.rstrip('/').split('/'):
                            _hat_orig_dir = _hat_orig_dir / _part

                        if _hat_orig_dir != vtf_output_path:
                            ensure_directory_exists(_hat_orig_dir)
                            for _vmt_src in vtf_output_path.glob("*.vmt"):
                                _vmt_mirror = _hat_orig_dir / _vmt_src.name
                                if not _vmt_mirror.exists():
                                    copy_file_safe(_vmt_src, _vmt_mirror)
                                    logger.info(f"Зеркальный VMT для all-class шапки: {_vmt_mirror.name}")
                        else:
                            logger.debug("Пути для шапки совпадают, зеркало не нужно")

                    if debug_mode:
                        DebugService.save_patched_stage(ctx, ctx.decompile_dir)

                    # ── Текстуры из 2D панели (c_arrow, sniper_lens и т.п.) ──────── #
                    # Материалы из SMD модели которые НЕ в QC skinfamilies →
                    # extra_texture_callback их не покрывает → добавляем здесь.
                    # Фиксированные доп. текстуры (vgui-вставки и т.п.) — пишем по
                    # их зашитому пути, не по cdmaterials. Возвращает обработанные имена.
                    _fixed_handled = VPKService._build_fixed_extra_textures(
                        weapon_key, panel_extra_textures, ctx, size,
                        format_type, flags, vtf_options,
                    )

                    # Доп. статические файлы мода (HUD .res, info.vdf) — напр. для
                    # кастомного циферблата Dead Ringer. Пишутся всегда (активируют мод).
                    VPKService._write_fixed_extra_files(weapon_key, ctx)

                    if panel_extra_textures:
                        # Собираем уже созданные имена (extra_materials + BLU)
                        _processed = set()
                        for _f in vtf_output_path.glob("*.vtf"):
                            _processed.add(_f.stem)

                        for _pet_name, _pet_img in panel_extra_textures.items():
                            if _pet_name in _fixed_handled:
                                continue   # уже записан по фиксированному пути
                            # Защита от UI-sentinel: '__single__' — главная текстура,
                            # а не имя материала. Если протёк — пропускаем, иначе
                            # в VPK появятся мусорные __single__.vmt / __single__.vtf.
                            if not _pet_name or _pet_name.startswith('__'):
                                continue
                            if _pet_name in _processed:
                                continue   # уже создан через skinfamilies
                            try:
                                _es, _ef, _efl, _eo = _eff(_pet_name)
                                if VPKService._render_extra_texture(
                                    _pet_name, _pet_img, vtf_output_path, vmt_path,
                                    patched_cdmaterials_path, _es, _ef, _efl, _eo,
                                ):
                                    logger.info(f"Panel extra texture: {_pet_name}.vtf/vmt")
                            except Exception as _pet_exc:
                                logger.warning(f"Panel extra texture ошибка '{_pet_name}': {_pet_exc}")

                    # ── Пер-текстурные файловые карты (detail/selfillum/phong/warp) ──────
                    # Теперь VMT всех материалов (главный + доп. + BLU) созданы, поэтому
                    # карты каждого материала ложатся в его собственный VMT.
                    VPKService._build_material_maps(
                        material_maps, vtf_output_path, texture_filename, vmt_path,
                        patched_cdmaterials_path, size,
                        base_image_path=image_path, is_normal_map=is_normal_map,
                        panel_extra_textures=panel_extra_textures,
                    )

                    # ── VTF/VMT вариантов стилей (skinfamilies) ─────────────────
                    # Для каждой переопределённой текстуры доп-стиля (напр.
                    # lefteye_bloody) создаём VTF + VMT рядом с базовыми. Имена
                    # совпадают с теми, что выписаны в инъектированный $texturegroup.
                    if _has_skins:
                        _variant_files = skin_build_data.get('variant_files', {})
                        for _v_name, _v_img in _variant_files.items():
                            try:
                                if VPKService._render_extra_texture(
                                    _v_name, _v_img, vtf_output_path, vmt_path,
                                    patched_cdmaterials_path, size, format_type, flags, vtf_options,
                                ):
                                    logger.info(f"[SKIN BUILD] вариант: {_v_name}.vtf/vmt")
                                else:
                                    logger.warning(f"[SKIN BUILD] нет файла варианта '{_v_name}': {_v_img}")
                            except Exception as _v_exc:
                                logger.warning(f"[SKIN BUILD] вариант '{_v_name}' — ошибка: {_v_exc}", exc_info=True)

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
                        VPKService._copy_compiled_models_to_vpkroot(ctx, qc_path)

                    # Подстраховка: для оружия без BLU удаляем любые {texture}_blue.*,
                    # если их успел создать другой путь (texturegroup/варианты).
                    from src.data.weapons import NO_BLU_WEAPON_KEYS as _NO_BLU2
                    if weapon_key in _NO_BLU2:
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
            
            # Собираем VPK файл (финальный этап - упаковываем все в один файл)
            if is_cancelled():
                return cancelled_result(ctx)
            emit_progress(80, t.get('build_packing', 'Creating VPK file...'))
            emit_sub(-1, "Packing VPK..." if language == "en" else "Упаковка VPK...")
            # Логируем все файлы в VPK root (для отладки, чтобы видеть какие файлы идут в мод)
            if ctx.vpkroot_dir.exists():
                vpkroot_files = []
                for _root, _dirs, _files in os.walk(ctx.vpkroot_dir):
                    for _f in _files:
                        rel = os.path.relpath(os.path.join(_root, _f), ctx.vpkroot_dir).replace('\\', '/')
                        vpkroot_files.append(rel)
                logger.info(f"[VPK CONTENTS] Files going into VPK ({len(vpkroot_files)} total):\n" +
                            "\n".join(f"  {f}" for f in vpkroot_files))
            vpk_path = VPKService._create_vpk_file(ctx, filename, export_folder, language)
            
            # Если использовали отредактированный VMT - удаляем его после сборки (чтобы не засорять папку)
            if vmt_to_delete:
                from src.services.edited_vmt_service import EditedVMTService
                if EditedVMTService.delete_edited_vmt(vmt_to_delete):
                    logger.info(f"Удален отредактированный VMT файл: {vmt_to_delete}")
            
            # Чистим папку с временными VMT файлами (которые доставали из игры для редактора)
            # (это мусор, который остается после работы редактора VMT)
            temp_vmt_extract_dir = DirectoryPaths.TEMP_VMT_EXTRACT_DIR
            if temp_vmt_extract_dir.exists():
                try:
                    for file_path in temp_vmt_extract_dir.iterdir():
                        try:
                            if file_path.is_file() or file_path.is_symlink():
                                file_path.unlink()
                            elif file_path.is_dir():
                                shutil.rmtree(file_path)
                        except Exception as e:
                            logger.warning(f"Не удалось удалить {file_path}: {e}", exc_info=True)
                    logger.debug("Очищена папка temp_vmt_extract")
                except Exception as e:
                    logger.warning(f"Не удалось очистить папку temp_vmt_extract: {e}", exc_info=True)

            backup_vmt_dir = Path("tools/backupVMT")
            if backup_vmt_dir.exists():
                try:
                    for file_path in backup_vmt_dir.iterdir():
                        try:
                            if file_path.is_file() or file_path.is_symlink():
                                file_path.unlink()
                            elif file_path.is_dir():
                                shutil.rmtree(file_path)
                        except Exception as e:
                            logger.warning(f"Не удалось удалить {file_path}: {e}", exc_info=True)
                    logger.debug("Очищена папка backupVMT")
                except Exception as e:
                    logger.warning(f"Не удалось очистить папку backupVMT: {e}", exc_info=True)
            
            ctx.cleanup(on_error=False, keep_on_error=False, debug_mode=debug_mode)
            
            success_message = t.get('vpk_success', 'VPK successfully created: {path}').format(path=vpk_path)
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
    def _build_special_mode_vpk(
        ctx: BuildContext,
        mode: str,
        image_path: str,
        size: Tuple[int, int],
        format_type: str,
        flags: List[str],
        vtf_options: dict = None,
        keep_temp_on_error: bool = False,
        debug_mode: bool = False,
        language: str = "en",
        custom_vtf_path: str = None
    ) -> Tuple[bool, str, Optional[str]]:
        return BuildService.build_special_mode_vpk(
            ctx,
            mode,
            image_path,
            size,
            format_type,
            flags,
            vtf_options,
            keep_temp_on_error,
            debug_mode,
            language,
            custom_vtf_path
        )
    
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
            is_ru = (language == 'ru')
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
                display = name_ru if is_ru else name_en
                mask_vtf_path = masks_dir / f"{vtf_name}.vtf"
                mask_vmt_path = masks_dir / f"{vtf_name}.vmt"

                # Спрашиваем пользователя через стандартный callback
                mask_img = extra_texture_callback(vtf_name, "spy") if extra_texture_callback else None

                if mask_img == EXTRA_TEX_USE_GAME_ORIGINAL:
                    # Берём оригинал из VPK
                    orig = VPKService._get_original_vtf_bytes(
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
                    VPKService._process_image(mask_img, tmp_png, size)
                    vtf_flags, merged = TextureService.resolve_vtf_flags_and_options(flags, vtf_options, drop_normal=True)
                    VPKService._create_vtf(str(tmp_png), str(masks_dir), format_type, vtf_flags, merged)
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
            vpk_path = VPKService._create_vpk_file(ctx, filename, export_folder, language)
            ctx.cleanup(on_error=False, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
            logger.info(f"VPK масок шпиона готов: {vpk_path}")
            return True, vpk_path

        except Exception as exc:
            logger.error(f"_build_spy_masks_vpk: {exc}", exc_info=True)
            if ctx:
                ctx.cleanup(on_error=True, keep_on_error=keep_temp_on_error, debug_mode=debug_mode)
            return False, str(exc)

    @staticmethod
    def _validate_build_params(
        image_path: str,
        mode: str,
        filename: str,
        size: Tuple[int, int],
        format_type: str,
        tf2_root_dir: str,
        t: dict = None,
        custom_vtf_path: str = None
    ) -> Optional[str]:
        return validate_build_params(
            image_path,
            mode,
            filename,
            size,
            format_type,
            tf2_root_dir,
            t,
            custom_vtf_path
        )
    
    @staticmethod
    def _get_original_vtf_bytes(
        mat_name: str,
        cdmaterials_paths,          # str | list[str] | None
        textures_vpk: Optional[str],
        misc_vpk: Optional[str],
        log_not_found: bool = True,
    ) -> Optional[bytes]:
        """
        Извлекает оригинальный VTF из игровых VPK-файлов.

        Crowbar добавляет префикс ``console\\`` ко всем $cdmaterials путям.
        В реальных VPK этого префикса нет, поэтому мы его снимаем.
        Пути вида ``console\\..\\..\\effects`` (для частиц) пропускаются.

        Args:
            mat_name:          Имя материала (без расширения).
            cdmaterials_paths: Один путь или список путей из $cdmaterials QC.
                               Crowbar-префикс ``console/`` снимается автоматически.
            textures_vpk:      Путь к tf2_textures_dir.vpk.
            misc_vpk:          Путь к tf2_misc_dir.vpk.

        Returns:
            Байты VTF или None если не найдено.
        """
        try:
            import vpk as vpklib

            mat_lower = mat_name.lower()

            # Нормализуем cdmaterials_paths в список
            if cdmaterials_paths is None:
                raw_paths: list = []
            elif isinstance(cdmaterials_paths, str):
                raw_paths = [cdmaterials_paths]
            else:
                raw_paths = list(cdmaterials_paths)

            def _normalize(raw: str) -> Optional[str]:
                """Снять console/ prefix, пропустить пути с '..'."""
                p = raw.strip("/\\").replace("\\", "/")
                # Crowbar добавляет "console/" — снимаем
                if p.lower().startswith("console/"):
                    p = p[len("console/"):]
                # Пути типа "../../effects" — не текстурные, пропускаем
                if ".." in p:
                    return None
                return p.rstrip("/")

            candidates: list = []

            # Кандидаты из QC ($cdmaterials), все строки
            seen_cdmat = set()
            for raw in raw_paths:
                cdmat = _normalize(raw)
                if cdmat and cdmat not in seen_cdmat:
                    seen_cdmat.add(cdmat)
                    candidates.append(f"materials/{cdmat}/{mat_lower}.vtf")

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
                    pak = vpklib.open(vpk_path)
                    for vtf_path in candidates:
                        try:
                            data = pak[vtf_path].read()
                            logger.debug(f"Оригинальный VTF из игры: {vtf_path}")
                            return data
                        except KeyError:
                            continue
                except Exception as _e:
                    logger.debug(f"VPK ошибка при поиске оригинала {mat_name}: {_e}")

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
            logger.warning(f"_get_original_vtf_bytes: {exc}")
            return None

    @staticmethod
    def _process_image(input_path: str, output_path: str, size: Tuple[int, int]) -> None:
        return TextureService.process_image(input_path, output_path, size)
    
    @staticmethod
    def _create_vtf(png_path: str, output_path: str, format_type: str, flags: List[str], 
                   options: dict = None) -> None:
        return TextureService.create_vtf(png_path, output_path, format_type, flags, options)
    
    @staticmethod
    def _create_vpk_file(ctx: BuildContext, filename: str, export_folder: str = "export", language: str = "en") -> str:
        return PackagingService.create_vpk_file(ctx, filename, export_folder, language)
    
    @staticmethod
    def _copy_compiled_models_to_vpkroot(ctx: BuildContext, qc_path: str) -> None:
        return ModelService.copy_compiled_models_to_vpkroot(ctx, qc_path)
    
    @staticmethod
    def _generate_uv_layout(ctx: BuildContext, weapon_key: str, image_size: Tuple[int, int], export_folder: str = "export", language: str = "en") -> None:
        return ModelService.generate_uv_layout(ctx, weapon_key, image_size, export_folder, language)
