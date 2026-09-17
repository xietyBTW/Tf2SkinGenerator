"""
Собирает таблицу «система частиц → чем она вызывается» (src/data/particle_sources_table.py).

Игра нигде не хранит такой таблицы: эффект называют по имени скрипты оружия
(вспышка, взрыв, трассер), код игры (пламя огнемёта, луч медигана, турель,
крит) и items_game (необычные эффекты). Здесь всё это сводится в один словарь
раз на версию игры — приложению достаётся готовый модуль, без дешифровки
и без исходников движка в рантайме.

Запуск (нужны игра и исходники TF2 из Source SDK 2013):
    python scripts/particle_sources_build.py D:/GitHub/ParticleOracle/sdk/src/game

Источники по убыванию точности:
1. `scripts/tf_weapon_*.ctx` (ICE, см. vice.py): MuzzleFlashParticleEffect,
   ExplosionEffect/PlayerEffect/WaterEffect, TracerEffect → предмет назван
   точно, вместе с токеном локализации.
2. Строковые литералы в коде игры: имя файла говорит, чьё это —
   tf_weapon_flamethrower.cpp, tf_obj_sentrygun.cpp, merasmus.cpp.
3. Дерево PCF: дочерние системы необычного эффекта наследуют его.
4. Имя файла PCF — последняя догадка (taunt_fx, bullet_tracers).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Set

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

import vice  # noqa: E402

OUT = ROOT / 'src' / 'data' / 'particle_sources_table.py'

#: Снаряд в коде → скрипт оружия, которое его пускает.
PROJECTILES = {
    'flare': 'flaregun', 'rocket': 'rocketlauncher',
    'energy_ball': 'particle_cannon', 'energy_ring': 'raygun',
    'arrow': 'compound_bow', 'nail': 'syringegun_medic', 'syringe': 'syringegun_medic',
    'dragons_fury': 'rocketlauncher_fireball', 'jar': 'jar',
    'stunball': 'bat_wood', 'cleaver': 'cleaver', 'spellfireball': 'spellbook',
    'ball_ornament': 'bat_giftwrap',
}

#: Файл кода → (вид, метка). Первое совпадение по имени файла побеждает;
#: `c_` (клиентская половина) отбрасывается заранее.
FILE_RULES = [
    (r'^obj_sentrygun|^tf_obj_sentrygun', 'building', 'sentry'),
    (r'^obj_teleporter|^tf_obj_teleporter', 'building', 'teleporter'),
    (r'^obj_dispenser|^tf_obj_dispenser', 'building', 'dispenser'),
    (r'^tf_obj_sapper', 'building', 'sapper'),
    (r'^tf_obj\b|^baseobject', 'building', ''),
    (r'^tf_weapon_spellbook|^tf_weaponbase_merasmus', 'halloween', ''),
    (r'merasmus|eyeball_boss|headless_hatman|^ghost|^zombie|halloween|'
     r'pumpkin_bomb|teleport_vortex|crybaby|^tf_wearable_campaign', 'halloween', ''),
    (r'mann_vs_machine|^tf_bot|^bot_npc|tank_boss|populat|currencypack|'
     r'boss_alpha|target_dummy', 'mvm', ''),
    (r'^tf_fx_|^fx_|^physics_shared|^ragdoll_shared|^props_shared|^fire_smoke',
     'impact', ''),
    (r'^tf_player|^tf_gamemovement|^tf_item_wearable|^tf_dropped_weapon|'
     r'^tf_revive|^tf_flame\b|^tf_flame\.|^baseanimating|^playerrelativemodel',
     'player', ''),
    (r'^tf_gamerules|^tf_shareddefs|^entity_|^func_capture|passtime|'
     r'^tf_match_summary|^tf_hud_account|^teamplay_gamerules|^item_world|'
     r'^tf_extra_map_entity|^logicentities|robot_destruction|^tf_projectile_'
     r'|^tf_weapon|^tf_weaponbase|^basecombatweapon', 'game', ''),
]

#: Файл PCF → (вид, метка), когда больше ничего не сказало. По вхождению,
#: первое совпадение побеждает. Метка у оружия — стебель его скрипта.
PCF_KINDS = [
    ('taunt', 'taunt', ''), ('rps', 'taunt', ''),
    ('drg_cowmangler', 'weapon', 'particle_cannon'), ('drg_bison', 'weapon', 'raygun'),
    ('drg_pyro', 'weapon', 'flamethrower'), ('drg_engineer', 'weapon', 'drg_pomson'),
    ('dxhr', 'weapon', 'mechanical_arm'), ('invasion_ray_gun', 'weapon', 'raygun'),
    ('bullet_tracers', 'weapon', ''), ('muzzle_flash', 'weapon', ''),
    ('rocketbackblast', 'weapon', 'rocketlauncher'), ('rocket', 'weapon', 'rocketlauncher'),
    ('stickybomb', 'weapon', 'pipebomblauncher'), ('flamethrower', 'weapon', 'flamethrower'),
    ('medicgun', 'weapon', 'medigun'), ('sniper', 'weapon', 'sniperrifle'),
    ('soldierbuff', 'weapon', 'buff_item'), ('items_demo', 'weapon', ''),
    ('items_engineer', 'building', ''), ('firstperson_weapon', 'weapon', ''),
    ('conc_stars', 'player', ''), ('disguise', 'player', ''), ('class_fx', 'player', ''),
    ('burningplayer', 'player', ''), ('crit', 'player', ''), ('player', 'player', ''),
    ('speechbubbles', 'player', ''), ('nemesis', 'player', ''),
    ('explosion', 'impact', ''), ('bigboom', 'impact', ''), ('dirty_explode', 'impact', ''),
    ('blood', 'impact', ''), ('impact', 'impact', ''), ('sparks', 'impact', ''),
    ('buildingdamage', 'building', ''), ('teleport', 'building', 'teleporter'),
    ('dispenser', 'building', 'dispenser'), ('sentry', 'building', 'sentry'),
    ('halloween', 'halloween', ''), ('bombinomicon', 'halloween', ''),
    ('ghost', 'halloween', ''), ('eyeboss', 'halloween', ''), ('xms', 'halloween', ''),
    ('mvm', 'mvm', ''), ('robot', 'mvm', ''),
    ('koth', 'game', ''), ('flag', 'game', ''), ('cart', 'game', ''), ('rune', 'game', ''),
    ('powerups', 'game', ''), ('doomsday', 'game', ''), ('passtime', 'game', ''),
    ('rankup', 'game', ''), ('training', 'game', ''), ('vgui', 'game', ''),
    ('stamp', 'game', ''), ('npc_fx', 'game', ''),
    ('unusual', 'unusual', ''), ('item_fx', 'unusual', ''), ('killstreak', 'unusual', ''),
    ('level_fx', 'world', ''), ('cinefx', 'world', ''), ('water', 'world', ''),
    ('smoke', 'world', ''), ('harbor', 'world', ''), ('rain', 'world', ''),
    ('stormfront', 'world', ''), ('urban', 'world', ''), ('cig_smoke', 'world', ''),
]


def weapon_stem(file_stem: str, scripts: Set[str]) -> str:
    """Скрипт оружия по имени файла кода. Пусто — общий для оружия."""
    stem = re.sub(r'^c_', '', file_stem)
    m = re.match(r'^tf_weapon_(.+)$', stem)
    if m:
        return m.group(1) if m.group(1) in scripts else ''
    m = re.match(r'^tf_projectile_(.+)$', stem)
    if m:
        return PROJECTILES.get(m.group(1), '')
    return ''


def classify_file(file_name: str, scripts: Set[str]):
    """(вид, метка) по имени файла кода; None — файл не про эффекты (HUD)."""
    stem = re.sub(r'\.(cpp|h)$', '', file_name)
    bare = re.sub(r'^c_', '', stem)
    weapon = weapon_stem(stem, scripts)
    if weapon:
        return ('weapon', weapon)
    if re.match(r'^tf_weapon', bare) or re.match(r'^tf_projectile', bare):
        return ('weapon', '')
    for pattern, kind, label in FILE_RULES:
        if re.search(pattern, bare):
            return (kind, label)
    return None


def main(sdk_game: str) -> None:
    from src.app.session import AppSession
    from src.services import vtf_preview_service as vps
    from src.services.particle_editor_service import (
        ParticleEditorService, system_hierarchy,
    )
    from src.data import unusual_effects
    from src.data.weapon_model_index import get_items_game_path

    paths = AppSession().tf2_paths()
    if 'error' in paths:
        sys.exit(paths['error'])
    root = paths['root']
    paks = vps.open_vpks([paths['misc_vpk']])

    # 1. Скрипты оружия.
    scripts: Dict[str, str] = {}          # stem → текст
    printnames: Dict[str, str] = {}       # stem → токен локализации
    for name in sorted(n for n in paks[0]
                       if n.startswith('scripts/tf_weapon_') and n.endswith('.ctx')):
        stem = name[len('scripts/tf_weapon_'):-4]
        text = vice.decrypt(paks[0][name].read()).decode('utf-8', 'replace')
        scripts[stem] = text
        m = re.search(r'"printname"\s+"([^"]+)"', text)
        if m:
            printnames[stem] = m.group(1)
    print(f'скриптов оружия: {len(scripts)}')
    # Метка без скрипта — ошибка таблиц выше, а не данных игры.
    for stem in set(PROJECTILES.values()) | {l for _, k, l in PCF_KINDS
                                             if l and k == 'weapon'}:
        if stem not in scripts:
            print(f'  внимание: скрипта tf_weapon_{stem}.ctx нет')

    # 2. Все системы и дерево каждого файла.
    sources: Dict[str, Set[str]] = {}
    files: Dict[str, str] = {}
    parents: Dict[str, str] = {}          # система → корень дерева
    for pcf in ParticleEditorService.list_game_pcfs(root):
        svc = ParticleEditorService()
        try:
            svc.load_from_game(root, pcf)
        except Exception:
            continue
        systems = svc.systems_json()
        for name in systems:
            files.setdefault(name, pcf)

        def walk(tree, top):
            for name, kids in tree:
                parents.setdefault(name, top or name)
                walk(kids, top or name)
        walk(system_hierarchy(systems, order=svc.system_names()), '')
    lower = {k.lower(): k for k in files}
    print(f'систем: {len(files)}')

    def add(name: str, token: str) -> None:
        sources.setdefault(name, set()).add(token)

    # Скрипты: точные имена и трассеры с командным хвостом.
    for stem, text in scripts.items():
        for key, value in re.findall(r'"([A-Za-z]+Effect)"\s+"([^"]+)"', text):
            low = value.lower()
            if low in lower:
                add(lower[low], f'weapon:{stem}')
            elif 'tracer' in key.lower():
                for sl, orig in lower.items():
                    if sl.startswith(low + '_'):
                        add(orig, f'weapon:{stem}')

    # 3. Код игры.
    literal_files: Dict[str, Set[str]] = {}
    for folder, _, names in os.walk(sdk_game):
        for fn in names:
            if not fn.endswith(('.cpp', '.h')):
                continue
            try:
                text = Path(folder, fn).read_text(encoding='utf-8', errors='replace')
            except OSError:
                continue
            for lit in set(re.findall(r'"([A-Za-z0-9_%\.]{3,64})"', text)):
                literal_files.setdefault(lit, set()).add(fn)
    code_hits = 0
    for lit, fnames in literal_files.items():
        low = lit.lower()
        targets: List[str] = []
        if low in lower:
            targets = [lower[low]]
        elif '%' in lit:
            # Шаблон вроде `teleporter_%s_%s_level%d`: голова до первого
            # подставляемого поля, но только длинная и со словом целиком —
            # `player_%d` иначе накрывал бы всё, что начинается с player.
            head = low.split('%')[0]
            if len(head) >= 8 and head.endswith('_'):
                targets = [orig for sl, orig in lower.items() if sl.startswith(head)]
        for fn in fnames:
            kind = classify_file(fn, set(scripts))
            if kind is None:
                continue
            for name in targets:
                add(name, f'{kind[0]}:{kind[1]}')
                code_hits += 1
    print(f'ссылок из кода: {code_hits}')

    # 4. Необычные эффекты: корень и все его потомки.
    from src.data.hats_parser import parse_localization
    text = open(get_items_game_path(root), encoding='utf-8', errors='replace').read()
    unusual = {fx['system']: fx for fx in
               unusual_effects.parse(text, parse_localization(root, 'english'))}
    for name in files:
        top = parents.get(name, name)
        if top in unusual or name in unusual:
            add(name, f'unusual:{top if top in unusual else name}')

    # 5. Файл PCF — всем: у `flamethrower` из кода только «правила игры»
    # (там его зовут по имени класса), а файл говорит «огнемёт».
    for name, pcf in files.items():
        base = pcf.rsplit('/', 1)[-1]
        for word, kind, label in PCF_KINDS:
            if word in base:
                add(name, f'{kind}:{label if label in scripts else ""}')
                break

    covered = sum(1 for n in files if n in sources)
    print(f'покрыто: {covered} из {len(files)}')

    lines = [
        '"""',
        'Чем вызывается каждая система частиц игры — собрано скриптом',
        'scripts/particle_sources_build.py. Не править руками: перегенерировать.',
        '',
        'Токен источника: `вид:метка`. Виды — в src/data/particle_sources.py;',
        'метка у оружия — стебель скрипта (`flamethrower`), у постройки — её',
        'слово (`sentry`), у необычного эффекта — имя корневой системы.',
        '"""',
        '',
        'from __future__ import annotations',
        '',
        '#: Стебель скрипта оружия → токен локализации его названия.',
        'WEAPON_NAMES = {',
    ]
    for stem in sorted(printnames):
        lines.append(f'    {stem!r}: {printnames[stem]!r},')
    lines += ['}', '', '#: Система → источники.', 'SOURCES = {']
    for name in sorted(sources, key=str.lower):
        lines.append(f'    {name!r}: {tuple(sorted(sources[name]))!r},')
    lines += ['}', '']
    OUT.write_text('\n'.join(lines), encoding='utf-8')
    print(f'записано: {OUT} ({OUT.stat().st_size // 1024} КБ)')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit('нужен путь к исходникам игры: sdk/src/game')
    main(sys.argv[1])
