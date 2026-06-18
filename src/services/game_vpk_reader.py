"""
Кэширующий читатель игровых VPK (tf2_textures_dir.vpk / tf2_misc_dir.vpk).

Зачем: ``vpk.open()`` парсит весь индекс архива (десятки тысяч записей —
особенно tf2_textures_dir.vpk). Раньше воркеры предпросмотра открывали одни и
те же VPK по 5–9 раз за прогон (в каждом методе свой ``vpk.open``). Этот класс
открывает каждый VPK ОДИН раз и переиспользует хэндлы.

Плюс централизует типовую цепочку «найти VMT → распарсить $basetexture →
найти VTF», которая дублировалась в preview-воркерах и сервисах извлечения.

Использование:
    with GameVpkReader([textures_vpk, misc_vpk]) as reader:
        data = reader.read("materials/models/.../c_x.vtf")
        vmt = reader.find_vmt(cdmaterials, "c_x")          # (path, content) | None
        if vmt:
            base = GameVpkReader.parse_basetexture(vmt[1])
            vtf  = reader.find_vtf_for_basetexture(base)
"""

import os
import re
from typing import List, Optional, Tuple

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

# Подмены workshop-путей: одна и та же текстура может лежать под
# models/player/items ИЛИ models/workshop[_partner]/player/items.
_WORKSHOP_SWAPS = [
    ("materials/models/player/items",
     "materials/models/workshop_partner/player/items"),
    ("materials/models/player/items",
     "materials/models/workshop/player/items"),
    ("materials/models/workshop_partner/player/items",
     "materials/models/player/items"),
    ("materials/models/workshop/player/items",
     "materials/models/player/items"),
]

_RE_BASETEX_QUOTED = re.compile(r'"?\$baseTexture"?\s+"([^"]+)"', re.IGNORECASE)
_RE_BASETEX_BARE = re.compile(r'"?\$baseTexture"?\s+([^\s"{}]+)', re.IGNORECASE)


class GameVpkReader:
    """Открывает игровые VPK один раз и переиспользует хэндлы."""

    def __init__(self, vpk_paths: List[Optional[str]]):
        # Сохраняем порядок (он задаёт приоритет при дублях ключей в разных VPK).
        self._paths = [p for p in vpk_paths if p]
        self._paks: Optional[list] = None

    @property
    def paks(self) -> list:
        """Лениво открывает каждый существующий VPK один раз, кэширует список."""
        if self._paks is None:
            import vpk as vpklib
            self._paks = []
            for path in self._paths:
                if not os.path.exists(path):
                    continue
                try:
                    self._paks.append(vpklib.open(path))
                except Exception as exc:
                    logger.debug(f"GameVpkReader: не удалось открыть {path}: {exc}")
        return self._paks

    def read(self, internal_path: str) -> Optional[bytes]:
        """Читает файл по внутреннему пути из первого VPK, где он есть."""
        for pak in self.paks:
            try:
                return pak[internal_path].read()
            except KeyError:
                continue
            except Exception as exc:
                logger.debug(f"GameVpkReader.read({internal_path}): {exc}")
        return None

    @staticmethod
    def find_vmt_in_pak(pak, cdmaterials: List[str], mat_name: str) -> Optional[Tuple[str, str]]:
        """
        Ищет VMT материала в ОДНОМ открытом pak (cdmaterials × workshop-подмены).

        Пропускает VMT, в пути/контенте которых есть «backpack» (иконки
        инвентаря, не модельные текстуры).

        Returns:
            (vmt_path, vmt_content) или None.
        """
        candidates: List[str] = []
        for cdmat in cdmaterials:
            base_dir = f"materials/{cdmat}"
            candidates.append(f"{base_dir}/{mat_name}.vmt")
            for src, dst in _WORKSHOP_SWAPS:
                if base_dir.startswith(src):
                    candidates.append(f"{base_dir.replace(src, dst, 1)}/{mat_name}.vmt")

        for path in candidates:
            try:
                raw = pak[path].read()
            except KeyError:
                continue
            except Exception:
                continue
            try:
                content = raw.decode("utf-8", errors="replace")
            except Exception:
                continue
            if "backpack" in path.lower() or "backpack" in content.lower():
                logger.debug(f"GameVpkReader: пропускаем backpack VMT: {path}")
                continue
            return path, content
        return None

    def find_vmt(self, cdmaterials: List[str], mat_name: str) -> Optional[Tuple[str, str]]:
        """Ищет VMT по всем открытым pak (порядок paks = приоритет)."""
        for pak in self.paks:
            result = self.find_vmt_in_pak(pak, cdmaterials, mat_name)
            if result:
                return result
        return None

    @staticmethod
    def parse_basetexture(vmt_content: str) -> Optional[str]:
        """
        Извлекает $baseTexture из VMT (ключ с кавычками/без, значение с/без кавычек).
        Возвращает путь относительно materials/ (прямые слеши, lowercase) или None.
        """
        m = _RE_BASETEX_QUOTED.search(vmt_content)
        if m:
            return m.group(1).replace("\\", "/").lower()
        m = _RE_BASETEX_BARE.search(vmt_content)
        return m.group(1).replace("\\", "/").lower() if m else None

    @staticmethod
    def find_vtf_in_pak(pak, basetexture: str) -> Optional[bytes]:
        """Находит VTF в ОДНОМ pak по значению $baseTexture (путь относительно materials/)."""
        if not basetexture:
            return None
        path = basetexture.replace("\\", "/").lower().strip("/")
        if not path.startswith("materials/"):
            path = "materials/" + path
        if not path.endswith(".vtf"):
            path += ".vtf"
        try:
            return pak[path].read()
        except KeyError:
            return None
        except Exception:
            return None

    def find_vtf_for_basetexture(self, basetexture: str) -> Optional[bytes]:
        """Находит VTF по значению $baseTexture во всех открытых pak."""
        for pak in self.paks:
            data = self.find_vtf_in_pak(pak, basetexture)
            if data is not None:
                return data
        return None

    def close(self) -> None:
        """Закрывает все открытые VPK-хэндлы (если поддерживают close)."""
        for pak in (self._paks or []):
            close = getattr(pak, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        self._paks = None

    def __enter__(self) -> "GameVpkReader":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
