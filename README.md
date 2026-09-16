# ⚡ ForwardBin Jarvis (Hybrid Edition)

> **Intelligent Content Drop Bin & Time Slot Scheduler for macOS & Linux**
> **Architecture: High-Performance Rust Core + Composited Floating UI**

ForwardBin is your executive desktop assistant. Drop any video link, research paper, article, or webinar onto the floating desktop bin (or copy and snatch it). ForwardBin extracts page metadata, accurately calculates event timezones or reading durations, books an optimal conflict-free slot into your calendar, and dispatches clean Light-Mode Gmail-styled confirmation briefs and timely reminders.

---

## 💻 Supported Platforms

- **macOS** (Apple Silicon M1/M2/M3/M4 & Intel):
  - Native clipboard snatching via `pbpaste`
  - Native macOS Notification Center alerts via `osascript`
  - Background daemon managed via macOS `launchd` (`~/Library/LaunchAgents/com.forwardbin.daemon.plist`)
  - Lightweight animated floating desktop orb via native Cocoa/Tkinter (or GTK3)
- **Linux** (Fedora, Ubuntu, Debian, Arch, Manjaro):
  - Wayland (`wl-paste`) and X11 (`xclip`) clipboard snatching
  - Desktop notifications via `notify-send`
  - 24/7 background daemon and desktop UI managed via `systemd --user`
  - Composited translucent GTK3 / Cairo cyber vortex drop target

---

## 🏛️ Hybrid Architecture Layout

```text
forwardbin/
├── Cargo.toml            # Rust native package manifest
├── Cargo.lock            # Exact Rust dependency tree
├── src/                  # ⚡ RUST NATIVE CORE (~8MB RAM, 0% CPU)
│   ├── main.rs           # CLI dispatcher, setup wizard & command router
│   ├── daemon.rs         # 24/7 background polling & slot notification daemon
│   ├── ai.rs             # Fast page inspection & OpenRouter LLM integration
│   ├── calendar.rs       # Free slot finder & Google Calendar URL generator
│   ├── db.rs             # Embedded SQLite connection & migrations
│   ├── emailer.rs        # Resend light-mode transactional email service
│   └── config.rs         # Cross-platform config & notification manager
│
├── forwardbin/           # 🎨 PYTHON COMPOSITED DESKTOP UI
│   ├── ui/
│   │   ├── animated_bin.py  # Cairo vector rendering, cyber vortex & particles
│   │   ├── macos_bin.py     # Native macOS Tkinter/Cocoa floating drop target
│   │   └── floating_bin.py  # GTK3 drag-and-drop floating desktop target
│   ├── content_extractor.py # Deep page & Slate CMS event extractor
│   ├── core.py              # Cross-platform workflow coordinator
│   └── calendar_sync.py     # Calendar ICS & Evolution Data Server sync
│
├── bin/
│   └── forwardbin        # Unified executable dispatcher
├── systemd/              # Linux systemd service units
├── launchd/              # macOS launchd LaunchAgent plists
│   └── com.forwardbin.daemon.plist
│
├── install.sh            # 1-step cross-platform installer (macOS & Linux)
├── uninstall.sh          # Clean uninstaller (macOS & Linux)
├── Makefile              # Developer shortcuts (build, install, restart, status)
└── pyproject.toml        # Python package metadata
```

---

## 🚀 Quick Installation

### On macOS
```bash
# 1. Install prerequisites (if not already installed)
brew install rust python3

# 2. Clone and install
git clone <repo-url>
cd forwardbin
./install.sh
```

### On Linux (Fedora / Ubuntu / Arch)
```bash
# 1. Clone and install (install.sh guides you through distro packages)
git clone <repo-url>
cd forwardbin
./install.sh
```

---

## 🧙 Configuration Setup Wizard

Run the interactive setup anytime to configure your email, notification rules, and timezone:

```bash
forwardbin setup
```

---

## 🛠️ Commands & Usage

```bash
# Launch or show the floating animated UI bin
forwardbin ui

# Schedule any link or event directly from terminal
forwardbin add "https://gradapply.georgetown.edu/register/?id=9a32578d-1828-429b-b6c0-2867b4939b02"
forwardbin add "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
forwardbin add "https://arxiv.org/abs/1706.03762"

# Snatch whatever is currently in your clipboard (pbpaste / wl-paste / xclip)
forwardbin clipboard

# List your upcoming scheduled items
forwardbin list

# View configuration
forwardbin config --show

# Send a test email via Resend
forwardbin test-email
```

---

## ⚙️ Background Services

| Platform | Service Manager | File Location | Memory |
| :--- | :--- | :--- | :--- |
| **macOS** | `launchd` (`launchctl`) | `~/Library/LaunchAgents/com.forwardbin.daemon.plist` | **~8 MB** |
| **Linux** | `systemd --user` | `~/.config/systemd/user/forwardbin-daemon.service` | **~8 MB** |

To uninstall cleanly at any time:
```bash
./uninstall.sh
# or remove all saved database & config:
./uninstall.sh --purge
```
