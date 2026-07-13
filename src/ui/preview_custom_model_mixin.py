"""
Миксин панели превью: кастомная/заменяющая модель и правка QC.

Загрузка мод-VPK пользователя, замена модели, диалог правки QC и загрузка
кастомного SMD в превью (``_on_load_vpk_clicked`` / ``_on_replace_model_clicked``
/ ``_on_edit_qc_clicked`` / ``_load_custom_smd_file`` и связанные геттеры).
Вынесены из ``PreviewPanel`` без изменения тел; состояние и общие методы
остаются на панели и разрешаются через ``self``.
"""

import os
from typing import Optional

from PySide6.QtWidgets import QFileDialog

from src.shared.logging_config import get_logger
from src.ui.material_cards import editable_material_cards

logger = get_logger(__name__)


class PreviewCustomModelMixin:
    """Кастомная/заменяющая модель и правка QC (см. модуль)."""

    def _on_load_vpk_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.t.get('3d_select_vpk', 'Select VPK mod'),
            "",
            "VPK Files (*.vpk);;All Files (*)",
        )
        if not path:
            return
        self._loaded_vpk_mod_path = path
        self.vpk_mod_loaded.emit(path)
        self._start_vpk_mod_worker(path)

    # ═══════════════════════════════════════════════════════════════════════════
    # Custom SMD
    # ═══════════════════════════════════════════════════════════════════════════

    def _on_replace_model_clicked(self) -> None:
        """Кнопка «заменить модель»: выбрать свою модель и сразу показать её в 3D + карточки.
        Не требует предварительной загрузки оригинала: данные оригинала (кости/
        материалы) сборка тянет из игры сама. Замена включается автоматически —
        сборка видит загруженную модель через get_custom_smd_path().

        ВАЖНО: НЕ ставим self._custom_smd_mode — иначе кнопка-куб
        (_on_load_3d_clicked) начнёт грузить кастомную SMD вместо игровой модели.
        Эта кнопка полностью независима: грузит SMD напрямую, путь хранится в
        _custom_smd_path (его читает сборка)."""
        if not self._3d_available or not self._3d_widget:
            return
        if not self.is_3d_mode():
            self._switch_to_3d()
        self._load_custom_smd_via_dialog()

    def _ask_model_ready(self, mat_names: list) -> bool:
        """Спрашивает, готова ли модель (свои материалы) или это замена геометрии.

        Returns True — сохранять материалы пользователя (многотекстурная/готовая
        модель); False — заменить только геометрию, адаптировать под игровой
        материал (старое поведение для простых решей одной текстуры).
        """
        from PySide6.QtWidgets import QMessageBox
        from src.data.material_filter import filter_editable
        n_editable = len(filter_editable(mat_names or []))
        recommend_keep = n_editable > 1   # >1 материала → почти наверняка «готовая»

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle(self.t.get('model_ready_title', 'Model type'))
        box.setText(self.t.get(
            'model_ready_text',
            'Is this model already game-ready (its own materials, rigged to the TF2 skeleton)?'
        ))
        info = (
            'Yes — keep the model\'s own materials as-is (multi-texture / ready models).\n'
            'No — replace geometry only and use the game texture (single material).'
            if self._lang != 'ru' else
            'Да — сохранить материалы модели как есть (многотекстурные / готовые модели).\n'
            'Нет — заменить только геометрию и использовать игровую текстуру (один материал).'
        )
        box.setInformativeText(info)
        yes = box.addButton(
            self.t.get('model_ready_yes', 'Yes, keep materials'), QMessageBox.YesRole
        )
        no = box.addButton(
            self.t.get('model_ready_no', 'No, geometry only'), QMessageBox.NoRole
        )
        box.setDefaultButton(yes if recommend_keep else no)
        box.exec()
        keep = box.clickedButton() is yes
        logger.info(
            f"[CUSTOM MODEL] mat_names={mat_names} editable={n_editable} "
            f"→ keep_user_materials={keep}"
        )
        return keep

    def get_custom_keep_materials(self) -> bool:
        """Для сборки: сохранять ли материалы пользовательской модели."""
        return self._custom_keep_materials

    def get_custom_qc_text(self) -> Optional[str]:
        """Для сборки: отредактированный пользователем QC (None = авто)."""
        return self._custom_qc_text

    def _current_tg_block(self) -> str:
        """Текущий $texturegroup из стилей (или '' — группы нет)."""
        try:
            from src.services.model_build_service import ModelBuildService
            data = self.get_skin_build_data()
            if data:
                return ModelBuildService.generate_texturegroup_block(
                    data.get('mesh_materials', []), data.get('tg_overrides', {})
                )
        except Exception as exc:
            logger.debug(f"[QC EDIT] tg_block: {exc}")
        return ''

    def _on_edit_qc_clicked(self) -> None:
        """Открывает редактор ИСПРАВЛЕННОГО QC с замочками на важных блоках."""
        from src.services.model_build_service import ModelBuildService
        from src.services import decompile_cache
        from src.ui.qc_editor_dialog import QCEditorDialog

        tg_block = self._current_tg_block()
        if self._custom_qc_text:
            # Уже редактировали — показываем правки пользователя, но $texturegroup
            # синхронизируем с актуальными стилями (правки человека не теряются).
            qc_text = ModelBuildService.replace_texturegroup_in_text(
                self._custom_qc_text, tg_block
            )
        else:
            qc_path = decompile_cache.find_cached_qc_for_weapon(self._weapon_key)
            qc_text = ModelBuildService.make_corrected_qc(
                qc_path or '', self._weapon_key, tg_block
            )
        if not qc_text.strip():
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self,
                self.t.get('qc_edit_title', 'QC Editor'),
                'QC ещё не извлечён из игры. Подождите загрузку модели в 3D и попробуйте снова.'
                if self._lang == 'ru' else
                'QC not extracted yet. Wait for the 3D model to load and try again.',
            )
            return

        dlg = QCEditorDialog(qc_text=qc_text, lang=self._lang, parent=self)
        code = dlg.exec()
        if code == 2:        # «Сбросить к исходному»
            self._custom_qc_text = None
            logger.info("[QC EDIT] сброс к авто-QC")
        elif code:           # Сохранить
            self._custom_qc_text = dlg.get_text()
            logger.info(f"[QC EDIT] сохранён QC ({len(self._custom_qc_text)} символов)")

    def _load_custom_smd_via_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.t.get('3d_select_smd_title', 'Select SMD Model File'),
            "",
            "SMD Files (*.smd);;All Files (*)",
        )
        if path:
            self._load_custom_smd_file(path)

    def _load_custom_smd_file(self, smd_path: str, keep_materials: Optional[bool] = None) -> None:
        """Загружает кастомную SMD в превью. keep_materials != None → не спрашиваем
        диалог «готова/замена» (тихая перезагрузка при восстановлении стиля)."""
        if not self._3d_available or not self._3d_widget:
            return
        import tempfile
        from src.services.smd_to_obj_service import SmdToObjService

        self.btn_load_3d.setEnabled(False)
        self._3d_widget.show_loading(self.t.get('3d_converting_smd', 'Converting SMD...'))
        try:
            tmp_dir = tempfile.mkdtemp(prefix="tf2_smd_preview_")
            obj_path = os.path.join(tmp_dir, "model.obj")
            ok, mat_names = SmdToObjService.convert(smd_path, obj_path)
            if not ok or not os.path.exists(obj_path):
                self._3d_widget.show_error(self.t.get('3d_error_convert', 'SMD conversion error'))
                return

            # Запоминаем путь — чтобы сборка переиспользовала ту же модель,
            # а не просила выбрать SMD повторно.
            self._custom_smd_path = smd_path

            # Спрашиваем тип модели: «готова» (свои материалы) или «замена
            # геометрии» (игровой материал). По умолчанию рекомендуем по числу
            # материалов: >1 → почти наверняка модель со своими материалами.
            self._custom_keep_materials = (
                keep_materials if keep_materials is not None
                else self._ask_model_ready(mat_names or [])
            )
            self._reset_skin_state()
            # Сбрасываем командное состояние (RED/BLU/Australium) от ранее
            # загруженной ИГРОВОЙ модели — иначе её кнопки-«стили» и командная
            # текстура остаются поверх кастомной модели. Для geometry-only
            # фоновый QC-воркер при необходимости покажет команды заново.
            self._reset_team_vpk_state()

            if self._custom_keep_materials:
                # ── «Готовая» модель: карточки по материалам САМОГО SMD ──────
                # Имена из меша пользователя, служебные (глаза/sheen) отфильтрованы.
                self._3d_widget.load_model_files(obj_path, self.image_path or '')
                # Единый источник выбора карточек (как у игровых моделей).
                editable = [s.name for s in editable_material_cards(mat_names or [])]
                if len(editable) > 1:
                    self._set_material_slots(editable)
                elif editable:
                    self._material_names = editable
                    self._card_mode = False
                logger.info(f"[CUSTOM MODEL keep] материалы из SMD → карточки: {editable}")
                # Редактор QC доступен только для «готовой» модели.
                self._custom_qc_text = None
                if hasattr(self, 'btn_edit_qc'):
                    self.btn_edit_qc.setVisible(True)
                # Стили (skinfamilies) оригинала — для переопределения под свои текстуры.
                self._start_skin_detection()
            else:
                # ── «Только геометрия»: карточки из QC игровой модели ─────────
                # Показываем ГЕОМЕТРИЮ ПОЛЬЗОВАТЕЛЯ, но карточки/текстуры берём из
                # QC игровой модели (там всё сводится к игровым текстурам). Воркер
                # извлекает их в фоне, НЕ перезагружая геометрию на оригинальную.
                logger.info("[CUSTOM MODEL geometry-only] геометрия пользователя + карточки из QC")
                self._custom_qc_text = None
                if hasattr(self, 'btn_edit_qc'):
                    self.btn_edit_qc.setVisible(False)
                self._3d_widget.load_model_files(obj_path, self.image_path or '')
                if self._pending_3d_params:
                    self._start_qc_cards_worker()
        except Exception as exc:
            logger.error(f"Custom SMD load: {exc}", exc_info=True)
            if self._3d_widget:
                self._3d_widget.show_error(self.t.get('3d_error_load', 'Model load error'))
        finally:
            self.btn_load_3d.setEnabled(True)
