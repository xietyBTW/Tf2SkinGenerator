"""
Генерация «цветного» crit.pcf из стокового particle-файла TF2.

Зачем так:
    Приложение НЕ распространяет particle-файл Valve. Вместо того чтобы носить
    правленый crit.pcf в репозитории (это контент Valve — chужой copyright),
    мы берём оригинальный ``particles/crit.pcf`` из установленной у пользователя
    TF2 (``tf2_misc_dir.vpk``) и применяем к нему ровно ту модификацию, которая
    делает текст крита/промаха цветным вместо форсированного зелёного:

      • из систем ``crit_text`` и ``miss_text`` удаляется инициализатор
        ``Color Random`` (он задаёт стартовый цвет частицы: зелёный 0 255 30);
      • оттуда же удаляется оператор ``Color Fade`` (уводит цвет по времени жизни).

    После удаления у частицы остаётся базовый цвет определения (255 255 255) —
    и damage-текст рендерится в своём натуральном цвете, а не зелёным.

    В git при этом лежит только ЭТОТ код (описание правки), а не файл Valve.

Результат кэшируется в ``tools/mod_data/crit.pcf`` — первая сборка critHIT его
создаёт, дальнейшие переиспользуют.
"""

import io
import os
import re
from pathlib import Path
from typing import Optional

from src.services.tf2_paths import TF2Paths
from src.shared.file_utils import ensure_directory_exists
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

try:
    from srctools.dmx import Element
    SRCTOOLS_AVAILABLE = True
except ImportError:
    SRCTOOLS_AVAILABLE = False
    Element = None  # type: ignore


class CritPcfService:
    """Строит цветной crit.pcf из стокового файла TF2."""

    #: Путь к particle-файлу внутри tf2_misc_dir.vpk.
    PCF_VPK_PATH = "particles/crit.pcf"

    #: Системы частиц, в которых убираем принудительный цвет.
    TARGET_SYSTEMS = ("crit_text", "miss_text")

    #: Что удаляем: {имя_массива: {имена_подэлементов_в_нижнем_регистре}}.
    _REMOVE = {
        "operators": {"color fade"},
        "initializers": {"color random"},
    }

    @classmethod
    def ensure_colored_crit_pcf(
        cls,
        tf2_root_dir: str,
        dest_path,
        force: bool = False,
    ) -> Optional[str]:
        """
        Гарантирует наличие цветного crit.pcf по пути ``dest_path``.

        Args:
            tf2_root_dir: Корень установки TF2 (…/steamapps/common/Team Fortress 2).
            dest_path:    Куда положить готовый файл (обычно tools/mod_data/crit.pcf).
            force:        True → перегенерировать, даже если файл уже есть.

        Returns:
            Путь к готовому файлу (str) либо None, если сгенерировать не удалось
            (нет srctools / нет пути к TF2 / не найден стоковый crit.pcf).
            None — не фатально: вызывающий код просто соберёт мод без crit.pcf.
        """
        dest = Path(dest_path)

        if dest.exists() and not force:
            return str(dest)

        if not SRCTOOLS_AVAILABLE:
            logger.warning(
                "Библиотека srctools не установлена — не могу сгенерировать crit.pcf. "
                "Установите: pip install srctools"
            )
            return None

        if not tf2_root_dir or not os.path.exists(tf2_root_dir):
            logger.warning(
                f"Путь к TF2 не задан или не существует ({tf2_root_dir!r}) — "
                "crit.pcf не сгенерирован."
            )
            return None

        # ── Достаём стоковый crit.pcf из tf2_misc_dir.vpk ──────────────────────
        try:
            _studiomdl, tf2_misc_vpk, _tf_dir = TF2Paths.resolve(tf2_root_dir)
        except FileNotFoundError as e:
            logger.warning(f"Не удалось найти tf2_misc_dir.vpk: {e}")
            return None

        raw = cls._read_stock_pcf(tf2_misc_vpk)
        if raw is None:
            logger.warning(
                f"Стоковый {cls.PCF_VPK_PATH} не найден в {tf2_misc_vpk}."
            )
            return None

        # ── Преобразуем и сохраняем ────────────────────────────────────────────
        try:
            data = cls._strip_forced_color(raw)
        except Exception as e:
            logger.error(f"Ошибка преобразования crit.pcf: {e}", exc_info=True)
            return None

        try:
            ensure_directory_exists(dest.parent)
            dest.write_bytes(data)
        except OSError as e:
            logger.error(f"Не удалось записать {dest}: {e}", exc_info=True)
            return None

        logger.info(f"Сгенерирован цветной crit.pcf из TF2: {dest}")
        return str(dest)

    # ── Внутреннее ──────────────────────────────────────────────────────────── #

    @staticmethod
    def _read_stock_pcf(tf2_misc_vpk: str) -> Optional[bytes]:
        """Читает particles/crit.pcf из tf2_misc_dir.vpk (через общий кэш VPK)."""
        try:
            from src.services.vpk_cache import open_vpk_cached
        except ImportError:
            logger.error("Модуль vpk_cache недоступен.")
            return None

        try:
            vpk_file = open_vpk_cached(tf2_misc_vpk)
        except Exception as e:
            logger.warning(f"Не удалось открыть VPK {tf2_misc_vpk}: {e}", exc_info=True)
            return None
        if vpk_file is None:
            return None

        path = CritPcfService.PCF_VPK_PATH
        if path not in vpk_file:
            return None
        try:
            return vpk_file[path].read()
        except Exception as e:
            logger.warning(f"Ошибка чтения {path} из VPK: {e}", exc_info=True)
            return None

    @classmethod
    def _strip_forced_color(cls, raw: bytes) -> bytes:
        """
        Парсит бинарный PCF, удаляет Color Random/Color Fade из целевых систем и
        возвращает сериализованный бинарный PCF (с тем же binary-encoding/format,
        что и оригинал).
        """
        enc_ver, fmt_name, fmt_ver = cls._detect_encoding(raw)

        root, _, _ = Element.parse(io.BytesIO(raw))

        try:
            defs = list(root["particleSystemDefinitions"].iter_elem())
        except KeyError:
            defs = []

        for definition in defs:
            if definition.name in cls.TARGET_SYSTEMS:
                cls._strip_element(definition)

        out = io.BytesIO()
        root.export_binary(
            out, version=enc_ver, fmt_name=fmt_name, fmt_ver=fmt_ver, unicode="format"
        )
        return out.getvalue()

    @classmethod
    def _strip_element(cls, el) -> None:
        """Удаляет из массивов элемента подэлементы с целевыми именами (in-place)."""
        for group, names in cls._REMOVE.items():
            if group not in el:
                continue
            kept = [
                sub for sub in el[group].iter_elem()
                if (sub.name or "").strip().lower() not in names
            ]
            el[group] = kept

    @staticmethod
    def _detect_encoding(raw: bytes):
        """
        Читает из заголовка ``<!-- dmx encoding binary N format NAME V -->``
        версию бинарного кодирования и формат. Фолбэк — (2, 'pcf', 1),
        как в стоковых crit.pcf TF2.
        """
        header = raw.split(b"-->", 1)[0]
        m = re.search(
            rb"encoding\s+binary\s+(\d+)\s+format\s+(\w+)\s+(\d+)", header
        )
        if m:
            return int(m.group(1)), m.group(2).decode("ascii"), int(m.group(3))
        return 2, "pcf", 1
