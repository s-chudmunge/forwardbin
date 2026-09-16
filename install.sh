#!/usr/bin/env bash
# ==============================================================================
# ForwardBin Hybrid (Rust Core + GTK3/Cairo UI) One-Step Installer & Setup
# ==============================================================================
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
SYSTEMD_DIR="$HOME/.config/systemd/user"

echo "🚀 Building & Installing ForwardBin Hybrid..."
echo "📂 Project Directory: $PROJECT_DIR"

# 1. Setup PATH for cargo
if [ -d "$HOME/.cargo/bin" ]; then
    export PATH="$HOME/.cargo/bin:$PATH"
fi

# 2. Build native Rust release binary
echo "🦀 Compiling native Rust core (daemon, CLI, scheduler)..."
cd "$PROJECT_DIR"
cargo build --release

# 3. Install CLI launcher
echo "📦 Installing launcher to $BIN_DIR/forwardbin..."
mkdir -p "$BIN_DIR"
cp "$PROJECT_DIR/bin/forwardbin" "$BIN_DIR/forwardbin"
chmod +x "$BIN_DIR/forwardbin"

# 4. Install systemd user services
echo "⚙️ Configuring systemd user services..."
mkdir -p "$SYSTEMD_DIR"
cp "$PROJECT_DIR/systemd/forwardbin-ui.service" "$SYSTEMD_DIR/"
cp "$PROJECT_DIR/systemd/forwardbin-daemon.service" "$SYSTEMD_DIR/"

systemctl --user daemon-reload
systemctl --user enable forwardbin-ui.service forwardbin-daemon.service
systemctl --user restart forwardbin-ui.service forwardbin-daemon.service

echo "✅ ForwardBin Hybrid installed and running successfully!"
echo "✨ Status:"
systemctl --user status forwardbin-ui.service forwardbin-daemon.service --no-pager
