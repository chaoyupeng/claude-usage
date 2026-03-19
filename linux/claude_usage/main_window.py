"""Main application window — dropdown-style panel anchored near the system tray."""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from .log_models import AggregatedStats
from .models import UsageResponse

if TYPE_CHECKING:
    from .app import Application

# ---------------------------------------------------------------------------
# CSS theme
# ---------------------------------------------------------------------------

_CSS = """
/* Window chrome */
window {
    border: 1px solid alpha(@borders, 0.6);
}

/* ---- Progress bars: 6px tall, 3px radius ---- */
progressbar trough {
    min-height: 6px;
    border-radius: 3px;
}
progressbar progress {
    min-height: 6px;
    border-radius: 3px;
}

/* Color-coded progress bars */
progressbar.usage-low progress {
    background-color: #4CAF50;
}
progressbar.usage-medium progress {
    background-color: #FFC107;
}
progressbar.usage-high progress {
    background-color: #F44336;
}
progressbar.usage-extra progress {
    background-color: #5B8DEA;
}

/* ---- Thin separators ---- */
separator.thin {
    min-height: 1px;
    margin-top: 2px;
    margin-bottom: 2px;
}

/* ---- Segmented tab control ---- */
.segment-btn {
    padding-left: 20px;
    padding-right: 20px;
    font-size: 13px;
}
"""


class MainWindow(Gtk.ApplicationWindow):
    """Dropdown-style panel containing the Usage and Tokens tabs."""

    def __init__(
        self,
        application: Gtk.Application,
        app_controller: "Application",
    ) -> None:
        super().__init__(
            application=application,
            title="Claude Usage",
            default_width=340,
            default_height=520,
            resizable=False,
            decorated=False,
        )
        self._app = app_controller

        # Window icon
        import os
        icon_path = os.path.join(os.path.dirname(__file__), "resources", "claude-usage.png")
        if os.path.isfile(icon_path):
            from gi.repository import GdkPixbuf
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(icon_path)
            self.set_icon_name("claude-usage")

        # Import tab modules
        from .usage_tab import UsageTab
        from .token_dashboard import TokenDashboard

        # ------ CSS theme ------
        css = Gtk.CssProvider()
        css.load_from_string(_CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

        # ------ Custom header bar (no system buttons) ------
        self._header = Adw.HeaderBar()
        self._header.set_show_start_title_buttons(False)
        self._header.set_show_end_title_buttons(False)

        self._title_widget = Adw.WindowTitle(
            title="Claude Usage",
            subtitle="",
        )
        self._header.set_title_widget(self._title_widget)

        close_btn = Gtk.Button(icon_name="window-close-symbolic")
        close_btn.add_css_class("flat")
        close_btn.set_tooltip_text("Close")
        close_btn.connect("clicked", lambda _: self.hide_window())
        self._header.pack_end(close_btn)

        # ------ Segmented tab control ------
        tab_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        tab_box.set_halign(Gtk.Align.CENTER)
        tab_box.set_margin_top(6)
        tab_box.set_margin_bottom(4)
        tab_box.add_css_class("linked")

        self._usage_btn = Gtk.ToggleButton(label="Usage")
        self._usage_btn.add_css_class("segment-btn")
        self._usage_btn.set_active(True)
        self._usage_btn.connect("toggled", self._on_tab_toggled, "usage")
        tab_box.append(self._usage_btn)

        self._tokens_btn = Gtk.ToggleButton(label="Tokens")
        self._tokens_btn.add_css_class("segment-btn")
        self._tokens_btn.connect("toggled", self._on_tab_toggled, "tokens")
        tab_box.append(self._tokens_btn)

        # ------ Content stack ------
        self._stack = Gtk.Stack()
        self._stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._stack.set_transition_duration(150)
        self._stack.set_vexpand(True)
        self._stack.set_hexpand(True)

        self._usage_tab = UsageTab(app_controller=app_controller)
        self._stack.add_named(self._usage_tab, "usage")

        self._token_dashboard = TokenDashboard(app_controller=app_controller)
        self._stack.add_named(self._token_dashboard, "tokens")

        # ------ Footer bar ------
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        footer.set_margin_start(8)
        footer.set_margin_end(8)
        footer.set_margin_top(4)
        footer.set_margin_bottom(8)

        settings_btn = Gtk.Button(icon_name="emblem-system-symbolic")
        settings_btn.set_tooltip_text("Settings")
        settings_btn.add_css_class("flat")
        settings_btn.connect("clicked", self._on_settings_clicked)
        footer.append(settings_btn)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        footer.append(spacer)

        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Refresh")
        refresh_btn.add_css_class("flat")
        refresh_btn.connect("clicked", self._on_refresh_clicked)
        footer.append(refresh_btn)

        quit_btn = Gtk.Button(icon_name="application-exit-symbolic")
        quit_btn.set_tooltip_text("Quit")
        quit_btn.add_css_class("flat")
        quit_btn.connect("clicked", self._on_quit_clicked)
        footer.append(quit_btn)

        # ------ Main layout ------
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        main_box.append(self._header)
        main_box.append(tab_box)
        main_box.append(self._stack)
        main_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        main_box.append(footer)

        self.set_child(main_box)

        # ------ Dismiss behaviour ------
        self.connect("close-request", self._on_close_request)

        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_ctrl)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_usage(
        self,
        usage_response: Optional[UsageResponse],
        last_error: Optional[str],
    ) -> None:
        svc = self._app.usage_service
        is_auth = svc.is_authenticated if svc else False
        self._usage_tab.update(usage_response, last_error, is_auth)

    def update_tokens(self, stats: AggregatedStats) -> None:
        self._token_dashboard.update(stats)

    def set_account_email(self, email: Optional[str]) -> None:
        self._title_widget.set_subtitle(email or "")

    def show_window(self) -> None:
        self.set_visible(True)
        self.present()

    def hide_window(self) -> None:
        self.set_visible(False)

    def toggle_window(self) -> None:
        if self.get_visible():
            self.hide_window()
        else:
            self.show_window()

    def show_code_entry(self) -> None:
        self._usage_tab.show_code_entry()
        self.show_window()

    def reset_submit_state(self) -> None:
        self._usage_tab.reset_submit_state()

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_close_request(self, _window: Gtk.Window) -> bool:
        self.hide_window()
        return True  # prevent destruction

    def _on_key_pressed(self, _ctrl, keyval, _keycode, _state) -> bool:
        if keyval == Gdk.KEY_Escape:
            self.hide_window()
            return True
        return False

    def _on_tab_toggled(self, btn: Gtk.ToggleButton, tab_name: str) -> None:
        if not btn.get_active():
            return
        if tab_name == "usage":
            self._tokens_btn.set_active(False)
        else:
            self._usage_btn.set_active(False)
        self._stack.set_visible_child_name(tab_name)

    def _on_settings_clicked(self, _btn: Gtk.Button) -> None:
        from .settings_dialog import SettingsDialog

        dialog = SettingsDialog(app_controller=self._app, transient_for=self)
        dialog.present()

    def _on_refresh_clicked(self, _btn: Gtk.Button) -> None:
        self._app.refresh_usage()
        self._app.refresh_logs()

    def _on_quit_clicked(self, _btn: Gtk.Button) -> None:
        self._app.on_quit()
