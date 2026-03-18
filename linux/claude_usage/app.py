"""GTK4 Application class — main entry point and service wiring."""

from __future__ import annotations

import sys
import threading
from typing import Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .credentials import CredentialsStore
from .history_service import UsageHistoryService
from .log_models import AggregatedStats
from .log_service import ClaudeLogParser
from .models import UsageResponse
from .notification_service import NotificationService
from .usage_service import UsageService


class Application(Gtk.Application):
    """Claude Usage system-tray application."""

    def __init__(self) -> None:
        super().__init__(application_id="com.local.claude-usage")

        # Services — created during activate
        self.usage_service: Optional[UsageService] = None
        self.history_service: Optional[UsageHistoryService] = None
        self.log_parser: Optional[ClaudeLogParser] = None
        self.notification_service: Optional[NotificationService] = None

        # UI components
        self._window: Optional["MainWindow"] = None  # noqa: F821
        self._tray: Optional["TrayIcon"] = None  # noqa: F821

        # Polling handle
        self._poll_source_id: Optional[int] = None

        # Latest token stats
        self._token_stats: Optional[AggregatedStats] = None

    # ------------------------------------------------------------------
    # Activate
    # ------------------------------------------------------------------

    def do_activate(self) -> None:
        # Ensure libadwaita styling is initialised
        Adw.init()

        # Create services
        creds_store = CredentialsStore()
        self.usage_service = UsageService(credentials_store=creds_store)
        self.history_service = UsageHistoryService()
        self.notification_service = NotificationService()
        self.log_parser = ClaudeLogParser()

        # Wire services together
        self.usage_service.history_service = self.history_service
        self.usage_service.notification_service = self.notification_service

        # Load persisted data
        self.history_service.load_history()

        # Create tray icon (import here to avoid early gi.require_version conflicts)
        from .tray_icon import TrayIcon

        self._tray = TrayIcon(
            on_open=self._on_tray_open,
            on_refresh=self._on_tray_refresh,
            on_quit=self._on_tray_quit,
        )

        # Create main window
        from .main_window import MainWindow

        self._window = MainWindow(application=self, app_controller=self)
        self._window.set_visible(False)

        # Initial data load
        if self.usage_service.is_authenticated:
            self._fetch_profile_async()
            self.refresh_usage()

        self.refresh_logs()

        # Start polling
        self._start_polling()

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    def _start_polling(self) -> None:
        if self._poll_source_id is not None:
            GLib.source_remove(self._poll_source_id)
        interval_ms = int(self.usage_service.polling_minutes * 60 * 1000)
        self._poll_source_id = GLib.timeout_add(interval_ms, self._on_poll_tick)

    def _on_poll_tick(self) -> bool:
        """Called by GLib.timeout — returns True to keep ticking."""
        self.refresh_usage()
        self.refresh_logs()
        return True  # keep running

    def restart_polling(self) -> None:
        """Re-register the timer after a polling interval change."""
        self._start_polling()

    # ------------------------------------------------------------------
    # Refresh usage (background thread)
    # ------------------------------------------------------------------

    def refresh_usage(self) -> None:
        if self.usage_service is None:
            return
        if not self.usage_service.is_authenticated:
            self._update_ui_unauthenticated()
            return

        def _worker() -> None:
            self.usage_service.fetch_usage()
            GLib.idle_add(self._on_usage_fetched)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_usage_fetched(self) -> bool:
        """Runs on main thread via GLib.idle_add."""
        svc = self.usage_service
        if svc is None:
            return False

        # Update tray icon
        if self._tray is not None:
            if svc.is_authenticated and svc.usage is not None:
                self._tray.update_icon(svc.pct_5h, svc.pct_7d)
            else:
                self._tray.set_unauthenticated()

        # Update window
        if self._window is not None:
            self._window.update_usage(svc.usage, svc.last_error)

        return False  # remove idle callback

    def _update_ui_unauthenticated(self) -> None:
        if self._tray is not None:
            self._tray.set_unauthenticated()
        if self._window is not None:
            self._window.update_usage(None, self.usage_service.last_error if self.usage_service else None)

    # ------------------------------------------------------------------
    # Refresh logs (background thread)
    # ------------------------------------------------------------------

    def refresh_logs(self) -> None:
        if self.log_parser is None:
            return

        def _worker() -> None:
            stats = self.log_parser.scan_and_aggregate()
            GLib.idle_add(self._on_logs_scanned, stats)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_logs_scanned(self, stats: AggregatedStats) -> bool:
        self._token_stats = stats
        if self._window is not None:
            self._window.update_tokens(stats)
        return False

    # ------------------------------------------------------------------
    # Profile fetch
    # ------------------------------------------------------------------

    def _fetch_profile_async(self) -> None:
        def _worker() -> None:
            self.usage_service.fetch_profile()
            GLib.idle_add(self._on_profile_fetched)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_profile_fetched(self) -> bool:
        if self._window is not None and self.usage_service is not None:
            self._window.set_account_email(self.usage_service.account_email)
        return False

    # ------------------------------------------------------------------
    # OAuth helpers (called from UI)
    # ------------------------------------------------------------------

    def start_sign_in(self) -> None:
        if self.usage_service is not None:
            self.usage_service.start_oauth_flow()
            if self._window is not None:
                self._window.show_code_entry()

    def submit_code(self, code: str) -> None:
        if self.usage_service is None:
            return

        def _worker() -> None:
            self.usage_service.submit_oauth_code(code)
            GLib.idle_add(self._on_code_submitted)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_code_submitted(self) -> bool:
        svc = self.usage_service
        if svc is None:
            return False
        if svc.is_authenticated:
            self.refresh_usage()
            self._fetch_profile_async()
        if self._window is not None:
            self._window.update_usage(svc.usage, svc.last_error)
        return False

    def sign_out(self) -> None:
        if self.usage_service is not None:
            self.usage_service.sign_out()
        self._update_ui_unauthenticated()
        if self._window is not None:
            self._window.set_account_email(None)

    # ------------------------------------------------------------------
    # Tray callbacks
    # ------------------------------------------------------------------

    def _on_tray_open(self) -> None:
        if self._window is not None:
            self._window.show_window()

    def _on_tray_refresh(self) -> None:
        self.refresh_usage()
        self.refresh_logs()

    def _on_tray_quit(self) -> None:
        self.on_quit()

    # ------------------------------------------------------------------
    # Quit
    # ------------------------------------------------------------------

    def on_quit(self) -> None:
        if self.history_service is not None:
            self.history_service.flush_to_disk()
        self.quit()

    # ------------------------------------------------------------------
    # Run override
    # ------------------------------------------------------------------

    def run(self, argv: Optional[list] = None) -> int:  # type: ignore[override]
        return super().run(argv or sys.argv)
