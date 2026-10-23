"""
Текстуры чужого мода: какая основная, а какая служебная, и какие карты
материала уже стоят в его VMT

Одно правило на все места (карточки мода, сборка мода, обложка в
библиотеке). Поиск подстроки где угодно в пути не годится: «mask» спрятал бы
основную текстуру маски шпиона

Порядок доверия:
  1. VMT мода: на что ссылается `$basetexture` - основная, на что ссылаются
     прочие параметры ($bumpmap, $detail, $lightwarptexture…) - служебная.
     Так текстуру находит сама игра.
  2. Имя файла - только если VMT про неё молчит: суффикс стебля, а не
     подстрока в пути
"""

from __future__ import annotations

import os
from typing import Dict, Iterable, Optional, Set

from src.services import vmt_parse

#: Параметры VMT, которые указывают на ОСНОВНУЮ текстуру
_BASE_PARAMS = frozenset({'basetexture', 'basetexture2'})

#: Окончания стебля служебных текстур: и Valve, и авторов модов, и наших
#: карт (суффиксы MATERIAL_MAPS - `_exp`, `_illum`, `_envmask`…)
_SERVICE_SUFFIXES = (
    '_normal', '_normals', '_nrm', '_bump', '_bumpmap', '_ssbump',
    '_exp', '_exponent', '_phongexp', '_phong',
    '_illum', '_selfillum', '_selfillummask',
    '_envmask', '_envmapmask', '_envmap', '_cubemap', '_spec', '_specular',
    '_detail', '_mask', '_masks', '_sheen', '_sheenmask',
    '_lightwarp', '_phongwarp',
)
#: Слова, которых в имени основной текстуры не бывает вовсе
_SERVICE_WORDS = ('lightwarp', 'phongwarp', 'cubemap', 'normalmap', 'sheenmap')


def texture_key(path: str) -> str:
    """Путь текстуры так, как его пишет VMT: от materials/, без .vtf,
    прямые слэши, нижний регистр"""
    key = str(path or '').replace('\\', '/').strip().strip('/').lower()
    if key.startswith('materials/'):
        key = key[len('materials/'):]
    return key[:-4] if key.endswith('.vtf') else key


def is_service_name(vtf_path: str) -> bool:
    """Служебная ли текстура по одному имени (когда VMT о ней молчит)"""
    stem = os.path.splitext(os.path.basename(str(vtf_path)))[0].lower()
    if stem.endswith('_blue'):
        stem = stem[:-len('_blue')]
    return (stem.endswith(_SERVICE_SUFFIXES)
            or any(word in stem for word in _SERVICE_WORDS))


def vmt_references(vmt_texts: Iterable[str]) -> Dict[str, Set[str]]:
    """{'base': ключи основных текстур, 'service': ключи служебных} по VMT мода"""
    base: Set[str] = set()
    service: Set[str] = set()
    for text in vmt_texts:
        doc = vmt_parse.parse(text or '')
        for name, value in doc.root.params.items():
            if not isinstance(value, str) or not value.strip():
                continue
            key = texture_key(value)
            # Числа, векторы и «env_cubemap» путями не бывают
            if '/' not in key:
                continue
            (base if name in _BASE_PARAMS else service).add(key)
    return {'base': base, 'service': service - base}


def all_references(vmt_texts: Iterable[str]) -> Set[str]:
    """Каждое строковое значение VMT во всём дереве (блоки качества, прокси),
    приведённое к ключу текстуры. Для решения «можно ли удалить VTF»: тут
    лишнее безопасно (файл останется), а пропуск - нет (материал станет
    фиолетовым). Поэтому без фильтра по «/»: текстура бывает и в корне
    materials"""
    found: Set[str] = set()

    def walk(node) -> None:
        for value in node.params.values():
            if isinstance(value, str) and value.strip():
                found.add(texture_key(value))
        for children in node.blocks.values():
            for child in children:
                walk(child)

    for text in vmt_texts:
        walk(vmt_parse.parse(text or '').root)
    return found


def is_base_vtf(vtf_path: str, refs: Optional[Dict[str, Set[str]]] = None) -> bool:
    """Основная ли это текстура мода

    `refs` - результат `vmt_references`; без него решает только имя
    """
    if refs:
        key = texture_key(vtf_path)
        if key in refs['base']:
            return True
        if key in refs['service']:
            return False
    return not is_service_name(vtf_path)
