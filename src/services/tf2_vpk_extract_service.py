"""
Сервис для извлечения моделей из TF2 VPK файлов
"""

import os
import time
from pathlib import Path
from typing import List, Optional, Callable, Tuple
from src.shared.logging_config import get_logger
from src.shared.file_utils import ensure_directory_exists
from src.shared.validators import sanitize_path
from src.data.translations import TRANSLATIONS
from src.data.weapons import WEAPON_TEXTURE_PATHS

logger = get_logger(__name__)

try:
    import vpk
    VPK_AVAILABLE = True
except ImportError:
    VPK_AVAILABLE = False
    vpk = None

# Кэш открытых VPK теперь общий для всех потребителей — см. src/services/vpk_cache.py
# (потоко-локальный, один open на поток; раньше извлечение и GameVpkReader держали
# отдельные кэши и открывали один и тот же игровой VPK дважды за прогон воркера).
# Имя с подчёркиванием сохранено как тонкий алиас: на него завязаны вызовы
# _open_vpk_cached внутри этого файла.
from src.services.vpk_cache import open_vpk_cached as _open_vpk_cached  # noqa: E402


class TF2VPKExtractService:
    """Сервис для работы с извлечением файлов из TF2 VPK"""
    
    @staticmethod
    def check_mdl_exists(
        dir_vpk_path: str,
        mdl_rel_path: str,
        vpk_file=None
    ) -> bool:
        """
        Быстрая проверка существования MDL файла в VPK без извлечения
        
        Args:
            dir_vpk_path: Путь к tf2_misc_dir.vpk
            mdl_rel_path: Относительный путь к .mdl файлу внутри VPK
            vpk_file: Опционально открытый VPK файл (для оптимизации, если переиспользуется)
            
        Returns:
            True если MDL файл существует в VPK, False иначе
        """
        if not VPK_AVAILABLE:
            return False
        
        if not os.path.exists(dir_vpk_path):
            return False
        
        # Нормализуем путь (используем прямые слеши)
        normalized_path = mdl_rel_path.replace("\\", "/")
        
        # Открываем VPK файл если не передан — через общий кэш (vpk.open парсит
        # весь каталог архива). Кэшированный хэндл НЕ закрываем.
        if vpk_file is None:
            try:
                vpk_file = _open_vpk_cached(dir_vpk_path)
            except Exception as e:
                logger.warning(f"Не удалось открыть VPK файл для проверки: {e}", exc_info=True)
                return False
            if vpk_file is None:
                return False

        # Проверяем существование файла в VPK (быстрая операция).
        return normalized_path in vpk_file
    
    @staticmethod
    def extract_file_set(
        dir_vpk_path: str,
        mdl_rel_path: str,
        out_dir: str,
    ) -> List[str]:
        """
        Извлекает набор файлов модели из VPK (.mdl и связанные файлы)
        ОПТИМИЗИРОВАНО: Извлекает только после подтверждения существования MDL

        Args:
            dir_vpk_path: Путь к tf2_misc_dir.vpk
            mdl_rel_path: Относительный путь к .mdl файлу внутри VPK
            out_dir: Директория для извлечения

        Returns:
            Список путей к извлеченным файлам
            
        Raises:
            RuntimeError: Если не удалось извлечь .mdl файл
        """
        if not VPK_AVAILABLE:
            raise RuntimeError(
                "Библиотека vpk не установлена. Установите её через: pip install vpk"
            )
        
        if not os.path.exists(dir_vpk_path):
            raise FileNotFoundError(f"VPK файл не найден: {dir_vpk_path}")
        
        # Сначала проверяем, существует ли MDL файл (быстрая проверка)
        if not TF2VPKExtractService.check_mdl_exists(dir_vpk_path, mdl_rel_path):
            error_msg = f"MDL файл не найден в VPK: {mdl_rel_path}\n"
            error_msg += f"VPK файл: {dir_vpk_path}\n"
            raise RuntimeError(error_msg)
        
        os.makedirs(out_dir, exist_ok=True)
        
        # Получаем базовое имя файла без расширения
        mdl_basename = os.path.splitext(os.path.basename(mdl_rel_path))[0]
        mdl_dir = os.path.dirname(mdl_rel_path)
        
        # Определяем набор файлов для извлечения
        # .mdl - обязательный (уже проверили существование)
        # .vvd - обязательный
        # *.vtx - все варианты (dx80, dx90, sw)
        # .phy - опциональный
        
        files_to_extract = []
        
        # Добавляем .mdl
        files_to_extract.append(mdl_rel_path)
        
        # Добавляем .vvd
        vvd_path = os.path.join(mdl_dir, f"{mdl_basename}.vvd").replace("\\", "/")
        files_to_extract.append(vvd_path)
        
        # Добавляем варианты .vtx
        vtx_variants = ["dx80", "dx90", "sw"]
        for variant in vtx_variants:
            vtx_path = os.path.join(mdl_dir, f"{mdl_basename}.{variant}.vtx").replace("\\", "/")
            files_to_extract.append(vtx_path)
        
        # Добавляем .phy (опционально)
        phy_path = os.path.join(mdl_dir, f"{mdl_basename}.phy").replace("\\", "/")
        files_to_extract.append(phy_path)
        
        # Открываем VPK через общий кэш (vpk.open парсит весь каталог архива —
        # дорого на каждую сборку). Кэшированный хэндл не закрываем.
        try:
            vpk_file = _open_vpk_cached(dir_vpk_path)
        except Exception as e:
            raise RuntimeError(f"Не удалось открыть VPK файл {dir_vpk_path}: {e}")
        if vpk_file is None:
            raise RuntimeError(f"Не удалось открыть VPK файл {dir_vpk_path}")
        
        extracted_files = []
        
        try:
            # Извлекаем файлы
            for file_path in files_to_extract:
                try:
                    # Нормализуем путь (используем прямые слеши)
                    normalized_path = file_path.replace("\\", "/")
                    
                    # Проверяем, существует ли файл в VPK
                    if normalized_path not in vpk_file:
                        # Для .phy ошибка допустима (файл может не существовать)
                        if not file_path.endswith(".phy"):
                            logger.debug(f"Файл {normalized_path} не найден в VPK")
                        continue
                    
                    # Получаем файл из VPK
                    vpk_entry = vpk_file[normalized_path]
                    
                    # Определяем путь для сохранения
                    try:
                        extracted_file_path = Path(sanitize_path(file_path.replace("/", os.sep), Path(out_dir)))
                    except ValueError as e:
                        logger.warning(f"Недопустимый путь при извлечении {file_path}: {e}")
                        continue
                    extracted_file_dir = extracted_file_path.parent
                    
                    # Создаем директорию если нужно
                    if extracted_file_dir:
                        os.makedirs(extracted_file_dir, exist_ok=True)
                    
                    # Извлекаем файл
                    with open(extracted_file_path, 'wb') as f:
                        f.write(vpk_entry.read())
                    
                    extracted_files.append(str(extracted_file_path))
                    logger.info(f"Извлечен файл: {file_path} -> {extracted_file_path}")
                
                except Exception as e:
                    # Для .phy ошибка допустима
                    if not file_path.endswith(".phy"):
                        logger.warning(f"Ошибка при извлечении {file_path}: {e}", exc_info=True)
            
            # Проверяем, что .mdl был извлечен (обязательный файл)
            try:
                mdl_extracted = Path(sanitize_path(mdl_rel_path.replace("/", os.sep), Path(out_dir)))
            except ValueError as e:
                logger.warning(f"Недопустимый путь для mdl: {mdl_rel_path}: {e}")
                mdl_extracted = None
            if not mdl_extracted or not os.path.exists(mdl_extracted):
                # Пробуем найти .mdl файл рекурсивно в out_dir
                mdl_filename = f"{mdl_basename}.mdl"
                
                # Ищем .mdl файл рекурсивно в out_dir
                found_mdl = None
                for root, dirs, files in os.walk(out_dir):
                    if mdl_filename in files:
                        found_mdl = os.path.join(root, mdl_filename)
                        break
                
                if not found_mdl:
                    error_msg = f"Не удалось извлечь .mdl файл: {mdl_rel_path}\n"
                    error_msg += "Проверьте, что путь правильный и файл существует в VPK.\n"
                    error_msg += f"VPK файл: {dir_vpk_path}\n"
                    error_msg += f"Ожидаемый путь в VPK: {mdl_rel_path}\n"
                    error_msg += f"Директория извлечения: {out_dir}\n"
                    error_msg += "Попробуйте проверить содержимое VPK через GCFScape.\n"
                    error_msg += "Если библиотека vpk не установлена, установите её: pip install vpk"
                    raise RuntimeError(error_msg)
                
                # Используем найденный файл
                extracted_files.append(found_mdl)
            
            return extracted_files

        finally:
            # VPK кэшируется (_open_vpk_cached) — общий хэндл не закрываем.
            pass

    @staticmethod
    def extract_vmt_file(
        dir_vpk_path: str,
        cdmaterials_path: str,
        weapon_key: str,
        out_dir: str
    ) -> Optional[str]:
        """
        Извлекает VMT файл по пути из $cdmaterials
        
        Args:
            dir_vpk_path: Путь к tf2_misc_dir.vpk (или tf2_textures_dir.vpk)
            cdmaterials_path: Путь из $cdmaterials в QC файле
            weapon_key: Ключ оружия (например, c_shogun_kunai или v_machete)
            out_dir: Директория для извлечения
            
        Returns:
            Путь к извлеченному VMT файлу или None если не найден
        """
        if not VPK_AVAILABLE:
            logger.warning("Библиотека vpk не установлена. VMT файл не будет извлечен.")
            return None
        
        if not os.path.exists(dir_vpk_path):
            logger.warning(f"VPK файл не найден: {dir_vpk_path}")
            return None
        
        os.makedirs(out_dir, exist_ok=True)
        
        # Нормализуем путь из $cdmaterials (заменяем обратные слеши на прямые)
        normalized_cdmaterials = cdmaterials_path.replace("\\", "/").strip()
        
        # Если путь заканчивается на слеш, убираем его
        if normalized_cdmaterials.endswith("/"):
            normalized_cdmaterials = normalized_cdmaterials[:-1]
        
        # Определяем имя VMT файла
        # Если путь заканчивается на c_models или c_models/, то используем weapon_key
        # Если путь заканчивается на v_weapon, то используем последний элемент пути
        vmt_filename = None
        if normalized_cdmaterials.endswith("c_models") or normalized_cdmaterials.endswith("c_models/"):
            vmt_filename = f"{weapon_key}.vmt"
        else:
            # Извлекаем последний элемент пути (например, v_machete)
            path_parts = normalized_cdmaterials.split("/")
            if path_parts:
                last_part = path_parts[-1]
                if last_part.startswith("v_"):
                    vmt_filename = f"{last_part}.vmt"
                else:
                    # Fallback: используем weapon_key
                    vmt_filename = f"{weapon_key}.vmt"
        
        # Строим полный путь к VMT файлу в VPK
        # Сначала пробуем путь как есть (может уже содержать materials/)
        vmt_rel_path = f"{normalized_cdmaterials}/{vmt_filename}" if normalized_cdmaterials else vmt_filename
        
        # Пробуем найти VMT файл в tf2_textures_dir.vpk (обычно текстуры там)
        # Но сначала проверяем tf2_misc_dir.vpk
        try:
            vpk_file = _open_vpk_cached(dir_vpk_path)
            if vpk_file is None:
                return None

            # Список путей для поиска (с разными вариантами)
            paths_to_try = []
            
            # Если путь не начинается с materials/, добавляем оба варианта
            if not normalized_cdmaterials.startswith("materials/"):
                # С materials/ (предпочтительно)
                materials_path = f"materials/{vmt_rel_path}"
                paths_to_try.append(materials_path)
            
            # Путь как есть
            paths_to_try.append(vmt_rel_path)
            
            # Пробуем каждый путь
            for path_to_try in paths_to_try:
                if path_to_try in vpk_file:
                    vpk_entry = vpk_file[path_to_try]
                    
                    # Определяем путь для сохранения
                    extracted_file_path = os.path.join(out_dir, vmt_filename)
                    
                    # Извлекаем файл
                    with open(extracted_file_path, 'wb') as f:
                        f.write(vpk_entry.read())
                    
                    logger.info(f"Извлечен VMT файл: {path_to_try} -> {extracted_file_path}")
                    return extracted_file_path
            # VPK кэшируется (_open_vpk_cached) — НЕ закрываем.

        except Exception as e:
            logger.warning(f"Ошибка при извлечении VMT файла: {e}", exc_info=True)
            return None

        # Не найден по этому пути — норма при переборе $cdmaterials путей/VPK.
        # DEBUG, чтобы не спамить лог (раньше был WARNING на каждый промах).
        logger.debug(f"VMT файл не найден по пути: {vmt_rel_path}")
        return None
    
    @staticmethod
    def _scan_dir_for_vtf(vpk_file, dir_path: str) -> List[Tuple[str, str]]:
        """Возвращает список (rel_path, filename) для всех .vtf файлов
        непосредственно в dir_path внутри VPK (без рекурсии в подпапки)."""
        prefix = dir_path.rstrip('/') + '/'
        results = []
        for path in vpk_file:
            if path.startswith(prefix) and path.lower().endswith('.vtf'):
                remainder = path[len(prefix):]
                if '/' not in remainder:   # только прямые потомки папки
                    results.append((path, remainder))
        return results

    @staticmethod
    def extract_texture_with_progress(
        textures_vpk_path: str,
        weapon_key: str,
        out_dir: str,
        export_format: str = "VTF",
        language: str = "en",
        progress_callback: Optional[Callable[[int, str], None]] = None,
        cancel_callback: Optional[Callable[[], bool]] = None
    ) -> Tuple[bool, str, bool]:
        """
        Извлекает VTF-текстуры оружия — ровно те, что при сборке мода будут заменены.

        Алгоритм (приоритет по убыванию):
          1. WEAPON_TEXTURE_PATHS override — явный список файлов для нестандартных оружий.
          2. QC из decompile-кэша → parse $texturegroup → red_row + blu_row
             (та же логика что build: ModelBuildService.extract_texturegroup_structure).
          3. Fallback: ищем только главный VTF по weapon_key (одна текстура).
        """
        t = TRANSLATIONS.get(language, TRANSLATIONS['en'])

        def emit_progress(value: int, message: str) -> None:
            if progress_callback:
                progress_callback(value, message)

        def is_cancelled() -> bool:
            return bool(cancel_callback and cancel_callback())

        def _close(vpk_f) -> None:
            # VPK кэшируется (_open_vpk_cached) — общий хэндл не закрываем.
            # Оставлено как no-op, чтобы не трогать все места вызова.
            pass

        def _extract_and_convert(vpk_f, rel_path: str, filename: str) -> Optional[str]:
            """Извлекает один VTF и конвертирует если нужно. Возвращает финальный путь или None."""
            try:
                out_path = sanitize_path(filename, out_dir)
            except ValueError as exc:
                logger.warning(f"Недопустимый путь для VTF {filename}: {exc}")
                return None
            with open(out_path, 'wb') as f:
                f.write(vpk_f[rel_path].read())
            if export_format.upper() != 'VTF':
                converted = TF2VPKExtractService._convert_vtf_to_image(
                    out_path, out_dir, export_format.upper()
                )
                if converted:
                    try:
                        os.remove(out_path)
                    except Exception:
                        pass
                    return converted
            return out_path

        def _finish(paths: List[str]) -> Tuple[bool, str, bool]:
            emit_progress(100, t.get('extract_completed', 'Extraction completed'))
            if len(paths) == 1:
                msg = t.get('texture_extracted_success',
                            'Texture extracted successfully: {path}').format(path=paths[0])
            else:
                header = t.get('textures_extracted_multiple',
                               'Extracted {n} textures:').format(n=len(paths))
                msg = header + '\n' + '\n'.join(paths)
            return True, msg, False

        # ── Базовые проверки ──────────────────────────────────────────────────
        emit_progress(10, t.get('extract_init', 'Initializing extraction...'))
        time.sleep(0.1)

        if is_cancelled():
            return False, t.get('extract_cancelled', 'Extraction cancelled by user'), True

        if not VPK_AVAILABLE:
            return False, t.get('vpk_library_not_available', 'VPK library not available'), False

        emit_progress(20, t.get('extract_checking', 'Checking VPK file...'))
        time.sleep(0.1)

        if not os.path.exists(textures_vpk_path):
            return False, t.get('textures_vpk_not_found', 'tf2_textures_dir.vpk not found'), False

        if is_cancelled():
            return False, t.get('extract_cancelled', 'Extraction cancelled by user'), True

        ensure_directory_exists(out_dir)

        # ── Производные имена для построения путей поиска ────────────────────
        base_key = weapon_key[2:] if weapon_key.startswith('c_') else weapon_key
        _parts = base_key.rsplit('_', 1)
        parent_key = ('c_' + _parts[0]) if len(_parts) == 2 else None

        # ── Пути поиска в VPK (приоритет: workshop_partner → workshop → weapons)
        search_paths = [
            f"materials/models/workshop_partner/weapons/c_models/{weapon_key}",
        ] + ([f"materials/models/workshop_partner/weapons/c_models/{parent_key}"] if parent_key else []) + [
            f"materials/models/workshop/weapons/c_models/{weapon_key}",
        ] + ([f"materials/models/workshop/weapons/c_models/{parent_key}"] if parent_key else []) + [
            f"materials/models/weapons/c_models/{weapon_key}",
        ] + ([f"materials/models/weapons/c_models/{parent_key}"] if parent_key else []) + [
            f"materials/models/weapons/c_items/{weapon_key}",
            "materials/models/weapons/c_items",
            f"materials/models/weapons/v_{base_key}",
            f"materials/models/weapons/{weapon_key}",
        ]

        try:
            # ══════════════════════════════════════════════════════════════════
            # СПОСОБ 1: WEAPON_TEXTURE_PATHS — явный список файлов
            # ══════════════════════════════════════════════════════════════════
            if weapon_key in WEAPON_TEXTURE_PATHS:
                emit_progress(50, t.get('extract_extracting', 'Extracting texture...'))
                vpk_file = _open_vpk_cached(textures_vpk_path)
                extracted_paths: List[str] = []
                override_list = WEAPON_TEXTURE_PATHS[weapon_key]
                n = max(len(override_list), 1)
                for idx, vtf_rel_path in enumerate(override_list):
                    if is_cancelled():
                        _close(vpk_file)
                        return False, t.get('extract_cancelled', 'Extraction cancelled by user'), True
                    if vtf_rel_path not in vpk_file:
                        continue
                    vtf_filename = vtf_rel_path.split('/')[-1]
                    emit_progress(50 + int(idx / n * 40),
                                  t.get('extract_extracting', 'Extracting texture...') + f'  {vtf_filename}')
                    out = _extract_and_convert(vpk_file, vtf_rel_path, vtf_filename)
                    if out:
                        extracted_paths.append(out)
                _close(vpk_file)
                if extracted_paths:
                    return _finish(extracted_paths)
                # override не дал результата — идём дальше

            # ══════════════════════════════════════════════════════════════════
            # СПОСОБ 2: QC из кэша декомпиляции → $texturegroup (точная копия логики build)
            # Если пользователь ранее строил мод или смотрел 3D-превью —
            # кэш есть, и мы знаем РОВНО те же текстуры что заменит build.
            # ══════════════════════════════════════════════════════════════════
            emit_progress(25, t.get('extract_searching', 'Searching for texture...'))
            qc_texture_names: List[str] = []
            try:
                from src.services import decompile_cache
                from src.services.model_build_service import ModelBuildService
                qc_path = decompile_cache.find_cached_qc_for_weapon(weapon_key)
                if qc_path and os.path.exists(qc_path):
                    tg = ModelBuildService.extract_texturegroup_structure(qc_path)
                    red_row = tg.get('red_row', [])
                    blu_row = tg.get('blu_row', [])
                    # Объединяем red + blu, убираем дубли, сохраняем порядок
                    seen_names: set = set()
                    for name in red_row + blu_row:
                        if name and name not in seen_names:
                            seen_names.add(name)
                            qc_texture_names.append(name)
                    logger.info(f"[extract] QC кэш: {weapon_key} → текстуры: {qc_texture_names}")
            except Exception as _qc_err:
                logger.debug(f"[extract] QC кэш недоступен для {weapon_key}: {_qc_err}")

            if qc_texture_names:
                emit_progress(40, t.get('extract_extracting', 'Extracting texture...'))
                vpk_file = _open_vpk_cached(textures_vpk_path)
                extracted_paths = []
                n = max(len(qc_texture_names), 1)

                for idx, tex_name in enumerate(qc_texture_names):
                    if is_cancelled():
                        _close(vpk_file)
                        return False, t.get('extract_cancelled', 'Extraction cancelled by user'), True

                    vtf_filename = f"{tex_name}.vtf"
                    emit_progress(40 + int(idx / n * 50),
                                  t.get('extract_extracting', 'Extracting texture...') + f'  {vtf_filename}')

                    # Ищем файл по всем search_paths
                    found = False
                    for search_path in search_paths:
                        rel = f"{search_path}/{vtf_filename}"
                        if rel in vpk_file:
                            out = _extract_and_convert(vpk_file, rel, vtf_filename)
                            if out:
                                extracted_paths.append(out)
                            found = True
                            break
                    if not found:
                        logger.debug(f"[extract] VTF не найден в VPK: {vtf_filename}")

                _close(vpk_file)
                if extracted_paths:
                    return _finish(extracted_paths)
                # ни одной текстуры не нашли — идём к fallback

            # ══════════════════════════════════════════════════════════════════
            # СПОСОБ 3: Fallback — ищем только главный VTF по weapon_key
            # (кэша нет, пользователь ещё не строил мод для этого оружия)
            # ══════════════════════════════════════════════════════════════════
            emit_progress(50, t.get('extract_extracting', 'Extracting texture...'))
            vtf_candidates = [
                f"{weapon_key}.vtf",
                f"{weapon_key}_red.vtf",
                f"v_{base_key}.vtf",
            ]
            if not weapon_key.startswith('c_'):
                vtf_candidates.append(f"c_{weapon_key}.vtf")
            seen_c: set = set()
            vtf_candidates = [c for c in vtf_candidates if not (c in seen_c or seen_c.add(c))]

            vpk_file = _open_vpk_cached(textures_vpk_path)
            for search_path in search_paths:
                if is_cancelled():
                    _close(vpk_file)
                    return False, t.get('extract_cancelled', 'Extraction cancelled by user'), True
                for vtf_filename in vtf_candidates:
                    rel = f"{search_path}/{vtf_filename}"
                    if rel in vpk_file:
                        out = _extract_and_convert(vpk_file, rel, vtf_filename)
                        _close(vpk_file)
                        if out:
                            return _finish([out])
                        error_msg = t.get('texture_extract_failed',
                                          'Failed to extract texture for weapon: {weapon}').format(weapon=weapon_key)
                        emit_progress(0, t.get('extract_error', 'Extraction error'))
                        return False, error_msg, False

            _close(vpk_file)
            error_msg = t.get('texture_extract_failed',
                              'Failed to extract texture for weapon: {weapon}').format(weapon=weapon_key)
            emit_progress(0, t.get('extract_error', 'Extraction error'))
            return False, error_msg, False

        except Exception as e:
            logger.error(f"Ошибка при извлечении текстуры: {e}", exc_info=True)
            emit_progress(0, t.get('extract_critical_error', 'Critical error'))
            return False, str(e), False
    
    @staticmethod
    def extract_hand_textures_with_progress(
        textures_vpk_path: str,
        hand_textures: List[Tuple[str, str]],
        out_dir: str,
        export_format: str = "VTF",
        language: str = "en",
        progress_callback: Optional[Callable[[int, str], None]] = None,
        cancel_callback: Optional[Callable[[], bool]] = None,
        use_explicit_list: bool = False,
        misc_vpk_path: Optional[str] = None,
        arm_model_key: Optional[str] = None,
    ) -> Tuple[bool, str, bool]:
        """
        Извлекает текстуры персонажа из tf2_textures_dir.vpk.

        Два режима:
          • use_explicit_list=False (по умолч.) — сканирует папки, извлекает ВСЁ
            (используется для обычных рук, где нужны все текстуры из папки).
          • use_explicit_list=True — извлекает только файлы из списка hand_textures
            (используется для тел персонажей после диалога выбора).

        Args:
            textures_vpk_path:  Путь к tf2_textures_dir.vpk
            hand_textures:      Список (folder, vtf_name)
            out_dir:            Папка для экспорта
            export_format:      VTF / PNG / TGA / JPG
            language:           Язык сообщений
            progress_callback:  callback(pct, msg)
            cancel_callback:    callable → bool
            use_explicit_list:  True → извлекать только явно перечисленные файлы

        Returns:
            (success, message, cancelled)
        """
        import time
        t = TRANSLATIONS.get(language, TRANSLATIONS["en"])

        def emit(pct: int, msg: str) -> None:
            if progress_callback:
                progress_callback(pct, msg)

        def is_cancelled() -> bool:
            return bool(cancel_callback and cancel_callback())

        emit(10, t.get("extract_init", "Initializing extraction..."))
        time.sleep(0.05)

        if is_cancelled():
            return False, t.get("extract_cancelled", "Extraction cancelled by user"), True

        if not VPK_AVAILABLE:
            return False, t.get("vpk_library_not_available", "VPK library not available"), False

        emit(20, t.get("extract_checking", "Checking VPK file..."))

        if not os.path.exists(textures_vpk_path):
            return False, t.get("textures_vpk_not_found", "tf2_textures_dir.vpk not found"), False

        if is_cancelled():
            return False, t.get("extract_cancelled", "Extraction cancelled by user"), True

        ensure_directory_exists(out_dir)
        emit(30, t.get("extract_searching", "Searching for texture..."))

        try:
            vpk_file = _open_vpk_cached(textures_vpk_path)
        except Exception as exc:
            return False, str(exc), False
        if vpk_file is None:
            return False, t.get("textures_vpk_not_found", "tf2_textures_dir.vpk not found"), False

        emit(40, t.get("extract_searching", "Searching for texture..."))

        # all_vtfs stores (rel_path, filename, src_vpk_file)
        all_vtfs: List[Tuple[str, str, object]] = []

        # Открываем misc VPK если нужно (для шапок)
        misc_vpk_file = None
        if misc_vpk_path and os.path.exists(misc_vpk_path) and misc_vpk_path != textures_vpk_path:
            try:
                misc_vpk_file = _open_vpk_cached(misc_vpk_path)
            except Exception as _e:
                logger.warning(f"[extract] Не удалось открыть misc VPK {misc_vpk_path}: {_e}")

        # ── Попытка получить точный список текстур из QC кэша (как при сборке) ─ #
        # Если для данного arm_model_key есть декомпилированный QC, берём
        # red_row + blu_row из $texturegroup — точно те же текстуры, что создаёт
        # сборщик мода, а не потенциально неполный список из player_hands.py.
        if use_explicit_list and arm_model_key:
            try:
                from src.services import decompile_cache
                from src.services.model_build_service import ModelBuildService

                qc_path = decompile_cache.find_cached_qc_for_weapon(arm_model_key)
                if qc_path and os.path.exists(qc_path):
                    cdmaterials_raw = ModelBuildService.extract_cdmaterials_path_from_qc(qc_path)
                    tg = ModelBuildService.extract_texturegroup_structure(qc_path)
                    red_row = tg.get("red_row", [])
                    blu_row = tg.get("blu_row", [])

                    # Составляем de-duplicated список имён текстур
                    seen_names: set = set()
                    qc_tex_names: List[str] = []
                    for name in red_row + blu_row:
                        if name and name not in seen_names:
                            seen_names.add(name)
                            qc_tex_names.append(name)

                    if qc_tex_names and cdmaterials_raw:
                        # cdmaterials обычно выглядит как "models/player/scout" —
                        # берём последний компонент пути в качестве папки.
                        folder_from_qc = cdmaterials_raw.replace("\\", "/").rstrip("/").split("/")[-1]
                        if folder_from_qc:
                            hand_textures = [(folder_from_qc, name) for name in qc_tex_names]
                            logger.info(
                                f"[extract-hands] Используем QC кэш для {arm_model_key}: "
                                f"folder={folder_from_qc}, textures={qc_tex_names}"
                            )
            except Exception as _qc_err:
                logger.debug(f"[extract-hands] QC кэш недоступен для {arm_model_key}: {_qc_err}")

        if use_explicit_list:
            # ── Режим явного списка: ищем в нескольких путях и VPK ───────── #
            # Порядок поиска: textures VPK → misc VPK; prefixes: player → workshop_partner → workshop
            _PLAYER_PREFIXES = [
                "materials/models/player",
                "materials/models/workshop_partner/player",
                "materials/models/workshop/player",
            ]
            _vpk_sources = [vpk_file]
            if misc_vpk_file is not None:
                _vpk_sources.append(misc_vpk_file)

            for folder, vtf_name in hand_textures:
                filename = f"{vtf_name}.vtf"
                found = False
                for src_vpk in _vpk_sources:
                    for prefix in _PLAYER_PREFIXES:
                        rel_path = f"{prefix}/{folder}/{vtf_name}.vtf"
                        if rel_path in src_vpk:
                            all_vtfs.append((rel_path, filename, src_vpk))
                            found = True
                            break
                    if found:
                        break
                if not found:
                    logger.warning(
                        f"[extract] Не найдена в VPK: {folder}/{vtf_name}.vtf "
                        f"(проверено {len(_PLAYER_PREFIXES)} префиксов в {len(_vpk_sources)} VPK)"
                    )
        else:
            # ── Режим сканирования папок: извлекаем всё из папок ─────────── #
            seen_folders: set = set()
            player_dirs: List[str] = []
            for folder, _vtf_name in hand_textures:
                vpk_dir = f"materials/models/player/{folder}"
                if vpk_dir not in seen_folders:
                    seen_folders.add(vpk_dir)
                    player_dirs.append(vpk_dir)

            seen_files: set = set()
            for vpk_dir in player_dirs:
                dir_vtfs = TF2VPKExtractService._scan_dir_for_vtf(vpk_file, vpk_dir)
                for rel_path, filename in dir_vtfs:
                    if filename not in seen_files:
                        seen_files.add(filename)
                        all_vtfs.append((rel_path, filename, vpk_file))

        # VPK (textures + misc) кэшируются (_open_vpk_cached) — общие хэндлы не
        # закрываем: их переиспользуют последующие вызовы.
        if not all_vtfs:
            _weapon_name = hand_textures[0][1] if hand_textures else "unknown"
            return (
                False,
                t.get("texture_extract_failed", "Failed to extract texture for weapon: {weapon}").format(weapon=_weapon_name),
                False,
            )

        # ── Извлекаем и конвертируем все найденные файлы ─────────────────── #
        extracted_paths: List[str] = []
        n = max(len(all_vtfs), 1)

        try:
            for idx, (rel_path, filename, src_vpk) in enumerate(all_vtfs):
                if is_cancelled():
                    return False, t.get("extract_cancelled", "Extraction cancelled by user"), True

                pct = 50 + int(idx / n * 40)
                emit(pct, t.get("extract_extracting", "Extracting texture...") + f"  {filename}")

                try:
                    dest_path = sanitize_path(filename, out_dir)
                except ValueError as exc:
                    logger.warning(f"Недопустимый путь для {filename}: {exc}")
                    continue

                try:
                    with open(dest_path, "wb") as fh:
                        fh.write(src_vpk[rel_path].read())
                    logger.info(f"Извлечена текстура рук: {rel_path} → {dest_path}")
                except Exception as exc:
                    logger.warning(f"Ошибка записи {dest_path}: {exc}")
                    continue

                if export_format.upper() != "VTF":
                    emit(pct + 1, t.get("extract_converting", "Converting texture..."))
                    converted = TF2VPKExtractService._convert_vtf_to_image(
                        dest_path, out_dir, export_format.upper()
                    )
                    if converted:
                        try:
                            os.remove(dest_path)
                        except Exception:
                            pass
                        extracted_paths.append(converted)
                    else:
                        extracted_paths.append(dest_path)
                else:
                    extracted_paths.append(dest_path)
        finally:
            # VPK кэшируются (_open_vpk_cached) — общие хэндлы не закрываем.
            pass

        if not extracted_paths:
            _weapon_name2 = hand_textures[0][1] if hand_textures else "unknown"
            return (
                False,
                t.get("texture_extract_failed", "Failed to extract texture for weapon: {weapon}").format(weapon=_weapon_name2),
                False,
            )

        emit(100, t.get("extract_completed", "Extraction completed"))

        if len(extracted_paths) == 1:
            success_msg = t.get(
                "texture_extracted_success", "Texture extracted successfully: {path}"
            ).format(path=extracted_paths[0])
        else:
            paths_str = "\n".join(extracted_paths)
            success_msg = t.get(
                "texture_extracted_success", "Texture extracted successfully: {path}"
            ).format(path=paths_str)

        return True, success_msg, False

    @staticmethod
    def _convert_vtf_to_image(vtf_path: str, out_dir: str, image_format: str) -> Optional[str]:
        """
        Конвертирует VTF файл в изображение (PNG, TGA, JPG) используя библиотеку vtf2img
        
        Args:
            vtf_path: Путь к VTF файлу
            out_dir: Директория для сохранения
            image_format: Формат изображения (PNG, TGA, JPG)
            
        Returns:
            Путь к конвертированному файлу или None если ошибка
        """
        try:
            # Пробуем использовать библиотеку vtf2img для конвертации
            try:
                from vtf2img import Parser
            except ImportError:
                logger.warning("Библиотека vtf2img не установлена.")
                logger.info("Установите её через: .venv\\Scripts\\python.exe -m pip install vtf2img")
                logger.info("Или активируйте .venv и выполните: pip install vtf2img")
                return None
            
            # Формируем имя выходного файла
            vtf_basename = os.path.splitext(os.path.basename(vtf_path))[0]
            format_mapping = {
                "PNG": "png",
                "TGA": "tga",
                "JPG": "jpg",
                "JPEG": "jpg"
            }
            ext = format_mapping.get(image_format.upper(), "png")
            output_filename = f"{vtf_basename}.{ext}"
            output_path = os.path.join(out_dir, output_filename)
            
            # Открываем VTF файл
            parser = Parser(vtf_path)
            
            # Получаем изображение (vtf2img возвращает PIL Image напрямую)
            image = parser.get_image()
            
            # Логируем информацию об изображении для диагностики
            logger.debug(f"Изображение из VTF: mode={image.mode}, size={image.size}")
            
            # Конвертируем изображение в RGB
            # Используем стандартную конвертацию PIL, которая правильно обрабатывает альфа-канал
            if image.mode != "RGB":
                # PIL автоматически смешивает альфа-канал с черным фоном при convert("RGB")
                # Для текстуры игры нужен черный фон, а не белый
                image = image.convert("RGB")
            
            # Сохраняем изображение в нужном формате
            if image_format.upper() == "JPG" or image_format.upper() == "JPEG":
                image.save(output_path, "JPEG", quality=95)
            elif image_format.upper() == "TGA":
                image.save(output_path, "TGA")
            else:  # PNG по умолчанию
                image.save(output_path, "PNG")
            
            logger.info(f"Текстура конвертирована: {vtf_path} -> {output_path}")
            return output_path
                
        except Exception as e:
            logger.error(f"Ошибка при конвертации VTF в {image_format}: {e}", exc_info=True)
            return None
