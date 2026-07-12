"""
Миксин панели превью: режимы CritHIT и эффекта смерти.

Вход в крит-/death-режим, рендер крит-сцены на модель-персонаж и
вспомогательные операции (поиск кастомной модели крита, конвертация
игровой VTF, извлечение игровой текстуры эффекта смерти). Вынесены из
``PreviewPanel`` без изменения тел; состояние остаётся на панели и
разрешается через ``self``.
"""

import os

from src.shared.file_utils import get_temp_file_path
from src.shared.logging_config import get_logger
from src.ui.preview_mode import PreviewMode

logger = get_logger(__name__)


class PreviewCritHitMixin:
    """Режимы CritHIT и эффекта смерти (см. модуль)."""

    def set_crithit_mode(self, _render: bool = True) -> None:
        # _render=False — когда метод используется как подложка для эффекта смерти:
        # рендер крит-сцены отложен до входа в DEATH (иначе первый рендер уйдёт в
        # billboard, т.к. _death_effect_mode ещё False).
        # ── Снимок уходящего оружия в мини-память (ДО очистки состояния) ──── #
        # Переход в крит идёт через этот метод, а не set_3d_params, поэтому
        # снимок надо делать здесь — иначе возврат на оружие ничего не вернёт.
        snap = self._snapshot_outgoing(self._weapon_mode)
        if snap:
            self._mem_mode = snap['mode']
            self._mem_data = snap

        # Текстура/изображение оружия НЕ должны протекать в крит-сцену
        # (_render_crithit_scene использует self.image_path как текстуру биллборда).
        self.image_path = None
        self.vtf_path = None
        self._cur_obj = None

        # Переход из скайбокса: стоп его воркеров + снять фон-кубмапу.
        if self._pstate.is_skybox:
            self._exit_skybox_mode()

        self._pstate.enter(PreviewMode.CRITHIT)
        # Маски шпиона не относятся к крит/спец-режимам — прячем их селекторы,
        # иначе при переходе из режима масок в Special они «залипают».
        self._sync_spy_mask_buttons()
        self._pending_3d_params = None
        # Сбрасываем кэш последних 3D-параметров: иначе возврат на то же оружие,
        # что было до крита, вызовет ранний return в set_3d_params и _crithit_mode
        # останется True (кнопки не вернутся, крит-сцена зависнет).
        self._last_3d_params = None
        self._stop_worker('_3d_worker')
        self._stop_worker('_vpk_mod_worker')
        self._reset_team_vpk_state()
        # Прячем кнопки загрузки модели/VPK (крит-режим)
        self._update_3d_buttons_visibility()
        if self._3d_widget:
            self._3d_widget.show_prompt(
                self.t.get('3d_prompt_crithit', 'Switch to 3D tab — the soldier will appear automatically')
            )
        if _render and self.is_3d_mode() and self._3d_available:
            self._render_crithit_scene()

    def set_death_effect_mode(self, mode: str = '',
                              textures_vpk: str = '', misc_vpk: str = '') -> None:
        """Режим превью эффекта смерти (лёд/золото/огонь): модель-персонаж крита,
        но пользовательская текстура накладывается на МОДЕЛЬ — как будет в игре.

        Сначала на модель кладётся ОРИГИНАЛЬНАЯ игровая текстура эффекта (лёд/
        золото/огонь) из VPK — как у обычных моделей подтягивается игровая
        текстура. Пользовательская заменяет её при загрузке.

        Переиспользует крит-инфраструктуру (_crithit_mode = «режим сцены с
        персонажем»), флаг _death_effect_mode меняет, куда идёт текстура."""
        # Игровую текстуру эффекта тянем ДО set_crithit_mode (он чистит image_path).
        self._death_default_tex = ''
        if mode and (textures_vpk or misc_vpk):
            self._death_default_tex = self._extract_game_texture_for_death(
                mode, [textures_vpk, misc_vpk]
            )
        self.set_crithit_mode(_render=False)   # настройка крит-сцены БЕЗ рендера
        self._pstate.enter(PreviewMode.DEATH)  # → DEATH (_crithit_mode остаётся True, см. свойство)
        if self._3d_widget:
            self._3d_widget.show_prompt(
                self.t.get('3d_prompt_death_effect',
                           'Switch to 3D tab — the effect will appear on the model')
            )
        if self.is_3d_mode() and self._3d_available:
            self._render_crithit_scene()

    def _extract_game_texture_for_death(self, mode: str, vpk_paths: list) -> str:
        """Достаёт оригинальную VTF эффекта из игрового VPK → PNG (для дефолта).

        Возвращает путь к PNG или '' если не нашли (тогда модель без текстуры)."""
        try:
            from src.services.vmt_service import VMTService
            rel, _vmt, vtf = VMTService.get_weapon_relpaths(mode)
            rel_url = rel.replace('\\', '/').rstrip('/')
            candidates = [f"{rel_url}/{vtf}"]
            if vtf.lower() != vtf:
                candidates.append(f"{rel_url}/{vtf.lower()}")
            # Игровые VPK — через общий потоко-локальный кэш (vpk.open парсит
            # весь индекс, повторные переключения эффекта смерти мгновенны).
            from src.services import vtf_preview_service as vps
            paks = vps.open_vpks(vpk_paths)
            for pak in paks:
                for cand in candidates:
                    try:
                        data = pak[cand].read()
                    except KeyError:
                        continue
                    tmp = str(get_temp_file_path(prefix='tf2_deatheff_', suffix='.vtf'))
                    with open(tmp, 'wb') as f:
                        f.write(data)
                    png = self._convert_model_vtf(tmp)
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                    if png:
                        logger.info(f"[DEATH FX] игровая текстура эффекта: {cand}")
                        return png
        except Exception as exc:
            logger.debug(f"[DEATH FX] не удалось достать игровую текстуру: {exc}")
        return ''


    def _update_scene_texture(self, path: str) -> None:
        """Применяет новую текстуру к сцене-персонажу: для эффекта смерти —
        перерисовываем модель с текстурой; для крита — обновляем billboard."""
        if not self._3d_widget:
            return
        if self._death_effect_mode:
            self._render_crithit_scene()      # текстура ложится на модель
        else:
            self._3d_widget.update_crithit_texture(path)   # billboard крита

    def _render_crithit_scene(self) -> None:
        if not self._3d_widget or not self._3d_available:
            return
        class_name = self._crithit_class
        custom_model, model_tex = self._find_crithit_custom_model(class_name)

        if self._death_effect_mode:
            # Эффект смерти: на модель — текстура пользователя, иначе оригинальная
            # игровая текстура эффекта (лёд/золото/огонь). Billboard не показываем.
            crit_path = ''
            model_tex = self.image_path or self._death_default_tex or ''
        else:
            # Крит: текстура пользователя — billboard, модель в своей текстуре.
            crit_path = self.image_path or ''

        if model_tex.lower().endswith('.vtf'):
            model_tex = self._convert_model_vtf(model_tex)

        if custom_model:
            if custom_model.lower().endswith('.smd'):
                import tempfile
                from src.services.smd_to_obj_service import SmdToObjService
                self._3d_widget.show_loading("Converting custom model...")
                tmp = tempfile.mkdtemp(prefix="tf2_crithit_")
                obj = os.path.join(tmp, "model.obj")
                ok = SmdToObjService.convert(custom_model, obj)
                if ok and os.path.exists(obj):
                    self._3d_widget.load_crithit_scene_with_model(obj, crit_path, model_tex)
                else:
                    self._3d_widget.load_crithit_scene(crit_path, model_tex)
            else:
                self._3d_widget.load_crithit_scene_with_model(custom_model, crit_path, model_tex)
        else:
            self._3d_widget.load_crithit_scene(crit_path, model_tex)

    @staticmethod
    def _find_crithit_custom_model(class_name: str = 'soldier') -> tuple:
        here = os.path.dirname(os.path.abspath(__file__))
        model_root = os.path.join(os.path.dirname(os.path.dirname(here)), "tools", "Model")
        MODEL_EXTS = ('.obj', '.smd')
        TEX_EXTS   = ('.png', '.jpg', '.jpeg', '.bmp', '.tga', '.vtf', '.webp')

        def _scan(folder):
            if not os.path.isdir(folder):
                return '', ''
            m = t = ''
            for name in sorted(os.listdir(folder)):
                if name.startswith('.'):
                    continue
                lo, full = name.lower(), os.path.join(folder, name)
                if not m and lo.endswith(MODEL_EXTS): m = full
                if not t and lo.endswith(TEX_EXTS):   t = full
            return m, t

        m, t = _scan(os.path.join(model_root, class_name.lower()))
        if m:
            return m, t
        return _scan(model_root)

    @staticmethod
    def _convert_model_vtf(vtf_path: str) -> str:
        try:
            from src.services.vtflib_wrapper import VTFLib
            from PIL import Image
            rgba, w, h = VTFLib.read_vtf_as_rgba(vtf_path)
            img = Image.frombytes("RGBA", (w, h), rgba)
            png = str(get_temp_file_path(prefix='tf2_model_tex_', suffix='.png'))
            img.save(png)
            return png
        except Exception as exc:
            logger.warning(f"VTF→PNG модели: {exc}")
            return ''
