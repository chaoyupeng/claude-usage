"""Settings dialog — polling interval, notification thresholds, autostart, account."""

from __future__ import annotations

import json
import os
from typing import Optional, TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

if TYPE_CHECKING:
    from .app import Application


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_SETTINGS_FILE = os.path.join(
    os.path.expanduser("~"), ".config", "claude-usage-bar", "settings.json"
)

_AUTOSTART_DIR = os.path.join(os.path.expanduser("~"), ".config", "autostart")
_AUTOSTART_FILE = os.path.join(_AUTOSTART_DIR, "claude-usage.desktop")

_DESKTOP_ENTRY = """\
[Desktop Entry]
Type=Application
Name=Claude Usage
Exec=python3 -m claude_usage
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
"""


# ---------------------------------------------------------------------------
# Polling interval options
# ---------------------------------------------------------------------------

_POLLING_OPTIONS = [
    (5, "5 minutes"),
    (15, "15 minutes"),
    (30, "30 minutes"),
    (60, "1 hour"),
]


# ---------------------------------------------------------------------------
# SettingsDialog
# ---------------------------------------------------------------------------

class SettingsDialog(Gtk.Window):
    """Modal settings window with polling, notification, autostart, and account sections."""

    def __init__(
        self,
        app_controller: "Application",
        transient_for: Optional[Gtk.Window] = None,
    ) -> None:
        super().__init__(
            title="Settings",
            default_width=340,
            default_height=-1,
            resizable=False,
            modal=True,
        )
        if transient_for is not None:
            self.set_transient_for(transient_for)

        self._app = app_controller

        # Load current settings from disk
        self._settings = self._load_settings()

        # Main layout
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Header bar
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        main_box.append(header)

        # Content with sections
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_start(16)
        content.set_margin_end(16)
        content.set_margin_top(8)
        content.set_margin_bottom(16)

        # ------ Polling interval section ------
        polling_section = self._make_section("Polling Interval")

        polling_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        polling_label = Gtk.Label(label="Check every", xalign=0)
        polling_label.set_hexpand(True)
        polling_row.append(polling_label)

        self._polling_dropdown = Gtk.DropDown.new_from_strings(
            [opt[1] for opt in _POLLING_OPTIONS]
        )
        current_minutes = self._get_polling_minutes()
        for i, (minutes, _) in enumerate(_POLLING_OPTIONS):
            if minutes == current_minutes:
                self._polling_dropdown.set_selected(i)
                break
        self._polling_dropdown.connect("notify::selected", self._on_polling_changed)
        polling_row.append(self._polling_dropdown)

        polling_section.append(polling_row)
        content.append(polling_section)

        # ------ Notification thresholds section ------
        notif_section = self._make_section("Notification Thresholds")

        notif_service = self._app.notification_service

        self._scale_5h = self._make_threshold_row(
            notif_section,
            "5-hour window",
            notif_service.threshold_5h if notif_service else 0,
            self._on_threshold_5h_changed,
        )

        self._scale_7d = self._make_threshold_row(
            notif_section,
            "7-day window",
            notif_service.threshold_7d if notif_service else 0,
            self._on_threshold_7d_changed,
        )

        self._scale_extra = self._make_threshold_row(
            notif_section,
            "Extra usage",
            notif_service.threshold_extra if notif_service else 0,
            self._on_threshold_extra_changed,
        )

        hint_label = Gtk.Label(
            label="Set to 0 to disable. Notifies when usage crosses the threshold.",
            xalign=0,
        )
        hint_label.add_css_class("dim-label")
        hint_label.add_css_class("caption")
        hint_label.set_wrap(True)
        notif_section.append(hint_label)

        content.append(notif_section)

        # ------ Autostart section ------
        autostart_section = self._make_section("Startup")

        autostart_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        autostart_label = Gtk.Label(label="Start on login", xalign=0)
        autostart_label.set_hexpand(True)
        autostart_row.append(autostart_label)

        self._autostart_switch = Gtk.Switch()
        self._autostart_switch.set_active(self._is_autostart_enabled())
        self._autostart_switch.set_valign(Gtk.Align.CENTER)
        self._autostart_switch.connect("notify::active", self._on_autostart_toggled)
        autostart_row.append(self._autostart_switch)

        autostart_section.append(autostart_row)
        content.append(autostart_section)

        # ------ Account section ------
        account_section = self._make_section("Account")

        svc = self._app.usage_service
        if svc is not None and svc.is_authenticated:
            email_label = Gtk.Label(
                label=svc.account_email or "Signed in",
                xalign=0,
            )
            email_label.set_hexpand(True)
            email_label.set_ellipsize(3)  # Pango.EllipsizeMode.END
            account_section.append(email_label)

            sign_out_btn = Gtk.Button(label="Sign Out")
            sign_out_btn.add_css_class("destructive-action")
            sign_out_btn.set_halign(Gtk.Align.START)
            sign_out_btn.connect("clicked", self._on_sign_out_clicked)
            account_section.append(sign_out_btn)
        else:
            not_signed_in = Gtk.Label(label="Not signed in", xalign=0)
            not_signed_in.add_css_class("dim-label")
            account_section.append(not_signed_in)

        content.append(account_section)

        main_box.append(content)
        self.set_child(main_box)

    # ------------------------------------------------------------------
    # Section builder
    # ------------------------------------------------------------------

    @staticmethod
    def _make_section(title: str) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        lbl = Gtk.Label(label=title, xalign=0)
        lbl.add_css_class("heading")
        box.append(lbl)
        return box

    # ------------------------------------------------------------------
    # Threshold row builder
    # ------------------------------------------------------------------

    @staticmethod
    def _make_threshold_row(
        parent: Gtk.Box,
        label_text: str,
        initial_value: int,
        on_changed_cb,
    ) -> Gtk.Scale:
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        lbl = Gtk.Label(label=label_text, xalign=0)
        lbl.set_hexpand(True)
        top.append(lbl)

        val_label = Gtk.Label(label=f"{initial_value}%" if initial_value > 0 else "Off", xalign=1)
        val_label.add_css_class("numeric")
        val_label.set_size_request(40, -1)
        top.append(val_label)

        row.append(top)

        scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 100, 5
        )
        scale.set_value(initial_value)
        scale.set_draw_value(False)
        scale.set_hexpand(True)

        def _on_value_changed(s: Gtk.Scale) -> None:
            v = int(s.get_value())
            val_label.set_text(f"{v}%" if v > 0 else "Off")
            on_changed_cb(v)

        scale.connect("value-changed", _on_value_changed)
        row.append(scale)

        parent.append(row)
        return scale

    # ------------------------------------------------------------------
    # Settings persistence
    # ------------------------------------------------------------------

    @staticmethod
    def _load_settings() -> dict:
        try:
            with open(_SETTINGS_FILE, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _save_settings(self) -> None:
        os.makedirs(os.path.dirname(_SETTINGS_FILE), mode=0o700, exist_ok=True)
        try:
            tmp = _SETTINGS_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self._settings, f, indent=2)
            os.replace(tmp, _SETTINGS_FILE)
        except OSError:
            pass

    def _get_polling_minutes(self) -> int:
        svc = self._app.usage_service
        if svc is not None:
            return svc.polling_minutes
        return self._settings.get("pollingMinutes", 30)

    # ------------------------------------------------------------------
    # Autostart management
    # ------------------------------------------------------------------

    @staticmethod
    def _is_autostart_enabled() -> bool:
        return os.path.isfile(_AUTOSTART_FILE)

    @staticmethod
    def _enable_autostart() -> None:
        os.makedirs(_AUTOSTART_DIR, mode=0o755, exist_ok=True)
        with open(_AUTOSTART_FILE, "w") as f:
            f.write(_DESKTOP_ENTRY)

    @staticmethod
    def _disable_autostart() -> None:
        try:
            os.remove(_AUTOSTART_FILE)
        except FileNotFoundError:
            pass

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_polling_changed(self, dropdown: Gtk.DropDown, _param) -> None:
        idx = dropdown.get_selected()
        if 0 <= idx < len(_POLLING_OPTIONS):
            minutes = _POLLING_OPTIONS[idx][0]
            self._settings["pollingMinutes"] = minutes
            self._save_settings()
            svc = self._app.usage_service
            if svc is not None:
                svc.update_polling_interval(minutes)
                self._app.restart_polling()

    def _on_threshold_5h_changed(self, value: int) -> None:
        ns = self._app.notification_service
        if ns is not None:
            ns.set_threshold_5h(value)

    def _on_threshold_7d_changed(self, value: int) -> None:
        ns = self._app.notification_service
        if ns is not None:
            ns.set_threshold_7d(value)

    def _on_threshold_extra_changed(self, value: int) -> None:
        ns = self._app.notification_service
        if ns is not None:
            ns.set_threshold_extra(value)

    def _on_autostart_toggled(self, switch: Gtk.Switch, _param) -> None:
        if switch.get_active():
            self._enable_autostart()
        else:
            self._disable_autostart()

    def _on_sign_out_clicked(self, _btn: Gtk.Button) -> None:
        self._app.sign_out()
        self.close()
