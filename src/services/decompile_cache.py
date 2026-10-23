"""
Кэш декомпилированных моделей TF2

Crowbar decompile - самый долгий шаг (10-30 сек).
Плюс extract_file_set - ещё 3-10 сек.
Вместе это ~15-40 секунд которые можно сэкономить

Ключ кэша = weapon_key + mdl_rel_path + mtime VPK файла.
  - mtime VPK меняется при обновлении TF2 -> кэш автоматически инвалидируется.
  - Проверка mtime мгновенная (один stat() вызов).
  - На cache hit: пропускаем и extraction, и decompile
"""

import hashlib
import json
import os
import shutil
import threading
import uuid
from pathlib import Path
from typing import Optional

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

_CACHE_DIR = Path(os.path.expanduser("~")) / ".tf2skingen_cache" / "decompiled"
_META_FILENAME = "_cache_meta.json"
_CACHE_VERSION = 4  # v3: vpk_mtime вместо mdl_hash; v4: SMD дописаны геометрией, которую терял Crowbar (mdl_mesh)

# Мягкий потолок размера кэша. После сохранения новой записи кэш само-урезается
# до этого размера, удаляя самые давно использованные записи (LRU по mtime папки;
# mtime «трогается» на cache hit). Без лимита кэш рос бы бесконечно. <=0 - выкл.
# Это умолчание: человек выбирает потолок в настройках (`model_cache_mb`)
_CACHE_MAX_MB = 1024

#: Превью и поиск стилей разбирают одну модель параллельно и оба несут её в
#: кэш: rmtree одного стирал copytree другого, и в записи оставались метаданные
#: без QC. Пишем по одному, второй застаёт готовую запись и не трогает её
_SAVE_LOCK = threading.Lock()

#: Метаданные записей в памяти: find_* зовутся по нескольку раз на загрузку
#: превью, а чтение всех meta.json с диска стоит десятки мс. Читается с диска
#: один раз на папку кэша, дальше его правят сохранение и удаление записей
_INDEX_LOCK = threading.Lock()
_index: dict = {}                      # имя папки записи -> meta
_index_root: Optional[Path] = None

#: Обходы лимита по одному: фоновый после сохранения и вызов из настроек
_LIMIT_LOCK = threading.Lock()


def get_cache_dir() -> Path:
    """Возвращает папку кэша, создаёт если нет"""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return _CACHE_DIR


def _vpk_mtime(vpk_path: str) -> str:
    """Время модификации VPK файла - меняется при обновлении игры"""
    try:
        mtime = os.path.getmtime(vpk_path)
        return f"{mtime:.0f}"
    except OSError:
        return "0"


def _cache_key(weapon_key: str, vpk_path: str, mdl_rel_path: str) -> str:
    """
    Ключ кэша на основе оружия, VPK файла и пути к MDL.
    Используем hash чтобы избежать проблем с длинными путями
    """
    raw = f"{weapon_key}|{vpk_path}|{mdl_rel_path}|{_vpk_mtime(vpk_path)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _meta_path(cache_entry_dir: Path) -> Path:
    return cache_entry_dir / _META_FILENAME


def _entries(root: Optional[Path] = None) -> list:
    """[(папка записи, meta)] из индекса"""
    global _index, _index_root
    root = root or get_cache_dir()
    with _INDEX_LOCK:
        if _index_root != root:
            _index, _index_root = _scan(root), root
        return [(root / name, meta) for name, meta in _index.items()]


def _scan(root: Path) -> dict:
    found = {}
    for meta_file in root.glob(f"*/{_META_FILENAME}"):
        if ".tmp-" in meta_file.parent.name:
            continue                    # запись ещё собирается, см. _save_to_cache
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                found[meta_file.parent.name] = json.load(f)
        except (OSError, ValueError):
            continue
    return found


def _index_put(entry_dir: Path, meta: dict) -> None:
    with _INDEX_LOCK:
        if _index_root == entry_dir.parent:
            _index[entry_dir.name] = meta


def _remove_entry(entry_dir: Path) -> None:
    shutil.rmtree(entry_dir, ignore_errors=True)
    with _INDEX_LOCK:
        if _index_root == entry_dir.parent:
            _index.pop(entry_dir.name, None)


def _data_size(entry_dir: Path) -> int:
    return sum(f.stat().st_size for f in entry_dir.rglob("*")
               if f.is_file() and not f.name.startswith(_META_FILENAME))


