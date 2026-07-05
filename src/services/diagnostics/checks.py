"""Проверки диагностики — чистые функции InspectedMod → List[Finding].

Каждая проверка независима и тестируется изолированно. Добавить новую проверку =
написать функцию + внести её в CHECKS (runner.py). Порог серьёзности выбран так,
чтобы «почти наверняка сломано» → ERROR, «возможно/если не из игры» → WARNING.
"""

from __future__ import annotations

from typing import List

from src.services.diagnostics.context import InspectedMod
from src.services.diagnostics.models import Finding, Severity
from src.services.diagnostics.vtf_reader import is_power_of_two

# Версии .mdl, совместимые с TF2 (studiomdl TF2 компилирует в 48/49).
_TF2_MDL_VERSIONS = (48, 49)


def check_structure(mod: InspectedMod) -> List[Finding]:
    """Корневая структура VPK: есть materials/models и нет лишней папки-обёртки."""
    out: List[Finding] = []
    if not mod.all_rel:
        out.append(Finding(
            Severity.ERROR, "structure.empty", "Мод пустой",
            detail="В VPK не найдено файлов.",
        ))
        return out

    tops = mod.top_dirs()
    has_root_content = bool(tops & {"materials", "models", "particles", "sound", "scripts"})

    # Лишняя папка-обёртка: контент вложен на уровень глубже (…/materials, но
    # не materials/ в корне) — игра такой мод не увидит.
    nested = any(
        ("/materials/" in rel or "/models/" in rel) for rel in mod.all_rel
    )
    if not has_root_content and nested:
        out.append(Finding(
            Severity.ERROR, "structure.wrapper_folder",
            "Лишняя папка-обёртка", location=(sorted(tops)[0] if tops else ""),
            detail="materials/ и models/ должны лежать в КОРНЕ VPK, а не внутри "
                   "ещё одной папки.",
            fix_hint="Переупакуйте так, чтобы materials/ и models/ были в корне.",
        ))
    elif not has_root_content:
        out.append(Finding(
            Severity.WARNING, "structure.no_content",
            "Нет materials/ и models/ в корне",
            detail="Мод ничего не переопределяет — обычно нужна хотя бы одна из "
                   "папок materials/ или models/.",
        ))
    return out


def check_vmt_syntax(mod: InspectedMod) -> List[Finding]:
    """Синтаксис каждого VMT (битый VMT → материал не грузится → фиолет)."""
    from src.services.vmt_service import VMTService

    out: List[Finding] = []
    for vmt in mod.vmts:
        ok, msg, line = VMTService.validate_vmt_syntax(vmt.content)
        if not ok:
            loc = f" (строка {line})" if line else ""
            out.append(Finding(
                Severity.ERROR, "vmt.syntax", "Ошибка синтаксиса VMT",
                location=vmt.rel_path,
                detail=f"{msg}{loc}. Материал с битым VMT не загрузится (фиолет).",
                fix_hint="Исправьте VMT в редакторе (незакрытые скобки/кавычки).",
            ))
    return out


def check_vmt_textures_exist(mod: InspectedMod) -> List[Finding]:
    """$basetexture/$bumpmap/… ссылаются на VTF, которого нет в моде → фиолет.

    Одну и ту же недостающую текстуру (её могут делить несколько VMT) сообщаем
    один раз."""
    out: List[Finding] = []
    seen: set = set()
    for vmt in mod.vmts:
        for param, tex_rel in vmt.texture_refs().items():
            if mod.has_vtf(tex_rel) or tex_rel in seen:
                continue
            seen.add(tex_rel)
            out.append(Finding(
                    Severity.WARNING, "vmt.missing_texture",
                    f"Нет текстуры для ${param}",
                    location=vmt.rel_path,
                    detail=f"VMT ссылается на «{tex_rel}.vtf», но такого файла в "
                           f"моде нет. Если текстура не берётся из игры — будет "
                           f"фиолетовая шашка.",
                    fix_hint=f"Добавьте {tex_rel}.vtf в мод или поправьте путь "
                             f"${param} в VMT.",
                ))
    return out


def check_vtf_dimensions(mod: InspectedMod) -> List[Finding]:
    """VTF со сторонами не степень двойки — Source читает их некорректно."""
    out: List[Finding] = []
    for key, (w, h) in sorted(mod.vtf_sizes.items()):
        if not (is_power_of_two(w) and is_power_of_two(h)):
            out.append(Finding(
                Severity.WARNING, "vtf.not_power_of_two",
                "Размер VTF не степень двойки",
                location=key + ".vtf",
                detail=f"{w}×{h}. Source ожидает степени двойки (512×512, "
                       f"1024×1024…); иначе возможны артефакты/незагрузка.",
                fix_hint="Пересохраните текстуру с размерами-степенями двойки.",
            ))
    return out


