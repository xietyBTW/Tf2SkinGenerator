import os
from ctypes import POINTER, c_char_p, c_float, c_int, c_uint, c_ubyte, c_void_p, pointer, windll
from pathlib import Path
from threading import Lock

from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class VTFImageFormat:
    RGBA8888 = 0
    ABGR8888 = 1
    RGB888 = 2
    BGR888 = 3
    RGB565 = 4
    I8 = 5
    IA88 = 6
    P8 = 7
    A8 = 8
    RGB888_BLUESCREEN = 9
    BGR888_BLUESCREEN = 10
    ARGB8888 = 11
    BGRA8888 = 12
    DXT1 = 13
    DXT3 = 14
    DXT5 = 15
    BGRX8888 = 16
    BGR565 = 17
    BGRX5551 = 18
    BGRA4444 = 19
    DXT1_ONEBITALPHA = 20
    BGRA5551 = 21
    UV88 = 22
    UVWQ8888 = 23
    RGBA16161616F = 24
    RGBA16161616 = 25
    UVLX8888 = 26
    R32F = 27
    RGB323232F = 28
    RGBA32323232F = 29


class VTFImageFlags:
    POINTSAMPLE = 0x00000001
    TRILINEAR = 0x00000002
    CLAMPS = 0x00000004
    CLAMPT = 0x00000008
    ANISOTROPIC = 0x00000010
    SRGB = 0x00000040
    NORMAL = 0x00000080
    NOMIP = 0x00000100
    NOLOD = 0x00000200
    ONEBITALPHA = 0x00001000
    EIGHTBITALPHA = 0x00002000
    NODEBUGOVERRIDE = 0x00020000
    SINGLECOPY = 0x00040000
    NODEPTHBUFFER = 0x00800000
    CLAMPU = 0x02000000
    VERTEXTEXTURE = 0x04000000
    SSBUMP = 0x08000000
    BORDER = 0x20000000


