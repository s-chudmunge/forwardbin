#!/usr/bin/env bash
# ==============================================================================
# ForwardBin Release Packaging Script
# Generates:
#   1. dist/forwardbin-v1.0.0-linux-x86_64.tar.gz (Pre-built binary archive)
#   2. dist/forwardbin-installer.run (Single-file self-extracting executable installer)
# ==============================================================================
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="1.0.0"
DIST_DIR="$DIR/dist"
STAGE_DIR="/tmp/forwardbin-v${VERSION}"

echo "=================================================================="
echo "📦  Building ForwardBin v${VERSION} Distribution Packages"
echo "=================================================================="

# 1. Compile and strip release binary
echo "🦀 Compiling release binary with cargo..."
cd "$DIR"
cargo build --release

mkdir -p "$DIST_DIR"
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"

echo "✂️  Stripping debug symbols from core binary..."
strip -s -o "$STAGE_DIR/forwardbin-core" "$DIR/target/release/forwardbin"
chmod +x "$STAGE_DIR/forwardbin-core"

# 2. Copy launcher, python modules, assets, services
echo "📂 Staging release assets..."
mkdir -p "$STAGE_DIR/bin"
cp "$DIR/bin/forwardbin" "$STAGE_DIR/bin/"
chmod +x "$STAGE_DIR/bin/forwardbin"

cp -r "$DIR/forwardbin" "$STAGE_DIR/"
cp -r "$DIR/assets" "$STAGE_DIR/"
cp -r "$DIR/systemd" "$STAGE_DIR/"
cp -r "$DIR/launchd" "$STAGE_DIR/"
cp "$DIR/install.sh" "$STAGE_DIR/"
chmod +x "$STAGE_DIR/install.sh"
cp "$DIR/uninstall.sh" "$STAGE_DIR/"
chmod +x "$STAGE_DIR/uninstall.sh"
cp "$DIR/LICENSE" "$STAGE_DIR/"
cp "$DIR/README.md" "$STAGE_DIR/"

# 3. Create Prebuilt Release Tarball
TAR_NAME="forwardbin-v${VERSION}-linux-x86_64.tar.gz"
echo "🗜️  Creating $TAR_NAME..."
tar -czf "$DIST_DIR/$TAR_NAME" -C "/tmp" "forwardbin-v${VERSION}"
ls -lh "$DIST_DIR/$TAR_NAME"

# 4. Create Single-File Self-Extracting Executable Installer (.run)
RUN_INSTALLER="$DIST_DIR/forwardbin-installer.run"
echo "🚀 Creating self-extracting installer: $RUN_INSTALLER..."

cat << 'RUN_HEADER_EOF' > "$RUN_INSTALLER"
#!/usr/bin/env bash
# ==============================================================================
# ForwardBin Single-File Self-Extracting Installer
# Run: chmod +x forwardbin-installer.run && ./forwardbin-installer.run
# ==============================================================================
set -e

TMP_EXTRACT="$(mktemp -d -t forwardbin-pkg-XXXXXX)"
cleanup() { rm -rf "$TMP_EXTRACT"; }
trap cleanup EXIT INT TERM

echo "📦 Extracting ForwardBin installer payload..."
PAYLOAD_LINE=$(grep -a -n "^__ARCHIVE_PAYLOAD_BELOW__$" "$0" | cut -d: -f1)
tail -n +$((PAYLOAD_LINE + 1)) "$0" | tar -xz -C "$TMP_EXTRACT"

# Find extracted folder
PKG_DIR=$(find "$TMP_EXTRACT" -maxdepth 1 -type d -name "forwardbin-*" | head -n 1)
if [ -z "$PKG_DIR" ]; then
    PKG_DIR="$TMP_EXTRACT"
fi

echo "⚡ Starting ForwardBin setup..."
"$PKG_DIR/install.sh" "$@"
exit 0
__ARCHIVE_PAYLOAD_BELOW__
RUN_HEADER_EOF

# Append the tarball payload
cat "$DIST_DIR/$TAR_NAME" >> "$RUN_INSTALLER"
chmod +x "$RUN_INSTALLER"

ls -lh "$RUN_INSTALLER"

# Clean up stage
rm -rf "$STAGE_DIR"

echo "=================================================================="
echo "✅ Build Complete! Packages available in dist/:"
echo "   1. $DIST_DIR/$TAR_NAME"
echo "   2. $RUN_INSTALLER"
echo "=================================================================="
