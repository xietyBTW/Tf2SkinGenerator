"""
Воркер для подготовки данных 3D Preview в фоновом потоке.

Шаги:
  1. Проверяем кэш декомпиляции (fast path).
  2. Если нет кэша — извлекаем MDL из VPK, декомпилируем через Crowbar.
  3. Находим reference SMD среди декомпилированных файлов.
  4. Конвертируем SMD → OBJ + MTL.
  5. Извлекаем основную текстуру VTF → PNG.
  6. Эмитируем ready(obj_path, texture_path).
"""

import glob
import os
import shutil
import tempfile
from typing import Optional

from PySide6.QtCore import QThread, Signal

from src.data.weapons import WEAPON_MDL_PATHS
from src.services import decompile_cache
from src.services.model_build_service import ModelBuildService
from src.services.tf2_paths import TF2Paths
from src.services.tf2_vpk_extract_service import TF2VPKExtractService
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class Preview3DWorker(QThread):
    """Готовит OBJ + текстуру для 3D Preview."""

    # Модель и первый кадр текстуры готовы
    ready    = Signal(str, str)
    # Анимированная текстура RED: список путей к PNG кадрам + framerate
    # Эмитируется ПОСЛЕ ready если кадров > 1
    animated = Signal(object, float)
    # BLU-вариант текстуры: [frame_paths], framerate
    # Эмитируется только если у оружия есть командная раскраска
    blu_ready = Signal(object, float)
    # Несколько текстур для мульти-материальных моделей: {mat_name: png_path}
    # Эмитируется вместо animated когда модель имеет > 1 материал
    multi_material = Signal(object)
    # Ошибка
    failed   = Signal(str)
    # Текстовый прогресс для UI
    progress = Signal(str)

    _PROGRESS = {
        'ru': {
            'searching':   'Поиск модели...',
            'converting':  'Конвертация модели...',
            'texture':     'Загрузка текстуры...',
            'extracting':  'Извлечение модели из VPK...',
            'decompiling': 'Декомпиляция модели...',
            'not_found':   'Модель не найдена в VPK',
            'conv_error':  'Ошибка конвертации модели',
        },
        'en': {
            'searching':   'Searching for model...',
            'converting':  'Converting model...',
            'texture':     'Loading texture...',
            'extracting':  'Extracting model from VPK...',
            'decompiling': 'Decompiling model...',
            'not_found':   'Model not found in VPK',
            'conv_error':  'Model conversion error',
        },
    }

    def __init__(
        self,
        weapon_key: str,
        mode: str,
        misc_vpk_path: str,
        textures_vpk_path: str,
        lang: str = 'en',
        parent=None,
    ):
        super().__init__(parent)
        self.weapon_key        = weapon_key
        self.mode              = mode
        self.misc_vpk_path     = misc_vpk_path
        self.textures_vpk_path = textures_vpk_path
        self._preview_dir: Optional[str] = None
        self._p = self._PROGRESS.get(lang, self._PROGRESS['en'])

    # ── Точка входа ───────────────────────────────────────────────────────── #

    def run(self) -> None:
        try:
            self._preview_dir = tempfile.mkdtemp(prefix="tf2sg_3d_")

            # ── 1. SMD ────────────────────────────────────────────────────── #
            self.progress.emit(self._p['searching'])
            smd_path = self._get_reference_smd()
            if not smd_path:
                self.failed.emit(self._p['not_found'])
                return
            if self.isInterruptionRequested():
                return

            # ── 2. OBJ ────────────────────────────────────────────────────── #
            self.progress.emit(self._p['converting'])
            obj_path = os.path.join(self._preview_dir, "model.obj")
            from src.services.smd_to_obj_service import SmdToObjService
            from src.data.player_hands import HAND_MODE_KEYS, HAND_MODES

            # Ищем bodygroup SMDs в той же папке (например c_righthand_bodygroup.smd)
            bodygroup_smds = self._find_bodygroup_smds(smd_path)
            if bodygroup_smds:
                logger.info(
                    f"[3D] Найдены bodygroup SMD: "
                    f"{[os.path.basename(b) for b in bodygroup_smds]}"
                )

            ok, mat_names = SmdToObjService.convert(
                smd_path, obj_path,
                extra_smd_paths=bodygroup_smds
            )
            if not ok:
                self.failed.emit(self._p['conv_error'])
                return
            if self.isInterruptionRequested():
                return

            # ── 3. Текстура ───────────────────────────────────────────────── #
            self.progress.emit(self._p['texture'])

            if self.mode in HAND_MODE_KEYS and mat_names:
                # Режим рук: мульти-материал — каждый меш получает свою текстуру
                tex_map = self._extract_multi_textures(mat_names)
                self.ready.emit(obj_path, "")          # модель без единой текстуры
                if tex_map:
                    self.multi_material.emit(tex_map)  # {mat_name: png_path}
                # BLU/анимация для рук не нужны
            else:
                # Обычное оружие: одна текстура (возможно анимированная)
                frame_paths, framerate = self._extract_texture_frames()

                first_tex = frame_paths[0] if frame_paths else ""
                self.ready.emit(obj_path, first_tex)

                if len(frame_paths) > 1:
                    self.animated.emit(frame_paths, framerate)

                if self.isInterruptionRequested():
                    return

                # ── 4. Текстура BLU (если есть командная раскраска) ──────── #
                blu_paths, blu_fps = self._extract_blu_texture_frames(framerate)
                if blu_paths:
                    self.blu_ready.emit(blu_paths, blu_fps)

        except Exception as exc:
            logger.error(f"Preview3DWorker: {exc}", exc_info=True)
            self.failed.emit(str(exc))

    # ── Получение SMD ─────────────────────────────────────────────────────── #

    def _get_reference_smd(self) -> Optional[str]:
        """Возвращает reference SMD из кэша или после декомпиляции."""
        mdl_rel = WEAPON_MDL_PATHS.get(
            self.weapon_key,
            f"models/weapons/c_models/{self.weapon_key}/{self.weapon_key}.mdl",
        )

        cached = decompile_cache.get_cached_decompile(
            self.weapon_key, self.misc_vpk_path, mdl_rel
        )
        if cached:
            logger.info(f"3D Preview: кэш декомпила для {self.weapon_key}")
            return self._find_reference_smd(cached)

        return self._extract_and_decompile(mdl_rel)

    def _extract_and_decompile(self, mdl_rel_hint: str) -> Optional[str]:
        """Извлекает MDL из VPK и декомпилирует через Crowbar."""
        from src.services.extract_model_service import ExtractModelService

        self.progress.emit(self._p['extracting'])

        # ── Диагностика: проверяем доступность VPK и инструментов ─────────── #
        if not os.path.exists(self.misc_vpk_path):
            logger.error(f"[3D] misc VPK не найден: {self.misc_vpk_path}")
            self.failed.emit(f"VPK not found: {self.misc_vpk_path}")
            return None

        crowbar = TF2Paths.get_crowbar_path()
        crowbar_abs = os.path.abspath(crowbar)
        if not os.path.exists(crowbar_abs):
            logger.error(f"[3D] Crowbar не найден: {crowbar_abs}")
            self.failed.emit(f"Crowbar not found: {crowbar_abs}")
            return None

        logger.info(f"[3D] cwd={os.getcwd()} | crowbar={crowbar_abs} | vpk={self.misc_vpk_path}")

        paths_to_try = ExtractModelService._build_paths_to_try(
            self.mode, self.weapon_key
        )

        found_rel: Optional[str] = None
        for path in paths_to_try:
            if self.isInterruptionRequested():
                return None
            try:
                if TF2VPKExtractService.check_mdl_exists(self.misc_vpk_path, path):
                    found_rel = path
                    logger.info(f"[3D] MDL найден: {path}")
                    break
            except Exception as e:
                logger.debug(f"[3D] check_mdl_exists ошибка для {path}: {e}")
                continue

        if not found_rel:
            logger.warning(f"[3D] MDL не найден в VPK для {self.weapon_key}. Пробовали: {paths_to_try[:3]}")
            return None

        try:
            mdl_dir = tempfile.mkdtemp(prefix="tf2sg_mdl_")
            extracted = TF2VPKExtractService.extract_file_set(
                self.misc_vpk_path, found_rel, mdl_dir, None
            )
            mdl_file = next((f for f in extracted if f.endswith(".mdl")), None)
            if not mdl_file:
                logger.error(f"[3D] MDL файл не найден после извлечения: {extracted}")
                shutil.rmtree(mdl_dir, ignore_errors=True)
                return None

            if self.isInterruptionRequested():
                shutil.rmtree(mdl_dir, ignore_errors=True)
                return None

            self.progress.emit(self._p['decompiling'])
            decomp_dir = tempfile.mkdtemp(prefix="tf2sg_decomp_")
            logger.info(f"[3D] Запускаем Crowbar: mdl={mdl_file} → {decomp_dir}")
            ModelBuildService.decompile(mdl_file, decomp_dir, crowbar)
            logger.info(f"[3D] Crowbar завершён успешно")

            decompile_cache.save_to_cache(
                self.weapon_key, self.misc_vpk_path, found_rel, decomp_dir
            )

            shutil.rmtree(mdl_dir, ignore_errors=True)
            return self._find_reference_smd(decomp_dir)

        except Exception as exc:
            logger.error(f"[3D] Ошибка декомпиляции для {self.weapon_key}: {exc}", exc_info=True)
            self.failed.emit(f"Decompile error: {exc}")
            return None

    def _find_reference_smd(self, directory: str) -> Optional[str]:
        """Находит reference SMD (исключая physics/anim) в директории."""
        _SKIP = ("physics", "phys", "anim", "idle", "pose")

        def skip(path: str) -> bool:
            return any(kw in os.path.basename(path).lower() for kw in _SKIP)

        # Лучший вариант — *_reference.smd
        refs = [p for p in glob.glob(os.path.join(directory, "*_reference.smd"))
                if not skip(p)]
        if refs:
            return refs[0]

        # SMD с weapon_key в имени
        wk_smds = [
            p for p in glob.glob(os.path.join(directory, f"*{self.weapon_key}*.smd"))
            if not skip(p)
        ]
        if wk_smds:
            return wk_smds[0]

        # Любой SMD не physics/anim
        all_smds = [p for p in glob.glob(os.path.join(directory, "*.smd"))
                    if not skip(p)]
        return all_smds[0] if all_smds else None

    def _find_bodygroup_smds(self, reference_smd_path: str) -> list:
        """
        Ищет *_bodygroup.smd файлы в той же папке что и reference SMD.

        Source Engine хранит опциональную геометрию (бодигруппы) в отдельных
        SMD файлах рядом с reference SMD. Пример: c_righthand_bodygroup.smd
        внутри c_pyro_arms — правая рука, которая включается при нужном оружии.

        Returns:
            Список путей к найденным _bodygroup.smd файлам.
        """
        directory = os.path.dirname(reference_smd_path)
        pattern   = os.path.join(directory, "*_bodygroup.smd")
        return sorted(glob.glob(pattern))

    @staticmethod
    def _scan_smd_mat_names(smd_paths: list) -> set:
        """
        Быстрое сканирование имён материалов из нескольких SMD файлов.

        Читает только имена материалов (без парсинга вершин) — в 10-30 раз
        быстрее чем полный _parse_triangles_by_mat.

        Returns:
            Множество всех имён материалов из всех SMD файлов.
        """
        import re
        result: set = set()
        for path in smd_paths:
            if not os.path.exists(path):
                continue
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                m = re.search(r"\btriangles\b(.*?)\bend\b", content,
                              re.DOTALL | re.IGNORECASE)
                if not m:
                    continue
                lines = [ln.strip() for ln in m.group(1).splitlines() if ln.strip()]
                # Каждые 4 строки: имя_материала, вершина1, вершина2, вершина3
                result.update(lines[i] for i in range(0, len(lines), 4))
            except Exception:
                pass
        return result

    # ── Извлечение нескольких текстур (мульти-материал) ──────────────────── #

    def _extract_multi_textures(self, mat_names: list) -> dict:
        """
        Для каждого имени материала из SMD ищет VTF в VPK и сохраняет как PNG.

        Returns:
            {mat_name: png_path} — только для найденных текстур.
        """
        result: dict = {}
        try:
            import vpk as vpklib
            from PIL import Image
            from src.services.vtflib_wrapper import VTFLib
            from src.data.player_hands import HAND_MODE_KEYS, HAND_MODES

            pak = vpklib.open(self.textures_vpk_path)

            # Для моделей рук определяем папку (materials/models/player/{folder}/)
            # Все материалы SMD текстурируем — _find_vtf_for_mat ищет сначала
            # в папке игрока, что покрывает и руки, и рукав костюма.
            arm_folder: Optional[str] = None
            if self.mode in HAND_MODE_KEYS:
                textures_list = HAND_MODES.get(self.mode, {}).get("textures", [])
                if textures_list:
                    arm_folder = textures_list[0][0]

            for mat_name in mat_names:
                vtf_data = self._find_vtf_for_mat(pak, mat_name, arm_folder)
                if not vtf_data:
                    logger.warning(f"[3D] Текстура для материала '{mat_name}' не найдена")
                    continue

                tmp_vtf = os.path.join(self._preview_dir, f"_tmp_{mat_name}.vtf")
                with open(tmp_vtf, "wb") as f:
                    f.write(vtf_data)

                all_frames = None
                try:
                    all_frames, w, h = VTFLib.read_vtf_all_frames(tmp_vtf)
                except Exception as vtf_exc:
                    logger.warning(
                        f"[3D] VTFLib не смог декодировать '{mat_name}': {vtf_exc}"
                    )
                finally:
                    try:
                        os.remove(tmp_vtf)
                    except OSError:
                        pass

                if not all_frames:
                    continue

                img = Image.frombytes("RGBA", (w, h), all_frames[0])
                png_path = os.path.join(self._preview_dir, f"{mat_name}.png")
                img.save(png_path)
                result[mat_name] = png_path
                logger.debug(f"[3D] Материал '{mat_name}' → {os.path.basename(png_path)}")

        except Exception as exc:
            logger.warning(f"[3D] Ошибка извлечения мульти-текстур: {exc}", exc_info=True)

        return result

    def _find_vtf_for_mat(
        self, pak, mat_name: str, arm_folder: Optional[str]
    ) -> Optional[bytes]:
        """Ищет VTF-данные для имени материала из SMD."""
        paths: list = []
        mat_lower = mat_name.lower()

        # Приоритет: папка рук игрока (materials/models/player/{folder}/)
        # Пробуем оба варианта: оригинальный регистр и lowercase,
        # т.к. SMD может использовать mixed-case (engineer_handL), а VTF в VPK
        # хранится в lowercase (engineer_handl).
        if arm_folder:
            paths.append(f"materials/models/player/{arm_folder}/{mat_name}.vtf")
            if mat_lower != mat_name:
                paths.append(f"materials/models/player/{arm_folder}/{mat_lower}.vtf")

            # Fallback для sheen/overlay мешей: в TF2 эти материалы содержат
            # ту же геометрию рук, что и базовый материал, но рендерятся с
            # эффектом киллстрика. VTF для sheen в VPK нет — используем базовый.
            # Например: hvyweapon_hands_sheen → hvyweapon_hands.vtf
            _OVERLAY_SUFFIXES = ("_sheen2", "_sheen", "_overlay", "_fresnel")
            for suf in _OVERLAY_SUFFIXES:
                if mat_lower.endswith(suf):
                    base = mat_name[: -len(suf)]
                    base_lower = base.lower()
                    paths.append(
                        f"materials/models/player/{arm_folder}/{base}.vtf"
                    )
                    if base_lower != base:
                        paths.append(
                            f"materials/models/player/{arm_folder}/{base_lower}.vtf"
                        )
                    break

        # Стандартные пути оружий
        paths += [
            f"materials/models/workshop_partner/weapons/c_models/{mat_name}/{mat_name}.vtf",
            f"materials/models/weapons/c_models/{mat_name}/{mat_name}.vtf",
            f"materials/models/weapons/c_items/{mat_name}.vtf",
            f"materials/models/workshop/weapons/c_models/{mat_name}/{mat_name}.vtf",
        ]

        for path in paths:
            try:
                return pak[path].read()
            except KeyError:
                continue
        return None

    # ── Извлечение текстуры ───────────────────────────────────────────────── #

    def _extract_texture_frames(self) -> tuple:
        """
        Извлекает VTF текстуру из VPK.

        Если VTF содержит несколько кадров (анимированная текстура) —
        сохраняет каждый кадр отдельным PNG и читает framerate из VMT.

        Returns:
            (frame_paths: list[str], framerate: float)
            frame_paths пустой если текстура не найдена.
        """
        try:
            import vpk as vpklib
            from src.data.weapons import WEAPON_TEXTURE_PATHS

            wk = self.weapon_key
            _standard = [
                f"materials/models/workshop_partner/weapons/c_models/{wk}/{wk}.vtf",
                f"materials/models/weapons/c_models/{wk}/{wk}.vtf",
                f"materials/models/weapons/c_items/{wk}/{wk}.vtf",
                f"materials/models/workshop/weapons/c_models/{wk}/{wk}.vtf",
            ]
            # Нестандартные пути проверяем первыми
            vtf_search = WEAPON_TEXTURE_PATHS.get(wk, []) + _standard
            vmt_search = [p.replace(".vtf", ".vmt") for p in vtf_search]

            pak = vpklib.open(self.textures_vpk_path)
            vtf_data: Optional[bytes] = None
            for path in vtf_search:
                try:
                    vtf_data = pak[path].read()
                    logger.debug(f"3D Preview текстура: {path}")
                    break
                except KeyError:
                    continue

            if not vtf_data:
                logger.warning(f"Текстура для {self.weapon_key} не найдена в VPK")
                return [], 0.0

            # Сохраняем VTF во временный файл
            vtf_file = os.path.join(self._preview_dir, "_tmp.vtf")
            with open(vtf_file, "wb") as f:
                f.write(vtf_data)

            from src.services.vtflib_wrapper import VTFLib
            from PIL import Image

            # Читаем все кадры
            all_frames_rgba, w, h = VTFLib.read_vtf_all_frames(vtf_file)
            os.remove(vtf_file)

            frame_paths: list[str] = []
            for i, rgba in enumerate(all_frames_rgba):
                img  = Image.frombytes("RGBA", (w, h), rgba)
                name = f"texture_{i:03d}.png" if len(all_frames_rgba) > 1 else "texture.png"
                path = os.path.join(self._preview_dir, name)
                img.save(path)
                frame_paths.append(path)

            # Framerate из VMT
            framerate = 0.0
            if len(frame_paths) > 1:
                framerate = self._read_vmt_framerate(pak, vmt_search)
                logger.info(
                    f"Анимированная текстура: {len(frame_paths)} кадров "
                    f"@ {framerate:.1f} fps для {self.weapon_key}"
                )

            return frame_paths, framerate

        except Exception as exc:
            logger.warning(f"Не удалось извлечь текстуру для 3D Preview: {exc}")
            return [], 0.0

    def _extract_blu_texture_frames(self, red_framerate: float) -> tuple:
        """
        Пробует найти BLU-вариант текстуры (суффикс _blue) в VPK.

        Возвращает (frame_paths: list[str], framerate: float).
        Если BLU текстура не найдена — возвращает ([], 0.0).
        """
        try:
            import vpk as vpklib
            from src.data.weapons import WEAPON_TEXTURE_PATHS

            wk = self.weapon_key
            _extra_blu = [
                p.replace(".vtf", "_blue.vtf")
                for p in WEAPON_TEXTURE_PATHS.get(wk, [])
            ]
            _std_blu = [
                f"materials/models/workshop_partner/weapons/c_models/{wk}/{wk}_blue.vtf",
                f"materials/models/weapons/c_models/{wk}/{wk}_blue.vtf",
                f"materials/models/weapons/c_items/{wk}/{wk}_blue.vtf",
                f"materials/models/workshop/weapons/c_models/{wk}/{wk}_blue.vtf",
            ]
            blu_vtf_search = _extra_blu + _std_blu

            pak = vpklib.open(self.textures_vpk_path)
            vtf_data: Optional[bytes] = None
            for path in blu_vtf_search:
                try:
                    vtf_data = pak[path].read()
                    logger.debug(f"3D Preview BLU текстура: {path}")
                    break
                except KeyError:
                    continue

            if not vtf_data:
                return [], 0.0

            vtf_file = os.path.join(self._preview_dir, "_tmp_blu.vtf")
            with open(vtf_file, "wb") as f:
                f.write(vtf_data)

            from src.services.vtflib_wrapper import VTFLib
            from PIL import Image

            all_frames_rgba, w, h = VTFLib.read_vtf_all_frames(vtf_file)
            os.remove(vtf_file)

            frame_paths: list[str] = []
            for i, rgba in enumerate(all_frames_rgba):
                img  = Image.frombytes("RGBA", (w, h), rgba)
                name = f"texture_blu_{i:03d}.png" if len(all_frames_rgba) > 1 else "texture_blu.png"
                path = os.path.join(self._preview_dir, name)
                img.save(path)
                frame_paths.append(path)

            # Используем тот же framerate что и у RED (из VMT)
            fps = red_framerate if len(frame_paths) > 1 else 0.0
            logger.info(
                f"BLU текстура найдена: {len(frame_paths)} кадров "
                f"@ {fps:.1f} fps для {self.weapon_key}"
            )
            return frame_paths, fps

        except Exception as exc:
            logger.debug(f"BLU текстура не найдена для {self.weapon_key}: {exc}")
            return [], 0.0

    def _read_vmt_framerate(self, pak, vmt_search: list) -> float:
        """Ищет animatedtextureframerate в VMT файле из VPK."""
        import re
        DEFAULT_FPS = 15.0
        for path in vmt_search:
            try:
                content = pak[path].read().decode("utf-8", errors="replace")
                m = re.search(
                    r'"animatedtextureframerate"\s+"?([0-9.]+)"?',
                    content,
                    re.IGNORECASE,
                )
                if m:
                    return max(0.1, float(m.group(1)))
                break   # VMT найден, но без framerate — используем дефолт
            except KeyError:
                continue
        return DEFAULT_FPS
