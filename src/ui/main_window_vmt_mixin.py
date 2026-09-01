"""
Миксин главного окна: VMT-редактор и извлечение оригинальных VMT.

Разрешение цели редактирования по текущему режиму, извлечение исходного
VMT из игровых VPK / из QC / для шапок и открытие редактора VMT. Вынесены
из ``MainWindow`` без изменения тел; состояние и виджеты остаются на окне
и разрешаются через ``self``.
"""

import os
from typing import Optional

from src.shared.logging_config import get_logger
from src.ui.error_handler import ErrorHandler
from src.ui.vmt_editor import VMTEditorDialog

logger = get_logger(__name__)


class MainWindowVmtMixin:
    """VMT-редактор и извлечение оригинальных VMT (см. модуль)."""

    def _resolve_vmt_target(self):
        """(weapon_key, display_name) для VMT-редактора по текущему режиму, либо None
        (с предупреждением), если режим не поддерживается.

        Само правило — в ``vmt_source_service.resolve_target``: тем же путём
        ключ находит веб-представление, а расхождение означало бы «правка
        потерялась»."""
        from src.services import vmt_source_service

        target = vmt_source_service.resolve_target(
            self.mode,
            hat_mdl=getattr(self, '_hat_mdl_path', None),
            hat_display=getattr(self, '_hat_display_name', None),
        )
        if target is None:
            key = ('select_weapon_error' if self.mode == 'hat'
                   else 'vmt_editor_not_available')
            fallback = ('Select a hat first' if self.mode == 'hat'
                        else 'VMT editor is not available for this mode.')
            ErrorHandler.show_warning(self, self.t.get(key, fallback), self.t['error'])
        return target

    def _open_vmt_for_material(self, material: str = "") -> None:
        """
        Открывает VMT-редактор для КОНКРЕТНОГО материала карточки (пер-текстурно).
        material='' → главный материал текущего превью.
        """
        if not hasattr(self, 'mode') or not self.mode:
            ErrorHandler.show_warning(self, self.t.get('select_weapon_error', 'Select a weapon first'), self.t['error'])
            return
        from src.data.weapons import SPECIAL_MODES
        if self.mode in set(SPECIAL_MODES) | {"custom"}:
            ErrorHandler.show_warning(self, self.t.get('vmt_editor_not_available', 'VMT editor is not available for this mode.'), self.t['error'])
            return
        target = self._resolve_vmt_target()
        if target is None:
            return
        weapon_key, display_name = target

        mat = (material or '').strip()
        if not mat and hasattr(self, 'preview_panel'):
            names = getattr(self.preview_panel, '_material_names', None) or []
            mat = names[0] if names else ''
        if not mat:
            mat = weapon_key  # запасной ключ (как у глобальной кнопки)

        # Ключ хранилища и извлекаемый файл = имя материала. Для главного материала
        # это совпадает с texture_filename, который сборка уже ищет.
        self._open_vmt_for_target(weapon_key, mat, edit_key=mat, material_name=mat)

    def _open_vmt_for_target(self, weapon_key: str, display_name: str,
                             edit_key: Optional[str] = None,
                             material_name: Optional[str] = None) -> None:
        """
        Открывает сохранённый VMT либо извлекает оригинал из игры и открывает редактор.

        edit_key      — ключ EditedVMTService (по умолч. weapon_key — главный материал).
        material_name — имя VMT-файла для извлечения (по умолч. weapon_key).
        """
        from src.services.edited_vmt_service import EditedVMTService
        edit_key = edit_key or weapon_key
        material_name = material_name or weapon_key
        # ── Открываем сохранённый VMT (если есть) ────────────────────────── #
        edited_vmt_path = EditedVMTService.get_edited_vmt(edit_key)
        if edited_vmt_path and os.path.exists(edited_vmt_path):
            # Игровой оригинал берём из бэкапа (.orig) — чтобы «Reset to game
            # original» вернул именно его, а не текущую правку. Если бэкапа нет
            # (правка сделана до появления этого механизма) — доизвлекаем оригинал
            # из игры, иначе Reset вернул бы саму правку.
            original = EditedVMTService.read_original_backup(edit_key)
            if original is None:
                original = self._extract_game_vmt_content(weapon_key, material_name)
            self.open_vmt_editor(edited_vmt_path, edit_key, display_name,
                                 original_content=original)
            return

        # ── Нет сохранённого — нужен путь к TF2 для извлечения ──────────── #
        settings     = self.settings_panel.get_settings()
        tf2_root_dir = settings.get('tf2_game_folder', '')

        if not tf2_root_dir:
            ErrorHandler.show_warning(
                self,
                self.t.get('tf2_path_not_specified', 'TF2 path not specified in settings'),
                self.t['error'],
            )
            return

        # ── Извлекаем VMT из VPK ─────────────────────────────────────────── #
        from src.services import vmt_source_service
        vmt_path = vmt_source_service.extract_original(
            self.mode, weapon_key, tf2_root_dir, material_name, self.language)

        if not vmt_path:
            ErrorHandler.show_warning(
                self,
                self.t.get(
                    'vmt_extract_failed',
                    'Could not extract original VMT for: {key}\nCheck TF2 path in settings.',
                ).format(key=display_name),
                self.t['error'],
            )
            return

        self.open_vmt_editor(vmt_path, edit_key, display_name)


    def _extract_game_vmt_content(self, weapon_key: str,
                                  material_name: Optional[str] = None) -> Optional[str]:
        """Игровой оригинал VMT как СОДЕРЖИМОЕ — для «вернуть как в игре»."""
        from src.services import vmt_source_service

        tf2_root_dir = self.settings_panel.get_settings().get('tf2_game_folder', '')
        if not tf2_root_dir:
            return None
        return vmt_source_service.original_content(
            self.mode, weapon_key, tf2_root_dir, material_name, self.language)

    def extract_original_vmt_from_game(self, weapon_key: str, tf2_root_dir: str,
                                       material_name: Optional[str] = None) -> Optional[str]:
        """Путь к извлечённому оригиналу VMT (правило — в vmt_source_service)."""
        from src.services import vmt_source_service
        return vmt_source_service.extract_weapon_vmt(
            weapon_key, tf2_root_dir, material_name, self.language)

    def open_vmt_editor(self, path: str, edit_key: str = "", display_name: str = "",
                        original_content: Optional[str] = None) -> None:
        """Открывает редактор VMT файла.

        edit_key — ключ EditedVMTService (имя материала/текстуры, а не оружия).
        original_content — «чистый» игровой оригинал для кнопки сброса, когда
        открываем уже сохранённую правку (иначе оригинал = открытый файл)."""
        dialog = VMTEditorDialog(self, path, edit_key, self.t, display_name=display_name,
                                 original_content=original_content, language=self.language)
        dialog.exec()
