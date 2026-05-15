"""
3D Preview виджет на базе QWebEngineView + Three.js.

Рендерит OBJ-модель в WebGL прямо внутри Qt-окна.
Обмен данными с JS — через page().runJavaScript() с JSON-строками.

Текстура и OBJ передаются не как file://, а как:
  - OBJ content: строка (читается в Python, передаётся в JS как JSON)
  - Texture:     data URL (base64-encoded PNG)

Это гарантирует работу без CORS-проблем и file:// ограничений Chromium.
"""

import base64
import json
import os
from typing import Optional

from src.shared.logging_config import get_logger

logger = get_logger(__name__)

_HTML_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static", "viewer3d.html")
)

# Флаг доступности WebEngine — проверяется один раз при первом импорте
_WEBENGINE_AVAILABLE: Optional[bool] = None


def is_webengine_available() -> bool:
    """Возвращает True если PySide6-WebEngine установлен."""
    global _WEBENGINE_AVAILABLE
    if _WEBENGINE_AVAILABLE is None:
        try:
            from PySide6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
            _WEBENGINE_AVAILABLE = True
        except ImportError:
            _WEBENGINE_AVAILABLE = False
    return _WEBENGINE_AVAILABLE


class Preview3DWidget:
    """
    Фабрика: возвращает реальный QWebEngineView (если доступен)
    или заглушку-QLabel.

    Использование:
        widget = Preview3DWidget.create(parent)
        # widget — либо _Real3DWidget, либо _Fallback3DWidget
        widget.load_model_files(obj_path, texture_path)
        widget.update_texture_file(png_path)
    """

    @staticmethod
    def create(parent=None):
        if is_webengine_available() and os.path.exists(_HTML_PATH):
            return _Real3DWidget(parent)
        else:
            return _Fallback3DWidget(parent)


# ── Реальный виджет ──────────────────────────────────────────────────────── #

