#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
DATA_HOME=${XDG_DATA_HOME:-"$HOME/.local/share"}
BIN_HOME=${XDG_BIN_HOME:-"$HOME/.local/bin"}
APP_DIR="$DATA_HOME/pixel-pet"
APPLICATIONS_DIR="$DATA_HOME/applications"
ICON_DIR="$DATA_HOME/icons/hicolor/64x64/apps"
DESKTOP_FILE="$APPLICATIONS_DIR/com.abhi.pixelpet.desktop"
COMMAND_FILE="$BIN_HOME/pixel-pet"

mkdir -p "$APP_DIR/scripts" "$APPLICATIONS_DIR" "$ICON_DIR" "$BIN_HOME"

for file in \
    pet.py pet_behavior.py pet_controller.py pet_settings.py process_identity.py \
    behavior_input.py behavior_scheduler.py niri_monitor.py live_settings.py \
    pixel_pet_manager.py companion_presentation.py run-pet.sh VERSION README.md \
    PRODUCT.md DESIGN.md CONTEXT.md
do
    install -m 0644 "$PROJECT_DIR/$file" "$APP_DIR/$file"
done
chmod 0755 "$APP_DIR/run-pet.sh" "$APP_DIR/pet.py"
install -m 0755 "$PROJECT_DIR/scripts/uninstall.sh" "$APP_DIR/scripts/uninstall.sh"

rm -rf "$APP_DIR/assets"
cp -R "$PROJECT_DIR/assets" "$APP_DIR/assets"

cat >"$COMMAND_FILE" <<EOF
#!/bin/sh
case "\${1:-}" in
    version|update)
        exec python3 "$APP_DIR/pixel_pet_manager.py" "\$@"
        ;;
    help|--help|-h)
        exec python3 "$APP_DIR/pixel_pet_manager.py" --help
        ;;
    uninstall)
        shift
        exec "$APP_DIR/scripts/uninstall.sh" "\$@"
        ;;
    *)
        exec "$APP_DIR/run-pet.sh" "\$@"
        ;;
esac
EOF
chmod 0755 "$COMMAND_FILE"

install -m 0644 \
    "$PROJECT_DIR/assets/catbone/icon.png" \
    "$ICON_DIR/com.abhi.pixelpet.png"

cat >"$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=Pixel Pet
GenericName=Desktop Companion
Comment=A quiet pixel-art companion for your desktop
Exec="$COMMAND_FILE"
TryExec=$COMMAND_FILE
Icon=com.abhi.pixelpet
Terminal=false
Categories=Utility;
Keywords=pet;cat;companion;pixel;desktop;
StartupNotify=true
StartupWMClass=com.abhi.pixelpet
Actions=Background;

[Desktop Action Background]
Name=Start in Background
Exec="$COMMAND_FILE" --background
EOF
chmod 0644 "$DESKTOP_FILE"

if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "$DESKTOP_FILE"
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPLICATIONS_DIR" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$DATA_HOME/icons/hicolor" >/dev/null 2>&1 || true
fi

printf 'Installed Pixel Pet. Launch it from your app launcher or run: %s\n' "$COMMAND_FILE"
printf 'See available commands with: %s --help\n' "$COMMAND_FILE"
if command -v pgrep >/dev/null 2>&1 \
    && pgrep -f "$APP_DIR/pet.py" >/dev/null 2>&1
then
    printf 'Pixel Pet is already running. Quit and relaunch it to load this update.\n'
fi
case ":${PATH:-}:" in
    *":$BIN_HOME:"*) ;;
    *) printf 'Note: add %s to PATH to use the pixel-pet command directly.\n' "$BIN_HOME" ;;
esac
