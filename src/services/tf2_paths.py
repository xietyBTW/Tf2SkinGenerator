"""
Утилиты для работы с путями TF2
"""

import os
from typing import Tuple, Optional


class TF2Paths:
    """Класс для разрешения путей TF2"""
    
    CROWBAR_PATH = "tools/crowbar/CrowbarCommandLineDecomp.exe"
    
    @staticmethod
    def resolve(tf2_root_dir: str) -> Tuple[str, str, str]:
        """
        Разрешает пути к необходимым файлам TF2
        
        Args:
            tf2_root_dir: Корневая директория TF2 (steamapps/common/Team Fortress 2)
            
        Returns:
            Tuple[studiomdl_exe, tf2_misc_dir_vpk, tf_dir]
            
        Raises:
            FileNotFoundError: Если какой-то файл не найден
        """
        if not os.path.exists(tf2_root_dir):
            raise FileNotFoundError(f"TF2 root directory not found: {tf2_root_dir}")
        
        # Путь к studiomdl.exe
        studiomdl_exe = os.path.join(tf2_root_dir, "bin", "studiomdl.exe")
        if not os.path.exists(studiomdl_exe):
            raise FileNotFoundError(
                f"studiomdl.exe not found at: {studiomdl_exe}\n"
                f"Expected path: <tf2_root_dir>\\bin\\studiomdl.exe"
            )
        
        # Путь к tf2_misc_dir.vpk
        tf_dir = os.path.join(tf2_root_dir, "tf")
        tf2_misc_dir_vpk = os.path.join(tf_dir, "tf2_misc_dir.vpk")
        if not os.path.exists(tf2_misc_dir_vpk):
            raise FileNotFoundError(
                f"tf2_misc_dir.vpk not found at: {tf2_misc_dir_vpk}\n"
                f"Expected path: <tf2_root_dir>\\tf\\tf2_misc_dir.vpk"
            )
        
        # Путь к tf2_textures_dir.vpk (для извлечения VMT файлов)
        tf2_textures_dir_vpk = os.path.join(tf_dir, "tf2_textures_dir.vpk")
        # Проверяем наличие, но не выбрасываем ошибку если не найден (может быть в другом месте)
        
        return studiomdl_exe, tf2_misc_dir_vpk, tf_dir
    
    @staticmethod
    def resolve_textures_vpk(tf2_root_dir: str) -> Optional[str]:
        """
        Разрешает путь к tf2_textures_dir.vpk для извлечения VMT файлов
        
        Args:
            tf2_root_dir: Корневая директория TF2
            
        Returns:
            Путь к tf2_textures_dir.vpk или None если не найден
        """
        if not os.path.exists(tf2_root_dir):
            return None
        
        tf_dir = os.path.join(tf2_root_dir, "tf")
        tf2_textures_dir_vpk = os.path.join(tf_dir, "tf2_textures_dir.vpk")
        if os.path.exists(tf2_textures_dir_vpk):
            return tf2_textures_dir_vpk
        
        return None
    
    @staticmethod
    def get_crowbar_path() -> str:
        """
        Возвращает путь к Crowbar CLI
        
        Returns:
            Путь к CrowbarCommandLineDecomp.exe
        """
        return TF2Paths.CROWBAR_PATH
    
    @staticmethod
    def check_crowbar() -> Tuple[bool, Optional[str]]:
        """
        Проверяет наличие Crowbar CLI
        
        Returns:
            Tuple[exists, error_message]
        """
        crowbar_path = TF2Paths.get_crowbar_path()
        if not os.path.exists(crowbar_path):
            return False, f"Crowbar CLI missing: {crowbar_path}"
        return True, None



# ── Кандидаты MDL-путей для шапок (единая логика для сборки/превью/извлечения) ──

_TF2_CLASSES = (
    "heavy", "scout", "soldier", "pyro",
    "demoman", "engineer", "medic", "sniper", "spy",
)


def build_hat_mdl_candidates(mdl_rel: str) -> list:
    """
    Список путей-кандидатов к MDL шапки внутри VPK (порядок сохранён, без дублей):

      1. Раскрывает %s-плейсхолдер во все 9 классов TF2
         (all_domination_%s.mdl → all_domination_heavy.mdl и т.д.).
      2. Добавляет варианты расположения:
         models/player/items ↔ models/workshop/player/items ↔
         models/workshop_partner/player/items.
      3. Для путей с суффиксом класса (..._heavy.mdl) добавляет остальные классы.

    Все пути приводятся к нижнему регистру (в VPK ключи — lowercase).
    Используется в сборке, 3D-превью и извлечении — раньше дублировалось трижды.
    """
    import re
    norm = mdl_rel.replace("\\", "/").lower()

    # 1. %s → классы
    if "%s" in norm:
        base = []
        for cls in _TF2_CLASSES:
            try:
                v = norm % cls
            except (TypeError, ValueError):
                v = norm.replace("%s", cls)
            if v not in base:
                base.append(v)
    else:
        base = [norm]

    # 2. player/items ↔ workshop ↔ workshop_partner
    paths = []
    for c in base:
        paths.append(c)
        for src, dsts in (
            ("models/player/items",
             ("models/workshop_partner/player/items", "models/workshop/player/items")),
            ("models/workshop/player/items",
             ("models/workshop_partner/player/items", "models/player/items")),
            ("models/workshop_partner/player/items",
             ("models/workshop/player/items", "models/player/items")),
        ):
            if src in c:
                for dst in dsts:
                    v = c.replace(src, dst)
                    if v not in paths:
                        paths.append(v)
                break

    # 3. Суффиксы класса (_heavy → остальные классы)
    cls_pat = re.compile(
        r'_(heavy|scout|soldier|pyro|demoman|engineer|medic|sniper|spy)\.mdl$'
    )
    extra = []
    for c in list(paths):
        if cls_pat.search(c):
            for cls in _TF2_CLASSES:
                # группа всегда оканчивается на .mdl — подставляем явно
                variant = cls_pat.sub(f'_{cls}.mdl', c)
                if variant not in paths and variant not in extra:
                    extra.append(variant)
    paths += extra

    return paths
