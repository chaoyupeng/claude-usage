"""System tray icon using AyatanaAppIndicator3 with dynamic Cairo rendering.

Key constraints on GNOME Shell:
- AppIndicator menus are serialized over DBus (dbusmenu protocol) which only
  supports text labels, icons, checkmarks — NOT custom GTK3 widgets like
  ProgressBar.  So menu items use plain text labels for usage percentages.
- Icons must use set_icon_full() with the FULL absolute path including .png
  extension, as GNOME Shell's AppIndicator extension doesn't reliably use
  set_icon_theme_path().
- The menu `show` signal fires when the user clicks the tray icon, which we
  use to simultaneously present the main application window (dropdown behavior).
"""

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
from gi.repository import GLib, Gtk as Gtk3


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ICON_W = 160
_ICON_H = 48
_INDICATOR_ID = "claude-usage-bar"


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------

def _color_for_pct(pct: float) -> tuple:
    if pct < 0.60:
        return (0.298, 0.686, 0.314)   # green
    elif pct < 0.80:
        return (1.0, 0.757, 0.027)     # yellow
    else:
        return (0.957, 0.263, 0.212)    # red


# ---------------------------------------------------------------------------
# TrayIcon
# ---------------------------------------------------------------------------

class TrayIcon:
    """System tray icon with usage info in the menu."""

    def __init__(
        self,
        on_open: Optional[Callable[[], None]] = None,
        on_refresh: Optional[Callable[[], None]] = None,
        on_quit: Optional[Callable[[], None]] = None,
    ) -> None:
        self._on_open = on_open
        self._on_refresh = on_refresh
        self._on_quit = on_quit

        # Two alternating temp icon files to force AppIndicator refresh
        self._tmp_dir = tempfile.mkdtemp(prefix="claude-usage-icon-")
        self._icon_paths = [
            os.path.join(self._tmp_dir, "icon_a.png"),
            os.path.join(self._tmp_dir, "icon_b.png"),
        ]
        self._icon_index = 0

        # Menu item references
        self._item_5h: Optional[Gtk3.MenuItem] = None
        self._item_7d: Optional[Gtk3.MenuItem] = None
        self._sign_in_item: Optional[Gtk3.MenuItem] = None

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
        # Render initial icon and pass FULL path with .png extension
        initial_icon = self._render_to_file(0.0, 0.0)

        self._indicator = AppIndicator3.Indicator.new(
            _INDICATOR_ID,
            initial_icon,  # absolute path to .png file
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self._indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)

        # Build menu — text labels only (custom widgets don't work over dbusmenu)
        menu = Gtk3.Menu()

        # When menu appears, also show the main window (dropdown behavior)
        menu.connect("show", self._on_menu_show)

        # Usage text items (clicking opens the dashboard)
        self._item_5h = Gtk3.MenuItem(label="5-hour:  --%")
        self._item_5h.connect("activate", self._on_menu_open)
        menu.append(self._item_5h)

        self._item_7d = Gtk3.MenuItem(label="7-day:   --%")
        self._item_7d.connect("activate", self._on_menu_open)
        menu.append(self._item_7d)

        menu.append(Gtk3.SeparatorMenuItem())

        # Sign-in prompt (hidden when authenticated)
        self._sign_in_item = Gtk3.MenuItem(label="Sign in to view usage")
        self._sign_in_item.connect("activate", self._on_menu_open)
        self._sign_in_item.set_visible(False)
        self._sign_in_item.set_no_show_all(True)
        menu.append(self._sign_in_item)

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
    # Icon + menu updates
    # ------------------------------------------------------------------

    def update_icon(self, pct_5h: float, pct_7d: float) -> None:
        """Update tray icon, panel label, and menu text with usage percentages (0..1)."""
        icon_path = self._render_to_file(pct_5h, pct_7d)
        if self._indicator is not None:
            self._indicator.set_icon_full(icon_path, "Claude Usage")
            self._indicator.set_label("", "")

        # Update menu item labels (plain text — works over dbusmenu)
        if self._item_5h:
            self._item_5h.set_label(f"5-hour:  {pct_5h * 100:.0f}%")
            self._item_5h.show()
        if self._item_7d:
            self._item_7d.set_label(f"7-day:   {pct_7d * 100:.0f}%")
            self._item_7d.show()
        if self._sign_in_item:
            self._sign_in_item.hide()

    def set_unauthenticated(self) -> None:
        """Show dashed icon and sign-in prompt in menu."""
        icon_path = self._render_to_file(0.0, 0.0, dashed=True)
        if self._indicator is not None:
            self._indicator.set_icon_full(icon_path, "Claude Usage (not signed in)")
            self._indicator.set_label("", "")

        if self._item_5h:
            self._item_5h.hide()
        if self._item_7d:
            self._item_7d.hide()
        if self._sign_in_item:
            self._sign_in_item.show()

    # ------------------------------------------------------------------
    # Icon rendering
    # ------------------------------------------------------------------

    def _render_to_file(
        self, pct_5h: float, pct_7d: float, dashed: bool = False
    ) -> str:
        """Render icon to a temp PNG and return the FULL absolute path."""
        surface = self.render_icon(pct_5h, pct_7d, dashed=dashed)
        idx = self._icon_index
        self._icon_index = 1 - idx
        png_path = self._icon_paths[idx]
        surface.write_to_png(png_path)
        return png_path

    @staticmethod
    def render_icon(
        pct_5h: float,
        pct_7d: float,
        dashed: bool = False,
        logo_surface: Optional[cairo.ImageSurface] = None,
    ) -> cairo.ImageSurface:
        """Draw a wide icon with two rows: label + bar + percentage.

        Layout (160x48):
          5h [████████████░░░░░] 28%
          7d [██████████████░░░] 11%
        """
        w, h = _ICON_W, _ICON_H
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surface)

        pad = 2
        label_w = 20       # width for "5h"/"7d" label
        pct_w = 36          # width for "28%" text
        bar_x = pad + label_w + 4
        bar_w = w - bar_x - pct_w - 4
        bar_h = 14
        gap = 6
        row_h = bar_h
        y_start = (h - row_h * 2 - gap) / 2
        radius = 4
        font_size = 13

        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(font_size)

        rows = [
            (pct_5h, "5h"),
            (pct_7d, "7d"),
        ]

        for i, (pct, label) in enumerate(rows):
            pct = max(0.0, min(1.0, pct))
            y = y_start + i * (row_h + gap)

            # Label ("5h" / "7d")
            cr.set_source_rgba(0.85, 0.85, 0.85, 1.0)
            ext = cr.text_extents(label)
            cr.move_to(pad + label_w - ext.width, y + row_h / 2 + ext.height / 2)
            cr.show_text(label)

            # Bar background
            bx = bar_x
            _rounded_rect(cr, bx, y, bar_w, bar_h, radius)
            cr.set_source_rgba(0.6, 0.6, 0.6, 0.30)
            cr.fill()

            if dashed:
                cr.set_source_rgba(0.6, 0.6, 0.6, 0.5)
                cr.set_dash([4, 4])
                cr.set_line_width(2)
                mid_y = y + bar_h / 2
                cr.move_to(bx + radius, mid_y)
                cr.line_to(bx + bar_w - radius, mid_y)
                cr.stroke()
                cr.set_dash([])
            elif pct > 0.0:
                fill_w = bar_w * pct
                color = _color_for_pct(pct)
                cr.save()
                _rounded_rect(cr, bx, y, bar_w, bar_h, radius)
                cr.clip()
                cr.set_source_rgb(*color)
                cr.rectangle(bx, y, fill_w, bar_h)
                cr.fill()
                cr.restore()

            # Percentage text
            pct_text = f"{pct * 100:.0f}%" if not dashed else "--%"
            cr.set_source_rgba(0.85, 0.85, 0.85, 1.0)
            ext = cr.text_extents(pct_text)
            tx = w - pad - pct_w / 2 - ext.width / 2
            cr.move_to(tx, y + row_h / 2 + ext.height / 2)
            cr.show_text(pct_text)

        surface.flush()
        return surface

    # ------------------------------------------------------------------
    # Menu callbacks
    # ------------------------------------------------------------------

    def _on_menu_show(self, _menu: Gtk3.Menu) -> None:
        """Fired when the tray menu opens — also show the main window."""
        if self._on_open is not None:
            self._on_open()

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
# Helper
# ---------------------------------------------------------------------------

