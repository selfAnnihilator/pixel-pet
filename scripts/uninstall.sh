#!/bin/sh
set -eu

PURGE=false
case "${1:-}" in
    "") ;;
    --purge) PURGE=true ;;
    *) printf 'Usage: pixel-pet uninstall [--purge]\n' >&2; exit 2 ;;
esac

DATA_HOME=${XDG_DATA_HOME:-"$HOME/.local/share"}
BIN_HOME=${XDG_BIN_HOME:-"$HOME/.local/bin"}
CONFIG_HOME=${XDG_CONFIG_HOME:-"$HOME/.config"}
APPLICATIONS_DIR="$DATA_HOME/applications"

if command -v pgrep >/dev/null 2>&1; then
    for pid in $(pgrep -f "$DATA_HOME/pixel-pet/pet.py" || true); do
        kill "$pid" 2>/dev/null || true
    done
fi

rm -rf "$DATA_HOME/pixel-pet"
rm -f "$BIN_HOME/pixel-pet"
rm -f "$APPLICATIONS_DIR/com.abhi.pixelpet.desktop"
rm -f "$DATA_HOME/icons/hicolor/64x64/apps/com.abhi.pixelpet.png"
rm -f "$CONFIG_HOME/autostart/pixel-pet.desktop"
if "$PURGE"; then
    rm -rf "$CONFIG_HOME/pixel-pet"
fi

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPLICATIONS_DIR" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$DATA_HOME/icons/hicolor" >/dev/null 2>&1 || true
fi

if "$PURGE"; then
    printf 'Uninstalled Pixel Pet and removed its settings.\n'
else
    printf 'Uninstalled Pixel Pet. Settings remain in %s/pixel-pet.\n' "$CONFIG_HOME"
fi
