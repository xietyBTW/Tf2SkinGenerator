"""Справочник параметров для генерации пресетов (в том числе ИИ)"""

from typing import Any, Dict, List, Optional

from src.services.particle_editor.pcf_format import MODULE_GROUPS


#: Инструкция для ИИ-ассистента, вкладывается в справочник по выбору
#: пользователя. На английском: модели точнее следуют инструкциям на нём,
#: а пользователь всё равно пишет свои требования отдельным сообщением.
#: Пояснения справочника: файл открывает и человек, поэтому на языке
#: интерфейса. Задание для ИИ (_AI_INSTRUCTIONS) - всегда английское
_REFERENCE_TEXT = {
    "ru": {
        "about": "Справочник параметров частиц TF2. Соберите набор в "
                 "поле clipboard_format.example и вставьте его в "
                 "редактор через Ctrl+V (правый клик по дереву свойств "
                 "→ Вставить параметры).",
        "notes": [
            "Имена параметров и модулей писать точно как здесь.",
            "example - значение из реального эффекта игры, а не "
            "умолчание движка: это ориентир по смыслу и порядку величин.",
            "range - [минимум, максимум] этого параметра по всем "
            "эффектам игры: значения вне него почти наверняка ошибка "
            "порядка величины.",
            "Отсутствующий параметр не ошибка: движок берёт своё "
            "умолчание. Указывайте только то, что нужно менять.",
            "previewed=false - модуль работает в игре, но 3D-превью "
            "редактора его не симулирует.",
        ],
        "value_types": {
            "float": "число, например 1.5",
            "integer": "целое число",
            "bool": "true / false",
            "string": "строка, например \"effects\\\\crit.vmt\"",
            "vec3": "[x, y, z]",
            "color": "[r, g, b, a], каждое 0-255",
        },
        "clipboard": "Значение JSON, которое кладётся в буфер "
                     "обмена. attrs - параметры самой системы, "
                     "modules - модули по группам: список пар "
                     "[имя модуля, {параметры}]. full=true "
                     "означает полный набор - при вставке "
                     "редактор спросит, заменять ли существующие.",
    },
    "en": {
        "about": "TF2 particle parameter reference. Build a set in the "
                 "shape of clipboard_format.example and paste it into "
                 "the editor with Ctrl+V (right-click the property tree "
                 "→ Paste parameters).",
        "notes": [
            "Write parameter and module names exactly as they are here.",
            "example is a value from a real game effect, not the engine "
            "default: a guide to meaning and order of magnitude.",
            "range is [minimum, maximum] of this parameter across all "
            "game effects: a value outside it is almost surely off by "
            "an order of magnitude.",
            "A missing parameter is not an error: the engine uses its "
            "default. Only list what needs to change.",
            "previewed=false means the module works in game, but the "
            "editor's 3D preview does not simulate it.",
        ],
        "value_types": {
            "float": "number, e.g. 1.5",
            "integer": "whole number",
            "bool": "true / false",
            "string": "string, e.g. \"effects\\\\crit.vmt\"",
            "vec3": "[x, y, z]",
            "color": "[r, g, b, a], each 0-255",
        },
        "clipboard": "The JSON value put on the clipboard. attrs are "
                     "the system's own parameters, modules are modules "
                     "by group: a list of [module name, {parameters}] "
                     "pairs. full=true means a complete set: on paste "
                     "the editor asks whether to replace existing ones.",
    },
}


