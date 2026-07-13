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
