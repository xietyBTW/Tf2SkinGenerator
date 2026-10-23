"""
War Paint на показанном оружии: список скинов, раскладка узора по
материалам, предпросмотр и запекание в текстуры карточек

Своё состояние - только фоновая работа предпросмотра и кэши, карточки и
текстуры живут в состоянии превью сеанса, и запечённый War Paint дальше
правится как обычная своя текстура (`set_texture`, история правок)

Доступ - `session().paintkits`; `api.py` зовёт его методы напрямую
"""

from __future__ import annotations

import os
import threading
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from src.shared.logging_config import get_logger

if TYPE_CHECKING:
    from src.app.session import AppSession

logger = get_logger(__name__)


class PaintkitEditor:
    """War Paint показанного оружия"""

    def __init__(self, host: "AppSession") -> None:
        self._host = host
        #: Фоновая сборка предпросмотра, новая отменяет прежнюю
        self._paintkit_job = None
        #: Какие материалы модели красятся War Paint: {модель: ...}
        self._paintable_by_model: Dict[str, Any] = {}
        self._paintkit_preview_lock = threading.Lock()

    def _own_paintkits(self, tf2_root: str, lang: str = 'ru') -> List[dict]:
        """
        War Paint игры для показанного оружия

        На своей геометрии их нет: рецепт Valve кладёт узор по маскам под
        развёртку СТОКОВОЙ модели, и на чужой развёртке он лёг бы мимо. Там
        работает универсальный режим - по частям самой модели
        """
        from src.data import paintkit_defs
        if self._host._custom_geometry():
            return []
        return paintkit_defs.for_model(tf2_root, self._host._shown_mdl(), lang)

    def paintkits(self, lang: str = 'ru') -> Dict[str, Any]:
        """
        War Paint для показанного оружия

        Есть свои в игре - отдаются они (``generic: False``). Нет (или модель
        своя) - все War Paint с шаблоном в универсальном режиме
        (``generic: True``): узор раскладывается по частям модели, см.
        paintkit_generic. Следом в обоих случаях - украшенное оружие
        коллекций с других пушек (``decorated``): в игре каждый такой скин
        есть только у своих, здесь он ложится по деталям
        """
        from src.data import paintkit_defs

        paths = self._host.tf2_paths()
        if 'error' in paths:
            return paths
        if not self._host._shown_weapon():
            return {'items': [], 'generic': False}
        own = self._own_paintkits(paths['root'], lang)
        kits = own or paintkit_defs.generic_kits(paths['root'], lang)
        ids = {k['id'] for k in kits}
        decorated = [k for k in paintkit_defs.decorated_kits(paths['root'], lang)
                     if k['id'] not in ids]
        return {'items': kits + decorated, 'generic': not own}

    def _paintkit_offer(self, paths: Dict[str, str], item: int,
                        real: bool) -> Tuple[List[str], List[str], List[str]]:
        """
        (карточки, на которые War Paint может лечь, те из них, что красит
        игра, те, на которые узор ляжет по деталям). ``real`` - War Paint
        игры, а не универсальный режим: карточку игры рецепт красит и без
        своего меша, по деталям - нет

        Карточке без своего меша (вставки HUD, материал $texturegroup вне
        модели, огоньки гирлянды мода) узор по деталям не положить: у
        одноматериальной модели она нашла бы единственный меш, и War Paint
        лёг бы по чужой развёртке, у многоматериальной - не нашла бы ничего.
        Материал части идёт за своим исходным: развёртка у них общая, и
        картинка исходного ложится на него как есть
        """
        from src.domain.preview.texture_state import is_decor
        from src.services import mesh_parts_service

        t = self._host.preview.textures
        main = t.stable_main()
        game = self._game_cards(paths, item) if real else []
        model = mesh_parts_service.load(self._host._obj_path, self._host.preview.part_cuts,
                                        self._host.preview.part_regions)

        def own_mesh(card: str) -> bool:
            found = self._host.parts._mesh_of(model, card) if model else None
            return isinstance(found, tuple) and found[0].lower() == card.lower()

        cards: List[str] = []
        spread: List[str] = []
        for card in t.material_names:
            if not card or is_decor(card):
                continue
            # У главной меш найдётся всегда: без своего узор ляжет по самому
            # большому материалу модели (_paintkit_generic)
            mesh = card == main or own_mesh(card)
            if mesh or card in game:
                group = [card, *(p for p, src in t.part_cards.items() if src == card)]
                cards += group
                if mesh:
                    spread += group
        cards += [c for c in game if c not in cards]
        return cards, [c for c in cards if c in game or t.part_cards.get(c) in game], spread

    def _game_cards(self, paths: Dict[str, str], item: int) -> List[str]:
        """
        Карточки, на которые War Paint кладёт сама игра: материалы с прокси
        WeaponSkin у модели, куда игра его кладёт (items_game; у Детонатора
        это ещё и гильза). Модель и её VMT за сеанс не меняются - ответ
        запоминается
        """
        from src.data import paintkit_defs
        from src.services.game_vpk_reader import GameVpkReader
        from src.services.paintkit_worker import paintable_materials

        defs = paintkit_defs.load(paths['root'])
        mdl = ((paintkit_defs.item_model_path(paths['root'], defs, item) if defs else '')
               or self._host._shown_mdl())
        known = self._paintable_by_model
        if mdl not in known:
            reader = GameVpkReader([paths['textures_vpk'], paths['misc_vpk']])
            try:
                known[mdl] = paintable_materials(reader, mdl)
            finally:
                reader.close()
        return self._paintkit_targets(known[mdl], self._host.preview.textures.stable_main())

    def paintkit_materials(self, item: int = 0) -> Dict[str, Any]:
        """
        Материалы оружия для панели War Paint: [{card, game, parts}]

        ``game`` - War Paint на этот материал кладёт сама игра (у War Paint
        игры они отмечены по умолчанию, остальные - по желанию, узором по
        своим деталям). В универсальном режиме ``game`` нет ни у кого, и
        отмечены все. ``parts`` - у материала есть своя геометрия, и узор по
        деталям на него ляжет. Спрашивается при открытии панели: у
        многоматериальной модели материалы приходят позже самой модели
        """
        paths = self._host.tf2_paths()
        if 'error' in paths:
            return paths
        own = self._own_paintkits(paths['root'])
        # Куда War Paint кладёт игра - по модели этой пушки: у скина с другой
        # пушки ``item`` её, а не этой
        if own and not any(k['item'] == int(item) for k in own):
            item = own[0]['item']
        cards, game, spread = self._paintkit_offer(paths, item, bool(own))
        return {'materials': [{'card': c, 'game': c in game, 'parts': c in spread}
                              for c in cards]}

    def _paintkit_generic(self, card: str, layout: int, assign) -> Any:
        """Универсальный режим для карточки: узор по её деталям - или ошибка

        Поверх игровой текстуры своей команды, а не поверх прошлой правки:
        иначе War Paint накладывался бы на War Paint
        """
        from src.services import mesh_parts_service

        t = self._host.preview.textures
        # Не через _parts_model: тот отказывает при включённом переключателе
        # (разбитая бутылка), а узору хватает геометрии в кадре - воркер
        # разбирает ту же модель заново
        model = mesh_parts_service.load(self._host._obj_path, self._host.preview.part_cuts,
                                        self._host.preview.part_regions)
        found = (self._host.parts._mesh_of(model, card) if model
                 else {'error': 'Модель ещё не загружена'})
        if isinstance(found, dict) and card != t.stable_main():
            # Чужой узор не подставляем: у главной запасной ход - самый
            # большой материал модели, у второстепенной он лёг бы мимо
            return found
        return {'obj_path': self._host._obj_path, 'cuts': self._host.preview.part_cuts,
                'regions': self._host.preview.part_regions, 'card': card,
                'obj_material': found[0] if isinstance(found, tuple) else '',
                'base_png': t.game_base(card, t.active_team) or t.resolve_base(card) or '',
                'layout_seed': int(layout), 'assign': assign}

    def _paintkit_plans(self, kit: int, item: int, layout: int,
                        materials: Optional[List[str]] = None):
        """
        Что собрать: [(карточки, универсальный режим или None, forced, метка)]
        - или ошибка

        War Paint игры собирается рецептом Valve один раз и ложится на
        карточки, которые красит игра. Остальные материалы, как и все
        материалы оружия без War Paint в игре, получают узор по своим
        деталям - каждый отдельной сборкой: развёртка у каждого своя.
        Материал части получает картинку своего исходного. ``materials`` -
        что красить; None - что отмечено в панели по умолчанию
        (paintkit_materials). Раскладка человека относится к главной
        карточке: её детали он и раскладывал

        Метка - отпечаток всего, от чего зависит картинка, кроме аргументов в
        имени: оружие, карточки, его OBJ, разрезы частей, базовая текстура.
        Без неё у универсального режима (донор у всех пушек один) с тем же
        сидом всплывала бы картинка с развёрткой прошлой пушки или прошлых
        разрезов
        """
        import hashlib
        import json

        from src.data import paintkit_defs

        paths = self._host.tf2_paths()
        if 'error' in paths:
            return paths
        t = self._host.preview.textures
        main = t.stable_main()
        if not main or not self._host._shown_weapon():
            return {'error': 'Сначала выберите оружие'}
        own = next((k for k in self._own_paintkits(paths['root'])
                    if k['id'] == int(kit) and k['item'] == int(item)), None)
        cards, game, spread = self._paintkit_offer(paths, item, own is not None)
        wanted = set((game if own else cards) if materials is None else materials)
        # Рецепт под одну пушку по деталям других материалов не разложить
        by_parts = own is None or own.get('by_parts', False)
        chosen = [c for c in cards if c in wanted and (c in game or (by_parts and c in spread))]
        if not chosen:
            return {'error': 'Отметьте хотя бы один материал'}
        assign = self._host.preview.paintkit_layouts.get(str(int(kit))) or None

        plans = []
        painted = [c for c in chosen if c in game]
        if painted:
            forced = None
            if assign:
                # Свой War Paint с раскладкой человека: группы Valve
                # выбираются заново переменными select
                from src.services.paintkit_layout import own_forced, own_groups
                defs = paintkit_defs.load(paths['root'])
                kit_obj, item_obj = (paintkit_defs.find_item(defs, kit, item)
                                     if defs else (None, None))
                layers, over = (paintkit_defs.template_layers(defs, kit_obj)
                                if kit_obj else ([], False))
                found = defs.variables(kit_obj, item_obj, 1) if layers and item_obj else None
                if found:
                    forced = own_forced(own_groups(found[1], layers, over), assign,
                                        layers, over) or None
            plans.append((painted, None, forced))
        by_source: Dict[str, List[str]] = {}
        for card in chosen:
            if card not in game:
                by_source.setdefault(t.part_cards.get(card, card), []).append(card)
        for source, members in by_source.items():
            generic = self._paintkit_generic(source, layout,
                                             assign if source == main and not own else None)
            if 'error' in generic:
                return generic
            plans.append((members, generic, None))

        try:
            obj_mtime = os.path.getmtime(self._host._obj_path) if self._host._obj_path else 0
        except OSError:
            obj_mtime = 0
        out = []
        for cards_of, generic, forced in plans:
            stamp = json.dumps([self._host._shown_weapon(), cards_of, generic, forced, obj_mtime],
                               sort_keys=True, default=str)
            out.append((cards_of, generic, forced,
                        hashlib.sha1(stamp.encode('utf-8')).hexdigest()[:10]))
        return out

    def _paintkit_job_for(self, kit: int, item: int, wear: int, seed: int, size: int,
                          generic, forced, out: str):
        """Воркер War Paint под текущее оружие и команду"""
        from src.services.paintkit_worker import PaintkitWorker
        from src.shared.constants import Team

        paths = self._host.tf2_paths()
        t = self._host.preview.textures
        team = 'blue' if t.active_team == Team.BLU else 'red'
        return PaintkitWorker(paths['root'], paths['textures_vpk'], paths['misc_vpk'],
                              kit, item, wear, team, seed, out, size=size,
                              generic=generic, forced=forced)

    def preview_paintkit(self, kit: int, item: int, wear: int = 1, seed: int = 0,
                         layout: int = 0, materials: Optional[List[str]] = None
                         ) -> Dict[str, Any]:
        """
        Быстрый предпросмотр War Paint (512 px): страница кладёт его на модель
        временно, пока человек выбирает. В текстуры ничего не пишется.
        Ответ - {images: {карточка: png}}

        Синхронно: при кэше текстур это доли секунды на материал, а страница
        всё равно ждёт картинку, чтобы показать. Одновременно считается один
        """
        seed = int(seed) & ((1 << 64) - 1)
        team = self._host.preview.textures.active_team
        plans = self._paintkit_plans(kit, item, layout, materials)
        if isinstance(plans, dict):
            return plans
        images = {}
        lock = self._paintkit_preview_lock
        with lock:
            for cards, generic, forced, tag in plans:
                out = os.path.join(self._host._work_dir(), f'warpaint_prev_{int(kit)}_{int(item)}'
                                   f'_w{int(wear)}_{seed}_{int(layout)}_{team}_{tag}.png')
                if not os.path.isfile(out):
                    ok, message = self._paintkit_job_for(kit, item, wear, seed, 512,
                                                         generic, forced, out).work()
                    if not ok:
                        return {'error': message}
                images.update((card, out) for card in cards)
        return {'images': images}

    def apply_paintkit(self, kit: int, item: int, wear: int = 1, seed: int = 0,
                       size: int = 1024, layout: int = 0,
                       materials: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Собирает War Paint в текстуры и кладёт их на карточки (см.
        _paintkit_plans): War Paint игры - туда, куда его кладёт игра
        (материалы с прокси WeaponSkin), и по желанию на остальные материалы
        узором по их деталям. У оружия без War Paint в игре узор ложится на
        каждый отмеченный материал по его деталям (``layout`` перемешивает,
        какой узор на какой детали)

        Собирается под активную команду: у War Paint с командными узорами RED
        и BLU разные, и человек накладывает второй, переключив команду. Дальше
        это обычные свои текстуры - их можно дорисовать и собрать в мод.
        Результат приходит событием ``paintkit_ready``
        """
        from src.services.paintkit_worker import PaintkitBatch
        from src.shared.constants import Team

        job = self._paintkit_job
        if job is not None and job.isRunning():
            return {'error': 'War Paint уже накладывается'}
        t = self._host.preview.textures
        weapon_key = self._host._shown_weapon()
        team = 'blue' if t.active_team == Team.BLU else 'red'
        seed = int(seed) & ((1 << 64) - 1)
        size = min(max(int(size), 256), 2048)
        plans = self._paintkit_plans(kit, item, layout, materials)
        if isinstance(plans, dict):
            return plans
        w = PaintkitBatch([
            (cards, self._paintkit_job_for(
                kit, item, wear, seed, size, generic, forced,
                os.path.join(self._host._work_dir(), f'warpaint_{int(kit)}_{int(item)}'
                             f'_w{int(wear)}_{team}_{seed}_{int(layout)}_{size}_{tag}.png')))
            for cards, generic, forced, tag in plans])
        w.progress.connect(lambda _pct, text: self._host._put('progress', text=text))

        def done(ok: bool, message: str) -> None:
            # Пока собиралось, человек мог уйти на другое оружие: чужой War
            # Paint на новую пушку не кладём
            same = (self._host._shown_weapon() == weapon_key
                    and ('blue' if self._host.preview.textures.active_team == Team.BLU
                         else 'red') == team)
            applied = 0
            try:
                if ok and same:
                    # Один War Paint - один шаг отмены, сколько бы карточек
                    # он ни покрасил
                    self._host._edits_held = True
                    try:
                        for card, png in [(c, png) for cards, png in w.done for c in cards]:
                            res = self._host.set_texture(card, png) or {}
                            if 'error' in res:
                                ok, message = False, res['error']
                                break
                            applied += 1
                    finally:
                        self._host._edits_held = False
                    if ok:
                        self._host._autosave()
            except Exception as exc:                      # noqa: BLE001
                logger.error(f'[paintkit] {exc}', exc_info=True)
                ok, message = False, str(exc)
            if applied and not ok:
                # Не легло на одну карточку - снимаем и с остальных: War Paint
                # на половине оружия выглядел бы наложенным целиком. Шаг
                # отмены ещё не записан, и последний снимок - то, что было до
                try:
                    self._host.undo_edits(0)
                except Exception as exc:                  # noqa: BLE001
                    logger.error(f'[paintkit] откат: {exc}', exc_info=True)
            self._host._put('paintkit_ready', ok=bool(ok and same),
                      message='' if ok and same else (message or 'Оружие сменилось'),
                      missing=list(w.missing))

        w.finished.connect(done)
        self._paintkit_job = w
        w.start()
        return {'started': True, 'team': team}

    def paintkit_layout(self, kit: int, item: int, layout: int = 0) -> Dict[str, Any]:
        """
        Раскладка War Paint по деталям для углублённого режима: слои с
        плитками узоров, детали с их слоем и карта треугольников для вьювера.
        См. paintkit_layout.describe
        """
        from src.data import paintkit_defs
        from src.services import paintkit_layout
        from src.services.game_vpk_reader import GameVpkReader
        from src.services.paintkit_worker import LOOKS_MASK, make_loader

        paths = self._host.tf2_paths()
        if 'error' in paths:
            return paths
        material = self._host.preview.textures.stable_main()
        if not material or not self._host._shown_weapon():
            return {'error': 'Сначала выберите оружие'}
        defs = paintkit_defs.load(paths['root'])
        kit_obj, item_obj = paintkit_defs.find_item(defs, kit, item) if defs else (None, None)
        if not (kit_obj and item_obj):
            return {'error': 'Этот War Paint не ложится на это оружие'}
        found = self._host.parts._parts_model(material)
        if isinstance(found, dict):
            return found
        model, obj_mat, card = found
        own = any(k['id'] == int(kit) and k['item'] == int(item)
                  for k in self._own_paintkits(paths['root']))
        reader = GameVpkReader([paths['textures_vpk'], paths['misc_vpk']])
        try:
            res = paintkit_layout.describe(
                defs, kit_obj, item_obj, model, obj_mat, own,
                make_loader(reader, LOOKS_MASK), make_loader(reader, 128),
                os.path.join(self._host._work_dir(), 'warpaint_layers'),
                self._host.preview.paintkit_layouts.get(str(int(kit))), int(layout))
        finally:
            reader.close()
        if 'error' not in res:
            res['material'] = card
        return res

    def set_paintkit_layout(self, kit: int, assign: Optional[Dict[str, int]] = None
                            ) -> Dict[str, Any]:
        """Раскладка человека для War Paint ``kit``: {деталь: слой}; пусто - автомат"""
        clean = {}
        for k, v in (assign or {}).items():
            try:
                layer = int(v)
            except (TypeError, ValueError):
                continue
            if isinstance(k, str) and len(k) < 16 and 0 <= layer < 64:
                clean[k] = layer
        if clean:
            self._host.preview.paintkit_layouts[str(int(kit))] = clean
        else:
            self._host.preview.paintkit_layouts.pop(str(int(kit)), None)
        # Раскладка - черновик до «Применить»: шагом отмены она не считается
        self._host._autosave(step=False)
        return {'ok': True}

    def _paintkit_targets(self, paintable: List[str], main: str) -> List[str]:
        """Карточки под War Paint: материалы WeaponSkin среди карточек, иначе главная

        Синие пары (c_detonator_blue) карточек не имеют - их заполняет команда
        BLU той же карточки, поэтому сравниваются только имена карточек
        """
        wanted = {m.lower() for m in paintable or []}
        cards = [c for c in (self._host.preview.textures.material_names or [])
                 if c and c.lower() in wanted]
        if main and main not in cards and (not wanted or main.lower() in wanted
                                           or not cards):
            cards.insert(0, main)
        return cards
