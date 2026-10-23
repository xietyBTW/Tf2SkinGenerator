"""
Воркер определения стилей (skinfamilies) оригинальной игровой модели

Используется при замене модели кастомной: чтобы приложение узнало, сколько
стилей (skin 0/1/2…) и какие роли (Bloody/Clean/команды/австралий) есть у
оригинала, и предложило пользователю их переопределить

Источник истины - QC декомпилированной игровой модели:
  1. Сначала ищем готовый QC в кэше декомпиляции (мгновенно).
  2. Если кэша нет - извлекаем MDL из VPK и декомпилируем через Crowbar
     (тот же путь, что и 3D-превью, результат тоже кладётся в кэш)

НИЧЕГО не трогает в дефолтном пути сборки - только читает QC и отдаёт
структуру стилей наверх через сигнал
"""

import os
import glob
from typing import Optional

from src.services.base_worker import Signal

from src.data.weapons import WEAPON_MDL_PATHS
from src.services import decompile_cache, model_decompile_service
from src.services.base_worker import BaseWorker
from src.services.model_build_service import ModelBuildService
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class SkinDetectWorker(BaseWorker):
    """Определяет skinfamilies оригинальной модели в фоне"""

    # dict из ModelBuildService.extract_skin_info (num_skins, roles, is_team, …)
    detected = Signal(object)
    # Не удалось (модель не найдена / ошибка декомпиляции) - UI просто не
    # показывает стили, кастомная замена продолжает работать как одно-скиновая
    failed = Signal(str)

    def __init__(
        self,
        weapon_key: str,
        mode: str,
        misc_vpk_path: str,
        lang: str = 'en',
        parent=None,
    ):
        super().__init__(parent)
        self.weapon_key = weapon_key
        self.mode = mode
        self.misc_vpk_path = misc_vpk_path
        self._lang = lang

    def run(self) -> None:
        try:
            qc_path = self._get_qc()
            if not qc_path or not os.path.exists(qc_path):
                self.failed.emit("qc_not_found")
                return
            info = ModelBuildService.extract_skin_info(qc_path)
            if not info:
                self.failed.emit("no_skin_info")
                return
            info = self._with_item_styles(info)
            logger.info(
                f"[SKIN] {self.weapon_key}: num_skins={info.get('num_skins')} "
                f"roles={info.get('roles')} is_team={info.get('is_team')} "
                f"australium={info.get('has_australium')}"
            )
            self.detected.emit(info)
        except Exception as exc:
            logger.warning(f"[SKIN] detect failed for {self.weapon_key}: {exc}", exc_info=True)
            self.failed.emit(str(exc))

    def _with_item_styles(self, info: dict) -> dict:
        """
        Строки скина, которые в игре - отдельный предмет («Критокола» - строка 2
        модели Бонка), становятся стилями с его именем. QC знает их только как
        «Skin N», а безымянные строки в полосу стилей не идут - и такую
        текстуру было не выбрать и не поправить
        """
        from src.data.item_skin_styles import styled_skins
        from src.data.weapon_model_index import tf2_root_from_misc_vpk

        if self.mode == "hat":
            return info
        root = tf2_root_from_misc_vpk(self.misc_vpk_path)
        named = styled_skins(self.weapon_key, root, self._lang) if root else []
        rows = info.get('rows') or []
        have = {int(index) for _label, index in info.get('styles') or ()}
        # Строка-копия более ранней (у «Ботоубийц» огнемёта строки 3/5/7 -
        # та же синяя: их цвет даёт навешенная голова робота) - не стиль:
        # править в ней нечего, текстура общая
        extra = [(name, skin) for name, skin in named
                 if 0 < skin < len(rows) and skin not in have and rows[skin] not in rows[:skin]]
        if not extra:
            return info
        titles = dict((skin, name) for name, skin in extra)
        return {
            **info,
            'styles': [*(info.get('styles') or []), *extra],
            'skins': [{**s, 'role': titles.get(s.get('index'), s.get('role'))}
                      for s in info.get('skins') or []],
        }

    # получение QC

    def _get_qc(self) -> Optional[str]:
        """QC из кэша или после декомпиляции (cache miss)"""
        # 1) Быстрый путь - любой кэш для этого weapon_key
        cached_qc = decompile_cache.find_cached_qc_for_weapon(self.weapon_key)
        if cached_qc:
            logger.info(f"[SKIN] кэш QC для {self.weapon_key}")
            return cached_qc

        # 2) Cache miss - извлекаем и декомпилируем (как 3D-превью)
        return self._extract_and_decompile()

    def _mdl_rel(self) -> str:
        from src.data.weapon_quirks import PREVIEW_MDL_OVERRIDE
        from src.data.player_characters import PLAYER_BODY_MODE_KEYS as _PBK, SPY_MASK_MODE_KEY as _SMK
        override = PREVIEW_MDL_OVERRIDE.get(self.weapon_key)
        if self.mode == "hat" or self.mode in _PBK or self.mode == _SMK:
            return self.weapon_key
        if override:
            return override
        return WEAPON_MDL_PATHS.get(
            self.weapon_key,
            f"models/weapons/c_models/{self.weapon_key}/{self.weapon_key}.mdl",
        )

    def _mdl_candidates(self) -> list:
        """Пути MDL внутри VPK в порядке приоритета"""
        from src.data.weapon_quirks import PREVIEW_MDL_OVERRIDE
        from src.data.player_characters import PLAYER_BODY_MODE_KEYS as _PBK

        mdl_rel = self._mdl_rel()
        if self.mode == "hat" or self.mode in _PBK or self.weapon_key in PREVIEW_MDL_OVERRIDE:
            return [mdl_rel]

        from src.data.weapon_model_index import tf2_root_from_misc_vpk
        from src.services.extract_model_service import ExtractModelService
        return ExtractModelService._build_paths_to_try(
            self.mode, self.weapon_key, tf2_root_from_misc_vpk(self.misc_vpk_path)
        )

    def _extract_and_decompile(self) -> Optional[str]:
        """QC после извлечения из VPK и Crowbar. None - показывать нечего

        Определение стилей - фоновая подсказка, а не основная работа: любая
        неудача здесь означает «стилей не знаем», и наверх уходит пустой
        результат, а не ошибка
        """
        try:
            result = model_decompile_service.ensure_decompiled(
                self.weapon_key,
                self.misc_vpk_path,
                self._mdl_candidates(),
                cancelled=self.isInterruptionRequested,
            )
        except model_decompile_service.DecompileError as exc:
            logger.warning(f"[SKIN] {self.weapon_key}: {exc}")
            return None
        if result is None:
            return None

        qcs = glob.glob(os.path.join(result.directory, "*.qc"))
        return qcs[0] if qcs else None