def get_cached_decompile(
    weapon_key: str,
    vpk_path: str,
    mdl_rel_path: str,
) -> Optional[str]:
    """
    Проверяет кэш **до** extraction - только по mtime VPK

    Args:
        weapon_key:   Ключ оружия (например "c_flaregun_pyro")
        vpk_path:     Путь к tf2_misc_dir.vpk
        mdl_rel_path: Относительный путь к MDL внутри VPK

    Returns:
        Путь к закэшированной папке с QC/SMD, или None при промахе
    """
    try:
        key = _cache_key(weapon_key, vpk_path, mdl_rel_path)
        entry_dir = get_cache_dir() / key

        if not entry_dir.exists():
            logger.debug(f"Кэш декомпила не найден: {weapon_key}")
            return None

        meta_file = _meta_path(entry_dir)
        if not meta_file.exists():
            _remove_entry(entry_dir)
            return None

        with open(meta_file, "r", encoding="utf-8") as f:
            meta = json.load(f)

        if meta.get("version") != _CACHE_VERSION:
            logger.info(f"Версия кэша устарела для {weapon_key}, сбрасываем")
            _remove_entry(entry_dir)
            return None

        # Проверяем что VPK не изменился (дополнительная страховка)
        stored_mtime = meta.get("vpk_mtime", "")
        current_mtime = _vpk_mtime(vpk_path)
        if stored_mtime != current_mtime:
            logger.info(f"VPK обновился, кэш для {weapon_key} недействителен")
            _remove_entry(entry_dir)
            return None

        # Проверяем что QC файл на месте
        qc_name = meta.get("qc_filename")
        if not qc_name or not (entry_dir / qc_name).exists():
            logger.warning(f"QC файл в кэше не найден: {weapon_key}")
            _remove_entry(entry_dir)
            return None

        # Cache hit - обновляем mtime записи, чтобы LRU-эвикция
        # (enforce_cache_limit) считала её свежеиспользованной
        try:
            os.utime(entry_dir, None)
        except OSError:
            pass

        logger.info(f"Кэш декомпила: {weapon_key} - пропускаем extraction + decompile")
        return str(entry_dir)

    except Exception as e:
        logger.warning(f"Ошибка при чтении кэша декомпила: {e}")
        return None


def find_same_model(vpk_path: str, mdl_rel_path: str) -> Optional[str]:
    """
    Готовая запись ТОЙ ЖЕ модели под другим ключом, либо None

    Ключ записи - логический (оружие, `__player_heavy`, путь шапки), и одну
    модель разные части приложения называли по-своему: модель класса лежала
    в кэше трижды (`heavy`, `models/player/heavy.mdl`, `__player_heavy`) -
    три запуска Crowbar. Годность та же, что у `get_cached_decompile`
    """
    want = mdl_rel_path.replace("\\", "/").lower()
    stamp = _vpk_mtime(vpk_path)
    for entry, meta in _entries():
        if (meta.get("version") == _CACHE_VERSION
                and meta.get("vpk_mtime") == stamp
                and os.path.normcase(str(meta.get("vpk_path") or "")) == os.path.normcase(vpk_path)
                and str(meta.get("mdl_rel_path") or "").replace("\\", "/").lower() == want
                and (entry / str(meta.get("qc_filename") or "")).is_file()):
            return str(entry)
    return None


def _purge_stale_entries(weapon_key: str, mdl_rel_path: str, keep_key: str) -> None:
    """
    Удаляет записи того же оружия с устаревшим mtime VPK

    mtime входит в ключ кэша, поэтому после обновления игры старые записи
    становятся недостижимыми, но без этой очистки копились бы бесконечно
    """
    try:
        for entry, meta in _entries():
            if entry.name == keep_key:
                continue
            if (meta.get("weapon_key") == weapon_key
                    and meta.get("mdl_rel_path") == mdl_rel_path):
                _remove_entry(entry)
                logger.debug(f"Удалена устаревшая запись кэша: {entry.name} ({weapon_key})")
    except Exception as e:
        logger.warning(f"Ошибка очистки устаревшего кэша для {weapon_key}: {e}")


