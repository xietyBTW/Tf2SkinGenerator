"""
Сервис для работы с пользовательскими VPK модами.
Позволяет загрузить готовый VPK мод, заменить в нём текстуры и пересобрать.
Обнаружение текстур происходит через сканирование VTF файлов (discover_textures)
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
    """Сервис для редактирования и пересборки пользовательских VPK модов"""

    # Извлечение

    @staticmethod
    def extract_vpk_to_dir(vpk_path: str, output_dir: str) -> bool:
        """
        Распаковывает VPK файл в указанную директорию

        Порядок попыток:
          1. vpk.exe x <file>     - официальный инструмент Valve (самый надёжный)
          2. Python-библиотека vpk - резервный метод
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Попытка 1: vpk.exe x
        if CustomVPKService._extract_via_vpk_exe(vpk_path, str(output_path)):
            return True

        logger.warning("vpk.exe недоступен или не смог распаковать - пробуем Python-библиотеку vpk")

        # Попытка 2: Python-библиотека vpk
        return CustomVPKService._extract_via_python_vpk(vpk_path, str(output_path))

    @staticmethod
    def _extract_via_vpk_exe(vpk_path: str, output_dir: str) -> bool:
        """Распаковка через tools/VPK/vpk.exe с ключом 'x'"""
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
        """Распаковка через Python-библиотеку vpk (резервный метод)"""
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

    @classmethod
    def discover_textures(cls, extract_dir: str) -> List[Dict]:
        """
        Перечисляет ОСНОВНЫЕ текстуры мода по самим VTF-файлам (надёжно: не зависит
        от того, насколько корректны/полны VMT). Основная или служебная - правило
        mod_textures (сначала VMT мода, потом имя), то же, что у карточек превью

        Каждый элемент:
            name        - уникальный ключ карточки/сборки
            vtf_name    - реальное имя VTF-файла без расширения
            vtf_path    - путь к VTF
            vmt_path    - путь к VMT, чей $basetexture смотрит на VTF, иначе
                          VMT с тем же стеблем (или None)
            vmt_dir     - папка, куда класть заменённый VTF
            is_blue     - VTF-стебель оканчивается на _blue
            rel_dir     - папка VTF относительно extract_dir (для дизамбигуации)
        """
        from src.services import vmt_parse
        from src.services.mod_textures import is_base_vtf, texture_key, vmt_references

        extract_path = Path(extract_dir)
        all_files = [f for f in extract_path.rglob('*') if f.is_file()]
        vtf_files = [f for f in all_files if f.suffix.lower() == '.vtf']
        vmt_files = [f for f in all_files if f.suffix.lower() == '.vmt']

        def rel(p: Path) -> str:
            return p.relative_to(extract_path).as_posix()

        texts = {}
        for vf in vmt_files:
            try:
                texts[vf] = vf.read_text(encoding='utf-8', errors='replace')
            except OSError:
                continue
        refs = vmt_references(texts.values())
        vmt_by_stem: Dict[str, str] = {}
        vmt_by_base: Dict[str, str] = {}
        for vf in vmt_files:
            vmt_by_stem.setdefault(vf.stem.lower(), str(vf))
            base = vmt_parse.parse(texts.get(vf, '')).path('$basetexture')
            if base:
                vmt_by_base.setdefault(texture_key(base), str(vf))

        entries: List[Dict] = []
        for vtf in sorted(vtf_files):
            if not is_base_vtf(rel(vtf), refs):
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
                'vmt_path': (vmt_by_base.get(texture_key(rel(vtf)))
                             or vmt_by_stem.get(stem.lower())),
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
        """Делает поле 'name' уникальным в пределах списка (in-place)

        Имена не конфликтуют -> не трогаем (обратная совместимость). При коллизии
        к имени добавляется последний сегмент папки, затем - индекс, пока не
        станет уникальным
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

    # Основной пайплайн сборки

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
        decor_builds: Optional[list] = None,
        tf2_root_dir: Optional[str] = None,
        bypass_method: str = "console",
        material_maps: Optional[Dict] = None,
        material_settings: Optional[Dict] = None,
    ) -> Tuple[bool, str]:
        """
        Полный пайплайн редактирования кастомного мода:

        1. Распаковать исходный VPK
        2. Сканировать VMT -> найти все текстуры (RED + BLU)
        3. Первую RED текстуру -> заменить из image_path (или custom_vtf_path)
        4. Остальные -> запросить через extra_texture_callback; если отказ - оставить оригинал
        4б. Рельеф (Normal Map), карты материала и анимация - в VMT мода
        5. Правленые гирлянды (decor_builds) - своими моделями поверх
        6. Перепаковать в VPK и скопировать в export_folder

        material_maps / material_settings - по именам карточек (= имена
        текстур мода), как у модельной сборки
        """
        from src.services.texture_service import TextureService
        from src.shared.file_utils import copy_file_safe
        from src.data.translations import TRANSLATIONS

        t = TRANSLATIONS.get(language, TRANSLATIONS['en'])

        def emit(pct: int, label: str) -> None:
            if sub_progress_callback:
                sub_progress_callback(pct, label)

        # Временная директория - называем "vpkroot" чтобы vpk.exe создал "vpkroot.vpk"
        temp_root = Path(tempfile.mkdtemp(prefix="tf2sg_custom_"))
        vpkroot_dir = temp_root / "vpkroot"

        try:
            # 1. Извлечение
            emit(-1, "Extracting VPK..." if language == "en" else "Распаковка VPK...")
            if not CustomVPKService.extract_vpk_to_dir(custom_vpk_source_path, str(vpkroot_dir)):
                return False, (
                    "Failed to extract VPK. Make sure the file is a valid single-file VPK mod."
                    if language == "en" else
                    "Не удалось распаковать VPK. Убедитесь, что это корректный однофайловый VPK мод."
                )

            # 2. Обнаружение текстур
            # По самим VTF-файлам (как и 2D-карточки) - чтобы замена на любой
            # карточке (включая стили) применилась, имена совпадают с карточками
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

            # Правки VMT из редактора - до рельефа и карт: те дописываются
            # уже в правленый VMT, как у модельной сборки
            CustomVPKService._apply_vmt_edits(custom_vpk_source_path, all_textures)

            # 3. Подготовка конвертера
            # Настройки материала (свои поверх общих) - как у модельной сборки:
            # с одними общими мод собрался бы молча без рельефа и карт
            from src.data.texture_overrides import effective_settings, own_settings
            global_tex = {'size': size, 'format': format_type,
                          'flags': flags or [], 'options': vtf_options or {}}

            def _settings(tex: Dict):
                e = effective_settings(global_tex, own_settings(material_settings, tex['name']))
                return tuple(e['size']), e['format'], list(e['flags'] or []), dict(e['options'] or {})

            # Что сделала замена: {name: (картинка, fps, есть ли нормаль)}
            replaced: Dict[str, Tuple[str, Optional[float], bool]] = {}

            def _stock(tex: Dict):
                # Родную нормаль мода читаем ДО рендера всех текстур: наша
                # ляжет под тем же именем, а у красной и синей она бывает общей
                if custom_vtf_path and tex is all_textures[0]:
                    return None
                return (CustomVPKService._mod_normal(tex, vpkroot_dir)
                        if _settings(tex)[3].get('normal') else None)

            def _replace(src_img: str, tex: Dict, stock) -> bool:
                """Конвертирует src_img в VTF и заменяет VTF-файл текстуры"""
                vmt_dir = Path(tex['vmt_dir'])
                # Имя файла - реальное имя VTF, а не уникализированный ключ карточки
                # ('name' может содержать дискриминатор папки при коллизии стилей)
                tex_name = tex.get('vtf_name') or tex['name']

                # Если VTF уже существует - кладём рядом с ним;
                # иначе кладём рядом с VMT (стандартное место для TF2 модов)
                if tex.get('vtf_path'):
                    vtf_dest = Path(tex['vtf_path'])
                else:
                    vtf_dest = vmt_dir / f"{tex_name}.vtf"

                vtf_dest.parent.mkdir(parents=True, exist_ok=True)
                tex_size, tex_format, tex_flags, tex_opts = _settings(tex)

                try:
                    if custom_vtf_path and tex is all_textures[0]:
                        # Первая текстура + пользователь загрузил готовый VTF - копируем напрямую
                        copy_file_safe(custom_vtf_path, str(vtf_dest))
                        fps, is_normal = None, False
                    else:
                        fps, is_normal = TextureService.render_image_to_vtf(
                            src_img, vtf_dest.parent, vtf_dest,
                            vtf_dest.parent / f"{tex_name}.png", tex_name,
                            tex_size, tex_format, tex_flags, tex_opts, stock)
                    replaced[tex['name']] = (src_img, fps, is_normal)
                    logger.info(f"Текстура заменена: {vtf_dest}")
                    return True
                except Exception as e:
                    logger.error(f"Ошибка замены {tex_name}: {e}", exc_info=True)
                    return False

            # 4. Замена текстур
            from src.shared.constants import EXTRA_TEX_USE_GAME_ORIGINAL

            # Первая (главная) текстура - из image_path пользователя (классический
            # путь). Если image_path не задан (режим 2D-карточек) - главную
            # текстуру тоже спрашиваем через callback, как и остальные
            first = all_textures[0]
            todo = []   # (картинка, текстура, родная нормаль)
            if image_path and os.path.isfile(image_path):
                todo.append((image_path, first, _stock(first)))
                remaining = all_textures[1:]
            else:
                remaining = all_textures

            # Остальные текстуры - спрашиваем последовательно через callback
            for tex in remaining:
                user_img = extra_texture_callback(tex['name'], "custom") if extra_texture_callback else None
                # «Использовать обычную» - оставляем оригинальный VTF без изменений
                if user_img == EXTRA_TEX_USE_GAME_ORIGINAL:
                    logger.info(f"Custom VPK: пропускаем текстуру (использовать из мода): {tex['name']}")
                    continue
                if user_img and os.path.isfile(user_img):
                    todo.append((user_img, tex, _stock(tex)))
                # Если пользователь не выбрал - оригинальный VTF остаётся без изменений

            # Текстуры независимы, а сжатие отпускает GIL: жмём одновременно
            if todo:
                names = ", ".join(tex['name'] for _, tex, _ in todo)
                emit(-1, f"Converting {names}..." if language == "en"
                     else f"Конвертация {names}...")
                from src.services.texture_build.vtf_jobs import VtfJobs
                jobs = VtfJobs()
                for job in todo:
                    jobs.submit(_replace, *job)
                jobs.finish()

            # 4б. Рельеф, карты материала, анимация -> VMT мода
            problems = CustomVPKService._apply_material_extras(
                all_textures, replaced, material_maps or {}, _settings,
                vpkroot_dir, temp_root, language, tf2_root_dir)

            # 5. Гирлянды
            # Тем же сборщиком, что у обычного оружия: модель гирлянды
            # поверх мода, материалы в своей папке (decor_build)
            decor_note = ''
            if decor_builds:
                decor_note = CustomVPKService._build_decor(
                    decor_builds, temp_root, vpkroot_dir, tf2_root_dir, size,
                    format_type, flags or [], vtf_options or {}, bypass_method,
                    emit, language)

            # 6. Перепаковка
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
            return True, "\n".join([msg, *problems, *([decor_note] if decor_note else [])])

        except Exception as e:
            logger.error(f"Критическая ошибка build_custom_mod: {e}", exc_info=True)
            return False, str(e)
        finally:
            shutil.rmtree(str(temp_root), ignore_errors=True)

    @staticmethod
    def _apply_vmt_edits(mod_path: str, textures: List[Dict]) -> None:
        """Правленые VMT материалов мода (ключ - мод + карточка) - вместо его"""
        from src.services.edited_vmt_service import EditedVMTService
        for tex in textures:
            vmt = tex.get('vmt_path')
            edited = vmt and EditedVMTService.get_edited_vmt(
                EditedVMTService.mod_key(mod_path, tex['name']))
            if edited:
                shutil.copyfile(edited, vmt)
                logger.info(f"Правленый VMT мода: {tex['name']} -> {vmt}")

    @staticmethod
    def _materials_dir(vtf_dir: Path, vpkroot_dir: Path) -> Optional[str]:
        """Папка VTF от materials/ - так на неё ссылается VMT (None - вне materials)"""
        try:
            rel = vtf_dir.relative_to(vpkroot_dir).as_posix()
        except ValueError:
            return None
        return rel[len('materials/'):] if rel.lower().startswith('materials/') else None

    @staticmethod
    def _mod_normal(tex: Dict, vpkroot_dir: Path):
        """Родная нормаль материала из самого мода (RGBA) или None

        Рельеф ложится поверх неё, как у модельной сборки поверх игровой: её
        альфа - маска блеска, и затирать работу автора мода нельзя
        """
        from src.services import normal_map, vmt_parse

        vmt = tex.get('vmt_path')
        if not vmt:
            return None
        try:
            text = Path(vmt).read_text(encoding='utf-8', errors='replace')
        except OSError:
            return None
        bump = vmt_parse.parse(text).path('bumpmap')
        if not bump:
            return None
        bump = bump[:-4] if bump.endswith('.vtf') else bump
        vtf = vpkroot_dir / 'materials' / f"{bump}.vtf"
        # ponytail: нормаль из игры (не из мода) не ищем, рельеф тогда без основы
        return normal_map.rgba_from_vtf(vtf.read_bytes()) if vtf.is_file() else None

    @staticmethod
    def _apply_material_extras(all_textures: List[Dict], replaced: Dict, material_maps: Dict,
                               settings_for: Callable, vpkroot_dir: Path, temp_root: Path,
                               language: str, tf2_root_dir: Optional[str] = None) -> List[str]:
        """
        Рельеф (Normal Map), карты материала и анимация - в VMT мода

        Источник картинки: своя (если текстуру заменили) или VTF из мода - как
        у модельной сборки «нормаль и из игровой текстуры». Карты ложатся теми
        же правилами (texture_build.material_maps.apply_maps_for_material), путь - от
        папки VTF под materials/. Синий VMT без своих карт наследует карты
        красного (параметры, VTF те же). Возвращает строки для отчёта сборки

        Карты, что уже стояли в VMT мода (material_maps.detect_maps): карта
        без записи остаётся как в моде, `{"mod": True}` - тоже, но с числами
        из записи, `{"off": True}` - снимается (и её VTF, если он больше
        никому не нужен). Синий VMT снимает только явно снятое: своих карт
        синего красная запись не касается
        """
        from PIL import Image

        from src.data.material_maps import MATERIAL_MAPS, detect_maps
        from src.services import normal_map
        from src.services.part_materials import model_name
        from src.services.texture_service import TextureService
        from src.services.vmt_service import VMTService
        from src.services.texture_build import game_source, map_settings
        from src.services.texture_build import material_maps as mat_maps

        from src.services.tf2_paths import TF2Paths

        # Родная нормаль материала - из мода, иначе из игры: маска отражения и
        # блеска ложится в её альфу, не стирая рельеф
        read_texture = game_source.texture_reader(
            vpkroot_dir, [TF2Paths.resolve_textures_vpk(tf2_root_dir)] if tf2_root_dir else [])
        problems: List[str] = []
        dropped: set = set()          # текстуры снятых карт мода
        first = all_textures[0] if all_textures else None
        by_name = {t['name'].lower(): t for t in all_textures}

        def maps_of(tex: Dict) -> Optional[Dict]:
            """Запись карт материала; None - человек их не трогал"""
            key = model_name(tex['name'])
            found = next((v for k, v in material_maps.items()
                          if k and model_name(k) == key), None)
            # Пустой ключ - главная карточка, страница не знает её имени
            if found is None and tex is first:
                found = material_maps.get('')
            return found

        def keep_and_drop(vmt_path: str, record: Dict) -> None:
            """Карты мода: снятые - долой, оставленные - с числами из записи"""
            try:
                text = Path(vmt_path).read_text(encoding='utf-8', errors='replace')
            except OSError:
                return
            for map_id, found in detect_maps(text).items():
                entry = record.get(map_id) or {}
                if entry.get('off'):
                    VMTService.remove_material_map(vmt_path, map_id)
                    if found.get('texture'):
                        dropped.add(found['texture'])
                elif entry.get('mod'):
                    numbers = {k: v for k, v in entry.items()
                               if k in MATERIAL_MAPS[map_id].get('numeric', ())}
                    if numbers:
                        VMTService.add_material_map_params(vmt_path, '', None, None, numbers)

        for i, tex in enumerate(all_textures):
            size, fmt, _flags, opts = settings_for(tex)
            record = maps_of(tex)
            maps = {k: v for k, v in (record or {}).items()
                    if not (v.get('mod') or v.get('off'))}
            image, fps, rendered_normal = replaced.get(tex['name'], (None, None, False))
            wants_normal = bool(opts.get('normal'))
            if not (record is not None or wants_normal or fps):
                continue

            mat = tex['vtf_name']
            vtf_dir = Path(tex['vtf_path']).parent
            normal_vtf = vtf_dir / f"{mat}_normal.vtf"
            cdmat = CustomVPKService._materials_dir(vtf_dir, vpkroot_dir)
            vmt = tex.get('vmt_path')
            if cdmat is None or not vmt:
                if not (maps or wants_normal or fps):
                    continue
                problems.append(
                    f"{tex['name']}: no VMT next to the texture, normal map and material maps skipped"
                    if language == 'en' else
                    f"{tex['name']}: рядом с текстурой нет VMT, рельеф и карты не добавлены")
                continue
            try:
                if not image and (maps or wants_normal):
                    rgba = normal_map.rgba_from_vtf(Path(tex['vtf_path']).read_bytes())
                    if rgba is not None:
                        image = str(temp_root / f"mod_src_{i}.png")
                        Image.fromarray(rgba, 'RGBA').save(image)

                has_normal = wants_normal and rendered_normal and normal_vtf.exists()
                if wants_normal and not has_normal and image:
                    stock = CustomVPKService._mod_normal(tex, vpkroot_dir)
                    has_normal = TextureService.write_normal_vtf(
                        image, vtf_dir, mat, fmt, opts, stock) is not None

                if fps:
                    VMTService.enable_animated_basetexture(vmt, fps)
                if has_normal:
                    VMTService.update_vmt_bumpmap_path(vmt, cdmat, f"{mat}_normal")
                    if fps:
                        VMTService.enable_animated_bumpmap(vmt, fps)
                if record is not None:
                    blue = by_name.get(f"{tex['name']}_blue".lower())
                    blue_vmt = (blue.get('vmt_path') if blue and maps_of(blue) is None
                                else None)
                    for target in filter(None, (vmt, blue_vmt)):
                        keep_and_drop(target, record)
                    if maps:
                        red = mat_maps.apply_maps_for_material(
                            maps, mat, Path(vmt), image, vtf_dir, cdmat, size, has_normal,
                            read_texture=read_texture)
                        if blue_vmt:
                            mat_maps.apply_maps_for_material(
                                maps, mat, Path(blue_vmt), image, vtf_dir, cdmat,
                                size, has_normal, params_only=True, read_texture=read_texture,
                                red=red)
                    # Свои настройки (цвет отражения, пульсация свечения…) и у
                    # карт, что оставлены как в моде, - после своих карт: иначе
                    # $phongboost 0 от «сильнее по краю» гасил бы их блик
                    kept = {k: v for k, v in record.items() if v.get('mod')}
                    if kept:
                        for target, only in ((vmt, False), (blue_vmt, True)):
                            if target:
                                map_settings.apply_settings(
                                    kept, mat, Path(target), vtf_dir, cdmat, size, image,
                                    has_normal, only)
            except Exception as e:                          # noqa: BLE001
                logger.warning(f"Custom VPK: рельеф/карты '{tex['name']}' не вышли: {e}",
                               exc_info=True)
                problems.append(
                    f"{tex['name']}: normal map / material maps failed, see the log"
                    if language == 'en' else
                    f"{tex['name']}: рельеф или карты не вышли, подробности в журнале")
        CustomVPKService._drop_orphans(dropped, vpkroot_dir)
        return problems

    @staticmethod
    def _drop_orphans(textures, vpkroot_dir: Path) -> None:
        """VTF снятых карт, на которые больше не смотрит ни один VMT мода, -
        из мода вон: иначе архив везёт мёртвый груз"""
        from src.services.mod_textures import all_references, texture_key

        if not textures:
            return
        texts = []
        for vmt in vpkroot_dir.rglob('*.vmt'):
            try:
                texts.append(vmt.read_text(encoding='utf-8', errors='replace'))
            except OSError:
                continue
        alive = all_references(texts)
        for texture in textures:
            key = texture_key(texture)
            vtf = vpkroot_dir / 'materials' / f"{key}.vtf"
            if key not in alive and vtf.is_file():
                vtf.unlink()
                logger.info(f"Custom VPK: снятая карта убрана из мода: {key}.vtf")

    @staticmethod
    def _build_decor(entries: list, temp_root: Path, vpkroot_dir: Path,
                     tf2_root_dir: Optional[str], size, format_type: str,
                     flags: List[str], vtf_options: Dict, bypass_method: str,
                     emit: Callable[[int, str], None], language: str) -> str:
        """Гирлянды в распакованный мод. Возвращает пометку для отчёта, если
        собрались не все: мод при этом собирается - со стоковыми гирляндами,
        как и у обычного оружия (decor_build)"""
        from types import SimpleNamespace

        from src.services.decor_build import build_decor_models
        from src.services.tf2_paths import TF2Paths
        from src.shared.constants import bypass_prefix

        failed = ("Edited lights were not built - see the log"
                  if language == "en" else
                  "Правленые гирлянды не собрались - подробности в журнале")
        try:
            studiomdl_exe, misc_vpk, tf_dir = TF2Paths.resolve(tf2_root_dir or '')
        except FileNotFoundError as exc:
            logger.warning(f"[гирлянда] custom-мод: нет инструментов игры: {exc}")
            return failed
        # Гирлянда из самого мода заменится игровой с правками превью: превью
        # показывает игровую, и собирается то, что видно, - но работу автора
        # мода молча терять нельзя
        replaced = [Path(e['mdl']).stem for e in entries
                    if (vpkroot_dir / e['mdl']).is_file()]
        if replaced:
            logger.warning(f"[гирлянда] custom-мод: своя гирлянда мода заменена "
                           f"игровой: {replaced}")
        ctx = SimpleNamespace(temp_dir=str(temp_root), vpkroot_dir=vpkroot_dir)
        built = build_decor_models(
            ctx, entries, misc_vpk=misc_vpk,
            textures_vpk=TF2Paths.resolve_textures_vpk(tf2_root_dir) or '',
            studiomdl_exe=studiomdl_exe, tf_dir=tf_dir, size=size,
            format_type=format_type, flags=flags, vtf_options=vtf_options,
            bypass_prefix=bypass_prefix(bypass_method), emit_sub=emit,
            language=language)
        notes = [] if built == len(entries) else [failed]
        if replaced:
            notes.append(("The mod's own lights were replaced with the game ones: "
                          if language == "en" else
                          "Своя гирлянда мода заменена игровой: ") + ", ".join(replaced))
        return "\n".join(notes)
