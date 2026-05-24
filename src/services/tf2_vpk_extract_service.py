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


class TF2VPKExtractService:
    """Сервис для работы с извлечением файлов из TF2 VPK"""
    
    @staticmethod
    def find_tf2_misc_dir_vpk(vpk_folder: str) -> Optional[str]:
        """
        Находит tf2_misc_dir.vpk в указанной папке (fallback метод)
        
        Args:
            vpk_folder: Путь к папке с VPK файлами
            
        Returns:
            Путь к tf2_misc_dir.vpk или None если не найден
        """
        if not os.path.exists(vpk_folder):
            return None
        
        # Сначала ищем в корне папки
        target_name = "tf2_misc_dir.vpk"
        root_path = os.path.join(vpk_folder, target_name)
        if os.path.exists(root_path):
            return root_path
        
        # Если не нашли в корне, ищем рекурсивно
        for root, dirs, files in os.walk(vpk_folder):
            if target_name in files:
                return os.path.join(root, target_name)
        
        return None
    
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
        
        # Открываем VPK файл если не передан
        should_close = False
        if vpk_file is None:
            try:
                vpk_file = vpk.open(dir_vpk_path)
                should_close = True
            except Exception as e:
                logger.warning(f"Не удалось открыть VPK файл для проверки: {e}", exc_info=True)
                return False
        
        try:
            # Проверяем существование файла в VPK (быстрая операция)
            exists = normalized_path in vpk_file
            return exists
        finally:
            # Закрываем VPK файл только если мы его открыли
            if should_close and hasattr(vpk_file, 'close'):
                try:
                    vpk_file.close()
                except:
                    pass
    
    @staticmethod
    def extract_file_set(
        dir_vpk_path: str,
        mdl_rel_path: str,
        out_dir: str,
        vpk_exe_path: str = None  # Не используется, оставлен для совместимости
    ) -> List[str]:
        """
        Извлекает набор файлов модели из VPK (.mdl и связанные файлы)
        ОПТИМИЗИРОВАНО: Извлекает только после подтверждения существования MDL
        
        Args:
            dir_vpk_path: Путь к tf2_misc_dir.vpk
            mdl_rel_path: Относительный путь к .mdl файлу внутри VPK
            out_dir: Директория для извлечения
            vpk_exe_path: Не используется (оставлен для совместимости)
            
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
        
        # Открываем VPK файл один раз для всех извлечений
        try:
            vpk_file = vpk.open(dir_vpk_path)
        except Exception as e:
            raise RuntimeError(f"Не удалось открыть VPK файл {dir_vpk_path}: {e}")
        
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
                    error_msg += f"Проверьте, что путь правильный и файл существует в VPK.\n"
                    error_msg += f"VPK файл: {dir_vpk_path}\n"
                    error_msg += f"Ожидаемый путь в VPK: {mdl_rel_path}\n"
                    error_msg += f"Директория извлечения: {out_dir}\n"
                    error_msg += f"Попробуйте проверить содержимое VPK через GCFScape.\n"
                    error_msg += f"Если библиотека vpk не установлена, установите её: pip install vpk"
                    raise RuntimeError(error_msg)
                
                # Используем найденный файл
                extracted_files.append(found_mdl)
            
            return extracted_files
        
        finally:
            # Закрываем VPK файл
            if hasattr(vpk_file, 'close'):
                try:
                    vpk_file.close()
                except:
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
            vpk_file = vpk.open(dir_vpk_path)
            
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
                    # Закрываем VPK файл если есть метод close
                    if hasattr(vpk_file, 'close'):
                        try:
                            vpk_file.close()
                        except:
                            pass
                    return extracted_file_path
            
            # Закрываем VPK файл если не нашли файл
            if hasattr(vpk_file, 'close'):
                try:
                    vpk_file.close()
                except:
                    pass
            
        except Exception as e:
            logger.warning(f"Ошибка при извлечении VMT файла: {e}", exc_info=True)
            return None
        
        logger.warning(f"VMT файл не найден по пути: {vmt_rel_path}")
        return None
    
    @staticmethod
    def extract_texture(
        textures_vpk_path: str,
        weapon_key: str,
        out_dir: str,
        export_format: str = "VTF"
    ) -> Optional[str]:
        """
        Извлекает оригинальную текстуру (VTF файл) оружия из tf2_textures_dir.vpk
        и конвертирует в выбранный формат изображения (PNG, TGA, JPG)
        
        Пути поиска в порядке приоритета:
        1. materials/models/workshop_partner/weapons/c_models/{weapon_key}/
        2. materials/models/workshop/weapons/c_models/{weapon_key}/
        3. materials/models/weapons/c_models/{weapon_key}/
        4. materials/models/weapons/c_items/{weapon_key}/
        
        Args:
            textures_vpk_path: Путь к tf2_textures_dir.vpk
            weapon_key: Ключ оружия (например, c_scattergun)
            out_dir: Директория для извлечения
            export_format: Формат экспорта (VTF, PNG, TGA, JPG)
            
        Returns:
            Путь к извлеченному/конвертированному файлу или None если не найден
        """
        if not VPK_AVAILABLE:
            logger.warning("Библиотека vpk не установлена. Текстура не будет извлечена.")
            return None
        
        if not os.path.exists(textures_vpk_path):
            logger.warning(f"VPK файл не найден: {textures_vpk_path}")
            return None
        
        ensure_directory_exists(out_dir)

        # ── Явные переопределения (нестандартные имена/папки) ────────────────
        if weapon_key in WEAPON_TEXTURE_PATHS:
            try:
                vpk_file = vpk.open(textures_vpk_path)
                for vtf_rel_path in WEAPON_TEXTURE_PATHS[weapon_key]:
                    if vtf_rel_path in vpk_file:
                        vtf_filename = vtf_rel_path.split('/')[-1]
                        try:
                            extracted_file_path = sanitize_path(vtf_filename, out_dir)
                        except ValueError:
                            continue
                        with open(extracted_file_path, 'wb') as f:
                            f.write(vpk_file[vtf_rel_path].read())
                        if hasattr(vpk_file, 'close'):
                            try:
                                vpk_file.close()
                            except Exception:
                                pass
                        logger.info(f"Извлечена текстура (override): {vtf_rel_path}")
                        if export_format.upper() != "VTF":
                            converted = TF2VPKExtractService._convert_vtf_to_image(
                                extracted_file_path, out_dir, export_format.upper()
                            )
                            if converted:
                                try:
                                    os.remove(extracted_file_path)
                                except Exception:
                                    pass
                                return converted
                        return extracted_file_path
                if hasattr(vpk_file, 'close'):
                    try:
                        vpk_file.close()
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"Ошибка при поиске override-текстуры для {weapon_key}: {e}")

        # ── Производные имена ────────────────────────────────────────────────
        # base_key: weapon_key без префикса c_  (c_bat → bat, w_sd_sapper → w_sd_sapper)
        base_key = weapon_key[2:] if weapon_key.startswith('c_') else weapon_key

        # parent_key: для составных ключей убираем последний суффикс через _
        # c_minigun_natascha → c_minigun,  c_axtinguisher_pyro → c_axtinguisher
        _parts = base_key.rsplit('_', 1)
        parent_key = ('c_' + _parts[0]) if len(_parts) == 2 else None

        # ── Пути поиска (приоритет: workshop_partner → workshop → weapons) ───
        search_paths = [
            # workshop_partner — высший приоритет
            f"materials/models/workshop_partner/weapons/c_models/{weapon_key}",
        ] + ([f"materials/models/workshop_partner/weapons/c_models/{parent_key}"] if parent_key else []) + [
            # workshop
            f"materials/models/workshop/weapons/c_models/{weapon_key}",
        ] + ([f"materials/models/workshop/weapons/c_models/{parent_key}"] if parent_key else []) + [
            # weapons — базовые пути
            f"materials/models/weapons/c_models/{weapon_key}",
        ] + ([f"materials/models/weapons/c_models/{parent_key}"] if parent_key else []) + [
            f"materials/models/weapons/c_items/{weapon_key}",
            "materials/models/weapons/c_items",     # плоский: c_items/c_shovel.vtf
            f"materials/models/weapons/v_{base_key}",  # старый v_-viewmodel
            f"materials/models/weapons/{weapon_key}",  # w_-world-model
        ]

        # ── Возможные имена VTF файлов ────────────────────────────────────────
        vtf_candidates = [
            f"{weapon_key}.vtf",
            # Командные варианты: c_bonk_bat_red.vtf / c_bonk_bat_blue.vtf
            f"{weapon_key}_red.vtf",
            f"{weapon_key}_blue.vtf",
            # Старый v_-viewmodel: v_bat.vtf для c_bat
            f"v_{base_key}.vtf",
        ]
        if not weapon_key.startswith('c_'):
            vtf_candidates.append(f"c_{weapon_key}.vtf")
        # Убираем дубли, сохраняя порядок
        seen_cand: set = set()
        vtf_candidates = [c for c in vtf_candidates if not (c in seen_cand or seen_cand.add(c))]
        
        try:
            vpk_file = vpk.open(textures_vpk_path)

            # Пробуем найти VTF файл по каждому пути
            for search_path in search_paths:
                for vtf_filename in vtf_candidates:
                    vtf_rel_path = f"{search_path}/{vtf_filename}"

                    # Проверяем, существует ли файл в VPK
                    if vtf_rel_path in vpk_file:
                        vpk_entry = vpk_file[vtf_rel_path]

                        # Определяем путь для сохранения VTF
                        try:
                            extracted_file_path = sanitize_path(vtf_filename, out_dir)
                        except ValueError as e:
                            logger.warning(f"Недопустимый путь для сохранения VTF: {vtf_filename}: {e}")
                            return None

                        # Извлекаем файл
                        with open(extracted_file_path, 'wb') as f:
                            f.write(vpk_entry.read())

                        logger.info(f"Извлечена текстура: {vtf_rel_path} -> {extracted_file_path}")
                        # Закрываем VPK файл если есть метод close
                        if hasattr(vpk_file, 'close'):
                            try:
                                vpk_file.close()
                            except:
                                pass

                        # Конвертируем VTF в выбранный формат, если нужно
                        if export_format.upper() != "VTF":
                            converted_path = TF2VPKExtractService._convert_vtf_to_image(
                                extracted_file_path,
                                out_dir,
                                export_format.upper()
                            )
                            if converted_path:
                                # Удаляем временный VTF файл
                                try:
                                    os.remove(extracted_file_path)
                                except:
                                    pass
                                return converted_path

                        return extracted_file_path

            # Закрываем VPK файл если есть метод close
            if hasattr(vpk_file, 'close'):
                try:
                    vpk_file.close()
                except:
                    pass
            logger.warning(f"Текстура не найдена для оружия {weapon_key}")
            return None

        except Exception as e:
            logger.error(f"Ошибка при извлечении текстуры: {e}", exc_info=True)
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
        t = TRANSLATIONS.get(language, TRANSLATIONS['en'])

        def emit_progress(value: int, message: str) -> None:
            if progress_callback:
                progress_callback(value, message)

        def is_cancelled() -> bool:
            return bool(cancel_callback and cancel_callback())

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
        emit_progress(30, t.get('extract_searching', 'Searching for texture...'))
        time.sleep(0.1)

        search_paths = [
            f"materials/models/workshop_partner/weapons/c_models/{weapon_key}",
            f"materials/models/workshop/weapons/c_models/{weapon_key}",
            f"materials/models/weapons/c_models/{weapon_key}",
            f"materials/models/weapons/c_items/{weapon_key}",
        ]

        vtf_candidates = [
            f"{weapon_key}.vtf",
            f"c_{weapon_key}.vtf" if not weapon_key.startswith('c_') else None,
        ]
        vtf_candidates = [name for name in vtf_candidates if name]

        try:
            emit_progress(50, t.get('extract_extracting', 'Extracting texture...'))
            vpk_file = vpk.open(textures_vpk_path)

            for search_path in search_paths:
                if is_cancelled():
                    if hasattr(vpk_file, 'close'):
                        try:
                            vpk_file.close()
                        except:
                            pass
                    return False, t.get('extract_cancelled', 'Extraction cancelled by user'), True
                for vtf_filename in vtf_candidates:
                    if is_cancelled():
                        if hasattr(vpk_file, 'close'):
                            try:
                                vpk_file.close()
                            except:
                                pass
                        return False, t.get('extract_cancelled', 'Extraction cancelled by user'), True
                    vtf_rel_path = f"{search_path}/{vtf_filename}"
                    if vtf_rel_path in vpk_file:
                        vpk_entry = vpk_file[vtf_rel_path]
                        try:
                            extracted_file_path = sanitize_path(vtf_filename, out_dir)
                        except ValueError as e:
                            logger.warning(f"Недопустимый путь для сохранения VTF: {vtf_filename}: {e}")
                            return False, t.get('extract_error', 'Extraction error'), False
                        with open(extracted_file_path, 'wb') as f:
                            f.write(vpk_entry.read())

                        if hasattr(vpk_file, 'close'):
                            try:
                                vpk_file.close()
                            except:
                                pass

                        if export_format.upper() != "VTF":
                            emit_progress(80, t.get('extract_converting', 'Converting texture...'))
                            time.sleep(0.1)
                            converted_path = TF2VPKExtractService._convert_vtf_to_image(
                                extracted_file_path,
                                out_dir,
                                export_format.upper()
                            )
                            if converted_path:
                                try:
                                    os.remove(extracted_file_path)
                                except:
                                    pass
                                success_msg = t.get('texture_extracted_success', 'Texture extracted successfully: {path}').format(path=converted_path)
                                emit_progress(100, t.get('extract_completed', 'Extraction completed'))
                                return True, success_msg, False
                            error_msg = t.get('texture_extract_failed', 'Failed to extract texture').format(weapon=weapon_key)
                            emit_progress(0, t.get('extract_error', 'Extraction error'))
                            return False, error_msg, False

                        success_msg = t.get('texture_extracted_success', 'Texture extracted successfully: {path}').format(path=extracted_file_path)
                        emit_progress(100, t.get('extract_completed', 'Extraction completed'))
                        return True, success_msg, False

            if hasattr(vpk_file, 'close'):
                try:
                    vpk_file.close()
                except:
                    pass

            error_msg = t.get('texture_extract_failed', 'Failed to extract texture').format(weapon=weapon_key)
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
            vpk_file = vpk.open(textures_vpk_path)
        except Exception as exc:
            return False, str(exc), False

        emit(40, t.get("extract_searching", "Searching for texture..."))
        all_vtfs: List[Tuple[str, str]] = []  # (rel_path, filename)

        if use_explicit_list:
            # ── Режим явного списка: извлекаем только выбранные файлы ────── #
            for folder, vtf_name in hand_textures:
                rel_path = f"materials/models/player/{folder}/{vtf_name}.vtf"
                filename  = f"{vtf_name}.vtf"
                if rel_path in vpk_file:
                    all_vtfs.append((rel_path, filename))
                else:
                    logger.warning(f"[extract] Не найдена в VPK: {rel_path}")
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
                        all_vtfs.append((rel_path, filename))

        if not all_vtfs:
            if hasattr(vpk_file, "close"):
                try:
                    vpk_file.close()
                except Exception:
                    pass
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
            for idx, (rel_path, filename) in enumerate(all_vtfs):
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
                        fh.write(vpk_file[rel_path].read())
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
            if hasattr(vpk_file, "close"):
                try:
                    vpk_file.close()
                except Exception:
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
            from PIL import Image
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