class VTFLib:
    _lock = Lock()
    _initialized = False
    _dll = None

    @classmethod
    def _load(cls):
        if cls._dll is not None:
            return cls._dll

        vtf_dir = Path("tools/VTF").resolve()
        if not vtf_dir.exists():
            raise FileNotFoundError(f"tools/VTF not found: {vtf_dir}")

        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(vtf_dir))

        dll_path = vtf_dir / "VTFLib.dll"
        if not dll_path.exists():
            raise FileNotFoundError(f"VTFLib.dll not found: {dll_path}")

        cls._dll = windll.LoadLibrary(str(dll_path))

        vlBool = c_int
        vlUInt = c_uint
        vlByte = c_ubyte

        cls._dll.vlInitialize.restype = vlBool
        cls._dll.vlInitialize.argtypes = []

        cls._dll.vlShutdown.restype = None
        cls._dll.vlShutdown.argtypes = []

        cls._dll.vlGetLastError.restype = c_char_p
        cls._dll.vlGetLastError.argtypes = []

        cls._dll.vlCreateImage.restype = vlBool
        cls._dll.vlCreateImage.argtypes = [POINTER(vlUInt)]

        cls._dll.vlDeleteImage.restype = None
        cls._dll.vlDeleteImage.argtypes = [vlUInt]

        cls._dll.vlBindImage.restype = vlBool
        cls._dll.vlBindImage.argtypes = [vlUInt]

        cls._dll.vlImageCreate.restype = vlBool
        cls._dll.vlImageCreate.argtypes = [vlUInt, vlUInt, vlUInt, vlUInt, vlUInt, c_int, vlBool, vlBool, vlBool]

        cls._dll.vlImageDestroy.restype = None
        cls._dll.vlImageDestroy.argtypes = []

        cls._dll.vlImageSetData.restype = None
        cls._dll.vlImageSetData.argtypes = [vlUInt, vlUInt, vlUInt, vlUInt, POINTER(vlByte)]

        cls._dll.vlImageSetFlags.restype = None
        cls._dll.vlImageSetFlags.argtypes = [vlUInt]

        cls._dll.vlImageSave.restype = vlBool
        cls._dll.vlImageSave.argtypes = [c_char_p]

        cls._dll.vlImageComputeMipmapSize.restype = vlUInt
        cls._dll.vlImageComputeMipmapSize.argtypes = [vlUInt, vlUInt, vlUInt, vlUInt, c_int]

        cls._dll.vlImageConvertFromRGBA8888.restype = vlBool
        cls._dll.vlImageConvertFromRGBA8888.argtypes = [POINTER(vlByte), POINTER(vlByte), vlUInt, vlUInt, c_int]

        cls._dll.vlImageGenerateThumbnail.restype = vlBool
        cls._dll.vlImageGenerateThumbnail.argtypes = []

        cls._dll.vlSetFloat.restype = None
        cls._dll.vlSetFloat.argtypes = [c_int, c_float]

        # ── Функции для чтения VTF ──────────────────────────────────────── #
        cls._dll.vlImageLoad.restype = vlBool
        cls._dll.vlImageLoad.argtypes = [c_char_p, vlBool]

        cls._dll.vlImageGetWidth.restype = vlUInt
        cls._dll.vlImageGetWidth.argtypes = []

        cls._dll.vlImageGetHeight.restype = vlUInt
        cls._dll.vlImageGetHeight.argtypes = []

        cls._dll.vlImageGetFormat.restype = c_int
        cls._dll.vlImageGetFormat.argtypes = []

        cls._dll.vlImageGetData.restype = POINTER(vlByte)
        cls._dll.vlImageGetData.argtypes = [vlUInt, vlUInt, vlUInt, vlUInt]

        cls._dll.vlImageConvertToRGBA8888.restype = vlBool
        cls._dll.vlImageConvertToRGBA8888.argtypes = [POINTER(vlByte), POINTER(vlByte), vlUInt, vlUInt, c_int]

        return cls._dll

    @classmethod
    def initialize(cls) -> None:
        with cls._lock:
            dll = cls._load()
            if cls._initialized:
                return
            ok = bool(dll.vlInitialize())
            if not ok:
                err = dll.vlGetLastError()
                raise RuntimeError(err.decode("utf-8", errors="replace") if err else "VTFLib init failed")
            cls._initialized = True

    @classmethod
    def _last_error(cls) -> str:
        dll = cls._load()
        err = dll.vlGetLastError()
        return err.decode("utf-8", errors="replace") if err else "VTFLib error"

    @classmethod
    def create_animated_vtf(
        cls,
        frames_rgba8888: list[bytes],
        width: int,
        height: int,
        dest_format: int,
        flags: int,
        output_file: str,
        generate_thumbnail: bool = True,
    ) -> None:
        cls.initialize()
        dll = cls._load()

        vlUInt = c_uint
        vlByte = c_ubyte
        vlBool = c_int

        img_id = vlUInt(0)
        if not dll.vlCreateImage(pointer(img_id)):
            raise RuntimeError(cls._last_error())
        try:
            if not dll.vlBindImage(img_id.value):
                raise RuntimeError(cls._last_error())

            if not dll.vlImageCreate(
                vlUInt(width),
                vlUInt(height),
                vlUInt(len(frames_rgba8888)),
                vlUInt(1),
                vlUInt(1),
                c_int(dest_format),
                vlBool(0),
                vlBool(0),
                vlBool(1),
            ):
                raise RuntimeError(cls._last_error())

            if flags:
                dll.vlImageSetFlags(vlUInt(flags))

            keepalive_buffers: list[c_void_p] = []
            for i, frame in enumerate(frames_rgba8888):
                if len(frame) != width * height * 4:
                    raise ValueError("Frame size mismatch")

                src = (vlByte * len(frame)).from_buffer_copy(frame)
                if dest_format == VTFImageFormat.RGBA8888:
                    dll.vlImageSetData(vlUInt(i), vlUInt(0), vlUInt(0), vlUInt(0), src)
                    keepalive_buffers.append(src)
                    continue

                dest_size = int(dll.vlImageComputeMipmapSize(vlUInt(width), vlUInt(height), vlUInt(1), vlUInt(0), c_int(dest_format)))
                if dest_size <= 0:
                    raise RuntimeError("Failed to compute dest buffer size")
                dest = (vlByte * dest_size)()
                ok = bool(dll.vlImageConvertFromRGBA8888(src, dest, vlUInt(width), vlUInt(height), c_int(dest_format)))
                if not ok:
                    raise RuntimeError(cls._last_error())
                dll.vlImageSetData(vlUInt(i), vlUInt(0), vlUInt(0), vlUInt(0), dest)
                keepalive_buffers.append(src)
                keepalive_buffers.append(dest)

            if generate_thumbnail:
                try:
                    dll.vlImageGenerateThumbnail()
                except Exception:
                    pass

            out_bytes = str(Path(output_file)).encode("utf-8")
            if not dll.vlImageSave(out_bytes):
                raise RuntimeError(cls._last_error())
            _ = keepalive_buffers
        finally:
            try:
                dll.vlImageDestroy()
            except Exception:
                pass
            try:
                dll.vlDeleteImage(img_id.value)
            except Exception:
                pass

    @classmethod
    def read_vtf_as_rgba(cls, vtf_path: str) -> tuple:
        """
        Загружает VTF файл и возвращает первый кадр в формате RGBA8888.

        Returns:
            (rgba_bytes: bytes, width: int, height: int)

        Raises:
            RuntimeError: если загрузка или конвертация не удалась
        """
        cls.initialize()
        dll = cls._load()

        vlUInt = c_uint
        vlByte = c_ubyte
        vlBool = c_int

        img_id = vlUInt(0)
        if not dll.vlCreateImage(pointer(img_id)):
            raise RuntimeError(cls._last_error())
        try:
            if not dll.vlBindImage(img_id.value):
                raise RuntimeError(cls._last_error())

            path_bytes = str(vtf_path).encode("utf-8")
            if not dll.vlImageLoad(path_bytes, vlBool(0)):
                raise RuntimeError(cls._last_error())

            width  = int(dll.vlImageGetWidth())
            height = int(dll.vlImageGetHeight())
            src_format = int(dll.vlImageGetFormat())

            # Получаем указатель на сырые данные первого кадра (frame=0, face=0, slice=0, mip=0)
            src_ptr = dll.vlImageGetData(vlUInt(0), vlUInt(0), vlUInt(0), vlUInt(0))
            if not src_ptr:
                raise RuntimeError("vlImageGetData returned NULL")

            dest_size = width * height * 4
            dest = (vlByte * dest_size)()

            if src_format == VTFImageFormat.RGBA8888:
                # Уже в нужном формате — просто копируем
                import ctypes
                ctypes.memmove(dest, src_ptr, dest_size)
            else:
                ok = bool(dll.vlImageConvertToRGBA8888(
                    src_ptr, dest, vlUInt(width), vlUInt(height), c_int(src_format)
                ))
                if not ok:
                    raise RuntimeError(cls._last_error())

            return bytes(dest), width, height
        finally:
            try:
                dll.vlImageDestroy()
            except Exception:
                pass
            try:
                dll.vlDeleteImage(img_id.value)
            except Exception:
                pass
