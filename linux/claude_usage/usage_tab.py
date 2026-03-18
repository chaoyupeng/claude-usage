"""Usage tab — shows rate-limit buckets, per-model breakdown, and usage history chart."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk, Pango  # noqa: E402

from .models import ExtraUsage, UsageBucket, UsageResponse

if TYPE_CHECKING:
    from .app import Application


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_time_remaining(resets_at: Optional[str]) -> str:
    """Return a human-readable string like 'Resets in 2h 14m'."""
    if not resets_at:
        return ""
    normalised = resets_at.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalised)
    except (ValueError, TypeError):
        return ""
    now = datetime.now(timezone.utc)
    delta = dt - now
    total_seconds = max(int(delta.total_seconds()), 0)
    if total_seconds <= 0:
        return "Resetting..."
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    if hours > 0:
        return f"Resets in {hours}h {minutes}m"
    return f"Resets in {minutes}m"


def _pct_text(utilization: Optional[float]) -> str:
    if utilization is None:
        return "-%"
    return f"{utilization:.0f}%"


def _time_ago_text(dt: Optional[datetime]) -> str:
    if dt is None:
        return ""
    now = datetime.now(timezone.utc)
    secs = int((now - dt).total_seconds())
    if secs < 60:
        return "Updated just now"
    minutes = secs // 60
    if minutes < 60:
        return f"Updated {minutes}m ago"
    hours = minutes // 60
    return f"Updated {hours}h {minutes % 60}m ago"


# ---------------------------------------------------------------------------
# UsageBucketRow — reusable widget for a single usage bucket
# ---------------------------------------------------------------------------

class UsageBucketRow(Gtk.Box):
    """A labelled progress bar for a usage bucket (5-hour or 7-day)."""

    def __init__(self, label_text: str, bar_css_class: str = "") -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.set_margin_start(12)
        self.set_margin_end(12)
        self.set_margin_top(4)
        self.set_margin_bottom(4)

        # Top row: label and percentage
        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self._label = Gtk.Label(label=label_text, xalign=0)
        self._label.add_css_class("heading")
        top_row.append(self._label)

        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        top_row.append(spacer)

        self._pct_label = Gtk.Label(label="-%", xalign=1)
        self._pct_label.add_css_class("numeric")
        top_row.append(self._pct_label)

        self.append(top_row)

        # Progress bar
        self._bar = Gtk.ProgressBar()
        self._bar.set_hexpand(True)
        if bar_css_class:
            self._bar.add_css_class(bar_css_class)
        self.append(self._bar)

        # Reset timer text
        self._reset_label = Gtk.Label(label="", xalign=0)
        self._reset_label.add_css_class("dim-label")
        self._reset_label.add_css_class("caption")
        self.append(self._reset_label)

    def update(self, bucket: Optional[UsageBucket]) -> None:
        if bucket is None:
            self._pct_label.set_text("-%")
            self._bar.set_fraction(0.0)
            self._reset_label.set_text("")
            return
        utilization = bucket.utilization or 0.0
        self._pct_label.set_text(_pct_text(utilization))
        self._bar.set_fraction(max(0.0, min(1.0, utilization / 100.0)))
        self._reset_label.set_text(_format_time_remaining(bucket.resets_at))


# ---------------------------------------------------------------------------
# UsageTab
# ---------------------------------------------------------------------------

class UsageTab(Gtk.Box):
    """Content for the 'Usage' tab — sign-in, buckets, chart."""

    def __init__(self, app_controller: "Application") -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._app = app_controller

        # Scrolled wrapper
        self._scroll = Gtk.ScrolledWindow()
        self._scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._scroll.set_vexpand(True)

        self._content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._content_box.set_margin_top(8)
        self._content_box.set_margin_bottom(8)
        self._scroll.set_child(self._content_box)
        self.append(self._scroll)

        # ------ Sign-in widgets (hidden when authenticated) ------
        self._sign_in_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._sign_in_box.set_margin_start(24)
        self._sign_in_box.set_margin_end(24)
        self._sign_in_box.set_margin_top(48)
        self._sign_in_box.set_valign(Gtk.Align.CENTER)
        self._sign_in_box.set_vexpand(True)

        sign_in_label = Gtk.Label(label="Sign in to view your Claude usage")
        sign_in_label.add_css_class("title-3")
        self._sign_in_box.append(sign_in_label)

        sign_in_btn = Gtk.Button(label="Sign in with Claude")
        sign_in_btn.add_css_class("suggested-action")
        sign_in_btn.add_css_class("pill")
        sign_in_btn.set_halign(Gtk.Align.CENTER)
        sign_in_btn.connect("clicked", self._on_sign_in_clicked)
        self._sign_in_box.append(sign_in_btn)

        # Code entry (shown after OAuth flow starts)
        self._code_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._code_box.set_visible(False)

        code_label = Gtk.Label(label="Paste the authorization code:")
        code_label.add_css_class("dim-label")
        self._code_box.append(code_label)

        code_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._code_entry = Gtk.Entry()
        self._code_entry.set_placeholder_text("code#state")
        self._code_entry.set_hexpand(True)
        self._code_entry.connect("activate", self._on_code_submit)
        code_row.append(self._code_entry)

        submit_btn = Gtk.Button(label="Submit")
        submit_btn.add_css_class("suggested-action")
        submit_btn.connect("clicked", self._on_code_submit)
        code_row.append(submit_btn)

        self._code_box.append(code_row)
        self._sign_in_box.append(self._code_box)
        self._content_box.append(self._sign_in_box)

        # ------ Authenticated content (hidden when not signed in) ------
        self._auth_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._auth_box.set_visible(False)

        # Error banner
        self._error_bar = Gtk.InfoBar()
        self._error_bar.set_message_type(Gtk.MessageType.ERROR)
        self._error_bar.set_revealed(False)
        self._error_bar.set_show_close_button(True)
        self._error_bar.connect("response", lambda _bar, _resp: _bar.set_revealed(False))
        self._error_label = Gtk.Label(label="")
        self._error_label.set_wrap(True)
        self._error_bar.add_child(self._error_label)
        self._auth_box.append(self._error_bar)

        # 5-hour bucket
        self._bucket_5h = UsageBucketRow("5-hour window")
        self._auth_box.append(self._bucket_5h)

        # 7-day bucket
        self._bucket_7d = UsageBucketRow("7-day window")
        self._auth_box.append(self._bucket_7d)

        # Per-model section
        self._model_frame = Gtk.Frame()
        self._model_frame.set_margin_start(12)
        self._model_frame.set_margin_end(12)
        self._model_frame.set_margin_top(4)
        self._model_frame.set_visible(False)

        model_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        model_inner.set_margin_start(8)
        model_inner.set_margin_end(8)
        model_inner.set_margin_top(8)
        model_inner.set_margin_bottom(8)

        model_header = Gtk.Label(label="Per-model (7-day)", xalign=0)
        model_header.add_css_class("caption-heading")
        model_inner.append(model_header)

        self._opus_row = self._make_model_row("Opus")
        model_inner.append(self._opus_row)
        self._sonnet_row = self._make_model_row("Sonnet")
        model_inner.append(self._sonnet_row)

        self._model_frame.set_child(model_inner)
        self._auth_box.append(self._model_frame)

        # Extra usage section
        self._extra_frame = Gtk.Frame()
        self._extra_frame.set_margin_start(12)
        self._extra_frame.set_margin_end(12)
        self._extra_frame.set_margin_top(4)
        self._extra_frame.set_visible(False)

        extra_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        extra_inner.set_margin_start(8)
        extra_inner.set_margin_end(8)
        extra_inner.set_margin_top(8)
        extra_inner.set_margin_bottom(8)

        extra_header_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        extra_title = Gtk.Label(label="Extra usage", xalign=0)
        extra_title.add_css_class("heading")
        extra_header_row.append(extra_title)

        extra_spacer = Gtk.Box()
        extra_spacer.set_hexpand(True)
        extra_header_row.append(extra_spacer)

        self._extra_amount_label = Gtk.Label(label="", xalign=1)
        self._extra_amount_label.add_css_class("numeric")
        extra_header_row.append(self._extra_amount_label)

        extra_inner.append(extra_header_row)

        self._extra_bar = Gtk.ProgressBar()
        self._extra_bar.set_hexpand(True)
        extra_inner.append(self._extra_bar)

        self._extra_frame.set_child(extra_inner)
        self._auth_box.append(self._extra_frame)

        # Usage history chart
        from .usage_chart import UsageChart

        self._chart = UsageChart()
        self._chart.set_margin_start(12)
        self._chart.set_margin_end(12)
        self._chart.set_margin_top(8)
        self._auth_box.append(self._chart)

        # "Updated X ago" label
        self._updated_label = Gtk.Label(label="", xalign=0.5)
        self._updated_label.add_css_class("dim-label")
        self._updated_label.add_css_class("caption")
        self._updated_label.set_margin_top(8)
        self._updated_label.set_margin_bottom(4)
        self._auth_box.append(self._updated_label)

        self._content_box.append(self._auth_box)

    # ------------------------------------------------------------------
    # Model row helper
    # ------------------------------------------------------------------

    @staticmethod
    def _make_model_row(name: str) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.set_margin_top(2)
        label = Gtk.Label(label=name, xalign=0)
        label.set_size_request(60, -1)
        row.append(label)

        bar = Gtk.ProgressBar()
        bar.set_hexpand(True)
        bar.set_valign(Gtk.Align.CENTER)
        row.append(bar)

        pct = Gtk.Label(label="-%", xalign=1)
        pct.add_css_class("numeric")
        pct.set_size_request(40, -1)
        row.append(pct)

        # Stash references
        row._bar = bar  # type: ignore[attr-defined]
        row._pct_label = pct  # type: ignore[attr-defined]
        return row

    @staticmethod
    def _update_model_row(row: Gtk.Box, bucket: Optional[UsageBucket]) -> None:
        bar = row._bar  # type: ignore[attr-defined]
        pct_label = row._pct_label  # type: ignore[attr-defined]
        if bucket is None or bucket.utilization is None:
            bar.set_fraction(0.0)
            pct_label.set_text("-%")
            return
        frac = max(0.0, min(1.0, bucket.utilization / 100.0))
        bar.set_fraction(frac)
        pct_label.set_text(f"{bucket.utilization:.0f}%")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(
        self,
        usage_response: Optional[UsageResponse],
        last_error: Optional[str],
        is_authenticated: bool,
    ) -> None:
        if not is_authenticated:
            self._sign_in_box.set_visible(True)
            self._auth_box.set_visible(False)
            return

        self._sign_in_box.set_visible(False)
        self._code_box.set_visible(False)
        self._auth_box.set_visible(True)

        # Error banner
        if last_error:
            self._error_label.set_text(last_error)
            self._error_bar.set_revealed(True)
        else:
            self._error_bar.set_revealed(False)

        if usage_response is None:
            self._bucket_5h.update(None)
            self._bucket_7d.update(None)
            self._model_frame.set_visible(False)
            self._extra_frame.set_visible(False)
            self._updated_label.set_text("")
            return

        # Primary buckets
        self._bucket_5h.update(usage_response.five_hour)
        self._bucket_7d.update(usage_response.seven_day)

        # Per-model section
        has_opus = usage_response.seven_day_opus is not None
        has_sonnet = usage_response.seven_day_sonnet is not None
        self._model_frame.set_visible(has_opus or has_sonnet)
        self._opus_row.set_visible(has_opus)
        self._sonnet_row.set_visible(has_sonnet)
        if has_opus:
            self._update_model_row(self._opus_row, usage_response.seven_day_opus)
        if has_sonnet:
            self._update_model_row(self._sonnet_row, usage_response.seven_day_sonnet)

        # Extra usage
        extra = usage_response.extra_usage
        if extra is not None and extra.is_enabled:
            self._extra_frame.set_visible(True)
            util = extra.utilization or 0.0
            self._extra_bar.set_fraction(max(0.0, min(1.0, util / 100.0)))
            used = extra.used_credits_amount
            limit = extra.monthly_limit_amount
            if used is not None and limit is not None:
                self._extra_amount_label.set_text(
                    f"{ExtraUsage.format_usd(used)} / {ExtraUsage.format_usd(limit)}"
                )
            else:
                self._extra_amount_label.set_text(f"{util:.0f}%")
        else:
            self._extra_frame.set_visible(False)

        # Update chart with history data
        svc = self._app.usage_service
        if svc is not None and self._app.history_service is not None:
            points = self._app.history_service.history.data_points
            self._chart.update(points)

        # "Updated X ago"
        if svc is not None:
            self._updated_label.set_text(_time_ago_text(svc.last_updated))

    def show_code_entry(self) -> None:
        self._code_box.set_visible(True)
        self._code_entry.set_text("")
        self._code_entry.grab_focus()

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_sign_in_clicked(self, _btn: Gtk.Button) -> None:
        self._app.start_sign_in()

    def _on_code_submit(self, _widget: Gtk.Widget) -> None:
        code = self._code_entry.get_text().strip()
        if code:
            self._app.submit_code(code)