class _Real3DWidget:
    """QWebEngineView с Three.js viewer."""

    def __init__(self, parent=None):
        from PySide6.QtCore import QUrl
        from PySide6.QtWebEngineWidgets import QWebEngineView
        from PySide6.QtWebEngineCore import QWebEngineSettings

        self._view = QWebEngineView(parent)
        self._ready = False
        self._pending: Optional[tuple] = None   # (obj_path, tex_path)
        self._lang: str = 'en'

        settings = self._view.settings()
        # Разрешаем CDN из локального файла
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
        )

        self._view.setUrl(QUrl.fromLocalFile(_HTML_PATH))
        self._view.loadFinished.connect(self._on_load_finished)

    # ── Qt proxy ─────────────────────────────────────────────────────────── #

    @property
    def qt_widget(self):
        return self._view

    def setParent(self, parent):
        self._view.setParent(parent)

    def show(self): self._view.show()
    def hide(self): self._view.hide()

    def setSizePolicy(self, *a): self._view.setSizePolicy(*a)
    def setMinimumHeight(self, h): self._view.setMinimumHeight(h)
    def setMinimumWidth(self, w): self._view.setMinimumWidth(w)

    # ── Загрузка страницы ────────────────────────────────────────────────── #

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            logger.error("3D viewer HTML не загрузился")
            return
        self._ready = True
        # Применяем язык сразу после загрузки страницы
        self._view.page().runJavaScript(
            f"window.setLanguage({json.dumps(self._lang)})"
        )
        if self._pending:
            obj_path, tex_path = self._pending
            self._pending = None
            self.load_model_files(obj_path, tex_path)

    # ── Публичный API ────────────────────────────────────────────────────── #

    def set_language(self, lang: str) -> None:
        """Переключает язык интерфейса 3D вьювера ('ru' / 'en')."""
        self._lang = lang
        if self._ready:
            self._view.page().runJavaScript(
                f"window.setLanguage({json.dumps(lang)})"
            )

    def load_model_files(self, obj_path: str, texture_path: str = "") -> None:
        """Загружает модель из OBJ файла (читает содержимое и передаёт в JS)."""
        if not self._ready:
            self._pending = (obj_path, texture_path)
            return

        try:
            with open(obj_path, "r", encoding="utf-8") as f:
                obj_content = f.read()
        except Exception as exc:
            logger.error(f"Не удалось прочитать OBJ: {exc}")
            self.show_error("Ошибка чтения модели")
            return

        # Вычисляем центр и масштаб в Python — надёжнее чем Three.js bbox после загрузки
        cx, cy, cz, scale = _compute_obj_bounds(obj_content)

        tex_data_url = ""
        if texture_path and os.path.exists(texture_path):
            tex_data_url = _file_to_data_url(texture_path)

        self._js_load(obj_content, tex_data_url, cx, cy, cz, scale)

    def update_texture_file(self, png_path: str) -> None:
        """Обновляет текстуру на уже загруженной модели (статичная)."""
        if not self._ready or not os.path.exists(png_path):
            return
        data_url = _file_to_data_url(png_path)
        js = f"window.updateTextureFromDataUrl({json.dumps(data_url)})"
        self._view.page().runJavaScript(js)

    def update_animated_texture_files(
        self, frame_paths: list, framerate: float
    ) -> None:
        """
        Запускает анимацию текстуры на уже загруженной модели.

        Args:
            frame_paths: список путей к PNG кадрам (в порядке анимации)
            framerate:   частота кадров (fps)
        """
        if not self._ready or not frame_paths:
            return
        valid = [p for p in frame_paths if os.path.exists(p)]
        if not valid:
            return
        data_urls = [_file_to_data_url(p) for p in valid]
        js = (
            f"window.loadAnimatedTexture("
            f"{json.dumps(data_urls)}, "
            f"{framerate:.4f}"
            f")"
        )
        self._view.page().runJavaScript(js)

    def load_crithit_scene(self, crit_tex_path: str = "", model_tex_path: str = "") -> None:
        """Загружает CritHIT сцену: процедурный солдат + billboard с текстурой крита.

        Args:
            crit_tex_path:  путь к PNG текстуры критического удара (billboard над головой)
            model_tex_path: путь к текстуре самого персонажа (накладывается на боксы солдата)
        """
        if not self._ready:
            return
        crit_url  = _file_to_data_url(crit_tex_path)  if crit_tex_path  and os.path.exists(crit_tex_path)  else ""
        model_url = _file_to_data_url(model_tex_path) if model_tex_path and os.path.exists(model_tex_path) else ""
        js = f"window.loadCritHitScene({json.dumps(crit_url)}, {json.dumps(model_url)})"
        self._view.page().runJavaScript(js)

    def load_crithit_scene_with_model(
        self,
        obj_path: str,
        crit_tex_path: str = "",
        model_tex_path: str = "",
    ) -> None:
        """CritHIT сцена с пользовательской OBJ-моделью вместо процедурного солдата.

        Args:
            obj_path:       путь к OBJ файлу модели персонажа
            crit_tex_path:  путь к PNG текстуры критического удара (billboard)
            model_tex_path: путь к текстуре самого персонажа
        """
        if not self._ready:
            return
        try:
            with open(obj_path, "r", encoding="utf-8", errors="replace") as f:
                obj_content = f.read()
        except Exception as exc:
            logger.warning(f"Не удалось прочитать кастомную модель {obj_path}: {exc}")
            self.load_crithit_scene(crit_tex_path, model_tex_path)
            return

        cx, cy, cz, scale = _compute_obj_bounds(obj_content)
        crit_url  = _file_to_data_url(crit_tex_path)  if crit_tex_path  and os.path.exists(crit_tex_path)  else ""
        model_url = _file_to_data_url(model_tex_path) if model_tex_path and os.path.exists(model_tex_path) else ""
        js = (
            f"window.loadCritHitSceneWithModel("
            f"{json.dumps(obj_content)}, "
            f"{json.dumps(crit_url)}, "
            f"{cx:.6f}, {cy:.6f}, {cz:.6f}, {scale:.6f}, "
            f"{json.dumps(model_url)}"
            f")"
        )
        self._view.page().runJavaScript(js)

    def update_crithit_texture(self, crit_tex_path: str) -> None:
        """Обновляет текстуру CritHIT billboard (путь к PNG)."""
        if not self._ready:
            return
        data_url = _file_to_data_url(crit_tex_path) if crit_tex_path and os.path.exists(crit_tex_path) else ""
        js = f"window.updateCritHitTexture({json.dumps(data_url)})"
        self._view.page().runJavaScript(js)

    def show_prompt(self, text: str = "") -> None:
        """Показывает подсказку без спиннера (режим ожидания действия)."""
        if self._ready:
            self._view.page().runJavaScript(
                f"window.showPrompt({json.dumps(text)})"
            )

    def show_loading(self, text: str = "") -> None:
        if self._ready:
            self._view.page().runJavaScript(
                f"window.showLoading({json.dumps(text)})"
            )

    def show_error(self, text: str) -> None:
        if self._ready:
            self._view.page().runJavaScript(
                f"window.showError({json.dumps(text)})"
            )

    def reset(self) -> None:
        if self._ready:
            self._view.page().runJavaScript("window.resetViewer()")

    # ── Внутреннее ───────────────────────────────────────────────────────── #

    def _js_load(
        self,
        obj_content: str,
        tex_data_url: str,
        cx: float, cy: float, cz: float,
        scale: float,
    ) -> None:
        js = (
            f"window.loadModelFromContent("
            f"{json.dumps(obj_content)}, "
            f"{json.dumps(tex_data_url)}, "
            f"{cx:.6f}, {cy:.6f}, {cz:.6f}, {scale:.6f}"
            f")"
        )
        self._view.page().runJavaScript(js)


