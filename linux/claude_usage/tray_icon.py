"""System tray icon using AyatanaAppIndicator3 with dynamic Cairo rendering."""

from __future__ import annotations

import math
import os
import tempfile
from typing import Callable, Optional

import gi

gi.require_version("Gtk", "3.0")

try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator3

    _HAS_INDICATOR = True
except (ValueError, ImportError):
    _HAS_INDICATOR = False

import cairo
from gi.repository import Gtk as Gtk3  # GTK3 for AppIndicator menus


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ICON_SIZE = 64
_BAR_WIDTH = 22
_BAR_HEIGHT = 52
_BAR_RADIUS = 4
_BAR_SPACING = 8
_LABEL_FONT_SIZE = 9
_INDICATOR_ID = "claude-usage-bar"


# ---------------------------------------------------------------------------
# TrayIcon
# ---------------------------------------------------------------------------

class TrayIcon:
    """System tray icon with dynamically-rendered usage bars."""

    def __init__(
        self,
        on_open: Optional[Callable[[], None]] = None,
        on_refresh: Optional[Callable[[], None]] = None,
        on_quit: Optional[Callable[[], None]] = None,
    ) -> None:
        self._on_open = on_open
        self._on_refresh = on_refresh
        self._on_quit = on_quit

        # Two alternating temp icon paths to force AppIndicator refresh
        self._tmp_dir = tempfile.mkdtemp(prefix="claude-usage-icon-")
        self._icon_paths = [
            os.path.join(self._tmp_dir, "icon_a"),
            os.path.join(self._tmp_dir, "icon_b"),
        ]
        self._icon_index = 0

        self._indicator: Optional[object] = None

        if _HAS_INDICATOR:
            self._setup_indicator()
        else:
            import sys

            print(
                "[TrayIcon] AyatanaAppIndicator3 not available — running without tray",
                file=sys.stderr,
            )

    # ------------------------------------------------------------------
    # Indicator setup
    # ------------------------------------------------------------------

    def _setup_indicator(self) -> None:
        # Render an initial neutral icon
        initial_path = self._render_to_file(0.0, 0.0)

        self._indicator = AppIndicator3.Indicator.new(
            _INDICATOR_ID,
            initial_path,
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self._indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)

        # Build GTK3 menu
        menu = Gtk3.Menu()

        item_open = Gtk3.MenuItem(label="Open")
        item_open.connect("activate", self._on_menu_open)
        menu.append(item_open)

        item_refresh = Gtk3.MenuItem(label="Refresh")
        item_refresh.connect("activate", self._on_menu_refresh)
        menu.append(item_refresh)

        menu.append(Gtk3.SeparatorMenuItem())

        item_quit = Gtk3.MenuItem(label="Quit")
        item_quit.connect("activate", self._on_menu_quit)
        menu.append(item_quit)

        menu.show_all()
        self._indicator.set_menu(menu)

    # ------------------------------------------------------------------
    # Icon rendering
    # ------------------------------------------------------------------

    def update_icon(self, pct_5h: float, pct_7d: float) -> None:
        """Re-render the tray icon with the given usage percentages (0..1)."""
        icon_path = self._render_to_file(pct_5h, pct_7d)
        if self._indicator is not None:
            self._indicator.set_icon_full(icon_path, "Claude Usage")

    def set_unauthenticated(self) -> None:
        """Render a dashed/empty bars icon for the unauthenticated state."""
        icon_path = self._render_to_file(0.0, 0.0, dashed=True)
        if self._indicator is not None:
            self._indicator.set_icon_full(icon_path, "Claude Usage (not signed in)")

    def _render_to_file(
        self, pct_5h: float, pct_7d: float, dashed: bool = False
    ) -> str:
        """Render a Cairo icon and write it to a temp PNG; return the base path (no extension)."""
        surface = self.render_icon(pct_5h, pct_7d, size=_ICON_SIZE, dashed=dashed)
        # Alternate between two file names so AppIndicator detects a change
        idx = self._icon_index
        self._icon_index = 1 - idx
        base_path = self._icon_paths[idx]
        png_path = base_path + ".png"
        surface.write_to_png(png_path)
        return base_path

    @staticmethod
    def render_icon(
        pct_5h: float,
        pct_7d: float,
        size: int = 64,
        dashed: bool = False,
    ) -> cairo.ImageSurface:
        """Draw two vertical usage bars with labels onto a Cairo ImageSurface."""
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
        cr = cairo.Context(surface)

        # Scale factor
        scale = size / 64.0

        # Bar geometry
        bar_w = _BAR_WIDTH * scale
        bar_h = _BAR_HEIGHT * scale
        radius = _BAR_RADIUS * scale
        spacing = _BAR_SPACING * scale
        total_w = bar_w * 2 + spacing
        x_start = (size - total_w) / 2
        y_top = 2 * scale
        label_y = size - 2 * scale

        bars = [
            (pct_5h, "5h", (0.345, 0.537, 0.918)),   # blue
            (pct_7d, "7d", (0.918, 0.569, 0.247)),   # orange
        ]

        for i, (pct, label, color) in enumerate(bars):
            x = x_start + i * (bar_w + spacing)
            pct = max(0.0, min(1.0, pct))

            # Background bar (rounded rect)
            _rounded_rect(cr, x, y_top, bar_w, bar_h, radius)
            cr.set_source_rgba(0.6, 0.6, 0.6, 0.25)
            cr.fill()

            if dashed:
                # Draw dashed lines inside the bar
                cr.set_source_rgba(0.6, 0.6, 0.6, 0.5)
                cr.set_dash([3 * scale, 3 * scale])
                cr.set_line_width(1.5 * scale)
                mid_x = x + bar_w / 2
                cr.move_to(mid_x, y_top + radius)
                cr.line_to(mid_x, y_top + bar_h - radius)
                cr.stroke()
                cr.set_dash([])
            elif pct > 0.0:
                # Fill bar from bottom
                fill_h = bar_h * pct
                fill_y = y_top + bar_h - fill_h
                cr.save()
                _rounded_rect(cr, x, y_top, bar_w, bar_h, radius)
                cr.clip()
                cr.set_source_rgb(*color)
                cr.rectangle(x, fill_y, bar_w, fill_h)
                cr.fill()
                cr.restore()

            # Label text below bar
            cr.set_source_rgba(0.85, 0.85, 0.85, 1.0)
            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            cr.set_font_size(_LABEL_FONT_SIZE * scale)
            extents = cr.text_extents(label)
            text_x = x + (bar_w - extents.width) / 2
            cr.move_to(text_x, label_y)
            cr.show_text(label)

        surface.flush()
        return surface

    # ------------------------------------------------------------------
    # Menu callbacks
    # ------------------------------------------------------------------

    def _on_menu_open(self, _item: Gtk3.MenuItem) -> None:
        if self._on_open is not None:
            self._on_open()

    def _on_menu_refresh(self, _item: Gtk3.MenuItem) -> None:
        if self._on_refresh is not None:
            self._on_refresh()

    def _on_menu_quit(self, _item: Gtk3.MenuItem) -> None:
        if self._on_quit is not None:
            self._on_quit()


# ---------------------------------------------------------------------------
# Helper: rounded rectangle path
# ---------------------------------------------------------------------------

def _rounded_rect(
    cr: cairo.Context,
    x: float,
    y: float,
    w: float,
    h: float,
    r: float,
) -> None:
    """Add a rounded rectangle sub-path to the Cairo context."""
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()
