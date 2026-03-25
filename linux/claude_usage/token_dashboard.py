"""Token dashboard tab — shows Claude Code log statistics and charts."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

import cairo
from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from .log_models import AggregatedStats, TokenFormatter, TokenUsage

if TYPE_CHECKING:
    from .app import Application


# ---------------------------------------------------------------------------
# Colour palette for token categories
# ---------------------------------------------------------------------------

_COLORS = {
    "cache_read": (0.404, 0.729, 0.486),    # green
    "cache_write": (0.298, 0.569, 0.820),   # blue
    "input": (0.918, 0.671, 0.247),          # amber
    "output": (0.839, 0.373, 0.373),         # red
}

_CHART_BG = (0.18, 0.18, 0.20)
_CHART_GRID = (0.30, 0.30, 0.32)
_CHART_BAR = (0.404, 0.729, 0.486)
_CHART_TEXT = (0.75, 0.75, 0.75)


# ---------------------------------------------------------------------------
# Stat card helper
# ---------------------------------------------------------------------------

def _make_stat_card(title: str, value: str) -> Gtk.Box:
    """Create a small box with a title and a large value label."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    box.set_hexpand(True)
    box.set_margin_start(4)
    box.set_margin_end(4)
    box.set_margin_top(4)
    box.set_margin_bottom(4)

    val_label = Gtk.Label(label=value)
    val_label.add_css_class("title-2")
    val_label.set_halign(Gtk.Align.CENTER)
    box.append(val_label)

    title_label = Gtk.Label(label=title)
    title_label.add_css_class("dim-label")
    title_label.add_css_class("caption")
    title_label.set_halign(Gtk.Align.CENTER)
    box.append(title_label)

    # stash for updates
    box._val_label = val_label  # type: ignore[attr-defined]
    return box


# ---------------------------------------------------------------------------
# TokenBreakdownBar — horizontal stacked bar via Cairo
# ---------------------------------------------------------------------------

class TokenBreakdownBar(Gtk.DrawingArea):
    """Horizontal stacked bar showing cache_read / cache_write / input / output proportions."""

    def __init__(self) -> None:
        super().__init__()
        self.set_content_height(28)
        self.set_content_width(320)
        self.set_hexpand(True)
        self._usage: Optional[TokenUsage] = None
        self.set_draw_func(self._draw)

    def set_usage(self, usage: TokenUsage) -> None:
        self._usage = usage
        self.queue_draw()

    def _draw(
        self,
        _area: Gtk.DrawingArea,
        cr: cairo.Context,
        width: int,
        height: int,
    ) -> None:
        if self._usage is None or self._usage.total == 0:
            cr.set_source_rgb(*_CHART_BG)
            cr.rectangle(0, 0, width, height)
            cr.fill()
            return

        total = self._usage.total
        segments = [
            (self._usage.cache_read, _COLORS["cache_read"], "Cache read"),
            (self._usage.cache_write, _COLORS["cache_write"], "Cache write"),
            (self._usage.input, _COLORS["input"], "Input"),
            (self._usage.output, _COLORS["output"], "Output"),
        ]

        radius = 6.0
        # Draw rounded background
        _rounded_rect(cr, 0, 0, width, height, radius)
        cr.set_source_rgb(*_CHART_BG)
        cr.fill()

        # Clip to rounded rect
        cr.save()
        _rounded_rect(cr, 0, 0, width, height, radius)
        cr.clip()

        x = 0.0
        for count, color, _label in segments:
            if count <= 0:
                continue
            seg_w = (count / total) * width
            cr.set_source_rgb(*color)
            cr.rectangle(x, 0, seg_w, height)
            cr.fill()
            x += seg_w

        cr.restore()


# ---------------------------------------------------------------------------
# BarChart — generic bar chart via Cairo
# ---------------------------------------------------------------------------

