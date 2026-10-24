"""
Сборка мода из показанного предмета: что собирать берётся из сеанса, вопросы
сборки (недостающая текстура, сменная часть модели) уходят странице и
возвращаются ответом

Доступ - `session().building`; `api/building.py` зовёт его методы напрямую
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.shared.logging_config import get_logger
from src.shared.validators import vpk_file_name

if TYPE_CHECKING:
    from src.app.session import AppSession

logger = get_logger(__name__)

#: «Ответа ещё нет» для запомненного выбора текстуры. Отдельный сторож, потому
#: что сам ответ бывает None - это «взять главную текстуру»
_NO_CHOICE = object()


def _part_kind(smd_name: str) -> str:
    """Что за сменная часть - по имени SMD. Пусто, если по имени не понять"""
    name = (smd_name or '').lower()
    if 'exploded' in name:
        return 'exploded'
    if 'broken' in name:
        return 'broken'
    return ''


class BuildEditor:
    """Сборка VPK, её отмена и ответы на вопросы воркера"""

    def __init__(self, host: "AppSession") -> None:
        self._host = host
        #: Воркер сборки. Один на сеанс: две сборки разом писали бы в одну
        #: временную папку
        self._build = None
        #: Запомненный ответ «применить ко всем» для недостающих текстур.
        #: Живёт одну сборку: следующая спрашивает заново. Сравнивать с None
        #: нельзя - None и есть один из ответов («взять главную»), поэтому
        #: «ответа ещё нет» помечено своим сторожем
        self._texture_choice = _NO_CHOICE

    def build(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Собирает VPK из текущего состояния превью

        Параметры формата приходят от страницы, а ЧТО именно собирать - из
        сеанса: какие текстуры пользователь положил на какие материалы. Второй
        раз спрашивать это у представления незачем, оно и так лишь отражение

        Шаги: свои картинки из превью (`_build_images`) -> испечённые склейки
        частей -> вопрос про краску игры (`_answer_tint`) -> запрос сборки
        (`_build_request`) -> воркер (`_start_build`). Любой шаг до воркера
        может вернуть ответ странице: ошибку или вопрос
        """
        if self._build is not None and self._build.isRunning():
            return {'error': 'Сборка уже идёт'}

        paths = self._host.tf2_paths()
        if 'error' in paths:
            return paths

        mode = getattr(self._host, '_mode', '')
        if not mode:
            return {'error': 'Сначала выберите предмет'}

        images = self._build_images(mode, paths, params)
        if isinstance(images, dict):
            return images
        # Гифка на части: превью держит один кадр, сборке нужны все. Полные
        # склейки печёт воркер (это десятки секунд), а запрос уже смотрит на
        # их будущие пути
        plan = self._host.parts.bake_plan([images.image, *images.extra.values(),
                                     *self._host.preview.textures.blu_uploaded_paths().values(),
                                     *images.decor_paths(), *images.part_paths(),
                                     *images.style_paths()])
        images.remap(self._host.parts.baked_path, decor=True)
        question = self._answer_tint(images, mode, params)
        if question:
            return question
        return self._start_build(self._build_request(images, mode, paths, params), plan)

    def _build_images(self, mode: str, paths: Dict[str, str],
                      params: Dict[str, Any]) -> Any:
        """Свои картинки сборки из превью (BuildImages) или ответ странице:
        ошибка, если собирать нечего, или {'confirm_empty'} - «изменений нет,
        всё равно собрать?»"""
        from src.app.build_images import BuildImages
        from src.data.skyboxes import SKYBOX_MODE

        t = self._host.preview.textures
        # Главная текстура - то, что лежит на главном материале модели
        main = t.stable_main()
        image = t.uploaded_for_mat(main) if main else None
        # Картинки материалов частей едут своим полем (спеки частей): у них
        # своя картинка на каждую команду, а не одна доп. текстура на все
        own_parts = set(self._host.preview.part_material_names())
        extra = {m: p for m, p in t.uploaded_slot_paths().items() if m not in own_parts}
        if self._host.preview.custom_vpk_mode:
            # Сборка мода кладёт `image` на ПЕРВЫЙ VTF архива, а главная
            # карточка - материал модели (VpkModController._on_materials).
            # Без `image` каждая текстура спрашивается по имени, и отвечает
            # карточка с тем же именем (_on_build_needs_texture)
            image = None
        # У неба главного материала нет вовсе: «своя текстура» - это панорама
        # (её сборка режет сама) или подменённые грани. Слоты в сборку неба не
        # идут: там свои поля, а грани уже лежат в overrides
        sky = t.skybox_build_data() if mode == SKYBOX_MODE else {}
        # Гирлянды поверх оружия собираются своими моделями: правлена может
        # быть одна гирлянда, и оружие тогда в мод не идёт вовсе
        decor = self._host.decor.builds(paths['root']) if mode != SKYBOX_MODE else []
        if mode == SKYBOX_MODE:
            image = sky.get('equirect') or None
            extra = {}
            if not image and not sky.get('face_overrides'):
                return {'error': 'Загрузите панораму 360° или грани неба'}
        # Своей главной текстуры нет - мод собирается с игровой, если есть что
        # собирать: правленый VMT, карты, своя модель… Только там, где сборка
        # идёт модельным конвейером (он умеет «главная из игры»), у спец-режимов,
        # масок и мода из VPK текстура - единственное, что они собирают
        main_from_game = False
        if mode != SKYBOX_MODE and not image and self._model_pipeline_mode(mode):
            weapon_edits = bool(extra) or self._edits_besides_textures(mode, params)
            if not weapon_edits and not decor and not params.get('allow_empty'):
                # Страница спросит «изменений нет - всё равно собрать?»
                return {'confirm_empty': True}
            # Правлена одна гирлянда - оружие в мод не идёт вовсе (сборка
            # «только гирлянды»), и главная из игры ему не нужна
            main_from_game = weapon_edits or not decor
        elif mode != SKYBOX_MODE and not image and not extra and not decor:
            return {'error': 'Не загружено ни одной своей текстуры'}
        return BuildImages(
            image=image, extra=extra,
            blu={m: p for m, p in t.blu_uploaded_paths().items() if m not in own_parts},
            decor=decor, parts=self._part_material_specs() or [],
            styles=self._own_style_data(), sky=sky, main_from_game=main_from_game)

    def _answer_tint(self, images: Any, mode: str,
                     params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Краска игры по альфе ($blendtintbybasealpha): своя картинка без
        альфы в игре перекрасится ЦЕЛИКОМ, а превью показывает её как есть.
        Спрашиваем до сборки, ответ приходит тем же вызовом (`tint_mode`).
        У шапки со снятой галкой «Краски из игры» красить нечего

        Вопрос странице ({'confirm_tint'}) или None; ответ «none»/«mask»
        подменяет картинки исправленными
        """
        tint_mode = str(params.get('tint_mode') or '')
        if mode == 'hat' and not params.get('hat_paints', True):
            return None
        risks = self._host._tint_risks(images.own_paths())
        if risks and tint_mode not in ('none', 'mask', 'strip', 'keep'):
            from src.services import vmt_tint
            spec = next(iter(risks.values()))[0]
            return {'confirm_tint': {
                'color': vmt_tint.color_name(spec.color, params.get('lang') or 'ru'),
                'hex': '#%02x%02x%02x' % spec.color}}
        if tint_mode in ('none', 'mask'):
            fixed = self._host._fix_tint(risks, tint_mode)
            images.remap(lambda p: fixed.get(p, p))
        return None

    def _build_request(self, images: Any, mode: str, paths: Dict[str, str],
                       params: Dict[str, Any]) -> Any:
        """BuildRequest из картинок сборки, параметров страницы и сеанса"""
        from src.data.skyboxes import SKYBOX_MODE
        from src.services.build_request import BuildRequest

        tint_mode = str(params.get('tint_mode') or '')
        hat_primary, hat_models = (self._hat_build_models(params.get('hat_classes'))
                                   if mode == 'hat' else (None, None))
        size = int(params.get('size') or 512)
        image = images.image
        if images.main_from_game:
            from src.shared.constants import EXTRA_TEX_USE_GAME_ORIGINAL
            image = EXTRA_TEX_USE_GAME_ORIGINAL
        return BuildRequest(
            image_path=image,
            main_from_game=images.main_from_game,
            mode=mode,
            filename=vpk_file_name(params.get('filename'), 'mod.vpk'),
            size=(size, size),
            format_type=params.get('format') or 'DXT5',
            flags=list(params.get('flags') or []),
            vtf_options=dict(params.get('options') or {}),
            tf2_root_dir=paths['root'],
            # Из настроек, а не из запроса: страница папку не шлёт, и мод
            # всегда уходил в «export» от текущей папки процесса
            export_folder=self._host._export_settings()[0],
            language=params.get('lang') or 'ru',
            panel_extra_textures=images.extra or None,
            # «Прочее» со страницы: сборка спрашивает про эти материалы так
            # же, как про доп. материалы геометрии
            misc_materials=list(self._host.preview.misc_materials) or None,
            panel_blu_textures=images.blu or None,
            force_team=bool(self._host.preview.textures.force_team),
            isolate_shoulders=bool(params.get('isolate_shoulders')),
            # Карты материала (detail / самосвечение / phong): VTF по ним
            # генерит сборка, а VMT дописывает сама - страница их только
            # набирает
            material_maps=(dict(self._host.preview.texture_maps) or None),
            # Свои настройки материала (разрешение, формат, флаги): сборка
            # накладывает их поверх глобальных сама
            material_settings=(dict(self._host.preview.texture_overrides) or None),
            # Показанный мод из VPK: сборка берёт его содержимое за основу
            custom_vpk_source_path=(self._host._vpk_mod_path
                                    if self._host.preview.custom_vpk_mode else None),
            # Шапка: путь к её MDL обязателен - по режиму «hat» модель не
            # найти, и сборка падала на поиске «оружия hat»
            hat_mdl_path=hat_primary,
            hat_class_models=hat_models,
            # Правленые соседние стили: у каждого своя модель и своя текстура,
            # но мод один - иначе человек собирал бы их по одному и вручную
            # склеивал
            hat_style_builds=(self._host._hat_style_builds(params.get('hat_classes'))
                              if mode == 'hat' else None),
            decor_builds=images.decor or None,
            # Своя модель снаряда в оружии: на игровой модели и на своей
            part_models=(dict(self._host.preview.part_models) or None
                         if not self._host.preview.custom_vpk_mode else None),
            # Части-материалы: у игровой и у своей модели (у мода из VPK
            # номера треугольников превью - чужие)
            part_materials=(images.parts or None
                            if not self._host.preview.custom_vpk_mode else None),
            # Стили своей модели «со своими материалами» (и её Australium):
            # таблицу скинов сборка собирает из них сама
            skin_build_data=images.styles,
            # Папка обхода sv_pure из настроек (console / vgui): без неё
            # сборка молча оставалась на умолчании console
            bypass_method=self._host._bypass_method(),
            # Краски из игры: с ними текстура красится командным цветом, как у
            # стоковой шапки. Спрашивает страница - умолчание «да», как в окне
            hat_apply_game_paints=bool(params.get('hat_paints', True)),
            strip_game_tint=(tint_mode == 'strip'),
            # Своя геометрия: включает замену сама фактом загрузки - отдельной
            # галочки на странице нет, как и в кнопке приложения
            replace_model_enabled=bool(self._host.preview.custom_smd_path),
            replace_model_path=self._host.preview.custom_smd_path,
            replace_keep_materials=bool(self._host.preview.custom_keep_materials),
            # Правленый QC берётся только у «готовой» модели: у замены
            # геометрии сборка собирает QC сама
            custom_qc_text=(self._host.preview.custom_qc_text
                            if self._host.preview.custom_keep_materials else None),
            # Небо: какие имена перекрывает мод и чем заменены отдельные грани.
            # Панорама уехала в `image_path` - сборка режет её сама, в
            # выбранном разрешении
            skybox_sky_names=(self._host._sky_names_to_build()
                              if mode == SKYBOX_MODE else None),
            skybox_face_overrides=(images.sky.get('face_overrides') or None),
        )

    def _start_build(self, request: Any, plan: Any) -> Dict[str, Any]:
        """Запускает воркер сборки и переводит его сигналы в события страницы"""
        from src.services.build_worker import BuildWorker
        w = BuildWorker(request=request,
                        prepare=(lambda report: self._host.parts.bake(plan, report))
                        if plan else None)

        # Сборка умеет СПРАШИВАТЬ у интерфейса недостающую текстуру и
        # блокируется до ответа (UiRequest, таймаут 300 секунд). Вопрос доходит
        # до человека: «не нашлось» в сеансе означает «взять ГЛАВНУЮ текстуру»,
        # и скин молча растекался бы на служебные материалы
        w.request_extra_texture.connect(self._on_build_needs_texture)
        # Сменные части модели (бутылка целая/разбитая, набалдашник кабера до и
        # после взрыва) при подмене модели спрашиваются так же: без ответа
        # сборка ждала бы пять минут на каждую часть
        w.request_extra_model.connect(self._on_build_needs_model)
        # Свой SMD с другими именами материалов: сборка идёт дальше, а
        # предупреждение остаётся в журнале.
        # Ответ строкой: True воркер считал отказом и отменял сборку
        def _on_mismatch(msg: str) -> None:
            logger.warning(msg)
            w.set_texture_mismatch_result('continue')
        w.texture_mismatch_warning.connect(_on_mismatch)

        w.progress.connect(lambda pct, text: self._host._put('build_progress',
                                                       percent=pct, text=text))
        # Подшаг: проценты у него свои, внутри этапа, - линию сборки он не
        # двигает, только подписывает
        w.sub_progress.connect(lambda pct, text: self._host._put('build_progress',
                                                           percent=pct, text=text,
                                                           sub=True))
        # Отмена кончается тем же «не собрано», но это не ошибка: интерфейсу
        # незачем вздрагивать красным
        def _done(ok: bool, msg: str) -> None:
            # Итог в полосе короткий: имя мода и число предупреждений. Сами
            # предупреждения дописаны к сообщению строками «- …» после пустой
            # строки (VPKService, «Внимание:») и лежат в журнале: строкой в
            # полосе их было не прочесть
            tail = (msg or '').partition('\n\n')[2]
            self._host._put('build_done', ok=bool(ok), message=msg,
                      cancelled=not ok and w.isInterruptionRequested(),
                      filename=os.path.basename(request.filename),
                      warnings=sum(1 for line in tail.splitlines() if line.startswith('- ')))
        w.finished.connect(_done)
        w.finished.connect(lambda ok, msg: self._host.parts.drop_baked())
        # `error` не слушаем: за ним всегда идёт `finished` (BaseWorker.run),
        # и одна ошибка приходила странице дважды
        self._build = w
        self._texture_choice = _NO_CHOICE   # «ко всем» - на одну сборку
        w.start()
        return {'started': True, 'filename': request.filename}

    @staticmethod
    def _model_pipeline_mode(mode: str) -> bool:
        """Собирается ли режим модельным конвейером (он умеет «главная из
        игры»): там же, где есть редактор VMT, кроме масок шпиона - у них своя
        сборка из одних текстур"""
        from src.app.api import controls_for
        from src.data.player_characters import SPY_MASK_MODE_KEY
        return bool(controls_for(mode).get('vmt_editor')) and mode != SPY_MASK_MODE_KEY

    def _part_material_specs(self) -> Optional[list]:
        """Части-материалы для сборки:
        [{name, base, tris, total, sources, image, image_blu, style_images,
        map_base, existing?}]

        `image`/`image_blu` - своя картинка материала части на RED и на BLU
        (у нейтрального исходного это одна и та же): сборка ставит её только в
        строки скина своей команды. `style_images` - {материал строки стиля:
        картинка} - её правки стилей (у гильотины Bloody - в строке
        `c_sd_cleaver_bloody`). В остальных строках - игровая текстура строки.
        `map_base` - основа карт «из текстуры»: своя картинка RED, иначе
        игровая текстура исходного. `existing` - части отданы родному
        материалу модели: только переименовать треугольники
        """
        from src.domain.preview.texture_state import _existing
        from src.services import part_materials as pm
        from src.shared.constants import Team

        t = self._host.preview.textures
        rows = (t.skin_info or {}).get('rows') or []
        head = [str(n).lower() for n in rows[0]] if rows else []
        specs = []
        for base, entries in self._host.preview.part_materials.items():
            col = head.index(base.lower()) if base.lower() in head else -1
            for e in entries:
                if not e.get('tris'):
                    continue
                name = e['name']
                if e.get('existing'):
                    # Картинка, VMT и место в $texturegroup у родного
                    # материала свои - их сборка пишет и без частей
                    specs.append({'name': name, 'base': base, 'tris': list(e['tris']),
                                  'total': e.get('total'), 'late': e.get('late'),
                                  'sources': list(e.get('sources') or []),
                                  'existing': True, 'image': None, 'image_blu': None,
                                  'style_images': {}, 'map_base': None})
                    continue
                image = _existing(t.textures.get(Team.RED, {}).get(name))
                blu = _existing(t.textures.get(Team.BLU, {}).get(name))
                # «Сделать командным» без своей синей: синий берёт красную -
                # так же, как превью (resolve_base) и главная (uploaded_for_mat)
                if not blu and t.force_team and not t.is_team_material(name):
                    blu = image
                maps = self._host.preview.texture_maps.get(name) or {}
                derive = any((m or {}).get('derive') for m in maps.values())
                styles = {}
                for style, overrides in t.skin_overrides.items():
                    own = _existing((overrides or {}).get(name))
                    if not own:
                        continue
                    if self._host.preview.own_styles:
                        # Своя модель: строки стиля собирает сборка, и исходный
                        # в них - `<материал>_<стиль>`, если его добавили в стиль
                        card = e.get('card') or base
                        if card in (self._host.preview.skin_chosen.get(style) or set()):
                            styles[f"{pm.model_name(base)}_"
                                   f"{self._host.preview.style_suffix(style)}".lower()] = own
                        continue
                    row = rows[style] if 0 < int(style) < len(rows) else []
                    if 0 <= col < len(row) and str(row[col]).lower() != base.lower():
                        styles[str(row[col]).lower()] = own
                specs.append({'name': name, 'base': base, 'tris': list(e['tris']),
                              'total': e.get('total'), 'late': e.get('late'),
                              'sources': list(e.get('sources') or []),
                              'image': image,
                              'image_blu': blu,
                              'style_images': styles,
                              'map_base': (image or t.game_base(name, Team.RED))
                              if derive else None})
        return specs or None

    def _own_style_data(self) -> Optional[Dict[str, Any]]:
        """
        Стили своей модели «со своими материалами» для сборки:
        {mesh_materials, tg_overrides {скин: {материал: вариант}}, variant_files}

        Игровая таблица скинов к такой модели не подходит - её имена игровые,
        - и сборка собирает свою (ModelBuildService.generate_texturegroup_block)
        из того, что человек положил в стили «плюсиком»: материал стиля
        получает вариант `<материал>_<стиль>` во всех строках этого стиля
        (у Australium их две - RED и BLU), остальные во всех скинах те же.
        Раньше это заполняла панель окна Qt; веб-версия - нет, и стили своей
        модели молча пропадали из мода
        """
        from src.domain.preview.texture_state import _existing

        p, t = self._host.preview, self._host.preview.textures
        if not p.own_styles:
            return None
        mats = list(t.material_names)
        overrides: Dict[int, Dict[str, str]] = {}
        files: Dict[str, str] = {}
        for style, by_mat in sorted(t.skin_overrides.items()):
            for mat in mats:
                path = _existing((by_mat or {}).get(mat)) if style else None
                if not path:
                    continue
                name = f"{mat}_{p.style_suffix(int(style))}"
                files[name] = path
                for row in p.style_rows(int(style)):
                    overrides.setdefault(row, {})[mat] = name
        if not overrides:
            return None
        return {'mesh_materials': mats, 'tg_overrides': overrides, 'variant_files': files}

    def _edits_besides_textures(self, mode: str, params: Dict[str, Any]) -> List[str]:
        """Что правлено кроме своих текстур - то, ради чего стоит собирать мод
        и без них. Пусто - мод вышел бы игровым

        Флаги и формат VTF сюда не входят: без своей картинки игровая текстура
        кладётся как есть, и они ничего не меняют
        """
        from src.services.edited_vmt_service import EditedVMTService

        p, t = self._host.preview, self._host.preview.textures
        found = []
        for card in [''] + list(t.material_names or []):
            target = self._host.materials.vmt_target(card)
            if isinstance(target, tuple):
                edited = EditedVMTService.get_edited_vmt(target[1])
                if edited and os.path.exists(edited):
                    found.append('vmt')
                    break
        if p.texture_maps:
            found.append('maps')
        if p.custom_smd_path:
            found.append('model')
        if p.part_models:
            found.append('part_models')       # своя модель снаряда в оружии
        if p.part_materials:
            found.append('part_materials')
        if t.force_team:
            found.append('team')
        if self._host.decor.baked():
            found.append('festive')           # гирлянда вшита в модель оружия
        if (params.get('options') or {}).get('normal'):
            found.append('normal')            # рельеф строится и из игровой
        if params.get('isolate_shoulders'):
            found.append('shoulders')
        return found

    def cancel_build(self) -> Dict[str, Any]:
        """Останавливает идущую сборку

        Сборка шапки на девять классов с текстурами 2048 идёт минуты, и
        передумать посреди неё человек должен иметь право. Воркер проверяет
        отмену между шагами сам - здесь только просьба остановиться, о
        завершении скажет его же `finished`
        """
        build = self._build
        if build is None or not build.isRunning():
            return {'running': False}
        build.requestInterruption()
        # Ждущий вопрос (текстура или сменная часть модели) держит воркер на
        # паузе: без ответа он не дойдёт до проверки отмены и висел бы до
        # таймаута в 300 секунд
        if hasattr(build, 'set_extra_texture_result'):
            build.set_extra_texture_result(None)
        if hasattr(build, 'set_extra_model_result'):
            build.set_extra_model_result(None)
        return {'running': True, 'cancelling': True}

    def _hat_build_models(self, classes):
        """
        (основная модель, модели всех выбранных классов) для сборки шапки

        Основной сборка собирает одну модель, остальные выбранные классы -
        добавочно. Основной раньше всегда была модель ПРЕВЬЮ, то есть первого
        класса в списке: снятая с него галка ничего не меняла (класс всё равно
        попадал в мод), а при одном выбранном классе собирался только тот, что в
        превью, - выбранный не собирался вовсе. Теперь основная - модель превью,
        только если её класс выбран, иначе первая выбранная
        """
        primary = self._host.preview.weapon_key
        models = self._hat_models_for(classes)
        if models and primary not in models.values():
            primary = next(iter(models.values()))
        return primary, models

    def _hat_models_for(self, classes) -> Optional[Dict[str, str]]:
        """
        Модели мультиклассовой шапки под выбранные классы

        Собирать все девять, когда человеку нужен один класс, - это девять
        моделей в моде вместо одной. Пустой выбор считаем «все»: молча собрать
        пустую шапку хуже, чем собрать лишнее
        """
        if not self._host._hat_models:
            return None
        wanted = {str(c).lower() for c in (classes or [])}
        if not wanted:
            return dict(self._host._hat_models)
        picked = {cls: path for cls, path in self._host._hat_models.items()
                  if cls.lower() in wanted}
        return picked or dict(self._host._hat_models)

    # Недостающая текстура: вопрос страницы, ответ человека

    def _on_build_needs_texture(self, material: str, weapon_key: str,
                                remaining: int = 0) -> None:
        """
        Сборке не хватает текстуры для материала

        Порядок тот же, что в окне: уже загруженная текстура отвечает сама,
        запомненный выбор «ко всем» отвечает следом, и только потом спрашиваем
        человека. Пока он думает, воркер стоит на UiRequest
        """
        # Правка стиля хранится под БАЗОВЫМ материалом, а сборка спрашивает
        # материал строки $texturegroup по его имени (c_sd_cleaver_bloody) -
        # без этой связки Bloody у гильотины собирался бы игровым
        uploaded = (self._host.preview.textures.uploaded_for_mat(material)
                    or self._host.preview.textures.style_upload_for(material))
        if uploaded:
            self._answer_texture_request(self._host.parts.baked_path(uploaded))
            return
        from src.shared.constants import EXTRA_TEX_USE_GAME_ORIGINAL
        # Мод из VPK: текстура материала уже лежит в моде и видна на
        # карточке - своей нет, значит остаётся его. Спрашивать не о чем.
        # Синий двойник красного без правки - тоже: карточки у него нет, а
        # игровой выглядит как красный
        if (self._host.preview.custom_vpk_mode
                or material.lower() in self._host.preview.textures.blu_twins):
            self._answer_texture_request(EXTRA_TEX_USE_GAME_ORIGINAL)
            return
        # Сборку отменяют: воркер дойдёт до проверки отмены только после
        # ответа, а каждый новый вопрос до неё показывал бы окно заново
        build = self._build
        if build is not None and build.isInterruptionRequested():
            self._answer_texture_request(EXTRA_TEX_USE_GAME_ORIGINAL)
            return
        if self._texture_choice is not _NO_CHOICE:
            self._answer_texture_request(self._texture_choice)
            return
        self._host._put('need_texture', material=material, weapon_key=weapon_key,
                  remaining=int(remaining))

    # Сменная часть модели: вопрос страницы, ответ человека

    def _on_build_needs_model(self, smd_name: str, weapon_key: str) -> None:
        """
        Сборке нужна геометрия сменной части (`$bodygroup`): своя модель
        подменила основную, а у оружия есть ещё состояния - разбитая бутылка,
        взорванный кабер. Игра переключает их сама, и мод должен дать каждое
        """
        build = self._build
        if build is not None and build.isInterruptionRequested():
            self._answer_model_request(None)
            return
        self._host._put('need_model', part=smd_name, weapon_key=weapon_key,
                  kind=_part_kind(smd_name))

    def _answer_model_request(self, path: Optional[str]) -> None:
        build = self._build
        if build is not None and hasattr(build, 'set_extra_model_result'):
            build.set_extra_model_result(path)

    def answer_model(self, path: str = '') -> Dict[str, Any]:
        """Ответ страницы на ``need_model``: свой SMD либо пусто - игровая"""
        if path and not os.path.isfile(path):
            return {'error': 'Файл модели не найден'}
        self._answer_model_request(path or None)
        return {'ok': True}

    def _answer_texture_request(self, value) -> None:
        """Отдаёт ответ ждущему воркеру сборки"""
        build = self._build
        if build is not None and hasattr(build, 'set_extra_texture_result'):
            build.set_extra_texture_result(value)

    def answer_texture(self, choice: str = 'game', path: str = '',
                       apply_all: bool = False) -> Dict[str, Any]:
        """
        Ответ страницы на ``need_texture``

        Три варианта - те же, что в диалоге приложения:
          • ``game`` - оставить игровой оригинал (в мод не попадёт);
          • ``main`` - скопировать главную текстуру на этот материал;
          • ``file`` - своя картинка по пути ``path``
        """
        from src.shared.constants import (
            EXTRA_TEX_USE_GAME_ORIGINAL, EXTRA_TEX_USE_MAIN,
        )

        if choice == 'file' and path:
            value = path
        elif choice == 'main':
            value = EXTRA_TEX_USE_MAIN
        else:
            value = EXTRA_TEX_USE_GAME_ORIGINAL

        if apply_all:
            self._texture_choice = value
        self._answer_texture_request(value)
        return {'answered': choice}
