"""
Какой SMD считается основной моделью

Превью и сборка спрашивают одну функцию: если они возьмут разные файлы,
человек увидит одно, а в игру уйдёт другое. Наборы файлов сняты с настоящих
папок декомпиляции (имена и размеры в КБ, LOD-и до первого), но кэш
вытесняется, поэтому папки собираются заново
"""

import os

import pytest

from src.services import smd_locator, smd_service

_LODS = ('_lod1', '_lod2')

CASES = [
    # Два _reference со своими LOD-ами: шланг идёт первым по алфавиту, но
    # это лишь часть медигана
    ('c_medigun', '', {
        'c_medigun_hose_reference.smd': 60, 'c_medigun_hose_reference_lod1.smd': 30,
        'c_medigun_physics.smd': 20, 'c_medigun_reference.smd': 900,
        'c_medigun_reference_lod1.smd': 400}, 'c_medigun_reference.smd'),
    ('c_shotgun', '', {
        'c_shotgun_physics.smd': 20, 'c_shotgun_reference.smd': 845,
        'c_shotgun_reference_lod1.smd': 413}, 'c_shotgun_reference.smd'),
    ('c_grenadelauncher', '', {
        'c_grenadelauncher.smd': 2386, 'c_grenadelauncher_lod1.smd': 1188,
        'c_grenadelauncher_physics.smd': 35, 'grenade_bodygroup.smd': 56,
        'grenade_bodygroup_lod1.smd': 24}, 'c_grenadelauncher.smd'),
    # Ключ не совпадает с именем файла
    ('c_batt_buffpack', '', {
        'c_batt_buffpack_physics.smd': 9, 'c_battalion_buffpack.smd': 1050},
     'c_battalion_buffpack.smd'),
    # У шапок ключ - полный путь MDL
    ('models/workshop_partner/player/items/sniper/c_bet_brinkhood/c_bet_brinkhood.mdl', 'hat', {
        'c_bet_brinkhood.smd': 463, 'c_bet_brinkhood_lod1.smd': 159,
        'c_bet_brinkhood_physics.smd': 27}, 'c_bet_brinkhood.smd'),
    ('models/player/items/heavy/stormspirit_hat.mdl', 'hat', {
        'storm_spirit_hat.smd': 150, 'stormspirit_hat_physics.smd': 13},
     'storm_spirit_hat.smd'),
    # Без QC тело персонажа угадывается по размеру: короткие demo_smiley и
    # spy_mask - лицо и маска, а не тело
    ('models/player/demo.mdl', '', {
        'demo_morphs_low.smd': 1977, 'demo_morphs_low_lod1.smd': 1125,
        'demo_physics.smd': 76, 'demo_smiley.smd': 47, 'demo_smiley_lod1.smd': 17,
        'grenades_bodygroup.smd': 424, 'shoes_bodygroup.smd': 157},
     'demo_morphs_low.smd'),
    ('models/player/spy.mdl', '', {
        'spy_mask.smd': 92, 'spy_mask_lod1.smd': 92, 'spy_morphs_low.smd': 1589,
        'spy_morphs_low_lod1.smd': 943, 'spy_physics.smd': 79},
     'spy_morphs_low.smd'),
]


@pytest.mark.parametrize('key, mode, files, expected', CASES,
                         ids=[c[0].split('/')[-1] for c in CASES])
def test_reference_smd_choice(tmp_path, key, mode, files, expected):
    for name, kb in files.items():
        (tmp_path / name).write_bytes(b'x' * kb)
    assert os.path.basename(smd_service.find_reference_smd(str(tmp_path), key)) == expected
    found = smd_locator.find_reference_smd(str(tmp_path), mode, key, lambda d: None)
    assert os.path.basename(found) == expected


def test_lod_and_physics_only_means_nothing(tmp_path):
    for name in ('c_gun_physics.smd', 'c_gun_lod1.smd', 'c_gun_anims.smd'):
        (tmp_path / name).write_text('x', encoding='utf-8')
    assert smd_service.find_reference_smd(str(tmp_path), 'c_gun') is None
