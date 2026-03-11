#!/usr/bin/env bash
# install.sh — install git-ssh-helper on a local system
#
# Usage:
#   ./install.sh              # user install (no root required)
#   sudo ./install.sh         # system-wide install
#   ./install.sh --uninstall  # remove
#
# Install methods tried in order (user mode):
#   1. pipx  (recommended for CLI apps on PEP-668 systems)
#   2. venv  (~/.local/lib/git-ssh-helper-venv) + wrapper in ~/.local/bin
#
# Install methods tried in order (root/system mode):
#   1. venv  (/opt/git-ssh-helper-venv) + wrapper in /usr/local/bin
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="git-ssh-helper"
DESKTOP_ID="git-ssh-helper"
ICON_SRC="$SCRIPT_DIR/assets/git-ssh-helper.svg"

# Venv install paths
USER_VENV_DIR="$HOME/.local/lib/git-ssh-helper-venv"
USER_BIN_DIR="$HOME/.local/bin"
SYS_VENV_DIR="/opt/git-ssh-helper-venv"
SYS_BIN_DIR="/usr/local/bin"

# IMPORTANT: Do NOT use $XDG_DATA_HOME — it is overridden inside snap environments
# (e.g. VSCode snap sets it to the snap's private data dir).  Always use the real
# user data dir so desktop/icon entries are visible system-wide.
USER_DATA_DIR="$HOME/.local/share"

# ── colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; RESET='\033[0m'
info()  { echo -e "${CYAN}[INFO]${RESET}  $*"; }
ok()    { echo -e "${GREEN}[ OK ]${RESET}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
die()   { echo -e "${RED}[ERR ]${RESET}  $*" >&2; exit 1; }

# ── helpers ───────────────────────────────────────────────────────────────────
is_root() { [[ "$(id -u)" -eq 0 ]]; }

check_python() {
    command -v python3 >/dev/null 2>&1 \
        || die "python3 not found. Install: sudo apt install python3"
    python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)' \
        || die "Python 3.8+ required (found $(python3 --version))"
    ok "python3 found: $(python3 --version)"
}

check_git() {
    command -v git >/dev/null 2>&1 || die "git not found. Install: sudo apt install git"
    ok "git found"
}

check_gtk() {
    if python3 -c "import gi; gi.require_version('Gtk','3.0'); from gi.repository import Gtk" 2>/dev/null; then
        ok "GTK 3 (PyGObject) found"
    else
        warn "GTK 3 not found — GUI will show install hint"
        warn "Install: sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0"
    fi
}

# ── uninstall ─────────────────────────────────────────────────────────────────
do_uninstall() {
    info "Uninstalling $APP_NAME..."

    if is_root; then
        rm -rf "$SYS_VENV_DIR"
        rm -f "$SYS_BIN_DIR/git-ssh-helper"
        rm -f /usr/share/applications/${DESKTOP_ID}.desktop
        rm -f /usr/share/icons/hicolor/scalable/apps/git-ssh-helper.svg
        rm -f /usr/share/icons/hicolor/48x48/apps/git-ssh-helper.png
        command -v update-icon-caches >/dev/null 2>&1 \
            && update-icon-caches /usr/share/icons/hicolor 2>/dev/null || true
        command -v update-desktop-database >/dev/null 2>&1 \
            && update-desktop-database /usr/share/applications 2>/dev/null || true
    else
        # pipx uninstall (silent if not installed that way)
        if command -v pipx >/dev/null 2>&1; then
            pipx uninstall git-ssh-helper 2>/dev/null || true
            pipx uninstall ssh-tunnel     2>/dev/null || true
        fi
        # venv uninstall
        rm -rf "$USER_VENV_DIR"
        rm -f "$USER_BIN_DIR/git-ssh-helper"
        rm -f "$USER_DATA_DIR/applications/${DESKTOP_ID}.desktop"
        rm -f "$USER_DATA_DIR/icons/hicolor/scalable/apps/git-ssh-helper.svg"
        rm -f "$USER_DATA_DIR/icons/hicolor/48x48/apps/git-ssh-helper.png"
        command -v update-desktop-database >/dev/null 2>&1 \
            && update-desktop-database "$USER_DATA_DIR/applications" 2>/dev/null || true
    fi

    ok "Uninstall complete."
    exit 0
}

# ── install via pipx (user only) ──────────────────────────────────────────────
try_pipx() {
    command -v pipx >/dev/null 2>&1 || return 1
    info "pipx found — using pipx install"
    pipx install "$SCRIPT_DIR" --force
    ok "Installed via pipx"
    return 0
}

