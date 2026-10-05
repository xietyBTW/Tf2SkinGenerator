"""
Части модели: своя картинка или цвет на отдельном куске геометрии.

Материал у предмета один, значит и текстура одна. «Синий приклад» — это вклейка
в общую текстуру по месту части на развёртке (texture_compose_service).
Склейка кладётся туда же, куда легла бы обычная своя текстура, поэтому сборка
и превью про части не знают.

Правда о покраске — мазки (`part_textures`, `part_colors`) и основа под ними
(`part_bases`). Склейка из них ВЫВОДИТСЯ, её файл — всего лишь последний
результат: его можно удалить и собрать заново. «Эта текстура — наша склейка»
значит ровно одно: у слота есть запись в `part_bases`.

Пересборка идёт ВНЕ замка сеанса: на 2048² это доли секунды, и всё это время
страница не могла бы спросить ничего другого. Под замком снимается задание
(основа, слои, куда писать) и потом кладётся результат; обогнанный более
свежей правкой результат выбрасывается по номеру поколения.

Слот — карточка плюс стиль или команда (`part_specs.slot_key`): у стиля
Bloody и у синей команды своя стопка мазков.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import itertools
import os
import threading
from collections import Counter
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, List, Optional, Tuple

from src.domain.preview import part_specs
from src.shared.logging_config import get_logger

if TYPE_CHECKING:
    from src.app.session import AppSession

logger = get_logger(__name__)


def _existing(path: Optional[str]) -> Optional[str]:
    """Путь, если файл на месте, иначе None."""
    return path if path and os.path.isfile(path) else None


class PartsEditor:
    """Покраска частей модели одного сеанса."""

    #: Сколько склеек держим на диске. Одной мало: путь — это ещё и адрес
    #: картинки во вьювере и в альбоме, и удалить только что показанную нельзя,
    #: пока браузер её грузит.
    _KEEP_COMPOSITES = 4

    #: Длинная сторона кадра анимации для вьювера: он держит все кадры
    #: текстурами на видеокарте, 60 кадров 1024² — это 240 МБ.
    #: ponytail: один размер на всех; ужимать до 512 — если слабые видеокарты
    #: пожалуются.
    _ANIM_PREVIEW_SIZE = 1024

    def __init__(self, host: "AppSession") -> None:
        self._host = host
        #: Порядок появления склеек: старые ФАЙЛЫ чистим (`_drop_old_composites`).
        self._compose_files: List[str] = []
        #: Номера файлов склеек: имя — это ещё и адрес во вьювере, и по прежнему
        #: имени браузер показал бы прошлую склейку из кэша.
        self._compose_counter = itertools.count(1)
        #: Последнее поколение каждого слота: результат старше него — обогнан.
        self._generations = itertools.count(1)
        self._latest: Dict[str, int] = {}
        #: {склейка превью: полная склейка со всеми кадрами} — на одну сборку.
        self._baked: Dict[str, str] = {}
        #: Анимация частей в 3D: номер последнего расчёта (старые обрываются
        #: по нему) и что крутить, если настройку включат позже.
        self._anim_seq = 0
        self._anim_last: Any = None
        self._anim_lock = threading.Lock()

    @property
    def preview(self):
        return self._host.preview

    @property
    def _lock(self):
        return self._host._lock

    # ═══════════════════════════════════════════════════════════════════════ #
    # Модель, карточка, слот
    # ═══════════════════════════════════════════════════════════════════════ #

    def _parts_model(self, material: str = '') -> Any:
        """(разбор модели, имя материала в OBJ, ключ карточки) или ошибка.

        Имена расходятся: у одноматериальной модели карточка зовётся служебным
        ключом, а группа в OBJ — материалом из SMD. Связываем их здесь, чтобы
        дальше никто про это не думал.
        """
        from src.domain.preview.texture_state import is_decor
        from src.services import mesh_parts_service

        if is_decor(material):
            return self._decor_parts_model(material)
        # Карточка части-материала: её геометрия — часть исходного материала, и
        # красят её там же (разбор на части о материалах частей не знает).
        material = self.preview.textures.part_cards.get(material, material)
        model = mesh_parts_service.load(self._host._obj_path, self.preview.part_cuts,
                                        self.preview.part_regions)
        if not model:
            return {'error': 'Модель ещё не загружена'}
        # Номера частей считаются по геометрии в кадре: у разбитой бутылки они
        # другие, и мазки легли бы не на те куски основной.
        if self._host._bodygroups:
            return {'error': 'Части красят основное состояние модели — верните переключатель'}
        found = self._mesh_of(model, material)
        return found if isinstance(found, dict) else (model, *found)

    def _item_meshes(self, model: Any) -> List[str]:
        """Материалы OBJ, которые и есть предмет: без призрака оригинала
        (подгонка своей модели) и пушки-носителя праздничного оружия — она
        подложка сцены, а предмет — гирлянда на ней. Без этого у
        одноматериальной гирлянды имён выходило два, и её карточку
        («__single__») искали по имени."""
        names = [n for n in model.materials if not n.startswith('ghost:')]
        own = set(self.preview.scene_item_materials or ())
        if own & set(names):
            names = [n for n in names if n in own]
        return names

    def _mesh_of(self, model: Any, material: str) -> Any:
        """(материал в OBJ, карточка) по имени карточки или ошибка."""
        t = self.preview.textures
        # Австралий — та же геометрия, что у главного материала, со своей
        # текстурой: его карточку назвали прямо, либо он включён в кадре —
        # тогда части красят то, что человек видит.
        gold = t.is_variant_material(material)
        if gold:
            material = ''
        names = self._item_meshes(model)
        if len(names) == 1:
            # У одноматериальной модели карточка ВСЕГДА служебная, как её ни
            # назови: вьювер знает материал по имени из SMD и присылает его,
            # а работа хранится под ключом главной текстуры.
            obj_mat, card = names[0], t.storage_main_key()
        else:
            wanted = (material or t.stable_main() or '').lower()
            obj_mat = next((n for n in names if n.lower() == wanted), '')
            if not obj_mat:
                return {'error': 'У этого материала нет геометрии'}
            card = material or t.storage_main_key()

        if t.australium_mat_name and (gold or (
                t.australium_active and card == t.storage_main_key())):
            card = t.australium_mat_name
        return obj_mat, card

    def _card_of_mesh(self, model: Any, obj_mat: str) -> str:
        """Обратное `_mesh_of`: карточка материала OBJ (главная — служебным
        ключом у одноматериальной модели), без варианта австралия."""
        t = self.preview.textures
        names = self._item_meshes(model)
        if len(names) == 1:
            return t.storage_main_key()
        known = [*t.material_names, *self.preview.misc_materials]
        return next((m for m in known if m.lower() == obj_mat.lower()), obj_mat)

    def _decor_parts_model(self, material: str) -> Any:
        """Части гирлянды: разбор её собственной модели, карточка = меш.

        Геометрия гирлянды — отдельный OBJ, и номера треугольников в нём свои;
        вьювер присылает их по мешу гирлянды. Поэтому ни служебного ключа, ни
        варианта здесь нет — имя меша и есть карточка.
        """
        from src.services import mesh_parts_service

        decor = self._host._decor_for_card(material)
        if not decor or material not in decor.materials:
            return {'error': 'Гирлянда не показана'}
        model = mesh_parts_service.load(decor.obj_path, self.preview.part_cuts,
                                        self.preview.part_regions)
        if not model or material not in model.materials:
            return {'error': 'У этого материала нет геометрии'}
        return model, material, material

    def _parts_obj(self, obj_mat: str) -> str:
        """OBJ, в котором лежит материал: у гирлянды — свой."""
        from src.domain.preview.texture_state import is_decor
        decor = self._host._decor_for_card(obj_mat) if is_decor(obj_mat) else None
        return decor.obj_path if decor else self._host._obj_path

    def _slot(self, card: str, style: Optional[int] = None,
              team: Optional[str] = None) -> str:
        """
        Ключ хранения покраски: карточка плюс стиль или команда.

        Склейка ложится в слот стиля (`skin_overrides`) или команды, и мазки у
        каждого слота свои: покрасил Bloody у гильотины, вернулся на базовый —
        там чисто, и следующий мазок не пересоберёт текстуру с чужими мазками.
        """
        from src.domain.preview.texture_state import is_decor
        from src.shared.constants import Team

        t = self.preview.textures
        if style is None:
            style = self.preview.active_style
        # У гирлянды нет стилей; команда — как у любой карточки: у огоньков
        # фестивайзера синие свои, и мазки на них — своя стопка.
        if is_decor(card):
            style = 0
        if team is None:
            team = t.active_team
        blu = team != Team.RED and self._per_team(card)
        return part_specs.slot_key(card, int(style or 0), blu)

    def _per_team(self, card: str) -> bool:
        """Своя ли у карточки текстура на каждую команду. У командного
        материала — всегда; у нейтрального — под «сделать командным»: тогда
        RED и BLU правят порознь, и основа у мазков тоже своя."""
        t = self.preview.textures
        return t.is_team_material(card) or bool(t.force_team)

    def _slot_texture(self, card: str, style: int, team: str) -> Optional[str]:
        """Что лежит на карточке в этом стиле/команде — без разрешения."""
        from src.domain.preview.texture_state import is_decor
        t = self.preview.textures
        if style and not is_decor(card):
            return _existing(t.skin_overrides.get(style, {}).get(card))
        return _existing(t.textures.get(team, {}).get(card))

    def _put_slot_texture(self, card: str, path: Optional[str],
                          style: int, team: str) -> None:
        """Кладёт текстуру в слот стиля/команды. Активный слот — обычной
        маршрутизацией (нейтральная текстура уходит в обе команды), чужой —
        напрямую: его правила показа сейчас не действуют."""
        from src.domain.preview.texture_state import is_decor
        from src.shared.constants import Team
        t = self.preview.textures
        # У гирлянды стилей нет: её слот — это только команда.
        if is_decor(card):
            if team == t.active_team:
                t.set_texture(card, path)
                return
            style = 0
        elif style == self.preview.active_style and team == t.active_team:
            t.set_texture(card, path)
            return
        if style:
            where = [t.skin_overrides.setdefault(style, {})]
        elif self._per_team(card):
            where = [t.textures.setdefault(team, {})]
        else:
            # Нейтральная карточка одна на обе команды: `parse_slot` называет
            # её слот красным, и запись в одну команду оставила бы другой
            # прежнюю, возможно уже удалённую, склейку.
            where = [t.textures.setdefault(side, {}) for side in (Team.RED, Team.BLU)]
        for slot in where:
            if path:
                slot[card] = path
            else:
                slot.pop(card, None)

    def _shape_key(self, obj_mat: str) -> str:
        """
        Отпечаток РАЗБИЕНИЯ: модель, её время и сделанные разрезы.

        По нему решается, отдавать ли карты треугольников: они занимают 96%
        ответа, а меняются только от резки. Разрез — список НАБОРОВ островов:
        {0: [[1], [2]]} и {0: [[1, 2]]} — разные разбиения.
        """
        cuts = sorted(
            (int(g), tuple(sorted(tuple(sorted(int(i) for i in bundle))
                                  for bundle in v)))
            for g, v in (self.preview.part_cuts.get(obj_mat) or {}).items())
        stamp = 0.0
        obj = self._parts_obj(obj_mat)
        try:
            stamp = os.path.getmtime(obj) if obj else 0.0
        except OSError:
            pass
        # Области — наборы треугольников, их бывает на тысячи номеров: в
        # отпечаток идёт их хэш, а не сами списки.
        areas = hashlib.md5(repr(self.preview.part_regions.get(obj_mat) or [])
                            .encode('utf-8')).hexdigest()[:12]
        return f"{obj}|{stamp}|{obj_mat}|{cuts}|{areas}"

    def _brush(self) -> Dict[str, Any]:
        """Настройки кисти на СЕЙЧАС — для мазков, которые пришли без своих."""
        p = self.preview
        return {'strength': p.part_tint, 'exact': p.part_exact,
                'edge': p.part_edge, 'edge_color': p.part_edge_color}

    # ═══════════════════════════════════════════════════════════════════════ #
    # Что показать
    # ═══════════════════════════════════════════════════════════════════════ #

    def describe(self, material: str = '', known_shape: str = '') -> Dict[str, Any]:
        """
        Части модели: что показать списком и чем подсвечивать в 3D.

        `tri_part` — номер части для КАЖДОГО треугольника материала: вьювер
        отдаёт попадание мыши номером треугольника, и по-другому связать клик с
        частью нечем.
        """
        found = self._parts_model(material)
        if isinstance(found, dict):
            return found
        model, obj_mat, card = found

        slot = self._slot(card)
        images = self.preview.part_textures.get(slot, {})
        colors = self.preview.part_colors.get(slot, {})
        parts = model.parts_of(obj_mat)
        # Странице отдаём ключ ГЕОМЕТРИИ, а не карточку варианта: по нему она
        # держит карты треугольников для вьювера, и у австралия они те же.
        shown = card if not self.preview.textures.is_variant_material(card) \
            else (material or self.preview.textures.storage_main_key())
        tri_part = [0] * len(model.uv.get(obj_mat) or [])
        for part in parts:
            for tri in part.triangles:
                if tri < len(tri_part):
                    tri_part[tri] = part.index

        shape = self._shape_key(obj_mat)
        live = self._live_entries(model, obj_mat)
        owner = lambda part: self._owner_card(live, part)      # noqa: E731

        out: Dict[str, Any] = {
            'material': shown,
            # Свои материалы этого материала: по ним страница рисует список в
            # настройках инструмента «Материал».
            'materials': [{'name': e['name'], 'triangles': len(e['tris'])}
                          for e in self.preview.part_materials.get(obj_mat, [])],
            'can_own': self._can_own(material or card),
            'parts': [{
                'id': part.index,
                'area': round(part.uv_area, 4),
                'triangles': len(part.triangles),
                # Куски, делящие развёртку, в игре красятся вместе — молчать
                # об этом нельзя.
                'shared': list(part.shared),
                # Картинки части слоями, снизу вверх.
                'images': [dict(i) for i in images.get(part.index, [])],
                'color': colors.get(part.index),
                # Дробление настраивается на КУСОК, а не на часть: номер части
                # меняется вместе с разбиением, номер куска — нет.
                'chunk': part.chunk,
                'sub': part.sub,
                # Группа — куски, делящие развёртку: они режутся вместе.
                'group': part.group,
                # Острова, из которых собран отрезок; пусто — остаток куска.
                'islands': list(part.islands),
                # Область, выделенная ножницами; -1 — не область. По номеру её
                # возвращают обратно.
                'region': part.region,
                # Место части на развёртке: по нему страница подсвечивает
                # область прямо на текстуре.
                'bbox': [round(v, 5) for v in part.uv_bbox],
                # Свой материал части ('' — общий).
                'own': owner(part),
            } for part in parts],
            'group_islands': model.group_islands.get(obj_mat) or {},
            'tint': self.preview.part_tint,
            'exact': bool(self.preview.part_exact),
            'edge': self.preview.part_edge,
            'edge_color': self.preview.part_edge_color,
            'shape': shape,
        }
        if known_shape != shape:
            # Карту «треугольник → часть» отдаём, только когда разбиение
            # изменилось. Острова вьювер считает сам — по UV меша.
            out['tri_part'] = tri_part
        return out

    @staticmethod
    def _owner_card(entries: List[dict], part: Any) -> str:
        """Материал части (из `_live_entries`), в котором она целиком ('' — в общем)."""
        tris = set(part.triangles)
        return next((e['name'] for e in entries if tris and tris <= set(e['tris'])), '')

    def _live_entries(self, model: Any, obj_mat: str) -> List[dict]:
        """Материалы частей `obj_mat`, чьи номера треугольников годятся для
        этой модели (part_materials.fits): остальные выбирали на другой."""
        from src.services import part_materials as pm

        total = len(model.uv.get(obj_mat) or [])
        end = model.weapon_end(obj_mat)
        return [e for e in self.preview.part_materials.get(obj_mat, ())
                if pm.fits(e, total, end)]

    def _keep_for(self, model: Any, obj_mat: str, card: str,
                  style: int) -> Optional[Callable[[int], bool]]:
        """
        Чьи треугольники красит склейка карточки `card` (None — все).

        Мазки частей лежат в слоте исходного и идут в склейку каждого его
        материала части, но ложатся только на треугольники этого материала:
        развёртки материалов могут накрывать одно место текстуры (зеркальные
        половины, своя модель снаряда со своей развёрткой), и краска одного
        потекла бы на другой. Стилей материалы частей не касаются.
        """
        if style:
            return None
        source = self._source_card(card)
        entries = [e for e in self._live_entries(model, obj_mat) if e.get('card') == source]
        if not entries:
            return None
        if card != source:
            own = next((set(e['tris']) for e in entries if e['name'] == card), set())
            return own.__contains__
        taken = set().union(*(e['tris'] for e in entries))
        return lambda tri: tri not in taken

    def part_mask(self, material: str = '', part: int = 0) -> Dict[str, Any]:
        """
        Картинка-подсветка одной части: её форма на развёртке.

        Показывать надо ту же маску, по которой красит склейка: прямоугольник
        у детали, лежащей наискось, накрывал соседние куски. Файл кэшируется по
        отпечатку разбиения — форма меняется только от резки.
        """
        found = self._parts_model(material)
        if isinstance(found, dict):
            return found
        model, obj_mat, card = found

        polys = model.polygons(obj_mat, int(part))
        if not polys:
            return {'error': 'У этой части нет развёртки'}

        from src.services import texture_compose_service
        # В пропорциях САМОЙ текстуры: у тела шпиона она 1024×512, и квадратная
        # маска ложилась бы на кадр растянутой.
        shape = self._texture_shape(card)
        stamp = hashlib.md5(self._shape_key(obj_mat).encode('utf-8')).hexdigest()[:10]
        tail = f"{shape[0]}x{shape[1]}" if shape else 'square'
        out = os.path.join(self._host._work_dir(), 'masks',
                           f"{stamp}_{int(part)}_{tail}.png")
        if not os.path.isfile(out):
            texture_compose_service.outline_png(polys, out, shape=shape)
        return {'part': int(part), 'mask': out}

    def _texture_shape(self, card: str):
        """Размер картинки, показанной на этом материале. None — не прочитать."""
        t = self.preview.textures
        path = t.uploaded_for_mat(card) or t.game_base(card)
        if not path or not os.path.isfile(path):
            return None
        try:
            from PIL import Image
            with Image.open(path) as im:
                return im.size
        except (OSError, ValueError):
            return None

    def part_shape(self, material: str = '', part: int = 0,
                   layer: Optional[int] = None) -> Dict[str, Any]:
        """
        Развёртка одной части: по ней окно посадки рисует, куда ляжет картинка.

        ``layer`` — какую из картинок части правят (отрицательный — с конца);
        None — кладут новую. Основа для окна — всё, что уже лежит на материале,
        КРОМЕ правимого слоя: его окно рисует живьём.
        """
        found = self._parts_model(material)
        if isinstance(found, dict):
            return found
        model, obj_mat, card = found

        one = next((p for p in model.parts_of(obj_mat) if p.index == int(part)), None)
        if one is None:
            return {'error': 'Такой части нет'}

        with self._lock:
            stack = [dict(i) for i in (self.preview.part_textures.get(self._slot(card))
                                       or {}).get(int(part), [])]
            idx: Optional[int] = None
            if layer is not None and stack and -len(stack) <= int(layer) < len(stack):
                idx = int(layer) % len(stack)
            # Под частью в своём материале лежит его текстура, а не исходного.
            job = self._context_job(
                model, obj_mat, card, skip=(int(part), idx) if idx is not None else None,
                under=self._owner_card(self._live_entries(model, obj_mat), one) or card)
        spec = stack[idx] if idx is not None else None
        frames: List[str] = []
        delays: List[int] = []
        if spec:
            # Кадры анимации раскладываем сами: браузер их из гифки не достаёт.
            from src.services import texture_compose_service
            frames, delays = texture_compose_service.export_frames(
                spec['path'], os.path.join(self._host._work_dir(), 'frames'),
                f"part{int(part)}")
        return {
            'frames': frames,
            'delays': delays,
            'part': one.index,
            # Габарит, в который вписана картинка: у наклейки, пережившей
            # разрез, это габарит ПРЕЖНЕЙ части (её якорь).
            'bbox': [round(v, 6) for v in ((spec and spec.get('anchor')) or one.uv_bbox)],
            'polygons': [[[round(u, 6), round(v, 6)] for u, v in tri]
                         for tri in model.polygons(obj_mat, one.index)],
            'image': spec,
            'layer': idx,
            'images': stack,
            'base': self._run_context(job),
        }

    def _context_job(self, model: Any, obj_mat: str, card: str,
                     skip: Optional[tuple], under: str = '') -> Dict[str, Any]:
        """Под замком: основа окна посадки — материал со всем, что на нём лежит,
        кроме правимого слоя (иначе под живой картинкой лежала бы её же копия).
        `under` — чья основа под мазками (материал части), по умолчанию `card`."""
        keep = self._keep_for(model, obj_mat, under or card, self.preview.active_style)
        return {'base': self._compose_base(under or card) or '',
                'layers': self._part_layers(model, obj_mat, self._slot(card), skip, keep),
                'out': os.path.join(self._host._work_dir(),
                                    f"context_{self._next_compose()}.png")}

    def _run_context(self, job: Dict[str, Any]) -> str:
        from src.services import texture_compose_service

        if not job['base'] or not job['layers']:
            return job['base']
        result = texture_compose_service.compose(job['base'], job['layers'],
                                                 job['out'], frames=1)
        if not result:
            return job['base']
        with self._lock:
            # В общую очередь: уберётся со старыми склейками, а не копится.
            self._compose_files.append(result)
        return result

    # ═══════════════════════════════════════════════════════════════════════ #
    # Мазки
    # ═══════════════════════════════════════════════════════════════════════ #

    def set_part_texture(self, material: str = '', part: int = 0,
                         path: Optional[str] = None,
                         options: Optional[Dict[str, Any]] = None,
                         layer: Optional[int] = None) -> Dict[str, Any]:
        """
        Картинки одной части — слоями, снизу вверх.

        ``path`` — новая картинка: без ``layer`` ложится ПОВЕРХ уже лежащих,
        с ним — заменяет названный слой. Без пути, но с ``options`` — правка
        посадки уже положенной (``layer``, по умолчанию верхней). Без того и
        другого — убрать названный слой либо все картинки части разом.
        """
        found = self._parts_model(material)
        if isinstance(found, dict):
            return found
        model, obj_mat, card = found

        if path and not os.path.isfile(path):
            return {'error': 'Файл не найден'}

        with self._lock:
            chosen = self.preview.part_textures.setdefault(self._slot(card), {})
            stack = list(chosen.get(int(part), []))
            at = None if layer is None else int(layer)
            if at is not None and not -len(stack) <= at < len(stack):
                return {'error': 'Такой картинки на части нет'}
            if path:
                entry = part_specs.image_spec(
                    {**self._absolute_size(options, path, model, obj_mat, card,
                                           int(part)), 'path': path})
                if at is None:
                    stack.append(entry)
                else:
                    stack[at] = entry
            elif options is not None:
                if not stack:
                    return {'error': 'На этой части нет картинки'}
                idx = -1 if at is None else at
                spec = dict(stack[idx])
                # Якорь переживает правку посадки: он говорит, В ЧЁМ картинка
                # живёт, а окно двигает её ВНУТРИ этого габарита.
                fresh = part_specs.image_spec({**options, 'path': spec['path']})
                spec.update({k: v for k, v in fresh.items() if k not in ('path', 'anchor')})
                stack[idx] = spec
            elif at is None:
                stack = []
            else:
                del stack[at]
            if stack:
                chosen[int(part)] = stack
            else:
                chosen.pop(int(part), None)
            jobs = self._plans(model, obj_mat, card)
        return self._commit(jobs)

    def _absolute_size(self, options: Optional[Dict[str, Any]], path: str,
                       model: Any, obj_mat: str, card: str, part: int) -> Dict[str, Any]:
        """
        Посадка с размером В ДОЛЯХ ТЕКСТУРЫ (`size_uv`) — в масштабы части.

        Так приходит вставка скопированной картинки: «того же размера» значит
        того же на текстуре, а масштаб считается от габарита части — один и
        тот же масштаб на другой детали дал бы другую картинку. Пересчёт здесь,
        а не на странице: габарит части, размер текстуры и картинки знает
        Python, и склейка вписывает ровно по этим числам (`place_image`).
        """
        opts = dict(options or {})
        size = opts.pop('size_uv', None)
        one = next((p for p in model.parts_of(obj_mat) if p.index == part), None)
        shape = self._texture_shape(card)
        if not size or one is None or not shape:
            return opts
        try:
            from PIL import Image
            with Image.open(path) as im:
                iw, ih = max(1, im.width), max(1, im.height)
        except (OSError, ValueError):
            return opts
        tex_w, tex_h = shape
        u0, v0, u1, v1 = one.uv_bbox
        bw = max(1e-6, (u1 - u0) * tex_w)
        bh = max(1e-6, (v1 - v0) * tex_h)
        fit = str(opts.get('fit') or 'contain')
        if fit == 'stretch':
            base_w, base_h = bw, bh
        else:
            k = (max if fit == 'cover' else min)(bw / iw, bh / ih)
            base_w, base_h = iw * k, ih * k
        opts['scale'] = float(size[0]) * tex_w / base_w
        opts['scale_y'] = float(size[1]) * tex_h / base_h
        opts['offset'] = [0.0, 0.0]            # на новой детали — по её центру
        return opts

    def move_part_texture(self, material: str = '', part: int = 0,
                          layer: int = 0, to: int = 0) -> Dict[str, Any]:
        """Переставляет картинку части в стопке: порядок и есть наложение."""
        found = self._parts_model(material)
        if isinstance(found, dict):
            return found
        model, obj_mat, card = found

        with self._lock:
            chosen = self.preview.part_textures.setdefault(self._slot(card), {})
            stack = list(chosen.get(int(part), []))
            n = len(stack)
            src, dst = int(layer), int(to)
            if not (-n <= src < n and -n <= dst < n):
                return {'error': 'Такой картинки на части нет'}
            src %= n
            dst %= n
            if src == dst:
                return self._host.view_state()
            stack.insert(dst, stack.pop(src))
            chosen[int(part)] = stack
            jobs = self._plans(model, obj_mat, card)
        return self._commit(jobs)

    def set_part_colors(self, material: str = '',
                        colors: Optional[Dict[str, Any]] = None,
                        strength: Optional[float] = None,
                        exact: Optional[bool] = None) -> Dict[str, Any]:
        """
        Красит части: {номер части: цвет}, значение None — снять.

        Цвет — «#rrggbb» или градиент словарём (см. `part_specs.color_spec`).
        Скопом, а не по одной: «раскрасить всё случайно» и сброс — одно
        действие человека, и склейка на них одна.

        Без цветов это смена КИСТИ (сила, точный цвет): уже покрашенное помнит
        свою и не перекрашивается — ни пересборки, ни шага Ctrl+Z.
        """
        found = self._parts_model(material)
        if isinstance(found, dict):
            return found
        model, obj_mat, card = found

        with self._lock:
            if strength is not None:
                self.preview.part_tint = min(1.0, max(0.05, float(strength)))
            if exact is not None:
                self.preview.part_exact = bool(exact)
            if not colors:
                jobs = None
            else:
                brush = self._brush()
                painted = self.preview.part_colors.setdefault(self._slot(card), {})
                for part, color in colors.items():
                    if color:
                        painted[int(part)] = part_specs.color_spec(color, brush)
                    else:
                        painted.pop(int(part), None)
                jobs = self._plans(model, obj_mat, card)
        if jobs is None:
            # Настройку кисти запомнить надо (ползунок вернётся к ней с
            # работой), а шагом истории она не является.
            self._host._autosave(step=False)
            return self._host.view_state()
        return self._commit(jobs)

    def set_part_edge(self, material: str = '', width: float = 0.0,
                      color: str = '') -> Dict[str, Any]:
        """
        Окантовка для СЛЕДУЮЩИХ мазков: ширина в долях стороны текстуры, чтобы
        работа одинаково выглядела и в 512, и в 2048. Полоса ложится ВНУТРЬ
        части — наружу она покрасила бы соседнюю деталь.
        """
        found = self._parts_model(material)
        if isinstance(found, dict):
            return found
        with self._lock:
            self.preview.part_edge = max(0.0, min(0.1, float(width)))
            if color:
                self.preview.part_edge_color = str(color)
        self._host._autosave(step=False)
        return self._host.view_state()

    def clear_parts(self, material: str = '') -> Dict[str, Any]:
        """Снимает с частей всё разом — «начать заново» одной кнопкой."""
        found = self._parts_model(material)
        if isinstance(found, dict):
            return found
        model, obj_mat, card = found

        with self._lock:
            slot = self._slot(card)
            self.preview.part_textures.pop(slot, None)
            self.preview.part_colors.pop(slot, None)
            jobs = self._plans(model, obj_mat, card)
        return self._commit(jobs)

    # ═══════════════════════════════════════════════════════════════════════ #
    # Части — своими материалами (src/services/part_materials.py)
    # ═══════════════════════════════════════════════════════════════════════ #

    def set_part_material(self, material: str = '', parts: Optional[Iterable[int]] = None,
                          target: str = '') -> Dict[str, Any]:
        """
        Отдаёт части в свой материал или возвращает их в общий.

        `target`: '' — новый материал, имя — добавить в этот, '-' — вернуть в
        общий. Треугольник принадлежит одному материалу: отданный в новый
        уходит из прежнего. Опустевший материал исчезает вместе с карточкой.
        """
        from src.services import part_materials as pm

        if not self._can_own(material):
            return {'error': 'Частям этого предмета свой материал не дать'}
        found = self._parts_model(material)
        if isinstance(found, dict):
            return found
        model, obj_mat, card = found
        wanted = {int(p) for p in (parts or ())}
        tris = {t for part in model.parts_of(obj_mat) if part.index in wanted
                for t in part.triangles}
        if not tris:
            return {'error': 'Выберите части'}
        sources = pm.sources_of_obj(self._host._obj_path)
        if not sources:
            # OBJ собран до того, как превью стало помнить свои SMD.
            return {'error': 'Откройте предмет заново'}

        t = self.preview.textures
        base_card = t.storage_main_key() if t.is_variant_material(card) else card
        # `total` — сколько треугольников у материала сейчас, `late` — сколько
        # из них само оружие до снаряда в оружии: номера годятся только для
        # такой модели (сборка и вьювер сверяются, part_materials.fits).
        now = {'total': len(model.uv.get(obj_mat) or []),
               **({'late': model.late[obj_mat]} if obj_mat in model.late else {})}
        created = ''
        with self._lock:
            entries = self.preview.part_materials.get(obj_mat, [])
            into = None
            if target and target != '-':
                # Проверка до вычитания: иначе ошибка оставила бы треугольники
                # ничьими. Материал, выбранный на другой модели, не годится.
                into = next((e for e in self._live_entries(model, obj_mat)
                             if e['name'] == target), None)
                if into is None:
                    return {'error': 'Нет такого материала'}
            for entry in entries:
                entry['tris'] = sorted(set(entry['tris']) - tris)
            if into is not None:
                into['tris'] = sorted(set(into['tris']) | tris)
                into.pop('late', None)
                into.update(now, sources=sources)
            elif not target:
                from src.services.edited_vmt_service import EditedVMTService
                taken = [*model.materials, *self.preview.part_material_names()]
                created = pm.next_name(obj_mat, taken, EditedVMTService.has_edited_vmt)
                self.preview.part_materials.setdefault(obj_mat, []).append(
                    {'name': created, 'card': base_card, 'tris': sorted(tris),
                     **now, 'sources': sources})
            for empty in [e['name'] for e in entries if not e['tris']]:
                self._forget_part_material(empty)
            self.preview.sync_part_cards()
            if created:
                self._fork_card(base_card, created)
            # Треугольники сменили материал — каждая склейка красит теперь
            # другой их набор (`_keep_for`): исходный и все его материалы частей.
            jobs = [job for team in self._teams(base_card)
                    for job in self._plans(model, obj_mat, base_card, 0, team)]
        self._finish(jobs)
        self._host._autosave(step=True)
        return {**self._host.view_state(), 'created': created}

    def _teams(self, card: str) -> Tuple[str, ...]:
        """Команды, у которых у карточки свой слот."""
        from src.shared.constants import Team
        return (Team.RED, Team.BLU) if self._per_team(card) else (Team.RED,)

    def _fork_card(self, base: str, name: str) -> None:
        """
        ПОД ЗАМКОМ: новый материал части — копия исходного. Его своя картинка
        (та, что под мазками) по командам, правка VMT, карты и настройки
        текстуры переходят к материалу части, и часть выглядит как раньше.
        Дальше они живут порознь: картинка на исходном часть не задевает.
        """
        p = self.preview
        for team in self._teams(base):
            slot = self._slot(base, 0, team)
            own = (p.part_bases[slot] if slot in p.part_bases
                   else self._slot_texture(base, 0, team))
            if _existing(own):
                self._put_slot_texture(name, own, 0, team)
        key = self._host._card_key(base)
        if key in p.texture_maps:
            p.texture_maps[name] = copy.deepcopy(p.texture_maps[key])
        if key in p.texture_overrides:
            p.texture_overrides[name] = copy.deepcopy(p.texture_overrides[key])
        self._fork_vmt(base, name)

    def _fork_vmt(self, base: str, name: str) -> None:
        """Правка VMT исходного — копией к материалу части, вместе с игровым
        оригиналом: по нему сборка переносит правку на строки скина."""
        from src.services.edited_vmt_service import EditedVMTService as Vmt

        target = self._host._vmt_target(base)
        if isinstance(target, dict):
            return
        key = target[1]
        edited = Vmt.get_edited_vmt(key)
        if not (edited and os.path.exists(edited)):
            return
        try:
            with open(edited, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except OSError as exc:
            logger.warning(f"[ЧАСТИ] правка VMT {key} не скопирована: {exc}")
            return
        original = Vmt.read_original_backup(key)
        if original is not None:
            Vmt.save_original_backup(name, original)
        Vmt.save_edited_vmt(name, content)

    def _can_own(self, material: str) -> bool:
        """Можно ли дать частям свой материал. Сборка переносит их в SMD той
        модели, на которой их выбрали: у мода из VPK и у гирлянды его нет, а
        Dead Ringer показывает одну модель, а в мод кладёт материалы другой.
        Своя модель — можно: её SMD сборка кладёт на место игрового тем же
        порядком треугольников (part_materials.specs_for_custom_model)."""
        from src.data.weapons import MATERIAL_ONLY_WEAPON_KEYS, PREVIEW_MDL_OVERRIDE
        from src.domain.preview.texture_state import is_decor

        key = self.preview.weapon_key
        return not (self.preview.custom_vpk_mode or is_decor(material)
                    or key in MATERIAL_ONLY_WEAPON_KEYS or key in PREVIEW_MDL_OVERRIDE)

    def drop_part_material(self, name: str = '') -> Dict[str, Any]:
        """Возвращает все части материала в общий; карточка исчезает."""
        card = self.preview.textures.part_cards.get(name, '')
        with self._lock:
            if not self._forget_part_material(name):
                return {'error': 'Нет такого материала'}
            self.preview.sync_part_cards()
        # Мазки на этих треугольниках снова красит склейка исходного.
        found = self._parts_model(card)
        if not isinstance(found, dict):
            model, obj_mat, _ = found
            with self._lock:
                jobs = [job for team in self._teams(card)
                        for job in self._plans(model, obj_mat, card, 0, team)]
            self._finish(jobs)
        self._host._autosave(step=True)
        return self._host.view_state()

    def _forget_part_material(self, name: str) -> bool:
        """Убирает материал части и всё, что лежало на его карточке (под замком)."""
        p = self.preview
        for base, entries in list(p.part_materials.items()):
            kept = [e for e in entries if e['name'] != name]
            if len(kept) == len(entries):
                continue
            if kept:
                p.part_materials[base] = kept
            else:
                p.part_materials.pop(base)
            p.drop_part_cards([name])
            return True
        return False

    # ── Снаряд в оружии ──────────────────────────────────────────────────── #

    def forget_projectile(self, part_smd: str) -> None:
        """
        Сбрасывает правки, привязанные к треугольникам снаряда в оружии: его
        модель сменилась (своя ↔ игровая), и номера его треугольников и частей
        теперь чужие — как forget_decor_look у гирлянды.

        Снаряд идёт в конце своего материала (`ModelParts.late`), так что номера
        частей и треугольников самого оружия не меняются; уходят мазки частей
        снаряда, его разрезы и области, его треугольники в материалах частей.
        Материал, которого кроме снаряда нет ни у кого (ракета Ракетницы),
        уходит весь. Область ножниц, задевшая и оружие, и снаряд, обрезается
        до оружия — номера частей оружия при этом сдвигаются, и его мазки
        переезжают по треугольникам, как при резке (`_reshape`). Зовётся ДО
        смены модели: разбор берётся с кадра.
        """
        from src.services import mesh_parts_service
        from src.services import part_materials as pm

        try:
            with open(part_smd, encoding='utf-8', errors='replace') as f:
                shell = list(pm.material_counts(f.read()))
        except OSError:
            return
        p = self.preview
        obj = self._host._obj_path
        jobs: List[Optional[Dict[str, Any]]] = []
        with self._lock:
            model = mesh_parts_service.load(obj, p.part_cuts, p.part_regions)
            if not model:
                return
            for name in shell:
                # Имя в OBJ — как в SMD; скрытого снаряда со своим материалом
                # в кадре нет вовсе — тогда снаряду принадлежит всё.
                mesh = next((m for m in model.uv if m.lower() == name.lower()), name)
                total = len(model.uv.get(mesh) or [])
                end = model.weapon_end(mesh) if mesh in model.uv else 0
                slots = [s for s in {*p.part_textures, *p.part_colors}
                         if self._slot_mesh(model, s, mesh) == mesh]
                was = model.parts_of(mesh)
                # Материалы частей, выбранные на другой модели, и так не
                # собираются: новый `late` «оживил» бы их на чужих номерах.
                for entry in list(p.part_materials.get(mesh, [])):
                    if not pm.fits(entry, total, end):
                        continue
                    entry['tris'] = [t for t in entry['tris'] if t < end]
                    if entry['tris']:
                        entry['late'] = end
                    else:
                        self._forget_part_material(entry['name'])
                groups = {part.group for part in was if part.triangles and min(part.triangles) < end}
                regions = p.part_regions.get(mesh) or []
                straddle = any(r and min(r) < end <= max(r) for r in regions)
                kept = {'cuts': {g: v for g, v in (p.part_cuts.get(mesh) or {}).items()
                                 if int(g) in groups},
                        'regions': [left for r in regions if (left := [t for t in r if t < end])]}
                for store, value in ((p.part_cuts, kept['cuts']),
                                     (p.part_regions, kept['regions'])):
                    if value:
                        store[mesh] = value
                    else:
                        store.pop(mesh, None)
                now = (mesh_parts_service.load(obj, p.part_cuts, p.part_regions)
                       if straddle else model)
                if straddle and now:
                    owner = {t: part.index for part in was for t in part.triangles if t < end}
                    boxes = {part.index: list(part.uv_bbox) for part in was}
                    for slot in slots:
                        self._move_parts(now, mesh, slot, owner, boxes)
                else:
                    weapon = {part.index for part in was
                              if part.triangles and min(part.triangles) < end}
                    for slot in slots:
                        for store in (p.part_textures, p.part_colors):
                            strokes = store.get(slot) or {}
                            for k in [k for k in strokes if int(k) not in weapon]:
                                del strokes[k]
                for slot in slots:
                    card, style, team = part_specs.parse_slot(slot)
                    jobs += self._plans(now or model, mesh, card, style, team)
            p.sync_part_cards()
        self._finish(jobs)

    def _slot_mesh(self, model: Any, slot: str, shell: str) -> str:
        """Материал OBJ, части которого красят мазки слота ('' — не модели).
        Карточку, названную как материал снаряда `shell`, сверяем по имени:
        скрытого снаряда в кадре нет, и для одноматериального OBJ `_mesh_of`
        назвал бы меш оружия."""
        from src.domain.preview.texture_state import is_decor

        card = part_specs.parse_slot(slot)[0]
        if is_decor(card) or card in self.preview.textures.part_cards:
            return ''
        if card.lower() == str(shell).lower():
            return shell
        found = self._mesh_of(model, card)
        return '' if isinstance(found, dict) else found[0]

    def own_projectile(self, texture: Optional[str]) -> str:
        """
        Своя модель снаряда из OBJ/GLB — своим материалом части; его имя
        или '' (не вышло).

        Развёртка у такой модели своя, под свою картинку. В текстуре оружия
        она легла бы на чужие места, а краска снаряда — на оружие; в текстуре
        игрового снаряда, которую делят и другие модели (летящее ядро Пушки,
        ракета Обжигающего выстрела), испортила бы их. Свой материал — своя
        текстура: картинка из файла, без неё ровная серая под покраску. Карты
        материала исходного сняты по его развёртке и сюда не переходят.
        Зовётся, когда приехал OBJ со своим снарядом: номера его треугольников
        знает только он.
        """
        from src.services import mesh_parts_service
        from src.services import part_materials as pm
        from src.services.edited_vmt_service import EditedVMTService

        p = self.preview
        created = ''
        with self._lock:
            model = mesh_parts_service.load(self._host._obj_path, p.part_cuts,
                                            p.part_regions)
            if not model:
                return ''
            for mesh, first in model.late.items():
                total = len(model.uv.get(mesh) or [])
                card = self._card_of_mesh(model, mesh)
                if first >= total or not self._can_own(card):
                    continue
                taken = [*model.materials, *p.part_material_names()]
                name = pm.next_name(mesh, taken, EditedVMTService.has_edited_vmt)
                p.part_materials.setdefault(mesh, []).append(
                    {'name': name, 'card': card, 'tris': list(range(first, total)),
                     'total': total, 'late': first,
                     'sources': pm.sources_of_obj(self._host._obj_path)})
                p.sync_part_cards()
                image = (texture if texture and os.path.isfile(texture)
                         else self._plain_image())
                for team in self._teams(card):
                    self._put_slot_texture(name, image, 0, team)
                key = self._host._card_key(card)
                if key in p.texture_overrides:
                    p.texture_overrides[name] = copy.deepcopy(p.texture_overrides[key])
                self._fork_vmt(card, name)
                created = created or name
        return created

    def _plain_image(self) -> str:
        """Ровная серая основа своего снаряда, у которого в файле нет картинки."""
        path = os.path.join(self._host._work_dir(), 'plain_projectile.png')
        if not os.path.isfile(path):
            from PIL import Image
            Image.new('RGB', (512, 512), (150, 150, 150)).save(path)
        return path

    def part_material_view(self) -> Dict[str, Any]:
        """Что нужно вьюверу: какие треугольники каких мешей рисовать своими
        материалами.

        Номера годятся только для модели, на которой выбирали части: в другом
        состоянии (разбитая бутылка) или после обновления игры меш другой, и
        такой материал не показывается вовсе (part_materials.fits). Снаряд в
        оружии идёт в конце материала: скрыт он или заменён своей моделью —
        материалы самого оружия остаются. `total` уходит вьюверу затем же:
        в другой сцене (руки) меш с тем же именем бывает другим.

        Треугольники — отрезками [начало, сколько]: часть почти всегда лежит
        подряд (1576 номеров у обреза — 16 отрезков), а ответ уходит странице
        при каждой правке."""
        if not self.preview.part_materials or self._host._shape_changed():
            return {}
        from src.services import mesh_parts_service
        model = mesh_parts_service.load(self._host._obj_path, self.preview.part_cuts,
                                        self.preview.part_regions)

        def runs(tris) -> List[List[int]]:
            out: List[List[int]] = []
            for tri in sorted(tris):
                if out and out[-1][0] + out[-1][1] == tri:
                    out[-1][1] += 1
                else:
                    out.append([tri, 1])
            return out

        view: Dict[str, Any] = {}
        for base in self.preview.part_materials:
            live = self._live_entries(model, base) if model else []
            if live:
                view[base] = {'total': len(model.uv.get(base) or []), 'parts': [
                    {'name': e['name'], 'runs': runs(e['tris'])} for e in live]}
        return view

    def set_base(self, card: str, path: Optional[str]) -> Optional[Dict[str, Any]]:
        """
        Своя текстура на покрашенную карточку: ложится ПОД мазки.

        Раньше она заменяла склейку, а мазки оставались числиться: чипы
        говорили «покрашено», текстура — нет, и следующий мазок внезапно
        возвращал всё поверх новой картинки.

        None — карточка не покрашена, текстура кладётся обычным путём; {} —
        легла под мазки; {'error': …} — пересобрать сейчас нельзя (модель не
        та или не загружена), и основу не трогаем: иначе на экране и в сборке
        осталась бы склейка на прежней основе.
        """
        with self._lock:
            if self._slot(card) not in self.preview.part_bases:
                return None
        found = self._parts_model(card)
        if isinstance(found, dict):
            return found
        # Модель и меш — от разбора, а карточка — ИСХОДНАЯ: разбор переводит
        # главную карточку в австралиевую, когда тот включён, и основа легла
        # бы не в тот слот.
        model, obj_mat, _ = found
        with self._lock:
            slot = self._slot(card)
            if slot not in self.preview.part_bases:
                return None
            self.preview.part_bases[slot] = path or ''
            source = self._source_card(card)
            # У материала части мазки — в слоте исходного: пересобираем только
            # его склейку, исходный не трогаем.
            jobs = (self._plans(model, obj_mat, source, only=card) if source != card
                    else self._plans(model, obj_mat, card))
        self._finish(jobs)
        return {}

    # ── Резка ─────────────────────────────────────────────────────────────── #

    def set_part_detail(self, material: str = '', detail: float = 0.0) -> Dict[str, Any]:
        """Раздробить ВСЕ куски одинаково: доля 0..1 от числа швов каждого куска."""
        def everything(model, obj_mat) -> Dict[int, List[List[int]]]:
            share = max(0.0, min(1.0, float(detail)))
            out: Dict[int, List[List[int]]] = {}
            for group, count in (model.group_islands.get(obj_mat) or {}).items():
                if count < 2:
                    continue
                # Обычное округление, а не round(): у группы с одним швом
                # round(0.5) даёт 0 (банковское правило).
                take = int(share * (count - 1) + 0.5)
                # Острова пронумерованы от крупного: «первые N» — самые заметные.
                if take:
                    out[group] = [[i] for i in range(take)]
            return out

        return self._reshape(material, everything)

    def toggle_part_island(self, material: str = '', group: int = 0,
                           island: int = 0) -> Dict[str, Any]:
        """
        Отрезает названный остров развёртки или приращивает его обратно.

        Режется ГРУППА — все куски, делящие эту развёртку: у рук шпиона левая и
        правая делят её целиком, и разрезать одну без другой нельзя. Остров,
        вынутый из набора, возвращается в остаток куска.
        """
        def one(model, obj_mat) -> Dict[int, List[List[int]]]:
            out = self._cut_plan(obj_mat)
            made = [list(b) for b in out.get(int(group), ())]
            was = [b for b in made if int(island) in b]
            if was:
                for bundle in was:
                    bundle.remove(int(island))
            else:
                made.append([int(island)])
            made = [b for b in made if b]
            if made:
                out[int(group)] = made
            else:
                out.pop(int(group), None)
            return out

        return self._reshape(material, one)

    def _cut_plan(self, obj_mat: str) -> Dict[int, List[List[int]]]:
        """Копия разрезов ЭТОГО материала, которую можно править отдельно."""
        return {int(g): [list(b) for b in v]
                for g, v in (self.preview.part_cuts.get(obj_mat) or {}).items()}

    def add_part_region(self, material: str = '',
                        triangles: Optional[List[int]] = None) -> Dict[str, Any]:
        """
        Выделенное ножницами — в отдельную часть.

        Треугольники с ТЕМИ ЖЕ пикселями развёртки (зеркальная половина)
        добираются сами: в игре они покрасятся вместе, и часть, которая об
        этом молчит, обещала бы то, чего не будет. Сколько добрано — в ответе
        (`mirrored`), странице об этом говорить.
        """
        picked = {int(t) for t in (triangles or ())}
        if not picked:
            return {'error': 'Ничего не выделено'}
        added = {'mirrored': 0}

        def grow(model, obj_mat) -> List[List[int]]:
            uv = model.uv.get(obj_mat) or []
            chosen = {t for t in picked if 0 <= t < len(uv)}
            same: Dict[tuple, List[int]] = {}
            for index, tri in enumerate(uv):
                same.setdefault(tuple(sorted(tri)), []).append(index)
            full = {twin for t in chosen for twin in same[tuple(sorted(uv[t]))]}
            added['mirrored'] = len(full - chosen)
            # Прежние области отдают выделенное новой: у треугольника одна
            # часть, и хранить его дважды — значит однажды ответить не то.
            kept = [[t for t in region if t not in full]
                    for region in self.preview.part_regions.get(obj_mat) or []]
            return [r for r in kept if r] + [sorted(full)]

        out = self._reshape(material, regions=grow)
        if 'error' not in out:
            out['mirrored'] = added['mirrored']
        return out

    def remove_part_region(self, material: str = '', region: int = 0) -> Dict[str, Any]:
        """Возвращает область обратно: её треугольники — снова тем частям, из
        которых её вырезали."""
        def drop(model, obj_mat) -> List[List[int]]:
            made = [list(r) for r in self.preview.part_regions.get(obj_mat) or []]
            if 0 <= int(region) < len(made):
                del made[int(region)]
            return made

        return self._reshape(material, regions=drop)

    def _reshape(self, material: str, plan=None, regions=None) -> Dict[str, Any]:
        """
        Меняет разбиение и переносит на новые части уже покрашенное.

        ``plan(model, obj_mat)`` — новые разрезы по островам, ``regions`` —
        новый список областей; что не передано, то не меняется.

        Перенос идёт ПО ТРЕУГОЛЬНИКАМ: номер части от дробления зависит.
        Каждая новая часть наследует мазки той старой, из которой вышла больше
        всего треугольников.
        """
        from src.services.mesh_parts_service import bundles_of

        found = self._parts_model(material)
        if isinstance(found, dict):
            return found
        model, obj_mat, card = found
        was = model.parts_of(obj_mat)
        owner = {tri: part.index for part in was for tri in part.triangles}
        #: Габарит прежних частей: по нему наклейка остаётся на месте, когда
        #: часть под ней разрезали надвое.
        boxes = {part.index: list(part.uv_bbox) for part in was}
        wanted = plan(model, obj_mat) if plan else None
        areas = regions(model, obj_mat) if regions else None

        with self._lock:
            # Разрезы — СВОИ у каждого материала: номера групп считаются внутри
            # материала (у головы шпиона и у его тела есть своя «группа 1»).
            if wanted is not None:
                self.preview.part_cuts[obj_mat] = {
                    g: [list(b) for b in made] for g, made in bundles_of(wanted).items()}
            if areas is not None:
                if areas:
                    self.preview.part_regions[obj_mat] = areas
                else:
                    self.preview.part_regions.pop(obj_mat, None)
            found = self._parts_model(material)
            if isinstance(found, dict):
                return found
            model, obj_mat, card = found
            # Номера частей общие на геометрию, а мазки лежат по слотам (стиль,
            # команда): переносим их все.
            slots = [k for k in set(self.preview.part_textures) | set(self.preview.part_colors)
                     if part_specs.parse_slot(k)[0] == card]
            for slot in slots:
                self._move_parts(model, obj_mat, slot, owner, boxes)
            self._move_paintkit_layouts(model, obj_mat, owner)
            jobs = [job for _, style, team in map(part_specs.parse_slot, slots)
                    for job in self._plans(model, obj_mat, card, style, team)]
        return self._commit(jobs)

    def _move_paintkit_layouts(self, model: Any, obj_mat: str, owner: Dict[int, int]) -> None:
        """Раскладка War Paint держится за номера частей (``p3``) — переносим
        её так же, по треугольникам. Только у главного материала: War Paint
        раскладывается по нему, у соседнего номера частей свои."""
        from collections import Counter

        if not self.preview.paintkit_layouts:
            return
        main = self._parts_model('')
        if not isinstance(main, tuple) or main[1] != obj_mat:
            return
        heir = {}
        for part in model.parts_of(obj_mat):
            votes = Counter(owner.get(tri) for tri in part.triangles)
            votes.pop(None, None)
            if votes:
                heir[f'p{part.index}'] = f'p{votes.most_common(1)[0][0]}'
        for kit, layout in list(self.preview.paintkit_layouts.items()):
            moved = {k: v for k, v in layout.items() if not k.startswith('p')}
            moved.update({new: layout[old] for new, old in heir.items() if old in layout})
            self.preview.paintkit_layouts[kit] = moved

    def _move_parts(self, model: Any, obj_mat: str, slot: str,
                    owner: Dict[int, int], boxes: Dict[int, list]) -> None:
        """Переносит мазки одного слота на новые части — по треугольникам."""
        images = self.preview.part_textures.get(slot) or {}
        colors = self.preview.part_colors.get(slot) or {}
        if not (images or colors):
            return
        moved_images: Dict[int, Any] = {}
        moved_colors: Dict[int, Any] = {}
        for part in model.parts_of(obj_mat):
            votes = Counter(owner[t] for t in part.triangles if t in owner)
            if not votes:
                continue
            before = votes.most_common(1)[0][0]
            # Картинки и цвет переносятся по отдельности: у части бывает и то,
            # и другое.
            if before in images:
                # Якорь ставим ОДИН раз — при первом разрезе. Дальше он уже
                # описывает исходное место картинки.
                moved_images[part.index] = [
                    {**spec, 'anchor': spec['anchor'] or boxes.get(before)}
                    for spec in images[before]]
            if before in colors:
                moved_colors[part.index] = dict(colors[before])
        self.preview.part_textures[slot] = moved_images
        self.preview.part_colors[slot] = moved_colors

    # ═══════════════════════════════════════════════════════════════════════ #
    # Склейка: задание под замком, расчёт без него
    # ═══════════════════════════════════════════════════════════════════════ #

    def _compose_base(self, card: str, style: Optional[int] = None,
                      team: Optional[str] = None) -> Optional[str]:
        """
        Основа склейки слота: своя текстура человека под мазками, иначе игровая —
        у стиля его собственная (Bloody у гильотины), у команды её кадр.

        Для непокрашенного слота (окно посадки перед первым мазком) своя
        текстура — то, что лежит на нём сейчас.
        """
        t = self.preview.textures
        if style is None:
            style = self.preview.active_style
        if team is None:
            team = t.active_team
        slot = self._slot(card, style, team)
        if slot in self.preview.part_bases:
            own = _existing(self.preview.part_bases[slot])
        else:
            own = self._slot_texture(card, style, team)
        if own:
            return own
        if style:
            game = _existing(t.style_game_tex.get(style, {}).get(card))
            if game:
                return game
        with self._as_team(team):
            return t.game_base(card)

    def _as_team(self, team: str):
        """Временно смотрит на состояние глазами другой команды: `game_base`
        и разрешение текстур читают активную команду."""
        t = self.preview.textures

        @contextlib.contextmanager
        def swap():
            was = t.active_team
            t.active_team = team
            try:
                yield
            finally:
                t.active_team = was
        return swap()

    def _part_layers(self, model: Any, obj_mat: str, slot: str,
                     skip: Optional[tuple] = None,
                     keep: Optional[Callable[[int], bool]] = None) -> List[Any]:
        """Слои склейки из мазков слота. Сперва ЦВЕТ (тонировка игровой
        текстуры), потом картинки поверх него. ``skip`` — (часть, номер
        картинки), которую окно посадки рисует само; ``keep`` — только эти
        треугольники (`_keep_for`)."""
        from src.services.texture_compose_service import Layer

        images = self.preview.part_textures.get(slot) or {}
        colors = self.preview.part_colors.get(slot) or {}
        layers = []
        for part, color in sorted(colors.items()):
            polys = model.polygons(obj_mat, part, keep)
            if polys or keep is None:
                layers.append(Layer(polygons=polys, **color))
        for part, stack in sorted(images.items()):
            polys = model.polygons(obj_mat, part, keep)
            if not polys and keep is not None:
                continue
            # Картинка вписана в габарит ВСЕЙ части, даже если склейка красит
            # только её долю: иначе у части на два материала она бы съехала.
            whole = None
            if keep is not None and len(polys) != len(model.polygons(obj_mat, part)):
                whole = next((tuple(p.uv_bbox) for p in model.parts_of(obj_mat)
                              if p.index == part), None)
            for n, spec in enumerate(stack):
                if skip == (part, n):
                    continue
                layers.append(Layer(
                    polygons=polys,
                    image=spec['path'], fit=spec['fit'],
                    image_angle=spec['angle'], image_scale=spec['scale'],
                    image_scale_y=spec['scale_y'],
                    image_offset=tuple(spec['offset']),
                    image_flip_x=spec['flip_x'], image_flip_y=spec['flip_y'],
                    anchor=tuple(spec['anchor']) if spec['anchor'] else whole,
                    edge=spec['edge'], edge_color=spec['edge_color']))
        return layers

    def _plan(self, model: Any, obj_mat: str, card: str,
              style: Optional[int] = None, team: Optional[str] = None
              ) -> Optional[Dict[str, Any]]:
        """
        ПОД ЗАМКОМ: что пересобрать для слота. Шагает его поколение — всё, что
        считалось для слота раньше, этим обогнано.

        Мазков не осталось — склейке не с чего: слот возвращается к своей
        основе сразу, без расчёта, и задания нет.
        """
        t = self.preview.textures
        if style is None:
            style = self.preview.active_style
        if team is None:
            team = t.active_team
        slot = self._slot(card, style, team)
        self._latest[slot] = next(self._generations)
        p = self.preview
        if not (p.part_textures.get(slot) or p.part_colors.get(slot)):
            p.part_textures.pop(slot, None)
            p.part_colors.pop(slot, None)
            if slot in p.part_bases:
                self._put_slot_texture(card, p.part_bases.pop(slot) or None, style, team)
            return None
        if slot not in p.part_bases:
            # Первый мазок: что лежит на слоте сейчас — своя текстура человека.
            p.part_bases[slot] = self._slot_texture(card, style, team) or ''
        return {'slot': slot, 'gen': self._latest[slot],
                'epoch': p.edits_epoch, 'card': card,
                'style': style, 'team': team, 'mesh': obj_mat,
                'base': self._compose_base(card, style, team),
                'layers': self._part_layers(model, obj_mat, slot,
                                            keep=self._keep_for(model, obj_mat, card, style)),
                'out': os.path.join(self._host._work_dir(),
                                    f"parts_{self._next_compose()}.png")}

    def _plans(self, model: Any, obj_mat: str, card: str,
               style: Optional[int] = None, team: Optional[str] = None,
               only: str = '') -> List[Optional[Dict[str, Any]]]:
        """
        ПОД ЗАМКОМ: задания склейки для слота карточки и для материалов её
        частей (`only` — только для этого материала части, слот исходного не
        трогаем).

        Мазки частей лежат в слоте исходного: номера частей общие на
        геометрию, а часть может уйти в свой материал и вернуться. У материала
        части своя основа — его картинка или игровая текстура исходного, —
        поэтому склейка у него своя, с теми же мазками, и каждая склейка
        красит только треугольники своего материала (`_keep_for`). Стили и
        вариант (австралий) материалы частей не трогают — в сборке у них
        игровые.
        """
        t = self.preview.textures
        if style is None:
            style = self.preview.active_style
        if team is None:
            team = t.active_team
        jobs = [] if only else [self._plan(model, obj_mat, card, style, team)]
        entries = [e for e in self.preview.part_materials.get(obj_mat, [])
                   if e.get('card') == card and (not only or e['name'] == only)]
        if style or not entries:
            return jobs
        slot = self._slot(card, style, team)
        p = self.preview
        painted = p.part_textures.get(slot) or p.part_colors.get(slot)
        for entry in entries:
            layers = (self._part_layers(model, obj_mat, slot, keep=self._keep_for(
                model, obj_mat, entry['name'], 0)) if painted else None)
            jobs.append(self._part_job(entry['name'], team, layers))
        return jobs

    def _part_job(self, name: str, team: str,
                  layers: Optional[List[Any]]) -> Optional[Dict[str, Any]]:
        """ПОД ЗАМКОМ: склейка материала части в слоте команды; без мазков —
        вернуть ему его основу (как `_plan` у обычной карточки)."""
        p = self.preview
        slot = self._slot(name, 0, team)
        self._latest[slot] = next(self._generations)
        if not layers:
            if slot in p.part_bases:
                self._put_slot_texture(name, p.part_bases.pop(slot) or None, 0, team)
            return None
        if slot not in p.part_bases:
            p.part_bases[slot] = self._slot_texture(name, 0, team) or ''
        return {'slot': slot, 'gen': self._latest[slot],
                'epoch': p.edits_epoch, 'card': name,
                'style': 0, 'team': team, 'mesh': name,
                'base': self._compose_base(name, 0, team),
                'layers': layers,
                'out': os.path.join(self._host._work_dir(),
                                    f"parts_{self._next_compose()}.png")}

    def _source_card(self, card: str) -> str:
        """Карточка, в слоте которой лежат мазки: у материала части — его
        исходного, у остальных — она сама."""
        return self.preview.textures.part_cards.get(card, card)

    def _finish(self, jobs: Iterable[Optional[Dict[str, Any]]]) -> bool:
        """
        Считает задания БЕЗ замка и кладёт результаты под ним.

        False — хоть одно задание обогнала более свежая правка: её запрос
        положит свой результат и сам запишет работу.
        """
        from src.services import texture_compose_service

        current = True
        for job in jobs:
            if job is None:
                continue
            result = (texture_compose_service.compose(
                job['base'], job['layers'], job['out'], frames=1)
                if job['base'] else None)
            with self._lock:
                # Обогнано: свежей правкой этого слота, подменой всего
                # состояния (другой предмет, отмена, «забыть») или слот уже не
                # покрашен.
                if (self._latest.get(job['slot']) != job['gen']
                        or self.preview.edits_epoch != job['epoch']
                        or job['slot'] not in self.preview.part_bases):
                    current = False
                    if result:
                        with contextlib.suppress(OSError):
                            os.remove(result)
                    continue
                if not result:
                    continue
                self._compose_files.append(result)
                self._drop_old_composites()
                self._put_slot_texture(job['card'], result, job['style'], job['team'])
            # Вьювер крутит одну анимацию частей — у исходного материала;
            # склейка материала части оборвала бы её (`_anim_seq`).
            if job['card'] not in self.preview.textures.part_cards:
                self._animate_parts(job['card'], job['mesh'], result,
                                    job['base'], job['layers'])
        return current

    def _commit(self, jobs) -> Dict[str, Any]:
        """Досчитать, записать работу шагом истории и отдать вид."""
        if self._finish(jobs):
            self._host._autosave()
        return self._host.view_state()

    def recompose_slots(self, slots: Iterable[str]) -> None:
        """Пересобирает названные слоты — после отмены: снимок вернул мазки, а
        файлы его склеек могли уже уйти с диска."""
        jobs = []
        for slot in sorted(slots):
            card, style, team = part_specs.parse_slot(slot)
            found = self._parts_model(card)
            if isinstance(found, dict):
                continue
            model, obj_mat, _ = found
            source = self._source_card(card)
            with self._lock:
                jobs.extend(self._plans(model, obj_mat, source, style, team,
                                        only=card if source != card else ''))
        self._finish(jobs)

    def _next_compose(self) -> int:
        return next(self._compose_counter)

    def _drop_old_composites(self) -> None:
        """
        ПОД ЗАМКОМ: убирает с диска устаревшие склейки.

        Каждый мазок пишет новый файл: без уборки за день набегало 1090 файлов
        на 248 МБ. Держим последние `_KEEP_COMPOSITES` и всё, что назначено
        хоть какому-то материалу — любой команды, любого стиля оружия и любого
        отложенного стиля шапки.
        """
        live = self._live_texture_paths()
        recent = set(self._compose_files[-self._KEEP_COMPOSITES:])
        keep: List[str] = []
        for path in self._compose_files:
            if path in live or path in recent:
                keep.append(path)
                continue
            with contextlib.suppress(OSError):
                os.remove(path)
        self._compose_files = keep

    def _live_texture_paths(self) -> set:
        """Пути, назначенные сейчас хоть какому-то материалу. Склейка стиля
        лежит в `skin_overrides`, стиля шапки — в его снимке."""
        live: set = set()

        def walk(node) -> None:
            if isinstance(node, str):
                live.add(node)
            elif isinstance(node, dict):
                for value in node.values():
                    walk(value)
            elif isinstance(node, (list, tuple)):
                for value in node:
                    walk(value)

        t = self.preview.textures
        walk(t.textures)
        walk(t.skin_overrides)
        walk(self._host._hat_styles)
        return live

    # ── Анимация частей в 3D ─────────────────────────────────────────────── #

    @staticmethod
    def _parts_animation_on() -> bool:
        from src.config.app_config import AppConfig
        return bool(AppConfig.load_config().get('parts_animation'))

    def _animate_parts(self, card: str, mesh: str, still: str, base: str,
                       layers: List[Any]) -> None:
        """
        Крутит гифку с части в 3D — фоном, после того как мазок уже показан.

        Склейка превью — один кадр; кадры для вьювера рисуются отдельным
        потоком в уменьшенном размере и приезжают событием `parts_animated`.
        Новый мазок обрывает прежний расчёт. Выключено настройкой по умолчанию:
        это секунды работы и сотни мегабайт на видеокарте после каждого мазка.
        """
        from src.services import texture_compose_service

        with self._anim_lock:
            self._anim_seq += 1
            seq = self._anim_seq
            self._anim_last = (card, mesh, still, base, layers)
        if not self._parts_animation_on():
            return
        if not texture_compose_service.is_moving(layers):
            return
        alive = lambda: self._anim_seq == seq   # noqa: E731

        def run() -> None:
            out_dir = os.path.join(self._host._work_dir(), 'anim', str(seq))
            frames, fps = texture_compose_service.export_composite_frames(
                base, layers, out_dir, self._ANIM_PREVIEW_SIZE, alive)
            if not frames or not alive():
                return
            self._drop_old_animations(seq)
            # Меш зовётся по материалу из OBJ, а не по ключу карточки.
            self._host._put('parts_animated', material=card, mesh=mesh,
                            still=still, frames=frames, fps=fps)

        threading.Thread(target=run, daemon=True, name=f'parts-anim-{seq}').start()

    def _drop_old_animations(self, seq: int) -> None:
        """Кадры прежних анимаций: держим одну предыдущую — браузер может ещё
        грузить её, — остальные с диска долой (60 файлов на мазок)."""
        import shutil

        root = os.path.join(self._host._work_dir(), 'anim')
        try:
            names = os.listdir(root)
        except OSError:
            return
        for name in names:
            if name.isdigit() and int(name) < seq - 1:
                shutil.rmtree(os.path.join(root, name), ignore_errors=True)

    def refresh_parts_animation(self) -> None:
        """Настройку переключили: включили — крутим то, что на модели сейчас,
        выключили — обрываем расчёт, а кадры со сцены снимет сама страница."""
        with self._anim_lock:
            last = self._anim_last
            self._anim_seq += 1
        if not (last and self._parts_animation_on()):
            return
        # Склейка могла смениться без мазка: другой предмет, возврат работы.
        card, _, still = last[:3]
        if self.preview.textures.uploaded_for_mat(card) != still:
            return
        self._animate_parts(*last)

    # ── Анимация частей для сборки ───────────────────────────────────────── #

    def _card_of(self, path: str) -> Optional[Tuple[str, int, str]]:
        """(карточка, стиль, команда), где лежит этот файл."""
        from src.shared.constants import Team

        t = self.preview.textures
        for team, by_mat in t.textures.items():
            for mat, p in (by_mat or {}).items():
                if p == path:
                    return mat, 0, (team if self._per_team(mat) else Team.RED)
        for style, by_mat in t.skin_overrides.items():
            for mat, p in (by_mat or {}).items():
                if p == path:
                    return mat, int(style), Team.RED
        return None

    def bake_plan(self, paths: Iterable[Optional[str]]) -> Dict[str, Any]:
        """
        Какие склейки сборке надо испечь заново, со всеми кадрами.

        Превью держит от гифки на части один кадр, а в игру должна уехать вся
        анимация. Возвращает {путь склейки превью: (основа, слои, путь полной
        склейки)} и запоминает подмену путей (`baked_path`); материалы без
        анимации сюда не попадают — их склейка и так полная.
        """
        with self._lock:
            # Под замком: `_compose_base` на время смотрит глазами другой
            # команды (`_as_team`), а склейки теперь кладутся из других
            # потоков — и `set_team` посреди этого окна откатился бы.
            return self._bake_plan(paths)

    def _bake_plan(self, paths: Iterable[Optional[str]]) -> Dict[str, Any]:
        from src.services import texture_compose_service

        plan: Dict[str, Any] = {}
        for path in paths:
            if not path or path in plan:
                continue
            where = self._card_of(path)
            if not where:
                continue
            card, style, team = where
            slot = self._slot(card, style, team)
            if slot not in self.preview.part_bases:
                continue                         # не склейка — своя текстура
            found = self._parts_model(card)
            if isinstance(found, dict):
                logger.warning(f"анимация частей: {card} — {found['error']}")
                continue
            model, obj_mat, _ = found
            # У материала части мазки — в слоте исходного (см. `_plans`).
            layers = self._part_layers(
                model, obj_mat, self._slot(self._source_card(card), style, team),
                keep=self._keep_for(model, obj_mat, card, style))
            if not texture_compose_service.is_moving(layers):
                continue
            base = self._compose_base(card, style, team)
            full = os.path.join(self._host._work_dir(),
                                f"parts_{self._next_compose()}_full.png")
            plan[path] = (base, layers, full)
        self._baked = {src: full for src, (_, _, full) in plan.items()}
        return plan

    def baked_path(self, path: Optional[str]) -> Optional[str]:
        """Путь, который пойдёт в сборку: полная склейка вместо превью."""
        return self._baked.get(path, path) if path else path

    def bake(self, plan: Dict[str, Any], report) -> None:
        """Печёт полные склейки по плану. Зовётся из воркера сборки."""
        from src.services import texture_compose_service

        for n, (base, layers, full) in enumerate(plan.values(), 1):
            report(-1, f"Анимация частей {n}/{len(plan)}")
            if not texture_compose_service.compose(base, layers, full):
                raise RuntimeError(f"Не удалось собрать анимацию частей: {full}")

    def drop_baked(self) -> None:
        """Полные склейки нужны только сборке: у текстуры 2048 шестьдесят
        кадров весят сотни мегабайт, держать их до выхода незачем."""
        for full in self._baked.values():
            with contextlib.suppress(OSError):
                os.remove(full)
        self._baked = {}
