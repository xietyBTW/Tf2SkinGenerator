"""
Векторные иконки для кнопок панели превью.

Все иконки рисуются вручную через QPainter (правило проекта: без эмодзи).
Функции чистые — принимают цвет/размер и возвращают QIcon, не зависят от
состояния PreviewPanel, поэтому вынесены в отдельный модуль и переиспользуются
как карточками (`preview_widgets`), так и самой панелью.
"""


def _make_cube_icon(color: str = "#666666", size: int = 16):
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
    p.drawPolygon(QPolygonF([
        QPointF(s*.50, s*.04), QPointF(s*.94, s*.28),
        QPointF(s*.50, s*.52), QPointF(s*.06, s*.28),
    ]))
    p.drawPolygon(QPolygonF([
        QPointF(s*.06, s*.28), QPointF(s*.06, s*.72),
        QPointF(s*.50, s*.96), QPointF(s*.50, s*.52),
    ]))
    p.drawPolygon(QPolygonF([
        QPointF(s*.94, s*.28), QPointF(s*.94, s*.72),
        QPointF(s*.50, s*.96), QPointF(s*.50, s*.52),
    ]))
    p.end()
    return QIcon(pix)


def _make_replace_icon(color: str = "#666666", size: int = 16):
    """Иконка «заменить модель» — две стрелки-swap (⇄)."""
    from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor
    from PySide6.QtCore import Qt, QLineF
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(1.2)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    s = float(size)
    # верхняя стрелка вправо
    p.drawLine(QLineF(s*.16, s*.36, s*.84, s*.36))
    p.drawLine(QLineF(s*.84, s*.36, s*.67, s*.24))
    p.drawLine(QLineF(s*.84, s*.36, s*.67, s*.48))
    # нижняя стрелка влево
    p.drawLine(QLineF(s*.84, s*.64, s*.16, s*.64))
    p.drawLine(QLineF(s*.16, s*.64, s*.33, s*.52))
    p.drawLine(QLineF(s*.16, s*.64, s*.33, s*.76))
    p.end()
    return QIcon(pix)


def _make_gear_icon(color: str = "#bbbbbb", size: int = 16):
    """Иконка «настройки» — шестерёнка."""
    import math
    from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor
    from PySide6.QtCore import Qt, QPointF, QLineF
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    s = float(size)
    cx = cy = s / 2.0
    r_body = s * 0.27     # радиус «тела» шестерёнки (вершины зубьев)
    r_out = s * 0.45      # вершина зубьев
    r_hole = s * 0.115    # центральное отверстие
    n_teeth = 8

    # ── Зубья (толстые скруглённые нубы) ──
    tooth_pen = QPen(QColor(color))
    tooth_pen.setWidthF(max(1.6, s * 0.11))
    tooth_pen.setCapStyle(Qt.RoundCap)
    p.setPen(tooth_pen)
    p.setBrush(Qt.NoBrush)
    for i in range(n_teeth):
        a = (2.0 * math.pi * i) / n_teeth
        ca, sa = math.cos(a), math.sin(a)
        p.drawLine(QLineF(cx + ca * r_body, cy + sa * r_body,
                          cx + ca * r_out, cy + sa * r_out))

    # ── Кольцо тела + центральное отверстие ──
    ring_pen = QPen(QColor(color))
    ring_pen.setWidthF(1.4)
    p.setPen(ring_pen)
    p.drawEllipse(QPointF(cx, cy), r_body, r_body)
    p.drawEllipse(QPointF(cx, cy), r_hole, r_hole)
    p.end()
    return QIcon(pix)


def _make_vpk_icon(color: str = "#666666", size: int = 16):
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
    p.drawRect(QRectF(s*.08, s*.30, s*.84, s*.64))
    p.drawRect(QRectF(s*.18, s*.10, s*.64, s*.22))
    pen2 = QPen(QColor(color))
    pen2.setWidthF(0.9)
    p.setPen(pen2)
    for frac in (0.48, 0.60, 0.72):
        y = s * frac
        p.drawLine(QLineF(s*.18, y, s*.82, y))
    p.end()
    return QIcon(pix)


def _make_plus_icon(color: str = "#aaaaaa", size: int = 14):
    """Иконка «+» (две линии) — для кнопки «сделать командным»."""
    from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor
    from PySide6.QtCore import Qt, QPointF
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    s = float(size)
    pen = QPen(QColor(color))
    pen.setWidthF(2.0)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    c = s / 2.0
    m = s * 0.20
    p.drawLine(QPointF(c, m), QPointF(c, s - m))
    p.drawLine(QPointF(m, c), QPointF(s - m, c))
    p.end()
    return QIcon(pix)


def _make_eye_icon(color: str = "#cccccc", size: int = 16):
    """Иконка «глаз» — для кнопки «Прочее» (служебные текстуры: глаза/убер/зомби)."""
    from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor, QPainterPath
    from PySide6.QtCore import Qt, QPointF
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    s = float(size)
    cy = s / 2.0
    col = QColor(color)
    pen = QPen(col)
    pen.setWidthF(1.4)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    # Миндалевидный контур глаза (две дуги-века).
    path = QPainterPath()
    path.moveTo(s * 0.10, cy)
    path.quadTo(s * 0.5, s * 0.16, s * 0.90, cy)
    path.quadTo(s * 0.5, s * 0.84, s * 0.10, cy)
    p.drawPath(path)
    # Зрачок.
    r = s * 0.17
    p.setBrush(col)
    p.drawEllipse(QPointF(s * 0.5, cy), r, r)
    p.end()
    return QIcon(pix)


