"""Proxy that runs the tray icon in a GTK3 subprocess.

The main application uses GTK4, which cannot coexist with the GTK3-based
AyatanaAppIndicator3 in the same process.  This proxy spawns tray_icon as
a subprocess and communicates via JSON lines over stdin/stdout pipes.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from typing import Callable, Optional

from gi.repository import GLib


class TrayProxy:
    """Drop-in replacement for TrayIcon that delegates to a subprocess."""

    def __init__(
        self,
        on_open: Optional[Callable[[], None]] = None,
        on_refresh: Optional[Callable[[], None]] = None,
        on_quit: Optional[Callable[[], None]] = None,
    ) -> None:
        self._on_open = on_open
        self._on_refresh = on_refresh
        self._on_quit = on_quit
        self._proc: Optional[subprocess.Popen] = None
        self._start_subprocess()

    def _start_subprocess(self) -> None:
        self._proc = subprocess.Popen(
            [sys.executable, "-m", "claude_usage.tray_icon"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
        )
        thread = threading.Thread(target=self._read_events, daemon=True)
        thread.start()

    def _read_events(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                action = event.get("type")
                if action == "open" and self._on_open:
                    GLib.idle_add(self._on_open)
                elif action == "refresh" and self._on_refresh:
                    GLib.idle_add(self._on_refresh)
                elif action == "quit" and self._on_quit:
                    GLib.idle_add(self._on_quit)
            except (json.JSONDecodeError, KeyError):
                pass

    def _send_command(self, cmd: dict) -> None:
        if self._proc is not None and self._proc.stdin is not None:
            try:
                self._proc.stdin.write(json.dumps(cmd) + "\n")
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError):
                pass

    def update_icon(self, pct_5h: float, pct_7d: float) -> None:
        self._send_command({"type": "update_icon", "pct_5h": pct_5h, "pct_7d": pct_7d})

    def set_unauthenticated(self) -> None:
        self._send_command({"type": "set_unauthenticated"})

    def cleanup(self) -> None:
        if self._proc is not None:
            self._send_command({"type": "quit"})
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
