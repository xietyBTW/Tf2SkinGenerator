"""Запись документа наружу: сжатый PCF и VPK-мод с текстурами"""

import io
import tempfile
from pathlib import Path
from typing import Dict, Optional

from src.services.particle_editor.pcf_format import Element, ValueType, norm_mat
from src.shared.logging_config import get_logger

logger = get_logger(__name__)

#: Атрибуты со значениями по умолчанию Source: при экспорте вырезаются
#: (lossless - игра/превью подставляют те же дефолты). Присутствуют почти на
#: каждом операторе/рендерере, поэтому дают килобайты экономии. Это нужно,
#: чтобы модифицированный PCF влез в слот VPK: casual-bypass не грузит PCF
#: больше оригинала (та же причина, по которой у casual-pre-loader есть
#: pcf_compress). Значения - как в constants.py casual-pre-loader
_PCF_DEFAULT_ATTRS = {
    "operator start fadein": 0.0,
    "operator end fadein": 0.0,
    "operator start fadeout": 0.0,
    "operator end fadeout": 0.0,
    "operator fade oscillate": 0.0,
    "visibility proxy input control point number": -1,
    "visibility proxy radius": 1.0,
    "visibility input minimum": 0.0,
    "visibility input maximum": 1.0,
    "visibility alpha scale minimum": 0.0,
    "visibility alpha scale maximum": 1.0,
    "visibility radius scale minimum": 1.0,
    "visibility radius scale maximum": 1.0,
    "visibility camera depth bias": 0.0,
}


def pcf_vpk_path(pcf) -> str:
    """Путь PCF внутри VPK-мода (particles/<имя файла>)"""
    src = pcf.source_path or "custom.pcf"
    if src.startswith("vpk:"):
        return src[4:]
    return f"particles/{Path(src).name}"


def active_custom_files(pcf) -> Dict[str, bytes]:
    """Оверрайд-файлы без «сирот»: перезаписи текстур материалов, которые
    больше не используются ни одной системой, в VPK не попадают"""
    used_mats = set()
    for el in pcf._all_definition_elements():
        if "material" in el:
            try:
                used_mats.add(norm_mat(el["material"].val_str))
            except Exception:
                pass
    active_paths = set()
    for k, e in pcf._overwritten.items():
        if k in used_mats:
            active_paths.add(f"materials/{e['tex_rel']}.vtf")
            active_paths.add(f"materials/{k}")  # оригинальный VMT материала
    return {rel: data for rel, data in pcf.custom_files.items()
            if rel in active_paths}


def export_vpk(pcf, dest_path: str, language: str = "en") -> str:
    """
    Собирает VPK-мод: правленый PCF + кастомные материалы

    Args:
        dest_path: полный путь к итоговому .vpk
        language:  язык сообщений об ошибках упаковки

    Returns:
        Путь к созданному VPK
    """
    if pcf.root is None:
        raise RuntimeError("PCF не загружен")
    from src.services.packaging_service import PackagingService

    dest = Path(dest_path)
    pcf.last_textures_vpk = None
    materials = active_custom_files(pcf)
    tmp_root = Path(tempfile.mkdtemp(prefix="tf2sg_particles_"))
    try:
        vpkroot = tmp_root / "vpkroot"
        pcf_dest = vpkroot / pcf_vpk_path(pcf)
        pcf_dest.parent.mkdir(parents=True, exist_ok=True)
        save(pcf, str(pcf_dest))
        for rel, data in materials.items():
            f = vpkroot / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)
        out = PackagingService.pack_directory(
            vpkroot_dir=vpkroot,
            filename=dest.name,
            export_folder=str(dest.parent),
            language=language,
        )
        # Текстурная часть отдельным VPK без PCF: casual-pre-loader
        # относит мод с любым .pcf к партикл-пакам и материалы из него
        # не устанавливает - аддоном он увидит только чистый vpk
        if materials:
            texroot = tmp_root / "texroot"
            for rel, data in materials.items():
                f = texroot / rel
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(data)
            pcf.last_textures_vpk = PackagingService.pack_directory(
                vpkroot_dir=texroot,
                filename=f"{dest.stem}_textures.vpk",
                export_folder=str(dest.parent),
                language=language,
            )
        return out
    finally:
        import shutil
        shutil.rmtree(tmp_root, ignore_errors=True)


def serialize_pcf(pcf) -> bytes:
    """
    Сериализует дерево в бинарный PCF, вырезав default-атрибуты (сжатие
    как у casual-pre-loader - чтобы файл влез в слот VPK для казуала)

    Работает на КОПИИ дерева (re-parse собственных байтов): рабочее дерево
    не мутируется, обзор свойств в UI сохраняет все строки

    unicode="silent" ОБЯЗАТЕЛЬНО: "format" пишет в заголовок
    "unicode_binary", который парсер DMX игры не знает - TF2 молча
    отбрасывает весь PCF и эффекты пропадают
    """
    enc_ver, fmt_name, fmt_ver = pcf._encoding

    raw0 = io.BytesIO()
    pcf.root.export_binary(
        raw0, version=enc_ver, fmt_name=fmt_name, fmt_ver=fmt_ver,
        unicode="silent")
    copy_root, _, _ = Element.parse(io.BytesIO(raw0.getvalue()))
    strip_default_attrs(copy_root)
    merge_duplicate_elements(copy_root)

    out = io.BytesIO()
    copy_root.export_binary(
        out, version=enc_ver, fmt_name=fmt_name, fmt_ver=fmt_ver,
        unicode="silent")
    return out.getvalue()


