"""
Инструменты: извлечь модель и текстуры из игры, экспорт файлов модели,
объединение модов

Инструмент один на сеанс: две декомпиляции разом дерутся за один
временный каталог. Результат пишется в папку экспорта из настроек
(`_export_settings` сеанса), прогресс и итог уходят событиями страницы

Доступ - `session().tools`; `api.py` зовёт его методы напрямую
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from src.shared.logging_config import get_logger

if TYPE_CHECKING:
    from src.app.session import AppSession

logger = get_logger(__name__)


class ToolsEditor:
    """Извлечение из игры, экспорт и объединение модов"""

    def __init__(self, host: "AppSession") -> None:
        self._host = host
        #: Текущий воркер-инструмент (извлечение, экспорт, объединение)
        self._tool = None
        #: Подготовленная декомпиляция модели: ждёт выбора файлов на странице.
        #: Пока она жива, за ней числится временный каталог
        self._prepared: Optional[Dict[str, Any]] = None

    def _run_tool(self, worker, done: str = 'tool_done') -> Dict[str, Any]:
        """
        Запускает воркер-инструмент и переводит его сигналы в события

        Инструмент один на сеанс: две декомпиляции разом дерутся за один
        временный каталог - в приложении это ровно та же проверка
        (``_worker_busy``)
        """
        worker.progress.connect(lambda pct, text: self._host._put('progress', text=text))
        worker.finished.connect(
            lambda ok, msg: self._host._put(done, ok=bool(ok), message=msg))
        worker.error.connect(
            lambda msg: self._host._put(done, ok=False, message=msg))
        self._tool = worker
        worker.start()
        return {'started': True}

    def _tool_busy(self) -> bool:
        return self._tool is not None and self._tool.isRunning()

    def extract_model(self, lang: str = 'ru') -> Dict[str, Any]:
        """
        Декомпилирует модель предмета и отдаёт список готовых файлов

        Операция двухшаговая, как и в приложении: сначала файлы готовятся во
        временном каталоге, потом человек выбирает, что из них сохранить
        (``export_model_files``). Список приезжает событием ``extract_files``
        """
        from src.domain.preview.model_key import model_key_for

        mode = getattr(self._host, '_mode', '')
        # Ключ предмета берём тот же, по которому грузилось превью: у шапок он
        # свой на каждую вещь и из режима не выводится
        key = self._host.preview.weapon_key or model_key_for(mode)
        if not key:
            return {'error': f'Для режима «{mode}» модели нет'}

        paths = self._host.tf2_paths()
        if 'error' in paths:
            return paths
        if self._tool_busy():
            return {'error': 'Извлечение уже идёт'}

        from src.services.extract_model_worker import ExtractModelWorker
        w = ExtractModelWorker(tf2_root_dir=paths['root'], mode=mode,
                               weapon_key=key, language=lang)
        w.progress.connect(lambda pct, text: self._host._put('progress', text=text))
        w.finished.connect(lambda ok, msg: self._model_prepared(w, ok, msg))
        w.error.connect(lambda msg: self._host._put('extract_files', ok=False,
                                              message=msg, files=[], selected=[]))
        self._tool = w
        w.start()
        return {'started': True}

    def _model_prepared(self, worker, ok: bool, message: str) -> None:
        """Файлы готовы во временном каталоге - ждём выбора страницы"""
        from src.services.extract_model_service import ExtractModelService

        files = list(getattr(worker, 'prepared_files', None) or [])
        temp = getattr(worker, 'prepared_temp_dir', None)
        decompile = getattr(worker, 'prepared_decompile_dir', None)
        if not (ok and files and temp and decompile):
            if temp:
                ExtractModelService.cleanup_temp_dir(temp)
            self._prepared = None
            self._host._put('extract_files', ok=False, message=message,
                      files=[], selected=[])
            return

        self._prepared = {'temp': temp, 'decompile': decompile,
                          'key': worker.weapon_key}
        self._host._put('extract_files', ok=True, message=message, files=files,
                  selected=ExtractModelService.default_export_selection(files))

    def export_model_files(self, files: Optional[List[str]] = None,
                           lang: str = 'ru') -> Dict[str, Any]:
        """
        Сохраняет выбранные файлы модели в папку экспорта

        Пустой список - отказ: временный каталог тогда убирается сразу, иначе
        декомпиляция висела бы в temp до перезапуска
        """
        from src.services.extract_model_service import ExtractModelService

        prepared = self._prepared
        if not prepared:
            return {'error': 'Сначала извлеките модель'}

        chosen = [f for f in (files or []) if f]
        if not chosen:
            ExtractModelService.cleanup_temp_dir(prepared['temp'])
            self._prepared = None
            return {'cancelled': True}
        if self._tool_busy():
            return {'error': 'Извлечение уже идёт'}

        export_folder, _ = self._host._export_settings()
        from src.services.export_model_files_worker import ExportModelFilesWorker
        w = ExportModelFilesWorker(
            temp_dir=prepared['temp'],
            decompile_dir=prepared['decompile'],
            selected_files=chosen,
            export_folder=export_folder,
            weapon_key=prepared['key'],
            language=lang,
        )
        self._prepared = None
        return self._run_tool(w)

    def character_textures(self) -> List[str]:
        """
        Текстуры персонажа в игровом VPK - из них выбирают, что извлекать

        У тела персонажа их бывает под два десятка (лицо, части формы,
        экипировка), поэтому приложение спрашивает, а не тащит всё подряд
        """
        from src.data.player_characters import PLAYER_CHARACTERS

        folder = PLAYER_CHARACTERS.get(getattr(self._host, '_mode', ''), {}).get('folder')
        if not folder:
            return []
        paths = self._host.tf2_paths()
        if 'error' in paths:
            return []

        from src.services.vpk_cache import open_vpk_cached
        try:
            pak = open_vpk_cached(paths['textures_vpk'])
        except OSError as exc:
            logger.warning(f"не открыть VPK текстур: {exc}")
            return []
        if pak is None:
            return []

        prefix = f"materials/models/player/{folder}/"
        return sorted(
            path[len(prefix):-4] for path in pak
            if path.startswith(prefix) and path.lower().endswith('.vtf')
            and '/' not in path[len(prefix):]
        )

    def extract_texture(self, textures: Optional[List[str]] = None,
                        lang: str = 'ru') -> Dict[str, Any]:
        """
        Извлекает оригинальные текстуры предмета в папку экспорта

        У тела персонажа выбор обязателен: без списка возвращается
        ``need_textures`` - страница спрашивает, что брать, и зовёт снова
        """
        from src.data.player_characters import (
            PLAYER_BODY_MODE_KEYS, PLAYER_CHARACTERS,
        )
        from src.data.player_hands import HAND_MODE_KEYS, get_hand_textures
        from src.data.weapons import SPECIAL_MODES
        from src.domain.preview.model_key import model_key_for

        mode = getattr(self._host, '_mode', '')
        if not mode:
            return {'error': 'Сначала выберите предмет'}
        if mode in SPECIAL_MODES:
            return {'error': 'Для этого режима оригинальной текстуры нет'}

        paths = self._host.tf2_paths()
        if 'error' in paths:
            return paths
        if self._tool_busy():
            return {'error': 'Извлечение уже идёт'}

        export_folder, export_format = self._host._export_settings()

        # Шапка: своя цепочка QC -> VMT -> $baseTexture, у каждой вещи своя модель
        if mode == 'hat':
            key = self._host.preview.weapon_key
            if not key:
                return {'error': 'Сначала выберите шапку'}
            from src.services.hat_texture_extract_worker import HatTextureExtractWorker
            return self._run_tool(HatTextureExtractWorker(
                hat_mdl_path=key, tf2_root_dir=paths['root'],
                export_folder=export_folder, export_format=export_format,
                language=lang))

        is_body = mode in PLAYER_BODY_MODE_KEYS

        if is_body:
            if not textures:
                return {'need_textures': self.character_textures()}
            folder = PLAYER_CHARACTERS.get(mode, {}).get('folder', '')
            explicit = [(folder, name) for name in textures]
        elif mode in HAND_MODE_KEYS:
            explicit = get_hand_textures(mode)
        else:
            explicit = None

        # У рук ключ - модель предплечья: под ним лежит QC в кэше декомпиляции,
        # и служба берёт из него ПОЛНЫЙ $texturegroup - те же текстуры, что
        # положит сборка (список в player_hands бывает неполным)
        #
        # У тела персонажа ключ не передаём НАМЕРЕННО: там список выбрал
        # человек, и подмена его группой из QC вернула бы всё подряд
        key = '' if is_body else model_key_for(mode)
        if not key and not is_body:
            return {'error': f'Для режима «{mode}» текстуры не найти'}

        from src.services.extract_texture_worker import ExtractTextureWorker
        return self._run_tool(ExtractTextureWorker(
            textures_vpk_path=paths['textures_vpk'],
            weapon_key=key,
            export_folder=export_folder,
            export_format=export_format,
            language=lang,
            hand_textures=explicit,
            use_explicit_list=bool(explicit),
        ))

    def export_vpks(self) -> List[str]:
        """Имена собранных модов в папке экспорта - из них выбирают, что слить"""
        from pathlib import Path
        export_folder, _ = self._host._export_settings()
        folder = Path(export_folder)
        if not folder.is_dir():
            return []
        return sorted((f.name for f in folder.glob('*.vpk')), key=str.lower)

    def merge_vpk(self, files: Optional[List[str]] = None, name: str = '',
                  confirmed: bool = False, lang: str = 'ru') -> Dict[str, Any]:
        """
        Сливает несколько модов из папки экспорта в один VPK

        Моды, трогающие одно оружие, друг друга затирают - о таких сначала
        предупреждаем (``duplicates``) и ждём подтверждения, как это делает
        окно приложения
        """
        from pathlib import Path
        from src.services.merge_vpk_service import MergeVPKService

        chosen = [f for f in (files or []) if f]
        if len(chosen) < 2:
            return {'error': 'Выберите хотя бы два мода'}
        if not name.strip():
            return {'error': 'Задайте имя выходного файла'}
        if self._tool_busy():
            return {'error': 'Объединение уже идёт'}

        export_folder, _ = self._host._export_settings()
        # От страницы берём только имена: путь собираем сами, иначе она могла бы
        # указать файл за пределами папки экспорта
        paths = [Path(export_folder) / Path(f).name for f in chosen]
        missing = [p.name for p in paths if not p.is_file()]
        if missing:
            return {'error': 'Не найдены: ' + ', '.join(missing)}

        if not confirmed:
            duplicates = MergeVPKService.check_duplicate_weapons(paths)
            if duplicates:
                return {'duplicates': {str(k): list(v) for k, v in duplicates.items()}}

        from src.services.merge_vpk_worker import MergeVpkWorker
        return self._run_tool(MergeVpkWorker(paths, name.strip(), export_folder, lang))
