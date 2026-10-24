"""
Воркер для подготовки данных 3D Preview в фоновом потоке

Шаги:
  1. Проверяем кэш декомпиляции (fast path).
  2. Если нет кэша - извлекаем MDL из VPK, декомпилируем через Crowbar.
  3. Находим reference SMD среди декомпилированных файлов (smd_locator).
  4. Конвертируем SMD -> OBJ + MTL.
  5. Извлекаем текстуры VTF -> PNG (где они в VPK - texture_locator).
  6. Эмитируем ready(obj_path, texture_path)
"""

import os
import tempfile
from typing import Optional

from src.services.base_worker import Signal

from src.data.item_kinds import kind_of
from src.services import model_decompile_service
from src.services import qc_skin_parser, smd_locator, team_twins, texture_locator, vmt_tint
from src.services.base_worker import BaseWorker
from src.services.game_vpk_reader import GameVpkReader
from src.services.material_resolver import MaterialResolver
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


def with_part_models(decomp_dir: str, part_models: dict, out_dir: str) -> str:
    """
    Копия разобранной модели, где детали заменены своей геометрией человека

    Кэш разборки общий - превью трогает копию. Файл детали остаётся под своим
    именем: по именам SMD сборка находит треугольники частей (`# Sources:` в
    OBJ, part_materials), и в моде деталь лежит под тем же именем. Сшивка та
    же, что у сборки (SMDService.replace_model_sections): скелет и материал
    игровой детали, кости человека - на её кость (у гранаты Loch-n-Load это
    weapon_bone_4, её двигает рука на перезарядке)

    Returns: папка копии
    """
    import shutil

    from src.services.smd_service import SMDService

    shutil.copytree(decomp_dir, out_dir, dirs_exist_ok=True)
    on_disk = {os.path.splitext(f)[0].lower(): f for f in os.listdir(out_dir)
               if f.lower().endswith('.smd')}
    for base, user_smd in part_models.items():
        name = on_disk.get(str(base).lower())
        if not name or not (user_smd and os.path.isfile(user_smd)):
            continue
        target = os.path.join(out_dir, name)
        try:
            SMDService.replace_model_sections(user_smd, target, target)
        except Exception as exc:   # noqa: BLE001 - в кадре останется игровая деталь
            logger.warning(f"[3D] своя модель детали {name} не встала: {exc}")
    return out_dir


