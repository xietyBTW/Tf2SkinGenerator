"""
Панель предварительного просмотра — 2D (изображение) и 3D (модель).
"""

import os

from PySide6.QtWidgets import (
    QGroupBox, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QWidget, QStackedWidget, QSizePolicy,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from src.utils.themes import get_modern_styles
from src.shared.logging_config import get_logger

logger = get_logger(__name__)


class PreviewPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__()
        self.parent = parent
        self.styles = get_modern_styles()
        self.image_path = None
        self.vtf_path = None
        self.image_info = {}
        self._gif_movie = None
        self._gif_orig_size = None

        # 3D
        self._3d_widget = None          # Preview3DWidget (создаётся лениво)
        self._3d_worker = None          # Preview3DWorker (стандартный VPK)
        self._vpk_mod_worker = None     # PreviewVpkModWorker (пользовательский VPK)
        self._3d_available = False      # Есть ли WebEngine
        self._pending_3d_params = None  # (weapon_key, mode, misc_vpk, textures_vpk)
        self._custom_smd_mode = False   # True когда режим замены модели (кастомный SMD)
        self._crithit_mode = False      # True в режиме CritHIT (персонаж + billboard)
        self._crithit_class = 'soldier' # Класс персонажа для CritHIT (scout/soldier/…)

        # Командные раскраски (RED / BLU)
        self._red_frame_paths: list = []
        self._blu_frame_paths: list = []
        self._team_framerate: float  = 0.0
        self._active_team: str       = 'red'   # 'red' | 'blu'

        from src.config.app_config import AppConfig
        from src.data.translations import TRANSLATIONS
        config = AppConfig.load_config()
        current_lang = config.get('language') or 'en'
        self._lang = current_lang
        self.t = TRANSLATIONS[current_lang]

        self.setAcceptDrops(True)
        self.init_ui()

    # ── UI ────────────────────────────────────────────────────────────────── #

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        # ── Переключатель 2D / 3D ─────────────────────────────────────────── #
        self.toggle_bar = QWidget()
        toggle_layout = QHBoxLayout(self.toggle_bar)
        toggle_layout.setContentsMargins(0, 0, 0, 0)
        toggle_layout.setSpacing(4)
        toggle_layout.addStretch()

        btn_style_active = """
            QPushButton {
                background: #2a2a2a;
                color: #ccc;
                border: 1px solid #444;
                padding: 4px 16px;
                font-size: 11px;
                font-weight: 600;
                border-radius: 3px;
            }
        """
        btn_style_inactive = """
            QPushButton {
                background: transparent;
                color: #555;
                border: 1px solid #2a2a2a;
                padding: 4px 16px;
                font-size: 11px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background: rgba(255,255,255,0.04);
                color: #888;
                border-color: #383838;
            }
        """

        self.btn_2d = QPushButton("2D")
        self.btn_3d = QPushButton("3D")
        self.btn_2d.setFixedHeight(26)
        self.btn_3d.setFixedHeight(26)
        self.btn_2d.setStyleSheet(btn_style_active)
        self.btn_3d.setStyleSheet(btn_style_inactive)
        self._btn_style_active   = btn_style_active
        self._btn_style_inactive = btn_style_inactive

        self.btn_2d.clicked.connect(self._switch_to_2d)
        self.btn_3d.clicked.connect(self._switch_to_3d)

        toggle_layout.addWidget(self.btn_2d)
        toggle_layout.addWidget(self.btn_3d)

        # Кнопка загрузки 3D модели — иконка куба, без текста
        toggle_layout.addSpacing(12)
        self.btn_load_3d = QPushButton()
        self.btn_load_3d.setFixedSize(26, 26)
        self.btn_load_3d.setToolTip(self.t.get('3d_load_model_tip', 'Load 3D model'))
        self.btn_load_3d.setIcon(_make_cube_icon("#666666"))
        self.btn_load_3d.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: 1px solid #2a2a2a;
                border-radius: 3px;
                padding: 0px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.05);
                border-color: #555;
            }
            QPushButton:pressed {
                background: rgba(255, 255, 255, 0.08);
            }
            QPushButton:disabled {
                opacity: 0.3;
            }
        """)
        self.btn_load_3d.clicked.connect(self._on_load_3d_clicked)
        self.btn_load_3d.setVisible(False)  # только в 3D режиме
        toggle_layout.addWidget(self.btn_load_3d)

        # Кнопка загрузки VPK мода
        self.btn_load_vpk_mod = QPushButton()
        self.btn_load_vpk_mod.setFixedSize(26, 26)
        self.btn_load_vpk_mod.setToolTip(self.t.get('3d_load_vpk_tip', 'Load VPK mod for 3D Preview'))
        self.btn_load_vpk_mod.setIcon(_make_vpk_icon("#666666"))
        self.btn_load_vpk_mod.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: 1px solid #2a2a2a;
                border-radius: 3px;
                padding: 0px;
            }
            QPushButton:hover {
                background: rgba(255, 255, 255, 0.05);
                border-color: #555;
            }
            QPushButton:pressed {
                background: rgba(255, 255, 255, 0.08);
            }
            QPushButton:disabled {
                opacity: 0.3;
            }
        """)
        self.btn_load_vpk_mod.clicked.connect(self._on_load_vpk_mod_clicked)
        self.btn_load_vpk_mod.setVisible(False)   # только в 3D режиме
        self.btn_load_vpk_mod.setEnabled(False)   # включается когда настроен TF2 путь
        toggle_layout.addWidget(self.btn_load_vpk_mod)

        # ── Командные раскраски RED / BLU ─────────────────────────────────── #
        _team_btn_style = """
            QPushButton {
                background: transparent;
                border: 1px solid #2a2a2a;
                border-radius: 13px;
                padding: 0px;
            }
            QPushButton:hover  { border-color: #555; }
            QPushButton:pressed { background: rgba(255,255,255,0.08); }
        """
        _team_btn_style_active = """
            QPushButton {
                background: rgba(255,255,255,0.07);
                border: 1px solid #555;
                border-radius: 13px;
                padding: 0px;
            }
            QPushButton:hover { border-color: #888; }
        """
        self._team_btn_style        = _team_btn_style
        self._team_btn_style_active = _team_btn_style_active

        toggle_layout.addSpacing(8)

        self.btn_team_red = QPushButton()
        self.btn_team_red.setFixedSize(26, 26)
        self.btn_team_red.setToolTip(self.t.get('3d_team_red_tip', 'RED team texture'))
        self.btn_team_red.setIcon(_make_team_icon("#c0392b"))
        self.btn_team_red.setStyleSheet(_team_btn_style_active)   # RED активен по умолчанию
        self.btn_team_red.clicked.connect(self._on_team_red_clicked)
        self.btn_team_red.setVisible(False)   # показывается только когда есть BLU текстура
        toggle_layout.addWidget(self.btn_team_red)

        self.btn_team_blu = QPushButton()
        self.btn_team_blu.setFixedSize(26, 26)
        self.btn_team_blu.setToolTip(self.t.get('3d_team_blu_tip', 'BLU team texture'))
        self.btn_team_blu.setIcon(_make_team_icon("#2980b9"))
        self.btn_team_blu.setStyleSheet(_team_btn_style)
        self.btn_team_blu.clicked.connect(self._on_team_blu_clicked)
        self.btn_team_blu.setVisible(False)
        toggle_layout.addWidget(self.btn_team_blu)

        # Кнопки всегда видны; 3D покажет заглушку если WebEngine не установлен
        self.toggle_bar.setVisible(True)
        # Фиксируем высоту: без этого VBoxLayout отдаёт всё лишнее вертикальное
        # пространство toggle_bar (он имеет дефолтную политику Preferred/Preferred),
        # что создаёт большой пустой разрыв между кнопками 2D/3D и preview-блоком
        # при увеличении высоты окна.
        self.toggle_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(self.toggle_bar)

        # ── Стек страниц ─────────────────────────────────────────────────── #
        self.view_stack = QStackedWidget()
        self.view_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        # Страница 2D
        self.page_2d = self._build_2d_page()
        self.view_stack.addWidget(self.page_2d)

        layout.addWidget(self.view_stack)

        # ── Информация (всегда видна) ─────────────────────────────────────── #
        self.info_summary = self._build_info_panel()
        layout.addWidget(self.info_summary)

        # Растяжка в конце поглощает любое лишнее вертикальное пространство,
        # не позволяя layout-у «размазывать» его по виджетам без фиксированной высоты.
        layout.addStretch(1)

        self.setup_drag_drop()
        self.update_info_summary()

        # Инициализируем 3D виджет (ленивая — проверяем WebEngine)
        self._init_3d_widget()

    def _build_2d_page(self) -> QWidget:
        page = QWidget()
        page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        vlay = QVBoxLayout(page)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.setSpacing(0)

        _border_style = """
            QWidget {
                border: 1px solid #333;
                border-radius: 4px;
                background-color: #1a1a1a;
            }
        """

        # Пустое состояние
        self.empty_state = QWidget()
        self.empty_state.setFixedHeight(500)
        self.empty_state.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.empty_state.setMinimumWidth(800)
        self.empty_state.setStyleSheet(_border_style)

        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_layout.setSpacing(16)

        self.empty_text = QLabel(self.t['drag_text'])
        self.empty_text.setStyleSheet(
            "color:#666; font-size:14px; font-weight:300; text-align:center; padding:40px;"
        )
        self.empty_text.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(self.empty_text)

        self.select_file_button = QPushButton(self.t['select_file_btn'])
        self.select_file_button.setStyleSheet("""
            QPushButton {
                background-color: transparent; color: #888;
                border: 1px solid #333; padding: 10px 24px;
                font-size: 13px; font-weight: 500; border-radius: 4px;
            }
            QPushButton:hover {
                background-color: rgba(255,255,255,0.05);
                border-color: #555; color: #ccc;
            }
        """)
        self.select_file_button.clicked.connect(self.browse_image)
        empty_layout.addWidget(self.select_file_button, alignment=Qt.AlignCenter)
        vlay.addWidget(self.empty_state)

        # Превью изображения
        self.preview_style = """
            QLabel {
                border: 1px solid #333;
                border-radius: 4px;
                background-color: #1a1a1a;
            }
        """
        self.preview = QLabel()
        self.preview.setStyleSheet(self.preview_style)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setFixedHeight(500)
        self.preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.preview.setMinimumWidth(800)
        self.preview.hide()
        vlay.addWidget(self.preview, alignment=Qt.AlignCenter)

        return page

    def _build_info_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedHeight(220)
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        panel.setMinimumWidth(600)
        panel.setStyleSheet("""
            QWidget {
                background-color: rgba(255,255,255,0.02);
                border: 1px solid #333;
                border-radius: 4px;
            }
        """)

        info_layout = QVBoxLayout(panel)
        info_layout.setContentsMargins(12, 12, 12, 12)
        info_layout.setSpacing(8)

        self.info_title = QLabel(self.t['info_title'])
        self.info_title.setStyleSheet(
            "font-weight:600; font-size:13px; color:#ccc; "
            "padding-bottom:8px; border-bottom:1px solid #333;"
        )
        info_layout.addWidget(self.info_title)

        for attr in ('info_resolution', 'info_format', 'info_flags', 'info_filename'):
            lbl = QLabel("")
            lbl.setStyleSheet("font-size:12px; color:#888;")
            setattr(self, attr, lbl)
            info_layout.addWidget(lbl)

        return panel

    def _init_3d_widget(self):
        """Создаёт 3D-виджет и добавляет его в стек.

        Всегда добавляет страницу в стек — либо реальный QWebEngineView,
        либо QLabel-заглушку с инструкцией по установке.
        """
        from src.ui.preview_3d_widget import Preview3DWidget, is_webengine_available
        self._3d_available = is_webengine_available()

        if not self._3d_available:
            logger.info("WebEngine недоступен — используем заглушку 3D Preview")

        # Создаём виджет в любом случае (реальный или заглушка)
        self._3d_widget = Preview3DWidget.create(self)
        self._3d_widget.set_language(self._lang)

        qt_w = self._3d_widget.qt_widget
        qt_w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        qt_w.setMinimumHeight(500)
        qt_w.setMinimumWidth(800)

        self.page_3d = qt_w
        self.view_stack.addWidget(self.page_3d)

        if self._3d_available:
            logger.info("3D Preview виджет инициализирован (WebEngine)")
        else:
            logger.info("3D Preview заглушка добавлена (установите PySide6-Addons)")

    # ── Переключение 2D / 3D ─────────────────────────────────────────────── #

    def _switch_to_2d(self):
        self.view_stack.setCurrentIndex(0)
        self.btn_2d.setStyleSheet(self._btn_style_active)
        self.btn_3d.setStyleSheet(self._btn_style_inactive)
        self.btn_load_3d.setVisible(False)
        self.btn_load_vpk_mod.setVisible(False)
        self.btn_team_red.setVisible(False)
        self.btn_team_blu.setVisible(False)

    def _switch_to_3d(self):
        if self._3d_widget is None:
            return
        self.view_stack.setCurrentIndex(1)
        self.btn_2d.setStyleSheet(self._btn_style_inactive)
        self.btn_3d.setStyleSheet(self._btn_style_active)

        # В режиме CritHIT кнопки "загрузить модель" и "VPK мод" не нужны —
        # солдат строится прямо в Three.js без VPK.
        if self._crithit_mode:
            self.btn_load_3d.setVisible(False)
            self.btn_load_vpk_mod.setVisible(False)
            if self._3d_available:
                from PySide6.QtCore import QTimer
                QTimer.singleShot(200, self._render_crithit_scene)
            return

        self.btn_load_3d.setVisible(True)
        self.btn_load_vpk_mod.setVisible(True)
        # Кнопка VPK мода всегда доступна в 3D — пользователь может загрузить
        # свой мод даже без выбранного оружия (воркер сам разберётся с путями)
        self.btn_load_vpk_mod.setEnabled(True)

        # Если пользователь уже загрузил свою текстуру — применяем её на модель.
        # Задержка нужна: WebView "просыпается" после показа не мгновенно,
        # и runJavaScript до этого момента может не дойти до JS.
        if self.image_path and self._3d_available and self._3d_widget:
            import os
            path = self.image_path  # захватываем в замыкание
            if os.path.exists(path):
                from PySide6.QtCore import QTimer
                QTimer.singleShot(300, lambda: self._3d_widget.update_texture_file(path))

    def is_3d_mode(self) -> bool:
        return self.view_stack.currentIndex() == 1

    # ── 3D Preview — публичный API ───────────────────────────────────────── #

    def set_custom_model_mode(self, enabled: bool = True) -> None:
        """
        Переключает в режим кастомной SMD модели (Replace Model).

        При enabled=True кнопка «Загрузить 3D модель» откроет диалог выбора
        SMD файла пользователя вместо извлечения модели из VPK.
        При enabled=False сбрасывает режим и отключает кнопку.
        """
        self._custom_smd_mode = enabled
        self._pending_3d_params = None
        self._stop_3d_worker()

        if enabled:
            if self._3d_widget:
                self._3d_widget.show_prompt(self.t.get('3d_prompt_smd', 'Click ▶ and select an SMD file'))
            self.btn_load_3d.setEnabled(True)
            # VPK мод тоже доступен в режиме замены модели (для сравнения)
            self.btn_load_vpk_mod.setEnabled(True)
        else:
            if self._3d_widget:
                self._3d_widget.reset()
            self.btn_load_3d.setEnabled(False)
            self.btn_load_vpk_mod.setEnabled(False)

    def set_crithit_mode(self) -> None:
        """
        Переключает 3D viewer в режим CritHIT:
        — генерирует солдата прямо в Three.js (без VPK)
        — показывает текстуру пользователя как billboard над головой.
        """
        self._crithit_mode = True
        self._custom_smd_mode = False
        self._pending_3d_params = None
        self._stop_3d_worker()
        self._stop_vpk_mod_worker()
        self._reset_team_state()

        if self._3d_widget:
            self._3d_widget.show_prompt(
                self.t.get('3d_prompt_crithit', 'Switch to 3D tab — the soldier will appear automatically')
            )

        # Если пользователь уже в 3D режиме — сразу рисуем сцену
        if self.is_3d_mode() and self._3d_available:
            self._render_crithit_scene()

    def _render_crithit_scene(self) -> None:
        """Передаёт текущее изображение в JS для отрисовки CritHIT сцены.

        Ищет модель и текстуру персонажа в tools/Model/<class>/.
        Если в папке класса пусто — строит процедурного солдата из BoxGeometry.
        """
        if not self._3d_widget or not self._3d_available:
            return

        crit_tex_path = self.image_path or ""
        class_name    = getattr(self, '_crithit_class', 'soldier')
        custom_model, model_tex_path = self._find_crithit_custom_model(class_name)

        # VTF модельной текстуры конвертируем в PNG
        if model_tex_path.lower().endswith('.vtf'):
            model_tex_path = self._convert_model_vtf(model_tex_path)

        if custom_model:
            if custom_model.lower().endswith('.smd'):
                import tempfile
                from src.services.smd_to_obj_service import SmdToObjService
                self._3d_widget.show_loading("Converting custom model...")
                import os as _os
                tmp = tempfile.mkdtemp(prefix="tf2_crithit_")
                obj_path = _os.path.join(tmp, "model.obj")
                ok = SmdToObjService.convert(custom_model, obj_path)
                if ok and _os.path.exists(obj_path):
                    self._3d_widget.load_crithit_scene_with_model(obj_path, crit_tex_path, model_tex_path)
                else:
                    logger.warning(f"SMD конвертация не удалась для {custom_model}, использую процедурного солдата")
                    self._3d_widget.load_crithit_scene(crit_tex_path, model_tex_path)
            else:
                self._3d_widget.load_crithit_scene_with_model(custom_model, crit_tex_path, model_tex_path)
        else:
            self._3d_widget.load_crithit_scene(crit_tex_path, model_tex_path)

    # ── Поиск кастомной модели CritHIT ──────────────────────────────────── #

    @staticmethod
    def _find_crithit_custom_model(class_name: str = 'soldier') -> tuple:
        """
        Ищет модель и текстуру персонажа для CritHIT.

        Порядок поиска:
          1. tools/Model/<class_name>/  — папка выбранного класса
          2. tools/Model/               — корневая папка (обратная совместимость)

        Поддерживаемые модели:   .obj, .smd
        Поддерживаемые текстуры: .png, .jpg, .jpeg, .bmp, .tga, .vtf, .webp

        Возвращает (model_path, texture_path) — оба могут быть пустой строкой.
        """
        import os as _os
        here = _os.path.dirname(_os.path.abspath(__file__))
        project_root = _os.path.dirname(_os.path.dirname(here))
        model_root = _os.path.join(project_root, "tools", "Model")

        MODEL_EXTS   = ('.obj', '.smd')
        TEXTURE_EXTS = ('.png', '.jpg', '.jpeg', '.bmp', '.tga', '.vtf', '.webp')

        def _scan(folder: str) -> tuple:
            if not _os.path.isdir(folder):
                return "", ""
            model_path = tex_path = ""
            for name in sorted(_os.listdir(folder)):
                if name.startswith('.'):
                    continue
                lo = name.lower()
                full = _os.path.join(folder, name)
                if not model_path and lo.endswith(MODEL_EXTS):
                    model_path = full
                if not tex_path and lo.endswith(TEXTURE_EXTS):
                    tex_path = full
            return model_path, tex_path

        # Папка класса
        class_dir = _os.path.join(model_root, class_name.lower())
        m, t = _scan(class_dir)
        if m:
            logger.info(f"CritHIT [{class_name}]: модель={m}, текстура={t or '—'}")
            return m, t

        # Корневая папка (backward compat)
        m, t = _scan(model_root)
        if m:
            logger.info(f"CritHIT [root]: модель={m}, текстура={t or '—'}")
            return m, t

        return "", ""

    @staticmethod
    def _convert_model_vtf(vtf_path: str) -> str:
        """Конвертирует VTF текстуру модели во временный PNG. Возвращает путь или ''."""
        try:
            import tempfile
            from src.services.vtflib_wrapper import VTFLib
            from PIL import Image
            rgba_bytes, w, h = VTFLib.read_vtf_as_rgba(vtf_path)
            img = Image.frombytes("RGBA", (w, h), rgba_bytes)
            png_path = tempfile.mktemp(suffix='.png', prefix='tf2_model_tex_')
            img.save(png_path)
            logger.info(f"CritHIT: VTF→PNG модельной текстуры: {png_path}")
            return png_path
        except Exception as exc:
            logger.warning(f"VTF→PNG для модельной текстуры не удался: {exc}")
            return ""

    def show_3d_no_tf2_message(self) -> None:
        """
        Показывает подсказку в 3D виджете когда TF2 не настроен.
        Кнопка остаётся заблокированной.
        """
        self._pending_3d_params = None
        self._custom_smd_mode = False
        self._crithit_mode = False
        self._stop_3d_worker()
        self._reset_team_state()

        if self._3d_widget:
            self._3d_widget.show_prompt(
                self.t.get('3d_prompt_no_tf2', 'Set TF2 folder in Settings to load original models')
            )

        self.btn_load_3d.setEnabled(False)
        self.btn_load_vpk_mod.setEnabled(False)

    def set_3d_params(
        self,
        weapon_key: str,
        mode: str,
        misc_vpk_path: str,
        textures_vpk_path: str,
    ) -> None:
        """
        Сохраняет параметры для 3D загрузки без запуска воркера.
        Вызывается из main_window при смене оружия.
        Реальная загрузка начнётся только по кнопке «Загрузить 3D модель».
        """
        self._custom_smd_mode = False   # сбрасываем режим кастомной модели
        self._crithit_mode = False      # сбрасываем CritHIT режим
        self._pending_3d_params = (weapon_key, mode, misc_vpk_path, textures_vpk_path)

        # Сбрасываем воркер, командные раскраски и показываем приглашение
        self._stop_3d_worker()
        self._reset_team_state()

        if self._3d_widget:
            self._3d_widget.show_prompt(self.t.get('3d_prompt_weapon', 'Select a weapon and click ▶ to load the model'))

        # Разблокируем обе кнопки (пути к игре доступны)
        self.btn_load_3d.setEnabled(True)
        self.btn_load_vpk_mod.setEnabled(True)

    def _on_load_3d_clicked(self) -> None:
        """Обработчик кнопки «Загрузить 3D модель»."""
        logger.info(f"[BTN] load_3d clicked | custom_smd={self._custom_smd_mode} | "
                    f"pending={self._pending_3d_params} | "
                    f"3d_available={self._3d_available} | "
                    f"widget={self._3d_widget}")
        if self._custom_smd_mode:
            self._load_custom_smd_via_dialog()
            return
        if not self._pending_3d_params:
            logger.warning("[BTN] _pending_3d_params is None — кнопка нажата до выбора оружия")
            return
        weapon_key, mode, misc_vpk, textures_vpk = self._pending_3d_params
        logger.info(f"[BTN] запуск воркера: weapon={weapon_key} mode={mode} "
                    f"vpk_exists={os.path.exists(misc_vpk) if misc_vpk else 'NO_PATH'}")
        self._start_3d_worker(weapon_key, mode, misc_vpk, textures_vpk)

    def _load_custom_smd_via_dialog(self) -> None:
        """Показывает диалог выбора SMD и загружает кастомную модель в 3D viewer."""
        from PySide6.QtWidgets import QFileDialog
        smd_path, _ = QFileDialog.getOpenFileName(
            self,
            self.t.get('3d_select_smd_title', 'Select SMD Model File'),
            "",
            "SMD Files (*.smd);;All Files (*)"
        )
        if not smd_path:
            return
        self._load_custom_smd_file(smd_path)

    def _load_custom_smd_file(self, smd_path: str) -> None:
        """
        Конвертирует пользовательский SMD → OBJ и показывает в 3D viewer.

        Конвертация быстрая (просто парсинг текста), выполняется в главном потоке.
        Если нужна текстура — берёт текущее загруженное изображение (self.image_path).
        """
        if not self._3d_available or self._3d_widget is None:
            return

        import os, tempfile
        from src.services.smd_to_obj_service import SmdToObjService

        self.btn_load_3d.setEnabled(False)
        self._3d_widget.show_loading(self.t.get('3d_converting_smd', 'Converting SMD...'))

        try:
            temp_dir = tempfile.mkdtemp(prefix="tf2_smd_preview_")
            obj_path = os.path.join(temp_dir, "model.obj")

            ok = SmdToObjService.convert(smd_path, obj_path)
            if not ok or not os.path.exists(obj_path):
                self._3d_widget.show_error(self.t.get('3d_error_convert', 'SMD conversion error'))
                return

            # Используем текущую текстуру пользователя (если загружена)
            texture_path = self.image_path or ""

            self._3d_widget.load_model_files(obj_path, texture_path)

        except Exception as exc:
            logger.error(f"Ошибка загрузки кастомной SMD модели: {exc}", exc_info=True)
            if self._3d_widget:
                self._3d_widget.show_error(self.t.get('3d_error_load', 'Model load error'))
        finally:
            self.btn_load_3d.setEnabled(True)

    # ── VPK мод — загрузка пользовательского мода ────────────────────────── #

    def enable_vpk_mod_button(self, enabled: bool = True) -> None:
        """Разрешает или запрещает кнопку загрузки VPK мода."""
        self.btn_load_vpk_mod.setEnabled(enabled)

    def _on_load_vpk_mod_clicked(self) -> None:
        """Обработчик кнопки «Загрузить VPK мод»."""
        from PySide6.QtWidgets import QFileDialog
        vpk_path, _ = QFileDialog.getOpenFileName(
            self,
            self.t.get('3d_select_vpk', 'Select VPK mod'),
            "",
            "VPK Files (*.vpk);;All Files (*)"
        )
        if not vpk_path:
            return
        self._start_vpk_mod_worker(vpk_path)

    def _start_vpk_mod_worker(self, user_vpk_path: str) -> None:
        """Запускает фоновый воркер для разбора VPK мода."""
        if not self._3d_available or self._3d_widget is None:
            return

        # Приоритет: пути из уже сохранённых параметров 3D (они уже проверены)
        misc_vpk     = ""
        textures_vpk = ""
        if self._pending_3d_params and len(self._pending_3d_params) >= 4:
            misc_vpk     = self._pending_3d_params[2]
            textures_vpk = self._pending_3d_params[3]
        elif hasattr(self, 'parent') and hasattr(self.parent, 'settings_panel'):
            # Fallback: берём из настроек
            try:
                from src.services.tf2_paths import TF2Paths
                settings     = self.parent.settings_panel.get_settings()
                tf2_root_dir = settings.get('tf2_game_folder', '')
                if tf2_root_dir:
                    _, misc_vpk, _ = TF2Paths.resolve(tf2_root_dir)
                    textures_vpk   = TF2Paths.resolve_textures_vpk(tf2_root_dir)
            except Exception:
                pass

        # Останавливаем предыдущие воркеры и сбрасываем команды
        self._stop_3d_worker()
        self._stop_vpk_mod_worker()
        self._reset_team_state()

        self.btn_load_vpk_mod.setEnabled(False)
        self.btn_load_3d.setEnabled(False)
        self._3d_widget.show_loading(self.t.get('3d_analyzing_vpk', 'Analyzing VPK mod...'))

        from src.services.preview_vpk_mod_worker import PreviewVpkModWorker
        worker = PreviewVpkModWorker(
            user_vpk_path    = user_vpk_path,
            misc_vpk_path    = misc_vpk,
            textures_vpk_path= textures_vpk,
            lang             = getattr(self, '_lang', 'en'),
            parent           = self,
        )
        worker.progress.connect(self._on_vpk_mod_progress)
        worker.ready.connect(self._on_vpk_mod_ready)
        worker.animated.connect(self._on_3d_animated)
        worker.blu_ready.connect(self._on_3d_blu_ready)
        worker.failed.connect(self._on_vpk_mod_failed)
        worker.start()
        self._vpk_mod_worker = worker

    def _on_vpk_mod_progress(self, text: str) -> None:
        if self._3d_widget:
            self._3d_widget.show_loading(text)

    def _on_vpk_mod_ready(self, obj_path: str, texture_path: str) -> None:
        self.btn_load_vpk_mod.setEnabled(True)
        self.btn_load_3d.setEnabled(bool(self._pending_3d_params or self._custom_smd_mode))
        if texture_path:
            self._red_frame_paths = [texture_path]
            self._active_team = 'red'
        if self._3d_widget:
            self._3d_widget.load_model_files(obj_path, texture_path)

    def _on_vpk_mod_failed(self, error: str) -> None:
        logger.warning(f"VPK мод 3D Preview не удался: {error}")
        self.btn_load_vpk_mod.setEnabled(True)
        self.btn_load_3d.setEnabled(bool(self._pending_3d_params or self._custom_smd_mode))
        if self._3d_widget:
            self._3d_widget.show_error(self.t.get('3d_error_prefix', 'Error: {error}').format(error=error))

    def _stop_vpk_mod_worker(self) -> None:
        if self._vpk_mod_worker and self._vpk_mod_worker.isRunning():
            self._vpk_mod_worker.requestInterruption()
            self._vpk_mod_worker.wait(3000)
        self._vpk_mod_worker = None

    def _start_3d_worker(
        self,
        weapon_key: str,
        mode: str,
        misc_vpk_path: str,
        textures_vpk_path: str,
    ) -> None:
        """Запускает фоновый воркер загрузки 3D модели."""
        if not self._3d_available or self._3d_widget is None:
            return

        self._stop_3d_worker()
        self._reset_team_state()
        self.btn_load_3d.setEnabled(False)
        self._3d_widget.show_loading(self.t.get('3d_preparing', 'Preparing 3D model...'))

        from src.services.preview_3d_worker import Preview3DWorker
        worker = Preview3DWorker(
            weapon_key=weapon_key,
            mode=mode,
            misc_vpk_path=misc_vpk_path,
            textures_vpk_path=textures_vpk_path,
            lang=getattr(self, '_lang', 'en'),
            parent=self,
        )
        worker.progress.connect(self._on_3d_progress)
        worker.ready.connect(self._on_3d_ready)
        worker.animated.connect(self._on_3d_animated)
        worker.blu_ready.connect(self._on_3d_blu_ready)
        worker.failed.connect(self._on_3d_failed)
        worker.start()
        self._3d_worker = worker

    def reset_3d_preview(self) -> None:
        """Сбрасывает 3D viewer (например, при смене режима на Spray)."""
        self._pending_3d_params = None
        self._custom_smd_mode = False
        self._crithit_mode = False
        self._stop_3d_worker()
        self._stop_vpk_mod_worker()
        self._reset_team_state()
        if self._3d_widget:
            self._3d_widget.reset()
        self.btn_load_3d.setEnabled(False)
        if self.is_3d_mode():
            self._switch_to_2d()
    def update_3d_texture(self, png_path: str) -> None:
        """Обновляет текстуру на 3D модели (когда пользователь загружает своё изображение)."""
        if self._3d_widget and self.is_3d_mode():
            self._3d_widget.update_texture_file(png_path)

    def _stop_3d_worker(self):
        if self._3d_worker and self._3d_worker.isRunning():
            self._3d_worker.requestInterruption()
            self._3d_worker.wait(3000)
        self._3d_worker = None

    def _on_3d_progress(self, text: str):
        if self._3d_widget:
            self._3d_widget.show_loading(text)

    def _on_3d_ready(self, obj_path: str, texture_path: str):
        self.btn_load_3d.setEnabled(True)
        # Сохраняем RED кадр (один кадр; анимированные кадры придут через _on_3d_animated)
        if texture_path:
            self._red_frame_paths = [texture_path]
            self._active_team = 'red'
        if self._3d_widget:
            self._3d_widget.load_model_files(obj_path, texture_path)

    def _on_3d_animated(self, frame_paths: list, framerate: float) -> None:
        """Запускает анимацию RED текстуры когда воркер нашёл многокадровый VTF."""
        if frame_paths:
            self._red_frame_paths = frame_paths
            self._team_framerate  = framerate
        if self._3d_widget and frame_paths:
            logger.info(
                f"3D Preview: запуск анимации RED текстуры "
                f"({len(frame_paths)} кадров @ {framerate:.1f} fps)"
            )
            self._3d_widget.update_animated_texture_files(frame_paths, framerate)

    def _on_3d_blu_ready(self, frame_paths: list, framerate: float) -> None:
        """Получены кадры BLU текстуры — сохраняем и показываем кнопки команд."""
        if not frame_paths:
            return
        self._blu_frame_paths = frame_paths
        if framerate > 0:
            self._team_framerate = framerate
        logger.info(
            f"3D Preview: BLU текстура готова "
            f"({len(frame_paths)} кадров @ {framerate:.1f} fps)"
        )
        # Показываем кнопки только если мы в 3D режиме
        if self.is_3d_mode():
            self.btn_team_red.setVisible(True)
            self.btn_team_blu.setVisible(True)

    def _reset_team_state(self) -> None:
        """Сбрасывает данные командных раскрасок и скрывает кнопки."""
        self._red_frame_paths = []
        self._blu_frame_paths = []
        self._team_framerate  = 0.0
        self._active_team     = 'red'
        if hasattr(self, 'btn_team_red'):
            self.btn_team_red.setVisible(False)
            self.btn_team_red.setStyleSheet(self._team_btn_style_active)
        if hasattr(self, 'btn_team_blu'):
            self.btn_team_blu.setVisible(False)
            self.btn_team_blu.setStyleSheet(self._team_btn_style)

    def _on_team_red_clicked(self) -> None:
        """Переключается на RED раскраску."""
        if self._active_team == 'red' or not self._3d_widget:
            return
        self._active_team = 'red'
        self.btn_team_red.setStyleSheet(self._team_btn_style_active)
        self.btn_team_blu.setStyleSheet(self._team_btn_style)
        self._apply_team_texture(self._red_frame_paths)

    def _on_team_blu_clicked(self) -> None:
        """Переключается на BLU раскраску."""
        if self._active_team == 'blu' or not self._3d_widget or not self._blu_frame_paths:
            return
        self._active_team = 'blu'
        self.btn_team_blu.setStyleSheet(self._team_btn_style_active)
        self.btn_team_red.setStyleSheet(self._team_btn_style)
        self._apply_team_texture(self._blu_frame_paths)

    def _apply_team_texture(self, frame_paths: list) -> None:
        """Применяет список кадров (или один кадр) как текстуру на 3D модели."""
        if not frame_paths or not self._3d_widget:
            return
        if len(frame_paths) > 1 and self._team_framerate > 0:
            self._3d_widget.update_animated_texture_files(frame_paths, self._team_framerate)
        else:
            self._3d_widget.update_texture_file(frame_paths[0])

    def _on_3d_failed(self, error: str):
        logger.warning(f"3D Preview не удался: {error}")
        self.btn_load_3d.setEnabled(True)
        if self._3d_widget:
            self._3d_widget.show_error(self.t.get('3d_unavailable', 'Model unavailable: {error}').format(error=error))

    # ── GIF helpers ──────────────────────────────────────────────────────── #

    def _stop_gif(self) -> None:
        if self._gif_movie is not None:
            self._gif_movie.stop()
            self.preview.setMovie(None)
            self._gif_movie.deleteLater()
            self._gif_movie = None
        self._gif_orig_size = None

    def _start_gif(self, path: str, preview_width: int) -> bool:
        from PySide6.QtGui import QMovie, QImageReader
        from PySide6.QtCore import QSize

        reader = QImageReader(path)
        orig = reader.size()
        if not orig.isValid() or orig.width() <= 0:
            return False

        movie = QMovie(path)
        if not movie.isValid():
            movie.deleteLater()
            return False

        self._gif_orig_size = orig
        movie.setScaledSize(orig.scaled(preview_width, 500, Qt.KeepAspectRatio))
        self._gif_movie = movie
        self.preview.setMovie(movie)
        movie.start()
        return True

    # ── Image loading ────────────────────────────────────────────────────── #

    def load_image(self, path):
        """Загружает изображение (или GIF) для 2D Preview."""
        self._stop_gif()
        self.image_path = path
        self.vtf_path = None

        self.empty_state.hide()
        self.preview.show()
        self.preview.clear()
        self.preview.setStyleSheet(self.preview_style)
        self.preview.updateGeometry()
        self.updateGeometry()

        from PySide6.QtCore import QTimer

        if path.lower().endswith('.gif'):
            def try_start_gif():
                if self._gif_movie is not None:
                    return
                w = max(self.preview.width(), self.width(), 600)
                if not self._start_gif(path, w):
                    pix = QPixmap(path).scaled(w, 500, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    self.preview.setPixmap(pix)
            QTimer.singleShot(50, try_start_gif)
            QTimer.singleShot(200, try_start_gif)
        else:
            def scale_image():
                w = max(self.preview.width(), self.width(), 600)
                pix = QPixmap(path).scaled(w, 500, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.preview.setPixmap(pix)
            QTimer.singleShot(50, scale_image)
            QTimer.singleShot(200, scale_image)

        # Обновляем текстуру в 3D если открыт 3D режим
        if self.is_3d_mode():
            if self._crithit_mode and self._3d_available and self._3d_widget:
                # CritHIT режим: обновляем только billboard над головой солдата
                captured = path
                from PySide6.QtCore import QTimer as T
                T.singleShot(300, lambda p=captured: self._3d_widget.update_crithit_texture(p))
            elif path.lower().endswith(('.png', '.jpg', '.jpeg')):
                from PySide6.QtCore import QTimer as T
                T.singleShot(300, lambda: self.update_3d_texture(path))

        self.update_info_summary()

    def clear_preview(self):
        self._stop_gif()
        self.image_path = None
        self.vtf_path = None
        self.image_info = {}
        self.preview.clear()
        self.preview.hide()
        self.empty_state.show()
        self.update_info_summary()

    def get_image_path(self):
        return self.image_path

    def get_vtf_path(self):
        return self.vtf_path

    def load_vtf(self, path):
        """Загружает VTF файл — рендерит первый кадр через VTFLib."""
        import os
        if not os.path.exists(path):
            return

        self.vtf_path = path
        self.image_path = None
        self.empty_state.hide()
        self.preview.show()
        self.preview.clear()
        self.preview.setStyleSheet(self.preview_style)

        rendered = False
        png_for_3d = None
        try:
            from src.services.vtflib_wrapper import VTFLib
            rgba_bytes, vtf_w, vtf_h = VTFLib.read_vtf_as_rgba(path)
            from PySide6.QtGui import QImage, QPixmap
            qimage = QImage(rgba_bytes, vtf_w, vtf_h, vtf_w * 4, QImage.Format_RGBA8888)
            if not qimage.isNull():
                preview_w = max(self.preview.width(), 600)
                pixmap = QPixmap.fromImage(qimage).scaled(
                    preview_w, 500, Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                self.preview.setPixmap(pixmap)
                rendered = True

                # Сохраняем PNG для 3D текстуры
                import tempfile
                png_for_3d = tempfile.mktemp(suffix='.png')
                from PIL import Image
                img = Image.frombytes("RGBA", (vtf_w, vtf_h), rgba_bytes)
                img.save(png_for_3d)
        except Exception as e:
            logger.warning(f"Не удалось отрендерить VTF: {e}")

        if not rendered:
            self.preview.setText(f"VTF: {os.path.basename(path)}")
            self.preview.setStyleSheet(
                self.preview_style + "QLabel { color:#ccc; font-size:14px; }"
            )
            self.preview.setAlignment(Qt.AlignCenter)

        # Применяем на 3D модель или CritHIT billboard
        if png_for_3d and self._3d_available and self._3d_widget:
            self.image_path = png_for_3d  # сохраняем для _switch_to_3d
            if self.is_3d_mode():
                if self._crithit_mode:
                    self._3d_widget.update_crithit_texture(png_for_3d)
                else:
                    self._3d_widget.update_texture_file(png_for_3d)

        self.update_info_summary()

    def display_image(self, pil_image):
        """Отображает PIL Image в превью."""
        self._stop_gif()
        try:
            import tempfile
            temp_path = tempfile.mktemp(suffix='.png')
            pil_image.save(temp_path, 'PNG')
            self.image_path = temp_path
            self.vtf_path = None
            self.preview.show()
            self.empty_state.hide()
            self.preview.updateGeometry()
            self.updateGeometry()

            from PySide6.QtCore import QTimer
            def scale_image():
                w = max(self.preview.width(), self.width(), 600)
                pix = QPixmap(temp_path).scaled(w, 500, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.preview.setPixmap(pix)
            QTimer.singleShot(50, scale_image)
            QTimer.singleShot(200, scale_image)
            self.update_info_summary()
        except Exception as e:
            logger.error(f"Ошибка при отображении изображения: {e}", exc_info=True)
            import tempfile
            temp_path = tempfile.mktemp(suffix='.png')
            pil_image.save(temp_path, 'PNG')
            self.load_image(temp_path)

    # ── Info summary ─────────────────────────────────────────────────────── #

    def update_info_summary(self):
        if hasattr(self.parent, 'settings_panel'):
            settings = self.parent.settings_panel.get_settings()
            size = settings.get('size', (512, 512))
            self.info_resolution.setText(f"{self.t['info_resolution']} {size[0]}x{size[1]}")
            self.info_format.setText(f"{self.t['info_format']} {settings.get('format', 'DXT1')}")
            flags = settings.get('flags', [])
            self.info_flags.setText(
                f"{self.t['info_flags']} {', '.join(flags)}" if flags
                else self.t['info_flags_none']
            )
            fn = settings.get('filename', '')
            self.info_filename.setText(
                f"{self.t['info_filename']} {fn}" if fn
                else self.t['info_filename_none']
            )
        else:
            self.info_resolution.setText(f"{self.t['info_resolution']} -")
            self.info_format.setText(f"{self.t['info_format']} -")
            self.info_flags.setText(self.t['info_flags_none'])
            self.info_filename.setText(self.t['info_filename_none'])

    # ── Drag & Drop ──────────────────────────────────────────────────────── #

    def setup_drag_drop(self):
        self.empty_state.setAcceptDrops(True)
        self.preview.setAcceptDrops(True)

    def browse_image(self):
        from PySide6.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            self.t.get('open_dialog_title', 'Select file'),
            "",
            f"{self.t.get('images_filter', 'Images')} "
            "(*.png *.jpg *.jpeg *.bmp *.gif *.tiff *.webp);;VTF Files (*.vtf);;All Files (*.*)"
        )
        if file_path:
            if self.is_vtf_file(file_path):
                self.load_vtf(file_path)
            elif self.is_image_file(file_path):
                self.load_image(file_path)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if urls:
                fp = urls[0].toLocalFile()
                if self.is_image_file(fp) or self.is_vtf_file(fp):
                    event.accept()
                    return
        event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            fp = urls[0].toLocalFile()
            if self.is_vtf_file(fp):
                self.load_vtf(fp)
                event.accept()
                return
            elif self.is_image_file(fp):
                self.load_image(fp)
                event.accept()
                return
        event.ignore()

    def is_image_file(self, fp):
        return any(fp.lower().endswith(e)
                   for e in ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff', '.webp'))

    def is_vtf_file(self, fp):
        return fp.lower().endswith('.vtf')

    # ── Language ─────────────────────────────────────────────────────────── #

    def update_language(self, t, lang: str = 'en'):
        self.t = t
        self._lang = lang
        self.empty_text.setText(self.t['drag_text'])
        self.select_file_button.setText(self.t['select_file_btn'])
        self.info_title.setText(self.t['info_title'])
        if self.info_summary.isVisible():
            self.update_info_summary()
        # Обновляем подсказки 3D кнопок
        if hasattr(self, 'btn_load_3d'):
            self.btn_load_3d.setToolTip(self.t.get('3d_load_model_tip', 'Load 3D model'))
        if hasattr(self, 'btn_load_vpk_mod'):
            self.btn_load_vpk_mod.setToolTip(self.t.get('3d_load_vpk_tip', 'Load VPK mod for 3D Preview'))
        if hasattr(self, 'btn_team_red'):
            self.btn_team_red.setToolTip(self.t.get('3d_team_red_tip', 'RED team texture'))
        if hasattr(self, 'btn_team_blu'):
            self.btn_team_blu.setToolTip(self.t.get('3d_team_blu_tip', 'BLU team texture'))
        # Передаём язык в 3D вьювер
        if hasattr(self, '_3d_widget') and self._3d_widget is not None:
            self._3d_widget.set_language(lang)

    # ── Resize ───────────────────────────────────────────────────────────── #

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self.preview.isVisible():
            return

        from PySide6.QtCore import QTimer

        if self._gif_movie is not None and self._gif_orig_size is not None:
            def resize_gif():
                w = max(self.preview.width(), self.width(), 600)
                self._gif_movie.setScaledSize(
                    self._gif_orig_size.scaled(w, 500, Qt.KeepAspectRatio)
                )
            QTimer.singleShot(50, resize_gif)

        elif self.image_path:
            def scale_image():
                import os
                w = max(self.preview.width(), self.width(), 600)
                if os.path.exists(self.image_path):
                    pix = QPixmap(self.image_path)
                    if not pix.isNull():
                        self.preview.setPixmap(
                            pix.scaled(w, 500, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        )
                else:
                    cur = self.preview.pixmap()
                    if cur:
                        self.preview.setPixmap(
                            cur.scaled(w, 500, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        )
            QTimer.singleShot(50, scale_image)


# ── Иконки для кнопок 3D ─────────────────────────────────────────────────── #

def _make_cube_icon(color: str = "#666666", size: int = 16):
    """
    Рисует изометрический куб через QPainter и возвращает QIcon.
    Никаких эмодзи и внешних файлов — чистый QPainter.
    """
    from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor, QPolygonF
    from PySide6.QtCore import Qt, QPointF

    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)

    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)

    pen = QPen(QColor(color))
    pen.setWidthF(1.1)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)

    s = float(size)

    # Верхняя грань (ромб)
    top = QPolygonF([
        QPointF(s * 0.50, s * 0.04),
        QPointF(s * 0.94, s * 0.28),
        QPointF(s * 0.50, s * 0.52),
        QPointF(s * 0.06, s * 0.28),
    ])
    p.drawPolygon(top)

    # Левая боковая грань
    left = QPolygonF([
        QPointF(s * 0.06, s * 0.28),
        QPointF(s * 0.06, s * 0.72),
        QPointF(s * 0.50, s * 0.96),
        QPointF(s * 0.50, s * 0.52),
    ])
    p.drawPolygon(left)

    # Правая боковая грань
    right = QPolygonF([
        QPointF(s * 0.94, s * 0.28),
        QPointF(s * 0.94, s * 0.72),
        QPointF(s * 0.50, s * 0.96),
        QPointF(s * 0.50, s * 0.52),
    ])
    p.drawPolygon(right)

    p.end()
    return QIcon(pix)


def _make_vpk_icon(color: str = "#666666", size: int = 16):
    """
    Рисует иконку архива/пакета (VPK) через QPainter — прямоугольник с крышкой
    и горизонтальными линиями внутри (как папка с файлами).
    Никаких эмодзи и внешних файлов — чистый QPainter.
    """
    from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor
    from PySide6.QtCore import Qt, QRectF, QLineF

    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)

    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)

    pen = QPen(QColor(color))
    pen.setWidthF(1.1)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)

    s = float(size)

    # Основной корпус (прямоугольник)
    body = QRectF(s * 0.08, s * 0.30, s * 0.84, s * 0.64)
    p.drawRect(body)

    # Крышка (трапеция сверху — просто прямоугольник поменьше)
    lid = QRectF(s * 0.18, s * 0.10, s * 0.64, s * 0.22)
    p.drawRect(lid)

    # Горизонтальные линии внутри (содержимое)
    pen2 = QPen(QColor(color))
    pen2.setWidthF(0.9)
    p.setPen(pen2)

    line_xs = s * 0.18
    line_xe = s * 0.82
    for frac in (0.48, 0.60, 0.72):
        y = s * frac
        p.drawLine(QLineF(line_xs, y, line_xe, y))

    p.end()
    return QIcon(pix)


def _make_team_icon(fill_color: str, size: int = 16):
    """
    Рисует иконку командной раскраски — заполненный круг с тонкой обводкой.
    fill_color: '#c0392b' для RED, '#2980b9' для BLU.
    """
    from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor
    from PySide6.QtCore import Qt, QRectF

    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)

    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)

    s = float(size)
    margin = s * 0.12
    rect = QRectF(margin, margin, s - 2 * margin, s - 2 * margin)

    col = QColor(fill_color)
    p.setBrush(col)
    pen = QPen(col.darker(130))
    pen.setWidthF(1.0)
    p.setPen(pen)
    p.drawEllipse(rect)

    p.end()
    return QIcon(pix)
