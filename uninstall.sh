#!/usr/bin/env bash
# ==============================================================================
# ForwardBin Uninstaller
# Cleans up binaries, desktop shortcuts, and systemd services.
# ==============================================================================
set -e

echo "🛑 Stopping and disabling ForwardBin services..."
systemctl --user stop forwardbin-ui.service forwardbin-daemon.service 2>/dev/null || true
systemctl --user disable forwardbin-ui.service forwardbin-daemon.service 2>/dev/null || true

echo "🧹 Removing systemd units..."
rm -f "$HOME/.config/systemd/user/forwardbin-ui.service"
rm -f "$HOME/.config/systemd/user/forwardbin-daemon.service"
systemctl --user daemon-reload 2>/dev/null || true

echo "🗑️ Removing launcher and installed binaries..."
rm -f "$HOME/.local/bin/forwardbin"
rm -rf "$HOME/.local/lib/forwardbin"

echo "🎨 Removing desktop shortcut & icons..."
rm -f "$HOME/.local/share/applications/forwardbin.desktop"
rm -f "$HOME/.local/share/icons/hicolor/scalable/apps/forwardbin.svg"

# Optional removal of user database and config
if [ "$1" = "--purge" ] || [ "$1" = "-p" ]; then
    echo "⚠️ Purging user configuration and database..."
    rm -rf "$HOME/.config/forwardbin"
    rm -rf "$HOME/.local/share/forwardbin"
else
    echo "ℹ️ Note: Your configuration (~/.config/forwardbin) and scheduled data (~/.local/share/forwardbin) were preserved."
    echo "To remove them completely, run: ./uninstall.sh --purge"
fi

echo "✅ ForwardBin has been successfully uninstalled."
