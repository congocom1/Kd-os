"""core/jarvis_orb.py — the signature JARVIS holographic orb.

A software-rendered (QPainter) holographic globe: rotating meridian and
latitude wireframe, a surface particle field, an inner plasma core that
breathes with the voice, and the orange segmented tech rings from the films.

Drops into the same contract HudCanvas uses for HoloAvatar:
    orb = JarvisOrb()
    orb.step(dt, amp, speaking=..., muted=..., state=..., v_open=..., ...)
    orb.paint(painter, cx, cy, r, primary, accent, background)
    orb.glance(dx, dy, hold)

Everything is precomputed once (sphere point sets are static unit vectors);
per-frame work is one rotate+project pass in plain arithmetic, keeping the
HudCanvas paint budget intact.
"""
from __future__ import annotations

import math
import random

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush, QColor, QLinearGradient, QPainter, QPen, QPolygonF, QRadialGradient,
)


def _c(col: QColor, alpha: float) -> QColor:
    c = QColor(col)
    c.setAlpha(max(0, min(255, int(alpha))))
    return c


def _blend(a: QColor, b: QColor, pct_b: float) -> QColor:
    k = max(0.0, min(1.0, pct_b))
    return QColor(
        int(a.red() + (b.red() - a.red()) * k),
        int(a.green() + (b.green() - a.green()) * k),
        int(a.blue() + (b.blue() - a.blue()) * k),
    )


# Sphere sampling: (meridian count, points per line, latitude bands)
_MERIDIANS, _MPTS, _LATS, _LPTS = 10, 36, 6, 48
_PARTICLES = 48


