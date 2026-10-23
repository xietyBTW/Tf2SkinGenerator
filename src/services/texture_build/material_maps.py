"""
Стадия «карты материала»: файловые и производные карты (нормаль, phong,
envmap, detail, свечение) в VMT каждого выбранного материала
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple

from src.services.texture_service import TextureService
from src.services.vmt_service import VMTService
from src.shared.file_utils import ensure_directory_exists
from src.shared.logging_config import get_logger

from . import map_settings
from . import map_textures

logger = get_logger(__name__)


def build_material_maps(
    material_maps: Optional[dict],
    vtf_output_path: Path,
    texture_filename: str,
    vmt_path: Path,
    patched_cdmaterials_path: str,
    size: Tuple[int, int],
    base_image_path: Optional[str] = None,
    is_normal_map: bool = False,
    panel_extra_textures: Optional[dict] = None,
    read_texture: Optional[Callable[[str], Optional[bytes]]] = None,
) -> None:
    """
    Генерит файловые карты материала ПЕР-ТЕКСТУРНО

    read_texture: путь текстуры из VMT -> байты VTF (мод, затем игра) - чтобы
    маска в альфе нормали ложилась на РОДНУЮ нормаль, а не на выдуманную

    material_maps: {material_name: {map_id: spec}} - карты для каждого выбранного
    материала (а не глобально на главный). Карты каждого материала пишутся в
    ЕГО VMT:
      • главный (== texture_filename) -> vmt_path, база = base_image_path;
      • прочие -> {mat}.vmt (создан extra/panel_extra), база = panel_extra_textures[mat].
    Если есть {mat}_blue.vmt - параметры дублируются туда (команда наследует).
    Ошибка одной карты не валит сборку
    """
    if not material_maps:
        return
    from src.services.part_materials import model_name
    panel_extra_textures = panel_extra_textures or {}
    for mat, maps in material_maps.items():
        if not maps:
            continue
        # Пустой ключ '' = главный материал (UI не всегда знает texture_filename).
        # Имя карточки - к имени в модели (`model_name`): у своей модели
        # «Material.001» собран как material_001, и VMT лежит под ним
        if mat == '' or model_name(mat) == model_name(texture_filename):
            real_mat = texture_filename
            mat_vmt = vmt_path
            mat_base = base_image_path
        else:
            real_mat = model_name(mat)
            mat_vmt = vtf_output_path / f"{real_mat}.vmt"
            mat_base = panel_extra_textures.get(mat)
            if not mat_vmt.exists():
                logger.warning(f"Карты материала '{mat}': VMT не найден ({mat_vmt.name}), пропуск")
                continue
        red = apply_maps_for_material(
            maps, real_mat, mat_vmt, mat_base, vtf_output_path,
            patched_cdmaterials_path, size, is_normal_map, read_texture=read_texture,
        )
        _blu_vmt = vtf_output_path / f"{real_mat}_blue.vmt"
        if _blu_vmt.exists():
            apply_maps_for_material(
                maps, real_mat, _blu_vmt, mat_base, vtf_output_path,
                patched_cdmaterials_path, size, is_normal_map, params_only=True,
                read_texture=read_texture, red=red,
            )


@dataclass
class _MapJob:
    """Карты одного материала: общее для всех шагов (что, куда, из чего)"""
    maps: dict
    mat: str
    vmt_path: Path
    base_image_path: Optional[str]
    out_dir: Path
    cdmaterials: str
    size: Tuple[int, int]
    is_normal_map: bool
    params_only: bool
    read_texture: Optional[Callable[[str], Optional[bytes]]]
    red: Optional[dict]

    def doc(self):
        """VMT материала как он есть сейчас (шаги его дописывают)"""
        from src.services import vmt_parse
        try:
            return vmt_parse.parse(Path(self.vmt_path).read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            return vmt_parse.parse("")

    def has_base(self) -> bool:
        return bool(self.base_image_path) and os.path.isfile(self.base_image_path)

    def blue_follows(self, orig_bump) -> bool:
        """Синий следует за нормалью красного, только если у красного маска
        вышла и нормаль у них была одна"""
        from src.services.mod_textures import texture_key
        red = self.red
        return bool(red and red.get("mask")) and (
            orig_bump is None
            or texture_key(orig_bump) == texture_key(red.get("bump") or ""))


def apply_maps_for_material(
    material_maps: dict,
    mat: str,
    vmt_path: Path,
    base_image_path: Optional[str],
    vtf_output_path: Path,
    patched_cdmaterials_path: str,
    size: Tuple[int, int],
    is_normal_map: bool = False,
    params_only: bool = False,
    read_texture: Optional[Callable[[str], Optional[bytes]]] = None,
    red: Optional[dict] = None,
) -> dict:
    """
    Применяет набор карт к ОДНОМУ материалу: генерит VTF (имена {mat}{suffix})
    и вписывает параметры в его VMT. params_only=True - только параметры (VTF
    уже создан, напр. при дублировании в BLU-VMT)

    Источник карты: "image" (файл) либо "derive" (из базовой текстуры material'а).
    Для derive-phong доп. создаётся карта нормалей + $envmap («Авто-блеск»)

    Возвращает {"mask": маска легла в альфу {mat}_normal, "bump": $bumpmap
    материала ДО сборки}. Синий (`params_only`) получает это как `red`:
    следует за нормалью красного, только если у красного маска вышла и
    нормаль у них была одна (своя синяя нормаль мода не подменяется)
    """
    from src.data.material_maps import MATERIAL_MAPS, MAP_ORDER

    job = _MapJob(material_maps, mat, vmt_path, base_image_path, vtf_output_path,
                  patched_cdmaterials_path, size, is_normal_map, params_only,
                  read_texture, red)
    doc = job.doc()
    orig_bump = doc.path("$bumpmap")
    # Каким материал был до карт: под это написан его $envmaptint (_envmap_tint)
    was_phong = doc.flag("$phong")
    result = {"mask": False, "bump": orig_bump, "exp": False,
              "exp_tex": doc.path("$phongexponenttexture")}

    envmask_combined = _envmask_prepass(job, orig_bump, result)
    for map_id in MAP_ORDER:
        spec = material_maps.get(map_id)
        # Карты мода (оставить/снять) - забота сборки мода, не генератора
        if not spec or spec.get("mod") or spec.get("off"):
            continue
        # envmapmask уже разрешён через альфу нормали - отдельную карту не пишем
        if map_id == "envmapmask" and envmask_combined:
            continue
        cfg = MATERIAL_MAPS[map_id]
        if cfg.get("vmt_only"):
            _vmt_only_map(job, map_id, spec, cfg)
        else:
            _texture_map(job, map_id, spec, cfg, envmask_combined, orig_bump, result)

    map_settings.phong_channels(
        material_maps, mat, vmt_path, vtf_output_path, patched_cdmaterials_path, size,
        base_image_path, read_texture, params_only, red, result)
    map_settings.apply_settings(
        {k: v for k, v in material_maps.items() if not (v.get("mod") or v.get("off"))},
        mat, vmt_path, vtf_output_path, patched_cdmaterials_path, size,
        base_image_path, is_normal_map, params_only, was_phong)
    return result


def _envmask_prepass(job: _MapJob, orig_bump, result: dict) -> bool:
    """
    Pre-pass: маска отражения при нормали или phong

    Вики Valve ($envmapmask): отдельная маска не работает с $bumpmap и
    с $phong вовсе. В TF2 Valve ни разу не ставит её вместе с $bumpmap -
    маска лежит в альфе нормали ($normalmapalphaenvmapmask, 684
    материала). Значит, у оружия с родной нормалью или phong маска уходит
    в альфу нормали ВСЕГДА, а не только когда нормаль строим мы:
    $envmapmask там не работает. При phong та же альфа - маска
    блеска (у движка она одна на оба эффекта)

    Returns:
        True - маска разрешена через альфу нормали (отдельную карту не писать)
    """
    maps, mat = job.maps, job.mat
    spec = maps.get("envmapmask")
    if not spec or spec.get("mod") or spec.get("off"):
        return False
    doc = job.doc()
    uses_normal = (job.is_normal_map
                   or (job.out_dir / f"{mat}_normal.vtf").exists()
                   or doc.get("$bumpmap") is not None
                   or doc.flag("$phong")
                   or bool((maps.get("rimlight") or {}).get("enabled"))
                   or bool(maps.get("phongexp"))
                   # «Сильнее по краю» и карты блика включат phong,
                   # контур свечения - нормаль, с ними отдельная маска
                   # не читается, значит маска сразу уходит в альфу нормали
                   or float(spec.get("env_fresnel") or 0) > 0
                   or bool((maps.get("phongcolor") or {}).get("enabled"))
                   or bool(maps.get("phongwarp"))
                   or (maps.get("selfillum") or {}).get("glow_edge") == "on")
    if not uses_normal:
        return False
    env_params = {"$envmap": "env_cubemap", "$normalmapalphaenvmapmask": "1"}
    if job.params_only:
        # BLU-дубль: нормаль с маской уже создана для RED. Не вышла
        # у красного или у синего своя нормаль - синий не трогаем
        # (и нерабочий $envmapmask ему тоже не пишем)
        if job.blue_follows(orig_bump):
            map_textures.mask_params(job.vmt_path, job.cdmaterials, mat, env_params, job.out_dir)
        return True
    combined = False
    mask_png = map_textures.mask_png(spec, "envmapmask", job.base_image_path, job.out_dir,
                                     f"{mat}_envmask_src", job.size)
    if mask_png and map_textures.normal_with_mask(
            mask_png, mat, job.vmt_path, job.out_dir, job.cdmaterials,
            job.size, job.base_image_path, job.read_texture):
        combined = map_textures.mask_params(job.vmt_path, job.cdmaterials, mat,
                                            env_params, job.out_dir)
    if mask_png and mask_png.exists():
        mask_png.unlink()
    result["mask"] = combined
    if not combined:
        logger.warning(f"[{mat}] маску отражения не удалось положить в "
                       f"альфу нормали: отдельный $envmapmask с нормалью "
                       f"или phong игра не читает")
    return combined


def _map_params(cfg: dict, spec: dict) -> dict:
    """Параметры карты: её VMT-параметры + числовые переопределения из UI"""
    extra = dict(cfg["extra_vmt"])
    for k, v in spec.items():
        if isinstance(k, str) and k.startswith("$"):
            extra[k] = str(v)
    return extra


def _with_defaults(job: _MapJob, cfg: dict, extra: dict) -> dict:
    """Параметры карты + `vmt_defaults` тех, чего в VMT ещё нет (своё
    у материала важнее: у оружия TF2 $phongfresnelranges подобран)"""
    doc = job.doc()
    missing = {k: v for k, v in cfg.get("vmt_defaults", {}).items()
               if doc.get(k) is None}
    return {**missing, **extra}


def _vmt_only_map(job: _MapJob, map_id: str, spec: dict, cfg: dict) -> None:
    """
    Параметрическая карта без своей текстуры (rim light): только пишем
    VMT-параметры (+ числовые переопределения из UI). Работает и при
    params_only (дублирование в BLU-VMT) - там тоже нужны те же параметры
    """
    if not spec.get("enabled"):
        return
    extra = _with_defaults(job, cfg, _map_params(cfg, spec))
    # Rim/phong не считаются без $bumpmap. Если в VMT его ещё нет -
    # генерим нормаль из базы (существующую НЕ трогаем). params_only
    # (дубль в BLU-VMT) только пишет параметры, VTF уже создан
    if not job.params_only and cfg.get("derive_auto_normal") and job.has_base():
        try:
            vmt_txt = Path(job.vmt_path).read_text(encoding="utf-8", errors="ignore").lower()
        except OSError:
            vmt_txt = ""
        # Живая строка, а не комментарий: у 240 материалов игры
        # $bumpmap есть только в «//»
        if not VMTService.has_live_param(vmt_txt, "$bumpmap"):
            map_textures.ensure_derived_normal(
                job.base_image_path, job.out_dir, job.mat, job.vmt_path,
                job.cdmaterials, job.size, job.is_normal_map,
            )
    VMTService.add_material_map_params(str(job.vmt_path), job.cdmaterials, None, None, extra)
    logger.info(f"Карта '{map_id}' [{job.mat}] → VMT-параметры (+нормаль при необходимости)")


def _texture_map(job: _MapJob, map_id: str, spec: dict, cfg: dict,
                 envmask_combined: bool, orig_bump, result: dict) -> None:
    """Карта со своей текстурой {mat}{suffix}: VTF из файла или из базы,
    затем её параметры в VMT"""
    mat = job.mat
    map_key = f"{mat}{cfg['suffix']}"
    derive = bool(spec.get("derive")) and bool(cfg.get("derive_kind"))
    image = spec.get("image")

    if not derive and (not image or not os.path.isfile(image)):
        if not job.params_only:
            logger.warning(f"Карта '{map_id}' [{mat}]: нет файла и не derive, пропуск")
        return
    if derive and not job.has_base():
        if not job.params_only:
            logger.warning(f"Карта '{map_id}' [{mat}]: derive невозможен - нет базы, пропуск")
        return
    if not job.params_only and not _render_map_vtf(job, map_id, spec, cfg, map_key, derive, image):
        return

    extra = _map_params(cfg, spec)
    if derive:
        _derive_params(job, spec, cfg, extra, envmask_combined, orig_bump, result)
    if map_id == "detail" and not _detail_params(job, map_key, extra):
        return
    if map_id == "phongexp":
        # Размер блика - в красном канале нашей карты. $phongexponent
        # > 0 его перекрывает (skin_dx9_helper.cpp) - а он стоит у 8379
        # из 8511 phong-материалов TF2. Без снятия карта не меняла блик
        if job.params_only or (job.out_dir / f"{map_key}.vtf").exists():
            if VMTService.remove_param(str(job.vmt_path), "$phongexponent"):
                logger.info(f"[{mat}] $phongexponent снят: размер блика - из Phong-карты")
            result["exp"] = not job.params_only

    VMTService.add_material_map_params(
        str(job.vmt_path), job.cdmaterials, map_key, cfg["path_param"],
        _with_defaults(job, cfg, extra)
    )
    logger.info(f"Карта '{map_id}' [{mat}] → {map_key}.vtf ({'derive' if derive else 'file'})")


def _render_map_vtf(job: _MapJob, map_id, spec, cfg, map_key, derive, image) -> bool:
    """VTF карты. False - не вышло (предупреждение уже в логе)"""
    try:
        ensure_directory_exists(job.out_dir)
        temp_png = job.out_dir / f"{map_key}.png"
        opts = dict(cfg.get("options", {}))
        # Карта может требовать фиксированный размер (warp-градиенты:
        # lightwarp = 256×1, phongwarp = 256×256). Иначе - глобальный
        map_size = tuple(cfg.get("size") or job.size)
        # Формат может зависеть от параметра (detail в режиме 2
        # накладывается по своей альфе - DXT1 её теряет)
        fmt = cfg["format"]
        for param, by in cfg.get("format_by", {}).items():
            value = str(spec.get(param, cfg["extra_vmt"].get(param, "")))
            fmt = by.get(value, fmt)
        if derive:
            threshold = spec.get("threshold")
            threshold = int(threshold) if threshold not in (None, "") else None
            TextureService.derive_effect_map(
                job.base_image_path, str(temp_png), cfg["derive_kind"], map_size,
                threshold=threshold,
            )
        else:
            TextureService.process_image(image, str(temp_png), map_size)
        TextureService.create_vtf(str(temp_png), str(job.out_dir), fmt, list(cfg["flags"]), opts)
        if temp_png.exists():
            temp_png.unlink()
        return True
    except Exception as e:
        logger.warning(f"Не удалось создать VTF карты '{map_id}' [{job.mat}]: {e}", exc_info=True)
        return False


def _derive_params(job: _MapJob, spec, cfg, extra: dict, envmask_combined: bool,
                   orig_bump, result: dict) -> None:
    """Карта из базы: её доп. параметры и «Авто-блеск» (маска в альфе нормали)"""
    mat = job.mat
    # Окружение предмета (золото, студийный блик) не подменяем
    has_env = job.doc().get("$envmap") is not None
    extra.update({k: v for k, v in cfg.get("derive_extra_vmt", {}).items()
                  if not (k == "$envmap" and has_env)})
    if not cfg.get("derive_auto_normal") or envmask_combined:
        return
    if not job.params_only:
        # Авто-блеск: ГДЕ блестит - альфа нормали (вики Valve:
        # маска phong по умолчанию в альфе $bumpmap), а не альфа
        # exponent-текстуры (там маска rim light): в exponent «Порог» ни на
        # что бы не влиял
        gloss = map_textures.mask_png(spec, "envmapmask", job.base_image_path, job.out_dir,
                                      f"{mat}_gloss_src", job.size)
        if gloss and map_textures.normal_with_mask(
                gloss, mat, job.vmt_path, job.out_dir, job.cdmaterials,
                job.size, job.base_image_path, job.read_texture):
            result["mask"] = map_textures.mask_params(
                job.vmt_path, job.cdmaterials, mat, {}, job.out_dir)
        if gloss and gloss.exists():
            gloss.unlink()
    elif job.blue_follows(orig_bump):
        # Синий: та же нормаль с маской, что у красного
        map_textures.mask_params(job.vmt_path, job.cdmaterials, mat, {}, job.out_dir)


def _detail_params(job: _MapJob, map_key: str, extra: dict) -> bool:
    """detail: снять огонь с $detail и выбрать режим. False - карты нет"""
    mat = job.mat
    # Огонь снимаем, только когда своя detail-карта и правда есть
    if not (job.params_only or (job.out_dir / f"{map_key}.vtf").exists()):
        return False
    if VMTService.release_detail(str(job.vmt_path)):
        logger.warning(f"[{mat}] $detail был занят эффектом горения (BurnLevel): "
                       f"прокси огня сняты, на предмете огня видно не будет")
    # Режим 5 (свечение) на VertexLitGeneric с нормалью рисуется
    # только при $phong (вики Valve, $detailblendmode) - без него
    # берём 1: то же сложение, но с освещением
    doc = job.doc()
    if (str(extra.get("$detailblendmode")) == "5" and doc.get("$bumpmap") is not None
            and not doc.flag("$phong")):
        extra["$detailblendmode"] = "1"
        logger.warning(f"[{mat}] detail-свечение без $phong не рисуется, взят режим 1")
    return True
