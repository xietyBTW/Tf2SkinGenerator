"""
Своя модель вместо игровой: SMD или OBJ/GLB «из интернета», подгонка
импорта, её QC и восстановление из сохранённой работы

Показ модели идёт обычным путём сеанса (`controller`, `_on_model_ready`);
здесь - что за модель, как её превратить в SMD и что ждёт ответа человека
(«готова / только геометрия»). Пути и подгонка модели живут в состоянии
превью сеанса - их сохраняет работа

Доступ - `session().custom_model`; `api.py` зовёт его методы напрямую
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.shared.logging_config import get_logger

if TYPE_CHECKING:
    from src.app.session import AppSession

logger = get_logger(__name__)


class CustomModelEditor:
    """Своя модель предмета и её QC"""

    def __init__(self, host: "AppSession") -> None:
        self._host = host
        #: Сконвертированная своя модель, ждущая ответа «готова / только
        #: геометрия». Держим, чтобы не конвертировать SMD второй раз
        self._pending_model: Optional[Dict[str, Any]] = None
        #: Разобранный импорт (источник, сетка, папка): подгонка пересобирает
        #: SMD из него, не читая OBJ/GLB заново
        self._imported_mesh: Optional[tuple] = None
        #: (треугольников было, стало) - если импорт пришлось упростить
        self._imported_simplified: Optional[tuple] = None

    def _carrier_for_preview(self):
        """Пушка, на которой висит текущий предмет. Пусто - ни на чём

        Праздничное оружие - навесная гирлянда: в кадре она не одна, и всё,
        что рисует предмет, обязано рисовать и носителя
        """
        from src.services import carrier_model

        paths = self._host.tf2_paths()
        key = self._host.preview.weapon_key
        if 'error' in paths or not key:
            return carrier_model.NONE
        return carrier_model.find(key, paths['misc_vpk'], paths['root'])

    def load_custom_model(self, path: str = '', keep: Optional[bool] = None,
                          lang: str = 'ru') -> Dict[str, Any]:
        """
        Подставляет свою геометрию вместо игровой

        Два шага, потому что от ответа зависит всё дальнейшее. «Готова» -
        модель со своими материалами: карточки берутся из её SMD, доступна
        правка QC. «Только геометрия» - на экране геометрия пользователя, а
        карточки и текстуры приезжают из игрового QC (там всё сводится к
        игровым текстурам)

        Рекомендацию считаем здесь: больше одного редактируемого материала -
        почти наверняка готовая модель
        """
        import os

        from src.domain.preview.material_cards import editable_material_cards
        from src.services import mesh_import_service

        pending = self._pending_model
        if keep is not None and pending and pending['src'] == (path or pending['src']):
            # Второй заход после ответа: SMD уже сконвертирован
            smd, obj, materials = pending['smd'], pending['obj'], pending['materials']
            source, fit = pending['source'], pending['fit']
        else:
            if not path or not os.path.isfile(path):
                return {'error': 'Файл модели не найден'}
            # Источник помним у любой модели: подгонка (масштаб, поворот,
            # сдвиг) пересобирает SMD из него. У OBJ/GLB SMD делаем сами
            source, fit = path, mesh_import_service.Fit()
            try:
                smd = self.bake_imported_mesh(path, fit)
            except mesh_import_service.MeshImportError as exc:
                return {'error': str(exc)}
            obj, materials = self._custom_model_obj(smd, ghost=True)
            if obj is None:
                return {'error': 'SMD не сконвертировался'}

        cards = [c.name for c in editable_material_cards(materials)]
        if keep is None:
            self._pending_model = {'src': path, 'smd': smd, 'obj': obj,
                                   'materials': materials, 'source': source,
                                   'fit': fit}
            return {'ask_keep': True, 'materials': cards,
                    'recommend_keep': len(cards) > 1}

        self._pending_model = None
        with self._host._lock:
            p = self._host.preview
            # Главный материал ИГРОВОЙ модели - до сброса: карточки «только
            # геометрии» приедут теми же именами, но позже, а текстуру из
            # файла класть надо сейчас
            game_main = p.textures.stable_main()
            # Своя геометрия - свои треугольники: части прежней модели на ней
            # ничего не значат
            p.forget_parts_layout()
            p.custom_smd_path = smd
            p.custom_obj_path = obj
            p.custom_keep_materials = bool(keep)
            p.custom_qc_text = None
            p.custom_source_path = source
            p.custom_fit = fit.to_dict() if fit else None
            p.reset_skins()
            # Командные кадры и вариант остались от ИГРОВОЙ модели - на чужой
            # геометрии они показывали бы не то. Для «только геометрии» их
            # вернёт воркер карточек
            p.reset_team_frames()
            p.reset_misc()

        self._show_custom_model(obj, cards, lang)

        # Базовый цвет из MTL/glTF - сразу в слоты: «готовой» модели по её
        # материалам, «только геометрии» - первый найденный на главный
        # игровой материал (все её материалы схлопнутся в него)
        placed = self._place_imported_textures(
            source, cards if keep else [game_main] if game_main else [])

        self._host._autosave()
        logger.info(f"своя модель: {smd} keep={bool(keep)} материалов={len(cards)}")
        return {'started': True, 'keep': bool(keep), 'materials': cards,
                'obj': obj, 'fit': p.custom_fit, 'textures': placed,
                'simplified': (self._imported_simplified
                               if source else None)}

    def _show_custom_model(self, obj: str, cards: List[str], lang: str) -> None:
        """
        Ставит свою геометрию в кадр

        `obj` - её OBJ для вьювера, `cards` - материалы из SMD. У «готовой»
        модели они и есть карточки, у «только геометрии» карточки игровые, их
        привозит воркер без геометрии. Состояние (`custom_smd_path`, `keep`)
        к этому моменту уже выставлено - либо загрузкой, либо вернувшейся
        работой
        """
        p = self._host.preview
        with self._host._lock:
            p.custom_obj_path = obj
            if p.custom_keep_materials:
                p.textures.material_names = cards
                p.textures.main_material = cards[0] if cards else None

        # Габариты считает та же дорожка, что и у игровой модели
        self._host.controller.stop()
        # Сцена в руках собрана под ПРОШЛУЮ геометрию: забыть её, иначе
        # следующий запрос вида от первого лица получит одни дорожки
        self._host.viewmodel.stop()
        self._host._on_model_ready(obj, '')
        # Подложку носителя `stop()` не отменяет: она про геометрию в кадре, а
        # та никуда не делась. Без возврата пушка под своей гирляндой серая
        with self._host._lock:
            self._host.controller.apply_scene_extra()

        paths = self._host.tf2_paths()
        mode = getattr(self._host, '_mode', '')
        if 'error' in paths or not mode or not p.weapon_key:
            return
        # Стили оригинала пригодятся и своей модели: по ним переопределяют
        # текстуры вариантов. Сброшены выше - ищем заново
        self._host.skins.detect(p.weapon_key, mode, paths['misc_vpk'], lang=lang)
        if not p.custom_keep_materials:
            self._host.controller.load_game_model(
                p.weapon_key, mode, paths['misc_vpk'], paths['textures_vpk'],
                lang=lang, geometry=False)

    def restore(self, lang: str = 'ru') -> bool:
        """
        Своя модель из вернувшейся работы - в кадр. False - ставить нечего

        Работа помнит SMD, а кадр после возврата показывал ИГРОВУЮ модель:
        текстура, нарисованная под свою геометрию, ложилась на чужую, и на
        экране было не то, что уйдёт в сборку. OBJ для вьювера живёт один
        запуск, поэтому собираем его заново из того же SMD
        """
        from src.domain.preview.material_cards import editable_material_cards

        p = self._host.preview
        smd = p.custom_smd_path
        if not smd or not os.path.isfile(smd) or self._host._vpk_mod_path:
            return False
        # Призрак оригинала нужен подгонке, а она есть только у импорта
        obj, materials = self._custom_model_obj(smd, ghost=bool(p.custom_source_path))
        if obj is None:
            logger.warning(f"своя модель из работы не показана: {smd}")
            return False
        cards = [c.name for c in editable_material_cards(materials)]
        with self._host._lock:
            # Кадры команд и «Прочее» - от игровой геометрии, правки человека
            # (текстуры, «сделать командным») уже на месте, их не трогаем
            force = p.textures.force_team
            p.reset_team_frames()
            p.reset_misc()
            p.textures.force_team = force
        self._show_custom_model(obj, cards, lang)
        return True

    def _place_imported_textures(self, source: Optional[str], cards: List[str]) -> int:
        """Кладёт текстуры импортированной модели на карточки, сколько легло

        `cards` - материалы «готовой» модели (свои имена) либо один главный
        игровой материал «только геометрии»: в него схлопнутся все её
        материалы, туда же идёт первая найденная картинка
        """
        cached = self._imported_mesh
        if not source or not cached or cached[0] != source or not cards:
            return 0
        textures = cached[1].textures if cached[1] is not None else {}
        if not textures:
            return 0
        by_card = [(m, textures[m]) for m in cards if m in textures]
        pairs = by_card or [(cards[0], next(iter(textures.values())))]
        with self._host._lock:
            for material, path in pairs:
                self._host.preview.textures.set_texture(material, path)
        return len(pairs)

    def _custom_model_obj(self, smd: str, ghost: bool):
        """OBJ своей модели для превью: (путь, материалы модели) или (None, [])

        `ghost` - добавить полупрозрачный оригинал оружия ориентиром для
        подгонки: без него человек не знает, куда повернуть и насколько
        увеличить. Его материалы идут с приставкой `ghost:` - вьювер по ней
        рисует призрак, а карточек по ним нет
        """
        import os
        import tempfile

        from src.services import carrier_model, decompile_cache
        from src.services import smd_service
        from src.services.smd_to_obj_service import MeshPart, SmdToObjService

        obj_dir = tempfile.mkdtemp(prefix='tf2_smd_preview_')
        obj = os.path.join(obj_dir, 'model.obj')
        # Пушка-НОСИТЕЛЬ остаётся в кадре: у праздничного оружия своей
        # моделью заменяют гирлянду, а не пушку под ней. У обычного
        # оружия носителя нет, и список пуст - на них это не влияет
        carrier = self._carrier_for_preview()
        parts = [MeshPart(smd_path=smd, extra_smd_paths=tuple(carrier.smds))]
        if ghost:
            key = self._host.preview.weapon_key or ''
            qc = decompile_cache.find_cached_qc_for_weapon(key) if key else None
            ref = smd_service.find_reference_smd(os.path.dirname(qc), key) if qc else None
            if ref:
                parts.append(MeshPart(smd_path=ref, material_prefix='ghost:'))
            else:
                logger.info('призрак оригинала не показан: модель ещё не разобрана')
        ok, materials = SmdToObjService.convert_parts(parts, obj)
        if not ok or not os.path.exists(obj):
            return None, []
        # Материалы носителя и призрака предмету не принадлежат: карточек по
        # ним нет и в сборку они не идут - иначе своя модель гирлянды тянула
        # бы за собой ещё и текстуру базового обреза
        own = carrier_model.materials(carrier)
        materials = [m for m in (materials or [])
                     if m not in own and not m.startswith('ghost:')]
        return obj, materials

    def bake_imported_mesh(self, source: str, fit) -> str:
        """SMD с запечённой подгонкой: из OBJ/GLB - свой, из SMD - тот же с
        пересчитанными вершинами, лимиты studiomdl - ошибкой"""
        import os
        import tempfile

        from src.services import mesh_import_service

        # Разобранный меш держим: подгонка правится ползунком, и разбирать
        # 65k треугольников заново на каждый шаг - секунда впустую
        cached = self._imported_mesh
        if cached and cached[0] == source:
            _, mesh, out_dir = cached
        elif source.lower().endswith('.smd'):
            # Свой SMD: кости и веса остаются, двигаются только вершины.
            # Без подгонки файл идёт как есть - ничего не переписываем
            self._imported_simplified = None
            if fit == mesh_import_service.Fit():
                return source
            out_dir = tempfile.mkdtemp(prefix='tf2_mesh_import_')
            self._imported_mesh = (source, None, out_dir)
            mesh = None
        else:
            mesh = mesh_import_service.load_mesh(source)
            # Скульпт из интернета на сотни тысяч треугольников studiomdl не
            # возьмёт - упрощаем сами, с сохранением UV; человеку об этом
            # скажет ответ загрузки. Слишком много материалов так не лечится
            self._imported_simplified = None
            if mesh_import_service.over_limits(mesh):
                before = mesh.triangle_count
                mesh = mesh_import_service.simplify(mesh)
                self._imported_simplified = (before, mesh.triangle_count)
            problem = mesh_import_service.check_limits(mesh)
            if problem:
                raise mesh_import_service.MeshImportError(problem)
            if not mesh.has_uv:
                logger.warning(f"у модели нет UV-развёртки: {source}")
            # Одна папка на источник: SMD перезаписывается, а не плодится
            # по 15 МБ на каждый шаг ползунка
            out_dir = tempfile.mkdtemp(prefix='tf2_mesh_import_')
            self._imported_mesh = (source, mesh, out_dir)
        stem = os.path.splitext(os.path.basename(source))[0]
        out = os.path.join(out_dir, stem + '.smd')
        if mesh is None:
            return mesh_import_service.transform_smd(source, out, fit)
        return mesh_import_service.write_smd(mesh, out, fit)

    def set_custom_fit(self, fit: Optional[dict] = None) -> Dict[str, Any]:
        """Подгонка импортированной модели: пересобирает SMD с запечённым
        трансформом. Сцену превью не перегружает - вьювер крутит модель сам
        тем же трансформом; SMD нужен сборке и виду от первого лица"""
        from src.services import mesh_import_service

        p = self._host.preview
        if not p.custom_source_path:
            return {'error': 'Подгонка есть только у импортированной модели'}
        parsed = mesh_import_service.Fit.from_dict(fit)
        try:
            smd = self.bake_imported_mesh(p.custom_source_path, parsed)
        except mesh_import_service.MeshImportError as exc:
            return {'error': str(exc)}
        with self._host._lock:
            p.custom_smd_path = smd
            p.custom_fit = parsed.to_dict()
        self._host._autosave()
        return {'fit': p.custom_fit}

    def drop_custom_model(self, lang: str = 'ru') -> Dict[str, Any]:
        """Забывает свою модель и возвращает в кадр игровую

        Не только в состоянии: иначе в кадре и в альбоме оставались бы своя
        геометрия и её карточки до перезагрузки предмета. Игровую модель
        грузим той же дорожкой, что и выбор предмета - с её карточками и
        стилями, правки текстур при этом остаются
        """
        p = self._host.preview
        key, mode = p.weapon_key, getattr(self._host, '_mode', '')
        with self._host._lock:
            p.begin_game_model()
            p.custom_qc_text = None
        self._pending_model = None
        self._imported_mesh = None
        self._host.viewmodel.stop()        # сцена в руках была со своей моделью
        paths = self._host.tf2_paths()
        if key and mode and 'error' not in paths:
            self._host.controller.load_game_model(
                key, mode, paths['misc_vpk'], paths['textures_vpk'], lang=lang)
            self._host.skins.detect(key, mode, paths['misc_vpk'], lang=lang)
        self._host._autosave()
        return {'dropped': True}

    def qc_text(self) -> Dict[str, Any]:
        """
        QC для правки: сохранённый пользователем либо исправленный авто-QC

        Правка QC имеет смысл только у «готовой» модели: у замены геометрии
        сборка собирает QC сама под игровые материалы
        """
        from src.services import decompile_cache
        from src.services.model_build_service import ModelBuildService

        p = self._host.preview
        if not p.custom_keep_materials:
            return {'error': 'QC правится только у своей готовой модели'}

        if p.custom_qc_text:
            # $texturegroup синхронизируем со стилями, правки человека при этом
            # не теряются
            return {'text': ModelBuildService.replace_texturegroup_in_text(
                p.custom_qc_text, ''), 'edited': True}

        qc_path = decompile_cache.find_cached_qc_for_weapon(p.weapon_key)
        text = ModelBuildService.make_corrected_qc(qc_path or '', p.weapon_key, '')
        if not text.strip():
            return {'error': 'QC ещё не извлечён из игры - дождитесь загрузки модели'}
        return {'text': text, 'edited': False}

    def save_qc(self, text: str = '') -> Dict[str, Any]:
        """Запоминает правку QC; пустой текст - вернуться к авто-QC"""
        with self._host._lock:
            self._host.preview.custom_qc_text = text.strip() or None
        self._host._autosave()
        return {'edited': bool(self._host.preview.custom_qc_text)}