class BarChart(Gtk.DrawingArea):
    """A simple vertical bar chart drawn with Cairo."""

    def __init__(self, bar_count: int = 60, chart_height: int = 100) -> None:
        super().__init__()
        self.set_content_height(chart_height)
        self.set_content_width(320)
        self.set_hexpand(True)
        self._bar_count = bar_count
        self._values: list[float] = []
        self._labels: list[str] = []
        self.set_draw_func(self._draw)

    def set_data(self, values: list[float], labels: Optional[list[str]] = None) -> None:
        self._values = values
        self._labels = labels or []
        self.queue_draw()

    def _draw(
        self,
        _area: Gtk.DrawingArea,
        cr: cairo.Context,
        width: int,
        height: int,
    ) -> None:
        if not self._values:
            cr.set_source_rgb(*_CHART_BG)
            cr.rectangle(0, 0, width, height)
            cr.fill()
            return

        pad_bottom = 16 if self._labels else 4
        chart_h = height - pad_bottom - 4
        max_val = max(self._values) if self._values else 1
        if max_val <= 0:
            max_val = 1

        n = len(self._values)
        bar_gap = 1.0
        bar_w = max(1.0, (width - (n - 1) * bar_gap) / n)

        # Background
        cr.set_source_rgb(*_CHART_BG)
        cr.rectangle(0, 0, width, height)
        cr.fill()

        # Grid lines
        cr.set_source_rgb(*_CHART_GRID)
        cr.set_line_width(0.5)
        for frac in (0.25, 0.5, 0.75):
            y = 4 + chart_h * (1 - frac)
            cr.move_to(0, y)
            cr.line_to(width, y)
            cr.stroke()

        # Bars
        for i, val in enumerate(self._values):
            x = i * (bar_w + bar_gap)
            bar_h = (val / max_val) * chart_h if max_val > 0 else 0
            y = 4 + chart_h - bar_h
            cr.set_source_rgb(*_CHART_BAR)
            cr.rectangle(x, y, bar_w, bar_h)
            cr.fill()

        # Labels
        if self._labels:
            cr.set_source_rgb(*_CHART_TEXT)
            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            cr.set_font_size(9)
            step = max(1, n // 6)
            for i in range(0, n, step):
                if i < len(self._labels):
                    lbl = self._labels[i]
                    x = i * (bar_w + bar_gap) + bar_w / 2
                    extents = cr.text_extents(lbl)
                    cr.move_to(x - extents.width / 2, height - 2)
                    cr.show_text(lbl)


# ---------------------------------------------------------------------------
# TokenDashboard
# ---------------------------------------------------------------------------

class TokenDashboard(Gtk.Box):
    """Full token statistics dashboard in a scrollable view."""

    def __init__(self, app_controller: "Application") -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._app = app_controller
        self._last_scanned: Optional[datetime] = None

        # Direct content (no scroll — everything should fit)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        content.set_margin_start(12)
        content.set_margin_end(12)
        content.set_margin_top(4)
        content.set_margin_bottom(4)
        content.set_vexpand(True)
        self.append(content)

        # ------ Header grid: 4 stat cards ------
        stat_grid = Gtk.Grid()
        stat_grid.set_column_homogeneous(True)
        stat_grid.set_row_spacing(4)
        stat_grid.set_column_spacing(4)

        self._card_tokens = _make_stat_card("Total Tokens", "-")
        self._card_sessions = _make_stat_card("Sessions", "-")
        self._card_messages = _make_stat_card("Messages", "-")
        self._card_cost = _make_stat_card("Est. Cost", "-")

        stat_grid.attach(self._card_tokens, 0, 0, 1, 1)
        stat_grid.attach(self._card_sessions, 1, 0, 1, 1)
        stat_grid.attach(self._card_messages, 0, 1, 1, 1)
        stat_grid.attach(self._card_cost, 1, 1, 1, 1)

        content.append(stat_grid)

        # ------ Token breakdown bar ------
        breakdown_label = Gtk.Label(label="Token Breakdown", xalign=0)
        breakdown_label.add_css_class("heading")
        breakdown_label.set_margin_top(4)
        content.append(breakdown_label)

        self._breakdown_bar = TokenBreakdownBar()
        content.append(self._breakdown_bar)

        # Legend
        legend_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        legend_box.set_margin_top(4)
        for name, color in _COLORS.items():
            dot = Gtk.DrawingArea()
            dot.set_content_width(10)
            dot.set_content_height(10)
            dot.set_valign(Gtk.Align.CENTER)
            c = color

            def _draw_dot(
                _a: Gtk.DrawingArea,
                cr: cairo.Context,
                w: int,
                h: int,
                _c: tuple = c,
            ) -> None:
                cr.set_source_rgb(*_c)
                cr.arc(w / 2, h / 2, min(w, h) / 2, 0, 2 * math.pi)
                cr.fill()

            dot.set_draw_func(_draw_dot)
            legend_box.append(dot)

            pretty = name.replace("_", " ").title()
            lbl = Gtk.Label(label=pretty)
            lbl.add_css_class("caption")
            lbl.add_css_class("dim-label")
            legend_box.append(lbl)

        content.append(legend_box)

        # ------ Today section ------
        today_label = Gtk.Label(label="Today", xalign=0)
        today_label.add_css_class("heading")
        today_label.set_margin_top(4)
        content.append(today_label)

        today_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self._today_tokens_label = Gtk.Label(label="0 tokens", xalign=0)
        today_row.append(self._today_tokens_label)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        today_row.append(spacer)
        self._today_msgs_label = Gtk.Label(label="0 messages", xalign=1)
        self._today_msgs_label.add_css_class("dim-label")
        today_row.append(self._today_msgs_label)
        content.append(today_row)

        # ------ Last hour chart ------
        hour_label = Gtk.Label(label="Last Hour", xalign=0)
        hour_label.add_css_class("heading")
        hour_label.set_margin_top(4)
        content.append(hour_label)

        self._hour_chart = BarChart(bar_count=60, chart_height=60)
        content.append(self._hour_chart)

        # ------ 14-day trend ------
        trend_label = Gtk.Label(label="14-Day Trend", xalign=0)
        trend_label.add_css_class("heading")
        trend_label.set_margin_top(4)
        content.append(trend_label)

        self._daily_chart = BarChart(bar_count=14, chart_height=60)
        content.append(self._daily_chart)

        # ------ Models section ------
        models_label = Gtk.Label(label="Models", xalign=0)
        models_label.add_css_class("heading")
        models_label.set_margin_top(4)
        content.append(models_label)

        self._models_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        content.append(self._models_box)

        # ------ Footer ------
        footer_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        footer_box.set_margin_top(4)

        refresh_btn = Gtk.Button(label="Scan Logs")
        refresh_btn.add_css_class("flat")
        refresh_btn.connect("clicked", self._on_refresh_clicked)
        footer_box.append(refresh_btn)

        spacer2 = Gtk.Box()
        spacer2.set_hexpand(True)
        footer_box.append(spacer2)

        self._scanned_label = Gtk.Label(label="")
        self._scanned_label.add_css_class("dim-label")
        self._scanned_label.add_css_class("caption")
        footer_box.append(self._scanned_label)

        content.append(footer_box)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, stats: AggregatedStats) -> None:
        self._last_scanned = datetime.now(timezone.utc)

        # Stat cards
        self._card_tokens._val_label.set_text(  # type: ignore[attr-defined]
            TokenFormatter.format(stats.total_usage.total)
        )
        self._card_sessions._val_label.set_text(  # type: ignore[attr-defined]
            str(stats.session_count)
        )
        self._card_messages._val_label.set_text(  # type: ignore[attr-defined]
            str(stats.total_messages)
        )
        self._card_cost._val_label.set_text(  # type: ignore[attr-defined]
            TokenFormatter.format_cost(stats.estimated_cost)
        )

        # Breakdown bar
        self._breakdown_bar.set_usage(stats.total_usage)

        # Today
        self._today_tokens_label.set_text(
            f"{TokenFormatter.format(stats.today_usage.total)} tokens"
        )
        self._today_msgs_label.set_text(f"{stats.today_messages} messages")

        # Last hour chart
        if stats.last_hour_minutes:
            values = [float(m.tokens) for m in stats.last_hour_minutes]
            labels = [m.minute.strftime("%M") for m in stats.last_hour_minutes]
            self._hour_chart.set_data(values, labels)

        # 14-day chart
        if stats.daily_breakdown:
            values = [float(d.usage.total) for d in stats.daily_breakdown]
            labels = [d.display_date.strftime("%d") for d in stats.daily_breakdown]
            self._daily_chart.set_data(values, labels)

        # Model breakdown
        self._rebuild_model_rows(stats)

        # Scanned label
        self._scanned_label.set_text("Scanned just now")

    # ------------------------------------------------------------------
    # Model rows
    # ------------------------------------------------------------------

    def _rebuild_model_rows(self, stats: AggregatedStats) -> None:
        # Remove existing children
        child = self._models_box.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self._models_box.remove(child)
            child = next_child

        if not stats.model_breakdown:
            placeholder = Gtk.Label(label="No model data")
            placeholder.add_css_class("dim-label")
            self._models_box.append(placeholder)
            return

        max_tokens = max(
            (m.usage.total for m in stats.model_breakdown), default=1
        )
        if max_tokens <= 0:
            max_tokens = 1

        for ms in stats.model_breakdown:
            row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)

            top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            name_lbl = Gtk.Label(label=ms.model, xalign=0)
            name_lbl.set_ellipsize(3)  # Pango.EllipsizeMode.END
            name_lbl.set_hexpand(True)
            top.append(name_lbl)

            info_lbl = Gtk.Label(
                label=f"{TokenFormatter.format(ms.usage.total)} / {ms.message_count} msgs",
                xalign=1,
            )
            info_lbl.add_css_class("dim-label")
            info_lbl.add_css_class("caption")
            top.append(info_lbl)

            row.append(top)

            # Stacked bar for this model
            model_bar = _ModelStackedBar(ms.usage, max_tokens)
            row.append(model_bar)

            self._models_box.append(row)

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_refresh_clicked(self, _btn: Gtk.Button) -> None:
        self._app.refresh_logs()