def save_to_cache(
    weapon_key: str,
    vpk_path: str,
    mdl_rel_path: str,
    decompile_dir: str,
) -> Optional[str]:
    """
    Сохраняет декомпилированные файлы в кэш

    Args:
        weapon_key:    Ключ оружия
        vpk_path:      Путь к VPK файлу
        mdl_rel_path:  Относительный путь MDL в VPK
        decompile_dir: Папка с QC + SMD после Crowbar

    Returns:
        Путь к папке записи кэша, или None при ошибке
    """
    with _SAVE_LOCK:
        return _save_to_cache(weapon_key, vpk_path, mdl_rel_path, decompile_dir)


def _save_to_cache(weapon_key: str, vpk_path: str, mdl_rel_path: str,
                   decompile_dir: str) -> Optional[str]:
    staging: Optional[Path] = None
    try:
        ready = get_cached_decompile(weapon_key, vpk_path, mdl_rel_path)
        if ready:
            return ready                # сосед успел раньше - запись целая

        key = _cache_key(weapon_key, vpk_path, mdl_rel_path)
        entry_dir = get_cache_dir() / key

        _purge_stale_entries(weapon_key, mdl_rel_path, keep_key=key)

        # Запись собирается рядом и встаёт под свой ключ одним переименованием.
        # Читатель (get_cached_decompile) идёт без замка: застав папку посреди
        # copytree ещё без метаданных, он считал её битой и стирал - копия
        # падала с WinError 3
        staging = entry_dir.with_name(f"{key}.tmp-{uuid.uuid4().hex[:8]}")
        shutil.copytree(decompile_dir, staging)

        # Имя QC
        qc_name = None
        for f in Path(decompile_dir).iterdir():
            if f.suffix.lower() == ".qc":
                qc_name = f.name
                break

        meta = {
            "version": _CACHE_VERSION,
            "weapon_key": weapon_key,
            "vpk_path": vpk_path,
            "mdl_rel_path": mdl_rel_path,
            "vpk_mtime": _vpk_mtime(vpk_path),
            "qc_filename": qc_name,
            # Для лимита: иначе каждое сохранение обходило бы все файлы кэша
            "size": _data_size(staging),
        }
        with open(_meta_path(staging), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        if entry_dir.exists():
            shutil.rmtree(entry_dir)
        os.rename(staging, entry_dir)
        _index_put(entry_dir, meta)

        logger.info(f"Кэш декомпила сохранён: {weapon_key}")

        # В фоне: сохранение идёт внутри загрузки превью и держит _SAVE_LOCK.
        # Потолок и папку берём сейчас, чтобы поток не увидел чужие
        threading.Thread(target=enforce_cache_limit, args=(_limit_mb(), get_cache_dir()),
                         daemon=True, name="decompile-cache-limit").start()
        return str(entry_dir)

    except Exception as e:
        logger.warning(f"Не удалось сохранить кэш декомпила: {e}")
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)
        return None


def _limit_mb() -> float:
    """Потолок из настроек (вкладка «Обслуживание»); 0 - без ограничения"""
    try:
        from src.config.app_config import AppConfig
        return float(AppConfig.get('model_cache_mb', _CACHE_MAX_MB))
    except Exception:                                         # noqa: BLE001
        return _CACHE_MAX_MB


def enforce_cache_limit(max_mb: Optional[float] = None, root: Optional[Path] = None) -> int:
    """Удаляет самые давно использованные записи, пока кэш не уложится в max_mb

    LRU приближается через mtime папки записи (трогается на cache hit в
    get_cached_decompile). Запись - атомарная единица удаления. Метафайл записи
    учитывается в её размере. None - потолок из настроек; <=0 - лимит отключён

    Returns:
        Количество удалённых записей
    """
    if max_mb is None:
        max_mb = _limit_mb()
    if not max_mb or max_mb <= 0:
        return 0
    with _LIMIT_LOCK:
        return _enforce_cache_limit(max_mb, root or get_cache_dir())