# ── Заглушка (нет WebEngine) ─────────────────────────────────────────────── #

class _Fallback3DWidget:
    """QLabel-заглушка когда PySide6-WebEngine не установлен."""

    def __init__(self, parent=None):
        from PySide6.QtWidgets import QLabel
        from PySide6.QtCore import Qt
        self._label = QLabel(parent)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setText(
            "3D Preview недоступен.\n"
            "Установите PySide6-Addons:\n"
            "pip install PySide6-Addons"
        )
        self._label.setStyleSheet(
            "QLabel { color: #555; font-size: 13px; background: #1a1a1a; "
            "border: 1px solid #333; border-radius: 4px; }"
        )

    @property
    def qt_widget(self):
        return self._label

    def setParent(self, parent): self._label.setParent(parent)
    def show(self): self._label.show()
    def hide(self): self._label.hide()
    def setSizePolicy(self, *a): self._label.setSizePolicy(*a)
    def setMinimumHeight(self, h): self._label.setMinimumHeight(h)
    def setMinimumWidth(self, w): self._label.setMinimumWidth(w)

    def set_language(self, lang: str): pass
    def show_prompt(self, text: str = ""): pass
    def load_model_files(self, *_): pass
    def update_texture_file(self, *_): pass
    def update_animated_texture_files(self, *_): pass
    def load_crithit_scene(self, crit_tex_path: str = "", model_tex_path: str = ""): pass
    def load_crithit_scene_with_model(self, obj_path: str, crit_tex_path: str = "", model_tex_path: str = ""): pass
    def update_crithit_texture(self, *_): pass
    def show_loading(self, *_): pass
    def show_error(self, text=""): pass
    def reset(self): pass


# ── Утилита ──────────────────────────────────────────────────────────────── #

def _file_to_data_url(path: str) -> str:
    """
    Читает файл изображения и возвращает data URL (base64).

    Автоматически определяет MIME-тип по расширению.
    Форматы без нативной поддержки в браузере (TGA, BMP и пр.)
    конвертируются в PNG через PIL перед кодированием.
    """
    ext = os.path.splitext(path)[1].lower()

    # Форматы с нативной поддержкой в Chromium/WebEngine
    _NATIVE = {
        '.png':  'image/png',
        '.jpg':  'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.webp': 'image/webp',
        '.gif':  'image/gif',
    }

    if ext in _NATIVE:
        mime = _NATIVE[ext]
        with open(path, "rb") as f:
            data = f.read()
    else:
        # TGA, BMP, VTF и прочие → конвертируем в PNG через PIL
        try:
            from PIL import Image
            import io
            img = Image.open(path).convert("RGBA")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            data = buf.getvalue()
            mime = "image/png"
        except Exception as exc:
            logger.warning(f"Не удалось конвертировать {path} в PNG для 3D viewer: {exc}")
            # Последний шанс — читаем как есть и надеемся на png
            with open(path, "rb") as f:
                data = f.read()
            mime = "image/png"

    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _compute_obj_bounds(obj_content: str):
    """
    Парсит вершины OBJ и возвращает (cx, cy, cz, scale) где:
      cx, cy, cz — центр bounding box
      scale      — коэффициент для масштабирования в диапазон 2 единицы

    Вычисляется в Python чтобы не зависеть от Three.js bbox,
    который ненадёжен сразу после загрузки модели.
    """
    xs, ys, zs = [], [], []
    for line in obj_content.splitlines():
        if not line.startswith("v "):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            xs.append(float(parts[1]))
            ys.append(float(parts[2]))
            zs.append(float(parts[3]))
        except ValueError:
            continue

    if not xs:
        return 0.0, 0.0, 0.0, 1.0

    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    cz = (min(zs) + max(zs)) / 2

    extent = max(
        max(xs) - min(xs),
        max(ys) - min(ys),
        max(zs) - min(zs),
    )
    scale = (2.0 / extent) if extent > 0 else 1.0
    return cx, cy, cz, scale
