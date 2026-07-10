# Pixel Pet

Pixel Pet is a pixel-art desktop companion for Wayland. Catbone lives in a
transparent screen overlay, looks toward the pointer, reacts to typing, and can
be dragged anywhere on screen.

The GTK4/Libadwaita Pet Controller provides live configuration without command
line flags or environment variables.

## Run

```bash
./run-pet.sh
```

The first launch opens the Pet Controller and starts Catbone. Closing the
controller keeps the companion running. Run `./run-pet.sh` again to reopen the
existing controller. Use **Quit Pixel Pet** to stop both.

Start without opening the controller:

```bash
./run-pet.sh --background
```

## Settings

- Pet size from 75% to 200%
- Pointer tracking
- Typing reactions
- Typing Hold from 0 to 5 seconds
- Pause or resume
- Reset screen position
- Launch at login through XDG autostart
- Restore defaults

Settings apply immediately and persist in:

```text
${XDG_CONFIG_HOME:-~/.config}/pixel-pet/settings.json
```

## Requirements

- Python 3
- GTK4 and PyGObject
- Libadwaita 1
- gtk4-layer-shell
- A wlroots Wayland compositor such as niri, sway, or Hyprland

`run-pet.sh` locates and preloads `libgtk4-layer-shell.so` before starting the
app.

### Global input access

Pointer tracking and typing reactions read Linux evdev devices so the overlay
never needs keyboard focus. Your account must be able to read `/dev/input`.

The controller detects missing access and provides this setup command:

```bash
sudo usermod -aG input "$USER"
```

Sign out and back in after changing group membership, then select **Recheck**.
Pixel Pet never runs `sudo` itself.

## Behavior

- Pointer movement selects one of nine Catbone look directions.
- Every physical keydown alternates the typing paw.
- A held key holds the pressed-paw pose.
- Releasing the final key returns to the ready pose for the configured Typing
  Hold duration.
- Dragging overrides typing and shows the held wobble animation.
- Fullscreen apps temporarily hide the overlay.

## Project layout

- `pet.py`: overlay runtime, input tracking, and application lifecycle
- `pet_controller.py`: GTK4/Libadwaita Pet Controller
- `pet_settings.py`: persistent settings and XDG autostart
- `assets/catbone/`: tracking, drag, and typing sprite sheets
- `PRODUCT.md` / `DESIGN.md`: product and visual direction
- `CONTEXT.md`: canonical behavior language
- `context.md`: implementation history and operational notes

## Credits

Cat artwork includes assets derived from work by Artoellie. Check the artist's
license before redistributing art.

## License

Code: MIT. Art: © Artoellie, per the artist's terms.
