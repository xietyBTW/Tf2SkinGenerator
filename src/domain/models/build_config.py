"""
Модель конфигурации сборки
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Optional, Dict, Any


@dataclass
class BuildConfig:
    """Конфигурация для сборки VPK"""
    
    # Обязательные параметры
    image_path: Optional[str] = None
    mode: str = ""
    filename: str = ""
    size: Tuple[int, int] = (512, 512)
    format_type: str = "DXT1"
    
    # Опциональные параметры
    flags: List[str] = field(default_factory=list)
    vtf_options: Dict[str, Any] = field(default_factory=dict)
    tf2_root_dir: str = ""
    export_folder: str = "export"
    keep_temp_on_error: bool = False
    debug_mode: bool = False
    replace_model_enabled: bool = False
    draw_uv_layout: bool = False
    language: str = "en"
    custom_vtf_path: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразует конфигурацию в словарь"""
        return {
            'image_path': self.image_path,
            'mode': self.mode,
            'filename': self.filename,
            'size': self.size,
            'format_type': self.format_type,
            'flags': self.flags,
            'vtf_options': self.vtf_options,
            'tf2_root_dir': self.tf2_root_dir,
            'export_folder': self.export_folder,
            'keep_temp_on_error': self.keep_temp_on_error,
            'debug_mode': self.debug_mode,
            'replace_model_enabled': self.replace_model_enabled,
            'draw_uv_layout': self.draw_uv_layout,
            'language': self.language,
            'custom_vtf_path': self.custom_vtf_path
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BuildConfig':
        """Создает конфигурацию из словаря"""
        return cls(**data)

