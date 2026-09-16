# ⚡ ForwardBin Jarvis (Hybrid Edition)

> **Intelligent Content Drop Bin & Time Slot Scheduler for Fedora Linux**
> **Architecture: High-Performance Rust Core + Composited GTK3/Cairo Animated UI**

ForwardBin is your executive desktop assistant. Drop any video link, research paper, article, or webinar onto the floating desktop bin (or hit `Super + Shift + F`). ForwardBin extracts page metadata, accurately calculates event timezones or reading durations, books an optimal conflict-free slot into your calendar, and dispatches clean Light-Mode Gmail-styled confirmation briefs and timely reminders.

---

## 🏛️ Hybrid Directory Layout

```text
forwardbin/
├── Cargo.toml            # Rust native package manifest
├── Cargo.lock            # Exact Rust dependency tree
├── src/                  # ⚡ RUST NATIVE CORE (~8MB RAM, 0% CPU)
│   ├── main.rs           # CLI dispatcher & command router
│   ├── daemon.rs         # Background polling & slot notification daemon
│   ├── ai.rs             # Fast page inspection & OpenRouter LLM integration
│   ├── calendar.rs       # Free slot finder & Google Calendar URL generator
│   ├── db.rs             # Embedded SQLite connection & migrations
│   ├── emailer.rs        # Resend light-mode transactional email service
│   └── config.rs         # JSON configuration manager
│
├── forwardbin/           # 🎨 PYTHON COMPOSITED DESKTOP UI
│   ├── ui/
│   │   ├── animated_bin.py  # Cairo vector rendering, cyber vortex & particles
│   │   └── floating_bin.py  # GTK3 drag-and-drop floating desktop target
│   ├── content_extractor.py # Deep page & Slate CMS event extractor
│   ├── core.py              # Python workflow coordinator
│   └── calendar_sync.py     # GNOME Evolution Data Server (EDS) sync
│
├── bin/
│   └── forwardbin        # Unified executable dispatcher
├── systemd/              # User systemd service definitions
│   ├── forwardbin-ui.service      # Desktop drop widget
│   └── forwardbin-daemon.service  # 24/7 background monitor
│
├── install.sh            # 1-step installer & systemd configurator
├── Makefile              # Developer shortcuts (build, install, restart, status)
└── pyproject.toml        # Python package metadata
```

---

## 🚀 Quick Setup & Installation

```bash
cd /home/sankalp/projects/forwardbin

# 1-Step Build & Install:
./install.sh

# Or using Make:
make install
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

# Snatch whatever is currently copied in your clipboard
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

ForwardBin runs as two lightweight systemd user services:

```bash
# Check status
make status
# or:
systemctl --user status forwardbin-ui.service forwardbin-daemon.service

# Restart services
make restart
```

| Service | Engine | Role | Memory |
| :--- | :--- | :--- | :--- |
| `forwardbin-ui.service` | Python (GTK3/Cairo) | Desktop floating bin widget | ~40 MB |
| `forwardbin-daemon.service` | **Rust (Native Release)** | 24/7 background scheduler & emails | **~8 MB** |
