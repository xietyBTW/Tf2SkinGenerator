"""
Сервис для извлечения моделей из TF2 VPK файлов
"""

import os
from pathlib import Path
from typing import List, Optional
from src.shared.logging_config import get_logger
from src.shared.file_utils import ensure_directory_exists

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
                    extracted_file_path = os.path.join(out_dir, file_path.replace("/", os.sep))
                    extracted_file_dir = os.path.dirname(extracted_file_path)
                    
                    # Создаем директорию если нужно
                    if extracted_file_dir:
                        os.makedirs(extracted_file_dir, exist_ok=True)
                    
                    # Извлекаем файл
                    with open(extracted_file_path, 'wb') as f:
                        f.write(vpk_entry.read())
                    
                    extracted_files.append(extracted_file_path)
                    logger.info(f"Извлечен файл: {file_path} -> {extracted_file_path}")
                
                except Exception as e:
                    # Для .phy ошибка допустима
                    if not file_path.endswith(".phy"):
                        logger.warning(f"Ошибка при извлечении {file_path}: {e}", exc_info=True)
            
            # Проверяем, что .mdl был извлечен (обязательный файл)
            mdl_extracted = os.path.join(out_dir, mdl_rel_path.replace("/", os.sep))
            if not os.path.exists(mdl_extracted):
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
        
        # Пути поиска в порядке приоритета
        search_paths = [
            f"materials/models/workshop_partner/weapons/c_models/{weapon_key}",
            f"materials/models/workshop/weapons/c_models/{weapon_key}",
            f"materials/models/weapons/c_models/{weapon_key}",
            f"materials/models/weapons/c_items/{weapon_key}",
        ]
        
        # Возможные имена VTF файлов
        vtf_candidates = [
            f"{weapon_key}.vtf",
            f"c_{weapon_key}.vtf" if not weapon_key.startswith('c_') else None,
        ]
        # Убираем None значения
        vtf_candidates = [name for name in vtf_candidates if name]
        
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
                        extracted_file_path = os.path.join(out_dir, vtf_filename)
                        
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