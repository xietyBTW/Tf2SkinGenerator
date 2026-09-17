"""Чем вызывается система частиц: таблица, подписи и шифр скриптов оружия."""

import sys
from pathlib import Path

from src.data import particle_sources as ps
from src.data.particle_sources_table import SOURCES, WEAPON_NAMES

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
import vice  # noqa: E402


def test_table_is_sane():
    """Каждый токен — «вид:метка» с известным видом; у оружия метка — стебель
    скрипта, у которого есть имя."""
    assert len(SOURCES) > 5000
    for name, tokens in SOURCES.items():
        for token in tokens:
            kind, _, label = token.partition(':')
            assert kind in ps.KIND_NAMES, (name, token)
            if kind == 'weapon' and label:
                assert label in WEAPON_NAMES, (name, token)


def test_tokens_are_found_case_insensitively():
    name = next(iter(SOURCES))
    assert ps.tokens_of(name.upper()) == SOURCES[name]
    assert ps.tokens_of('нет такой системы') == ()


def test_unknown_system_gets_kind_from_its_file():
    """Файл новее таблицы (сезонные анюжуалы) — вид по имени файла."""
    assert ps.tokens_of('brand_new_effect', 'particles/summer2030_unusuals.pcf') == ('unusual:',)
    assert ps.kinds_of('brand_new_effect', 'particles/taunt_fx_2030.pcf') == ['taunt']
    assert ps.kinds_of('brand_new_effect', 'particles/whatever.pcf') == []


def test_labels_name_the_item(monkeypatch):
    monkeypatch.setitem(ps._LOWER, 'probe_fx',
                        ('weapon:flamethrower', 'building:sentry',
                         'unusual:superrare_burning1', 'game:'))
    loc = {'TF_Weapon_FlameThrower': 'Огнемёт', 'TF_Object_Sentry': 'Турель'}
    assert ps.labels_of('probe_fx', '', loc, {'superrare_burning1': 'Язычки пламени'}) == [
        'Огнемёт', 'Турель', 'Язычки пламени']
    # Виды идут в порядке фасета, независимо от порядка токенов.
    assert ps.kinds_of('probe_fx') == ['weapon', 'building', 'unusual', 'game']


def test_weapon_without_localized_printname_uses_catalog_name(monkeypatch):
    """У `raygun` printname в локализации нет — имя берётся из каталога оружия."""
    monkeypatch.setitem(ps._LOWER, 'probe_ray', ('weapon:raygun',))
    assert ps.labels_of('probe_ray', '', {}, {}, 'ru') == ['Благочестивый бизон']
    assert ps.labels_of('probe_ray', '', {}, {}, 'en') == ['Righteous Bison']


def test_thin_ice_reference_vector():
    """Тест-вектор Квана для Thin-ICE (уровень 0): ключ deadbeef01234567,
    шифртекст de240d83a00a9cc0 → fedcba9876543210."""
    key = bytes.fromhex('deadbeef01234567')
    assert vice.decrypt(bytes.fromhex('de240d83a00a9cc0'), key).hex() == 'fedcba9876543210'
    # Хвост короче блока не трогается.
    assert vice.decrypt(b'\x01\x02\x03', key) == b'\x01\x02\x03'