# ── install via venv ──────────────────────────────────────────────────────────
install_venv() {
    local venv_dir bin_dir launcher

    if is_root; then
        venv_dir="$SYS_VENV_DIR"
        bin_dir="$SYS_BIN_DIR"
    else
        venv_dir="$USER_VENV_DIR"
        bin_dir="$USER_BIN_DIR"
    fi

    info "Creating venv at $venv_dir..."
    python3 -m venv "$venv_dir" \
        || die "python3-venv not available. Install: sudo apt install python3-venv python3-full"

    info "Installing package into venv..."
    "$venv_dir/bin/pip" install --quiet "$SCRIPT_DIR"
    ok "Package installed into venv"

    # Create a thin wrapper in bin_dir that delegates to the venv's binary
    mkdir -p "$bin_dir"
    launcher="$bin_dir/git-ssh-helper"
    cat > "$launcher" <<WRAPPER
#!/bin/sh
exec "$venv_dir/bin/git-ssh-helper" "\$@"
WRAPPER
    chmod 0755 "$launcher"
    ok "Launcher created: $launcher"

    # PATH warning for user installs
    if ! is_root && [[ ":${PATH}:" != *":${bin_dir}:"* ]]; then
        warn "$bin_dir is not in your PATH."
        warn "Add to your shell profile (~/.bashrc or ~/.zshrc):"
        warn "  export PATH=\"$bin_dir:\$PATH\""
        warn "Then reload: source ~/.bashrc"
    fi
}

# ── install icon ──────────────────────────────────────────────────────────────
install_icon() {
    local icon_dir_svg icon_dir_png

    if is_root; then
        icon_dir_svg="/usr/share/icons/hicolor/scalable/apps"
        icon_dir_png="/usr/share/icons/hicolor/48x48/apps"
    else
        icon_dir_svg="$USER_DATA_DIR/icons/hicolor/scalable/apps"
        icon_dir_png="$USER_DATA_DIR/icons/hicolor/48x48/apps"
    fi

    mkdir -p "$icon_dir_svg" "$icon_dir_png"

    if [[ -f "$ICON_SRC" ]]; then
        cp "$ICON_SRC" "$icon_dir_svg/git-ssh-helper.svg"
        ok "SVG icon → $icon_dir_svg/git-ssh-helper.svg"

        if command -v rsvg-convert >/dev/null 2>&1; then
            rsvg-convert -w 48 -h 48 "$ICON_SRC" -o "$icon_dir_png/git-ssh-helper.png"
            ok "PNG icon → $icon_dir_png/git-ssh-helper.png"
        elif command -v inkscape >/dev/null 2>&1; then
            inkscape "$ICON_SRC" --export-width=48 \
                --export-filename="$icon_dir_png/git-ssh-helper.png" 2>/dev/null
            ok "PNG icon → $icon_dir_png/git-ssh-helper.png"
        else
            warn "rsvg-convert / inkscape not found — PNG icon skipped (SVG only)"
            warn "Install: sudo apt install librsvg2-bin"
        fi
    else
        warn "Icon not found at $ICON_SRC — skipping"
    fi

    if is_root; then
        command -v update-icon-caches >/dev/null 2>&1 \
            && update-icon-caches /usr/share/icons/hicolor 2>/dev/null || true
        command -v gtk-update-icon-cache >/dev/null 2>&1 \
            && gtk-update-icon-cache -f -t /usr/share/icons/hicolor 2>/dev/null || true
    else
        local xdg_data="${XDG_DATA_HOME:-$HOME/.local/share}"
        command -v gtk-update-icon-cache >/dev/null 2>&1 \
            && gtk-update-icon-cache -f -t "$USER_DATA_DIR/icons/hicolor" 2>/dev/null || true
    fi
}

# ── install .desktop entry ────────────────────────────────────────────────────
install_desktop_entry() {
    local desktop_dir

    if is_root; then
        desktop_dir="/usr/share/applications"
    else
        desktop_dir="$USER_DATA_DIR/applications"
    fi

    mkdir -p "$desktop_dir"

    cat > "$desktop_dir/${DESKTOP_ID}.desktop" <<'DESKEOF'
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
DESKEOF

    ok "Desktop entry → $desktop_dir/${DESKTOP_ID}.desktop"
    command -v update-desktop-database >/dev/null 2>&1 \
        && update-desktop-database "$desktop_dir" 2>/dev/null || true
}

# ── main ──────────────────────────────────────────────────────────────────────
main() {
    echo ""
    echo "  git-ssh-helper installer"
    echo "  ========================"
    echo ""

    [[ "${1:-}" == "--uninstall" ]] && do_uninstall

    check_python
    check_git
    check_gtk

    if is_root; then
        info "Running as root — system-wide install via venv → $SYS_VENV_DIR"
        install_venv
    else
        info "Running as user — trying pipx first, then venv"
        try_pipx || install_venv
    fi

    install_icon
    install_desktop_entry

    echo ""
    ok "Installation complete!"
    echo ""
    echo "  Run:  git-ssh-helper --ui         (GUI/TUI mode)"
    echo "  Run:  git-ssh-helper --list-keys   (list SSH keys)"
    echo "  Run:  git-ssh-helper --help        (all options)"
    echo "  Uninstall: ./install.sh --uninstall"
    echo ""
}

main "$@"