class JarvisOrb:
    """Holographic globe hologram with a voice-reactive plasma core."""

    SPAN = 2.2          # vertical span in head-radii (HudCanvas sizing contract)

    def __init__(self):
        self._phase = 0.0        # globe rotation (integrated, jump-free)
        self._ring = 0.0         # tech ring rotation
        self._core_pulse = 0.0
        self._energy = 0.0       # smoothed voice energy
        self._tilt_x = 0.0       # glance offsets (radians)
        self._tilt_y = 0.0
        self._tilt_tx = 0.0
        self._tilt_ty = 0.0
        self._state = "IDLE"

        rng = random.Random(42)
        # Unit-sphere point sets, computed once.
        self._meridians = []
        for m in range(_MERIDIANS):
            lon = (m / _MERIDIANS) * math.pi
            self._meridians.append([
                (math.sin(t) * math.sin(lon), math.cos(t), math.sin(t) * math.cos(lon))
                for t in (i / _MPTS * 2 * math.pi for i in range(_MPTS + 1))
            ])
        self._latitudes = []
        for b in range(1, _LATS + 1):
            phi = (b / (_LATS + 1)) * math.pi - math.pi / 2
            r = math.cos(phi)
            self._latitudes.append([
                (r * math.cos(t), math.sin(phi), r * math.sin(t))
                for t in (i / _LPTS * 2 * math.pi for i in range(_LPTS + 1))
            ])
        self._particles = []
        for _ in range(_PARTICLES):
            z = rng.uniform(-1, 1)
            t = rng.uniform(0, 2 * math.pi)
            r = math.sqrt(max(0.0, 1 - z * z))
            self._particles.append((r * math.cos(t), z, r * math.sin(t)))

    # ── animation ─────────────────────────────────────────────────────────
    def step(self, dt, amp, speaking=False, muted=False, state="IDLE",
             v_open=0.0, v_wide=0.0, v_level=0.0, v_seq=None, v_hop=0.0):
        dt = max(0.0, min(0.10, dt))
        self._state = state or "IDLE"
        target = 0.0 if muted else min(1.0, amp * 1.6 + (0.25 if speaking else 0.0))
        self._energy += (target - self._energy) * (0.25 if speaking else 0.08)

        speed = 0.55 + 1.1 * self._energy
        if self._state in ("THINKING", "PROCESSING"):
            speed *= 2.1
        self._phase += dt * speed
        self._ring += dt * (0.35 + 0.9 * self._energy)
        self._core_pulse += dt * (1.4 + 2.2 * self._energy)

        # glance tilts ease toward their targets
        self._tilt_x += (self._tilt_tx - self._tilt_x) * 0.08
        self._tilt_y += (self._tilt_ty - self._tilt_y) * 0.08

    def glance(self, dx: float, dy: float, hold: float = 0.0):
        """Tilt the globe toward a point of interest (bounded)."""
        self._tilt_tx = max(-0.45, min(0.45, dx * 0.5))
        self._tilt_ty = max(-0.30, min(0.30, -dy * 0.35))

    # ── rendering ─────────────────────────────────────────────────────────
    def _project(self, pts, cx, cy, r, cos_a, sin_a, cos_b, sin_b, out):
        """Rotate about Y (spin) then X (tilt), perspective-project to 2D."""
        cam = 4.2
        for x, y, z in pts:
            x1 = x * cos_a + z * sin_a
            z1 = -x * sin_a + z * cos_a
            y1 = y * cos_b - z1 * sin_b
            z2 = y * sin_b + z1 * cos_b
            d = cam / (cam - z2)
            out.append((cx + x1 * r * d, cy + y1 * r * d, z2))

    def paint(self, p: QPainter, cx: float, cy: float, r: float,
              primary: QColor, accent: QColor, bg: QColor) -> None:
        amp = self._energy
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 1. aura
        aura_r = r * 1.5
        aura = QRadialGradient(cx, cy, aura_r)
        aura.setColorAt(0.00, _c(accent, 15 + int(24 * amp)))
        aura.setColorAt(0.55, _c(accent, 6 + int(9 * amp)))
        aura.setColorAt(1.00, _c(accent, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(aura))
        p.drawEllipse(QRectF(cx - aura_r, cy - aura_r, aura_r * 2, aura_r * 2))

        # 2. plasma core — white-hot center cooling into the accent
        pulse = 0.5 + 0.5 * math.sin(self._core_pulse * 2.2)
        core_r = r * (0.26 + 0.04 * pulse + 0.05 * amp)
        core = QRadialGradient(cx, cy, core_r)
        hot = _blend(QColor(255, 255, 255), accent, 0.25)
        core.setColorAt(0.00, _c(hot, 215 + int(40 * pulse)))
        core.setColorAt(0.45, _c(accent, 110 + int(45 * amp)))
        core.setColorAt(1.00, _c(accent, 0))
        p.setBrush(QBrush(core))
        p.drawEllipse(QRectF(cx - core_r, cy - core_r, core_r * 2, core_r * 2))

        # 3. rotating wireframe globe
        tilt = 0.42 + self._tilt_y
        cos_a, sin_a = math.cos(self._phase + self._tilt_x), math.sin(self._phase + self._tilt_x)
        cos_b, sin_b = math.cos(tilt), math.sin(tilt)
        globe_r = r * 0.98
        proj = []
        for line in self._latitudes:
            proj.clear()
            self._project(line, cx, cy, globe_r, cos_a, sin_a, cos_b, sin_b, proj)
            self._stroke_polyline(p, proj, primary, base_a=42, amp=amp)
        for line in self._meridians:
            proj.clear()
            self._project(line, cx, cy, globe_r, cos_a, sin_a, cos_b, sin_b, proj)
            self._stroke_polyline(p, proj, primary, base_a=54, amp=amp)

        # 4. surface particles, brighter on the near hemisphere
        proj.clear()
        self._project(self._particles, cx, cy, globe_r, cos_a, sin_a, cos_b, sin_b, proj)
        p.setPen(Qt.PenStyle.NoPen)
        for x, y, z in proj:
            if z > 0.15:
                a = 100 + 70 * z + 40 * amp
                d = 1.7 + 1.0 * z
            else:
                a = 26
                d = 1.2
            p.setBrush(QBrush(_c(accent, a)))
            p.drawEllipse(QRectF(x - d / 2, y - d / 2, d, d))

        # 5. segmented tech rings (film signature), counter-rotating
        for rr, nseg, gap, speed, wid, alpha in (
                (1.18, 10, 10, +1.0, 0.014, 0.62),
                (1.34, 24, 5, -0.6, 0.007, 0.30)):
            ring_r = r * rr
            rect = QRectF(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2)
            p.setBrush(Qt.BrushStyle.NoBrush)
            seg = 360.0 / nseg - gap
            for i in range(nseg):
                start = (i * 360.0 / nseg + self._ring * 20.0 * speed) % 360.0
                a = alpha
                p.setPen(QPen(_c(accent, a * (140 + 90 * amp)),
                              max(1.0, r * wid),
                              Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
                p.drawArc(rect, int(start * 16), int(seg * 16))

        # 6. horizontal scan sweep across the globe
        sweep_y = cy + math.sin(self._core_pulse * 0.7) * r * 0.9
        beam = QLinearGradient(cx, sweep_y - r * 0.05, cx, sweep_y + r * 0.05)
        beam.setColorAt(0.0, _c(primary, 0))
        beam.setColorAt(0.5, _c(primary, 14 + int(26 * amp)))
        beam.setColorAt(1.0, _c(primary, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(beam))
        p.drawRect(QRectF(cx - r * 1.4, sweep_y - r * 0.05, r * 2.8, r * 0.1))

    @staticmethod
    def _stroke_polyline(p: QPainter, proj, primary: QColor,
                         base_a: float, amp: float) -> None:
        """Draw a projected line, split into near/far segments for depth."""
        near = QPolygonF()
        far = QPolygonF()
        for x, y, z in proj:
            (near if z > 0.0 else far).append(QPointF(x, y))
        if far.size() > 1:
            p.setPen(QPen(_c(primary, base_a * 0.35), 0.7))
            p.drawPolyline(far)
        if near.size() > 1:
            p.setPen(QPen(_c(primary, base_a + 22 * amp), 0.9))
            p.drawPolyline(near)