class Preview3DWorker(BaseWorker):
    """Готовит OBJ + текстуру для 3D Preview"""

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
    # BLU-вариант мульти-материальных текстур: {mat_name: png_path}
    # Эмитируется для персонажей когда у каждого меша есть своя BLU-текстура
    blu_multi_material = Signal(object)
    # Игровые текстуры косметических стилей (bloody/clean):
    # {индекс скина: {базовый материал: png_path}}
    skin_textures = Signal(object)
    # Australium/Gold/Festive вариант оружия: (png_path, material_name)
    # Эмитируется когда в QC skinfamilies есть вариантная строка без 'blue'
    australium_ready = Signal(str, str)
    # {синий материал: его RED-пара} - в игре синий выглядит ТОЧНО как
    # красный. Переключатель ради них не показывается, а сборка отдаёт им
    # правку красного
    blu_same_as_red = Signal(object)
    # Как рисовать материалы: {имя материала: {blend, opacity, twoSided…}}.
    # Без этого вьювер рисует всё непрозрачным и матовым: стекло банки
    # Мутировавшего молока ($additive) превращается в серый пластик
    render_hints = Signal(object)
    # Чужая геометрия в кадре: ({материал: png} носителя, [материалы предмета]).
    # Праздничное оружие - это гирлянда, надетая на обычную пушку, пушка в
    # кадре нужна, но предмету не принадлежит: карточек по ней не строится и в
    # сборку она не идёт. Имена материалов ПРЕДМЕТА едут тем же сигналом: у
    # одноматериальной модели текстура хранится под служебным ключом, меша с
    # таким именем нет, и без настоящего имени гирлянда осталась бы стоковой
    scene_extra = Signal(object)
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
        bodygroups: Optional[dict] = None,
        part_models: Optional[dict] = None,
    ):
        super().__init__(parent)
        self.weapon_key        = weapon_key
        self.mode              = mode
        #: Выбранные варианты бодигрупп {имя группы: номер}: переключатель
        #: состояния в превью (разбитая бутылка). Пусто - как в игре по умолчанию
        self.bodygroups: dict  = dict(bodygroups or {})
        #: Своя геометрия деталей {имя SMD детали без .smd: SMD человека}:
        #: снаряд в оружии своей модели (см. with_part_models)
        self.part_models: dict = dict(part_models or {})
        #: Вид предмета: вместо разбросанных проверок «mode == 'hat'» и
        #: «mode in HAND_MODE_KEYS» (см. src/data/item_kinds.py)
        self.kind              = kind_of(mode)
        self.misc_vpk_path     = misc_vpk_path
        self.textures_vpk_path = textures_vpk_path
        self._preview_dir: Optional[str] = None
        self._decomp_dir:  Optional[str] = None  # папка с декомпилированными QC/SMD
        self._hat_decomp_dir: Optional[str] = None  # алиас для режима hat
        #: Папка декомпиляции пушки-носителя праздничной гирлянды. Её
        #: $cdmaterials свои: гирлянда лежит в папке оружия, а сама пушка - в
        #: своей, и без второго пути носитель остаётся серым
        self._carrier_dir: Optional[str] = None
        #: {материал: ResolvedMaterial} для RED - с чем сравнивать BLU,
        #: чтобы понять, отличаются ли команды вообще
        self._red_looks: dict = {}
        #: {папка декомпиляции: {материал: треугольники развёртки}}
        self._uv_cache: dict = {}
        #: Ленивый резолвер материалов и кэш разбора QC (по папке декомпиляции)
        self._materials: Optional[MaterialResolver] = None
        self._models: dict = {}
        self._cached_cdmaterials: Optional[list] = None
        #: «Поздние» детали (снаряд в оружии) - их задаёт _find_bodygroup_smds
        self._late_smds: Optional[list] = None
        self._p = self._PROGRESS.get(lang, self._PROGRESS['en'])

    # Точка входа

    def run(self) -> None:
        # Один кэширующий читатель VPK на весь прогон: vpk.open парсит весь индекс
        # архива, и каждый метод открывал бы те же VPK заново
        self._reader = GameVpkReader([self.textures_vpk_path, self.misc_vpk_path])
        try:
            self._preview_dir = tempfile.mkdtemp(prefix="tf2sg_3d_")

            # 1. SMD
            self.progress.emit(self._p['searching'])
            smd_path = self._get_reference_smd()
            if not smd_path:
                # Отменённая декомпиляция тоже отдаёт None - это не «нет в VPK»
                if not self.isInterruptionRequested():
                    self.failed.emit(self._p['not_found'])
                return
            if self.part_models:
                copy = with_part_models(os.path.dirname(smd_path), self.part_models,
                                        os.path.join(self._preview_dir, 'model'))
                smd_path = os.path.join(copy, os.path.basename(smd_path))
            # Сохраняем папку декомпиляции: нужна для QC-парсинга BLU текстур
            self._decomp_dir = os.path.dirname(smd_path)
            if self.kind.is_hat:
                self._hat_decomp_dir = self._decomp_dir
            if self.isInterruptionRequested():
                return

            # 2. OBJ
            self.progress.emit(self._p['converting'])
            obj_path = os.path.join(self._preview_dir, "model.obj")
            from src.services.smd_to_obj_service import SmdToObjService

            # Ищем bodygroup SMDs в той же папке (например c_righthand_bodygroup.smd)
            bodygroup_smds = self._find_bodygroup_smds(smd_path)
            # Основной SMD сам может быть вариантом группы (c_bottle.smd - целая
            # бутылка): выбрали другой вариант - основным становится он
            smd_path = self._swap_reference_for_choice(smd_path, bodygroup_smds)
            if bodygroup_smds:
                logger.info(
                    f"[3D] Найдены bodygroup SMD: "
                    f"{[os.path.basename(b) for b in bodygroup_smds]}"
                )

            # Персонажи TF2 компилируются с $upaxis Y - SMD уже Y-up,
            # конвертацию Z->Y для них не делаем
            _source_zup = self.kind.model_is_z_up

            # Превью-фильтр материалов: для моделей, где надо показать только часть
            # (напр. Dead Ringer на viewmodel с руками - оставляем только часы)
            _include_mats = None
            from src.data.weapon_quirks import MODEL_MATERIAL_WHITELIST
            _wl = MODEL_MATERIAL_WHITELIST.get(self.weapon_key)
            if _wl:
                _all_mats = SmdToObjService.scan_material_names(
                    [smd_path] + bodygroup_smds)
                _keep = {m for m in _all_mats if any(s in m.lower() for s in _wl)}
                if _keep:
                    _include_mats = _keep
                    logger.info(f"[3D] Превью-фильтр {self.weapon_key}: оставляем меши {_keep}")
                else:
                    logger.warning(
                        f"[3D] Whitelist {_wl} не совпал ни с одним материалом "
                        f"({_all_mats}) - показываю всю модель"
                    )

            # Поза из первой последовательности QC: игра всегда её проигрывает,
            # и reference-меш - не то, что видит игрок (у Мутировавшего молока
            # хлеб в bind-позе торчит из банки). Модель, чья поза совпадает с
            # bind, остаётся нетронутой - таких подавляющее большинство
            _pose_smd = self._find_pose_smd()

            # Пушка, НА КОТОРОЙ висит эта модель. Праздничное оружие - не
            # отдельная пушка, а навесная гирлянда: в `c_scattergun_xmas`
            # лежат одни огоньки. Без носителя в кадре висела гирлянда, а
            # оружия не было вовсе
            carrier_smds = self._carrier_smds()
            carrier_mats: set = set()
            if carrier_smds:
                carrier_mats = set(
                    SmdToObjService.scan_material_names(carrier_smds))
                bodygroup_smds = bodygroup_smds + carrier_smds

            ok, mat_names = SmdToObjService.convert(
                smd_path, obj_path,
                include_mats=_include_mats,
                extra_smd_paths=bodygroup_smds,
                source_zup=_source_zup,
                pose_smd_path=_pose_smd,
                # Косметика в MDL лежит как автору было удобно, игра ставит её
                # bonemerge на голову игрока - и превью так же
                on_player=self.kind.worn_on_player,
                late_smd_paths=self._late_smds,
            )
            if not ok:
                self.failed.emit(self._p['conv_error'])
                return
            if self.isInterruptionRequested():
                return

            # Носитель в кадре есть, но предмету он не принадлежит: его
            # материалы уходят подложкой сцены, а не в состав предмета. Иначе
            # база оружия стала бы карточкой альбома, и человек красил бы
            # обычный обрез, собирая мод на праздничный
            if carrier_mats:
                own = [m for m in mat_names if m not in carrier_mats]
                extra = self._extract_multi_textures(
                    [m for m in mat_names if m in carrier_mats])
                if extra:
                    self.scene_extra.emit((extra, own))
                logger.info(f"[3D] {self.weapon_key}: носитель добавлен в кадр, "
                            f"его материалы {sorted(carrier_mats)} - подложкой")
                mat_names = own

            # 3. Текстура
            self.progress.emit(self._p['texture'])

            # Свойства рисования - ДО текстур: вьювер применит их к материалам
            # по мере поступления картинок, а не пересоберёт материалы дважды
            self._emit_render_hints(mat_names)

            if self.kind.multi_material and mat_names:
                self._emit_multi_tex_mode(obj_path, mat_names)
            elif self.kind.is_spy_mask:
                self._emit_spy_mask_textures(obj_path, mat_names)
            elif self.kind.is_hat:
                self._emit_hat_textures(obj_path, mat_names)
            else:
                self._emit_weapon_textures(obj_path, mat_names)

        except Exception as exc:
            logger.error(f"Preview3DWorker: {exc}", exc_info=True)
            self.failed.emit(str(exc))
        finally:
            self._reader.close()

    def _find_pose_smd(self) -> Optional[str]:
        """SMD анимации из QC модели - поза, в которой предмет виден в игре"""
        if not self._decomp_dir:
            return None
        try:
            from src.services import smd_pose
            model = self._model(self._decomp_dir)
            if model is None:
                return None
            return smd_pose.find_pose_smd(model.qc_path)
        except Exception as exc:
            logger.debug(f"[3D] SMD анимации не найден: {exc}")
            return None

    def _emit_render_hints(self, mat_names: list) -> None:
        """Отдаёт вьюверу прозрачность/блик/отражение материалов модели

        Свойства берутся из VMT (vmt_render) и зависят только от материала,
        не от того, какая картинка на нём сейчас: пользователь может бросить
        свою текстуру на стекло, и оно обязано остаться стеклом
        """
        try:
            hints = self.materials.render_map(
                list(mat_names or []), self._get_qc_cdmaterials())
        except Exception as exc:
            logger.debug(f"[3D] свойства материалов не собраны: {exc}")
            hints = {}
        if self._decomp_dir:
            from src.services import control_panel
            hints.update(control_panel.screen_hints(self._decomp_dir))
        # Отправляем ВСЕГДА, даже пустое: иначе на новой модели останутся
        # свойства предыдущей, а материалы у разных пушек нередко тёзки
        # (36 моделей стока делят главную текстуру с соседней)
        if hints:
            logger.info(f"[3D] особые материалы: {hints}")
        self.render_hints.emit(hints)

    # Ветки извлечения текстур (по режиму)

    def _emit_multi_tex_mode(self, obj_path: str, mat_names: list) -> None:
        """Руки / тело персонажа: мульти-материал - каждый меш получает свою текстуру"""
        tex_map = self._extract_multi_textures(mat_names)
        # Служебные материалы $texturegroup вне геометрии (eyeball_invun,
        # *_zombie …) - для селектора «Прочее» в 2D
        _misc_extras = self._extract_texturegroup_misc_extras(mat_names)
        if _misc_extras:
            tex_map.update(_misc_extras)
        self.ready.emit(obj_path, "")
        if tex_map:
            self.multi_material.emit(tex_map)
        # BLU detection для персонажей:
        # Для многоматериальных моделей - строим полную карту {mat: blu_png}.
        # Если не удалось - пробуем одиночный BLU (старый путь как fallback)
        if self._decomp_dir and mat_names:
            try:
                raw = self._extract_blu_multi_textures_via_qc(mat_names)
                if raw:
                    # raw: {red_mat_name: (blu_png_path | None, blu_display_name)}
                    # tex_map - только записи с реальным PNG (для 3D-превью)
                    # name_map - все записи где BLU-имя отличается от RED (для лейблов карточек)
                    tex_map  = {k: v[0] for k, v in raw.items() if v[0]}
                    name_map = {k: v[1] for k, v in raw.items()}
                    self.blu_multi_material.emit((tex_map, name_map))
                    logger.info(
                        f"[3D] BLU multi-tex: {len(tex_map)} текстур, "
                        f"{len(name_map)} имён"
                    )
                else:
                    # Fallback: ищем единственный BLU VTF через QC
                    blu_paths, blu_fps = self._extract_blu_via_qc(
                        self._decomp_dir, 0.0, mat_names
                    )
                    if blu_paths:
                        self.blu_ready.emit(blu_paths, blu_fps)
            except Exception as _exc:
                logger.debug(f"[3D] BLU detection (multi-tex): {_exc}")

    def _emit_spy_mask_textures(self, obj_path: str, mat_names: list) -> None:
        """Маски маскировки: девять текстур на один меш головы

        Общий путь оружия извлёк бы ОДНУ маску (`mask_spy`) и карточку тела
        шпиона. Но масок девять, а тело предметом не является - сборка кладёт в мод только `mask_*.vtf`
        (``VpkService._build_spy_masks``), тело остаётся игровым

        Поэтому карточки - все девять масок, а материалы модели уходят
        подложкой сцены: голова в кадре нужна, но правят на ней маску
        """
        from src.data.player_characters import SPY_DISGUISE_MASKS, SPY_MASK_VTF_NAMES

        masks: dict = {}
        for _cls, vtf_name, *_rest in SPY_DISGUISE_MASKS:
            if self.isInterruptionRequested():
                return
            frames, _fps = self._extract_spy_mask_texture(vtf_name)
            if frames:
                masks[vtf_name] = frames[0]

        if not masks:
            logger.warning("[3D] маски маскировки не извлечены - обычный путь")
            self._emit_weapon_textures(obj_path, mat_names)
            return

        self.ready.emit(obj_path, next(iter(masks.values()), ""))
        # Меши кадра предмету не принадлежат: маска - это ТЕКСТУРА на голове, а
        # не своя геометрия. Их текстуры кладём подложкой, чтобы голова и тело
        # не остались серыми, а вторым в паре называем тот меш, который маску и
        # носит: какую из девяти на нём показать, решает альбом (см. card_mesh)
        scene = self._extract_multi_textures(mat_names) if mat_names else {}
        if scene:
            worn = [m for m in mat_names if m in set(SPY_MASK_VTF_NAMES)]
            self.scene_extra.emit((scene, worn))
        self.multi_material.emit(masks)

    def _emit_hat_textures(self, obj_path: str, mat_names: list) -> None:
        """Шапки: QC -> VMT -> $baseTexture -> VTF (+ BLU через skinfamilies skin 1)"""
        _qc_dir = self._hat_decomp_dir
        if not _qc_dir:
            from src.services import decompile_cache as _dc
            _cached_qc = _dc.find_cached_qc_for_weapon(self.weapon_key)
            if _cached_qc:
                _qc_dir = os.path.dirname(_cached_qc)

        hat_tex_map: dict = {}
        if _qc_dir and mat_names:
            try:
                hat_tex_map = self._extract_hat_textures_via_qc_vmt(
                    _qc_dir, mat_names
                )
            except Exception as exc:
                logger.warning(f"[3D] Ошибка QC→VMT→VTF: {exc}")

        if hat_tex_map:
            first_tex = next(iter(hat_tex_map.values()))
            self.ready.emit(obj_path, first_tex)
            if len(hat_tex_map) > 1:
                self.multi_material.emit(hat_tex_map)
        else:
            # Fallback: угадываем VTF по имени MDL
            logger.debug("[3D] QC→VMT не дал результата, используем fallback")
            frame_paths, _ = self._extract_hat_texture_frames()
            self.ready.emit(obj_path, frame_paths[0] if frame_paths else "")

        if self.isInterruptionRequested():
            return

        if _qc_dir:
            # Сначала пробуем по материалам: у многоматериальной шапки команда
            # меняет не все из них, и одна общая BLU-текстура легла бы на все
            # меши сразу (линза Alcoholic Automaton получала корпус)
            raw = self._extract_hat_blu_textures(_qc_dir, mat_names)
            if raw:
                tex_map = {m: png for m, (png, _n) in raw.items() if png}
                name_map = {m: n for m, (_p, n) in raw.items() if n}
                self.blu_multi_material.emit((tex_map, name_map))
                logger.info(
                    f"[3D] BLU шапки по материалам: {len(tex_map)} текстур "
                    f"из {len(mat_names)}"
                )
                # Одноматериальная шапка (Battle Balaclava «No Gloves»):
                # карточек нет, и панель ищет BLU не по имени материала, а
                # кадром. Без этого поле синей команды оставалось пустым.
                # Считаем материалы так же, как панель считает карточки:
                # служебные меши (глаза, sheen) карточку не получают
                from src.data.material_filter import is_editable_material
                _editable = [m for m in mat_names if is_editable_material(m)]
                if len(tex_map) == 1 and len(_editable or mat_names) <= 1:
                    self.blu_ready.emit(list(tex_map.values()), 0.0)
            elif not mat_names:
                # Карта по материалам решает сама, даже когда отличий нет.
                # Одна BLU-текстура на модель - только если материалов не знаем
                blu_paths, blu_fps = self._extract_blu_via_qc(
                    _qc_dir, 0.0, mat_names)
                if blu_paths:
                    self.blu_ready.emit(blu_paths, blu_fps)

    def _emit_weapon_textures(self, obj_path: str, mat_names: list) -> None:
        """Обычное оружие: текстуры + BLU/Australium через QC skinfamilies"""
        # Доп. текстуры по фиксированному пути (вне QC/модели), напр.
        # HUD-вставки Dead Ringer (pocket_watch_fg/bg)
        fixed_extras = self._extract_fixed_extra_textures()
        # Материалы из QC $texturegroup, которых нет в геометрии
        # (напр. smiley у гранатомёта) - чтобы карточки 2D совпадали
        # с тем, что предлагает сборка
        tg_extras = self._extract_texturegroup_extras(mat_names)

        # Служебные материалы $texturegroup вне геометрии - для «Прочее»
        misc_extras = self._extract_texturegroup_misc_extras(mat_names)
        # Чужие материалы модели (руки шпиона во вьюмодели часов) - не
        # карточки: сборка их не пишет, правка ушла бы в никуда
        from src.data.weapon_quirks import is_own_material
        tg_extras = {m: p for m, p in tg_extras.items() if is_own_material(self.weapon_key, m)}
        misc_extras = {m: p for m, p in misc_extras.items() if is_own_material(self.weapon_key, m)}

        # Игровые текстуры косметических стилей - не карточки базы, а
        # переопределения самих стилей
        style_textures = self._extract_style_textures()

        if len(mat_names) > 1:
            # Мульти-материальное оружие (shell, scope и т.п.)
            tex_map = self._extract_multi_textures(mat_names)
            if fixed_extras:
                tex_map.update(fixed_extras)
            if tg_extras:
                tex_map.update(tg_extras)
            if misc_extras:
                tex_map.update(misc_extras)
            first_tex = next(iter(tex_map.values()), "") if tex_map else ""
            self.ready.emit(obj_path, first_tex)
            if tex_map:
                self.multi_material.emit(tex_map)
            framerate = 0.0
        else:
            # Одиночная текстура (возможно анимированная)
            frame_paths, framerate = self._extract_texture_frames(mat_names)
            first_tex = frame_paths[0] if frame_paths else ""
            self.ready.emit(obj_path, first_tex)
            # Главная текстура + доп. (фиксированные и из $texturegroup) -> карточки 2D
            extra_cards: dict = {}
            extra_cards.update(fixed_extras)
            extra_cards.update(tg_extras)
            if extra_cards:
                combined: dict = {}
                main_name = mat_names[0] if mat_names else self.weapon_key
                if first_tex:
                    combined[main_name] = first_tex
                combined.update(extra_cards)
                if len(combined) > 1:
                    self.multi_material.emit(combined)
            elif len(frame_paths) > 1:
                self.animated.emit(frame_paths, framerate)

        if style_textures:
            self.skin_textures.emit(style_textures)

        if self.isInterruptionRequested():
            return

        # BLU + Australium через QC skinfamilies
        blu_paths, blu_fps = [], 0.0
        blu_multi_done = False
        # Материалы, которые в итоге ПОКАЗЫВАЮТСЯ: геометрия плюс добавки из
        # $texturegroup. Командной бывает только добавка - граната у quadball,
        # ядро у cannon, руки шпиона у часов, их геометрия одноматериальная, и
        # по одному имени модели BLU для них не искался вовсе
        card_names = list(dict.fromkeys(
            list(mat_names) + list(tg_extras) + list(fixed_extras)))
        if self._decomp_dir:
            # Мульти-материальное командное оружие (напр. праздничное:
            # клинок и lights меняются по команде в РАЗНЫХ колонках
            # $texturegroup) - BLU строим как карту {материал: blu_png}.
            # Одиночный BLU тут наложил бы одну текстуру на всю модель
            if len(card_names) > 1:
                _model = self._model(self._decomp_dir)
                if _model and _model.spec.team:
                    try:
                        raw = self._extract_blu_multi_textures_via_qc(card_names)
                        tex_map  = {k: v[0] for k, v in raw.items() if v[0]}
                        name_map = {k: v[1] for k, v in raw.items()}
                        if name_map:
                            self.blu_multi_material.emit((tex_map, name_map))
                            blu_multi_done = True
                    except Exception as _exc:
                        logger.debug(f"[3D] BLU multi (оружие): {_exc}")
            if not blu_multi_done:
                blu_paths, blu_fps = self._extract_blu_via_qc(
                    self._decomp_dir, framerate, mat_names
                )
            # Вариантные строки (Australium/Gold/Festive) проверяем
            # НЕЗАВИСИМО от BLU: у большинства австралиум-оружий
            # (ракетница и т.п.) есть И команды, И gold-строки, и
            # «if not blu_paths» скрыл бы вариант
            aus_path, aus_mat = self._extract_variant_via_qc(self._decomp_dir)
            if aus_path:
                self.australium_ready.emit(aus_path, aus_mat or "")
        # Fallback: прямой поиск {wk}_blue.vtf
        if not blu_multi_done and not blu_paths:
            blu_paths, blu_fps = self._extract_blu_texture_frames(framerate)
        if blu_paths:
            self.blu_ready.emit(blu_paths, blu_fps)

    # Получение SMD (поиск - src/services/smd_locator.py)

    def _get_reference_smd(self) -> Optional[str]:
        """Возвращает reference SMD из кэша или после декомпиляции"""
        mdl_rel = smd_locator.mdl_rel_path(self.mode, self.weapon_key)
        result = model_decompile_service.ensure_decompiled(
            self.weapon_key,
            self.misc_vpk_path,
            smd_locator.mdl_candidates(self.mode, self.weapon_key,
                                       self.misc_vpk_path, mdl_rel),
            cancelled=self.isInterruptionRequested,
            on_progress=self._emit_decompile_stage,
        )
        if result is None:
            return None
        return smd_locator.find_reference_smd(
            result.directory, self.mode, self.weapon_key, self._model)

    def _carrier_smds(self) -> list:
        """SMD пушки-носителя, если модель на ней висит. См. carrier_model"""
        # Только у оружия: у шапок и персонажей weapon_key - путь к MDL, и
        # носителя у них не бывает
        if self.kind.is_hat or self.kind.is_character or self.kind.is_spy_mask:
            return []
        from src.data.weapon_model_index import tf2_root_from_misc_vpk
        from src.services import carrier_model
        found = carrier_model.find(
            self.weapon_key, self.misc_vpk_path,
            tf2_root_from_misc_vpk(self.misc_vpk_path),
            cancelled=self.isInterruptionRequested,
            on_progress=self._emit_decompile_stage,
        )
        self._carrier_dir = found.directory or None
        return list(found.smds)

    def _emit_decompile_stage(self, stage: model_decompile_service.Stage) -> None:
        """Стадия из сервиса -> переведённая строка прогресса"""
        self.progress.emit(self._p[stage.value])

    def _find_bodygroup_smds(self, reference_smd_path: str) -> list:
        """Доп. SMD модели (smd_locator.bodygroup_smds), снаряд - в _late_smds"""
        smds, self._late_smds = smd_locator.bodygroup_smds(
            reference_smd_path, self.bodygroups, self.mode, self._model)
        return smds

    def _swap_reference_for_choice(self, smd_path: str, bodygroup_smds: list) -> str:
        """Основной SMD по переключателю бодигрупп (smd_locator)"""
        return smd_locator.swap_reference_for_choice(
            smd_path, bodygroup_smds, self.bodygroups, self._model)

    # Текстуры: поиск в VPK - src/services/texture_locator.py

    def _extract_multi_textures(self, mat_names: list) -> dict:
        """
        Для каждого имени материала из SMD ищет VTF в VPK и сохраняет как PNG

        Returns:
            {mat_name: png_path} - только для найденных текстур
        """
        result: dict = {}
        try:
            # Кэширующий reader открывает оба VPK один раз: VTF обычно в textures,
            # VMT (для материалов с $basetexture) - чаще в misc
            paks = self._reader.paks
            if not paks:
                return result
            # Руки и тела ищутся сначала в папке игрока - это покрывает и руки,
            # и рукав костюма
            arm_folder = texture_locator.player_folder(self.mode, self.weapon_key)
            # Пути материалов из QC ($cdmaterials) - авторитетный источник для
            # оружия: позволяет найти ВСЕ материалы модели (вторая текстура и т.п.),
            # даже если их папка не совпадает с именем материала
            cdmats = self._get_qc_cdmaterials()

            for mat_name in mat_names:
                vtf_data = texture_locator.material_vtf(paks, mat_name, arm_folder, cdmats)
                if not vtf_data:
                    logger.warning(f"[3D] Текстура для материала '{mat_name}' не найдена")
                    continue
                png_path = self._vtf_data_to_png(vtf_data, mat_name)
                if not png_path:
                    continue
                # Краска материала ($blendtintbybasealpha) - у пяти стоковых
                # пушек (Cow Mangler, Lollichop, праздничные) окрашиваемые
                # места в текстуре тоже лежат почти чёрными
                vmt_tint.apply_to_png(
                    png_path, self.materials.tint_for(mat_name, cdmats))
                result[mat_name] = png_path
                logger.debug(f"[3D] Материал '{mat_name}' → {os.path.basename(png_path)}")

        except Exception as exc:
            logger.warning(f"[3D] Ошибка извлечения мульти-текстур: {exc}", exc_info=True)

        return result

    def _extract_blu_multi_textures_via_qc(self, mat_names: list) -> dict:
        """
        Для каждого материала из SMD - BLU-вариант через QC skinfamilies
        (столбец материала в строке 0 -> тот же столбец строки 1)

        Returns:
            {red_mat_name: (blu_png_path | None, blu_display_name)}; без PNG -
            когда VTF не нашёлся, но имя BLU отличается (для подписей карточек).
            Пустой dict если BLU варианта нет
        """
        if not self._decomp_dir or not mat_names:
            return {}
        model = self._model(self._decomp_dir)
        if model is None:
            return {}
        if not model.layout.second_row or not model.cdmaterials:
            logger.debug(
                "[3D] _extract_blu_multi_textures_via_qc: "
                "второй скин в QC не найден → нет BLU варианта"
            )
            return {}

        result: dict = {}
        try:
            paks = self._reader.paks
            if not paks:
                return {}
            from src.data.player_characters import PLAYER_CHARACTERS
            arm_folder = PLAYER_CHARACTERS.get(self.mode, {}).get("folder", "")

            for mat_name, blu_tex_name, vtf_data in texture_locator.blu_multi_sources(
                    paks, model, mat_names, arm_folder):
                if not vtf_data:
                    logger.debug(f"[3D] BLU multi: VTF не найден для '{blu_tex_name}'")
                    # VTF нет, но маппинг имён всё равно записываем - чтобы карточки
                    # показывали BLU-имена даже без превью-текстуры
                    if blu_tex_name.lower() != mat_name.lower():
                        result[mat_name] = (None, blu_tex_name)
                    continue
                png_path = self._vtf_data_to_png(vtf_data, f"blu_{mat_name}")
                if not png_path:
                    continue
                result[mat_name] = (png_path, blu_tex_name)
                logger.debug(
                    f"[3D] BLU multi: '{mat_name}' → '{blu_tex_name}' "
                    f"({os.path.basename(png_path)})"
                )

        except Exception as exc:
            logger.warning(f"[3D] _extract_blu_multi_textures_via_qc: {exc}", exc_info=True)

        return result

    def _extract_fixed_extra_textures(self) -> dict:
        """
        Доп. текстуры предмета по ФИКСИРОВАННОМУ пути в VPK (вне QC и
        геометрии) - см. WEAPON_EXTRA_TEXTURES. Пример: HUD-вставки Dead
        Ringer pocket_watch_fg/bg

        Returns:
            {material_name: png_path}; слот без оригинала - пустой плейсхолдер
        """
        from src.data.weapon_quirks import WEAPON_EXTRA_TEXTURES
        extras = WEAPON_EXTRA_TEXTURES.get(self.weapon_key, [])
        if not extras:
            return {}

        result: dict = {}
        try:
            paks = self._reader.paks
            for ex in extras:
                data = texture_locator.fixed_extra_vtf(paks, ex)
                png = self._vtf_data_to_png(data, ex["name"]) if data else None
                # Слот предлагаем ВСЕГДА - даже без оригинала (пустой плейсхолдер)
                if not png:
                    png = self._make_blank_png(ex["name"])
                    logger.info(f"[3D] Фикс. доп. текстура без оригинала - пустой слот: {ex['name']}")
                if png:
                    result[ex["name"]] = png
        except Exception as exc:
            logger.warning(f"[3D] Ошибка извлечения фикс. доп. текстур: {exc}", exc_info=True)
        return result

    def _extract_texturegroup_extras(self, mat_names: list) -> dict:
        """
        Материалы из QC $texturegroup вне геометрии (texture_locator.
        texturegroup_extras) - карточками, как их предлагает сборка

        Returns:
            {material_name: png_path}; не нашли текстуру - пустой слот
        """
        if not self._decomp_dir:
            return {}
        try:
            model = self._model(self._decomp_dir)
            if model is None:
                return {}
            missing = texture_locator.texturegroup_extras(model.qc_path, mat_names)
            if not missing:
                return {}
            logger.info(f"[3D] Доп. материалы из $texturegroup (вне геометрии): {missing}")
            return self._textures_or_blank(missing)
        except Exception as exc:
            logger.debug(f"[3D] Не удалось собрать доп. материалы $texturegroup: {exc}")
            return {}

    def _extract_style_textures(self) -> dict:
        """
        Игровые текстуры косметических стилей: {индекс скина: {базовый материал: png}}

        Строка стиля выровнена по колонкам со строкой 0, поэтому её материал -
        это замена базового, а не отдельный материал модели: в общем списке
        карточек у Летающей гильотины базовый альбом показал бы две текстуры
        (свою и Bloody), а вкладка стиля - ни одной

        Форма ответа та же, что у мода из VPK (``_build_skin_textures``), -
        сеанс раскладывает их переопределениями стиля одним и тем же кодом
        """
        if not self._decomp_dir:
            return {}
        try:
            model = self._model(self._decomp_dir)
            if model is None:
                return {}
            from src.data.item_skin_styles import item_skin_styles
            from src.data.weapon_model_index import tf2_root_from_misc_vpk
            root = tf2_root_from_misc_vpk(self.misc_vpk_path)
            item_rows = item_skin_styles(root).get((self.weapon_key or "").lower(), {}) \
                if root else {}
            wanted, names = texture_locator.style_pairs(model.layout, list(item_rows))
            if not wanted:
                return {}
            resolved = self._extract_multi_textures(names)
            out: dict = {}
            for idx, pairs in wanted.items():
                mp = {base: resolved[var] for base, var in pairs.items()
                      if resolved.get(var)}
                if mp:
                    out[idx] = mp
            if out:
                logger.info(f"[3D] текстуры стилей из $texturegroup: "
                            f"{ {i: sorted(m) for i, m in out.items()} }")
            return out
        except Exception as exc:
            logger.debug(f"[3D] текстуры стилей не собраны: {exc}")
            return {}

    def _extract_texturegroup_misc_extras(self, mat_names: list) -> dict:
        """Служебные материалы $texturegroup вне геометрии (eyeball_invun,
        *_zombie …) - оригинальные текстуры для селектора «Прочее» в 2D

        Returns: {material_name: png_path} (с прозрачным плейсхолдером, если
        оригинал по путям модели не нашёлся)
        """
        if not self._decomp_dir:
            return {}
        try:
            model = self._model(self._decomp_dir)
            if model is None:
                return {}
            misc = texture_locator.texturegroup_misc(model.layout, mat_names)
            if not misc:
                return {}
            logger.info(f"[3D] Служебные материалы $texturegroup (для «Прочее»): {misc}")
            return self._textures_or_blank(misc)
        except Exception as exc:
            logger.debug(f"[3D] Не удалось собрать служебные материалы $texturegroup: {exc}")
            return {}

    def _textures_or_blank(self, names: list) -> dict:
        """{материал: png} по списку, не нашли - прозрачный плейсхолдер"""
        resolved = self._extract_multi_textures(names)
        result: dict = {}
        for m in names:
            png = resolved.get(m) or self._make_blank_png(m)
            if png:
                result[m] = png
        return result

    def _make_blank_png(self, name: str) -> Optional[str]:
        """Создаёт пустой прозрачный PNG-плейсхолдер (для слота без оригинала)"""
        try:
            from PIL import Image
            img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
            png_path = os.path.join(self._preview_dir, f"{name}.png")
            img.save(png_path)
            return png_path
        except Exception as exc:
            logger.debug(f"[3D] Не удалось создать плейсхолдер для {name}: {exc}")
            return None

    def _get_qc_cdmaterials(self) -> list:
        """
        Возвращает список путей $cdmaterials из QC декомпилированной модели
        (без 'materials/' и слешей по краям). Кэшируется. Нужен чтобы найти
        текстуры ВСЕХ материалов оружия по авторитетным путям из QC
        """
        if self._cached_cdmaterials is not None:
            return self._cached_cdmaterials
        cdmats: list = []
        try:
            model = self._model(self._decomp_dir)
            if model:
                cdmats = list(model.cdmaterials)
            # У пушки-носителя путь материалов свой: гирлянда лежит в папке
            # оружия, а сама пушка - в своей. Ищем по обеим, порядок значения
            # не имеет: имена материалов не пересекаются
            carrier = self._model(self._carrier_dir)
            if carrier:
                cdmats += [c for c in carrier.cdmaterials if c not in cdmats]
        except Exception as exc:
            logger.debug(f"[3D] Не удалось распарсить $cdmaterials: {exc}")
        self._cached_cdmaterials = cdmats
        return cdmats

    # BLU и вариант через QC skinfamilies (см. qc_skin_parser)

    def _extract_blu_via_qc(self, decomp_dir: str, red_framerate: float,
                            mat_names: Optional[list] = None) -> tuple:
        """
        Одна BLU-текстура на модель по QC $texturegroup skinfamilies: какие
        имена - texture_locator.blu_tex_names, где лежит - blu_vtf

        Args:
            mat_names: материалы, которые реально показаны в превью (без них
                синей текстурой предмета становились чужие руки вьюмодели)

        Returns:
            (frame_paths: list[str], framerate: float)
            Пустой список если BLU варианта нет
        """
        model = self._model(decomp_dir)
        if model is None:
            logger.debug(f"[3D] _extract_blu_via_qc: QC не найден в {decomp_dir}")
            return [], 0.0

        cdmaterials = model.cdmaterials
        blu_tex_names = texture_locator.blu_tex_names(model, mat_names, self.weapon_key)
        if not blu_tex_names:
            return [], 0.0

        logger.info(
            f"[3D] QC BLU skin family: cdmaterials={cdmaterials}, "
            f"tex_names={blu_tex_names}"
        )

        try:
            paks = self._reader.paks
            if not paks:
                return [], 0.0

            for tex_name in blu_tex_names:
                vtf_data, blu_look = texture_locator.blu_vtf(paks, cdmaterials, tex_name)
                if not vtf_data:
                    logger.debug(
                        f"[3D] BLU VTF не найден для '{tex_name.lower()}' "
                        f"(cdmaterials={cdmaterials})"
                    )
                    continue

                frame_paths = self._frames(vtf_data, "texture_blu")
                if not frame_paths:
                    continue

                # Синий материал может отличаться от красного ТОЛЬКО краской
                # в VMT (329 стоковых шапок) - без её применения переключатель
                # команд показывал бы две одинаковые картинки
                if blu_look is not None:
                    for frame in frame_paths:
                        vmt_tint.apply_to_png(frame, blu_look[1])

                fps = red_framerate if len(frame_paths) > 1 else 0.0
                logger.info(
                    f"[3D] BLU via QC: {len(frame_paths)} frame(s) "
                    f"@ {fps:.1f} fps для {self.weapon_key}"
                )
                return frame_paths, fps

        except Exception as exc:
            logger.warning(f"[3D] _extract_blu_via_qc: {exc}", exc_info=True)

        return [], 0.0

    def _extract_variant_via_qc(self, decomp_dir: str) -> tuple:
        """
        Текстура варианта оружия (Australium/Gold/Festive) из QC - см.
        texture_locator.variant_name

        Returns:
            (путь к PNG, имя текстуры) или (None, None)
        """
        model = self._model(decomp_dir)
        variant_tex = texture_locator.variant_name(model)
        if not variant_tex:
            return None, None
        try:
            vtf_data = texture_locator.read_in_cdmaterials(
                self._reader.paks, model.cdmaterials, variant_tex)[0]
            if not vtf_data:
                return None, None
            out = self._vtf_data_to_png(vtf_data, "texture_variant")
            if not out:
                return None, None
            logger.info(f"[3D] Вариант оружия извлечён: {out}")
            return out, variant_tex
        except Exception as exc:
            logger.warning(f"[3D] _extract_variant_via_qc: {exc}")
            return None, None

    # Состояние прогона: резолвер, разбор QC, запись PNG
    @property
    def materials(self) -> MaterialResolver:
        """Единая цепочка «материал -> PNG» с кэшем на весь прогон"""
        if self._materials is None:
            self._materials = MaterialResolver(self._reader, self._preview_dir)
        return self._materials

    def _model(self, decomp_dir: Optional[str]):
        """Разбор QC этой папки - один раз за прогон (см. QcModel)

        None на входе (папки декомпиляции ещё нет) - None на выходе, чтобы
        вызывающим не приходилось проверять это перед каждым обращением
        """
        if not decomp_dir:
            return None
        if decomp_dir not in self._models:
            self._models[decomp_dir] = qc_skin_parser.load_model(decomp_dir)
        return self._models[decomp_dir]

    def _vtf_data_to_png(self, vtf_data: bytes, name: str) -> Optional[str]:
        """
        Сохраняет VTF-байты как PNG в preview_dir.
        Возвращает путь к PNG или None при ошибке
        """
        from src.services import vtf_preview_service as _vps
        return _vps.vtf_bytes_to_png(
            vtf_data, os.path.join(self._preview_dir, f"{name}.png"), self._preview_dir)

    def _frames(self, vtf_data: bytes, base_name: str) -> list:
        """Все кадры VTF -> PNG в preview_dir (у анимированной текстуры их много)"""
        from src.services import vtf_preview_service as _vps
        return _vps.vtf_bytes_to_frame_pngs(vtf_data, self._preview_dir, base_name)

    # Шапки

    def _extract_hat_blu_textures(self, decomp_dir: str, mat_names: list) -> dict:
        """
        BLU-текстуры шапки ПО МАТЕРИАЛАМ: {red_mat: (png | None, blu_mat_name)}

        Шапка часто многоматериальная, и команда переключает НЕ ВСЁ. У
        hwn2022_alcoholic_automaton в $texturegroup четыре столбца, и линза в
        обеих строках одна и та же:

            { auto_1       auto       auto_1_blue auto_blue }
            { auto_1_blue  auto_blue  auto_1_blue auto_blue }

        Одна общая BLU-текстура (путь _extract_blu_via_qc) натянула бы на
        линзу текстуру корпуса. Здесь каждый материал берёт свой столбец -
        те, что в обеих строках одинаковы, так и остаются прежними

        Returns:
            {} - если второй скин не команда, QC не читается или ничего не нашли
        """
        model = self._model(decomp_dir)
        if not model or not mat_names or not model.cdmaterials:
            return {}
        # Карта «столбец RED -> столбец BLU», пустая, если второй скин не
        # команда (стиль bloody/clean) - тот же авторитет, что у сборки
        by_lower = {k.lower(): v for k, v in model.team_map.items()}
        if not by_lower:
            return {}

        result: dict = {}
        twins: dict = {}
        for mat_name in mat_names:
            mat_lower = mat_name.lower()
            blu_name = texture_locator.team_partner(by_lower, mat_lower)
            if blu_name is None:
                continue
            if qc_skin_parser.is_shared_column(mat_lower, blu_name):
                # Материал в обеих строках один и тот же: на BLU он остаётся
                # собой. Записываем это явно - по такой «ссылке на себя»
                # панель понимает, что карточку при смене команды не трогать
                result[mat_lower] = (None, mat_name)
                continue

            blu = self.materials.resolve(blu_name, model.cdmaterials,
                                         out_name=f"blu_{mat_lower}")
            png_path = blu.png_path
            red = self._red_looks.get(mat_lower)
            # Развёртку читаем, только когда решают пиксели: обычно VMT
            # различаются краской, и SMD не нужны
            tris = (self._uv_tris(decomp_dir, model).get(mat_lower)
                    if red is not None and red.params == blu.params
                    and red.basetexture != blu.basetexture else None)
            if png_path and team_twins.is_twin(red, blu, tris):
                # Числится командным, а выглядит точно как RED - для панели
                # это такой же общий материал, а сборка отдаст ему правку RED
                twins[blu_name] = mat_name
                png_path, blu_name = None, mat_name
            elif not png_path:
                # Материал командный, но его текстуру в игре не нашли. Показать
                # нечего, и пометить его командным значит оставить пустое поле
                # у синей команды - честнее считать материал общим
                logger.info(
                    f"[3D] BLU-текстура '{blu_name}' не найдена - материал "
                    f"'{mat_lower}' показываем общим для команд"
                )
                blu_name = mat_name
            result[mat_lower] = (png_path, blu_name)

        if twins:
            logger.info(f"[3D] BLU выглядит как RED: {sorted(twins)}")
            self.blu_same_as_red.emit(twins)
        # Ни одной реальной BLU-текстуры: в игре команды не отличаются, и
        # переключателю нечего показывать
        if not any(png for png, _ in result.values()):
            return {}
        return result

    def _uv_tris(self, decomp_dir: str, model) -> dict:
        """Треугольники развёртки по материалам - один разбор SMD за прогон"""
        if decomp_dir not in self._uv_cache:
            from src.services.model_build_service import ModelBuildService
            try:
                smds = ModelBuildService.extract_all_mesh_smds(model.qc_path)
            except Exception as exc:
                logger.debug(f"[3D] SMD модели для развёртки: {exc}")
                smds = []
            self._uv_cache[decomp_dir] = team_twins.uv_triangles(smds)
        return self._uv_cache[decomp_dir]

    def _extract_hat_textures_via_qc_vmt(
        self, decomp_dir: str, mat_names: list
    ) -> dict:
        """
        Текстуры шапки: материалы модели -> цепочка VMT -> $basetexture -> VTF

        Сама цепочка (включая командную краску из VMT) живёт в
        MaterialResolver - здесь только выбор материалов и запоминание того,
        как выглядит RED: по этому потом видно, отличается ли BLU-скин

        Returns:
            {mat_name: png_path}  (пустой dict если ничего не нашлось)
        """
        model = self._model(decomp_dir)
        if not model or not model.cdmaterials:
            logger.warning(f"[3D] $cdmaterials не найден в QC: {decomp_dir}")
            return {}

        logger.info(
            f"[3D] Hat QC: cdmaterials={model.cdmaterials}, materials={mat_names}")

        result: dict = {}
        for mat_name in mat_names:
            mat_lower = mat_name.lower()
            res = self.materials.resolve(mat_lower, model.cdmaterials,
                                         out_name=f"hat_{mat_lower}")
            if res.ok:
                self._red_looks[mat_lower] = res
                result[mat_lower] = res.png_path
        return result

    def _extract_hat_texture_frames(self) -> tuple:
        """
        Fallback: VTF шапки, угаданный по имени MDL (texture_locator.
        hat_vtf_paths). Только если путь QC->VMT->VTF ничего не дал

        Returns:
            (frame_paths: list[str], framerate: float)
        """
        try:
            vtf_paths = texture_locator.hat_vtf_paths(self.weapon_key)
            # Ищем в текстурах VPK, затем в misc VPK (порядок reader.paks)
            vtf_data: Optional[bytes] = None
            for pak in self._reader.paks:
                vtf_data, path = texture_locator.read_first(pak, vtf_paths)
                if vtf_data:
                    logger.debug(f"[3D] Hat texture: {path}")
                    break

            if not vtf_data:
                shown = vtf_paths[:4]
                logger.warning(
                    f"[3D] Текстура шапки не найдена (weapon_key={self.weapon_key}). "
                    f"Проверено путей: {len(vtf_paths)}, первые: {shown}"
                )
                return [], 0.0
            return self._frames(vtf_data, "hat_tex"), 0.0

        except Exception as exc:
            logger.warning(f"[3D] Не удалось извлечь текстуру шапки: {exc}")
            return [], 0.0

    def _extract_spy_mask_texture(self, mask_vtf_name: str) -> tuple:
        """Извлекает текстуру маски шпиона из VPK

        Args:
            mask_vtf_name: имя VTF без расширения (напр. 'mask_spy', 'mask_scout')

        Returns:
            (frame_paths, framerate) - стандартный формат как у других методов
        """
        try:
            from src.services import vtf_preview_service as _vps
            paks = _vps.open_vpks([self.textures_vpk_path, self.misc_vpk_path])
            vtf_data = _vps.read_from_vpks(
                paks, f"materials/models/player/spy/{mask_vtf_name}.vtf")
            if not vtf_data:
                logger.warning(f"[3D] Маска {mask_vtf_name}.vtf не найдена в VPK")
                return [], 0.0
            png_path = self._vtf_data_to_png(vtf_data, mask_vtf_name)
            if not png_path:
                return [], 0.0
            logger.info(f"[3D] Маска шпиона извлечена: {png_path}")
            return [png_path], 0.0
        except Exception as exc:
            logger.warning(f"[3D] _extract_spy_mask_texture: {exc}", exc_info=True)
            return [], 0.0

    # Одна текстура оружия (возможно анимированная)

    def _extract_texture_frames(self, mat_names: Optional[list] = None) -> tuple:
        """
        Извлекает VTF текстуру из VPK

        Если VTF содержит несколько кадров (анимированная текстура) -
        сохраняет каждый кадр отдельным PNG и читает framerate из VMT

        ``mat_names`` - материалы геометрии В КАДРЕ: текстуру ищем прежде
        всего для них (см. texture_locator.red_vtf_via_qc)

        Returns:
            (frame_paths: list[str], framerate: float)
            frame_paths пустой если текстура не найдена
        """
        if self.mode == "hat":
            return self._extract_hat_texture_frames()

        # Режим масок шпиона: извлекаем mask_spy.vtf по умолчанию
        if self.kind.is_spy_mask:
            return self._extract_spy_mask_texture("mask_spy")

        try:
            vtf_search = texture_locator.weapon_vtf_search(self.weapon_key)
            vmt_search = [p.replace(".vtf", ".vmt") for p in vtf_search]

            paks_tex = self._reader.paks
            pak = paks_tex[0] if paks_tex else None
            vtf_data: Optional[bytes] = None

            # Сначала - путь из QC ТОЙ модели, которую показываем
            # У части оружия в игре ДВЕ версии: старая в models/weapons/c_items
            # и мастерская в models/workshop/weapons/c_models. Геометрию мы
            # берём по MDL модели, а список ниже перебирается по порядку, и
            # c_items стоит в нём раньше workshop - у c_shortstop и
            # c_soda_popper из-за этого бралась текстура 512×512 от СТАРОЙ
            # версии, а развёртка была от мастерской. Текстура не совпадала с
            # моделью. $cdmaterials из QC указывает на материалы именно той
            # модели, поэтому спрашиваем его первым
            if self._decomp_dir:
                vtf_data = texture_locator.red_vtf_via_qc(
                    paks_tex, self._model(self._decomp_dir), self.weapon_key, mat_names)
                if vtf_data:
                    logger.debug("3D Preview текстура: по $cdmaterials из QC")

            if pak and not vtf_data:
                vtf_data, path = texture_locator.read_first(pak, vtf_search)
                if vtf_data:
                    logger.debug(f"3D Preview текстура: {path}")

            if not vtf_data:
                logger.warning(f"Текстура для {self.weapon_key} не найдена в VPK")
                return [], 0.0

            frame_paths = self._frames(vtf_data, "texture")

            # Краска из VMT: без неё окрашиваемые места показываются чёрными
            tint = texture_locator.tint_from_vmt_paths(paks_tex, vmt_search)
            if tint is not None:
                for frame in frame_paths:
                    vmt_tint.apply_to_png(frame, tint)

            # Framerate из VMT
            framerate = 0.0
            if len(frame_paths) > 1:
                from src.services import vtf_preview_service as _vps
                framerate = _vps.read_vmt_framerate(
                    paks_tex[0] if paks_tex else None, vmt_search)
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
        Пробует найти BLU-вариант текстуры (суффикс _blue) в VPK

        Возвращает (frame_paths: list[str], framerate: float).
        Если BLU текстура не найдена - возвращает ([], 0.0)
        """
        try:
            vtf_data: Optional[bytes] = None
            for path in texture_locator.weapon_blu_vtf_search(self.weapon_key):
                vtf_data = self._reader.read(path)
                if vtf_data:
                    logger.debug(f"3D Preview BLU текстура: {path}")
                    break

            if not vtf_data:
                return [], 0.0

            frame_paths = self._frames(vtf_data, "texture_blu")
            if not frame_paths:
                return [], 0.0

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
