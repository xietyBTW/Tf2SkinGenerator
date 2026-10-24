"""Редактор частиц"""

from __future__ import annotations

from typing import Dict, List

from src.app.api._common import _lang, endpoint


# Частицы

@endpoint
def particle_files() -> List[dict]:
    """PCF из игры - то, из чего выбирают эффект"""
    from src.app.session import session
    from src.services.particle_editor_service import ParticleEditorService

    paths = session().tf2_paths()
    if 'error' in paths:
        return []
    return [{'key': p, 'name': p.rsplit('/', 1)[-1].removesuffix('.pcf')}
            for p in ParticleEditorService.list_game_pcfs(paths['root'])]


@endpoint
def particle_effects(query: str = '', source: str = '',
                     lang: str = '') -> Dict[str, object]:
    """Эффекты игры по имени и по источнику - необычные, оружие, постройки…"""
    from src.app.session import session

    return session().particles.particle_effects(query, source, lang=_lang(lang))


@endpoint
def load_particles(source: str, system: str = '') -> Dict[str, object]:
    """Разбирает PCF: системы, материалы и дерево - всё, что рисует превью;
    `system` - на какой системе открыть (пусто - первый корень)"""
    from src.app.session import session
    return session().particles.load_particles(source, system)


@endpoint
def particle_effect_materials(system: str) -> Dict[str, object]:
    """Текстуры эффекта для движка - при выборе другой системы того же файла"""
    from src.app.session import session
    return session().particles.particle_effect_materials(system)


@endpoint
def particle_params(system: str, lang: str = '') -> List[dict]:
    """Крутилки простого режима для системы частиц"""
    from src.app.session import session

    lang = _lang(lang)
    return session().particles.particle_params(system, lang)


@endpoint
def particle_system(system: str, lang: str = '') -> Dict[str, object]:
    """Модули и атрибуты системы целиком - экспертный режим"""
    from src.app.session import session

    lang = _lang(lang)
    return session().particles.particle_system(system, lang)


@endpoint
def set_particle_attr(system: str, group, index: int, attr: str,
                      value) -> Dict[str, object]:
    """Правка одного атрибута системы или её модуля"""
    from src.app.session import session
    return session().particles.set_particle_attr(system, group, index, attr, value)


@endpoint
def particle_module_catalog(group: str) -> List[str]:
    """Модули, которые можно добавить в группу"""
    from src.app.session import session
    return session().particles.particle_module_catalog(group)


@endpoint
def add_particle_module(system: str, group: str,
                        function_name: str) -> Dict[str, object]:
    from src.app.session import session
    return session().particles.add_particle_module(system, group, function_name)


@endpoint
def apply_particle_gizmo(system: str, edits: list, prepare: bool = False) -> Dict[str, object]:
    """Итог перетаскивания ручек гизмо в превью частиц"""
    from src.app.session import session
    return session().particles.apply_particle_gizmo(system, edits, prepare)


@endpoint
def remove_particle_module(system: str, group: str,
                           index: int) -> Dict[str, object]:
    from src.app.session import session
    return session().particles.remove_particle_module(system, group, index)


@endpoint
def particle_missing_attrs(system: str, group=None, index: int = 0,
                           lang: str = '') -> List[dict]:
    """Параметры, которых у модуля ещё нет, со значениями как в игре"""
    from src.app.session import session

    lang = _lang(lang)
    return session().particles.particle_missing_attrs(system, group, index, lang)


@endpoint
def add_particle_attr(system: str, group, index: int, attr: str,
                      attr_type: str, value) -> Dict[str, object]:
    from src.app.session import session
    return session().particles.add_particle_attr(system, group, index, attr,
                                       attr_type, value)


@endpoint
def remove_particle_attr(system: str, group, index: int,
                         attr: str) -> Dict[str, object]:
    from src.app.session import session
    return session().particles.remove_particle_attr(system, group, index, attr)


@endpoint
def copy_particle_params(system: str, group=None, index=None,
                         attr=None) -> Dict[str, object]:
    """Набор параметров для буфера: один параметр, модуль, группа или всё"""
    from src.app.session import session
    return session().particles.copy_particle_params(system, group, index, attr)


@endpoint
def paste_particle_params(system: str, payload: dict,
                          mode: str = 'overwrite') -> Dict[str, object]:
    from src.app.session import session
    return session().particles.paste_particle_params(system, payload, mode)


@endpoint
def duplicate_particle_system(system: str, new_name: str) -> Dict[str, object]:
    from src.app.session import session
    return session().particles.duplicate_particle_system(system, new_name)


@endpoint
def rename_particle_system(system: str, new_name: str) -> Dict[str, object]:
    from src.app.session import session
    return session().particles.rename_particle_system(system, new_name)


@endpoint
def remove_particle_system(system: str) -> Dict[str, object]:
    from src.app.session import session
    return session().particles.remove_particle_system(system)


@endpoint
def particle_children(system: str) -> List[dict]:
    from src.app.session import session
    return session().particles.particle_children(system)


@endpoint
def add_particle_child(parent: str, child: str,
                       delay: float = 0.0) -> Dict[str, object]:
    from src.app.session import session
    return session().particles.add_particle_child(parent, child, delay)