def _enforce_cache_limit(max_mb: float, root: Path) -> int:
    try:
        sized = []          # (mtime, size_bytes, entry_dir)
        total = 0
        for entry, meta in _entries(root):
            try:
                if meta.get("size") is None:
                    _store_size(entry, meta)
                size = meta["size"] + _meta_path(entry).stat().st_size
                mtime = entry.stat().st_mtime
            except OSError:
                continue
            total += size
            sized.append((mtime, size, entry))

        limit = max_mb * 1024 * 1024
        if total <= limit:
            return 0

        # Старые (меньший mtime = давно используемые) - первыми под нож
        sized.sort(key=lambda x: x[0])
        removed = 0
        for _mtime, size, entry in sized:
            if total <= limit:
                break
            _remove_entry(entry)
            total -= size
            removed += 1
            logger.debug(
                f"Эвикция кэша декомпила (LRU): {entry.name}, "
                f"освобождено {size / (1024 * 1024):.1f} МБ"
            )
        if removed:
            logger.info(
                f"Кэш декомпила превысил {max_mb:.0f} МБ - удалено записей: {removed}"
            )
        return removed
    except Exception as e:
        logger.warning(f"Ошибка эвикции кэша декомпила: {e}")
        return 0


def _store_size(entry: Path, meta: dict) -> None:
    """Размер записи из прошлых версий: считаем один раз и пишем в meta"""
    meta["size"] = _data_size(entry)
    tmp = entry / f"{_META_FILENAME}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    os.replace(tmp, _meta_path(entry))     # читатель не застанет полфайла


def restore_from_cache(cache_dir: str, target_dir: str) -> str:
    """
    Копирует QC/SMD из кэша в рабочую директорию

    Returns:
        Путь к QC файлу в target_dir
    """
    cache_path = Path(cache_dir)
    target_path = Path(target_dir)
    target_path.mkdir(parents=True, exist_ok=True)

    shutil.copytree(
        cache_path, target_path,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(_META_FILENAME + "*"),
    )

    qc_name = None
    if _meta_path(cache_path).is_file():     # temp-папка Crowbar приходит без meta
        with open(_meta_path(cache_path), "r", encoding="utf-8") as f:
            qc_name = json.load(f).get("qc_filename")
    if qc_name and (target_path / qc_name).exists():
        return str(target_path / qc_name)

    for f in target_path.iterdir():
        if f.suffix.lower() == ".qc":
            return str(f)

    raise RuntimeError(f"QC file not found after restoring from cache in {target_dir}")


def find_cached_qc_for_weapon(weapon_key: str) -> Optional[str]:
    """
    Ищет в кэше декомпиляции QC-файл для любого варианта weapon_key
    (не требует знать точный vpk_path или mdl_rel_path)

    Используется, например, при извлечении текстуры шапки - чтобы
    узнать реальное имя текстуры из $texturegroup, а не угадывать его
    по имени MDL-файла

    Returns:
        Полный путь к QC-файлу или None если кэша нет
    """
    try:
        for entry, meta in _entries():
            if meta.get("weapon_key") != weapon_key:
                continue
            if meta.get("version") != _CACHE_VERSION:
                continue
            # Запись от старой версии VPK (игра обновилась) -> пропускаем,
            # иначе вернём устаревший QC
            stored_vpk = meta.get("vpk_path", "")
            if stored_vpk and meta.get("vpk_mtime", "") != _vpk_mtime(stored_vpk):
                logger.debug(f"Кэш QC для {weapon_key} устарел (VPK обновился), пропускаем")
                continue
            qc_name = meta.get("qc_filename")
            if not qc_name:
                continue
            qc_path = entry / qc_name
            if qc_path.exists():
                logger.debug(f"QC найден в кэше для {weapon_key}: {qc_path}")
                return str(qc_path)
    except Exception as e:
        logger.warning(f"Ошибка поиска QC в кэше для {weapon_key}: {e}")
    return None


def clear_cache(weapon_key: Optional[str] = None) -> int:
    """
    Очищает кэш

    Args:
        weapon_key: Если указан - только для этого оружия. None - весь кэш

    Returns:
        Количество удалённых записей
    """
    cache_dir = get_cache_dir()
    count = 0
    try:
        if weapon_key is None:
            targets = [e for e in cache_dir.iterdir() if e.is_dir()]
        else:
            targets = [e for e, meta in _entries(cache_dir)
                       if meta.get("weapon_key") == weapon_key]
        for entry in targets:
            _remove_entry(entry)
            count += 1
    except Exception as e:
        logger.warning(f"Ошибка при очистке кэша: {e}")
    return count


def get_cache_size_mb() -> float:
    """Размер кэша в МБ"""
    try:
        total = sum(
            f.stat().st_size
            for f in get_cache_dir().rglob("*")
            if f.is_file()
        )
        return total / (1024 * 1024)
    except Exception:
        return 0.0
