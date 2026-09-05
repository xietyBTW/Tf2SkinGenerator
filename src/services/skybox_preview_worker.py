"""
Воркеры превью скайбокса.

SkyboxFacesWorker — извлекает 6 стоковых граней выбранного неба из VPK игры
(VMT → $basetexture → VTF; фолбэк — прямые пути, см. `stock_face_stems`:
у стоковых небес VMT ссылается на текстуру, которой в игре нет) и конвертирует
в PNG.
"""

from typing import List

from src.services.base_worker import Signal

from src.data.skyboxes import SKY_FACES, stock_face_stems
from src.services.base_worker import BaseWorker
from src.services.game_vpk_reader import GameVpkReader
from src.services.vtf_preview_service import vtf_bytes_to_png
from src.shared.file_utils import get_temp_file_path
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class SkyboxSplitWorker(BaseWorker):
    """Режет панораму на 6 граней в фоне (numpy, для превью — 512px)."""

    ready = Signal(object)   # {face: png_path}
    failed = Signal(str)

    PREVIEW_FACE_SIZE = 512

    def __init__(self, equirect_path: str, parent=None,
                 face_size: int = PREVIEW_FACE_SIZE):
        super().__init__(parent)
        self._equirect_path = equirect_path
        self._face_size = face_size

    def run(self) -> None:
        try:
            import tempfile

            from src.services.skybox_service import SkyboxService
            # ВАЖНО: mkdtemp (папка), не get_temp_file_path — тот создаёт ФАЙЛ,
            # и os.makedirs внутри нарезки падал бы с FileExistsError.
            out_dir = tempfile.mkdtemp(prefix="tf2_sky_split_")
            faces = SkyboxService.split_equirect_to_faces(
                self._equirect_path, self._face_size, out_dir,
                cancel_callback=self.isInterruptionRequested)
            if self.isInterruptionRequested():
                return
            self.ready.emit(faces)
        except Exception as exc:
            logger.warning(f"[SKYBOX] нарезка панорамы: {exc}", exc_info=True)
            self.failed.emit(str(exc))


class SkyboxFacesWorker(BaseWorker):
    """Готовит PNG стоковых граней неба для 3D-превью."""

    ready = Signal(object)   # {face: png_path} (недостающие грани опущены)
    failed = Signal(str)

    def __init__(self, sky_name: str, vpk_paths: List[str], parent=None):
        super().__init__(parent)
        self._sky_name = sky_name
        self._vpk_paths = [p for p in vpk_paths if p]

    def run(self) -> None:
        try:
            faces = self._extract_faces()
            if self.isInterruptionRequested():
                return
            self.ready.emit(faces)
        except Exception as exc:
            logger.warning(f"[SKYBOX] извлечение граней {self._sky_name}: {exc}")
            self.failed.emit(str(exc))

    def _extract_faces(self) -> dict:
        reader = GameVpkReader(self._vpk_paths)
        result = {}
        for face in SKY_FACES:
            if self.isInterruptionRequested():
                return result
            data = self._read_face_vtf(reader, face)
            if data is None:
                logger.debug(f"[SKYBOX] грань не найдена: {self._sky_name}{face}")
                continue
            out_png = str(get_temp_file_path(
                prefix=f"tf2_sky_{self._sky_name}_{face}_", suffix=".png"))
            png = vtf_bytes_to_png(data, out_png)
            if png:
                result[face] = png
        return result

    def _read_face_vtf(self, reader: GameVpkReader, face: str):
        """VTF грани: через $basetexture VMT-ки, иначе по прямым именам.

        Прямой путь — не запасной вариант, а основной для стоковых небес: их
        VMT-ки ссылаются на `skybox/cloud<грань>`, которой в игре нет, а сами
        текстуры лежат под `<имя>side` одной на все четыре боковые грани. Пока
        имя строилось как `<имя><грань>`, у любого стокового неба находились
        только верх и низ, а бока в превью оставались пустыми.
        """
        vmt = reader.read(f"materials/skybox/{self._sky_name}{face}.vmt")
        if vmt is not None:
            base = GameVpkReader.parse_basetexture(
                vmt.decode("utf-8", errors="replace"))
            if base:
                data = reader.find_vtf_for_basetexture(base)
                if data is not None:
                    return data
        for stem in stock_face_stems(self._sky_name, face):
            data = reader.read(f"materials/skybox/{stem}.vtf")
            if data is not None:
                return data
        return None
