"""
Сервис для работы с пользовательскими VPK модами.
Позволяет загрузить готовый VPK мод, заменить в нём текстуры и пересобрать.
Обнаружение текстур происходит через сканирование VMT файлов (без QC).
"""

import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Callable, Tuple

from src.shared.file_utils import ensure_directory_exists
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

    # ── Сканирование VMT ─────────────────────────────────────────────────── #

    # Паттерны для поиска текстур в VMT-файлах.
    # Проверяем $basetexture, затем $detail и $bumpmap как запасные варианты.
    _VMT_TEX_PATTERNS: List[re.Pattern] = [
        re.compile(r'"\$basetexture"\s+"([^"]+)"', re.IGNORECASE),
        re.compile(r'\$basetexture\s+"([^"]+)"', re.IGNORECASE),
        re.compile(r'\$basetexture\s+(\S+)', re.IGNORECASE),
    ]

    @classmethod
    def scan_vmt_textures(cls, extract_dir: str) -> Dict:
        """
        Сканирует VMT файлы в распакованном VPK и возвращает структуру текстур.

        Каждая запись содержит:
            name      — имя текстуры (без расширения, из $basetexture)
            is_blue   — True если имя заканчивается на _blue
            vmt_path  — полный путь к VMT файлу
            vtf_path  — полный путь к VTF файлу (None если не существует)
            vmt_dir   — директория VMT (туда же кладётся заменённый VTF)

        Returns:
            {
                'all_textures': list[dict],
                'red_textures': list[dict],   # без _blue суффикса
                'blue_textures': list[dict],  # с _blue суффиксом
            }
        """
        extract_path = Path(extract_dir)
        textures: List[Dict] = []
        seen: set = set()

        # Диагностика: логируем структуру распакованной директории
        all_files = list(extract_path.rglob('*'))
        file_count = sum(1 for f in all_files if f.is_file())
        logger.info(f"Сканирование директории {extract_dir}: {file_count} файлов всего")

        vmt_files = [f for f in all_files if f.is_file() and f.suffix.lower() == '.vmt']
        logger.info(f"VMT файлов найдено: {len(vmt_files)}")
        for vf in vmt_files[:10]:  # первые 10 для диагностики
            logger.debug(f"  VMT: {vf.relative_to(extract_path)}")

        if not vmt_files:
            # Подробный вывод расширений, чтобы понять, что вообще есть в VPK
            exts: Dict[str, int] = {}
            for f in all_files:
                if f.is_file():
                    exts[f.suffix.lower()] = exts.get(f.suffix.lower(), 0) + 1
            logger.warning(f"VMT файлы не найдены. Расширения в VPK: {dict(sorted(exts.items()))}")

        for vmt_file in sorted(vmt_files):
            try:
                # Пробуем несколько кодировок
                content = None
                for enc in ('utf-8', 'cp1251', 'latin-1'):
                    try:
                        content = vmt_file.read_text(encoding=enc, errors='strict')
                        break
                    except (UnicodeDecodeError, Exception):
                        continue
                if content is None:
                    content = vmt_file.read_bytes().decode('utf-8', errors='ignore')
            except Exception as e:
                logger.warning(f"Не удалось прочитать {vmt_file}: {e}")
                continue

            # Пробуем паттерны по очереди
            basetexture: Optional[str] = None
            for pat in cls._VMT_TEX_PATTERNS:
                m = pat.search(content)
                if m:
                    basetexture = m.group(1).strip()
                    break

            if not basetexture:
                logger.debug(f"$basetexture не найден в {vmt_file.name}")
                logger.debug(f"  Содержимое (первые 200 симв): {content[:200]!r}")
                continue

            basetexture = basetexture.replace('\\', '/')
            tex_name = Path(basetexture).name  # только имя файла без пути

            if tex_name in seen:
                continue
            seen.add(tex_name)

            is_blue = tex_name.lower().endswith('_blue')

            # VTF может лежать рядом с VMT, или по пути $basetexture относительно materials/
            vtf_candidates = [
                vmt_file.parent / f"{tex_name}.vtf",
                extract_path / "materials" / f"{basetexture}.vtf",
                extract_path / f"{basetexture}.vtf",
            ]
            vtf_path = next((str(p) for p in vtf_candidates if p.exists()), None)

            textures.append({
                'name': tex_name,
                'is_blue': is_blue,
                'vmt_path': str(vmt_file),
                'vtf_path': vtf_path,
                'vmt_dir': str(vmt_file.parent),
                'basetexture': basetexture,  # полный путь из VMT (для замены VTF)
            })
            logger.debug(f"  Текстура: {tex_name}  (blue={is_blue}, vtf={'найден' if vtf_path else 'не найден'})")

        red = [t for t in textures if not t['is_blue']]
        blue = [t for t in textures if t['is_blue']]
        logger.info(f"Итого: {len(textures)} текстур ({len(red)} RED, {len(blue)} BLU)")
        return {'all_textures': textures, 'red_textures': red, 'blue_textures': blue}

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

            # ── 2. Сканирование VMT ────────────────────────────────────── #
            emit(-1, "Scanning textures..." if language == "en" else "Сканирование текстур...")
            tex_info = CustomVPKService.scan_vmt_textures(str(vpkroot_dir))
            all_textures = tex_info['all_textures']

            if not all_textures:
                return False, (
                    "No textures found in VPK (no VMT files with $basetexture)."
                    if language == "en" else
                    "В VPK не найдено текстур (нет VMT файлов с $basetexture)."
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
                tex_name = tex['name']

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
            # Первая (главная) текстура — из image_path пользователя
            first = all_textures[0]
            emit(-1,
                 f"Converting {first['name']}..."
                 if language == "en" else
                 f"Конвертация {first['name']}...")
            if image_path and os.path.isfile(image_path):
                _replace(image_path, first)

            # Остальные текстуры — спрашиваем последовательно через callback
            remaining = all_textures[1:]
            for tex in remaining:
                user_img = extra_texture_callback(tex['name'], "custom") if extra_texture_callback else None
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
