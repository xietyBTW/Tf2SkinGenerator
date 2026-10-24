"""
Сервис редактора частиц: PCF ⇄ JSON для JS-движка превью + правка атрибутов

Схема работы:
    • PCF загружается через srctools.dmx (из файла или из tf2_misc_dir.vpk);
      Element-дерево - единственный источник правды о данных.
    • Для JS-движка превью дерево конвертируется в JSON: каждая система -
      атрибуты + модули (initializers/operators/emitters/renderers/forces/
      constraints) + children (по имени). Каждый атрибут - {"t": тип, "v": знач}:
      один формат читают и JS-движок, и редактор свойств.
    • Материалы систем резолвятся в текстуры: VMT (regex $basetexture) ->
      VTF из tf2_textures_dir.vpk / tf2_misc_dir.vpk -> PNG data URL через VTFLib.
      Sheet-данные (спрайт-листы частиц) парсятся из ресурса VTF 0x10 напрямую.
    • Правки применяются к Element-дереву (set_attr) и сохраняются обратно
      в бинарный PCF с исходным encoding/format (как в CritPcfService)

Здесь - ядро: документ PCF, его загрузка и снимки истории. Остальное делают
соавторы из пакета particle_editor: каждый получает документ (self) и не
знает о соседях. Класс собирает их методы в один фасад
"""

import io
from pathlib import Path
from typing import Dict, List, Optional

from src.services.crit_pcf_service import CritPcfService
from src.services.particle_editor import (
    attr_edit, catalog, export, materials, origin, paste, structure,
    texture_colors, texture_replace)
from src.services.particle_editor import param_reference as reference
from src.services.particle_editor import stock as stock_mod
# Реэкспорт: эти имена импортируют из сервиса приложение, скрипты и тесты
from src.services.particle_editor.catalog import MODULE_CATALOG  # noqa: F401
from src.services.particle_editor.hierarchy import (  # noqa: F401
    MAX_CONTROL_POINTS, flatten_hierarchy, referenced_control_points,
    system_hierarchy)
from src.services.particle_editor.materials import _is_additive  # noqa: F401
from src.services.particle_editor.pcf_format import (  # noqa: F401
    MODULE_GROUPS, SRCTOOLS_AVAILABLE, Element, element_attrs_to_json,
    module_to_json, norm_mat as _norm_mat)
