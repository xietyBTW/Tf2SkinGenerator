"""
Построение текстур/материалов VPK-сборки (вынесено из VPKService).

Замкнутая подсистема: главная RED-текстура, BLU-строка, доп./служебные и
изолированные (плечи) материалы, вторичные текстуры, material-maps,
envmask/normal-производные, фиксированные extra-текстуры и запись их VMT,
плюс извлечение оригинальных VTF/VMT из игровых VPK.
Извлечено extract-class из ``VPKService`` — методы статические, внутренние
вызовы переиспользуют этот же класс, примитивы process_image/create_vtf
идут напрямую в ``TextureService`` (обёртки ``VPKService._process_image`` /
``_create_vtf`` остаются на VPKService для его собственных вызовов и тестов).
"""

import hashlib
import os
import shutil
from pathlib import Path
from typing import List, Optional, Tuple

from src.services import qc_skin_parser
from src.services.texture_service import TextureService
from src.services.vmt_service import VMTService
from src.shared.file_utils import ensure_directory_exists, copy_file_safe
from src.shared.logging_config import get_logger
from src.services.tf2_vpk_extract_service import TF2VPKExtractService
from src.shared.constants import EXTRA_TEX_USE_GAME_ORIGINAL

logger = get_logger(__name__)


class VpkTextureBuilder:
    """Построение текстур/материалов VPK-сборки (см. модуль)."""

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

        fps = None
        if str(img).lower().endswith('.vtf'):
            copy_file_safe(img, out_vtf)
        else:
            # Доп. материалы не бывают normal-map → снимаем 'normal'; единый рендер
            # (анимация / обычная картинка) через TextureService.render_image_to_vtf.
            opts = dict(vtf_options) if vtf_options else {}
            opts.pop("normal", None)
            fps, _ = TextureService.render_image_to_vtf(
                img,
                vtf_output_path=vtf_output_path,
                out_vtf_path=out_vtf,
                temp_png_path=vtf_output_path / f"{name}.png",
                normal_base="",
                size=size,
                format_type=format_type,
                flags=flags,
                vtf_options=opts,
            )

        if not out_vmt.exists():
            # Пер-материальный отредактированный VMT (если пользователь правил его
            # для этого материала) — копируем его, затем чиним путь $basetexture
            # под наш VTF/пропатченный cdmaterials. Иначе — обычная генерация.
            from src.services.edited_vmt_service import EditedVMTService
            _edited = EditedVMTService.get_edited_vmt(name)
            if _edited and os.path.exists(_edited):
                copy_file_safe(_edited, out_vmt)
                VMTService.update_vmt_basetexture_path(
                    str(out_vmt), patched_cdmaterials_path, name)
                logger.info(f"Доп.материал '{name}': использован отредактированный VMT")
            else:
                VpkTextureBuilder._write_material_vmt(out_vmt, vmt_path, patched_cdmaterials_path, name)
        if fps:
            VMTService.enable_animated_basetexture(str(out_vmt), fps)
        return True

    @staticmethod
    def _build_blu_team_texture(
        blu_mode: str,
        blu_image_path: Optional[str],
        vtf_filename: str,
        texture_filename: str,
        slots,
        tex,
        blu_texture_filename: Optional[str] = None,
    ) -> None:
        """
        Создаёт BLU-командную текстуру (и VMT) рядом с RED.

        blu_mode == 'same'        → копия RED VTF;
        иначе при blu_image_path  → отдельное изображение → VTF.
        BLU VMT — копия RED VMT с обновлённым $basetexture. Ошибки не критичны
        (мод соберётся и без BLU-варианта).

        blu_texture_filename — РЕАЛЬНОЕ имя синего материала из $texturegroup
        (та же колонка, что у главной). Нужно, т.к. имя может уже нести суффикс
        _red (w_grenade_red → w_grenade_blue), и «{texture}_blue» дало бы
        неверное w_grenade_red_blue. По умолчанию — «{texture}_blue».

        Примечание: BLU намеренно использует только UI-опции (tex.vtf_options),
        не подмешивая опции из флагов — поведение сохранено как в оригинале.
        """
        if not blu_mode or blu_mode in ('none', ''):
            return
        try:
            blu_name = blu_texture_filename or f"{texture_filename}_blue"
            red_vtf_path = slots.vtf_output_path / vtf_filename
            blu_vtf_name = f"{blu_name}.vtf"
            blu_vtf_path = slots.vtf_output_path / blu_vtf_name
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
                blu_png_tmp = slots.vtf_output_path / f"{blu_name}.png"
                TextureService.process_image(blu_image_path, str(blu_png_tmp), tex.size)
                blu_vtf_flags, _ = TextureService.parse_vtf_flags_and_options(tex.flags or [])
                blu_opts = dict(tex.vtf_options or {})
                blu_opts.pop('normal', None)   # BLU — не normal map
                TextureService.create_vtf(
                    str(blu_png_tmp), str(slots.vtf_output_path), tex.format_type, blu_vtf_flags, blu_opts
                )
                if blu_png_tmp.exists():
                    blu_png_tmp.unlink()
                blu_created = blu_vtf_path.exists()
                if blu_created:
                    logger.info(f"BLU текстура создана: {blu_vtf_name}")

            # BLU VMT — копия RED с обновлённым $basetexture
            if blu_created and slots.vmt_path.exists():
                blu_vmt_path = slots.vtf_output_path / f"{blu_name}.vmt"
                shutil.copy2(slots.vmt_path, blu_vmt_path)
                VMTService.update_vmt_basetexture_path(
                    str(blu_vmt_path), slots.patched_cdmaterials_path, blu_name
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
            VpkTextureBuilder._apply_maps_for_material(
                maps, real_mat, mat_vmt, mat_base, vtf_output_path,
                patched_cdmaterials_path, size, is_normal_map,
            )
            _blu_vmt = vtf_output_path / f"{real_mat}_blue.vmt"
            if _blu_vmt.exists():
                VpkTextureBuilder._apply_maps_for_material(
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

        # ── Pre-pass: разрешение конфликта $envmapmask + $bumpmap ──────────────
        # Source игнорирует отдельный $envmapmask при наличии $bumpmap. Если на
        # материале вместе с отражением активен эффект с нормалью (rim/phong) и
        # нормаль генерим МЫ — печём маску отражения в альфу нормали и используем
        # $normalmapalphaenvmapmask. Тогда обе фичи работают одновременно.
        envmask_combined = False
        envmask_spec = material_maps.get("envmapmask")
        if envmask_spec and base_image_path and os.path.isfile(base_image_path):
            rim_on = bool((material_maps.get("rimlight") or {}).get("enabled"))
            phong_on = bool(material_maps.get("phongexp"))
            try:
                _vmt_txt0 = Path(vmt_path).read_text(encoding="utf-8", errors="ignore").lower()
            except OSError:
                _vmt_txt0 = ""
            real_normal = (is_normal_map
                           or (vtf_output_path / f"{mat}_normal.vtf").exists()
                           or "$bumpmap" in _vmt_txt0)
            needs_bump = real_normal or rim_on or phong_on
            if needs_bump and not real_normal:
                # Нормаль генерим мы → можем запечь маску в её альфу.
                if params_only:
                    # BLU-дубль: VTF уже создан для RED, пишем только параметры.
                    VMTService.add_material_map_params(
                        str(vmt_path), patched_cdmaterials_path, None, None,
                        {"$envmap": "env_cubemap", "$normalmapalphaenvmapmask": "1"})
                    envmask_combined = True
                else:
                    mask_png = vtf_output_path / f"{mat}_envmask_src.png"
                    ok_mask = False
                    if envmask_spec.get("derive"):
                        thr = envmask_spec.get("threshold")
                        thr = int(thr) if thr not in (None, "") else None
                        TextureService.derive_effect_map(
                            base_image_path, str(mask_png), "envmapmask", size, threshold=thr)
                        ok_mask = mask_png.exists()
                    elif envmask_spec.get("image") and os.path.isfile(envmask_spec["image"]):
                        TextureService.process_image(envmask_spec["image"], str(mask_png), size)
                        ok_mask = mask_png.exists()
                    if ok_mask:
                        envmask_combined = VpkTextureBuilder._ensure_normal_with_envmask(
                            base_image_path, mask_png, vtf_output_path, mat,
                            vmt_path, patched_cdmaterials_path, size)
                        if mask_png.exists():
                            mask_png.unlink()
            elif real_normal:
                logger.warning(
                    f"[{mat}] envmapmask + готовая нормаль: отдельный $envmapmask "
                    f"может игнорироваться движком (есть $bumpmap)")

        for map_id in MAP_ORDER:
            spec = material_maps.get(map_id)
            if not spec:
                continue
            # envmapmask уже разрешён через альфу нормали — отдельную карту не пишем.
            if map_id == "envmapmask" and envmask_combined:
                continue
            cfg = MATERIAL_MAPS[map_id]

            # Параметрическая карта без своей текстуры (rim light): только пишем
            # VMT-параметры (+ числовые переопределения из UI). Работает и при
            # params_only (дублирование в BLU-VMT) — там тоже нужны те же параметры.
            if cfg.get("vmt_only"):
                if not spec.get("enabled"):
                    continue
                extra = dict(cfg["extra_vmt"])
                for k, v in spec.items():
                    if isinstance(k, str) and k.startswith("$"):
                        extra[k] = str(v)
                # Rim/phong не считаются без $bumpmap. Если в VMT его ещё нет —
                # генерим нормаль из базы (существующую НЕ трогаем). params_only
                # (дубль в BLU-VMT) только пишет параметры, VTF уже создан.
                if not params_only and cfg.get("derive_auto_normal") \
                        and base_image_path and os.path.isfile(base_image_path):
                    try:
                        _vmt_txt = Path(vmt_path).read_text(encoding="utf-8", errors="ignore").lower()
                    except OSError:
                        _vmt_txt = ""
                    if "$bumpmap" not in _vmt_txt:
                        VpkTextureBuilder._ensure_derived_normal(
                            base_image_path, vtf_output_path, mat, vmt_path,
                            patched_cdmaterials_path, size, is_normal_map,
                        )
                VMTService.add_material_map_params(
                    str(vmt_path), patched_cdmaterials_path, None, None, extra
                )
                logger.info(f"Карта '{map_id}' [{mat}] → VMT-параметры (+нормаль при необходимости)")
                continue

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
                    # Карта может требовать фиксированный размер (warp-градиенты:
                    # lightwarp = 256×1, phongwarp = 256×256). Иначе — глобальный.
                    _map_size = tuple(cfg.get("size") or size)
                    if derive:
                        threshold = spec.get("threshold")
                        threshold = int(threshold) if threshold not in (None, "") else None
                        TextureService.derive_effect_map(
                            base_image_path, str(temp_png), cfg["derive_kind"], _map_size,
                            threshold=threshold,
                        )
                        TextureService.create_vtf(str(temp_png), str(vtf_output_path),
                                               cfg["format"], list(cfg["flags"]), _map_opts)
                    else:
                        TextureService.process_image(image, str(temp_png), _map_size)
                        TextureService.create_vtf(str(temp_png), str(vtf_output_path),
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
                    VpkTextureBuilder._ensure_derived_normal(
                        base_image_path, vtf_output_path, mat, vmt_path,
                        patched_cdmaterials_path, size, is_normal_map,
                    )

            VMTService.add_material_map_params(
                str(vmt_path), patched_cdmaterials_path, map_key, cfg["path_param"], extra
            )
            logger.info(f"Карта '{map_id}' [{mat}] → {map_key}.vtf ({'derive' if derive else 'file'})")

    @staticmethod
    def _ensure_normal_with_envmask(
        base_image_path: str,
        mask_png: Path,
        vtf_output_path: Path,
        mat: str,
        vmt_path: Path,
        patched_cdmaterials_path: str,
        size: Tuple[int, int],
    ) -> bool:
        """
        Создаёт {mat}_normal.vtf, у которого RGB — нормаль из базы, а АЛЬФА —
        маска отражения. Прописывает $bumpmap + $envmap + $normalmapalphaenvmapmask.

        Так отражение по маске и эффекты с нормалью (rim/phong) уживаются: движок
        берёт маску отражения из альфы нормали, а не из отдельного $envmapmask
        (который при наличии $bumpmap игнорируется).
        """
        try:
            norm_png = vtf_output_path / f"{mat}_normal.png"
            TextureService.make_normal_with_alpha(
                base_image_path, str(mask_png), str(norm_png), size)
            # DXT5 — сохраняет альфу (маску). Не -normal: RGB уже нормаль.
            TextureService.create_vtf(str(norm_png), str(vtf_output_path), "DXT5", [], {})
            if norm_png.exists():
                norm_png.unlink()
            if not (vtf_output_path / f"{mat}_normal.vtf").exists():
                return False
            VMTService.update_vmt_bumpmap_path(
                str(vmt_path), patched_cdmaterials_path, f"{mat}_normal")
            VMTService.add_material_map_params(
                str(vmt_path), patched_cdmaterials_path, None, None,
                {"$envmap": "env_cubemap", "$normalmapalphaenvmapmask": "1"})
            logger.info(f"[{mat}] отражение запечено в альфу нормали ($normalmapalphaenvmapmask)")
            return True
        except Exception as e:
            logger.warning(f"[{mat}] не удалось запечь маску отражения в нормаль: {e}", exc_info=True)
            return False

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
            TextureService.process_image(base_image_path, str(norm_png), size)
            TextureService.create_vtf(str(norm_png), str(vtf_output_path), "DXT5", [], {"normal": True})
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
        try:
            with open(path, "rb") as f:
                return hashlib.file_digest(f, "md5").hexdigest()
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

                _img_hash = VpkTextureBuilder._file_content_hash(img)
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
                    TextureService.process_image(img, str(tmp_png), size)
                    TextureService.create_vtf(str(tmp_png), str(target_dir), format_type, _flags, _merged)
                    if tmp_png.exists():
                        tmp_png.unlink()
                    if _img_hash:
                        _vtf_cache[_img_hash] = (dest_vtf, _ex_fps)

                # 2) VMT рядом с VTF ($basetexture → реальный путь)
                VpkTextureBuilder._write_fixed_extra_vmt(ex, base_path, ctx, misc_vpk, textures_vpk)

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
    def _read_vmt_basetexture(vmt_path: str) -> Optional[str]:
        """Читает $basetexture из VMT (путь к VTF без расширения, как в файле).

        Нужно для «use game original»: у головы/варианта имя VTF ≠ имя материала
        (demoman_head_red → $basetexture "models/player/demo/demoman_head"), поэтому
        реальный VTF резолвим именно по $basetexture, а не по имени материала."""
        try:
            import re as _re_bt
            with open(vmt_path, encoding='utf-8', errors='ignore') as _f:
                _txt = _f.read()
            m = _re_bt.search(r'"?\$basetexture"?\s+"([^"]+)"', _txt, _re_bt.IGNORECASE)
            return m.group(1).strip() if m else None
        except Exception:
            return None

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
            if animated_fps:
                # Бамп многокадровый (гифка + normal) — тот же fps, что у базы.
                VMTService.enable_animated_bumpmap(str(vmt_path), animated_fps)
        return vmt_to_delete

    @staticmethod
    def _build_extra_material_textures(
        extra_materials, weapon_key, ctx, slots, tex,
        extra_texture_callback, animated_fps,
    ) -> dict:
        """
        Создаёт VTF+VMT для доп. материалов модели (столбцы 1+ RED-строки
        $texturegroup: shell, scope и т.п.). На каждый материал спрашивает
        текстуру через callback, либо берёт оригинал из игры, либо пропускает.

        Returns:
            {material_name: vtf_path} — для последующего копирования в BLU.
        """
        extra_materials_vtf_paths = {}

        for extra_mat_name in extra_materials:
            logger.info(f"Создаем текстуры для дополнительного материала: {extra_mat_name}")

            extra_vtf_path = slots.vtf(extra_mat_name)
            extra_vmt_path = slots.vmt(extra_mat_name)

            # Спрашиваем пользователя — нужна ли отдельная текстура для этого материала
            extra_image_path = extra_texture_callback(extra_mat_name, weapon_key) if extra_texture_callback else None
            # «Использовать из игры» — копируем ОРИГИНАЛЬНЫЙ VMT материала.
            # Его $basetexture абсолютный (напр. голова demoman_head_red →
            # "models/player/demo/demoman_head") → берёт верную игровую
            # текстуру. Поиск VTF по ИМЕНИ МАТЕРИАЛА ненадёжен: у головы/
            # варианта имя VTF ≠ имя материала, и старый fallback подставлял
            # текстуру ТЕЛА (главную) — отсюда «голова с текстурой тела».
            if extra_image_path == EXTRA_TEX_USE_GAME_ORIGINAL:
                logger.info(f"Извлекаем оригинал из игры для: {extra_mat_name}")
                # Родной VMT материала и резолв его $basetexture в реальный
                # VTF. Имя VTF часто ≠ имя материала (demoman_head_red →
                # $basetexture "models/player/demo/demoman_head"), поэтому
                # поиск по имени материала не находил → старый код подставлял
                # текстуру ТЕЛА. Пишем самодостаточно (VTF + VMT) — тогда и
                # BLU-цикл скопирует RED-вариант.
                _orig_vmt = None
                for _cd in (slots.original_cdmaterials_paths or []):
                    _orig_vmt = VpkTextureBuilder._extract_original_vmt(
                        _cd, extra_mat_name, slots.tf2_textures_vpk,
                        slots.tf2_misc_vpk, ctx.decompile_dir,
                    )
                    if _orig_vmt:
                        break
                _game_vtf = None
                if _orig_vmt and os.path.exists(_orig_vmt):
                    _bt = VpkTextureBuilder._read_vmt_basetexture(_orig_vmt)
                    if _bt:
                        _btp = _bt.replace('\\', '/').strip().strip('/')
                        _bt_dir, _bt_name = os.path.split(_btp)
                        _game_vtf = VpkTextureBuilder._get_original_vtf_bytes(
                            _bt_name,
                            ([_bt_dir] if _bt_dir else [])
                            + list(slots.original_cdmaterials_paths or []),
                            slots.tf2_textures_vpk, slots.tf2_misc_vpk,
                            log_not_found=False,
                        )
                if _game_vtf is None:
                    _game_vtf = VpkTextureBuilder._get_original_vtf_bytes(
                        extra_mat_name, slots.original_cdmaterials_paths,
                        slots.tf2_textures_vpk, slots.tf2_misc_vpk,
                        log_not_found=False,
                    )
                if _game_vtf:
                    with open(extra_vtf_path, "wb") as _f:
                        _f.write(_game_vtf)
                    # VMT: родной (сохраняет шейдер/детейл) с $basetexture,
                    # перенаправленным на наш console-VTF.
                    _base = (Path(_orig_vmt) if (_orig_vmt and os.path.exists(_orig_vmt))
                             else slots.vmt_path)
                    VpkTextureBuilder._write_material_vmt(
                        extra_vmt_path, _base, slots.patched_cdmaterials_path,
                        extra_mat_name)
                    extra_materials_vtf_paths[extra_mat_name] = extra_vtf_path
                    logger.info(f"Оригинал из игры: {extra_mat_name} (VTF+VMT)")
                    continue
                if _orig_vmt and os.path.exists(_orig_vmt):
                    # Текстуру не нашли (глаза/зомби — абсолютные shared
                    # пути): копируем VMT как есть, ссылки сами найдут.
                    copy_file_safe(_orig_vmt, extra_vmt_path)
                    logger.info(f"Оригинал из игры (VMT абс.): {extra_mat_name}")
                    continue
                # Совсем ничего — НЕ подменяем текстурой тела.
                extra_image_path = None

            if extra_image_path and not os.path.isfile(extra_image_path):
                logger.warning(f"Файл не найден: {extra_image_path}")
                extra_image_path = None

            extra_animated_fps = None
            if extra_image_path and os.path.isfile(extra_image_path):
                # Пользователь предоставил отдельное изображение для этого материала
                logger.info(f"Используем отдельное изображение для {extra_mat_name}: {extra_image_path}")

                if tex.custom_vtf_path or extra_image_path.lower().endswith('.vtf'):
                    # Пользователь загрузил готовый VTF (глобально или в эту
                    # карточку) — копируем как есть, без переконвертации.
                    copy_file_safe(extra_image_path, extra_vtf_path)
                elif TextureService.is_animated_image(extra_image_path):
                    # drop_normal — как и в статичной ветке ниже: доп. материалы
                    # normal map не получают (иначе бамп уехал бы в базовую текстуру).
                    vtf_flags_extra, merged_extra = TextureService.resolve_vtf_flags_and_options(
                        tex.flags, tex.vtf_options, drop_normal=True)
                    extra_animated_fps = TextureService.create_animated_vtf(
                        extra_image_path, str(extra_vtf_path),
                        tex.size, tex.format_type, vtf_flags_extra, merged_extra
                    )
                else:
                    extra_temp_png = slots.vtf_output_path / f"{extra_mat_name}.png"
                    TextureService.process_image(extra_image_path, extra_temp_png, tex.size)
                    vtf_flags_extra, merged_extra = TextureService.resolve_vtf_flags_and_options(
                        tex.flags, tex.vtf_options, drop_normal=True)
                    TextureService.create_vtf(
                        str(extra_temp_png), str(slots.vtf_output_path),
                        tex.format_type, vtf_flags_extra, merged_extra)
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
            VpkTextureBuilder._write_material_vmt(
                extra_vmt_path, slots.vmt_path, slots.patched_cdmaterials_path,
                extra_mat_name)

            # Если пользователь загрузил свою extra-текстуру — используем её FPS.
            # Если extra_image не было (скопирована основная VTF) — используем FPS основной.
            # Если extra_image статична — не анимируем extra VMT вообще.
            if extra_image_path and os.path.isfile(extra_image_path):
                _extra_fps = extra_animated_fps
            else:
                _extra_fps = animated_fps
            if _extra_fps:
                VMTService.enable_animated_basetexture(str(extra_vmt_path), _extra_fps)
        return extra_materials_vtf_paths

    @staticmethod
    def _write_blacklisted_materials(
        blacklisted_extra, panel_extra_textures, ctx, slots,
    ) -> None:
        """
        Пишет ОРИГИНАЛЬНЫЙ VMT (и VTF при наличии) для служебных/ЧС материалов
        (глаза/убер/зомби и т.п.). Из-за console-cdmaterials модель ищет их VMT
        по новому пути — без него материал стал бы фиолетовым. Текстурные ссылки
        у таких VMT абсолютные, поэтому отдельный VTF чаще не нужен.
        """
        _pet_keys = set((panel_extra_textures or {}).keys())
        for _bl_mat in blacklisted_extra:
            # Пользователь заменил служебную текстуру через «Прочее» —
            # её запишет блок panel_extra_textures ниже (его правка важнее).
            if _bl_mat in _pet_keys:
                continue
            _bl_vmt = slots.vmt(_bl_mat)
            if _bl_vmt.exists():
                continue
            try:
                _src_vmt = None
                for _cd in (slots.original_cdmaterials_paths or []):
                    _src_vmt = VpkTextureBuilder._extract_original_vmt(
                        _cd, _bl_mat, slots.tf2_textures_vpk,
                        slots.tf2_misc_vpk, ctx.decompile_dir,
                    )
                    if _src_vmt:
                        break
                _bl_orig = VpkTextureBuilder._get_original_vtf_bytes(
                    _bl_mat, slots.original_cdmaterials_paths,
                    slots.tf2_textures_vpk, slots.tf2_misc_vpk,
                )
                if not _src_vmt and not _bl_orig:
                    continue   # ни VMT, ни VTF — движковый эффект, пропуск
                if _src_vmt and os.path.exists(_src_vmt):
                    copy_file_safe(_src_vmt, _bl_vmt)
                else:
                    # Нет родного VMT — производный от главного (как раньше).
                    VpkTextureBuilder._write_material_vmt(
                        _bl_vmt, slots.vmt_path, slots.patched_cdmaterials_path,
                        _bl_mat)
                if _bl_orig:
                    with open(slots.vtf(_bl_mat), "wb") as _f:
                        _f.write(_bl_orig)
                logger.info(f"Служебный материал записан оригиналом: {_bl_mat}")
            except Exception as _e:
                logger.warning(f"Не удалось записать служебный материал {_bl_mat}: {_e}")

    @staticmethod
    def _write_shoulder_iso_materials(shoulder_iso, ctx, slots, tex) -> None:
        """
        Пишет VTF+VMT для изолированных материалов плеч/тела вьюмодели (vm_<orig>)
        под главным console-путём. Источник каждого: пользовательская текстура
        (разрешена при детекте) либо оригинал тела из игры (чтобы плечи не стали
        фиолетовыми). Список готовит _apply_shoulder_isolation.
        """
        for _new_name, _orig_name, _sh_src in shoulder_iso:
            _sh_vtf = slots.vtf(_new_name)
            _sh_vmt = slots.vmt(_new_name)
            # Источник уже разрешён при детекте (карточка/image_path/BLU);
            # без источника — берём оригинал из игры (без лишних диалогов).
            try:
                if _sh_src and os.path.isfile(_sh_src):
                    if str(_sh_src).lower().endswith('.vtf'):
                        copy_file_safe(_sh_src, _sh_vtf)
                    else:
                        _sh_png = slots.vtf_output_path / f"{_new_name}.png"
                        TextureService.process_image(_sh_src, _sh_png, tex.size)
                        _vf, _vo = TextureService.resolve_vtf_flags_and_options(tex.flags, tex.vtf_options, drop_normal=True)
                        TextureService.create_vtf(str(_sh_png), str(slots.vtf_output_path), tex.format_type, _vf, _vo)
                        if _sh_png.exists():
                            _sh_png.unlink()
                else:
                    # По умолчанию — оригинальная текстура тела из игры
                    # (по ОРИГИНАЛЬНОМУ имени), чтобы плечи не стали фиолетовыми.
                    _orig_vtf = VpkTextureBuilder._get_original_vtf_bytes(
                        _orig_name, slots.original_cdmaterials_paths,
                        slots.tf2_textures_vpk, slots.tf2_misc_vpk
                    )
                    if _orig_vtf:
                        with open(_sh_vtf, "wb") as _f:
                            _f.write(_orig_vtf)
                    else:
                        ctx.warn(
                            f"Не найдена оригинальная текстура плеч '{_orig_name}' — "
                            f"плечи вьюмодели могут быть фиолетовыми."
                        )
                        continue
                VpkTextureBuilder._write_material_vmt(
                    _sh_vmt, slots.vmt_path, slots.patched_cdmaterials_path, _new_name)
                logger.info(f"[SHOULDER ISO] записан материал плеч: {_new_name}")
            except Exception as _e:
                logger.error(f"[SHOULDER ISO] ошибка записи {_new_name}: {_e}", exc_info=True)

    @staticmethod
    def _build_blu_row_textures(
        blu_row, tg_structure, texture_filename, vtf_filename, ctx, slots, tex,
        extra_texture_callback, weapon_key, animated_fps, is_normal_map,
        extra_materials_vtf_paths,
    ) -> None:
        """
        Создаёт VTF+VMT для BLU-строки $texturegroup (row 1). На каждый столбец:
        спрашивает отдельное изображение, копирует соответствующую RED-текстуру,
        тянет оригинал из игры или пропускает (служебные/нейтральные shared,
        скин-варианты без RED-аналога). Выравнивание по col_idx с red_row.
        """
        from src.data.material_filter import is_editable_material as _is_edit
        if not blu_row:
            return
        red_row = tg_structure.get('red_row', [])

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
                _variant_vtf_path = slots.vtf(blu_tex_name)
                _variant_vmt_path = slots.vmt(blu_tex_name)

                if not _variant_vtf_path.exists():
                    _variant_img = extra_texture_callback(blu_tex_name, weapon_key) if extra_texture_callback else None
                    if _variant_img == EXTRA_TEX_USE_GAME_ORIGINAL:
                        logger.info(f"Извлекаем оригинал варианта из игры: {blu_tex_name}")
                        _game_vtf = VpkTextureBuilder._get_original_vtf_bytes(
                            blu_tex_name, slots.original_cdmaterials_paths,
                            slots.tf2_textures_vpk, slots.tf2_misc_vpk
                        )
                        if _game_vtf:
                            with open(_variant_vtf_path, "wb") as _f:
                                _f.write(_game_vtf)
                        else:
                            _main_vtf = slots.vtf_output_path / vtf_filename
                            if _main_vtf.exists():
                                copy_file_safe(_main_vtf, _variant_vtf_path)
                        _variant_img = None  # VTF на месте, пропускаем блок ниже
                    if _variant_img and not os.path.isfile(_variant_img):
                        _variant_img = None
                    if _variant_img:
                        tex.render_user_image_vtf(_variant_img, _variant_vtf_path, f"{blu_tex_name}.png")
                        logger.info(f"Создан VTF варианта (отд. изображение): {blu_tex_name}.vtf")
                    elif not _variant_vtf_path.exists():
                        # Пользователь отказался или нет callback — копируем основную
                        _main_vtf = slots.vtf_output_path / vtf_filename
                        if _main_vtf.exists():
                            copy_file_safe(_main_vtf, _variant_vtf_path)
                            logger.info(f"Создан VTF варианта (копия основной): {blu_tex_name}.vtf")
                        else:
                            logger.warning(f"Основной VTF не найден для варианта: {_main_vtf}")

                if not _variant_vmt_path.exists():
                    VpkTextureBuilder._write_material_vmt(_variant_vmt_path, slots.vmt_path, slots.patched_cdmaterials_path, blu_tex_name)
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
            if qc_skin_parser.is_shared_column(red_tex_name, blu_tex_name):
                if blu_tex_name.lower() == (texture_filename or "").lower():
                    continue

                from src.data.material_filter import is_editable_material as _is_edit_shared
                _is_system_tex = not _is_edit_shared(blu_tex_name)

                shared_vtf_path = slots.vtf(blu_tex_name)
                if not shared_vtf_path.exists():
                    if _is_system_tex:
                        # Системная — тихо пропускаем, движок обработает
                        logger.debug(f"Системная shared texture пропускается: {blu_tex_name}")
                        continue

                    # Скиновая shared текстура — спрашиваем пользователя
                    _shared_img = extra_texture_callback(blu_tex_name, weapon_key) if extra_texture_callback else None
                    if _shared_img == EXTRA_TEX_USE_GAME_ORIGINAL:
                        _game_vtf = VpkTextureBuilder._get_original_vtf_bytes(
                            blu_tex_name, slots.original_cdmaterials_paths,
                            slots.tf2_textures_vpk, slots.tf2_misc_vpk, log_not_found=False
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
                        _sh_flags, _sh_merged = TextureService.resolve_vtf_flags_and_options(tex.flags, tex.vtf_options, drop_normal=True)
                        _sh_png = slots.vtf_output_path / f"{blu_tex_name}.png"
                        TextureService.process_image(_shared_img, _sh_png, tex.size)
                        TextureService.create_vtf(str(_sh_png), str(slots.vtf_output_path), tex.format_type, _sh_flags, _sh_merged)
                        if _sh_png.exists():
                            _sh_png.unlink()
                        logger.info(f"Создан shared VTF: {blu_tex_name}.vtf")
                    else:
                        # Пользователь пропустил — не включаем
                        logger.debug(f"Shared texture пропущена пользователем: {blu_tex_name}")
                        continue

                # VTF существует → создаём VMT если нет
                shared_vmt_path = slots.vmt(blu_tex_name)
                if not shared_vmt_path.exists():
                    VpkTextureBuilder._write_material_vmt(shared_vmt_path, slots.vmt_path, slots.patched_cdmaterials_path, blu_tex_name)
                if animated_fps:
                    VMTService.enable_animated_basetexture(str(shared_vmt_path), animated_fps)
                continue

            logger.info(f"Создаем текстуры для BLU команды: {blu_tex_name} (RED: {red_tex_name})")

            blu_vtf_filename = f"{blu_tex_name}.vtf"
            blu_vmt_filename = f"{blu_tex_name}.vmt"
            blu_vtf_path = slots.vtf_output_path / blu_vtf_filename
            blu_vmt_path = slots.vtf_output_path / blu_vmt_filename

            # Спрашиваем у пользователя отдельное изображение для BLU материала
            _blu_mat_img = extra_texture_callback(blu_tex_name, weapon_key) if extra_texture_callback else None
            if _blu_mat_img == EXTRA_TEX_USE_GAME_ORIGINAL:
                _game_vtf = VpkTextureBuilder._get_original_vtf_bytes(
                    blu_tex_name, slots.original_cdmaterials_paths, slots.tf2_textures_vpk, slots.tf2_misc_vpk
                )
                if _game_vtf:
                    with open(blu_vtf_path, "wb") as _f:
                        _f.write(_game_vtf)
                    logger.info(f"Извлечён VTF из игры для BLU текстуры: {blu_tex_name}.vtf")
                else:
                    if col_idx == 0:
                        _red_src = slots.vtf(red_tex_name)
                    else:
                        _red_src = extra_materials_vtf_paths.get(
                            red_tex_name, slots.vtf(red_tex_name)
                        )
                    if _red_src.exists():
                        copy_file_safe(_red_src, blu_vtf_path)
                _blu_mat_img = None
            if _blu_mat_img and not os.path.isfile(_blu_mat_img):
                _blu_mat_img = None

            if _blu_mat_img and os.path.isfile(_blu_mat_img):
                # Пользователь дал отдельное изображение для этого BLU материала
                logger.info(f"Используем отдельное изображение для BLU {blu_tex_name}: {_blu_mat_img}")
                tex.render_user_image_vtf(_blu_mat_img, blu_vtf_path, f"{blu_tex_name}.png")
            elif not blu_vtf_path.exists():
                # Пользователь не предоставил изображение для BLU —
                # не включаем в мод, движок найдёт оригинал сам.
                logger.debug(f"BLU текстура пропускается (нет изображения): {blu_tex_name}")
                continue

            # Создаем VMT для BLU (копируем RED VMT и обновляем $basetexture)
            red_vmt_src = slots.vmt(red_tex_name)
            VpkTextureBuilder._write_material_vmt(blu_vmt_path, red_vmt_src, slots.patched_cdmaterials_path, blu_tex_name)

            if animated_fps:
                VMTService.enable_animated_basetexture(str(blu_vmt_path), animated_fps)

            # Normal map для BLU
            if is_normal_map:
                blu_normal_vtf = f"{blu_tex_name}_normal.vtf"
                red_normal_vtf = slots.vtf(f"{red_tex_name}_normal")
                blu_normal_vtf_path = slots.vtf_output_path / blu_normal_vtf

                if red_normal_vtf.exists():
                    copy_file_safe(red_normal_vtf, blu_normal_vtf_path)
                    logger.info(f"Скопирован normal VTF для BLU: {blu_normal_vtf}")

                blu_normal_key = f"{blu_tex_name}_normal"
                VMTService.update_vmt_bumpmap_path(str(blu_vmt_path), slots.patched_cdmaterials_path, blu_normal_key)
                logger.info(f"Обновлен VMT $bumpmap для BLU: {blu_normal_key}")

    @staticmethod
    def _build_main_material(
        image_path, texture_filename, vtf_filename, vtf_temp_png,
        original_cdmaterials_path, _game_vmt_name, mode, hat_apply_game_paints,
        ctx, slots, tex, extra_texture_callback, weapon_key, _eff,
    ):
        """
        Главная текстура материала: резолв RED (пользователь / «из игры»), создание
        главного VTF (готовый custom / .vtf из карточки / рендер из картинки) и запись
        главного VMT (родной игровой код с $basetexture, перенаправленным на материал).
        ``_eff`` — замыкание эффективных пер-текстурных настроек.

        Returns:
            (image_path, animated_fps, is_normal_map, vmt_to_delete).
        """
        is_normal_map = False
        animated_fps = None
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
                _orig_red = VpkTextureBuilder._get_original_vtf_bytes(
                    texture_filename, slots.original_cdmaterials_paths,
                    slots.tf2_textures_vpk, slots.tf2_misc_vpk
                )
                ensure_directory_exists(slots.vtf_output_path)
                vtf_file_path = slots.vtf_output_path / vtf_filename
                if _orig_red:
                    with open(vtf_file_path, "wb") as _f:
                        _f.write(_orig_red)
                    logger.info(f"Оригинальная RED VTF из игры: {vtf_filename}")
                else:
                    ctx.warn(
                        f"Не найдена игровая текстура '{texture_filename}' — "
                        f"в игре материал может быть фиолетовым. Загрузите свою "
                        f"текстуру в главный слот."
                    )
                image_path = None  # VTF уже на месте, не передаём дальше

        if tex.custom_vtf_path:
            # Если юзер сам сделал VTF - просто копируем его, не генерируем из картинки
            vtf_file_path = slots.vtf_output_path / vtf_filename
            ensure_directory_exists(slots.vtf_output_path)
            copy_file_safe(tex.custom_vtf_path, vtf_file_path)
            logger.info(f"Использован пользовательский VTF файл: {tex.custom_vtf_path} -> {vtf_file_path}")
        elif image_path and str(image_path).lower().endswith('.vtf'):
            # В карточку главного материала загрузили готовый VTF —
            # копируем как есть, без PIL-конвертации (иначе «cannot identify image»).
            ensure_directory_exists(slots.vtf_output_path)
            copy_file_safe(image_path, slots.vtf_output_path / vtf_filename)
            logger.info(f"Главная текстура: готовый VTF скопирован → {vtf_filename}")
        elif image_path:
            _ms, _mf, _mfl, _mo = _eff(texture_filename)
            animated_fps, is_normal_map = TextureService.render_image_to_vtf(
                image_path,
                vtf_output_path=slots.vtf_output_path,
                out_vtf_path=slots.vtf_output_path / vtf_filename,
                temp_png_path=vtf_temp_png,
                normal_base=texture_filename,
                size=_ms,
                format_type=_mf,
                flags=_mfl,
                vtf_options=_mo,
            )

        # Извлекаем оригинальный VMT по пути из QC (до патчинга) — в VPK он
        # лежит по оригинальному пути (slots.tf2_textures_vpk резолвлен выше).
        # Оригинальный VMT берём по ИГРОВОМУ имени (c_sd_cleaver.vmt) —
        # чтобы сохранить родной код материала (phong/прокси и т.п.).
        # _write_main_vmt затем переставит $basetexture на texture_filename
        # (имя материала меша).
        vmt_file = VpkTextureBuilder._extract_original_vmt(
            original_cdmaterials_path, _game_vmt_name,
            slots.tf2_textures_vpk, slots.tf2_misc_vpk, ctx.decompile_dir,
        )

        vmt_to_delete = VpkTextureBuilder._write_main_vmt(
            vmt_file, slots.vmt_path, texture_filename, slots.patched_cdmaterials_path,
            mode, hat_apply_game_paints, animated_fps, is_normal_map,
        )
        return image_path, animated_fps, is_normal_map, vmt_to_delete

    @staticmethod
    def _maybe_build_blu_team_texture(
        weapon_key, blu_row, blu_is_team, blu_mode, blu_image_path,
        vtf_filename, texture_filename, slots, tex, red_row=None,
    ) -> None:
        """
        Создаёт {texture}_blue (командную раскраску) ТОЛЬКО если у предмета есть
        настоящая команда (blu_is_team) и он не одиночно-текстурный. У вариант-онли
        оружия (обычный+австралий) команды нет — иначе появился бы лишний c_xxx_blue.

        Синюю пару главной берём из ЕЁ столбца: главной не обязательно нулевой
        (у Quick-Fix первый столбец — общее стекло, корпус второй), и blu_row[0]
        дал бы имя чужого материала.
        """
        from src.data.weapons import NO_BLU_WEAPON_KEYS as _NO_BLU
        # Создаём {texture}_blue ТОЛЬКО если у предмета есть настоящая
        # команда (blu_is_team). У вариант-онли оружия (скаттерган:
        # обычный+австралий) команды нет — иначе появляется лишний
        # c_xxx_blue, который движок даже не использует.
        _main_col = next(
            (i for i, name in enumerate(red_row or [])
             if qc_skin_parser.is_shared_column(name, texture_filename)), 0)
        _blu_col0 = blu_row[_main_col] if len(blu_row or []) > _main_col else None
        if weapon_key in _NO_BLU:
            logger.info(f"[{weapon_key}] BLU team texture пропущена (одиночная текстура)")
        elif not blu_is_team:
            logger.info(f"[{weapon_key}] BLU team texture пропущена (нет командной строки в $texturegroup)")
        elif _blu_col0 and qc_skin_parser.is_shared_column(_blu_col0, texture_filename):
            # Команда есть, но меняется НЕ главный материал (Quick-Fix: стекло
            # общее, синеет корпус). Синее имя тогда совпадает с красным, и
            # запись «синей главной» затёрла бы RED-текстуру этим же файлом.
            # Командные столбцы пишет _build_blu_row_textures — поколоночно.
            logger.info(
                f"[{weapon_key}] BLU главной текстуры не нужен: '{texture_filename}' "
                f"одинаков в обеих командах, синеют другие материалы"
            )
        else:
            # Реальное имя синего материала — из столбца главной (может быть
            # w_grenade_blue при w_grenade_red), иначе дефолт «{texture}_blue».
            VpkTextureBuilder._build_blu_team_texture(
                blu_mode, blu_image_path, vtf_filename, texture_filename,
                slots, tex, blu_texture_filename=_blu_col0,
            )

    @staticmethod
    def _run_extra_render_jobs(
        jobs, vtf_output_path, vmt_path, patched_cdmaterials_path, log_prefix,
    ) -> None:
        """Параллельно рендерит независимые доп. текстуры (panel-extra / варианты стилей).

        jobs: список ``(name, img, size, format_type, flags, vtf_options)``. Каждая
        задача пишет свои ``{name}.vtf/.vmt`` — без shared-файлов, без чтения игрового
        VPK и без UI-callback, поэтому безопасна в пуле потоков. VTFCmd — внешний
        CPU-bound процесс, так что параллелизм реально ускоряет многоматериальные и
        многостилевые сборки. Результаты логируются; функция ничего не возвращает.
        """
        if not jobs:
            return
        import concurrent.futures as _cf

        def _one(job):
            name, img, _size, _fmt, _flags, _opts = job
            try:
                ok = VpkTextureBuilder._render_extra_texture(
                    name, img, vtf_output_path, vmt_path,
                    patched_cdmaterials_path, _size, _fmt, _flags, _opts,
                )
                return name, ok, None
            except Exception as exc:
                return name, False, exc

        max_workers = min(len(jobs), (os.cpu_count() or 4))
        with _cf.ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="vtf") as ex:
            results = list(ex.map(_one, jobs))

        for name, ok, err in results:
            if err is not None:
                logger.warning(f"{log_prefix} '{name}' — ошибка: {err}", exc_info=False)
            elif ok:
                logger.info(f"{log_prefix}: {name}.vtf/vmt")
            else:
                logger.warning(f"{log_prefix} нет файла '{name}'")

    @staticmethod
    def _build_secondary_textures(
        weapon_key, panel_extra_textures, ctx, slots, tex,
        material_maps, texture_filename, image_path, is_normal_map,
        has_skins, skin_build_data, _eff,
    ) -> None:
        """
        Вторичные текстуры после главной+BLU: фиксированные доп. текстуры/файлы,
        текстуры из 2D-панели (материалы SMD вне skinfamilies), пер-текстурные
        файловые карты (detail/selfillum/phong) и VTF/VMT вариантов стилей. Порядок
        важен: карты ложатся в VMT после того, как все VMT материалов созданы.
        """
        _fixed_handled = VpkTextureBuilder._build_fixed_extra_textures(
            weapon_key, panel_extra_textures, ctx, tex.size,
            tex.format_type, tex.flags, tex.vtf_options,
        )

        # Доп. статические файлы мода (HUD .res, info.vdf) — напр. для
        # кастомного циферблата Dead Ringer. Пишутся всегда (активируют мод).
        VpkTextureBuilder._write_fixed_extra_files(weapon_key, ctx)

        if panel_extra_textures:
            # Собираем уже созданные имена (extra_materials + BLU)
            _processed = {_f.stem for _f in slots.vtf_output_path.glob("*.vtf")}

            # Каждый panel-extra независим (своё имя → свои файлы, без callback и
            # без чтения игрового VPK) → рендерим параллельно. Скип-логику и
            # пер-текстурные настройки (_eff) считаем серийно при сборе задач.
            _pet_jobs = []
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
                _es, _ef, _efl, _eo = _eff(_pet_name)
                _pet_jobs.append((_pet_name, _pet_img, _es, _ef, _efl, _eo))

            VpkTextureBuilder._run_extra_render_jobs(
                _pet_jobs, slots.vtf_output_path, slots.vmt_path, slots.patched_cdmaterials_path,
                "Panel extra texture",
            )

        # ── Пер-текстурные файловые карты (detail/selfillum/phong/warp) ──────
        # Теперь VMT всех материалов (главный + доп. + BLU) созданы, поэтому
        # карты каждого материала ложатся в его собственный VMT.
        VpkTextureBuilder._build_material_maps(
            material_maps, slots.vtf_output_path, texture_filename, slots.vmt_path,
            slots.patched_cdmaterials_path, tex.size,
            base_image_path=image_path, is_normal_map=is_normal_map,
            panel_extra_textures=panel_extra_textures,
        )

        # ── VTF/VMT вариантов стилей (skinfamilies) ─────────────────
        # Для каждой переопределённой текстуры доп-стиля (напр.
        # lefteye_bloody) создаём VTF + VMT рядом с базовыми. Имена
        # совпадают с теми, что выписаны в инъектированный $texturegroup.
        if has_skins:
            # Варианты стилей независимы между собой → тоже параллельно.
            _variant_files = skin_build_data.get('variant_files', {})
            _var_jobs = [
                (_v_name, _v_img, tex.size, tex.format_type, tex.flags, tex.vtf_options)
                for _v_name, _v_img in _variant_files.items()
            ]
            VpkTextureBuilder._run_extra_render_jobs(
                _var_jobs, slots.vtf_output_path, slots.vmt_path, slots.patched_cdmaterials_path,
                "[SKIN BUILD] вариант",
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
            from src.services.tf2_vpk_extract_service import _open_vpk_cached

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

