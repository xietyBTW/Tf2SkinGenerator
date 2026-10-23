"""
Блеск Killstreak на показанном оружии: где на модели лежит маска и превью
конструктора узора (src/services/sheen_builder.py) в пропорции оружия

От сеанса нужны показанное оружие, его модель, мод из VPK и пути к игре

Доступ - `session().sheen`; `api.py` зовёт его методы напрямую
"""

from __future__ import annotations

import itertools
import os
from typing import TYPE_CHECKING, Any, Dict, Optional

from src.shared.logging_config import get_logger

if TYPE_CHECKING:
    from src.app.session import AppSession

logger = get_logger(__name__)


class SheenEditor:
    """Маска блеска показанного оружия и превью своих узоров"""

    def __init__(self, host: "AppSession") -> None:
        self._host = host
        #: Номера превью конструктора и последний выданный: старый расчёт по
        #: нему видит, что узор уже другой, и бросает работу. next() у count
        #: атомарен, а `+= 1` из двух потоков сервера мог выдать один номер
        self._preview_numbers = itertools.count(1)
        self._preview_seq = 0

    def sheen_mask_params(self) -> Optional[Dict[str, Any]]:
        """Положение полосы блеска для показанного оружия - из заголовка его
        MDL в игре (vmt_effects.sheen_mask_params). None - не оружие или нет
        игры. Своя геометрия: берётся стоковая модель, полоса может лечь
        чуть иначе"""
        from src.services import vmt_effects
        from src.services.game_vpk_reader import GameVpkReader

        if not self._host._shown_weapon():
            return None
        # Мод из VPK со своей моделью: полоса - по ней. У куная из мода
        # модель на 2.5 единицы длиннее стоковой, и низ выпадал из маски
        p = self._host.preview
        if p.custom_vpk_mode and p.custom_vpk_own_model and self._host._vpk_mod_path:
            data = self._mod_mdl(self._host._shown_weapon())
            if data:
                return vmt_effects.sheen_mask_params(data)
        paths = self._host.tf2_paths()
        if 'error' in paths:
            return None
        from src.services.paintkit_worker import _find_mdl

        reader = GameVpkReader([paths['misc_vpk']])
        try:
            # Не у всех оружий модель лежит в c_models/<ключ>/: тогда по имени
            data = _find_mdl(reader, self._host._shown_mdl())
        finally:
            reader.close()
        return vmt_effects.sheen_mask_params(data) if data else None

    def _mod_mdl(self, weapon_key: str) -> Optional[bytes]:
        """MDL оружия из архива показанного мода (имя = ключ оружия;
        гирлянда того же мода - отдельный файл и сюда не попадает)"""
        import vpk as vpklib
        try:
            pak = vpklib.open(self._host._vpk_mod_path)
            for name in pak:
                if (name.lower().endswith('.mdl')
                        and os.path.basename(name)[:-4].lower() == weapon_key.lower()):
                    return pak[name].read()
        except Exception as exc:                             # noqa: BLE001
            logger.warning(f'MDL мода не прочитан: {exc}')
        return None

    def _sheen_aspect(self) -> tuple:
        """(пропорция показанного оружия, оружие ли это) - как в имени маски"""
        from src.services import sheen_builder
        try:
            bounds = self.sheen_mask_params()
        except Exception:                                  # noqa: BLE001
            bounds = None
        aspect = (bounds['stencil']['aspect'] if bounds and bounds.get('stencil')
                  else sheen_builder.DEFAULT_ASPECT)
        return round(min(12.0, max(0.5, aspect)), 1), bool(bounds)

    def sheen_preset_thumbs(self) -> Dict[str, Any]:
        import tempfile
        from pathlib import Path

        from src.services import sheen_builder

        aspect, _weapon = self._sheen_aspect()
        out = Path(tempfile.gettempdir()) / 'tf2sg_sheen_thumbs'
        thumbs = {}
        for key, p in sheen_builder.PRESETS.items():
            png = out / f'{key}_{aspect}.png'
            thumbs[key] = str(png) if png.exists() else sheen_builder.thumbnail(p['spec'], aspect, png)
        return {'thumbs': thumbs, 'aspect': aspect}

    def sheen_pattern_preview(self, spec: Dict[str, Any], length: float,
                              full: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Кадры узора из конструктора картинкой-сеткой - в пропорции
        показанного оружия (как ляжет в игре), иначе обычного ствола

        Новый вызов прерывает предыдущий ({'cancelled': True}): страница
        шлёт правку, не дожидаясь прошлого расчёта, и тяжёлый узор (высокое
        качество, 8 с прохода) не держит её секундами на устаревших кадрах"""
        import tempfile
        from pathlib import Path

        from src.services import sheen_builder, sheen_patterns

        aspect, weapon = self._sheen_aspect()             # как в имени маски
        mine = self._preview_seq = next(self._preview_numbers)
        try:
            res = sheen_builder.preview(
                spec, sheen_patterns.frames_for(float(length or 2.5)), aspect,
                Path(tempfile.gettempdir()) / 'tf2sg_sheen',
                cancelled=lambda: self._preview_seq != mine, gamut_spec=full)
        except sheen_builder.Cancelled:
            return {'cancelled': True}
        return {**res, 'aspect': aspect, 'weapon': weapon}