@endpoint
def remove_particle_child(parent: str, index: int) -> Dict[str, object]:
    from src.app.session import session
    return session().particles.remove_particle_child(parent, index)


@endpoint
def add_particle_layer(parent: str) -> Dict[str, object]:
    from src.app.session import session
    return session().particles.add_particle_layer(parent)


@endpoint
def particle_diff(system: str) -> Dict[str, object]:
    """Чем система отличается от игровой: атрибуты, модули, дочерние"""
    from src.app.session import session

    return session().particles.particle_diff(system)


@endpoint
def revert_particle_system(system: str) -> Dict[str, object]:
    """Возвращает систему в игровой вид"""
    from src.app.session import session

    return session().particles.revert_particle_system(system)


@endpoint
def revert_particle_attr(system: str, group=None, index: int = 0,
                         attr: str = '') -> Dict[str, object]:
    """Возвращает один параметр к значению игры"""
    from src.app.session import session

    return session().particles.revert_particle_attr(system, group, index, attr)


@endpoint
def particle_history() -> Dict[str, object]:
    """Есть ли куда откатываться и возвращаться"""
    from src.app.session import session
    return session().particles.particle_history()


@endpoint
def undo_particles(delta: int = -1) -> Dict[str, object]:
    """Откат (-1) или возврат (+1) правки эффекта"""
    from src.app.session import session
    return session().particles.undo_particles(delta)


@endpoint
def particle_control_points(system: str) -> Dict[str, object]:
    """Какие контрольные точки нужны этому эффекту"""
    from src.app.session import session
    return session().particles.particle_control_points(system)


@endpoint
def particle_models(lang: str = '') -> List[dict]:
    """Модели из кэша декомпиляции - на них сажают контрольную точку.
    С группой (player/hat/weapon/arms/other) и подписью из каталогов игры"""
    from src.app.session import session
    return session().particles.particle_models(_lang(lang))


@endpoint
def particle_model_load(mode: str, key: str = '', lang: str = '') -> Dict[str, object]:
    """Модель для точек по предмету каталога, сцена придёт событием cp_model"""
    from src.app.session import session
    return session().particles.particle_model_load(mode, key, _lang(lang))


@endpoint
def particle_model_scene(qc: str) -> Dict[str, object]:
    """Меш модели и её точки крепления"""
    from src.app.session import session
    return session().particles.particle_model_scene(qc)


@endpoint
def particle_materials(system: str = '') -> List[dict]:
    """Материалы выбранного эффекта с картинками - карточки 2D"""
    from src.app.session import session
    return session().particles.particle_materials(system)


@endpoint
def set_particle_texture(material: str, path: str,
                         max_size: int = 512) -> Dict[str, object]:
    from src.app.session import session
    return session().particles.set_particle_texture(material, path, max_size)


@endpoint
def reset_particle_texture(material: str) -> Dict[str, object]:
    from src.app.session import session
    return session().particles.reset_particle_texture(material)


@endpoint
def game_particle_materials() -> List[str]:
    """Материалы всех эффектов игры - работают в казуале без нового файла"""
    from src.app.session import session
    return session().particles.game_particle_materials()


@endpoint
def set_particle_material_to_game(material: str,
                                  game_material: str) -> Dict[str, object]:
    from src.app.session import session
    return session().particles.set_particle_material_to_game(material, game_material)


@endpoint
def rename_particle_material(material: str,
                             new_material: str) -> Dict[str, object]:
    from src.app.session import session
    return session().particles.rename_particle_material(material, new_material)


@endpoint
def use_particle_texture_colors(system: str) -> Dict[str, object]:
    from src.app.session import session
    return session().particles.use_particle_texture_colors(system)


@endpoint
def particle_lint(system: str = '', lang: str = '') -> Dict[str, object]:
    """Что в эффекте сломает его в игре"""
    from src.app.session import session

    lang = _lang(lang)
    return session().particles.particle_lint(system, lang)


@endpoint
def fix_particle_lint(system: str = '') -> Dict[str, object]:
    from src.app.session import session
    return session().particles.fix_particle_lint(system)


@endpoint
def particle_size() -> Dict[str, object]:
    """Файл эффектов, его размер в моде и потолок казуала"""
    from src.app.session import session
    from src.services.particle_editor.export import size_summary
    return size_summary(session().particles.pcf)


@endpoint
def save_particles(path: str) -> Dict[str, object]:
    from src.app.session import session
    return session().particles.save_particles(path)


@endpoint
def export_particles_vpk(name: str = 'particles_mod.vpk',
                         lang: str = '') -> Dict[str, object]:
    from src.app.session import session

    lang = _lang(lang)
    return session().particles.export_particles_vpk(name, lang)


@endpoint
def particle_param_reference(path: str = '',
                             for_ai: bool = False) -> Dict[str, object]:
    from src.app.session import session
    return session().particles.particle_param_reference(path, for_ai, _lang())


@endpoint
def set_particle_param(system: str, key: str, value) -> Dict[str, object]:
    """Меняет параметр эффекта, в ответе - обновлённые системы для превью"""
    from src.app.session import session
    return session().particles.set_particle_param(system, key, value)
