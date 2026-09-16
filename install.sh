#!/usr/bin/env bash
# ==============================================================================
# ForwardBin Hybrid (Rust Core + Animated UI) Universal Installer & Setup
# Compatible with macOS (Apple Silicon & Intel) & Linux (Fedora, Ubuntu, Arch)
# Supports pre-built releases (instant zero-compilation install) and source builds
# ==============================================================================
set -e

# Support curl | bash one-liner installation
if [ ! -f "${BASH_SOURCE[0]}" ] || [ "${BASH_SOURCE[0]}" = "/dev/stdin" ]; then
    echo "⬇️  Downloading ForwardBin from GitHub..."
    TMP_SRC="$(mktemp -d -t forwardbin-src-XXXXXX)"
    git clone --depth 1 https://github.com/s-chudmunge/forwardbin.git "$TMP_SRC"
    exec "$TMP_SRC/install.sh" "$@"
fi

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
LIB_DIR="$HOME/.local/lib/forwardbin"
CONFIG_DIR="$HOME/.config/forwardbin"
OS_TYPE="$(uname -s)"

echo "=================================================================="
echo "⚡  ForwardBin Jarvis Hybrid Installer"
echo "=================================================================="
echo "📂 Installer Location: $PROJECT_DIR"
if [ "$OS_TYPE" = "Darwin" ]; then
    echo "🍎 Platform: macOS (Darwin $(uname -m))"
else
    echo "🐧 Platform: Linux ($OS_TYPE $(uname -m))"
fi
echo ""

# ------------------------------------------------------------------------------
# 1. Environment & PATH
# ------------------------------------------------------------------------------
if [ -d "$HOME/.cargo/bin" ]; then
    export PATH="$HOME/.cargo/bin:$PATH"
fi
export PATH="$BIN_DIR:$PATH"

# ------------------------------------------------------------------------------
# 2. Check for Pre-built Binary or Compiler
# ------------------------------------------------------------------------------
PREBUILT=""
if [ -f "$PROJECT_DIR/forwardbin-core" ] && [ -x "$PROJECT_DIR/forwardbin-core" ]; then
    PREBUILT="$PROJECT_DIR/forwardbin-core"
elif [ -f "$PROJECT_DIR/bin/forwardbin-core" ] && [ -x "$PROJECT_DIR/bin/forwardbin-core" ]; then
    PREBUILT="$PROJECT_DIR/bin/forwardbin-core"
elif [ -f "$PROJECT_DIR/target/release/forwardbin" ] && [ -x "$PROJECT_DIR/target/release/forwardbin" ]; then
    PREBUILT="$PROJECT_DIR/target/release/forwardbin"
fi

if [ -n "$PREBUILT" ]; then
    echo "🚀 Pre-compiled native Rust engine found! (Instant install, no compiler needed)"
else
    if ! command -v cargo &>/dev/null; then
        echo "⚠️  Pre-compiled binary not found and cargo (Rust toolchain) is missing."
        echo ""
        echo "Please install Rust (https://rustup.rs) or download a pre-built release package."
        exit 1
    fi
    echo "🦀 Compiling native Rust core from source (daemon, scheduler, CLI)..."
    cd "$PROJECT_DIR"
    cargo build --release
    PREBUILT="$PROJECT_DIR/target/release/forwardbin"
fi

# ------------------------------------------------------------------------------
# 3. Setup Python UI Environment
# ------------------------------------------------------------------------------
echo "🐍 Setting up Python UI environment..."
mkdir -p "$LIB_DIR" "$LIB_DIR/python" "$BIN_DIR"

# Copy Python modules for 100% self-contained standalone execution
if [ -d "$PROJECT_DIR/forwardbin" ]; then
    rm -rf "$LIB_DIR/python/forwardbin"
    cp -r "$PROJECT_DIR/forwardbin" "$LIB_DIR/python/"
fi

if command -v pip3 &>/dev/null || command -v pip &>/dev/null; then
    PIP_CMD="$(command -v pip3 || command -v pip)"
    $PIP_CMD install --user -e "$PROJECT_DIR" 2>/dev/null || \
    $PIP_CMD install --user --break-system-packages -e "$PROJECT_DIR" 2>/dev/null || \
    echo "ℹ️  System packages will be used for Python dependencies."