from src.services.particle_editor.stock import diff_systems  # noqa: F401
from src.services.particle_editor.vtf_sheet import parse_vtf_sheet  # noqa: F401
from src.services.tf2_paths import TF2Paths
from src.services.vtf_preview_service import open_vpks, read_from_vpks
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class ParticleEditorService:
    """Загрузка, конвертация, правка и сохранение PCF"""

    def __init__(self) -> None:
        self.root = None                       # корневой Element PCF
        self._encoding = (2, "pcf", 1)         # (enc_ver, fmt_name, fmt_ver)
        self.source_path: Optional[str] = None  # откуда загружен (файл или vpk:путь)
        #: Кастомные материалы (замена текстур): {rel_path: bytes} -
        #: и .vmt (текст), и .vtf (бинарь), попадают в превью и в экспорт VPK
        self.custom_files: Dict[str, bytes] = {}
        #: Превью-инфо кастомных материалов: {норм. имя материала: info-dict}
        self._custom_material_info: Dict[str, dict] = {}
        #: Перезаписанные текстуры: {норм. имя материала: {tex_rel, material}}
        self._overwritten: Dict[str, dict] = {}
        #: Путь к <имя>_textures.vpk из последнего export_vpk (None - не собирался)
        self.last_textures_vpk: Optional[str] = None
        #: Размер загруженного файла - «потолок» для казуала (None - неизвестен)
        self._loaded_size: Optional[int] = None
        #: Игровая версия файла: (путь, сервис | None); None - ещё не искали
        self._stock = None
        #: systems_json игровой версии - для сравнения (None - не считали)
        self._stock_systems: Optional[Dict[str, dict]] = None

    # Загрузка

    def load_bytes(self, raw: bytes, source: str = "") -> None:
        """Парсит PCF из байтов (бросает исключение при ошибке)"""
        if not SRCTOOLS_AVAILABLE:
            raise RuntimeError("srctools не установлен (pip install srctools)")
        self._encoding = CritPcfService._detect_encoding(raw)
        self.root, _, _ = Element.parse(io.BytesIO(raw))
        self.source_path = source
        self._loaded_size = len(raw)   # «потолок» размера для казуала
        self.custom_files = {}
        self._custom_material_info = {}
        self._overwritten = {}

    def load_file(self, path: str) -> None:
        self.load_bytes(Path(path).read_bytes(), source=path)

    def load_from_game(self, tf2_root_dir: str, vpk_path: str) -> None:
        """Загружает PCF по внутреннему пути из tf2_misc_dir.vpk"""
        _, misc_vpk, _ = TF2Paths.resolve(tf2_root_dir)
        raw = read_from_vpks(open_vpks([misc_vpk]), vpk_path)
        if raw is None:
            raise FileNotFoundError(f"{vpk_path} не найден в {misc_vpk}")
        self.load_bytes(raw, source=f"vpk:{vpk_path}")

    # Снимки состояния (undo/redo)

    def snapshot(self) -> Optional[dict]:
        """
        Полное состояние редактора одним снимком

        Дерево сериализуется в байты (тот же формат, что и файл - сжатие
        default-атрибутов НЕ применяем, снимок должен быть точной копией),
        рядом кладутся оверрайды текстур. Снимочный подход выбран вместо
        обратимых команд: он автоматически покрывает и будущие операции -
        забыть «откат» для новой правки невозможно
        """
        if self.root is None:
            return None
        enc_ver, fmt_name, fmt_ver = self._encoding
        buf = io.BytesIO()
        self.root.export_binary(
            buf, version=enc_ver, fmt_name=fmt_name, fmt_ver=fmt_ver,
            unicode="silent")
        return {
            "pcf": buf.getvalue(),
            "custom_files": dict(self.custom_files),
            "custom_material_info": dict(self._custom_material_info),
            "overwritten": {k: dict(v) for k, v in self._overwritten.items()},
        }

    def restore(self, snap: dict) -> bool:
        """Возвращает состояние из снимка (дерево + оверрайды текстур)"""
        if not snap or not SRCTOOLS_AVAILABLE:
            return False
        try:
            root, _, _ = Element.parse(io.BytesIO(snap["pcf"]))
        except Exception as exc:
            logger.error(f"Восстановление снимка PCF: {exc}")
            return False
        self.root = root
        self.custom_files = dict(snap.get("custom_files") or {})
        self._custom_material_info = dict(
            snap.get("custom_material_info") or {})
        self._overwritten = {k: dict(v)
                             for k, v in (snap.get("overwritten") or {}).items()}
        return True

    # Определения систем

    def _definitions(self) -> list:
        if self.root is None:
            return []
        try:
            return list(self.root["particleSystemDefinitions"].iter_elem())
        except KeyError:
            return []

    def system_names(self) -> List[str]:
        return [d.name for d in self._definitions()]

    def _find_definition(self, name: str):
        for d in self._definitions():
            if d.name == name:
                return d
        # Системы, существующие только как children (нет в корневом списке)
        for d in self._all_definition_elements():
            if d.name == name:
                return d
        return None

    def _all_definition_elements(self) -> list:
        """Все определения систем: корневой список + достижимые через children
        (некоторые дочерние системы не значатся в корневом списке)"""
        out, seen, pending = [], set(), list(self._definitions())
        while pending:
            d = pending.pop(0)
            if id(d) in seen:
                continue
            seen.add(id(d))
            out.append(d)
            if "children" in d:
                try:
                    for ch in d["children"].iter_elem():
                        if "child" in ch:
                            try:
                                pending.append(ch["child"].val_elem)
                            except Exception:
                                pass
                except Exception:
                    pass
        return out

    def systems_json(self) -> Dict[str, dict]:
        """
        Все системы частиц -> {имя: система} для JS-движка и редактора

        children сериализуются как [{"delay": float, "childName": имя}];
        системы, на которые ссылаются только children (нет в корневом списке),
        добавляются в результат при обходе
        """
        result: Dict[str, dict] = {}
        pending = list(self._definitions())
        while pending:
            d = pending.pop(0)
            if d.name in result:
                continue
            sys_json = {
                "name": d.name,
                "attrs": element_attrs_to_json(d),
                "children": [],
            }
            for group in MODULE_GROUPS:
                mods = []
                if group in d:
                    try:
                        mods = [module_to_json(m) for m in d[group].iter_elem()]
                    except Exception as exc:
                        logger.warning(f"{d.name}/{group}: {exc}")
                sys_json[group] = mods
            if "children" in d:
                try:
                    for ch in d["children"].iter_elem():
                        delay = 0.0
                        if "delay" in ch:
                            delay = ch["delay"].val_float
                        child_el = None
                        if "child" in ch:
                            try:
                                child_el = ch["child"].val_elem
                            except Exception:
                                child_el = None
                        if child_el is None:
                            continue
                        sys_json["children"].append(
                            {"delay": delay, "childName": child_el.name}
                        )
                        pending.append(child_el)
                except Exception as exc:
                    logger.warning(f"{d.name}/children: {exc}")
            result[d.name] = sys_json
        return result

    # Соавторы документа
    # Функции модулей пакета particle_editor с документом первым аргументом:
    # присвоенные в теле класса, они становятся его методами

    # Сток: игровая версия файла, сравнение и откат (stock.py)
    stock_path = stock_mod.stock_path
    stock = stock_mod.stock
    stock_diff = stock_mod.stock_diff
    revert_system = stock_mod.revert_system
    revert_attr = stock_mod.revert_attr

    # Материалы: текстуры для превью, смена материала (materials.py)
    material_names = materials.material_names
    materials_json = materials.materials_json
    set_material_to_game = materials.set_material_to_game
    rename_material = materials.rename_material

    # Правка значений (attr_edit.py)
    set_attr = attr_edit.set_attr
    ensure_attr = attr_edit.ensure_attr
    remove_attr = attr_edit.remove_attr
    _module_owners = attr_edit.module_owners
    _module_for_edit = attr_edit.module_for_edit

    # Вставка скопированных параметров (paste.py)
    paste_params = paste.paste_params

    # Правка структуры: модули, системы, слои (structure.py)
    add_module = structure.add_module
    apply_gizmo_edits = structure.apply_gizmo_edits
    ensure_effect_origin = origin.ensure_effect_origin
    _seed_spawn_area = staticmethod(structure.seed_spawn_area)
    remove_module = structure.remove_module
    duplicate_system = structure.duplicate_system
    rename_system = structure.rename_system
    remove_system = structure.remove_system
    add_layer = structure.add_layer
    add_child = structure.add_child
    remove_child = structure.remove_child

    # Замена текстуры своей картинкой (texture_replace.py)
    set_system_texture = texture_replace.set_system_texture
    set_material_texture = texture_replace.set_material_texture
    _overwrite_texture = texture_replace.overwrite_texture
    _resolve_texture_path = texture_replace.resolve_texture_path
    _gif_to_sheet = staticmethod(texture_replace.gif_to_sheet)
    _image_to_vtf = staticmethod(texture_replace.image_to_vtf)
    is_custom_material = texture_replace.is_custom_material
    reset_material_texture = texture_replace.reset_material_texture

    # Родные цвета текстуры (texture_colors.py)
    use_texture_colors = texture_colors.use_texture_colors

    # Запись наружу: сжатый PCF и VPK-мод (export.py)
    pcf_vpk_path = export.pcf_vpk_path
    _active_custom_files = export.active_custom_files
    export_vpk = export.export_vpk
    serialized_size = export.serialized_size
    casual_size_overflow = export.casual_size_overflow
    save = export.save

    # Каталог игры (catalog.py, param_reference.py)
    # Состояние общее на процесс и живёт здесь, атрибутами класса: функции
    # каталога получают класс (cls) и пишут в него

    #: Кэш каталогов параметров: {(группа|None, fn_lower): {имя: {"t","v"}}}
    _attr_catalog: Dict[tuple, Dict[str, dict]] = {}
    #: Каноническое написание functionName: {(группа, fn_lower): "Имя Как В Игре"}
    _module_display: Dict[tuple, str] = {}
    #: Каноническое написание ИМЁН АТРИБУТОВ, как их пишет игра:
    #: {(группа, fn_lower): {имя_в_нижнем: "Имя Как В Игре"}}.
    #: КРИТИЧНО: Source читает атрибуты С УЧЁТОМ РЕГИСТРА - записанный
    #: строчными 'spin strength' игра игнорирует, ей нужен 'Spin Strength'
    _attr_canonical: Dict[tuple, Dict[str, str]] = {}
    #: Кэш списка игровых particle-материалов. Наполняется в том же проходе,
    #: что и каталог параметров (build_attr_catalog), и живёт на диске
    _game_materials_cache: Optional[List[str]] = None
    #: Все системы игры: {имя: путь PCF}. Собирается тем же проходом, что
    #: каталог параметров: эффект ищут по имени, а не по файлу из 134
    _system_index: Dict[str, str] = {}
    #: {дочерняя система: корневая}. Корней нет в словаре - они сами
    #: корни. Список игры сворачивает детей под корень: у эффекта из
    #: тридцати систем человеку нужна одна строка, а не тридцать
    _system_roots: Dict[str, str] = {}
    #: Поток фонового скана каталога - один на процесс
    _catalog_thread = None

    list_game_pcfs = staticmethod(catalog.list_game_pcfs)
    game_effect_materials = classmethod(catalog.game_effect_materials)
    canonical_attr_name = classmethod(catalog.canonical_attr_name)
    _attr_catalog_file = staticmethod(catalog.attr_catalog_file)
    _game_stamp = staticmethod(catalog.game_stamp)
    _load_disk_catalog = classmethod(catalog.load_disk_catalog)
    build_attr_catalog = classmethod(catalog.build_attr_catalog)
    system_roots = classmethod(catalog.system_roots)
    system_index = classmethod(catalog.system_index)
    _track_range = staticmethod(catalog.track_range)
    attr_stats = classmethod(catalog.attr_stats)
    module_attr_catalog = classmethod(catalog.module_attr_catalog)
    group_module_catalog = classmethod(catalog.group_module_catalog)
    missing_attrs = catalog.missing_attrs
    param_reference = classmethod(reference.param_reference)
    _param_reference_entry = staticmethod(reference.param_reference_entry)