_AI_INSTRUCTIONS = [
    "You help build a Team Fortress 2 particle effect. The user sends "
    "you this file TOGETHER WITH their own description of the effect "
    "they want. This file is the reference of everything you may use.",
    "",
    "OUTPUT",
    "- Reply with a single JSON object shaped exactly like "
    "clipboard_format.example in this file, and nothing else around it: "
    "no markdown fences, no comments inside the JSON.",
    "- The user copies it and presses Ctrl+V in the editor, so it must "
    "be valid JSON on its own.",
    "- After the JSON, in a separate message part, add a short "
    "plain-language summary of what each module does, so the user can "
    "tweak it.",
    "",
    "HARD RULES",
    "- Use ONLY module names and parameter names that appear in "
    "'modules' and 'system_params' of this file. Never invent or guess "
    "names: unknown ones are silently ignored on paste.",
    "- One preset describes ONE particle system. Child systems cannot "
    "be created through the clipboard. If the effect needs layers, say "
    "so and tell the user to add a layer in the editor and paste a "
    "second preset into it.",
    "- Include only parameters you actually want to change. Anything "
    "omitted keeps the engine default, which is usually what you want.",
    "- A visible system needs at least one emitter and one renderer "
    "(render_animated_sprites is the usual renderer).",
    "- Order matters inside a group: position initializers run in "
    "sequence, so 'Position Modify Offset Random' must come after the "
    "module that sets the base position.",
    "- Modules marked \"previewed\": false do work in game but are NOT "
    "simulated by the editor's 3D preview. Prefer previewed modules, "
    "and warn the user when you use one.",
    "- \"full\" decides how the paste behaves and must match what the "
    "user wants:",
    "    \"full\": false - an ADDITION. Parameters you list are merged "
    "into the system: matching ones are overwritten, everything else "
    "the system already has stays untouched. Use this to adjust or "
    "extend an existing effect.",
    "    \"full\": true - a COMPLETE effect. On paste the editor asks "
    "the user whether to keep the existing parameters or replace the "
    "system entirely, so send a self-sufficient set: emitter, position "
    "and lifetime initializers, renderer, material, and anything else "
    "the effect needs to work on its own.",
    "",
    "UNITS AND CONVENTIONS",
    "- Distances are Hammer units: a player is about 83 units tall, a "
    "weapon about 30 units long, 1 unit is roughly 1.9 cm. Z is up.",
    "- Times are in seconds. Colors are [r, g, b, a], each 0-255.",
    "- 'material' is the particle texture. Pick one from "
    "available_materials.paths in this file - those are the materials "
    "that actually ship with the game, so the effect works without the "
    "user supplying any texture. Copy the path exactly, including "
    "backslashes (escape them in JSON: \"effects\\\\crit.vmt\"). Never "
    "invent a material path: a missing material means no texture in game.",
    "- 'example' values in this file come from real game effects. They "
    "are not engine defaults; use them as a sanity check for scale.",
    "- ANIMATED textures (a material whose .vtf is a multi-frame sprite "
    "sheet, e.g. animated butterflies/vortex): to make the frames play, "
    "the render_animated_sprites renderer needs either "
    "\"animation_fit_lifetime\": true (plays the whole sheet once over "
    "each particle's lifetime - the safe default), OR a high "
    "\"animation rate\" with \"use animation rate as fps\": true where "
    "the rate is frames per second (~24-30). 'animation rate': 1 means "
    "one frame per second - a 32-frame sheet then looks frozen. When the "
    "user asks for an animated texture, always set one of these.",
    "- To make a sprite face the direction it moves ON SCREEN (a "
    "butterfly, spider or ghost flying head-first), add a SECOND "
    "renderer 'render_screen_velocity_rotate' with 'forward_angle' "
    "(degrees, usually 90 or -90 depending on which way the texture's "
    "head points) alongside render_animated_sprites - this is what the "
    "game's own effects use. Do NOT use the 'Rotation Orient to 2D "
    "Direction' operator for this: it orients in the WORLD horizontal "
    "plane (compass heading, top-down view), so camera-facing sprites "
    "end up sideways; it only suits flat/top-down sprites such as "
    "shark fins on water.",
    "",
    "ASK BEFORE ANSWERING",
    "Always make sure you know ONE thing before writing any JSON: is "
    "this a brand-new effect that should replace the whole system "
    "(\"full\": true), or an addition to an effect the user already "
    "has (\"full\": false)? If the user did not say, ask.",
    "Then, if the description leaves any of the following unclear, ask "
    "about them too - in one short message, at most four questions, "
    "and wait for the answer:",
    "1. Spawn area: a single point, a sphere or a box, and how large.",
    "2. Context and scale: on a weapon, on the player, or an explosion "
    "in the world? How large should it read on screen?",
    "3. Timing: a one-shot burst or a continuous stream, and for how "
    "long each particle lives.",
    "4. Look: colors, whether particles glow, and how they move "
    "(fly outward, rise, fall, hover, swirl).",
    "5. Density: roughly how many particles at once.",
    "If the description is already detailed, skip the questions and "
    "answer directly.",
]


