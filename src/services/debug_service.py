"""
Сервис для сохранения состояний отладки
"""

import os
import shutil


class DebugService:
    """Сервис для сохранения состояний на каждом этапе сборки в режиме отладки"""

    @staticmethod
    def save_extracted_stage(ctx, extracted_files: list) -> None:
        """Сохраняет состояние после извлечения MDL файлов."""
        if not hasattr(ctx, 'debug_stage1_extracted_dir') or not os.path.exists(ctx.debug_stage1_extracted_dir):
            return
        for file_path in extracted_files:
            if os.path.exists(file_path):
                rel_path = os.path.relpath(file_path, ctx.extract_dir)
                target_path = os.path.join(ctx.debug_stage1_extracted_dir, rel_path)
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                shutil.copy2(file_path, target_path)

    @staticmethod
    def save_decompiled_stage(ctx, decompile_dir: str) -> None:
        """Сохраняет состояние после декомпиляции."""
        DebugService._copy_dir_to_stage(ctx, 'debug_stage2_decompiled_dir', decompile_dir)

    @staticmethod
    def save_patched_stage(ctx, decompile_dir: str) -> None:
        """Сохраняет состояние после патчинга QC файла."""
        DebugService._copy_dir_to_stage(ctx, 'debug_stage3_patched_dir', decompile_dir)

    @staticmethod
    def save_compiled_stage(ctx, compile_dir: str) -> None:
        """Сохраняет состояние после компиляции."""
        DebugService._copy_dir_to_stage(ctx, 'debug_stage4_compiled_dir', compile_dir)

    # ── Внутренние хелперы ───────────────────────────────────────────────── #

    @staticmethod
    def _copy_dir_to_stage(ctx, stage_attr: str, source_dir: str) -> None:
        """
        Копирует содержимое source_dir в debug-директорию указанного этапа.

        Args:
            ctx:        Контекст сборки
            stage_attr: Имя атрибута контекста с путём debug-директории
                        (например, 'debug_stage2_decompiled_dir')
            source_dir: Директория-источник для копирования
        """
        stage_dir = getattr(ctx, stage_attr, None)
        if not stage_dir or not os.path.exists(stage_dir):
            return
        if not os.path.exists(source_dir):
            return

        for root, _, files in os.walk(source_dir):
            for file_name in files:
                src_path = os.path.join(root, file_name)
                rel_path = os.path.relpath(src_path, source_dir)
                target_path = os.path.join(stage_dir, rel_path)
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                shutil.copy2(src_path, target_path)
