"""
Сцена «На персонаже» для надеваемого оружия (ботинки, щит, парашют)

Сцену собирает тот же воркер, что у шапок (HatScenePreviewWorker): модель
класса, стойка слота, предмет сливается с костями персонажа по именам.
Здесь - только то, чем оружие отличается от шапки: чей предмет (класс из
режима, у всеклассового - все девять), где лежит модель (пути-кандидаты, как у
превью), что он прячет у персонажа и своя ли у него модель
"""

from __future__ import annotations

from typing import Any, Dict


def scene_args(host, tf2_root: str) -> Dict[str, Any]:
    """Аргументы `PreviewController.load_wear` для надеваемого оружия
    либо {'error': …}"""
    from src.data import viewmodel_anims
    from src.domain.preview.model_key import model_key_for
    from src.services.extract_model_service import ExtractModelService

    mode = getattr(host, '_mode', '')
    key = model_key_for(mode)
    if not key:
        return {'error': 'На персонаже показывается только предмет из каталога'}

    head = (mode or '').split('_', 1)[0].lower()
    if head == viewmodel_anims.ALL_CLASS_MODE:
        classes = list(viewmodel_anims.CLASS_MODEL_STEM)
    else:
        cls = viewmodel_anims.class_from_mode(mode)
        classes = [cls] if cls else []
    if not classes:
        return {'error': 'Не удалось понять, чей это предмет'}

    candidates = ExtractModelService._build_paths_to_try(mode, key, tf2_root)
    info = viewmodel_anims.anim_info(key, tf2_root)
    preview = host.preview
    return {
        'hat_models': {c: list(candidates) for c in classes},
        'weapon_key': key,
        'hidden_bodygroups': dict(info.hides) if info else {},
        # Своя модель - та же, что уйдёт в мод (как у вида от первого лица)
        'custom_smd': preview.custom_smd_path or '',
        'custom_keep': bool(preview.custom_keep_materials),
    }
