"""Локализуемые тексты находок диагностики.

Проверки (checks.py) содержат ЛОГИКУ и собирают параметры, а весь пользовательский
ТЕКСТ — здесь, по стабильному коду находки. Так текст переводится независимо от
логики и легко расширяется. Плейсхолдеры — в стиле str.format ({name}); литерал
«$» перед {param} остаётся как есть.
"""

from __future__ import annotations

from typing import Dict, Tuple

# code → lang → {title, detail, fix}
MESSAGES: Dict[str, Dict[str, Dict[str, str]]] = {
    "structure.empty": {
        "ru": {"title": "Мод пустой", "detail": "В VPK не найдено файлов."},
        "en": {"title": "Empty mod", "detail": "No files found in the VPK."},
    },
    "structure.wrapper_folder": {
        "ru": {"title": "Лишняя папка-обёртка",
               "detail": "materials/ и models/ должны лежать в КОРНЕ VPK, а не "
                         "внутри ещё одной папки.",
               "fix": "Переупакуйте так, чтобы materials/ и models/ были в корне."},
        "en": {"title": "Extra wrapper folder",
               "detail": "materials/ and models/ must be at the ROOT of the VPK, "
                         "not inside another folder.",
               "fix": "Repack so materials/ and models/ are at the root."},
    },
    "structure.no_content": {
        "ru": {"title": "Нет materials/ и models/ в корне",
               "detail": "Мод ничего не переопределяет — обычно нужна хотя бы одна "
                         "из папок materials/ или models/."},
        "en": {"title": "No materials/ or models/ at root",
               "detail": "The mod overrides nothing — usually at least one of "
                         "materials/ or models/ is expected."},
    },
    "vmt.syntax": {
        "ru": {"title": "Ошибка синтаксиса VMT",
               "detail": "{msg}{loc}. Материал с битым VMT не загрузится (фиолет).",
               "fix": "Исправьте VMT в редакторе (незакрытые скобки/кавычки)."},
        "en": {"title": "VMT syntax error",
               "detail": "{msg}{loc}. A material with a broken VMT won't load (purple).",
               "fix": "Fix the VMT in the editor (unclosed braces/quotes)."},
    },
    "vmt.missing_texture": {
        "ru": {"title": "Нет текстуры для ${param}",
               "detail": "VMT ссылается на «{tex}.vtf», но такого файла в моде нет. "
                         "Если текстура не берётся из игры — будет фиолетовая шашка.",
               "fix": "Добавьте {tex}.vtf в мод или поправьте путь ${param} в VMT."},
        "en": {"title": "Missing texture for ${param}",
               "detail": "The VMT references \"{tex}.vtf\", but that file isn't in the "
                         "mod. If it isn't provided by the game, you'll get a purple "
                         "checkerboard.",
               "fix": "Add {tex}.vtf to the mod or fix the ${param} path in the VMT."},
    },
    "vtf.not_power_of_two": {
        "ru": {"title": "Размер VTF не степень двойки",
               "detail": "{w}×{h}. Source ожидает степени двойки (512×512, 1024×1024…); "
                         "иначе возможны артефакты/незагрузка.",
               "fix": "Пересохраните текстуру с размерами-степенями двойки."},
        "en": {"title": "VTF size not a power of two",
               "detail": "{w}×{h}. Source expects powers of two (512×512, 1024×1024…); "
                         "otherwise you may get artifacts or a load failure.",
               "fix": "Re-export the texture with power-of-two dimensions."},
    },
    "vtf.corrupt": {
        "ru": {"title": "Битый VTF",
               "detail": "Не удалось прочитать заголовок VTF — файл повреждён или пустой.",
               "fix": "Пересохраните текстуру заново в VTF."},
        "en": {"title": "Corrupt VTF",
               "detail": "Couldn't read the VTF header — the file is damaged or empty.",
               "fix": "Re-export the texture to VTF."},
    },
    "model.incomplete": {
        "ru": {"title": "Неполный набор модели",
               "detail": "Рядом с .mdl нет {missing} — модель будет невидимой.",
               "fix": "Добавьте недостающие файлы модели (.vvd и .vtx-варианты)."},
        "en": {"title": "Incomplete model set",
               "detail": "The .mdl is missing {missing} next to it — the model will be "
                         "invisible.",
               "fix": "Add the missing model files (.vvd and .vtx variants)."},
    },
    "model.version": {
        "ru": {"title": "Версия модели {version}",
               "detail": "TF2 обычно использует версии {versions}. Модель из другой "
                         "игры/версии может не загрузиться."},
        "en": {"title": "Model version {version}",
               "detail": "TF2 usually uses versions {versions}. A model from another "
                         "game/version may fail to load."},
    },
    "model.missing_material": {
        "ru": {"title": "Модель ждёт материал «{mat}»",
               "detail": "В .mdl объявлен материал «{mat}» по путям {cds}, но парного "
                         "VMT в моде нет. Если он не из игры — фиолет.",
               "fix": "Добавьте VMT для «{mat}» в одну из папок $cdmaterials."},
        "en": {"title": "Model expects material \"{mat}\"",
               "detail": "The .mdl declares material \"{mat}\" under {cds}, but there's "
                         "no matching VMT in the mod. If it isn't from the game — purple.",
               "fix": "Add a VMT for \"{mat}\" into one of the $cdmaterials folders."},
    },
    "conflict.overlap": {
        "ru": {"title": "Конфликт с другим модом ({n} путей)",
               "detail": "Также присутствуют в другом моде:\n• {sample}{more}",
               "fix": "Уберите старый мод из tf/custom — иначе результат зависит от "
                      "порядка загрузки VPK."},
        "en": {"title": "Conflict with another mod ({n} paths)",
               "detail": "Also present in another mod:\n• {sample}{more}",
               "fix": "Remove the old mod from tf/custom — otherwise the result depends "
                      "on VPK load order."},
    },
    "summary": {
        "ru": {"title": "Осмотрено: {nv} VMT, {nt} VTF, {nm} моделей"},
        "en": {"title": "Inspected: {nv} VMT, {nt} VTF, {nm} models"},
    },
}


def render(code: str, lang: str, **params) -> Tuple[str, str, str]:
    """Возвращает (title, detail, fix) для кода находки на нужном языке.
    Фолбэк: en, затем пусто. Плейсхолдеры подставляются из params (лишние
    игнорируются, недостающие оставляют шаблон как есть)."""
    entry = MESSAGES.get(code, {})
    loc = entry.get(lang) or entry.get("en") or {}

    def fmt(key: str) -> str:
        template = loc.get(key, "")
        try:
            return template.format(**params)
        except (KeyError, IndexError):
            return template

    return fmt("title"), fmt("detail"), fmt("fix")
