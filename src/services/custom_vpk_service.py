"""
Сервис для работы с пользовательскими VPK модами.
Позволяет загрузить готовый VPK мод, заменить в нём текстуры и пересобрать.
Обнаружение текстур происходит через сканирование VTF файлов (discover_textures).
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Callable, Tuple

from src.shared.constants import ToolPaths, ToolTimeouts
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class CustomVPKService:
    """Сервис для редактирования и пересборки пользовательских VPK модов."""

    # ── Извлечение ───────────────────────────────────────────────────────── #

    @staticmethod
    def extract_vpk_to_dir(vpk_path: str, output_dir: str) -> bool:
        """
        Распаковывает VPK файл в указанную директорию.

        Порядок попыток:
          1. vpk.exe x <file>     — официальный инструмент Valve (самый надёжный)
          2. Python-библиотека vpk — резервный метод
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # ── Попытка 1: vpk.exe x ───────────────────────────────────────────
        if CustomVPKService._extract_via_vpk_exe(vpk_path, str(output_path)):
            return True

        logger.warning("vpk.exe недоступен или не смог распаковать — пробуем Python-библиотеку vpk")

        # ── Попытка 2: Python-библиотека vpk ──────────────────────────────
        return CustomVPKService._extract_via_python_vpk(vpk_path, str(output_path))

    @staticmethod
    def _extract_via_vpk_exe(vpk_path: str, output_dir: str) -> bool:
        """Распаковка через tools/VPK/vpk.exe с ключом 'x'."""
        vpk_tool = str(ToolPaths.get_vpk_tool())
        if not Path(vpk_tool).exists():
            logger.debug(f"vpk.exe не найден по пути {vpk_tool}")
            return False

        try:
            result = subprocess.run(
                [vpk_tool, "x", os.path.abspath(vpk_path)],
                cwd=output_dir,
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=ToolTimeouts.VPK,
            )
            stdout = (result.stdout or "").strip()
            stderr = (result.stderr or "").strip()
            if stdout:
                logger.debug(f"vpk.exe x stdout: {stdout[:500]}")
            if stderr:
                logger.debug(f"vpk.exe x stderr: {stderr[:500]}")

            if result.returncode != 0:
                logger.warning(f"vpk.exe x завершился с кодом {result.returncode}")
                return False

            # Проверяем, что реально что-то распаковалось
            extracted = list(Path(output_dir).rglob('*'))
            file_count = sum(1 for p in extracted if p.is_file())
            logger.info(f"vpk.exe x: распаковано {file_count} файлов в {output_dir}")
            return file_count > 0

        except Exception as e:
            logger.warning(f"vpk.exe x упал с исключением: {e}")
            return False

    @staticmethod
    def _extract_via_python_vpk(vpk_path: str, output_dir: str) -> bool:
        """Распаковка через Python-библиотеку vpk (резервный метод)."""
        try:
            import vpk as vpklib
        except ImportError:
            logger.error("Библиотека vpk не установлена. Установите через: pip install vpk")
            return False

        try:
            pak = vpklib.open(vpk_path)
        except Exception as e:
            logger.error(f"Не удалось открыть VPK {vpk_path}: {e}", exc_info=True)
            return False

        output_path = Path(output_dir)
        extracted = 0
        errors = 0
        try:
            for file_path in pak:
                try:
                    entry = pak[file_path]
                    data = entry.read()
                    # Нормализуем разделители (VPK всегда хранит с '/')
                    dest = output_path / Path(file_path.replace('\\', '/'))
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(data)
                    extracted += 1
                except Exception as e:
                    logger.warning(f"Пропуск файла {file_path}: {e}")
                    errors += 1
            logger.info(f"Python-vpk: распаковано {extracted} файлов (пропущено {errors}) в {output_dir}")
            return extracted > 0
        except Exception as e:
            logger.error(f"Ошибка при распаковке VPK (Python-vpk): {e}", exc_info=True)
            return False

    # Служебные VTF (не основная текстура) — исключаем из карточек.
    _SKIP_VTF_KEYWORDS = (
        "lightwarp", "phongwarp", "envmap", "cubemap", "sheen",
        "bumpmap", "_normal", "normalmap", "detail", "_spec",
        "selfillum", "_mask", "exponent",
    )

    @classmethod
    def discover_textures(cls, extract_dir: str) -> List[Dict]:
        """
        Перечисляет ОСНОВНЫЕ текстуры мода по самим VTF-файлам (надёжно: не зависит
        от того, насколько корректны/полны VMT). VMT подтягивается как доп. инфо
        (путь VMT для возможной правки). Служебные VTF (lightwarp/bump/… ) отброшены.

        Каждый элемент:
            name        — уникальный ключ карточки/сборки
            vtf_name    — реальное имя VTF-файла без расширения
            vtf_path    — путь к VTF
            vmt_path    — путь к парному VMT (или None)
            vmt_dir     — папка, куда класть заменённый VTF
            is_blue     — VTF-стебель оканчивается на _blue
            rel_dir     — папка VTF относительно extract_dir (для дизамбигуации)
        """
        extract_path = Path(extract_dir)
        all_files = [f for f in extract_path.rglob('*') if f.is_file()]
        vtf_files = [f for f in all_files if f.suffix.lower() == '.vtf']
        vmt_files = [f for f in all_files if f.suffix.lower() == '.vmt']

        # Индекс VMT по стеблю имени → путь VMT (для привязки к VTF).
        vmt_by_stem: Dict[str, str] = {}
        for vf in vmt_files:
            vmt_by_stem.setdefault(vf.stem.lower(), str(vf))

        def _is_service(p: Path) -> bool:
            low = p.name.lower()
            return any(kw in low for kw in cls._SKIP_VTF_KEYWORDS)

        entries: List[Dict] = []
        for vtf in sorted(vtf_files):
            if _is_service(vtf):
                continue
            stem = vtf.stem
            try:
                rel_dir = os.path.relpath(str(vtf.parent), str(extract_path)).replace('\\', '/')
            except Exception:
                rel_dir = ''
            entries.append({
                'name': stem,
                'vtf_name': stem,
                'vtf_path': str(vtf),
                'vmt_path': vmt_by_stem.get(stem.lower()),
                'vmt_dir': str(vtf.parent),
                'is_blue': stem.lower().endswith('_blue'),
                'rel_dir': rel_dir,
            })

        if not entries:
            logger.info(f"discover_textures: VTF не найдены в {extract_dir}")
        else:
            logger.info(f"discover_textures: {len(entries)} основных VTF в {extract_dir}")
        cls._disambiguate_names(entries)
        return entries

    @staticmethod
    def _disambiguate_names(textures: List[Dict]) -> None:
        """Делает поле 'name' уникальным в пределах списка (in-place).

        Имена не конфликтуют → не трогаем (обратная совместимость). При коллизии
        к имени добавляется последний сегмент папки, затем — индекс, пока не
        станет уникальным.
        """
        counts: Dict[str, int] = {}
        for t in textures:
            counts[t['vtf_name']] = counts.get(t['vtf_name'], 0) + 1

        used: set = set()
        for t in textures:
            base = t['vtf_name']
            if counts.get(base, 0) <= 1:
                t['name'] = base
                used.add(base)
                continue
            seg = (t.get('rel_dir') or '').split('/')[-1]
            candidate = f"{base} [{seg}]" if seg else base
            i = 2
            while candidate in used:
                candidate = f"{base} [{seg}{i}]" if seg else f"{base} ({i})"
                i += 1
            t['name'] = candidate
            used.add(candidate)

    # ── Основной пайплайн сборки ─────────────────────────────────────────── #

    @staticmethod
    def build_custom_mod(
        custom_vpk_source_path: str,
        image_path: Optional[str],
        size: Tuple[int, int],
        format_type: str = "DXT1",
        flags: Optional[List[str]] = None,
        vtf_options: Optional[Dict] = None,
        export_folder: str = "export",
        filename: str = "custom_mod.vpk",
        extra_texture_callback: Optional[Callable[[str, str], Optional[str]]] = None,
        language: str = "en",
        sub_progress_callback: Optional[Callable[[int, str], None]] = None,
        custom_vtf_path: Optional[str] = None,
        hat_mdl_path: Optional[str] = None,  # не используется в custom-режиме (для совместимости вызова)
    ) -> Tuple[bool, str]:
        """
        Полный пайплайн редактирования кастомного мода:

        1. Распаковать исходный VPK
        2. Сканировать VMT → найти все текстуры (RED + BLU)
        3. Первую RED текстуру → заменить из image_path (или custom_vtf_path)
        4. Остальные → запросить через extra_texture_callback; если отказ — оставить оригинал
        5. Перепаковать в VPK и скопировать в export_folder
        """
        from src.services.texture_service import TextureService
        from src.shared.file_utils import copy_file_safe
        from src.data.translations import TRANSLATIONS

        t = TRANSLATIONS.get(language, TRANSLATIONS['en'])

        def emit(pct: int, label: str) -> None:
            if sub_progress_callback:
                sub_progress_callback(pct, label)

        # Временная директория — называем "vpkroot" чтобы vpk.exe создал "vpkroot.vpk"
        temp_root = Path(tempfile.mkdtemp(prefix="tf2sg_custom_"))
        vpkroot_dir = temp_root / "vpkroot"

        try:
            # ── 1. Извлечение ──────────────────────────────────────────── #
            emit(-1, "Extracting VPK..." if language == "en" else "Распаковка VPK...")
            if not CustomVPKService.extract_vpk_to_dir(custom_vpk_source_path, str(vpkroot_dir)):
                return False, (
                    "Failed to extract VPK. Make sure the file is a valid single-file VPK mod."
                    if language == "en" else
                    "Не удалось распаковать VPK. Убедитесь, что это корректный однофайловый VPK мод."
                )

            # ── 2. Обнаружение текстур ─────────────────────────────────── #
            # По самим VTF-файлам (как и 2D-карточки) — чтобы замена на любой
            # карточке (включая стили) применилась; имена совпадают с карточками.
            emit(-1, "Scanning textures..." if language == "en" else "Сканирование текстур...")
            discovered = CustomVPKService.discover_textures(str(vpkroot_dir))
            all_textures = ([t for t in discovered if not t['is_blue']]
                            + [t for t in discovered if t['is_blue']])

            if not all_textures:
                return False, (
                    "No textures found in VPK (no VTF files)."
                    if language == "en" else
                    "В VPK не найдено текстур (нет VTF файлов)."
                )

            # ── 3. Подготовка конвертера ───────────────────────────────── #
            vtf_flags, flags_opts = TextureService.parse_vtf_flags_and_options(flags or [])
            merged_opts: Dict = {}
            if vtf_options:
                merged_opts.update(vtf_options)
            merged_opts.update(flags_opts)
            merged_opts.pop('normal', None)  # normal map не применяем автоматически

            def _replace(src_img: str, tex: Dict) -> bool:
                """Конвертирует src_img в VTF и заменяет VTF-файл текстуры."""
                vmt_dir = Path(tex['vmt_dir'])
                # Имя файла — реальное имя VTF, а не уникализированный ключ карточки
                # ('name' может содержать дискриминатор папки при коллизии стилей).
                tex_name = tex.get('vtf_name') or tex['name']

                # Если VTF уже существует — кладём рядом с ним;
                # иначе кладём рядом с VMT (стандартное место для TF2 модов).
                if tex.get('vtf_path'):
                    vtf_dest = Path(tex['vtf_path'])
                else:
                    vtf_dest = vmt_dir / f"{tex_name}.vtf"

                vtf_dest.parent.mkdir(parents=True, exist_ok=True)

                try:
                    if custom_vtf_path and tex is all_textures[0]:
                        # Первая текстура + пользователь загрузил готовый VTF — копируем напрямую
                        copy_file_safe(custom_vtf_path, str(vtf_dest))
                    elif TextureService.is_animated_image(src_img):
                        TextureService.create_animated_vtf(
                            src_img, str(vtf_dest), size, format_type, vtf_flags, merged_opts
                        )
                    else:
                        # process_image → PNG → create_vtf → VTF
                        tmp_png = vtf_dest.parent / f"{tex_name}.png"
                        TextureService.process_image(src_img, str(tmp_png), size)
                        TextureService.create_vtf(
                            str(tmp_png), str(vtf_dest.parent), format_type, vtf_flags, merged_opts
                        )
                        if tmp_png.exists():
                            tmp_png.unlink()
                    logger.info(f"Текстура заменена: {vtf_dest}")
                    return True
                except Exception as e:
                    logger.error(f"Ошибка замены {tex_name}: {e}", exc_info=True)
                    return False

            # ── 4. Замена текстур ──────────────────────────────────────── #
            from src.shared.constants import EXTRA_TEX_USE_GAME_ORIGINAL

            # Первая (главная) текстура — из image_path пользователя (классический
            # путь). Если image_path не задан (режим 2D-карточек) — главную
            # текстуру тоже спрашиваем через callback, как и остальные.
            first = all_textures[0]
            if image_path and os.path.isfile(image_path):
                emit(-1,
                     f"Converting {first['name']}..."
                     if language == "en" else
                     f"Конвертация {first['name']}...")
                _replace(image_path, first)
                remaining = all_textures[1:]
            else:
                remaining = all_textures

            # Остальные текстуры — спрашиваем последовательно через callback
            for tex in remaining:
                user_img = extra_texture_callback(tex['name'], "custom") if extra_texture_callback else None
                # «Использовать обычную» — оставляем оригинальный VTF без изменений
                if user_img == EXTRA_TEX_USE_GAME_ORIGINAL:
                    logger.info(f"Custom VPK: пропускаем текстуру (использовать из мода): {tex['name']}")
                    continue
                if user_img and os.path.isfile(user_img):
                    emit(-1,
                         f"Converting {tex['name']}..."
                         if language == "en" else
                         f"Конвертация {tex['name']}...")
                    _replace(user_img, tex)
                # Если пользователь не выбрал — оригинальный VTF остаётся без изменений

            # ── 5. Перепаковка ─────────────────────────────────────────── #
            emit(-1, "Packing VPK..." if language == "en" else "Упаковка VPK...")
            from src.services.packaging_service import PackagingService
            final = PackagingService.pack_directory(
                vpkroot_dir=vpkroot_dir,
                filename=filename,
                export_folder=export_folder,
                language=language,
            )

            msg = t.get('vpk_success', 'VPK successfully created: {path}').format(path=str(final))
            logger.info(msg)
            return True, msg

        except Exception as e:
            logger.error(f"Критическая ошибка build_custom_mod: {e}", exc_info=True)
            return False, str(e)
        finally:
            shutil.rmtree(str(temp_root), ignore_errors=True)
