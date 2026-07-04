"""
Модель состояния текстур 2D/3D-превью (чистый Python, без Qt — юнит-тестируется).

Зачем: раньше «что загружено и что показывать» жило россыпью полей виджета
(_textures / _skin_overrides / _vpk_*_tex_map / _blu_frames / австралий-слоты)
с ~50 точками прямого доступа, а правила маршрутизации (нейтральная текстура →
обе команды, вариантный стиль → skin_overrides, приоритеты разрешения) были
размазаны по обработчикам. Отсюда рассинхроны 2D↔3D.

Здесь — ЕДИНЫЙ источник правды и все правила в одном месте:

  • set_texture()          — куда пишется загруженная пользователем текстура;
  • resolve_card()/resolve_base() — что показывает карточка/2D при текущей
    команде/стиле (пользовательская → другая команда для нейтральных →
    VPK-оригинал → командный кадр);
  • uploaded_for_mat()/uploaded_slot_paths()/blu_uploaded_paths() — что уходит
    в сборку;
  • variant_display_texture() — что показывает активный вариант (Australium).

Виджет (preview_panel) держит экземпляр PreviewTextureState и делегирует сюда
и хранение, и разрешение; Qt-поля виджета — только отображение.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.shared.constants import Team

# Sentinel-ключ главной текстуры, когда у модели нет именованных материалов
# (одноматериальный случай). НЕ имя материала и НЕ должен попадать в сборку.
SINGLE_TEX_KEY = '__single__'


def team_priority(active_team: str) -> List[str]:
    """Порядок проверки команд: активная первой (сборка может начаться с BLU)."""
    if active_team == Team.BLU:
        return [Team.BLU, Team.RED]
    return [Team.RED, Team.BLU]


def _existing(path: Optional[str]) -> Optional[str]:
    """path, если файл существует, иначе None."""
    return path if (path and os.path.exists(path)) else None


@dataclass
class PreviewTextureState:
    """Состояние текстур превью: пользовательские загрузки + данные модели."""

    # ── Пользовательские текстуры ─────────────────────────────────────────── #
    #: {team: {mat_name: path}} — загруженные пользователем (skin 0).
    textures: Dict[str, Dict[str, str]] = field(
        default_factory=lambda: {Team.RED: {}, Team.BLU: {}})
    #: {skin_idx: {mat_name: path}} — переопределения вариантных стилей (skin > 0).
    skin_overrides: Dict[int, Dict[str, str]] = field(default_factory=dict)

    # ── Активные селекторы ────────────────────────────────────────────────── #
    active_team: str = Team.RED
    active_skin: int = 0
    #: dict из SkinDetectWorker (num_skins, roles, …) или None — стили не определены.
    skin_info: Optional[dict] = None
    #: «Сделать командным» (+ Команда): оружие БЕЗ нативной команды, которому
    #: пользователь синтезирует RED/BLU. У таких материалов нет blu_name_map/
    #: blu_frames, поэтому is_neutral() их считает нейтральными — но при force_team
    #: загрузка НЕ должна дублироваться в обе команды (иначе BLU затирает RED и
    #: 2D/3D показывают одинаковое). См. set_texture().
    force_team: bool = False

    # ── Данные модели (заполняются воркерами превью) ──────────────────────── #
    #: Имена материалов геометрии; [0] — главный. ВНИМАНИЕ: в режиме «Прочее»
    #: временно подменяется служебными — стабильное имя главного в main_material.
    material_names: List[str] = field(default_factory=list)
    #: Стабильное имя главного материала (не зависит от «Прочее»).
    main_material: Optional[str] = None
    #: {red_mat: blu_display_name} — командные пары материалов (персонажи/руки).
    blu_name_map: Dict[str, str] = field(default_factory=dict)
    #: Игровые оригиналы из VPK: {red_mat: png} по командам (ключи — RED-имена).
    vpk_red_tex_map: Dict[str, str] = field(default_factory=dict)
    vpk_blu_tex_map: Dict[str, str] = field(default_factory=dict)
    #: Командная текстура одним кадром (кадры анимации): пути PNG.
    red_frames: List[str] = field(default_factory=list)
    blu_frames: List[str] = field(default_factory=list)

    # ── Вариант Australium/Gold ───────────────────────────────────────────── #
    australium_frame: Optional[str] = None      # игровой gold-кадр (PNG)
    australium_user_tex: Optional[str] = None   # своя текстура варианта
    australium_mat_name: Optional[str] = None   # имя gold-материала (для сборки)
    australium_active: bool = False             # активен ли вариант в превью

    # ═══════════════════════════════════════════════════════════════════════ #
    # Ключи / классификация материалов
    # ═══════════════════════════════════════════════════════════════════════ #

    def storage_main_key(self) -> str:
        """Ключ ХРАНЕНИЯ главной текстуры (как исторически пишет load_image)."""
        return self.material_names[0] if self.material_names else SINGLE_TEX_KEY

    def stable_main(self) -> Optional[str]:
        """Стабильное имя главного материала независимо от режима «Прочее»."""
        if self.main_material:
            return self.main_material
        return self.material_names[0] if self.material_names else None

    def is_team_material(self, mat: str) -> bool:
        """True, если материал КОМАНДНЫЙ (есть свой синий вариант).

        С per-material маппингом — синее имя отличается от красного
        (medic_hands_red→medic_hands_blue). Без маппинга — главный материал
        командный, если BLU пришёл одним кадром (blu_frames): синий вариант
        существует, просто не по-материально. Это ЕДИНОЕ правило командности —
        им пользуются и хранение (is_neutral), и разрешение (resolve_base);
        расхождение этих двух путей давало «на BLU показывается RED» у
        мульти-материальных шапок с одним BLU-кадром.
        """
        if self.blu_name_map:
            bn = self.blu_name_map.get(mat, mat)
            return bn.lower() != mat.lower()
        if self.blu_frames:
            main_key = self.main_material or self.storage_main_key()
            return mat in (main_key, SINGLE_TEX_KEY)
        return False

    def is_neutral(self, mat: str) -> bool:
        """True, если текстура не относится к конкретной команде (RED/BLU).

        Нейтральные (sniper_lens, c_arrow, eyeball_r …) одинаковы для обеих
        команд — хранятся в обоих словарях, чтобы карточка не пропадала при
        переключении команды.

        Не симметрично is_team_material при непустом маппинге: нейтральность
        исключает и КЛЮЧИ, и ЗНАЧЕНИЯ маппинга (BLU-имя — тоже командное),
        а is_team_material смотрит только на пары «имя ≠ синее имя».
        """
        if self.blu_name_map:
            return (mat not in self.blu_name_map and
                    mat not in self.blu_name_map.values())
        return not self.is_team_material(mat)

    # ═══════════════════════════════════════════════════════════════════════ #
    # Запись
    # ═══════════════════════════════════════════════════════════════════════ #

    def set_texture(self, mat: str, path: Optional[str]) -> None:
        """Сохраняет (или сбрасывает, path=None) пользовательскую текстуру.

        Маршрутизация:
          • активен вариантный стиль (skin > 0) → skin_overrides этого стиля;
          • нейтральная → обе команды;
          • командная → только активная команда.
        """
        if self.skin_info and self.active_skin != 0:
            slot = self.skin_overrides.setdefault(self.active_skin, {})
            if path:
                slot[mat] = path
            else:
                slot.pop(mat, None)
            return

        # Нейтральная текстура пишется в обе команды, чтобы карточка не пропадала
        # при переключении команды. ИСКЛЮЧЕНИЕ — force_team: там пользователь
        # намеренно задаёт РАЗНЫЕ текстуры RED/BLU, поэтому дублирование запрещено
        # (иначе загрузка на BLU затирает RED). Дефолт «BLU как RED» до задания
        # своей синей обеспечивает симметричный fallback в resolve_base().
        teams = [self.active_team]
        if self.is_neutral(mat) and not self.force_team:
            teams.append(Team.BLU if self.active_team == Team.RED else Team.RED)
        for team in teams:
            if path:
                self.textures.setdefault(team, {})[mat] = path
            else:
                self.textures.get(team, {}).pop(mat, None)

    # ═══════════════════════════════════════════════════════════════════════ #
    # Разрешение (что показывать)
    # ═══════════════════════════════════════════════════════════════════════ #

    def variant_display_texture(self) -> Optional[str]:
        """Текстура активного варианта (Australium) или None, если не активен.
        Своя загруженная приоритетнее игрового gold-кадра."""
        if not self.australium_active:
            return None
        return _existing(self.australium_user_tex) or self.australium_frame

    def resolve_card(self, mat: str, hands_blu_view: bool = False) -> Optional[str]:
        """Текстура для карточки при текущей команде/стиле.

        hands_blu_view — режим рук на BLU: нейтральный материал показываем
        пустым (= «общий, наследует RED»), пока ему не задана отдельная синяя.
        """
        # Вариантный стиль (skin > 0): ТОЛЬКО его переопределение, без
        # наследования базы/игры — пустая карточка предлагает выбрать.
        if self.skin_info and self.active_skin != 0:
            return _existing(self.skin_overrides.get(self.active_skin, {}).get(mat))

        if hands_blu_view and not self.is_team_material(mat):
            return _existing(self.textures.get(Team.BLU, {}).get(mat))

        return self.resolve_base(mat)

    def resolve_base(self, mat: str) -> Optional[str]:
        """Базовая (skin 0) текстура материала: пользовательская активной
        команды → другая команда (нейтральные) → игровой оригинал из VPK →
        командный кадр для главного материала. Без учёта стилей (skin > 0)."""
        active = self.active_team
        p = _existing(self.textures.get(active, {}).get(mat))
        if p:
            return p

        team_specific = self.is_team_material(mat)
        if not team_specific:
            other = Team.BLU if active == Team.RED else Team.RED
            p = _existing(self.textures.get(other, {}).get(mat))
            if p:
                return p

        # Игровой оригинал текущей команды (карты ключуются RED-именами).
        vpk_map = self.vpk_red_tex_map if active == Team.RED else self.vpk_blu_tex_map
        g = _existing(vpk_map.get(mat))
        if g:
            return g

        # Нейтральные/служебные не зависят от команды — их оригинал только в
        # RED-карте; на BLU показываем его же (иначе «Прочее» на BLU пустое).
        if active != Team.RED and not team_specific:
            g = _existing(self.vpk_red_tex_map.get(mat))
            if g:
                return g

        # Главный материал без per-material карты: BLU пришёл одним кадром.
        if self.material_names and mat == self.material_names[0]:
            frames = self.blu_frames if active == Team.BLU else self.red_frames
            if frames and os.path.exists(frames[0]):
                return frames[0]

        return None

    # ═══════════════════════════════════════════════════════════════════════ #
    # Что уходит в сборку
    # ═══════════════════════════════════════════════════════════════════════ #

    def red_main(self) -> Optional[str]:
        """Пользовательская RED-текстура главного слота (без fallback на BLU)."""
        return _existing(self.textures.get(Team.RED, {}).get(self.storage_main_key()))

    def blu_main(self) -> Optional[str]:
        """Пользовательская BLU-текстура: главный слот, иначе любой BLU-слот."""
        blu = self.textures.get(Team.BLU, {})
        p = _existing(blu.get(self.storage_main_key()))
        if p:
            return p
        for candidate in blu.values():
            p = _existing(candidate)
            if p:
                return p
        return None

    def uploaded_for_mat(self, mat: str) -> Optional[str]:
        """Загруженная пользователем текстура для материала (для сборки).

        RED и BLU не смешиваются:
          1. RED-имя (ключ blu_name_map) → только textures[RED] — иначе сборка
             молча подставила бы BLU вместо диалога.
          2. BLU-имя (значение) → обратный поиск textures[BLU][RED-ключ]
             (карточки хранят BLU-текстуры под RED-ключами).
          3. Нейтральная при непустом маппинге → обе команды.
          4. Маппинг пуст → обе команды; суффикс '_blue'/'_blu' (force-team) →
             textures[BLU][база], затем главная BLU как fallback.
        """
        if self.blu_name_map:
            if mat in self.blu_name_map:
                return _existing(self.textures.get(Team.RED, {}).get(mat))
            for red_key, blu_name in self.blu_name_map.items():
                if blu_name == mat:
                    return _existing(self.textures.get(Team.BLU, {}).get(red_key))
            for team in (Team.RED, Team.BLU):
                p = _existing(self.textures.get(team, {}).get(mat))
                if p:
                    return p
            return None

        for team in (Team.RED, Team.BLU):
            p = _existing(self.textures.get(team, {}).get(mat))
            if p:
                return p
        ml = mat.lower()
        for suf in ('_blue', '_blu'):
            if ml.endswith(suf):
                base = mat[:-len(suf)]
                p = _existing(self.textures.get(Team.BLU, {}).get(base))
                if p:
                    return p
                # force_team без своей синей → «как RED»: берём базовую RED-текстуру
                # (раньше это обеспечивал дубль в set_texture; теперь дубля нет,
                # поэтому дефолт восстанавливаем здесь, в резолве сборки — иначе
                # синий скин остался бы без VTF = фиолетовый в игре).
                if self.force_team:
                    r = _existing(self.textures.get(Team.RED, {}).get(base))
                    if r:
                        return r
                return self.blu_main()
        return None

    def uploaded_slot_paths(self) -> Dict[str, str]:
        """{mat: path} всех заполненных слотов; активная команда приоритетнее.
        SINGLE_TEX_KEY пропускается (главная идёт в сборку отдельно)."""
        result: Dict[str, str] = {}
        for team in team_priority(self.active_team):
            for mat, path in self.textures.get(team, {}).items():
                if mat == SINGLE_TEX_KEY or mat in result:
                    continue
                if _existing(path):
                    result[mat] = path
        return result

    def blu_uploaded_paths(self) -> Dict[str, str]:
        """{mat: path} только BLU-слотов (для командности рук при сборке)."""
        return {
            mat: path
            for mat, path in self.textures.get(Team.BLU, {}).items()
            if mat != SINGLE_TEX_KEY and _existing(path)
        }

    # ═══════════════════════════════════════════════════════════════════════ #
    # Снимок / восстановление (мини-память оружия)
    # ═══════════════════════════════════════════════════════════════════════ #

    def snapshot(self) -> dict:
        """Глубокий снимок данных модели — для мгновенного восстановления
        оружия при возврате (без перезапуска воркера). Австралий-активность
        не сохраняется: после восстановления вариант всегда выключен."""
        return {
            'textures': {t: dict(d) for t, d in self.textures.items()},
            'material_names': list(self.material_names),
            'main_material': self.main_material,
            'active_team': self.active_team,
            'force_team': self.force_team,
            'blu_name_map': dict(self.blu_name_map),
            'vpk_red_tex_map': dict(self.vpk_red_tex_map),
            'vpk_blu_tex_map': dict(self.vpk_blu_tex_map),
            'red_frames': list(self.red_frames),
            'blu_frames': list(self.blu_frames),
            'australium_frame': self.australium_frame,
            'australium_mat_name': self.australium_mat_name,
            'australium_user_tex': self.australium_user_tex,
        }

    def restore(self, snap: dict) -> None:
        """Восстанавливает данные модели из snapshot(). Стили (skin_overrides)
        в мини-память не входят — они живут в пер-стилевой памяти шапок;
        на всякий случай сбрасываем их, чтобы залипший active_skin не резолвил
        карточки восстановленного оружия в чужие override'ы."""
        self.reset_skins()
        self.textures = {t: dict(d) for t, d in (snap.get('textures') or {}).items()}
        self.material_names = list(snap.get('material_names') or [])
        self.main_material = snap.get('main_material')
        self.active_team = snap.get('active_team', Team.RED)
        self.force_team = snap.get('force_team', False)
        self.blu_name_map = dict(snap.get('blu_name_map') or {})
        self.vpk_red_tex_map = dict(snap.get('vpk_red_tex_map') or {})
        self.vpk_blu_tex_map = dict(snap.get('vpk_blu_tex_map') or {})
        self.red_frames = list(snap.get('red_frames') or [])
        self.blu_frames = list(snap.get('blu_frames') or [])
        self.australium_frame = snap.get('australium_frame')
        self.australium_mat_name = snap.get('australium_mat_name')
        self.australium_user_tex = snap.get('australium_user_tex')
        self.australium_active = False

    # ═══════════════════════════════════════════════════════════════════════ #
    # Сбросы
    # ═══════════════════════════════════════════════════════════════════════ #

    def reset_skins(self) -> None:
        """Сброс стилей (skinfamilies) — при смене модели."""
        self.skin_info = None
        self.active_skin = 0
        self.skin_overrides = {}

    def reset_team_data(self) -> None:
        """Сброс командных данных из VPK (кадры, карты, маппинг имён)."""
        self.red_frames = []
        self.blu_frames = []
        self.vpk_red_tex_map = {}
        self.vpk_blu_tex_map = {}
        self.blu_name_map = {}
        self.active_team = Team.RED
        self.force_team = False

    def reset_australium(self) -> None:
        """Сброс варианта Australium (кадр, своя текстура, активность)."""
        self.australium_frame = None
        self.australium_active = False
        self.australium_user_tex = None
        self.australium_mat_name = None
