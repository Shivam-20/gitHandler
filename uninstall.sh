#!/usr/bin/env bash
# uninstall.sh — remove SSH Git Manager (git-ssh-helper) from this system
#
# Usage:
#   ./uninstall.sh          # remove user install
#   sudo ./uninstall.sh     # remove system-wide install
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="git-ssh-helper"
DESKTOP_ID="git-ssh-helper"

USER_VENV_DIR="$HOME/.local/lib/git-ssh-helper-venv"
USER_BIN_DIR="$HOME/.local/bin"
USER_DATA_DIR="$HOME/.local/share"   # always explicit — never $XDG_DATA_HOME
SYS_VENV_DIR="/opt/git-ssh-helper-venv"
SYS_BIN_DIR="/usr/local/bin"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; RESET='\033[0m'
info() { echo -e "${CYAN}[INFO]${RESET}  $*"; }
ok()   { echo -e "${GREEN}[ OK ]${RESET}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${RESET}  $*"; }

is_root() { [[ "$(id -u)" -eq 0 ]]; }

echo ""
echo "  SSH Git Manager — uninstaller"
echo "  =============================="
echo ""

if is_root; then
    info "System-wide uninstall..."

    # venv
    if [[ -d "$SYS_VENV_DIR" ]]; then
        rm -rf "$SYS_VENV_DIR"
        ok "Removed venv: $SYS_VENV_DIR"
    fi

    # binary
    if [[ -f "$SYS_BIN_DIR/$APP_NAME" ]]; then
        rm -f "$SYS_BIN_DIR/$APP_NAME"
        ok "Removed binary: $SYS_BIN_DIR/$APP_NAME"
    fi

    # desktop + icons
    rm -f "/usr/share/applications/${DESKTOP_ID}.desktop"
    rm -f "/usr/share/icons/hicolor/scalable/apps/${APP_NAME}.svg"
    rm -f "/usr/share/icons/hicolor/48x48/apps/${APP_NAME}.png"
    ok "Removed desktop entry and icons"

    command -v update-icon-caches >/dev/null 2>&1 \
        && update-icon-caches /usr/share/icons/hicolor 2>/dev/null || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 \
        && gtk-update-icon-cache -f -t /usr/share/icons/hicolor 2>/dev/null || true
    command -v update-desktop-database >/dev/null 2>&1 \
        && update-desktop-database /usr/share/applications 2>/dev/null || true

else
    info "User uninstall..."

    # pipx (handles both package names the tool may have been installed under)
    if command -v pipx >/dev/null 2>&1; then
        for _pkg in git-ssh-helper ssh-tunnel; do
            if pipx list 2>/dev/null | grep -q "$_pkg"; then
                pipx uninstall "$_pkg" 2>/dev/null && ok "pipx: removed $_pkg" || true
            fi
        done
    fi

    # venv
    if [[ -d "$USER_VENV_DIR" ]]; then
        rm -rf "$USER_VENV_DIR"
        ok "Removed venv: $USER_VENV_DIR"
    fi

    # binary wrapper (only if it points into our venv — don't remove a user's own file)
    if [[ -f "$USER_BIN_DIR/$APP_NAME" ]]; then
        if grep -q "git-ssh-helper-venv\|git-ssh-helper\|pipx" "$USER_BIN_DIR/$APP_NAME" 2>/dev/null; then
            rm -f "$USER_BIN_DIR/$APP_NAME"
            ok "Removed binary: $USER_BIN_DIR/$APP_NAME"
        else
            warn "Skipped $USER_BIN_DIR/$APP_NAME — doesn't look like our launcher"
        fi
    fi

    # desktop + icons
    rm -f "$USER_DATA_DIR/applications/${DESKTOP_ID}.desktop"
    rm -f "$USER_DATA_DIR/icons/hicolor/scalable/apps/${APP_NAME}.svg"
    rm -f "$USER_DATA_DIR/icons/hicolor/48x48/apps/${APP_NAME}.png"
    ok "Removed desktop entry and icons"

    command -v gtk-update-icon-cache >/dev/null 2>&1 \
        && gtk-update-icon-cache -f -t "$USER_DATA_DIR/icons/hicolor" 2>/dev/null || true
    command -v update-desktop-database >/dev/null 2>&1 \
        && update-desktop-database "$USER_DATA_DIR/applications" 2>/dev/null || true

    # user data (recent repos list etc.) — ask before removing
    USER_APP_DATA="$HOME/.local/share/git-ssh-helper"
    if [[ -d "$USER_APP_DATA" ]]; then
        read -r -p "  Remove app data ($USER_APP_DATA)? [y/N] " _ans
        if [[ "${_ans,,}" == "y" ]]; then
            rm -rf "$USER_APP_DATA"
            ok "Removed app data: $USER_APP_DATA"
        else
            info "Kept app data: $USER_APP_DATA"
        fi
    fi
fi

echo ""
ok "Uninstall complete."
echo ""
