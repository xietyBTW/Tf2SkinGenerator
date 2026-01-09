"""
Сервис для извлечения моделей из TF2 VPK файлов
"""

import os
from typing import List, Optional

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
                print(f"Предупреждение: Не удалось открыть VPK файл для проверки: {e}")
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
                            print(f"Предупреждение: Файл {normalized_path} не найден в VPK")
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
                    print(f"Извлечен файл: {file_path} -> {extracted_file_path}")
                
                except Exception as e:
                    # Для .phy ошибка допустима
                    if not file_path.endswith(".phy"):
                        print(f"Предупреждение: Ошибка при извлечении {file_path}: {e}")
            
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
            print("Предупреждение: Библиотека vpk не установлена. VMT файл не будет извлечен.")
            return None
        
        if not os.path.exists(dir_vpk_path):
            print(f"Предупреждение: VPK файл не найден: {dir_vpk_path}")
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
        vmt_rel_path = f"{normalized_cdmaterials}/{vmt_filename}" if normalized_cdmaterials else vmt_filename
        
        # Пробуем найти VMT файл в tf2_textures_dir.vpk (обычно текстуры там)
        # Но сначала проверяем tf2_misc_dir.vpk
        try:
            vpk_file = vpk.open(dir_vpk_path)
            
            # Проверяем, существует ли файл в VPK
            if vmt_rel_path in vpk_file:
                vpk_entry = vpk_file[vmt_rel_path]
                
                # Определяем путь для сохранения
                extracted_file_path = os.path.join(out_dir, vmt_filename)
                
                # Извлекаем файл
                with open(extracted_file_path, 'wb') as f:
                    f.write(vpk_entry.read())
                
                print(f"Извлечен VMT файл: {vmt_rel_path} -> {extracted_file_path}")
                return extracted_file_path
            
            # Если не нашли по полному пути, пробуем найти в materials/
            materials_vmt_path = f"materials/{vmt_rel_path}"
            if materials_vmt_path in vpk_file:
                vpk_entry = vpk_file[materials_vmt_path]
                
                extracted_file_path = os.path.join(out_dir, vmt_filename)
                with open(extracted_file_path, 'wb') as f:
                    f.write(vpk_entry.read())
                
                print(f"Извлечен VMT файл: {materials_vmt_path} -> {extracted_file_path}")
                return extracted_file_path
            
        except Exception as e:
            print(f"Предупреждение: Ошибка при извлечении VMT файла: {e}")
            return None
        
        print(f"Предупреждение: VMT файл не найден по пути: {vmt_rel_path}")
        return None