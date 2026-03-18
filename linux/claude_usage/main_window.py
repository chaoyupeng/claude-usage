"""Main application window with Usage and Tokens tabs."""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from .log_models import AggregatedStats
from .models import UsageResponse

if TYPE_CHECKING:
    from .app import Application


class MainWindow(Gtk.ApplicationWindow):
    """The primary window containing the Usage and Tokens tabs."""

    def __init__(
        self,
        application: Gtk.Application,
        app_controller: "Application",
    ) -> None:
        super().__init__(
            application=application,
            title="Claude Usage",
            default_width=360,
            default_height=520,
            resizable=False,
        )
        self._app = app_controller

        # Import tab modules
        from .usage_tab import UsageTab
        from .token_dashboard import TokenDashboard

        # ------ Header bar ------
        self._header = Adw.HeaderBar()
        self._title_widget = Adw.WindowTitle(
            title="Claude Usage",
            subtitle="",
        )
        self._header.set_title_widget(self._title_widget)

        # ------ Notebook (tabs) ------
        self._notebook = Gtk.Notebook()
        self._notebook.set_vexpand(True)
        self._notebook.set_hexpand(True)

        # Usage tab
        self._usage_tab = UsageTab(app_controller=app_controller)
        self._notebook.append_page(
            self._usage_tab,
            Gtk.Label(label="Usage"),
        )

        # Tokens tab
        self._token_dashboard = TokenDashboard(app_controller=app_controller)
        self._notebook.append_page(
            self._token_dashboard,
            Gtk.Label(label="Tokens"),
        )

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
        main_box.append(self._notebook)
        main_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        main_box.append(footer)

        self.set_child(main_box)

        # Close hides instead of destroying
        self.connect("close-request", self._on_close_request)

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

    def show_code_entry(self) -> None:
        """Show the OAuth code entry UI in the usage tab."""
        self._usage_tab.show_code_entry()
        self.show_window()

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_close_request(self, _window: Gtk.Window) -> bool:
        self.hide_window()
        return True  # prevent destruction

    def _on_settings_clicked(self, _btn: Gtk.Button) -> None:
        from .settings_dialog import SettingsDialog

        dialog = SettingsDialog(app_controller=self._app, transient_for=self)
        dialog.present()

    def _on_refresh_clicked(self, _btn: Gtk.Button) -> None:
        self._app.refresh_usage()
        self._app.refresh_logs()

    def _on_quit_clicked(self, _btn: Gtk.Button) -> None:
        self._app.on_quit()
