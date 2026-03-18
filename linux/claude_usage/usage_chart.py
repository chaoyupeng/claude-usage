"""Usage history line chart — Catmull-Rom spline rendering via Cairo."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

import gi

gi.require_version("Gtk", "4.0")

import cairo
from gi.repository import Gdk, Gtk  # noqa: E402

from .models import TimeRange, UsageDataPoint


# ---------------------------------------------------------------------------
# Colour constants
# ---------------------------------------------------------------------------

_COLOR_5H = (0.345, 0.537, 0.918)      # blue
_COLOR_7D = (0.918, 0.569, 0.247)      # orange
_COLOR_SONNET = (0.404, 0.729, 0.486)  # green
_GRID_COLOR = (0.30, 0.30, 0.32)
_BG_COLOR = (0.18, 0.18, 0.20)
_TEXT_COLOR = (0.70, 0.70, 0.70)
_TOOLTIP_BG = (0.12, 0.12, 0.14, 0.92)


# ---------------------------------------------------------------------------
# Catmull-Rom helper
# ---------------------------------------------------------------------------

def _catmull_rom(
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    p3: Tuple[float, float],
    n_segments: int = 16,
) -> List[Tuple[float, float]]:
    """Interpolate between p1 and p2 using Catmull-Rom spline."""
    points: List[Tuple[float, float]] = []
    for i in range(n_segments + 1):
        t = i / n_segments
        t2 = t * t
        t3 = t2 * t
        x = 0.5 * (
            (2 * p1[0])
            + (-p0[0] + p2[0]) * t
            + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
            + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3
        )
        y = 0.5 * (
            (2 * p1[1])
            + (-p0[1] + p2[1]) * t
            + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
            + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3
        )
        points.append((x, y))
    return points


# ---------------------------------------------------------------------------
# UsageChart
# ---------------------------------------------------------------------------

class UsageChart(Gtk.Box):
    """Line chart showing historical usage with a time-range selector."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        self._data_points: List[UsageDataPoint] = []
        self._time_range: TimeRange = TimeRange.DAY_1
        self._hover_x: Optional[float] = None

        # Time range selector
        range_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        range_box.set_halign(Gtk.Align.CENTER)
        range_box.add_css_class("linked")

        self._range_buttons: dict[TimeRange, Gtk.ToggleButton] = {}
        for tr in TimeRange:
            btn = Gtk.ToggleButton(label=tr.value)
            btn.set_active(tr == self._time_range)
            btn.connect("toggled", self._on_range_toggled, tr)
            range_box.append(btn)
            self._range_buttons[tr] = btn

        self.append(range_box)

        # Drawing area
        self._canvas = Gtk.DrawingArea()
        self._canvas.set_content_width(340)
        self._canvas.set_content_height(200)
        self._canvas.set_hexpand(True)
        self._canvas.set_draw_func(self._draw)

        # Hover motion tracking
        motion_ctrl = Gtk.EventControllerMotion()
        motion_ctrl.connect("motion", self._on_motion)
        motion_ctrl.connect("leave", self._on_leave)
        self._canvas.add_controller(motion_ctrl)

        self.append(self._canvas)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, data_points: List[UsageDataPoint]) -> None:
        self._data_points = data_points
        self._canvas.queue_draw()

    # ------------------------------------------------------------------
    # Range selector
    # ------------------------------------------------------------------

    def _on_range_toggled(self, btn: Gtk.ToggleButton, tr: TimeRange) -> None:
        if not btn.get_active():
            return
        self._time_range = tr
        # Deactivate other buttons
        for other_tr, other_btn in self._range_buttons.items():
            if other_tr != tr:
                other_btn.set_active(False)
        self._canvas.queue_draw()

    # ------------------------------------------------------------------
    # Hover
    # ------------------------------------------------------------------

    def _on_motion(
        self, _ctrl: Gtk.EventControllerMotion, x: float, _y: float
    ) -> None:
        self._hover_x = x
        self._canvas.queue_draw()

    def _on_leave(self, _ctrl: Gtk.EventControllerMotion) -> None:
        self._hover_x = None
        self._canvas.queue_draw()

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def _draw(
        self,
        _area: Gtk.DrawingArea,
        cr: cairo.Context,
        width: int,
        height: int,
    ) -> None:
        pad_left = 32.0
        pad_right = 8.0
        pad_top = 8.0
        pad_bottom = 20.0
        chart_w = width - pad_left - pad_right
        chart_h = height - pad_top - pad_bottom

        # Background
        cr.set_source_rgb(*_BG_COLOR)
        cr.rectangle(0, 0, width, height)
        cr.fill()

        # Grid lines and y-axis labels
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(9)
        for pct in (0, 25, 50, 75, 100):
            y = pad_top + chart_h * (1 - pct / 100.0)
            cr.set_source_rgb(*_GRID_COLOR)
            cr.set_line_width(0.5)
            cr.move_to(pad_left, y)
            cr.line_to(pad_left + chart_w, y)
            cr.stroke()

            cr.set_source_rgb(*_TEXT_COLOR)
            label = f"{pct}%"
            extents = cr.text_extents(label)
            cr.move_to(pad_left - extents.width - 4, y + extents.height / 2)
            cr.show_text(label)

        # Filter data points for the selected time range
        now = datetime.now(timezone.utc)
        range_start = now - timedelta(seconds=self._time_range.interval)
        filtered = [p for p in self._data_points if p.timestamp >= range_start]

        if len(filtered) < 2:
            cr.set_source_rgb(*_TEXT_COLOR)
            cr.set_font_size(11)
            msg = "Not enough data"
            extents = cr.text_extents(msg)
            cr.move_to(
                pad_left + (chart_w - extents.width) / 2,
                pad_top + (chart_h + extents.height) / 2,
            )
            cr.show_text(msg)
            self._draw_x_axis(cr, pad_left, pad_top, chart_w, chart_h, range_start, now)
            return

        # Sort by timestamp
        filtered.sort(key=lambda p: p.timestamp)

        # Map data to screen coords
        total_secs = self._time_range.interval

        def _to_screen(
            ts: datetime, pct: float
        ) -> Tuple[float, float]:
            t_offset = (ts - range_start).total_seconds()
            x = pad_left + (t_offset / total_secs) * chart_w
            y = pad_top + chart_h * (1 - max(0.0, min(1.0, pct)))
            return (x, y)

        # Build series
        series_5h = [_to_screen(p.timestamp, p.pct_5h) for p in filtered]
        series_7d = [_to_screen(p.timestamp, p.pct_7d) for p in filtered]
        series_sonnet: Optional[List[Tuple[float, float]]] = None
        if any(p.pct_sonnet_7d is not None for p in filtered):
            series_sonnet = [
                _to_screen(p.timestamp, p.pct_sonnet_7d or 0.0) for p in filtered
            ]

        # Draw series as smooth curves
        self._draw_spline(cr, series_5h, _COLOR_5H, chart_w, chart_h, pad_left, pad_top)
        self._draw_spline(cr, series_7d, _COLOR_7D, chart_w, chart_h, pad_left, pad_top)
        if series_sonnet:
            self._draw_spline(
                cr, series_sonnet, _COLOR_SONNET, chart_w, chart_h, pad_left, pad_top
            )

        # X-axis labels
        self._draw_x_axis(cr, pad_left, pad_top, chart_w, chart_h, range_start, now)

        # Tooltip on hover
        if self._hover_x is not None and pad_left <= self._hover_x <= pad_left + chart_w:
            self._draw_tooltip(
                cr, filtered, range_start, total_secs,
                pad_left, pad_top, chart_w, chart_h, width, height,
            )

    # ------------------------------------------------------------------
    # Spline drawing
    # ------------------------------------------------------------------

    @staticmethod
    def _draw_spline(
        cr: cairo.Context,
        points: List[Tuple[float, float]],
        color: Tuple[float, float, float],
        chart_w: float,
        chart_h: float,
        pad_left: float,
        pad_top: float,
    ) -> None:
        if len(points) < 2:
            return

        cr.set_source_rgb(*color)
        cr.set_line_width(1.5)

        # Build Catmull-Rom spline
        all_pts: List[Tuple[float, float]] = []
        n = len(points)
        for i in range(n - 1):
            p0 = points[max(0, i - 1)]
            p1 = points[i]
            p2 = points[i + 1]
            p3 = points[min(n - 1, i + 2)]
            seg_count = max(4, int(abs(p2[0] - p1[0]) / 3))
            seg = _catmull_rom(p0, p1, p2, p3, seg_count)
            if i == 0:
                all_pts.extend(seg)
            else:
                all_pts.extend(seg[1:])  # skip duplicate start

        if not all_pts:
            return

        cr.move_to(*all_pts[0])
        for pt in all_pts[1:]:
            cr.line_to(*pt)
        cr.stroke()

    # ------------------------------------------------------------------
    # X-axis
    # ------------------------------------------------------------------

    @staticmethod
    def _draw_x_axis(
        cr: cairo.Context,
        pad_left: float,
        pad_top: float,
        chart_w: float,
        chart_h: float,
        range_start: datetime,
        range_end: datetime,
    ) -> None:
        total_secs = (range_end - range_start).total_seconds()
        if total_secs <= 0:
            return

        cr.set_source_rgb(*_TEXT_COLOR)
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(9)

        # Determine label count
        label_count = 5
        y = pad_top + chart_h + 14

        for i in range(label_count + 1):
            t = range_start + timedelta(seconds=(i / label_count) * total_secs)
            if total_secs <= 3600:
                text = t.strftime("%H:%M")
            elif total_secs <= 86400:
                text = t.strftime("%H:%M")
            else:
                text = t.strftime("%m/%d")

            x = pad_left + (i / label_count) * chart_w
            extents = cr.text_extents(text)
            cr.move_to(x - extents.width / 2, y)
            cr.show_text(text)

    # ------------------------------------------------------------------
    # Tooltip
    # ------------------------------------------------------------------

    def _draw_tooltip(
        self,
        cr: cairo.Context,
        points: List[UsageDataPoint],
        range_start: datetime,
        total_secs: float,
        pad_left: float,
        pad_top: float,
        chart_w: float,
        chart_h: float,
        canvas_w: int,
        canvas_h: int,
    ) -> None:
        if self._hover_x is None:
            return

        # Find the closest point
        hover_frac = (self._hover_x - pad_left) / chart_w
        hover_time = range_start + timedelta(seconds=hover_frac * total_secs)

        closest: Optional[UsageDataPoint] = None
        closest_dist = float("inf")
        for p in points:
            dist = abs((p.timestamp - hover_time).total_seconds())
            if dist < closest_dist:
                closest_dist = dist
                closest = p

        if closest is None:
            return

        # Build tooltip lines
        lines = [
            f"5h: {closest.pct_5h * 100:.1f}%",
            f"7d: {closest.pct_7d * 100:.1f}%",
        ]
        if closest.pct_sonnet_7d is not None:
            lines.append(f"Sonnet 7d: {closest.pct_sonnet_7d * 100:.1f}%")
        lines.append(closest.timestamp.strftime("%H:%M"))

        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(10)

        line_height = 14.0
        max_text_w = 0.0
        for line in lines:
            ext = cr.text_extents(line)
            max_text_w = max(max_text_w, ext.width)

        tooltip_w = max_text_w + 16
        tooltip_h = line_height * len(lines) + 12

        # Position tooltip near hover
        tx = self._hover_x + 10
        ty = pad_top + 10
        if tx + tooltip_w > canvas_w:
            tx = self._hover_x - tooltip_w - 10

        # Background
        cr.set_source_rgba(*_TOOLTIP_BG)
        _rounded_rect_path(cr, tx, ty, tooltip_w, tooltip_h, 4)
        cr.fill()

        # Vertical indicator line
        cr.set_source_rgba(1, 1, 1, 0.3)
        cr.set_line_width(0.5)
        cr.move_to(self._hover_x, pad_top)
        cr.line_to(self._hover_x, pad_top + chart_h)
        cr.stroke()

        # Text
        cr.set_source_rgb(0.9, 0.9, 0.9)
        for i, line in enumerate(lines):
            cr.move_to(tx + 8, ty + 12 + i * line_height)
            cr.show_text(line)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _rounded_rect_path(
    cr: cairo.Context, x: float, y: float, w: float, h: float, r: float
) -> None:
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()