def _rounded_rect(
    cr: cairo.Context, x: float, y: float, w: float, h: float, r: float,
) -> None:
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


# ---------------------------------------------------------------------------
# Standalone subprocess mode
# ---------------------------------------------------------------------------

def _run_subprocess() -> None:
    import json
    import sys
    import threading

    def send_event(event_type: str) -> None:
        sys.stdout.write(json.dumps({"type": event_type}) + "\n")
        sys.stdout.flush()

    tray = TrayIcon(
        on_open=lambda: send_event("open"),
        on_refresh=lambda: send_event("refresh"),
        on_quit=lambda: send_event("quit"),
    )

    def stdin_reader() -> None:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                cmd = json.loads(line)
                action = cmd.get("type")
                if action == "update_icon":
                    GLib.idle_add(tray.update_icon, cmd["pct_5h"], cmd["pct_7d"])
                elif action == "set_unauthenticated":
                    GLib.idle_add(tray.set_unauthenticated)
                elif action == "quit":
                    GLib.idle_add(Gtk3.main_quit)
                    return
            except (json.JSONDecodeError, KeyError):
                pass
        GLib.idle_add(Gtk3.main_quit)

    thread = threading.Thread(target=stdin_reader, daemon=True)
    thread.start()

    Gtk3.main()


if __name__ == "__main__":
    _run_subprocess()
