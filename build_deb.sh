#!/usr/bin/env bash
# build_deb.sh — build a .deb package for git-ssh-helper
# Usage:  ./build_deb.sh [--output-dir DIR]
# Produces:  git-ssh-helper_<version>_all.deb
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="git-ssh-helper"
PKG_NAME="git-ssh-helper"
VERSION="0.1.0"
ARCH="all"
MAINTAINER="Maintainer <maintainer@example.com>"
DESCRIPTION="Helper to clone git repos using selected SSH private keys (GUI/TUI/CLI)"
LONG_DESC="git-ssh-helper discovers SSH private keys in ~/.ssh, lets you select one,
 and performs git clone via GIT_SSH_COMMAND so you don't have to touch ssh-agent or
 ~/.ssh/config manually. Includes a Tkinter GUI, a curses TUI, and a plain CLI."

OUTPUT_DIR="${SCRIPT_DIR}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; RESET='\033[0m'
info() { echo -e "${CYAN}[INFO]${RESET}  $*"; }
ok()   { echo -e "${GREEN}[ OK ]${RESET}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
die()  { echo -e "${RED}[ERR ]${RESET}  $*" >&2; exit 1; }

# ── parse args ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --output-dir) OUTPUT_DIR="$2"; shift 2 ;;
        --version)    VERSION="$2";    shift 2 ;;
        *) die "Unknown argument: $1" ;;
    esac
done

# ── check requirements ────────────────────────────────────────────────────────
command -v dpkg-deb >/dev/null 2>&1 || die "dpkg-deb not found. Install: sudo apt install dpkg"
command -v python3  >/dev/null 2>&1 || die "python3 not found"
python3 -m pip --version >/dev/null 2>&1 || die "pip not found: sudo apt install python3-pip"
command -v fakeroot >/dev/null 2>&1 || warn "fakeroot not found — package may have wrong file ownership (install: sudo apt install fakeroot)"

DEB_FILE="${OUTPUT_DIR}/${PKG_NAME}_${VERSION}_${ARCH}.deb"
BUILD_ROOT="$(mktemp -d)"
trap 'rm -rf "$BUILD_ROOT"' EXIT

info "Build root: $BUILD_ROOT"
info "Output:     $DEB_FILE"

# ── directory structure ───────────────────────────────────────────────────────
PKG_ROOT="$BUILD_ROOT/pkg"

mkdir -p \
    "$PKG_ROOT/DEBIAN" \
    "$PKG_ROOT/usr/lib/git-ssh-helper" \
    "$PKG_ROOT/usr/bin" \
    "$PKG_ROOT/usr/share/applications" \
    "$PKG_ROOT/usr/share/icons/hicolor/scalable/apps" \
    "$PKG_ROOT/usr/share/icons/hicolor/48x48/apps" \
    "$PKG_ROOT/usr/share/doc/$PKG_NAME"

# ── install Python package into lib dir ───────────────────────────────────────
info "Installing Python files..."
python3 -m pip install \
    --target "$PKG_ROOT/usr/lib/git-ssh-helper" \
    --no-compile \
    --no-deps \
    "$SCRIPT_DIR" \
    --quiet

# Remove pip-installed metadata we don't want in the deb
find "$PKG_ROOT/usr/lib/git-ssh-helper" \
    -maxdepth 1 -name "*.dist-info" -type d -exec rm -rf {} + 2>/dev/null || true
find "$PKG_ROOT/usr/lib/git-ssh-helper" \
    -maxdepth 1 -name "*.egg-info" -type d -exec rm -rf {} + 2>/dev/null || true

# Remove the script pip placed into lib (we create our own wrapper below)
rm -f "$PKG_ROOT/usr/lib/git-ssh-helper/bin/git-ssh-helper" 2>/dev/null || true
rmdir "$PKG_ROOT/usr/lib/git-ssh-helper/bin" 2>/dev/null || true

ok "Python package installed to $PKG_ROOT/usr/lib/git-ssh-helper"

# ── /usr/bin/git-ssh-helper wrapper ──────────────────────────────────────────
info "Creating launcher..."
cat > "$PKG_ROOT/usr/bin/git-ssh-helper" <<'LAUNCHER'
#!/usr/bin/env python3
import sys, os
sys.path.insert(0, "/usr/lib/git-ssh-helper")
from tools.cli import main
sys.exit(main())
LAUNCHER
chmod 0755 "$PKG_ROOT/usr/bin/git-ssh-helper"
ok "Launcher created"

# ── icon ──────────────────────────────────────────────────────────────────────
ICON_SRC="$SCRIPT_DIR/assets/git-ssh-helper.svg"
if [[ -f "$ICON_SRC" ]]; then
    cp "$ICON_SRC" "$PKG_ROOT/usr/share/icons/hicolor/scalable/apps/git-ssh-helper.svg"
    ok "SVG icon installed"

    if command -v rsvg-convert >/dev/null 2>&1; then
        rsvg-convert -w 48 -h 48 "$ICON_SRC" \
            -o "$PKG_ROOT/usr/share/icons/hicolor/48x48/apps/git-ssh-helper.png"
        ok "PNG icon generated via rsvg-convert"
    elif command -v inkscape >/dev/null 2>&1; then
        inkscape "$ICON_SRC" --export-width=48 \
            --export-filename="$PKG_ROOT/usr/share/icons/hicolor/48x48/apps/git-ssh-helper.png" 2>/dev/null
        ok "PNG icon generated via inkscape"
    else
        warn "rsvg-convert and inkscape not found — 48x48 PNG icon will be missing"
        warn "Install with: sudo apt install librsvg2-bin"
        # Remove empty png dir if icon was not generated
        rmdir "$PKG_ROOT/usr/share/icons/hicolor/48x48/apps" 2>/dev/null || true
        rmdir "$PKG_ROOT/usr/share/icons/hicolor/48x48" 2>/dev/null || true
    fi
