"""
Построение текстур/материалов VPK-сборки (вынесено из VPKService).

Замкнутая подсистема: рендер вторичных/BLU-текстур, material-maps,
envmask/normal-производные, фиксированные extra-текстуры и запись их VMT.
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

from src.services.texture_service import TextureService
from src.services.vmt_service import VMTService
from src.shared.file_utils import ensure_directory_exists, copy_file_safe
from src.shared.logging_config import get_logger

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
        vtf_output_path: Path,
        vtf_filename: str,
        vmt_path: Path,
        texture_filename: str,
        patched_cdmaterials_path: str,
        size: Tuple[int, int],
        format_type: str,
        flags: List[str],
        vtf_options: dict,
        blu_texture_filename: Optional[str] = None,
    ) -> None:
        """
        Создаёт BLU-командную текстуру (и VMT) рядом с RED.

        blu_mode == 'same'        → копия RED VTF;
        иначе при blu_image_path  → отдельное изображение → VTF.
        BLU VMT — копия RED VMT с обновлённым $basetexture. Ошибки не критичны
        (мод соберётся и без BLU-варианта).

        blu_texture_filename — РЕАЛЬНОЕ имя синего материала из $texturegroup
        (blu_row[0]). Нужно, т.к. col0 может уже нести суффикс _red
        (w_grenade_red → w_grenade_blue), и «{texture}_blue» дало бы неверное
        w_grenade_red_blue. По умолчанию — старое поведение «{texture}_blue».

        Примечание: BLU намеренно использует только UI-опции (vtf_options),
        не подмешивая опции из флагов — поведение сохранено как в оригинале.
        """
        if not blu_mode or blu_mode in ('none', ''):
            return
        try:
            blu_name = blu_texture_filename or f"{texture_filename}_blue"
            red_vtf_path = vtf_output_path / vtf_filename
            blu_vtf_name = f"{blu_name}.vtf"
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
                blu_png_tmp = vtf_output_path / f"{blu_name}.png"
                TextureService.process_image(blu_image_path, str(blu_png_tmp), size)
                blu_vtf_flags, _ = TextureService.parse_vtf_flags_and_options(flags or [])
                blu_opts = dict(vtf_options or {})
                blu_opts.pop('normal', None)   # BLU — не normal map
                TextureService.create_vtf(
                    str(blu_png_tmp), str(vtf_output_path), format_type, blu_vtf_flags, blu_opts
                )
                if blu_png_tmp.exists():
                    blu_png_tmp.unlink()
                blu_created = blu_vtf_path.exists()
                if blu_created:
                    logger.info(f"BLU текстура создана: {blu_vtf_name}")

            # BLU VMT — копия RED с обновлённым $basetexture
            if blu_created and vmt_path.exists():
                blu_vmt_path = vtf_output_path / f"{blu_name}.vmt"
                shutil.copy2(vmt_path, blu_vmt_path)
                VMTService.update_vmt_basetexture_path(
                    str(blu_vmt_path), patched_cdmaterials_path, blu_name
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
