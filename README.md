<p align="center">
  <img src="macos/Resources/icon.png" width="128" alt="Claude Usage icon">
</p>

# Claude Usage

A menu bar app that shows your Claude usage at a glance — rate limits, token stats, and more.

![macOS 14+](https://img.shields.io/badge/macOS-14%2B-blue)
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
- Runs in the menu bar
- Minimal dependencies — SwiftUI, Swift Charts, Sparkle

## Install

The app is **not notarised by Apple**, so macOS blocks it on first launch. This
is expected — notarisation requires a paid Apple Developer account. Pick
whichever route below suits you; both are one-time.

Download `ClaudeUsage.dmg` from the
[latest release](https://github.com/chaoyupeng/claude-usage/releases/latest) and
drag `ClaudeUsage.app` into `Applications`. Then:

**Route 1 — no Terminal.** Double-click the app. macOS shows
*"Apple could not verify … is free of malware"* with only **Done** and
**Move to Bin** — click **Done**, then open **System Settings → Privacy &
Security**, scroll to the bottom, and click **Open Anyway** next to the message
about `ClaudeUsageBar`. Confirm, and it launches.

**Route 2 — one command.** Clear the quarantine flag, then open it normally:

```sh
xattr -d com.apple.quarantine /Applications/ClaudeUsageBar.app
```

> Use `-d`, not `-dr`. The recursive form fails with *Operation not permitted* on
> recent macOS, because it tries to modify files inside the signed bundle.

On older macOS (14 and earlier) right-click → **Open** also worked. It no longer
does: the current dialog has no bypass button, which is why the two routes above
exist.

**From source** — a locally built app is never quarantined, so there is no
warning at all:

```sh
git clone https://github.com/chaoyupeng/claude-usage.git
cd claude-usage
make app          # builds macos/ClaudeUsageBar.app
make install      # copies it to /Applications
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
