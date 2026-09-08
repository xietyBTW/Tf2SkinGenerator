"""
Состояние сеанса превью и правила переходов между моделями (без Qt).

Зачем отдельно от панели. Переходы «кастомная модель → игровая», «оружие →
другое оружие», «выход из скайбокса» раньше жили прямо в теле
``_start_3d_worker`` вперемешку с ``setVisible`` и ``show_loading``. Из-за
этого каждое исправление «забыли сбросить флаг» приходилось повторять в
нескольких точках, а проверить правило можно было только через живой виджет.

Здесь — только состояние и его сбросы. Виджеты панель гасит сама: разделение
проходит ровно по границе «что помним» / «что рисуем».

PreviewSession владеет двумя моделями, которые уже были выделены раньше:
``textures`` (PreviewTextureState — что загружено и что показывать) и ``mode``
(PreviewState — взаимоисключающий режим превью). Остальные поля — то, что
панель держала россыпью атрибутов.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.domain.preview.mode import PreviewState
from src.domain.preview.texture_state import SINGLE_TEX_KEY, PreviewTextureState
from src.shared.constants import Team

#: Поля работы, ради которых её стоит хранить и предлагать вернуть.
#:
#: Список НЕ совпадает с содержимым `user_edits()`, и это намеренно. Туда
#: пишется всё состояние правки целиком, а работой предмет делает только то,
#: что человек в нём изменил: положенная текстура, покрашенные части, своя
#: геометрия. Остальное — спутники, и по одному их наличию говорить «у вас
#: есть несохранённые правки» нельзя:
#:
#:   • `texture_overrides` — настройки СБОРКИ материала (размер, формат,
#:     флаги VTF). Текстура от них не меняется ни на пиксель, а предмет с
#:     одной такой записью всю жизнь предлагал «вернуть правки», которых
#:     человек не делал. Записанными они остаются — просто вместе с работой,
#:     а не вместо неё;
#:   • `part_tint`, `skin_chosen`, `custom_keep_materials` — уточняют, как
#:     показать уже выбранное, и сами по себе не меняют ничего.
EDIT_FIELDS = (
    'textures', 'skin_overrides', 'australium_user_tex', 'force_team',
    'texture_maps', 'part_textures', 'part_colors',
    'custom_smd_path', 'custom_qc_text',
)


def _filled(value: Any) -> bool:
    """Есть ли внутри хоть что-нибудь. Пустая обёртка не считается.

    `{'red': {}, 'blu': {}}` — это не правка: словари команд и материалов
    заводятся сами и пустыми доезжают до записи на диск.
    """
    if isinstance(value, dict):
        return any(_filled(inner) for inner in value.values())
    return bool(value)


def has_real_edits(edits: Optional[Dict[str, object]]) -> bool:
    """Есть ли в работе то, ради чего её стоит хранить и возвращать.

    Одно правило на всех: и на состояние сеанса, и на файл с диска. Пока их
    было два — сеанс смотрел на поля, а диск на наличие `edits.json`, — они
    расходились, и предмет предлагал вернуть правки, которых в файле нет.
    """
    return any(_filled((edits or {}).get(name)) for name in EDIT_FIELDS)


@dataclass
class PreviewSession:
    """Всё, что превью помнит о текущей модели, кроме самих виджетов."""

    # ── Выделенные ранее модели ───────────────────────────────────────────── #
    textures: PreviewTextureState = field(default_factory=PreviewTextureState)
    mode: PreviewState = field(default_factory=PreviewState)

    # ── Кастомная (загруженная пользователем) модель ──────────────────────── #
    #: Путь к SMD, который пользователь подставил вместо игровой геометрии.
    custom_smd_path: Optional[str] = None
    #: OBJ подменённой модели — к нему возвращаются из вида от первого лица.
    custom_obj_path: Optional[str] = None
    #: True — модель «готова», её материалы сохраняются как есть (многотекстурная);
    #: False — заменяется только геометрия, материал берётся игровой.
    custom_keep_materials: bool = False
    #: Отредактированный пользователем QC. None = авто-QC.
    custom_qc_text: Optional[str] = None
    #: Точные имена материалов модели из SMD — для наложения текстур мода на
    #: правильные меши в режиме custom-VPK.
    custom_model_materials: List[str] = field(default_factory=list)
    #: Какое ИГРОВОЕ оружие заменяет открытый VPK-мод и чем: ключ и reference
    #: SMD из мода. Определяется по путям внутри VPK; пусто — мод не про
    #: оружие (шапка, эффект) или опознать не вышло.
    custom_vpk_weapon: Optional[str] = None
    custom_vpk_smd: Optional[str] = None
    #: Режим загруженного custom-VPK мода: карточки строятся из VTF мода и
    #: не должны перетираться обычной фильтрацией материалов модели.
    custom_vpk_mode: bool = False

    # ── «Прочее»: служебные материалы, скрытые блэклистом ─────────────────── #
    misc_materials: List[str] = field(default_factory=list)
    misc_mode: bool = False
    #: Нормальный набор карточек, чтобы вернуться из «Прочее».
    cards_before_misc: List[str] = field(default_factory=list)

    # ── Пер-текстурные файловые карты ─────────────────────────────────────── #
    #: {материал: {map_id: спецификация}} — detail / самосвечение / phong и т.п.
    #: Уходят в сборку как есть: VTF по ним генерит vpk_texture_builder.
    texture_maps: Dict[str, dict] = field(default_factory=dict)
    #: {материал: {size, format, flags, options}} — СВОИ настройки сборки.
    #: Разреженно: есть запись ⟺ материал собирается не как все остальные.
    texture_overrides: Dict[str, dict] = field(default_factory=dict)
    #: {материал: {номер части: картинка}} — картинки, положенные на ОТДЕЛЬНЫЕ
    #: куски модели. Сама текстура материала из них склеивается и лежит, как
    #: обычная пользовательская, в textures: дальше по конвейеру про части
    #: никто не знает.
    #: Запись бывает строкой (путь) ИЛИ словарём с настройкой посадки: как
    #: положить картинку на место части — вписать, повернуть, сдвинуть. Старые
    #: работы писались строкой, и ломать их из-за новой возможности незачем.
    part_textures: Dict[str, Dict[int, Any]] = field(default_factory=dict)
    #: {материал: {номер части: '#rrggbb'}} — тонировка отдельных кусков. Живёт
    #: рядом с картинками: у части либо своя картинка, либо цвет.
    part_colors: Dict[str, Dict[int, str]] = field(default_factory=dict)
    #: Сила тонировки, общая на предмет: 1.0 — в цвет, 0.3 — лёгкий оттенок.
    part_tint: float = 1.0
    #: Окантовка частей: ширина полосы по краю в долях стороны текстуры и её
    #: цвет. Общая на предмет, как и сила: обводят обычно всю работу разом, а
    #: не одну деталь. 0 — окантовки нет.
    part_edge: float = 0.0
    part_edge_color: str = '#141210'
    #: Окантовка частей: ширина полосы по краю в долях стороны текстуры и её
    #: цвет. Общая на предмет, как и сила: обводят обычно всю работу разом, а
    #: не одну деталь. 0 — окантовки нет.
    part_edge: float = 0.0
    part_edge_color: str = '#141210'
    #: {номер группы: список НАБОРОВ отрезанных островов развёртки}. Поимённо,
    #: а не счётчиком: счётчик резал острова в своём порядке, от крупного, и до
    #: мизинца можно было добраться только разрезав перед ним всё остальное.
    #: Набор, а не один остров: развёртка режет вещи не так, как их видит
    #: человек — палец у неё нередко разложен на верх и низ, и свести их в одну
    #: часть должно быть можно.
    #: Группа — куски, делящие развёртку (левая и правая рука шпиона): в игре
    #: у них общие пиксели, и режутся они вместе. Свойство ПРЕДМЕТА, а не
    #: кисти: номера частей от разрезов зависят, и хранить их надо там же, где
    #: саму покраску.
    part_cuts: Dict[int, List[int]] = field(default_factory=dict)

    # ── Вариантные стили ──────────────────────────────────────────────────── #
    #: Материалы, ЯВНО добавленные пользователем в стиль через «+»: {skin: {mat}}.
    #: Скин 0 здесь не участвует.
    skin_chosen: Dict[int, set] = field(default_factory=dict)

    # ── Чужая геометрия в кадре ───────────────────────────────────────────── #
    #: {материал: png} для мешей, которые в кадре есть, а к предмету не
    #: относятся: руки класса в виде от первого лица. Карточек у них не
    #: строится и в сборку они не идут, но без текстур руки в кадре серые.
    #: Подкладываются ПОД текстуры предмета, чтобы правка оружия их перебивала.
    scene_extra_textures: Dict[str, str] = field(default_factory=dict)
    #: Материалы ТОГО ЖЕ кадра, которые предмету всё-таки принадлежат — их
    #: называет воркер сцены (editable_materials). Нужны, чтобы положить
    #: текстуру предмета на настоящие имена мешей: у одноматериальной модели
    #: она хранится под служебным ключом, а меша с таким именем не бывает.
    scene_item_materials: List[str] = field(default_factory=list)

    # ── Что реально показано в 3D ─────────────────────────────────────────── #
    #: {material: path} — чтобы при смене стиля перезагружать в webview только
    #: изменившиеся текстуры.
    applied_3d_tex: Dict[str, str] = field(default_factory=dict)

    # ── Командные кадры ───────────────────────────────────────────────────── #
    team_framerate: float = 0.0
    #: У модели есть BLU-скин, но в стоке он не отличается от RED (та же
    #: текстура и та же краска в VMT) — влияет только на подпись кнопки.
    blu_matches_red: bool = False

    # ── Что сейчас загружено в 3D ─────────────────────────────────────────── #
    #: (режим, obj_path, texture_path) показанной модели; None — ничего не грузили.
    #: Нужно мини-памяти для мгновенного возврата к предыдущему оружию.
    current_object: Optional[tuple] = None
    #: Пользователь перетащил текстуру на КОНКРЕТНЫЙ меш в 3D. Сбрасывается при
    #: смене изображения и при загрузке новой модели.
    per_mesh_active: bool = False
    per_mesh_base_image: Optional[str] = None

    # ── Какой предмет сейчас редактируется ────────────────────────────────── #
    #: Ключ и режим текущего предмета. По ним понимаем, что предмет СМЕНИЛСЯ, и
    #: пора забыть пользовательские текстуры: перезагрузка того же предмета их
    #: терять не должна.
    weapon_key: str = ''
    weapon_mode: str = ''

    # ── Отложенные действия ───────────────────────────────────────────────── #
    #: Обновить 2D после загрузки модели (смена стиля без своих правок — иначе
    #: в 2D остаётся пустое или старое окно, а текстура только в 3D).
    pending_2d_refresh: bool = False

    # ═══════════════════════════════════════════════════════════════════════ #
    # Предикаты
    # ═══════════════════════════════════════════════════════════════════════ #

    @property
    def has_custom_model(self) -> bool:
        """True, если сейчас показывается что-то пользовательское, а не сток.

        Проверяются ЧЕТЫРЕ признака, а не один: пользователь мог подставить
        геометрию (custom_smd_path), оставить материалы готовой модели
        (custom_keep_materials), получить определённые стили оригинала
        (skin_info) или просто находиться в кастомном режиме. Любого из них
        достаточно, чтобы при возврате к игровой модели пришлось чистить
        карточки — иначе идентичность материалов кастома протекает в сток.
        """
        return bool(
            self.custom_smd_path
            or self.custom_keep_materials
            or self.textures.skin_info
            or self.mode.is_custom
        )

    def has_team_variant(self, is_hands: bool = False) -> bool:
        """
        Есть ли у модели РЕАЛЬНЫЙ командный вариант — от этого зависит, стоит
        ли вообще показывать переключатель RED/BLU.

        У рук правило строже: командным считается только материал, у которого
        синее имя ОТЛИЧАЕТСЯ от красного (engineer_red → engineer_blue). Руки
        скаута, шпиона и пулемётчика нейтральны, и переключатель у них был бы
        ложным — он ничего не менял бы.

        У остального достаточно любого признака: BLU одним кадром, покарточная
        карта BLU или маппинг имён.
        """
        t = self.textures
        if is_hands:
            return bool(t.blu_name_map) and any(
                str(blu).lower() != str(red).lower()
                for red, blu in t.blu_name_map.items())
        return bool(t.blu_frames or t.vpk_blu_tex_map or t.blu_name_map)

    def card_materials(self) -> List[str]:
        """
        Имена карточек прямо сейчас: обычные материалы, «Прочее» или стиль.

        Списки НЕ подменяют друг друга в ``material_names`` (как это делала
        панель): главный материал, ключ хранения и разрешение командных кадров
        завязаны на первый элемент, и подмена уводила их на служебный материал.
        Здесь режим просмотра выбирает список, а состав модели не меняется.

        У вариантного стиля карточки показывают ТОЛЬКО те материалы, которые
        человек сам в него добавил: стиль переопределяет базу выборочно, а
        остальное наследует. Так же ведёт себя панель приложения
        (``_rebuild_cards_for_skin``).
        """
        if self.misc_mode and self.misc_materials:
            return list(self.misc_materials)
        if self.active_style:
            chosen = self.skin_chosen.get(self.active_style) or set()
            return [m for m in self.textures.material_names if m in chosen]
        return list(self.textures.material_names)

    @property
    def active_style(self) -> int:
        """Активный вариантный стиль (0 — базовый, у него правил нет)."""
        t = self.textures
        return t.active_skin if (t.skin_info and t.active_skin) else 0

    def style_candidates(self) -> List[str]:
        """Материалы, которые ещё можно добавить в активный стиль."""
        if not self.active_style:
            return []
        chosen = self.skin_chosen.get(self.active_style) or set()
        return [m for m in self.textures.material_names if m not in chosen]

    def add_to_style(self, material: str) -> bool:
        """
        Добавляет материал в активный стиль — пустой карточкой под свою текстуру.

        Только базовый материал модели: стиль переопределяет ЕГО, и имя должно
        совпадать, иначе в $texturegroup уедет строка, которой нет у модели.
        """
        if not self.active_style or material not in self.textures.material_names:
            return False
        self.skin_chosen.setdefault(self.active_style, set()).add(material)
        return True

    def drop_from_style(self, material: str) -> bool:
        """Убирает материал из стиля вместе с его текстурой — стиль вернёт базу."""
        style = self.active_style
        if not style:
            return False
        chosen = self.skin_chosen.get(style) or set()
        if material not in chosen:
            return False
        chosen.discard(material)
        (self.textures.skin_overrides.get(style) or {}).pop(material, None)
        return True

    def visible_textures(self) -> Dict[str, str]:
        """
        Что показывать сейчас: {материал: путь} при текущей команде и стиле.

        Разрешение целиком в PreviewTextureState — здесь только обход
        материалов модели. Вариант (Australium) перекрывает главный материал:
        он показывается вместо него, а не рядом.
        """
        t = self.textures
        out: Dict[str, str] = {}
        for mat in self.card_materials():
            path = t.resolve_card(mat)
            if path:
                out[mat] = path
        return self._with_variant(out)

    def _with_variant(self, textures: Dict[str, str]) -> Dict[str, str]:
        """
        Накладывает активный вариант (Australium) на главный материал.

        Общее для 2D и 3D: раньше вариант применялся только к карточкам, и
        включённый австралий менял картинку в альбоме, а модель оставалась
        обычной — расхождение, которое видно сразу и выглядит как поломка.
        """
        variant = self.textures.variant_display_texture()
        if not variant:
            return textures
        main = self.textures.stable_main()
        if main:
            textures[main] = variant
        return textures

    def scene_textures(self) -> Dict[str, str]:
        """
        Что класть на меши в 3D: ВСЕ материалы модели, а не только карточки.

        Карточки отфильтрованы (глаза, зубы, sheen-оверлеи не редактируются),
        но мешу текстура нужна всё равно — иначе служебная часть модели
        остаётся серой. Правки пользователя при этом видны: путь для каждого
        материала разрешает то же состояние.
        """
        t = self.textures
        out: Dict[str, str] = {}

        # Мод из VPK: карточки названы по VTF мода, а красить надо меши модели.
        # Связь между ними — только имя без учёта регистра (resolve_mesh).
        if self.custom_vpk_mode and self.custom_model_materials:
            for mat in self.custom_model_materials:
                path = t.resolve_mesh(mat)
                if path:
                    out[mat] = path
            return {**self.scene_extra_textures, **out}

        # Вариантный стиль показывает СВОЁ поверх базы: материал без
        # переопределения наследует базовую текстуру, а не остаётся пустым.
        # Иначе выбор стиля раздевал модель догола (и вернуться было нечем).
        style = self.active_style
        overrides = t.skin_overrides.get(style, {}) if style else {}

        for mat in list(t.material_names) + list(self.misc_materials):
            if mat in out:
                continue
            path = overrides.get(mat) if style else None
            if not path:
                path = t.resolve_base(mat) if style else t.resolve_card(mat)
            if path:
                out[mat] = path
        return {**self.scene_extra_textures,
                **self._name_for_scene(self._with_variant(out))}

    def card_mesh(self) -> List[str]:
        """
        Меши, которые носят ВЫБРАННУЮ карточку — если карточек больше, чем мешей.

        Маски маскировки шпиона: девять текстур на одну голову. Обычное
        правило «карточка = материал» здесь не работает, и модель показывала
        бы одну и ту же маску, какую бы человек ни листал.

        Какая карточка выбрана, знает только альбом — положение прокрутки в
        Python не живёт. Поэтому здесь называются МЕШИ, а надевает на них
        текстуру страница (album.js → wearCard).
        """
        from src.data.item_kinds import kind_of

        mode = (self.current_object or ('', '', ''))[0]
        return list(self.scene_item_materials) if kind_of(mode).is_spy_mask else []

    def _name_for_scene(self, out: Dict[str, str]) -> Dict[str, str]:
        """
        Переводит служебный ключ одноматериальной модели в имена мешей сцены.

        ``SINGLE_TEX_KEY`` — ключ ХРАНЕНИЯ, а не имя меша: у модели с одним
        материалом его настоящее имя превью не знает, и вьюверу такую текстуру
        кладут глобально. Но в сцене вида от первого лица мешей несколько
        (оружие и руки класса), глобально её класть нельзя — а под служебным
        именем вьювер меш не находит и оставляет оружие СТОКОВЫМ. Имена
        приходят от воркера сцены, поэтому здесь они уже есть.
        """
        if not self.scene_item_materials or SINGLE_TEX_KEY not in out:
            return out
        out = dict(out)
        own = out.pop(SINGLE_TEX_KEY)
        for mat in self.scene_item_materials:
            out[mat] = own
        return out

    # ═══════════════════════════════════════════════════════════════════════ #
    # «Прочее» и «сделать командным»
    # ═══════════════════════════════════════════════════════════════════════ #

    def toggle_misc(self, on: Optional[bool] = None) -> bool:
        """
        Переключает просмотр служебных материалов.

        Активный вариант (Australium) при этом гасится — «Прочее» показывает
        обычные текстуры, и оставленный вариант перекрывал бы главный материал
        поверх служебных карточек.

        Returns:
            Включён ли режим после вызова.
        """
        if not self.misc_materials:
            self.misc_mode = False
            return False
        self.misc_mode = (not self.misc_mode) if on is None else bool(on)
        self.textures.australium_active = False
        return self.misc_mode

    def can_force_team(self, weapon_key: Optional[str] = None,
                       mode: Optional[str] = None) -> bool:
        """
        Стоит ли ПРЕДЛАГАТЬ «сделать командным» (синтез BLU-строки в сборке).

        Условия те же, что держала панель в ``_is_force_team_eligible`` и
        ``_update_team_btn_visibility``: предложение имеет смысл, только пока
        нативного командного варианта нет, режим ещё не включён и вариант
        (Australium) не занял переключатель.

        Ключ и режим можно передать явно — панель хранит их у себя и в сессию
        не пишет.
        """
        from src.data.pickups import PICKUP_MODE_PREFIX
        from src.data.player_characters import PLAYER_BODY_MODE_KEYS, SPY_MASK_MODE_KEY
        from src.data.player_hands import HAND_MODE_KEYS
        from src.data.weapons import (
            MATERIAL_ONLY_WEAPON_KEYS, NO_BLU_WEAPON_KEYS, SPECIAL_MODES,
        )

        key = self.weapon_key if weapon_key is None else weapon_key
        mode = (self.weapon_mode if mode is None else mode) or ''

        # '\x00' — sentinel панели «модель ещё не грузили».
        if not mode or not key or key == '\x00':
            return False
        if mode in ('hat', 'custom') or mode in HAND_MODE_KEYS:
            return False
        if mode in PLAYER_BODY_MODE_KEYS or mode == SPY_MASK_MODE_KEY:
            return False
        # Аптечки и патроны нейтральны: командного варианта у них нет и
        # синтезировать его не из чего.
        if mode.startswith(PICKUP_MODE_PREFIX) or mode in set(SPECIAL_MODES):
            return False
        # Синтез живёт в $texturegroup СВОЕЙ модели. У предметов, чью модель мод
        # не содержит, и у тех, чью BLU-строку сборка выкидывает, кнопка обещала
        # бы то, чего сборка не сделает.
        if key in NO_BLU_WEAPON_KEYS or key in MATERIAL_ONLY_WEAPON_KEYS:
            return False

        t = self.textures
        # is_hands=False: руки отсеяны выше, до сюда они не доходят.
        return not (t.force_team or t.australium_frame
                    or self.has_team_variant(False))

    def enable_force_team(self) -> None:
        """Включает «сделать командным»: показываются RED/BLU, активна RED."""
        self.textures.force_team = True
        self.textures.active_team = Team.RED

    # ═══════════════════════════════════════════════════════════════════════ #
    # Правки человека (то, что нельзя восстановить пересчётом)
    # ═══════════════════════════════════════════════════════════════════════ #
    #
    # Граница проходит по одному признаку: восстановимо ли это заново. Имена
    # материалов, игровые оригиналы, кадры команд и стили модель отдаёт сама
    # при каждой загрузке — их хранить незачем и вредно (замёрзнут пути во
    # временные папки). А положенная текстура, своя геометрия и правленый QC
    # не берутся ниоткуда: их или сохранили, или потеряли.
    #
    # Поэтому это НЕ snapshot(): тот смешивает и то и другое и годится только
    # для мгновенного возврата внутри сеанса.

    def user_edits(self) -> Dict[str, object]:
        """Всё, что сделал человек, — в простых значениях (готово к записи)."""
        t = self.textures
        return {
            'textures': {team: dict(paths) for team, paths in t.textures.items()},
            # Ключи стилей — числа; в JSON они станут строками, поэтому
            # приводим сразу здесь, чтобы туда и обратно читалось одинаково.
            'skin_overrides': {str(skin): dict(paths)
                               for skin, paths in t.skin_overrides.items()},
            'skin_chosen': {str(skin): sorted(mats)
                            for skin, mats in self.skin_chosen.items()},
            'australium_user_tex': t.australium_user_tex,
            'force_team': bool(t.force_team),
            'texture_maps': {mat: dict(maps)
                             for mat, maps in self.texture_maps.items()},
            'texture_overrides': {mat: dict(settings)
                                  for mat, settings in self.texture_overrides.items()},
            # Номера частей — числа; в JSON они станут строками, поэтому
            # приводим сразу здесь.
            'part_textures': {mat: {str(part): path for part, path in items.items()}
                              for mat, items in self.part_textures.items()},
            'part_colors': {mat: {str(part): color for part, color in items.items()}
                            for mat, items in self.part_colors.items()},
            'part_tint': float(self.part_tint),
            'custom_smd_path': self.custom_smd_path,
            'custom_keep_materials': bool(self.custom_keep_materials),
            'custom_qc_text': self.custom_qc_text,
        }

    def has_user_edits(self) -> bool:
        """Есть ли что сохранять. Пустую работу на диск не пишем."""
        return has_real_edits(self.user_edits())

    def apply_user_edits(self, edits: Optional[Dict[str, object]]) -> None:
        """
        Возвращает правки в сеанс.

        Молча пропускает то, чего не понимает: файл работы мог быть записан
        другой версией, и падать из-за лишнего ключа он не должен.
        """
        if not edits:
            return
        t = self.textures

        for team, paths in (edits.get('textures') or {}).items():
            t.textures.setdefault(team, {}).update(dict(paths or {}))
        for skin, paths in (edits.get('skin_overrides') or {}).items():
            t.skin_overrides.setdefault(int(skin), {}).update(dict(paths or {}))
        for skin, mats in (edits.get('skin_chosen') or {}).items():
            self.skin_chosen.setdefault(int(skin), set()).update(mats or [])

        t.australium_user_tex = edits.get('australium_user_tex') or None
        t.force_team = bool(edits.get('force_team'))
        self.texture_maps = {mat: dict(maps) for mat, maps
                             in (edits.get('texture_maps') or {}).items()}
        self.texture_overrides = {mat: dict(settings) for mat, settings
                                  in (edits.get('texture_overrides') or {}).items()}
        self.part_textures = {
            mat: {int(part): path for part, path in (items or {}).items()}
            for mat, items in (edits.get('part_textures') or {}).items()}
        self.part_colors = {
            mat: {int(part): color for part, color in (items or {}).items()}
            for mat, items in (edits.get('part_colors') or {}).items()}
        self.part_tint = float(edits.get('part_tint') or 1.0)
        self.custom_smd_path = edits.get('custom_smd_path') or None
        self.custom_keep_materials = bool(edits.get('custom_keep_materials'))
        self.custom_qc_text = edits.get('custom_qc_text') or None

    def forget_user_edits(self) -> None:
        """Сброс правок предмета — «начать с чистого» без смены предмета."""
        self.textures.textures = {Team.RED: {}, Team.BLU: {}}
        self.textures.skin_overrides = {}
        self.textures.australium_user_tex = None
        self.textures.force_team = False
        self.skin_chosen = {}
        self.texture_maps = {}
        self.texture_overrides = {}
        self.part_textures = {}
        self.part_colors = {}
        self.part_cuts = {}
        self.part_edge = 0.0
        self.reset_custom_model()
        self.custom_qc_text = None

    # ═══════════════════════════════════════════════════════════════════════ #
    # Частичные сбросы (у каждого есть своя половина в виджетах панели)
    # ═══════════════════════════════════════════════════════════════════════ #

    def reset_skins(self) -> None:
        """Забывает вариантные стили: смена оружия или выход из кастома."""
        self.textures.reset_skins()
        self.skin_chosen = {}

    def reset_custom_vpk(self) -> None:
        """Забывает, что заменял прошлый мод."""
        self.custom_vpk_weapon = None
        self.custom_vpk_smd = None

    def reset_custom_model(self) -> None:
        """Забывает подставленную пользователем геометрию."""
        self.custom_smd_path = None
        self.custom_obj_path = None
        self.custom_keep_materials = False

    def reset_misc(self) -> None:
        """Забывает набор «Прочее» — его пересоберёт приход материалов модели.

        Вместе с ним сбрасывается стабильное имя главного материала: в режиме
        «Прочее» material_names временно подменяется служебными, и оставшееся
        от прошлой модели имя привязало бы команду и вариант к чужой карточке.
        """
        self.misc_materials = []
        self.misc_mode = False
        self.textures.main_material = None
        # Имена материалов принадлежат конкретной модели: пережив переход, они
        # заставляли разрешать текстуры для чужих материалов.
        self.textures.material_names = []

    def reset_team_frames(self) -> None:
        """Забывает командные кадры, вариант и режим мода из VPK."""
        self.custom_vpk_mode = False
        # webview перезагружается — что было наложено, больше не актуально
        self.applied_3d_tex = {}
        self.team_framerate = 0.0
        self.textures.reset_team_data()
        self.textures.reset_australium()
        self.blu_matches_red = False
        # «Сделать командным» покажется снова, когда модель загрузится
        self.textures.force_team = False

    # ═══════════════════════════════════════════════════════════════════════ #
    # Переходы
    # ═══════════════════════════════════════════════════════════════════════ #

    def begin_item(self, weapon_key: str, mode: str) -> bool:
        """
        Переход к ДРУГОМУ предмету: забывает всё пользовательское.

        Повторяет ``PreviewPanel._begin_new_weapon``: текстуры, стили, грани
        скайбокса и пер-текстурные настройки относятся к конкретному предмету.
        Оставить их — значит перенести чужой скин на новое оружие; именно так
        текстура одной модели оказывалась на всех подряд.

        Перезагрузка ТОГО ЖЕ предмета ничего не сбрасывает: человек мог уже
        положить текстуры и просто обновляет превью.

        Returns:
            True, если предмет действительно сменился.
        """
        if weapon_key == self.weapon_key and mode == self.weapon_mode:
            return False

        self.weapon_key = weapon_key
        self.weapon_mode = mode

        t = self.textures
        t.textures = {Team.RED: {}, Team.BLU: {}}
        t.material_names = []
        t.main_material = None
        t.reset_skybox()
        self.reset_skins()
        self.reset_custom_model()
        # Карты и настройки привязаны к именам материалов ЭТОГО предмета —
        # у следующего они назвались бы чужими и ушли бы в сборку вслепую.
        self.texture_maps = {}
        self.texture_overrides = {}
        # Номера частей — тем более: у другой модели под номером 3 совсем
        # другой кусок.
        self.part_textures = {}
        self.part_colors = {}
        self.part_cuts = {}
        self.part_edge = 0.0
        self.custom_qc_text = None
        self.per_mesh_active = False
        self.per_mesh_base_image = None
        self.current_object = None
        self.scene_extra_textures = {}
        self.scene_item_materials = []
        return True

    def begin_game_model(self) -> bool:
        """
        Переход к ОБЫЧНОЙ игровой модели: чистит всё, что осталось от прошлой.

        Порядок важен только в одном месте: признак «уходим именно с кастома»
        снимается ДО сбросов, иначе он всегда получался False и карточки
        кастомной модели протекали в игровую.

        Returns:
            Был ли предыдущий показ кастомным — панели это нужно, чтобы решить,
            сбрасывать ли слоты материалов.
        """
        was_custom = self.has_custom_model

        self.reset_skins()
        self.reset_custom_model()
        # Чужой мод остался позади вместе со своим оружием: иначе вид от
        # первого лица показывал бы предмет прошлого мода.
        self.reset_custom_vpk()
        self.reset_team_frames()
        self.reset_misc()
        # Режим (mode) здесь НЕ трогаем: из кастомного режима выходит
        # set_custom_model_mode, а сюда приходят и обычные смены оружия.
        # Флаг ставит trigger_pending_load при смене стиля шапки; новая загрузка
        # модели начинает с чистого листа.
        self.pending_2d_refresh = False

        return was_custom
