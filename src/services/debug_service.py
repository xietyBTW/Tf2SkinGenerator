"""
Сервис для сохранения состояний отладки
"""

import os
import shutil
from typing import Optional


class DebugService:
    """Сервис для сохранения состояний на каждом этапе сборки в режиме отладки"""
    
    @staticmethod
    def save_extracted_stage(ctx, extracted_files: list) -> None:
        """
        Сохраняет состояние после извлечения MDL файлов
        
        Args:
            ctx: Контекст сборки
            extracted_files: Список извлеченных файлов
        """
        if not hasattr(ctx, 'debug_stage1_extracted_dir') or not os.path.exists(ctx.debug_stage1_extracted_dir):
            return
        
        # Копируем все извлеченные файлы
        for file_path in extracted_files:
            if os.path.exists(file_path):
                # Сохраняем структуру папок
                rel_path = os.path.relpath(file_path, ctx.extract_dir)
                target_path = os.path.join(ctx.debug_stage1_extracted_dir, rel_path)
                target_dir = os.path.dirname(target_path)
                os.makedirs(target_dir, exist_ok=True)
                shutil.copy2(file_path, target_path)
    
    @staticmethod
    def save_decompiled_stage(ctx, decompile_dir: str) -> None:
        """
        Сохраняет состояние после декомпиляции
        
        Args:
            ctx: Контекст сборки
            decompile_dir: Директория с декомпилированными файлами
        """
        if not hasattr(ctx, 'debug_stage2_decompiled_dir') or not os.path.exists(ctx.debug_stage2_decompiled_dir):
            return
        
        if not os.path.exists(decompile_dir):
            return
        
        # Копируем все файлы из директории декомпиляции
        for root, dirs, files in os.walk(decompile_dir):
            for file_name in files:
                src_path = os.path.join(root, file_name)
                rel_path = os.path.relpath(src_path, decompile_dir)
                target_path = os.path.join(ctx.debug_stage2_decompiled_dir, rel_path)
                target_dir = os.path.dirname(target_path)
                os.makedirs(target_dir, exist_ok=True)
                shutil.copy2(src_path, target_path)
    
    @staticmethod
    def save_patched_stage(ctx, decompile_dir: str) -> None:
        """
        Сохраняет состояние после редактирования (патчинга QC файла)
        
        Args:
            ctx: Контекст сборки
            decompile_dir: Директория с отредактированными файлами
        """
        if not hasattr(ctx, 'debug_stage3_patched_dir') or not os.path.exists(ctx.debug_stage3_patched_dir):
            return
        
        if not os.path.exists(decompile_dir):
            return
        
        # Копируем все файлы из директории декомпиляции (после патчинга)
        for root, dirs, files in os.walk(decompile_dir):
            for file_name in files:
                src_path = os.path.join(root, file_name)
                rel_path = os.path.relpath(src_path, decompile_dir)
                target_path = os.path.join(ctx.debug_stage3_patched_dir, rel_path)
                target_dir = os.path.dirname(target_path)
                os.makedirs(target_dir, exist_ok=True)
                shutil.copy2(src_path, target_path)
    
    @staticmethod
    def save_compiled_stage(ctx, compile_dir: str) -> None:
        """
        Сохраняет состояние после компиляции
        
        Args:
            ctx: Контекст сборки
            compile_dir: Директория со скомпилированными файлами
        """
        if not hasattr(ctx, 'debug_stage4_compiled_dir') or not os.path.exists(ctx.debug_stage4_compiled_dir):
            return
        
        if not os.path.exists(compile_dir):
            return
        
        # Копируем все файлы из директории компиляции
        for root, dirs, files in os.walk(compile_dir):
            for file_name in files:
                src_path = os.path.join(root, file_name)
                rel_path = os.path.relpath(src_path, compile_dir)
                target_path = os.path.join(ctx.debug_stage4_compiled_dir, rel_path)
                target_dir = os.path.dirname(target_path)
                os.makedirs(target_dir, exist_ok=True)
                shutil.copy2(src_path, target_path)

