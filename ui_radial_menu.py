#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Radial (pie) menu for Quick Convert — clean donut ring rendering.

Angles: QPainterPath.arcTo and painter.drawArc work in plain degrees
(1/16 of a degree only applies to QPolygon-like drawPie int calls —
we avoid the pie primitive entirely and draw ring sectors with paths).
"""

import math
import os

DEBUG = bool(os.environ.get("RADIAL_DEBUG"))

from PySide6.QtCore import Qt, Signal, Property, QRectF, QPointF, QSize, QTimer
from PySide6.QtCore import QPropertyAnimation, QEasingCurve
from PySide6.QtGui import (
    QPainter, QPainterPath, QColor, QPen, QBrush, QFont,
)
from PySide6.QtWidgets import QWidget

# Geometry
R_IN = 55.0          # inner radius (px)
R_OUT = 140.0        # outer radius (px)
GAP_DEG = 2.5        # gap between neighbouring sectors (deg)

# Theme
C_HOVER      = QColor("#2563EB")      # hovered sector
C_IDLE       = QColor(30, 30, 35, 230) # rgba(30,30,35,230)
C_BORDER     = QColor("#333333")      # sector separators / outline
C_TEXT       = QColor(255, 255, 255)   # white bold label
C_CENTER_BG  = QColor(14, 14, 18, 235)
C_CENTER_FG  = QColor(170, 170, 190)
C_ACCENT     = QColor("#2563EB")


def _ring_sector_path(radius_inner: float, radius_outer: float,
                      angle_start: float, angle_end: float) -> QPainterPath:
    """Ring sector as a path.

    angle_start..angle_end are *visual* degrees: 0° = east, positive =
    clockwise ON SCREEN.  Qt's arcTo uses the mirrored convention
    (positive = counterclockwise mathematically, which appears clockwise
    because the y-axis points down) — hence the negated angles here.
    """
    path = QPainterPath()
    rect_o = QRectF(-radius_outer, -radius_outer,
                    radius_outer * 2, radius_outer * 2)
    rect_i = QRectF(-radius_inner, -radius_inner,
                    radius_inner * 2, radius_inner * 2)

    path.arcMoveTo(rect_o, -angle_start)
    path.arcTo(rect_o, -angle_start, -(angle_end - angle_start))
    path.arcTo(rect_i, -angle_end, (angle_end - angle_start))
    path.closeSubpath()
    return path


class RadialMenu(QWidget):
    """Frameless translucent donut menu, closes on pick / Esc / right click."""

    formatSelected = Signal(str)
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self._hover = -1
        self._title = ""
        self._scale = 0.55

        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.NoFocus)   # popup grabs input itself

        side = int(R_OUT * 2 + 20)
        self.setFixedSize(QSize(side, side))

    # ------------------------------------------------------------------
    def popup(self, items, global_pos=None, title=""):
        """Show the donut centered exactly under the current mouse cursor.

        Coordinates reported by external hooks (pynput / win32) are in
        *physical* pixels, while Qt works in logical ones (125/150 % DPI
        scaling) — mixing them makes the menu land off-target.  QCursor.pos()
        is always correct, so we position the window by the cursor.
        """
        if not items:
            return
        self._items = list(items)
        self._title = title or ""
        self._hover = -1

        # Anchor: the *actual* cursor position, queried from Qt itself
        from PySide6.QtGui import QCursor
        cursor = QCursor.pos()

        # Ensure the real size is known before positioning
        side = int(R_OUT * 2 + 20)
        if (self.width(), self.height()) != (side, side):
            self.resize(side, side)

        # Center of the window must coincide with the cursor point
        x = cursor.x() - (self.width() // 2)
        y = cursor.y() - (self.height() // 2)

        # Keep the menu fully on screen
        screen = self.screen().availableGeometry()
        x = max(screen.left(), min(x, screen.right() - self.width()))
        y = max(screen.top(), min(y, screen.bottom() - self.height()))

        self.move(x, y)
        self.show()

        anim = QPropertyAnimation(self, b"scaleFactor", self)
        anim.setDuration(130)
        anim.setStartValue(0.55)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(anim.deleteLater)
        anim.start()
        self._anim = anim

    def close_menu(self, cancel=True):
        if self.isVisible():
            self.hide()
        if cancel:
            self.cancelled.emit()

    # ------------------------------------------------------------------
    # Geometry / hit test
    # ------------------------------------------------------------------
    def _center(self) -> QPointF:
        return QPointF(self.width() / 2.0, self.height() / 2.0)

    def _sector_bounds(self):
        """[(start_deg, end_deg)] per item. Item 0 is centered at the top."""
        n = len(self._items)
        step = 360.0 / n
        first_center = -90.0
        return [(first_center + i * step - step / 2.0,
                 first_center + i * step + step / 2.0) for i in range(n)]

    def _hit_index(self, pos: QPointF) -> int:
        c = self._center()
        dx, dy = pos.x() - c.x(), pos.y() - c.y()
        dist = math.hypot(dx, dy)
        if dist < R_IN or dist > R_OUT:
            return -1
        # Qt's arcTo: 0° is at 3 o'clock, sweep counterclockwise?  No —
        # angles grow clockwise on screen because +y points down.
        ang = math.degrees(math.atan2(dy, dx))  # -180..180, 0 = east, cw
        for i, (a0, a1) in enumerate(self._sector_bounds()):
            if a0 <= ang <= a1:
                return i
        return -1

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

        p.save()
        p.translate(self._center())
        p.scale(self._scale, self._scale)

        # Pass 1: fills
        for i, (a0, a1) in enumerate(self._sector_bounds()):
            gap = GAP_DEG
            hovered = (i == self._hover)
            path = _ring_sector_path(R_IN, R_OUT, a0 + gap, a1 - gap)
            if hovered:
                p.fillPath(path, C_HOVER)
            else:
                p.fillPath(path, C_IDLE)

        # Pass 2: separators + labels
        for i, (a0, a1) in enumerate(self._sector_bounds()):
            gap = GAP_DEG
            hovered = (i == self._hover)
            path = _ring_sector_path(R_IN, R_OUT, a0 + gap, a1 - gap)

            p.setPen(QPen(C_BORDER, 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)

            # --- Label on the sector bisector, horizontal text -----------
            mid = (a0 + a1) / 2.0
            rad = math.radians(mid)
            r_text = (R_IN + R_OUT) / 2.0
            tx = r_text * math.cos(rad)
            ty = r_text * math.sin(rad)

            f = QFont("Segoe UI", 11)
            f.setBold(True)
            p.setFont(f)
            if DEBUG:
                p.setPen(QPen(QColor("cyan")))
                p.setBrush(Qt.NoBrush)
                p.drawRect(QRectF(tx - 60, ty - 14, 120, 28))
            p.setPen(QPen(C_TEXT))
            p.drawText(QRectF(tx - 60, ty - 14, 120, 28),
                       Qt.AlignCenter, self._items[i])

        # Center hub (drawn at origin — we are already translated to center)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(C_CENTER_BG))
        p.drawEllipse(QPointF(0, 0), R_IN - 2, R_IN - 2)
        p.setPen(QPen(C_ACCENT, 2.0))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(0, 0), R_IN - 2, R_IN - 2)

        # Title (truncated) and hint inside the hub
        f = QFont("Segoe UI", 9, QFont.DemiBold if self._title else QFont.Normal)
        p.setFont(f)
        p.setPen(QPen(C_CENTER_FG))
        shown = self._title if len(self._title) <= 8 else self._title[:7] + "…"
        p.drawText(QRectF(-R_IN + 10, -R_IN + 26, R_IN * 2 - 20, 20),
                   Qt.AlignCenter, shown)
        p.setFont(QFont("Segoe UI", 7))
        p.setPen(QColor(120, 120, 135))
        p.drawText(QRectF(-R_IN + 10, R_IN - 42, R_IN * 2 - 20, 18),
                   Qt.AlignCenter, "Esc / ПКМ — отмена")

        p.restore()
        p.end()

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------
    def mouseMoveEvent(self, ev):
        idx = self._hit_index(ev.position())
        if idx != self._hover:
            self._hover = idx
            self.update()

    def leaveEvent(self, ev):
        self._hover = -1
        self.update()
        super().leaveEvent(ev)

    def mousePressEvent(self, ev):
        import logging
        logging.info("menu press btn=%s pos=%s", ev.button(), ev.position())
        if ev.button() == Qt.RightButton:
            self.close_menu(cancel=True)
            return
        if ev.button() == Qt.LeftButton:
            idx = self._hit_index(ev.position())
            logging.info("hit index=%s items=%s", idx, self._items)
            if idx >= 0:
                item = self._items[idx]
                self.formatSelected.emit(item)
                self.close_menu(cancel=False)
            else:
                self.close_menu(cancel=True)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.close_menu(cancel=True)
        super().keyPressEvent(ev)

    # ------------------------------------------------------------------
    # Animated scale property
    # ------------------------------------------------------------------
    def get_scale(self):
        return self._scale

    def set_scale(self, v):
        self._scale = v
        self.update()

    scaleFactor = Property(float, get_scale, set_scale)