def param_reference_entry(tv: dict) -> dict:
    """Описание одного параметра для справочника: тип, пример и разброс

    Разброс по эффектам игры отвечает на вопрос, который не решается
    одним примером: 0.1 - это норма или экзотика
    """
    entry = {"type": tv["t"], "example": tv["v"]}
    if tv.get("lo") is not None and tv.get("lo") != tv.get("hi"):
        entry["range"] = [tv["lo"], tv["hi"]]
    return entry


def param_reference(cls, tf2_root_dir: str = "",
                    supported: Optional[dict] = None,
                    with_prompt: bool = False,
                    materials: Optional[List[str]] = None,
                    lang: str = "en") -> dict:
    """
    Справочник параметров для генерации пресетов внешними средствами

    Отдаёт всё, что нужно, чтобы собрать корректный набор параметров
    и вставить его в редактор через буфер обмена: формат буфера, типы
    значений, модули по группам с их параметрами и примерами значений
    из эффектов игры, плюс отметка, какие модули отыгрывает превью
    """
    cls.build_attr_catalog(tf2_root_dir)
    # У части модулей в файлах игры старое написание имени - движок
    # превью знает их через таблицу алиасов, учитываем и здесь
    aliases = {str(k).lower(): str(v).lower()
               for k, v in ((supported or {}).get("aliases") or {}).items()}
    groups: Dict[str, dict] = {}
    for (group, fn), attrs in sorted(
            cls._attr_catalog.items(), key=lambda kv: (kv[0][0] or "", kv[0][1])):
        if group is None:
            continue
        entry = {
            "params": {name: param_reference_entry(tv)
                       for name, tv in sorted(attrs.items())},
        }
        if supported is not None:
            known = {str(s).strip().lower()
                     for s in (supported.get(group) or [])}
            entry["previewed"] = aliases.get(fn, fn) in known
        groups.setdefault(group, {})[
            cls._module_display.get((group, fn), fn)] = entry

    system_attrs = cls._attr_catalog.get((None, ""), {})
    text = _REFERENCE_TEXT.get(lang, _REFERENCE_TEXT["en"])
    reference: Dict[str, Any] = {
        "format": 1,
        "about": text["about"],
        "notes": text["notes"],
        "value_types": text["value_types"],
        "clipboard_format": {
            "description": text["clipboard"],
            "example": {
                "tf2sgParticleParams": {
                    "attrs": {"max_particles": {"t": "integer", "v": 50},
                              "radius": {"t": "float", "v": 8.0}},
                    "modules": {
                        "emitters": [["emit_instantaneously", {
                            "num_to_emit": {"t": "integer", "v": 30}}]],
                        "initializers": [["Lifetime Random", {
                            "lifetime_min": {"t": "float", "v": 0.5},
                            "lifetime_max": {"t": "float", "v": 1.2}}]],
                    },
                    "full": False,
                }
            },
        },
        "module_groups": list(MODULE_GROUPS),
        "system_params": {name: param_reference_entry(tv)
                          for name, tv in sorted(system_attrs.items())},
        "modules": groups,
    }
    if materials is not None:
        # Текстуры частиц, которые уже есть в игре: эффект с таким
        # материалом работает сразу, ничего доустанавливать не нужно
        reference["available_materials"] = {
            "about": "Particle materials shipped with the game. Use one "
                     "of these as the 'material' value; paths are exact.",
            "count": len(materials),
            "paths": list(materials),
        }
    if with_prompt:
        # Инструкция идёт первым ключом: модели читают файл сверху вниз
        reference = {"instructions_for_ai": "\n".join(_AI_INSTRUCTIONS),
                     **reference}
    return reference
