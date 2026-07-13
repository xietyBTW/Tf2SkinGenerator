"""
Миксин главного окна: VMT-редактор и извлечение оригинальных VMT.

Разрешение цели редактирования по текущему режиму, извлечение исходного
VMT из игровых VPK / из QC / для шапок и открытие редактора VMT. Вынесены
из ``MainWindow`` без изменения тел; состояние и виджеты остаются на окне
и разрешаются через ``self``.
"""

import os
from typing import Optional

from src.data.weapons import weapon_key_from_mode
from src.shared.logging_config import get_logger
from src.ui.error_handler import ErrorHandler
from src.ui.vmt_editor import VMTEditorDialog

logger = get_logger(__name__)


class MainWindowVmtMixin:
    """VMT-редактор и извлечение оригинальных VMT (см. модуль)."""

    def _resolve_vmt_target(self):
        """(weapon_key, display_name) для VMT-редактора по текущему режиму, либо None
        (с предупреждением), если режим не поддерживается."""
        from src.data.player_hands import HAND_MODE_KEYS, HAND_MODES
        from src.data.player_characters import PLAYER_BODY_MODE_KEYS, PLAYER_CHARACTERS
        if self.mode == "hat":
            hat_mdl = getattr(self, '_hat_mdl_path', None)
            if not hat_mdl:
                ErrorHandler.show_warning(
                    self,
                    self.t.get('select_weapon_error', 'Select a hat first'),
                    self.t['error'],
                )
                return None
            # Ключ для кэша — нормализованный MDL путь
            weapon_key   = hat_mdl.replace("\\", "/").lower()
            display_name = getattr(self, '_hat_display_name', weapon_key)

        elif self.mode in HAND_MODE_KEYS:
            arm_model = HAND_MODES.get(self.mode, {}).get("arm_model", "")
            if not arm_model:
                ErrorHandler.show_warning(
                    self,
                    self.t.get('vmt_editor_not_available', 'VMT editor is not available for this mode.'),
                    self.t['error'],
                )
                return None
            weapon_key   = arm_model
            display_name = arm_model

        elif self.mode in PLAYER_BODY_MODE_KEYS:
            mdl_key = PLAYER_CHARACTERS.get(self.mode, {}).get("mdl_key", "")
            if not mdl_key:
                ErrorHandler.show_warning(
                    self,
                    self.t.get('vmt_editor_not_available', 'VMT editor is not available for this mode.'),
                    self.t['error'],
                )
                return None
            weapon_key   = mdl_key
            display_name = mdl_key

        else:
            # Обычное оружие: mode = "scout_c_scattergun" → "c_scattergun"
            weapon_key   = weapon_key_from_mode(self.mode)
            display_name = weapon_key
        return weapon_key, display_name

    def _open_vmt_for_material(self, material: str = "") -> None:
        """
        Открывает VMT-редактор для КОНКРЕТНОГО материала карточки (пер-текстурно).
        material='' → главный материал текущего превью.
        """
        if not hasattr(self, 'mode') or not self.mode:
            ErrorHandler.show_warning(self, self.t.get('select_weapon_error', 'Select a weapon first'), self.t['error'])
            return
        from src.data.weapons import SPECIAL_MODES
        if self.mode in set(SPECIAL_MODES.values()) | {"custom"}:
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
        if self.mode == "hat":
            vmt_path = self._extract_hat_vmt_from_game(weapon_key, tf2_root_dir, material_name)
        else:
            vmt_path = self.extract_original_vmt_from_game(weapon_key, tf2_root_dir, material_name)

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
        """Извлекает игровой оригинал VMT и возвращает его СОДЕРЖИМОЕ (не путь).

        Нужно для бэкапа «Reset to game original», когда открываем уже сохранённую
        правку. None — если путь к TF2 не задан или оригинал не найден."""
        settings     = self.settings_panel.get_settings()
        tf2_root_dir = settings.get('tf2_game_folder', '')
        if not tf2_root_dir:
            return None
        if self.mode == "hat":
            path = self._extract_hat_vmt_from_game(weapon_key, tf2_root_dir, material_name)
        else:
            path = self.extract_original_vmt_from_game(weapon_key, tf2_root_dir, material_name)
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    return f.read()
            except OSError:
                return None
        return None

    def _extract_hat_vmt_from_game(self, hat_mdl: str, tf2_root_dir: str,
                                   material_name: Optional[str] = None) -> Optional[str]:
        """
        Извлекает VMT для шапки через $cdmaterials из кэшированного QC
        (тот же общий путь, что и у оружия — _extract_vmt_from_qc).
        """
        from src.services import decompile_cache

        qc_path = decompile_cache.find_cached_qc_for_weapon(hat_mdl)
        if not qc_path:
            # Нет кэша — пробуем без декомпиляции (быстро, не всегда работает)
            return None

        from src.services import qc_skin_parser
        # Материалы skin0, а если их нет — стебель имени модели (минус класс).
        _rows = qc_skin_parser.parse_texturegroup_rows(qc_path)
        skin0_textures = list(_rows[0]) if _rows else []
        if not skin0_textures:
            import re as _re
            stem = os.path.splitext(os.path.basename(hat_mdl))[0]
            stem = _re.sub(
                r'_(heavy|scout|soldier|pyro|demoman|engineer|medic|sniper|spy)$',
                '', stem, flags=_re.IGNORECASE,
            )
            skin0_textures = [stem]

        # Конкретный материал (пер-карточная правка) — ищем именно его; если у
        # добавленной текстуры нет своего VMT в игре, наследуем от главного
        # материала skin0 (правило #2).
        if material_name:
            fallback = [m for m in skin0_textures if m.lower() != material_name.lower()]
            mat_names = [material_name] + fallback
        else:
            mat_names = skin0_textures

        return self._extract_vmt_from_qc(qc_path, tf2_root_dir, mat_names)
    
    def extract_original_vmt_from_game(self, weapon_key: str, tf2_root_dir: str,
                                       material_name: Optional[str] = None) -> Optional[str]:
        """
        Извлекает оригинальный VMT оружия через $cdmaterials из QC (как у шапок).

        Папки материалов берём из декомпилированного QC модели (авторитетно), а не
        угадываем хардкодом. QC обычно уже в кэше после 3D-превью; если нет —
        декомпилируем модель на месте тем же сервисом, что и превью.

        Args:
            weapon_key:    ключ оружия (например c_scattergun).
            tf2_root_dir:  корень TF2.
            material_name: конкретный материал (пер-карточно) или None → skin0/ключ.

        Returns:
            Путь к извлечённому VMT или None.
        """
        from src.services import decompile_cache, qc_skin_parser

        qc_path = decompile_cache.find_cached_qc_for_weapon(weapon_key)
        if not qc_path:
            # Нет кэша — декомпилируем сейчас (класс в mode не важен).
            try:
                import glob as _glob
                from src.services.extract_model_service import ExtractModelService
                ok, _msg, _cancel, data = (
                    ExtractModelService.prepare_decompiled_model_files_with_progress(
                        tf2_root_dir, f"scout_{weapon_key}", weapon_key, language=self.language,
                    )
                )
                if ok and data and data.get("decompile_dir"):
                    qcs = _glob.glob(os.path.join(data["decompile_dir"], "*.qc"))
                    qc_path = qcs[0] if qcs else None
            except Exception as e:
                logger.debug(f"VMT: декомпиляция для {weapon_key} не удалась: {e}")
                qc_path = None
        if not qc_path:
            return None

        # Имя(имена) материала: конкретный (пер-карточно) или materials из skin0.
        rows = qc_skin_parser.parse_texturegroup_rows(qc_path)
        skin0 = list(rows[0]) if rows else []
        if material_name:
            # Специфичный материал первым; если у добавленной текстуры нет своего
            # VMT в игре — берём VMT главного материала (skin0) как основу
            # (правило #2: наследуем от основного оружия и правим).
            fallback = [m for m in skin0 if m.lower() != material_name.lower()]
            mat_names = [material_name] + fallback + ([weapon_key] if not skin0 else [])
        else:
            mat_names = skin0 or [weapon_key]
        return self._extract_vmt_from_qc(qc_path, tf2_root_dir, mat_names)

    def _extract_vmt_from_qc(self, qc_path: str, tf2_root_dir: str,
                             mat_names: list) -> Optional[str]:
        """Извлекает VMT через $cdmaterials из QC: папки материалов берём из самой
        модели (как делает игра), а не угадываем. Единый путь для оружия и шапок."""
        from src.services.tf2_paths import TF2Paths
        from src.services.game_vpk_reader import GameVpkReader
        from src.services import qc_skin_parser

        if not qc_path or not os.path.exists(qc_path):
            return None
        cdmaterials = qc_skin_parser.parse_cdmaterials(qc_path)
        if not cdmaterials or not mat_names:
            return None

        try:
            _, misc_vpk, _ = TF2Paths.resolve(tf2_root_dir)
        except Exception:
            misc_vpk = None
        textures_vpk = TF2Paths.resolve_textures_vpk(tf2_root_dir)

        # GameVpkReader берёт хэндлы из общего потоко-локального кэша: индекс
        # каждого VPK парсится один раз на поток, повторные открытия редактора
        # VMT мгновенны. Закрывать хэндлы нельзя — ими владеет кэш.
        vmt_content: Optional[str] = None
        vmt_filename: str = "material.vmt"
        with GameVpkReader([misc_vpk, textures_vpk]) as reader:
            if not reader.paks:
                return None
            for mat_name in mat_names:
                info = reader.find_vmt(cdmaterials, mat_name.lower())
                if info:
                    vmt_content = info[1]
                    vmt_filename = os.path.basename(info[0])
                    break
        if not vmt_content:
            return None

        temp_dir = os.path.join("tools", "temp_vmt_extract")
        os.makedirs(temp_dir, exist_ok=True)
        out_path = os.path.join(temp_dir, vmt_filename)
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(vmt_content)
            return out_path
        except OSError:
            return None

    def open_vmt_editor(self, path: str, edit_key: str = "", display_name: str = "",
                        original_content: Optional[str] = None) -> None:
        """Открывает редактор VMT файла.

        edit_key — ключ EditedVMTService (имя материала/текстуры, а не оружия).
        original_content — «чистый» игровой оригинал для кнопки сброса, когда
        открываем уже сохранённую правку (иначе оригинал = открытый файл)."""
        dialog = VMTEditorDialog(self, path, edit_key, self.t, display_name=display_name,
                                 original_content=original_content, language=self.language)
        dialog.exec()