def check_models(mod: InspectedMod) -> List[Finding]:
    """Модели: версия под TF2, полнота набора файлов, наличие нужных материалов."""
    out: List[Finding] = []
    vmt_paths = mod.vmt_rel_paths()

    for m in mod.mdls:
        # Полнота набора — без .vvd/.vtx модель невидима.
        if m.header.valid and (not m.has_vvd or not m.has_vtx):
            missing = ", ".join(
                x for x, ok in ((".vvd", m.has_vvd), (".vtx", m.has_vtx)) if not ok
            )
            out.append(Finding(
                Severity.ERROR, "model.incomplete", "Неполный набор модели",
                location=m.rel_path,
                detail=f"Рядом с .mdl нет {missing} — модель будет невидимой.",
                fix_hint="Добавьте недостающие файлы модели (.vvd и .vtx-варианты).",
            ))

        # Версия .mdl.
        if m.header.valid and m.header.version and m.header.version not in _TF2_MDL_VERSIONS:
            out.append(Finding(
                Severity.WARNING, "model.version",
                f"Версия модели {m.header.version}",
                location=m.rel_path,
                detail=f"TF2 обычно использует версии {'/'.join(map(str, _TF2_MDL_VERSIONS))}. "
                       f"Модель из другой игры/версии может не загрузиться.",
            ))

        # Модель ждёт материалы X по путям $cdmaterials — есть ли VMT?
        for mat in m.header.material_names:
            if _material_resolved(mat, m.header.cdmaterials, vmt_paths):
                continue
            out.append(Finding(
                Severity.WARNING, "model.missing_material",
                f"Модель ждёт материал «{mat}»",
                location=m.rel_path,
                detail=f"В .mdl объявлен материал «{mat}» по путям "
                       f"{m.header.cdmaterials or ['<нет $cdmaterials>']}, но парного "
                       f"VMT в моде нет. Если он не из игры — фиолет.",
                fix_hint=f"Добавьте VMT для «{mat}» в одну из папок $cdmaterials.",
            ))
    return out


def _material_resolved(mat: str, cdmaterials: List[str], vmt_paths) -> bool:
    """True, если для материала `mat` есть VMT по одному из путей $cdmaterials."""
    mat_l = mat.replace("\\", "/").lower().strip("/")
    for cd in (cdmaterials or []):
        cd_l = cd.replace("\\", "/").lower().strip("/")
        expected = f"materials/{cd_l}/{mat_l}.vmt" if cd_l else f"materials/{mat_l}.vmt"
        if expected in vmt_paths:
            return True
    # Материал мог быть задан полным путём (редко) — пробуем без cdmaterials.
    return f"materials/{mat_l}.vmt" in vmt_paths


def check_vtf_corrupt(mod: InspectedMod) -> List[Finding]:
    """VTF с непрочитанным заголовком — битый/пустой файл (материал не загрузится)."""
    return [
        Finding(
            Severity.WARNING, "vtf.corrupt", "Битый VTF",
            location=key + ".vtf",
            detail="Не удалось прочитать заголовок VTF — файл повреждён или пустой.",
            fix_hint="Пересохраните текстуру заново в VTF.",
        )
        for key in sorted(mod.bad_vtf)
    ]


def check_conflicts(mod: InspectedMod) -> List[Finding]:
    """Пути мода, которые ТАКЖЕ есть в других включённых модах tf/custom — VPK
    грузятся по алфавиту, поэтому «побеждает» один, и оба могут глючить."""
    if not mod.external_paths:
        return []
    conflicts = sorted(
        p for p in mod.all_rel
        if p in mod.external_paths and (p.startswith("materials/") or p.startswith("models/"))
    )
    if not conflicts:
        return []
    sample = conflicts[:6]
    more = len(conflicts) - len(sample)
    detail = "Также присутствуют в другом моде:\n• " + "\n• ".join(sample)
    if more > 0:
        detail += f"\n… и ещё {more}"
    return [Finding(
        Severity.WARNING, "conflict.overlap",
        f"Конфликт с другим модом ({len(conflicts)} путей)",
        detail=detail,
        fix_hint="Уберите старый мод из tf/custom — иначе результат зависит от "
                 "порядка загрузки VPK.",
    )]


def check_summary(mod: InspectedMod) -> List[Finding]:
    """Справочная сводка (INFO) — всегда, чтобы UI показал объём осмотра."""
    return [Finding(
        Severity.INFO, "summary",
        f"Осмотрено: {len(mod.vmts)} VMT, {len(mod.vtf_rel)} VTF, "
        f"{len(mod.mdls)} моделей",
    )]
