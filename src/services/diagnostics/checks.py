"""Проверки диагностики — чистые функции (InspectedMod, lang) → List[Finding].

Проверки содержат только ЛОГИКУ и параметры; пользовательский текст берётся из
messages.py по коду находки (локализуемо). Добавить проверку = функция + запись в
messages + строка в runner.CHECKS. Порог серьёзности: «почти наверняка сломано» →
ERROR, «возможно/если не из игры» → WARNING.
"""

from __future__ import annotations

from typing import List

from src.services.diagnostics.context import InspectedMod
from src.services.diagnostics.messages import render
from src.services.diagnostics.models import Finding, Severity
from src.services.diagnostics.vtf_reader import is_power_of_two

# Версии .mdl, совместимые с TF2 (studiomdl TF2 компилирует в 48/49).
_TF2_MDL_VERSIONS = (48, 49)


def _finding(severity: Severity, code: str, lang: str, location: str = "",
             **params) -> Finding:
    """Собирает Finding: текст — из messages по коду и языку, логика — снаружи."""
    title, detail, fix = render(code, lang, **params)
    return Finding(severity, code, title, detail, fix, location)


def check_structure(mod: InspectedMod, lang: str = "en") -> List[Finding]:
    """Корневая структура VPK: есть materials/models и нет лишней папки-обёртки."""
    if not mod.all_rel:
        return [_finding(Severity.ERROR, "structure.empty", lang)]

    tops = mod.top_dirs()
    has_root_content = bool(tops & {"materials", "models", "particles", "sound", "scripts"})
    nested = any(("/materials/" in rel or "/models/" in rel) for rel in mod.all_rel)

    if not has_root_content and nested:
        return [_finding(Severity.ERROR, "structure.wrapper_folder", lang,
                         location=(sorted(tops)[0] if tops else ""))]
    if not has_root_content:
        return [_finding(Severity.WARNING, "structure.no_content", lang)]
    return []


def check_vmt_syntax(mod: InspectedMod, lang: str = "en") -> List[Finding]:
    """Синтаксис каждого VMT (битый VMT → материал не грузится → фиолет)."""
    from src.services.vmt_service import VMTService

    out: List[Finding] = []
    for vmt in mod.vmts:
        ok, msg, line = VMTService.validate_vmt_syntax(vmt.content)
        if not ok:
            loc = (f" (строка {line})" if lang == "ru" else f" (line {line})") if line else ""
            out.append(_finding(Severity.ERROR, "vmt.syntax", lang,
                                location=vmt.rel_path, msg=msg, loc=loc))
    return out


def check_vmt_textures_exist(mod: InspectedMod, lang: str = "en") -> List[Finding]:
    """$basetexture/$bumpmap/… ссылаются на VTF, которого нет в моде → фиолет.
    Одну и ту же недостающую текстуру сообщаем один раз."""
    out: List[Finding] = []
    seen: set = set()
    for vmt in mod.vmts:
        for param, tex_rel in vmt.texture_refs().items():
            if mod.has_vtf(tex_rel) or tex_rel in seen:
                continue
            seen.add(tex_rel)
            out.append(_finding(Severity.WARNING, "vmt.missing_texture", lang,
                                location=vmt.rel_path, param=param, tex=tex_rel))
    return out


def check_vtf_dimensions(mod: InspectedMod, lang: str = "en") -> List[Finding]:
    """VTF со сторонами не степень двойки — Source читает их некорректно."""
    out: List[Finding] = []
    for key, (w, h) in sorted(mod.vtf_sizes.items()):
        if not (is_power_of_two(w) and is_power_of_two(h)):
            out.append(_finding(Severity.WARNING, "vtf.not_power_of_two", lang,
                                location=key + ".vtf", w=w, h=h))
    return out


def check_vtf_corrupt(mod: InspectedMod, lang: str = "en") -> List[Finding]:
    """VTF с непрочитанным заголовком — битый/пустой файл (материал не загрузится)."""
    return [
        _finding(Severity.WARNING, "vtf.corrupt", lang, location=key + ".vtf")
        for key in sorted(mod.bad_vtf)
    ]


def check_models(mod: InspectedMod, lang: str = "en") -> List[Finding]:
    """Модели: версия под TF2, полнота набора файлов, наличие нужных материалов."""
    out: List[Finding] = []
    vmt_paths = mod.vmt_rel_paths()
    versions = "/".join(map(str, _TF2_MDL_VERSIONS))

    for m in mod.mdls:
        if m.header.valid and (not m.has_vvd or not m.has_vtx):
            missing = ", ".join(
                x for x, ok in ((".vvd", m.has_vvd), (".vtx", m.has_vtx)) if not ok
            )
            out.append(_finding(Severity.ERROR, "model.incomplete", lang,
                                location=m.rel_path, missing=missing))

        if m.header.valid and m.header.version and m.header.version not in _TF2_MDL_VERSIONS:
            out.append(_finding(Severity.WARNING, "model.version", lang,
                                location=m.rel_path, version=m.header.version,
                                versions=versions))

        for mat in m.header.material_names:
            if _material_resolved(mat, m.header.cdmaterials, vmt_paths):
                continue
            cds = ", ".join(m.header.cdmaterials) if m.header.cdmaterials else "—"
            out.append(_finding(Severity.WARNING, "model.missing_material", lang,
                                location=m.rel_path, mat=mat, cds=cds))
    return out


def check_conflicts(mod: InspectedMod, lang: str = "en") -> List[Finding]:
    """Пути мода, которые также есть в других включённых модах tf/custom."""
    if not mod.external_paths:
        return []
    conflicts = sorted(
        p for p in mod.all_rel
        if p in mod.external_paths and (p.startswith("materials/") or p.startswith("models/"))
    )
    if not conflicts:
        return []
    sample_list = conflicts[:6]
    extra = len(conflicts) - len(sample_list)
    more = ""
    if extra > 0:
        more = (f"\n… и ещё {extra}" if lang == "ru" else f"\n… and {extra} more")
    return [_finding(Severity.WARNING, "conflict.overlap", lang,
                     n=len(conflicts), sample="\n• ".join(sample_list), more=more)]


def check_summary(mod: InspectedMod, lang: str = "en") -> List[Finding]:
    """Справочная сводка (INFO) — всегда, чтобы UI показал объём осмотра."""
    return [_finding(Severity.INFO, "summary", lang,
                     nv=len(mod.vmts), nt=len(mod.vtf_rel), nm=len(mod.mdls))]


# ── Внутреннее ──────────────────────────────────────────────────────────── #

def _material_resolved(mat: str, cdmaterials: List[str], vmt_paths) -> bool:
    """True, если для материала `mat` есть VMT по одному из путей $cdmaterials."""
    mat_l = mat.replace("\\", "/").lower().strip("/")
    for cd in (cdmaterials or []):
        cd_l = cd.replace("\\", "/").lower().strip("/")
        expected = f"materials/{cd_l}/{mat_l}.vmt" if cd_l else f"materials/{mat_l}.vmt"
        if expected in vmt_paths:
            return True
    return f"materials/{mat_l}.vmt" in vmt_paths
