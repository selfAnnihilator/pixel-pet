#!/bin/sh
# Launch the layer-shell pet. gtk4-layer-shell must be loaded before libwayland,
# so it's preloaded here (see https://github.com/wmww/gtk4-layer-shell/blob/main/linking.md).
HERE="$(cd "$(dirname "$0")" && pwd)"
PRELOAD="$(ldconfig -p | awk '/libgtk4-layer-shell\.so /{print $NF; exit}')"
exec env LD_PRELOAD="$PRELOAD" python3 "$HERE/pet.py" "$@"