# ---------------------------------------------------------------------------
# _ModelStackedBar — small stacked bar per model
# ---------------------------------------------------------------------------

class _ModelStackedBar(Gtk.DrawingArea):
    def __init__(self, usage: TokenUsage, max_total: int) -> None:
        super().__init__()
        self.set_content_height(12)
        self.set_content_width(320)
        self.set_hexpand(True)
        self._usage = usage
        self._max_total = max_total
        self.set_draw_func(self._draw)

    def _draw(
        self,
        _area: Gtk.DrawingArea,
        cr: cairo.Context,
        width: int,
        height: int,
    ) -> None:
        radius = 3.0
        # Background track
        _rounded_rect(cr, 0, 0, width, height, radius)
        cr.set_source_rgb(*_CHART_BG)
        cr.fill()

        if self._usage.total <= 0 or self._max_total <= 0:
            return

        filled_w = (self._usage.total / self._max_total) * width
        segments = [
            (self._usage.cache_read, _COLORS["cache_read"]),
            (self._usage.cache_write, _COLORS["cache_write"]),
            (self._usage.input, _COLORS["input"]),
            (self._usage.output, _COLORS["output"]),
        ]

        cr.save()
        _rounded_rect(cr, 0, 0, width, height, radius)
        cr.clip()

        x = 0.0
        total = self._usage.total
        for count, color in segments:
            if count <= 0:
                continue
            seg_w = (count / total) * filled_w
            cr.set_source_rgb(*color)
            cr.rectangle(x, 0, seg_w, height)
            cr.fill()
            x += seg_w

        cr.restore()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _rounded_rect(
    cr: cairo.Context, x: float, y: float, w: float, h: float, r: float
) -> None:
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()