def strip_default_attrs(root) -> int:
    """Удаляет из всех элементов дерева атрибуты со значением-дефолтом.
    Lossless: игра и превью подставляют те же дефолты. Возвращает счётчик"""
    removed, seen, stack = 0, set(), [root]
    while stack:
        el = stack.pop()
        if id(el) in seen:
            continue
        seen.add(id(el))
        for key in list(el.keys()):
            attr = el[key]
            if attr.type is ValueType.ELEMENT:
                # спуск в дочерние элементы/массивы элементов
                try:
                    if attr.is_array:
                        for sub in attr.iter_elem():
                            if sub is not None:
                                stack.append(sub)
                    else:
                        sub = attr.val_elem
                        if sub is not None:
                            stack.append(sub)
                except Exception:
                    pass
                continue
            dv = _PCF_DEFAULT_ATTRS.get(attr.name.lower())
            if dv is None:
                continue
            try:
                if attr.type in (ValueType.FLOAT, ValueType.TIME) \
                        and abs(attr.val_float - dv) < 1e-9:
                    del el[key]
                    removed += 1
                elif attr.type is ValueType.INTEGER and attr.val_int == dv:
                    del el[key]
                    removed += 1
            except Exception:
                pass
    return removed


#: Эти элементы различаются именем, а не содержимым: системы игра ищет по
#: имени, сливать их нельзя. casual-pre-loader оставляет первые три, ссылки
#: на дочерние системы мы не сливаем тоже: дочернюю систему движок умеет
#: искать и по имени (ParticleChildrenInfo_t.m_bUseNameBasedLookup), а
#: выигрыш на них - байты
_NAMED_TYPES = {"dmelement", "dmeelement", "dmeparticlesystemdefinition",
                "dmeparticlechild"}


def _element_key(el) -> Optional[tuple]:
    """Содержимое элемента для сравнения: тип и атрибуты, кроме имени.
    None - у элемента есть значение, которое не сравнить (матрица)"""
    attrs = []
    for attr in el.values():
        if attr.name.casefold() == "name":
            continue
        if attr.type is ValueType.ELEMENT:
            subs = list(attr.iter_elem()) if attr.is_array else [attr.val_elem]
            value = tuple(getattr(sub, "uuid", None) for sub in subs)
        else:
            value = tuple(attr._value) if attr.is_array else attr._value
        attrs.append((attr.name.casefold(), attr.type.name, value))
    key = (el.type.casefold(), tuple(sorted(attrs, key=lambda a: a[0])))
    try:
        hash(key)
    except TypeError:
        return None
    return key


def merge_duplicate_elements(root) -> int:
    """
    Одинаковые модули разных систем записываются один раз

    Операторы и инициализаторы в файле эффектов часто повторяются слово в
    слово, и в списках модулей их можно заменить ссылкой на один элемент:
    формат это позволяет, файлы Valve так и устроены. casual-pre-loader
    делает то же перед тем, как вписать PCF в игру, поэтому без этого размер
    файла у нас выходил больше, чем у него. Возвращает число замен
    """
    canon: Dict[tuple, object] = {}
    merged, seen, stack = 0, set(), [root]
    while stack:
        el = stack.pop()
        if el.uuid in seen:
            continue
        seen.add(el.uuid)
        for attr in el.values():
            if attr.type is not ValueType.ELEMENT:
                continue
            if not attr.is_array:
                if attr.val_elem is not None:
                    stack.append(attr.val_elem)
                continue
            for i, sub in enumerate(list(attr.iter_elem())):
                if sub is None:
                    continue
                stack.append(sub)
                if sub.type.casefold() in _NAMED_TYPES:
                    continue
                key = _element_key(sub)
                if key is None:
                    continue
                first = canon.setdefault(key, sub)
                if first is not sub:
                    attr[i] = first
                    merged += 1
    return merged


def serialized_size(pcf) -> int:
    """Размер экспортируемого (сжатого) PCF в байтах"""
    return len(serialize_pcf(pcf))


def size_summary(pcf) -> Dict[str, object]:
    """
    Файл эффектов, его размер в моде и потолок - для сводки внизу страницы

    Размер считается так же, как пишется мод, со сжатием: в казуале PCF
    больше оригинала не загрузится, и узнать об этом лучше до сборки.
    Пусто - файл не открыт или не сериализуется
    """
    if pcf is None or pcf.root is None:
        return {}
    try:
        size = serialized_size(pcf)
    except Exception as exc:                     # noqa: BLE001 - сводка, не сборка
        logger.debug(f"размер PCF для сводки: {exc}")
        return {}
    return {"file": pcf_vpk_path(pcf).rsplit("/", 1)[-1],
            "size": size, "ceiling": pcf._loaded_size}


def casual_size_overflow(pcf) -> Optional[int]:
    """
    На сколько байт сжатый PCF превышает исходный (потолок казуала).
    <= 0 - влезает; > 0 - в казуале не загрузится (бай-пасс не берёт PCF
    больше оригинального слота VPK). None - потолок неизвестен
    """
    ceiling = pcf._loaded_size
    if not ceiling:
        return None
    return serialized_size(pcf) - ceiling


def save(pcf, dest_path: str) -> None:
    """Сохраняет текущее дерево в бинарный (сжатый) PCF"""
    if pcf.root is None:
        raise RuntimeError("PCF не загружен")
    Path(dest_path).write_bytes(serialize_pcf(pcf))
    logger.info(f"PCF сохранён: {dest_path}")