fi

# ------------------------------------------------------------------------------
# 4. Install Rust Core Binary & Unified Launcher
# ------------------------------------------------------------------------------
echo "📦 Installing binaries to $BIN_DIR..."
rm -f "$LIB_DIR/forwardbin-core"
cp "$PREBUILT" "$LIB_DIR/forwardbin-core"
chmod +x "$LIB_DIR/forwardbin-core"

rm -f "$BIN_DIR/forwardbin"
cp "$PROJECT_DIR/bin/forwardbin" "$BIN_DIR/forwardbin"
chmod +x "$BIN_DIR/forwardbin"

# ------------------------------------------------------------------------------
# 5. Configure Background Daemons (launchd on macOS, systemd on Linux)
# ------------------------------------------------------------------------------
if [ "$OS_TYPE" = "Darwin" ]; then
    echo "🍎 Configuring macOS launchd LaunchAgents service..."
    LAUNCH_DIR="$HOME/Library/LaunchAgents"
    mkdir -p "$LAUNCH_DIR"
    cp "$PROJECT_DIR/launchd/com.forwardbin.daemon.plist" "$LAUNCH_DIR/"
    
    # Reload agent
    launchctl unload "$LAUNCH_DIR/com.forwardbin.daemon.plist" 2>/dev/null || true
    launchctl load -w "$LAUNCH_DIR/com.forwardbin.daemon.plist"
    echo "✅ macOS background daemon registered and active."
else
    echo "🐧 Configuring Linux systemd background services..."
    SYSTEMD_DIR="$HOME/.config/systemd/user"
    APP_DIR="$HOME/.local/share/applications"
    ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"

    mkdir -p "$APP_DIR" "$ICON_DIR" "$SYSTEMD_DIR"
    cp "$PROJECT_DIR/assets/forwardbin.desktop" "$APP_DIR/"
    cp "$PROJECT_DIR/assets/forwardbin.svg" "$ICON_DIR/"

    command -v update-desktop-database &>/dev/null && update-desktop-database "$APP_DIR" 2>/dev/null || true
    command -v gtk-update-icon-cache &>/dev/null && gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

    cp "$PROJECT_DIR/systemd/forwardbin-ui.service" "$SYSTEMD_DIR/"
    cp "$PROJECT_DIR/systemd/forwardbin-daemon.service" "$SYSTEMD_DIR/"

    systemctl --user daemon-reload
    systemctl --user enable forwardbin-ui.service forwardbin-daemon.service
    systemctl --user restart forwardbin-ui.service forwardbin-daemon.service
    echo "✅ Linux systemd services registered and active."
fi

# ------------------------------------------------------------------------------
# 6. First-Time Configuration Prompt
# ------------------------------------------------------------------------------
mkdir -p "$CONFIG_DIR"
if [ ! -f "$CONFIG_DIR/config.json" ]; then
    echo ""
    echo "=================================================================="
    echo "🧙  First-Time Setup: Configure ForwardBin"
    echo "=================================================================="
    echo "Would you like to run the configuration wizard now?"
    read -rp "(Set your notification email, timezone, API keys) [Y/n]: " RUN_WIZARD
    if [[ ! "$RUN_WIZARD" =~ ^[Nn]$ ]]; then
        "$BIN_DIR/forwardbin" setup || true
    fi
fi

echo ""
echo "=================================================================="
echo "🎉  ForwardBin Installation Complete!"
echo "=================================================================="
echo "Commands to get started:"
echo "  • forwardbin add <url>      - Schedule a video, paper, or link"
echo "  • forwardbin clipboard      - Snatch clipboard contents immediately"
echo "  • forwardbin list           - View upcoming scheduled reading slots"
echo "  • forwardbin ui             - Launch/focus the floating desktop drop bin"
echo "  • forwardbin setup          - Re-run configuration wizard anytime"
echo ""
echo "💡 Tip: Make sure $BIN_DIR is in your PATH."
echo "   Add this to your ~/.bashrc or ~/.zshrc if needed:"
echo "   export PATH=\"\$HOME/.local/bin:\$PATH\""
echo "=================================================================="
