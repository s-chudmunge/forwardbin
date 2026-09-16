#!/usr/bin/env bash
# ==============================================================================
# ForwardBin Hybrid (Rust Core + GTK3/Cairo UI) One-Step Installer & Setup
# Works across Fedora, Ubuntu, Debian, Arch, and standard Linux distributions.
# ==============================================================================
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
LIB_DIR="$HOME/.local/lib/forwardbin"
SYSTEMD_DIR="$HOME/.config/systemd/user"
APP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
CONFIG_DIR="$HOME/.config/forwardbin"

echo "=================================================================="
echo "⚡  ForwardBin Jarvis Hybrid Installer"
echo "=================================================================="
echo "📂 Project Source: $PROJECT_DIR"
echo ""

# ------------------------------------------------------------------------------
# 1. Environment & PATH
# ------------------------------------------------------------------------------
if [ -d "$HOME/.cargo/bin" ]; then
    export PATH="$HOME/.cargo/bin:$PATH"
fi
export PATH="$BIN_DIR:$PATH"

# ------------------------------------------------------------------------------
# 2. Dependency Checks & Helpful Distro Guidance
# ------------------------------------------------------------------------------
MISSING_DEPS=()

if ! command -v cargo &>/dev/null; then
    MISSING_DEPS+=("cargo (Rust toolchain)")
fi
if ! command -v python3 &>/dev/null; then
    MISSING_DEPS+=("python3")
fi

# Quick test for GTK3 Python bindings
if command -v python3 &>/dev/null; then
    if ! python3 -c "import gi, cairo; gi.require_version('Gtk', '3.0')" &>/dev/null; then
        MISSING_DEPS+=("GTK3/Cairo Python bindings (PyGObject & pycairo)")
    fi
fi

if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
    echo "⚠️  Missing required dependencies: ${MISSING_DEPS[*]}"
    echo ""
    echo "Please install them using your distribution's package manager:"
    if [ -f /etc/fedora-release ] || [ -f /etc/redhat-release ]; then
        echo "  👉 Fedora / RHEL:"
        echo "     sudo dnf install -y cargo gtk3 python3-gobject python3-cairo python3-pip"
    elif [ -f /etc/debian_version ]; then
        echo "  👉 Ubuntu / Debian / Mint:"
        echo "     sudo apt update && sudo apt install -y cargo gir1.2-gtk-3.0 python3-gi python3-gi-cairo python3-cairo python3-pip"
    elif [ -f /etc/arch-release ]; then
        echo "  👉 Arch Linux / Manjaro:"
        echo "     sudo pacman -S --needed rust gtk3 python-gobject python-cairo python-pip"
    else
        echo "  👉 Install Rust: https://rustup.rs"
        echo "  👉 Install GTK3, PyGObject, and pycairo using your package manager."
    fi
    echo ""
    read -rp "Would you like to proceed anyway? (y/N): " CONTINUE_ANYWAY
    if [[ ! "$CONTINUE_ANYWAY" =~ ^[Yy]$ ]]; then
        echo "Installation aborted. Please install the required packages and run ./install.sh again."
        exit 1
    fi
fi

# ------------------------------------------------------------------------------
# 3. Build Native Rust Release Binary
# ------------------------------------------------------------------------------
echo "🦀 Compiling native Rust core (daemon, scheduler, CLI)..."
cd "$PROJECT_DIR"
cargo build --release

# ------------------------------------------------------------------------------
# 4. Setup Python UI Environment
# ------------------------------------------------------------------------------
echo "🐍 Setting up Python UI environment..."
if command -v pip3 &>/dev/null || command -v pip &>/dev/null; then
    PIP_CMD="$(command -v pip3 || command -v pip)"
    # Attempt editable user install; handle PEP 668 externally managed envs if needed
    $PIP_CMD install --user -e "$PROJECT_DIR" 2>/dev/null || \
    $PIP_CMD install --user --break-system-packages -e "$PROJECT_DIR" 2>/dev/null || \
    echo "ℹ️  System packages will be used for Python dependencies."
fi

# ------------------------------------------------------------------------------
# 5. Install Rust Core Binary & Unified Launcher
# ------------------------------------------------------------------------------
echo "📦 Installing binaries..."
mkdir -p "$BIN_DIR" "$LIB_DIR"
cp "$PROJECT_DIR/target/release/forwardbin" "$LIB_DIR/forwardbin-core"
chmod +x "$LIB_DIR/forwardbin-core"

cp "$PROJECT_DIR/bin/forwardbin" "$BIN_DIR/forwardbin"
chmod +x "$BIN_DIR/forwardbin"

# ------------------------------------------------------------------------------
# 6. Install Desktop Shortcut & App Icon
# ------------------------------------------------------------------------------
echo "🎨 Installing desktop launcher & icon..."
mkdir -p "$APP_DIR" "$ICON_DIR"
cp "$PROJECT_DIR/assets/forwardbin.desktop" "$APP_DIR/"
cp "$PROJECT_DIR/assets/forwardbin.svg" "$ICON_DIR/"

# Update desktop & icon caches if tools exist
command -v update-desktop-database &>/dev/null && update-desktop-database "$APP_DIR" 2>/dev/null || true
command -v gtk-update-icon-cache &>/dev/null && gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

# ------------------------------------------------------------------------------
# 7. Configure Systemd User Services
# ------------------------------------------------------------------------------
echo "⚙️  Configuring systemd background services..."
mkdir -p "$SYSTEMD_DIR"
cp "$PROJECT_DIR/systemd/forwardbin-ui.service" "$SYSTEMD_DIR/"
cp "$PROJECT_DIR/systemd/forwardbin-daemon.service" "$SYSTEMD_DIR/"

systemctl --user daemon-reload
systemctl --user enable forwardbin-ui.service forwardbin-daemon.service
systemctl --user restart forwardbin-ui.service forwardbin-daemon.service

# ------------------------------------------------------------------------------
# 8. Check Configuration File
# ------------------------------------------------------------------------------
mkdir -p "$CONFIG_DIR"
if [ ! -f "$CONFIG_DIR/config.json" ]; then
    echo ""
    echo "💡 No configuration file detected at ~/.config/forwardbin/config.json."
    read -rp "Would you like to run the 30-second setup wizard now? (Y/n): " RUN_WIZARD
    if [[ ! "$RUN_WIZARD" =~ ^[Nn]$ ]]; then
        "$BIN_DIR/forwardbin" setup
    fi
fi

echo ""
echo "=================================================================="
echo "✅ ForwardBin Hybrid installed successfully!"
echo "=================================================================="
echo "🚀 Getting started:"
echo "   - Floating Drop Bin:   forwardbin ui (or launch from Applications menu)"
echo "   - Add any link/video:  forwardbin add <URL>"
echo "   - Snatch clipboard:    forwardbin clipboard"
echo "   - View scheduled queue:forwardbin list"
echo "   - Quick Setup Wizard:  forwardbin setup"
echo "=================================================================="