else
    warn "Icon not found at $ICON_SRC — skipping"
fi

# ── .desktop file ─────────────────────────────────────────────────────────────
cat > "$PKG_ROOT/usr/share/applications/git-ssh-helper.desktop" <<'DESKTOP'
[Desktop Entry]
Version=1.0
Type=Application
Name=SSH Git Manager
GenericName=Git SSH Key Manager
Comment=Manage SSH keys, remotes and branches for git repositories
Exec=git-ssh-helper --ui
Icon=git-ssh-helper
Terminal=false
Categories=Development;VersionControl;Utility;
Keywords=git;ssh;clone;key;remote;branch;tunnel;
StartupNotify=true
DESKTOP
ok ".desktop entry created"

# ── copyright / doc ───────────────────────────────────────────────────────────
if [[ -f "$SCRIPT_DIR/LICENSE" ]]; then
    cp "$SCRIPT_DIR/LICENSE" "$PKG_ROOT/usr/share/doc/$PKG_NAME/copyright"
fi

# gzip changelog (policy requirement)
cat > "$BUILD_ROOT/changelog" <<EOF
$PKG_NAME ($VERSION) unstable; urgency=low

  * Initial release.

 -- $MAINTAINER  $(date -R)
EOF
gzip -9n -c "$BUILD_ROOT/changelog" > "$PKG_ROOT/usr/share/doc/$PKG_NAME/changelog.gz"

# ── calculate installed size (kB) ─────────────────────────────────────────────
INSTALLED_SIZE="$(du -sk "$PKG_ROOT" | cut -f1)"

# ── DEBIAN/control ────────────────────────────────────────────────────────────
cat > "$PKG_ROOT/DEBIAN/control" <<EOF
Package: $PKG_NAME
Version: $VERSION
Architecture: $ARCH
Maintainer: $MAINTAINER
Installed-Size: $INSTALLED_SIZE
Depends: python3 (>= 3.8), git, openssh-client
Recommends: python3-tk, librsvg2-bin
Section: devel
Priority: optional
Homepage: https://github.com/example/git-ssh-helper
Description: $DESCRIPTION
 $LONG_DESC
EOF

# ── DEBIAN/postinst ───────────────────────────────────────────────────────────
cat > "$PKG_ROOT/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e
if command -v update-icon-caches >/dev/null 2>&1; then
    update-icon-caches /usr/share/icons/hicolor 2>/dev/null || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor 2>/dev/null || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications 2>/dev/null || true
fi
POSTINST
chmod 0755 "$PKG_ROOT/DEBIAN/postinst"

# ── DEBIAN/prerm ──────────────────────────────────────────────────────────────
cat > "$PKG_ROOT/DEBIAN/prerm" <<'PRERM'
#!/bin/sh
set -e
# nothing to do before removal
PRERM
chmod 0755 "$PKG_ROOT/DEBIAN/prerm"

# ── DEBIAN/postrm ─────────────────────────────────────────────────────────────
cat > "$PKG_ROOT/DEBIAN/postrm" <<'POSTRM'
#!/bin/sh
set -e
if command -v update-icon-caches >/dev/null 2>&1; then
    update-icon-caches /usr/share/icons/hicolor 2>/dev/null || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor 2>/dev/null || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications 2>/dev/null || true
fi
POSTRM
chmod 0755 "$PKG_ROOT/DEBIAN/postrm"

# ── fix permissions ───────────────────────────────────────────────────────────
info "Fixing permissions..."
find "$PKG_ROOT" -type d -exec chmod 0755 {} \;
find "$PKG_ROOT" -type f ! -name "postinst" ! -name "prerm" ! -name "postrm" \
    -exec chmod 0644 {} \;
chmod 0755 "$PKG_ROOT/usr/bin/git-ssh-helper"
chmod 0755 "$PKG_ROOT/DEBIAN/postinst"
chmod 0755 "$PKG_ROOT/DEBIAN/prerm"
chmod 0755 "$PKG_ROOT/DEBIAN/postrm"
# Make Python files non-executable (policy)
find "$PKG_ROOT/usr/lib/git-ssh-helper" -name "*.py" -exec chmod 0644 {} \;

# ── build deb ─────────────────────────────────────────────────────────────────
info "Building .deb package..."
mkdir -p "$OUTPUT_DIR"

if command -v fakeroot >/dev/null 2>&1; then
    fakeroot dpkg-deb --build "$PKG_ROOT" "$DEB_FILE"
else
    dpkg-deb --build "$PKG_ROOT" "$DEB_FILE"
fi

ok "Package built: $DEB_FILE"
echo ""
echo "  Install with:  sudo dpkg -i $DEB_FILE"
echo "  Or:            sudo apt install $DEB_FILE   (resolves deps)"
echo "  Remove with:   sudo apt remove $PKG_NAME"
echo ""
