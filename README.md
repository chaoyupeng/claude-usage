<p align="center">
  <img src="macos/Resources/icon.png" width="128" alt="Claude Usage icon">
</p>

# Claude Usage

A menu bar / system tray app that shows your Claude usage at a glance — rate limits, token stats, and more. Available for **macOS** and **Linux**.

![macOS 14+](https://img.shields.io/badge/macOS-14%2B-blue)
![Ubuntu 22.04+](https://img.shields.io/badge/Ubuntu-22.04%2B-E95420)
![License](https://img.shields.io/badge/license-BSD--2--Clause-green)

## Features

### Usage Tab (OAuth)
- Menu bar icon with dual-bar showing 5-hour and 7-day utilization
- Per-window usage with progress bars and reset timers
- Per-model breakdown (Opus / Sonnet) when available
- Extra usage tracking with USD currency display
- Usage history chart with Catmull-Rom interpolation (1h / 6h / 1d / 7d / 30d)
- Hover over the chart to see exact values at any point
- Configurable polling interval (5m / 15m / 30m / 1h)
- OAuth sign-in via browser — no API keys to manage

### Tokens Tab (Local)
- Parses Claude Code local logs from `~/.claude/projects/`
- Token counts (input, output, cache read/write) for today and all time
- Per-model cost estimates
- Daily breakdown bar chart (14 days)
- Last-hour per-minute activity graph
- No authentication required — works offline

### General
- Runs in the menu bar (macOS) or system tray (Linux)
- Minimal dependencies
- macOS: SwiftUI, Swift Charts, Sparkle
- Linux: Python, GTK4, AppIndicator3

## Install

### macOS

1. Download `ClaudeUsage.dmg` from the [latest release](https://github.com/chaoyupeng/claude-usage/releases/latest)
2. Open the disk image and drag `ClaudeUsage.app` into `Applications`
3. **Right-click** the app → **Open** (don't double-click — macOS blocks unsigned apps on first launch)
4. Click **Open** on the confirmation dialog — the app appears in the menu bar

### Linux

**AppImage (recommended):**

```sh
# Download the AppImage from the latest release, then:
chmod +x Claude_Usage-1.2.0-x86_64.AppImage
./Claude_Usage-1.2.0-x86_64.AppImage
```

System dependencies (install once):

```sh
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-ayatanaappindicator3-0.1 gir1.2-notify-0.7
```

**Debian package:**

```sh
sudo apt install ./claude-usage_1.1.0_all.deb
claude-usage
```

**From source:**

```sh
git clone https://github.com/chaoyupeng/claude-usage.git
cd claude-usage/linux
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-ayatanaappindicator3-0.1 gir1.2-notify-0.7
python3 -m claude_usage
```

## Usage

1. Launch the app — a menu bar icon appears with 5h/7d usage bars
2. Click the icon to open the popover
3. **Usage tab**: Click **Sign in with Claude** to authorize via browser, then usage auto-refreshes
4. **Tokens tab**: Shows Claude Code local token stats immediately (no sign-in needed)

## Data storage

All data is stored locally in `~/.config/claude-usage-bar/`:

| File | Purpose |
|------|---------|
| `credentials.json` | OAuth credentials (permissions: `0600`) |
| `history.json` | Usage history for the chart (30-day retention) |

Token stats are read directly from `~/.claude/projects/` JSONL logs. No data is sent anywhere other than the Anthropic API.

## Project structure

```
linux/                              # Linux system tray app (Python/GTK4)
├── claude_usage/
│   ├── app.py                      # GTK application, service wiring
│   ├── models.py                   # API response types
│   ├── usage_service.py            # OAuth, polling, API calls
│   ├── log_service.py              # JSONL log file scanner
│   ├── log_models.py               # Log parser and aggregation
│   ├── tray_icon.py                # AppIndicator3 system tray (GTK3 subprocess)
│   ├── tray_proxy.py               # IPC proxy for GTK3↔GTK4 tray communication
│   ├── main_window.py              # GTK4 dropdown window with tabs
│   ├── usage_tab.py                # Usage tab UI
│   ├── token_dashboard.py          # Tokens tab UI
│   ├── usage_chart.py              # Cairo chart with interpolation
│   └── ...
├── packaging/                      # .deb packaging
└── tests/

macos/                              # macOS menu bar app (Swift/SwiftUI)
├── Sources/ClaudeUsageBar/
│   ├── ClaudeUsageBarApp.swift      # App entry point, menu bar setup
│   ├── UsageService.swift           # OAuth, polling, API calls
│   ├── UsageModel.swift             # API response types
│   ├── UsageHistoryModel.swift      # History data types, time ranges
│   ├── UsageHistoryService.swift    # Persistence, downsampling
│   ├── UsageChartView.swift         # Swift Charts usage trajectory
│   ├── PopoverView.swift            # Main popover UI (Usage + Tokens tabs)
│   ├── TokenDashboardView.swift     # Tokens tab UI
│   ├── ClaudeLogService.swift       # JSONL log file scanner
│   ├── ClaudeLogModels.swift        # Log parser and aggregation
│   ├── SettingsView.swift           # Settings window
│   ├── NotificationService.swift    # Usage threshold notifications
│   ├── MenuBarIconRenderer.swift    # Menu bar icon drawing
│   ├── StoredCredentials.swift      # Credential persistence
│   ├── PollingOptionFormatter.swift # Polling interval display labels
│   ├── AppUpdater.swift             # Sparkle update integration
│   └── Resources/
│       ├── claude-logo.png          # Menu bar logo (512px template)
│       └── en.lproj/Localizable.strings
├── Tests/ClaudeUsageBarTests/       # Unit tests
├── Resources/
│   ├── Info.plist
│   ├── AppIcon.icns                 # App icon
│   └── claude-logo.svg             # Source SVG for menu bar logo
└── Package.swift
```

## License

[BSD 2-Clause](LICENSE)
