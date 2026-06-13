"""
Параметры одной сборки VPK, собранные в один объект.

Раньше ~28 значений тащились отдельными аргументами через main_window →
BuildWorker → build_with_progress (и дублировались в build_kwargs). Теперь это
один dataclass: добавить поле — поправить одно место, а не четыре сигнатуры.

Колбэки (progress/cancel/запрос текстуры/модели) сюда НЕ входят — это runtime-
функции UI-потока, их передают отдельно.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


@dataclass
class BuildRequest:
    image_path: Optional[str] = None
    mode: str = ""
    filename: str = ""
    size: Tuple[int, int] = (512, 512)
    format_type: str = "DXT1"
    flags: Optional[list] = None
    vtf_options: Optional[Dict[str, Any]] = None
    tf2_root_dir: str = ""
    export_folder: str = "export"
    keep_temp_on_error: bool = False
    debug_mode: bool = False
    replace_model_enabled: bool = False
    replace_model_path: Optional[str] = None
    model_ready_path: Optional[str] = None
    draw_uv_layout: bool = False
    language: str = "en"
    custom_vtf_path: Optional[str] = None
    blu_mode: str = "none"
    blu_image_path: Optional[str] = None
    custom_vpk_source_path: Optional[str] = None
    hat_mdl_path: Optional[str] = None
    hat_apply_game_paints: bool = True
    hat_class_models: Optional[Dict[str, str]] = None
    panel_extra_textures: Optional[Dict[str, Any]] = None
    material_maps: Optional[Dict[str, Any]] = None
    material_settings: Optional[Dict[str, Any]] = None
    skin_build_data: Optional[Dict[str, Any]] = None
    replace_keep_materials: bool = False
    custom_qc_text: Optional[str] = None
