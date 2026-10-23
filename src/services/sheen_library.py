"""
Библиотека узоров блеска: свои узоры (work/sheen_patterns/<id>.json) и
готовые шаблоны конструктора под одним видом id

Конструктор (sheen_builder) рисует кадры по описанию узора, здесь - где
узоры лежат, как их найти по id из VMT и чем отличить одну версию узора от
другой (`content_hash` - для пути маски в моде)
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
from pathlib import Path
from typing import List, Optional

from src.services.sheen_builder import (
    PRESETS, resolve_image, clean_spec, library_dir,
)

#: Свой узор: u + 8 hex
ID_RE = re.compile(r'^u[0-9a-f]{8}$')
#: Готовый узор (шаблон конструктора) в эффекте: `p_<ключ PRESETS>`
PRESET_PREFIX = "p_"


def list_patterns() -> List[dict]:
    folder = library_dir()
    out = []
    for path in sorted(folder.glob("u*.json")) if folder.is_dir() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if ID_RE.match(path.stem):
            out.append({"id": path.stem, "name": str(data.get("name") or path.stem),
                        "length": float(data.get("length") or 2.5)})
    return sorted(out, key=lambda p: p["name"].lower())


def is_pattern(pattern_id: str) -> bool:
    """Узор конструктора: свой (u + 8 hex) или готовый шаблон (p_<ключ>)"""
    text = str(pattern_id or "")
    return bool(ID_RE.match(text)) or (text.startswith(PRESET_PREFIX)
                                       and text[len(PRESET_PREFIX):] in PRESETS)


def load(pattern_id: str, deleted: bool = False) -> Optional[dict]:
    """Узор по id. `deleted` - искать и среди удалённых: сборка работы, где
    узор ещё стоит, не должна падать из-за того, что его убрали из списка.
    Шаблон (`p_<ключ>`) - из PRESETS: готовые узоры эффекта рисует тот же код
    """
    text = str(pattern_id or "")
    if is_pattern(text) and text.startswith(PRESET_PREFIX):
        preset = PRESETS[text[len(PRESET_PREFIX):]]
        return {"id": text, "name": preset["label"][0], "length": 2.5,
                "spec": clean_spec(preset["spec"])}
    if not ID_RE.match(text):
        return None
    path = library_dir() / f"{pattern_id}.json"
    if deleted and not path.exists():
        path = library_dir() / "deleted" / f"{pattern_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    spec = clean_spec(data.get("spec"))
    for layer in spec["layers"]:
        path = resolve_image(layer.get("image", "")) if layer["type"] == "image" else None
        if path:
            layer["image"] = str(path)
    return {"id": pattern_id, "name": str(data.get("name") or pattern_id),
            "length": float(data.get("length") or 2.5), "spec": spec}


def save(pattern_id: Optional[str], name: str, spec: dict, length: float) -> str:
    """Сохраняет узор, картинки слоёв копируются в библиотеку (по
    содержимому), чтобы узор не зависел от временных файлов"""
    folder = library_dir()
    (folder / "images").mkdir(parents=True, exist_ok=True)
    if not ID_RE.match(str(pattern_id or "")):
        pattern_id = "u" + secrets.token_hex(4)
    from PIL import Image

    spec = clean_spec(spec)
    for layer in spec["layers"]:
        src = resolve_image(layer.get("image", "")) if layer["type"] == "image" else None
        if src:
            try:
                with Image.open(src) as img:
                    img.load()
            except Exception as exc:                       # noqa: BLE001
                raise ValueError(f"картинка {src.name} не читается: {exc}") from exc
        if src and src.is_absolute() and folder not in src.parents:
            digest = hashlib.sha1(src.read_bytes()).hexdigest()[:16]
            target = folder / "images" / f"{digest}{src.suffix.lower() or '.png'}"
            if not target.exists():
                shutil.copyfile(src, target)
            layer["image"] = f"images/{target.name}"
        elif src and folder in src.parents:
            layer["image"] = src.relative_to(folder).as_posix()
    data = {"name": (name or "").strip()[:60] or "Мой узор", "length": float(length or 2.5),
            "spec": spec}
    (folder / f"{pattern_id}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                               encoding="utf-8")
    return pattern_id


def delete(pattern_id: str) -> bool:
    if not ID_RE.match(str(pattern_id or "")):
        return False
    path = library_dir() / f"{pattern_id}.json"
    if not path.exists():
        return False
    trash = library_dir() / "deleted"
    trash.mkdir(parents=True, exist_ok=True)
    path.replace(trash / path.name)
    return True


def content_hash(pattern_id: str) -> str:
    """Отпечаток узора: в моде маска лежит под ним, чтобы моды, собранные до
    и после правки узора, не делили один путь с разным содержимым"""
    data = load(pattern_id, deleted=True)
    if data is None:
        return ""
    blob = json.dumps(data["spec"], sort_keys=True).encode()
    for layer in data["spec"]["layers"]:
        path = resolve_image(layer.get("image", "")) if layer["type"] == "image" else None
        if path:
            blob += path.read_bytes()
    return hashlib.sha1(blob).hexdigest()[:8]