def _make_folder_icon(color: str = "#666666", size: int = 16):
    """Иконка «открыть файл» — папка."""
    from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor, QPainterPath
    from PySide6.QtCore import Qt
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(1.2)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    s = float(size)
    path = QPainterPath()
    path.moveTo(s*.10, s*.82)
    path.lineTo(s*.10, s*.22)
    path.lineTo(s*.40, s*.22)
    path.lineTo(s*.50, s*.34)
    path.lineTo(s*.90, s*.34)
    path.lineTo(s*.90, s*.82)
    path.closeSubpath()
    p.drawPath(path)
    p.end()
    return QIcon(pix)


def _make_image_icon(color: str = "#666666", size: int = 16):
    """Иконка «текстура» — картинка (рамка, горы, солнце)."""
    from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor
    from PySide6.QtCore import Qt, QRectF, QPointF, QLineF
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    col = QColor(color)
    pen = QPen(col)
    pen.setWidthF(1.2)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    s = float(size)
    p.drawRect(QRectF(s*.10, s*.14, s*.80, s*.72))
    # горы
    p.drawLine(QLineF(s*.16, s*.78, s*.42, s*.46))
    p.drawLine(QLineF(s*.42, s*.46, s*.60, s*.66))
    p.drawLine(QLineF(s*.60, s*.66, s*.72, s*.54))
    p.drawLine(QLineF(s*.72, s*.54, s*.84, s*.78))
    # солнце
    p.setBrush(col)
    p.drawEllipse(QPointF(s*.68, s*.30), s*.07, s*.07)
    p.end()
    return QIcon(pix)


def _make_droplet_icon(color: str = "#666666", size: int = 16):
    """Иконка «цвета текстуры» — капля."""
    from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor, QPainterPath
    from PySide6.QtCore import Qt
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(1.3)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    s = float(size)
    path = QPainterPath()
    path.moveTo(s*.50, s*.08)
    path.cubicTo(s*.78, s*.44, s*.86, s*.60, s*.50, s*.90)
    path.cubicTo(s*.14, s*.60, s*.22, s*.44, s*.50, s*.08)
    p.drawPath(path)
    p.end()
    return QIcon(pix)


def _make_save_icon(color: str = "#666666", size: int = 16):
    """Иконка «сохранить» — дискета."""
    from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor, QPainterPath
    from PySide6.QtCore import Qt, QRectF
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(1.2)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    s = float(size)
    path = QPainterPath()
    path.moveTo(s*.12, s*.12)
    path.lineTo(s*.74, s*.12)
    path.lineTo(s*.88, s*.26)
    path.lineTo(s*.88, s*.88)
    path.lineTo(s*.12, s*.88)
    path.closeSubpath()
    p.drawPath(path)
    p.drawRect(QRectF(s*.30, s*.12, s*.36, s*.22))   # шторка
    p.drawRect(QRectF(s*.26, s*.52, s*.48, s*.36))   # этикетка
    p.end()
    return QIcon(pix)


def _make_restart_icon(color: str = "#666666", size: int = 16):
    """Иконка «перезапуск» — круговая стрелка."""
    import math
    from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor, QPolygonF
    from PySide6.QtCore import Qt, QRectF, QPointF
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    col = QColor(color)
    pen = QPen(col)
    pen.setWidthF(1.4)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    s = float(size)
    m = s * .18
    rect = QRectF(m, m, s - 2*m, s - 2*m)
    # дуга ~300°, начало на 60°
    p.drawArc(rect, 60 * 16, 300 * 16)
    # стрелка на конце дуги (угол 60°)
    r = (s - 2*m) / 2.0
    cx = cy = s / 2.0
    a = math.radians(-60)
    tip_x, tip_y = cx + r * math.cos(a), cy + r * math.sin(a)
    p.setBrush(col)
    p.setPen(Qt.NoPen)
    p.drawPolygon(QPolygonF([
        QPointF(tip_x + s*.02, tip_y - s*.16),
        QPointF(tip_x + s*.16, tip_y + s*.06),
        QPointF(tip_x - s*.14, tip_y + s*.04),
    ]))
    p.end()
    return QIcon(pix)


def _make_pause_icon(color: str = "#666666", size: int = 16):
    """Иконка «пауза» — две вертикальные полосы."""
    from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
    from PySide6.QtCore import Qt, QRectF
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    s = float(size)
    p.drawRoundedRect(QRectF(s*.24, s*.16, s*.18, s*.68), 1.5, 1.5)
    p.drawRoundedRect(QRectF(s*.58, s*.16, s*.18, s*.68), 1.5, 1.5)
    p.end()
    return QIcon(pix)


def _make_play_icon(color: str = "#666666", size: int = 16):
    """Иконка «продолжить» — треугольник."""
    from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QPolygonF
    from PySide6.QtCore import Qt, QPointF
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    s = float(size)
    p.drawPolygon(QPolygonF([
        QPointF(s*.28, s*.14),
        QPointF(s*.84, s*.50),
        QPointF(s*.28, s*.86),
    ]))
    p.end()
    return QIcon(pix)


def _make_team_icon(fill_color: str, size: int = 16):
    from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor
    from PySide6.QtCore import Qt, QRectF
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    s = float(size)
    m = s * .12
    col = QColor(fill_color)
    p.setBrush(col)
    pen = QPen(col.darker(130))
    pen.setWidthF(1.0)
    p.setPen(pen)
    p.drawEllipse(QRectF(m, m, s - 2*m, s - 2*m))
    p.end()
    return QIcon(pix)
