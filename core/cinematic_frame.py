"""Software-painted instrument surround; decorative, never simulated telemetry.

Uses the HUD's existing animation clock, with no timers, services or assets.
"""
import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QRadialGradient


def paint_instrument_frame(painter, width, height, phase, accent, amber,
                           background, quiet=False):
    """Paint a responsive optical instrument behind the actual assistant core."""
    if width < 1 or height < 1:
        return
    p = painter
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    cx, cy = width / 2, height * 0.43
    radius = min(width * 0.43, height * 0.37)

    def ink(value, alpha):
        colour = QColor(value)
        colour.setAlpha(alpha)
        return colour

    # Broad atmospheric falloff, not a blur effect or an expensive extra layer.
    glow = QRadialGradient(cx, cy, radius * 1.6)
    glow.setColorAt(0, ink(accent, 30))
    glow.setColorAt(0.55, ink(accent, 12))
    glow.setColorAt(1, ink(background, 0))
    p.fillRect(QRectF(0, 0, width, height), glow)
    p.setBrush(Qt.BrushStyle.NoBrush)

    # Perspective floor extends the focal plane below the reactor.
    horizon = height * 0.76
    p.setPen(QPen(ink(accent, 18), 1))
    for lane in range(-5, 6):
        p.drawLine(QPointF(cx + lane * 22, horizon),
                   QPointF(cx + lane * width / 6, height))
    for depth in (0.12, 0.30, 0.55, 0.88):
        y = horizon + (height - horizon) * depth
        p.drawLine(QPointF(16, y), QPointF(width - 16, y))

    angle = 0 if quiet else phase * 7
    for scale, segments, offset in ((1.0, 3, angle), (0.93, 4, -angle * 0.6)):
        r = radius * scale
        rect = QRectF(cx-r, cy-r, r*2, r*2)
        p.setPen(QPen(ink(accent, 50), 1))
        p.drawEllipse(rect)
        for i in range(segments):
            p.setPen(QPen(ink(amber if i == 0 else accent, 145), 2))
            p.drawArc(rect, int((offset + i * 360 / segments) * 16),
                      int((360 / segments - 28) * 16))

    # Calibration ticks are geometry, not made-up metrics.
    for i in range(120):
        a = math.radians(i * 3)
        major = i % 10 == 0
        r0, r1 = radius * 1.035, radius * (1.075 if major else 1.05)
        p.setPen(QPen(ink(accent, 135 if major else 48), 1))
        p.drawLine(QPointF(cx + math.cos(a)*r0, cy + math.sin(a)*r0),
                   QPointF(cx + math.cos(a)*r1, cy + math.sin(a)*r1))

    # Orthogonal reference marks, with a clear central region for the hologram.
    p.setPen(QPen(ink(accent, 65), 1))
    for sign in (-1, 1):
        x = cx + sign * radius * 1.11
        if 20 < x < width - 20:
            p.drawLine(QPointF(x, cy-25), QPointF(x, cy+25))
            p.drawLine(QPointF(x-5, cy), QPointF(x+5, cy))
    p.setFont(QFont('Courier New', 8))
    p.setPen(ink(accent, 175))
    p.drawText(QRectF(30, 24, width-60, 18), Qt.AlignmentFlag.AlignLeft,
               'J / PERSONAL INTELLIGENCE')
    p.setPen(ink(amber, 200))
    p.drawText(QRectF(30, height-27, width-60, 16), Qt.AlignmentFlag.AlignRight,
               'VOICE INTERFACE / COMMAND CORE')
    p.restore()
