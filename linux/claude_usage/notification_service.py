"""Desktop notification service — ported from NotificationService.swift.

Uses ``notify-send`` (libnotify) on Linux instead of macOS UNUserNotificationCenter.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import List, Optional


# ---------------------------------------------------------------------------
# ThresholdAlert
# ---------------------------------------------------------------------------

@dataclass
class ThresholdAlert:
    window: str
    pct: int


# ---------------------------------------------------------------------------
# Pure threshold logic
# ---------------------------------------------------------------------------

def crossed_thresholds(
    threshold_5h: int,
    threshold_7d: int,
    threshold_extra: int,
    previous_5h: float,
    previous_7d: float,
    previous_extra: float,
    current_5h: float,
    current_7d: float,
    current_extra: float,
) -> List[ThresholdAlert]:
    """Return which threshold alerts should fire given a state transition.

    All percentage values are in the 0-100 scale.
    """
    alerts: List[ThresholdAlert] = []

    if threshold_5h > 0:
        t = float(threshold_5h)
        if current_5h >= t and previous_5h < t:
            alerts.append(ThresholdAlert(window="5-hour", pct=round(current_5h)))

    if threshold_7d > 0:
        t = float(threshold_7d)
        if current_7d >= t and previous_7d < t:
            alerts.append(ThresholdAlert(window="7-day", pct=round(current_7d)))

    if threshold_extra > 0:
        t = float(threshold_extra)
        if current_extra >= t and previous_extra < t:
            alerts.append(ThresholdAlert(window="Extra usage", pct=round(current_extra)))

    return alerts


# ---------------------------------------------------------------------------
# NotificationService
# ---------------------------------------------------------------------------

class NotificationService:
    """Manages usage-threshold notifications with settings persistence."""

    def __init__(self, settings_file: Optional[str] = None) -> None:
        if settings_file is None:
            config_dir = os.path.join(
                os.path.expanduser("~"), ".config", "claude-usage-bar"
            )
            os.makedirs(config_dir, mode=0o700, exist_ok=True)
            settings_file = os.path.join(config_dir, "settings.json")
        self._settings_file = settings_file

        self.threshold_5h: int = 0
        self.threshold_7d: int = 0
        self.threshold_extra: int = 0

        self._previous_pct_5h: Optional[float] = None
        self._previous_pct_7d: Optional[float] = None
        self._previous_pct_extra: Optional[float] = None

        self.load_settings()

    # ------------------------------------------------------------------
    # Threshold setters (clamped 0-100)
    # ------------------------------------------------------------------

    def set_threshold_5h(self, value: int) -> None:
        self.threshold_5h = max(0, min(100, value))
        self._previous_pct_5h = None
        self.save_settings()

    def set_threshold_7d(self, value: int) -> None:
        self.threshold_7d = max(0, min(100, value))
        self._previous_pct_7d = None
        self.save_settings()

    def set_threshold_extra(self, value: int) -> None:
        self.threshold_extra = max(0, min(100, value))
        self._previous_pct_extra = None
        self.save_settings()

    # ------------------------------------------------------------------
    # Check and notify
    # ------------------------------------------------------------------

    def check_and_notify(
        self, pct_5h: float, pct_7d: float, pct_extra: float
    ) -> None:
        """Check thresholds and send desktop notifications for crossings.

        *pct_5h*, *pct_7d*, *pct_extra* are ratios in 0..1 scale.
        """
        current_5h = pct_5h * 100
        current_7d = pct_7d * 100
        current_extra = pct_extra * 100

        prev_5h = self._previous_pct_5h if self._previous_pct_5h is not None else 0.0
        prev_7d = self._previous_pct_7d if self._previous_pct_7d is not None else 0.0
        prev_extra = self._previous_pct_extra if self._previous_pct_extra is not None else 0.0

        alerts = crossed_thresholds(
            threshold_5h=self.threshold_5h,
            threshold_7d=self.threshold_7d,
            threshold_extra=self.threshold_extra,
            previous_5h=prev_5h,
            previous_7d=prev_7d,
            previous_extra=prev_extra,
            current_5h=current_5h,
            current_7d=current_7d,
            current_extra=current_extra,
        )

        # Update previous values *after* computing alerts
        self._previous_pct_5h = current_5h
        self._previous_pct_7d = current_7d
        self._previous_pct_extra = current_extra

        for alert in alerts:
            self.send_notification(alert.window, alert.pct)

    # ------------------------------------------------------------------
    # Desktop notification via notify-send
    # ------------------------------------------------------------------

    @staticmethod
    def send_notification(window: str, pct: int) -> None:
        """Send a desktop notification using ``notify-send``."""
        title = "Claude Usage"
        body = f"{window} usage has reached {pct}%"
        try:
            subprocess.Popen(
                ["notify-send", title, body],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            # notify-send not installed — log to stderr
            import sys
            print(f"[Notification] {body} (notify-send not found)", file=sys.stderr)

    # ------------------------------------------------------------------
    # Settings persistence
    # ------------------------------------------------------------------

    def load_settings(self) -> None:
        try:
            with open(self._settings_file, "r") as f:
                data = json.load(f)
            self.threshold_5h = max(0, min(100, data.get("notificationThreshold5h", 0)))
            self.threshold_7d = max(0, min(100, data.get("notificationThreshold7d", 0)))
            self.threshold_extra = max(0, min(100, data.get("notificationThresholdExtra", 0)))
        except (FileNotFoundError, json.JSONDecodeError, TypeError, OSError):
            pass

    def save_settings(self) -> None:
        data = {
            "notificationThreshold5h": self.threshold_5h,
            "notificationThreshold7d": self.threshold_7d,
            "notificationThresholdExtra": self.threshold_extra,
        }
        try:
            tmp_path = self._settings_file + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, self._settings_file)
        except OSError:
            pass
