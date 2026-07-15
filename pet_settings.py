"""Persistent user settings and XDG autostart integration for Pixel Pet."""

from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy


DEFAULTS = {
    "pet": "catbone",
    "size_percent": 100,
    "pointer_tracking": True,
    "typing_reactions": True,
    "petting_reactions": True,
    "typing_hold_seconds": 2.0,
    "paused": False,
    "launch_at_login": False,
    "position": None,
}


def _config_home():
    return os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")


def settings_path():
    return os.path.join(_config_home(), "pixel-pet", "settings.json")


def autostart_path():
    return os.path.join(_config_home(), "autostart", "pixel-pet.desktop")


def _clamp_number(value, low, high, fallback):
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return fallback


def normalize(raw):
    data = deepcopy(DEFAULTS)
    if not isinstance(raw, dict):
        return data
    data["pet"] = "catbone"
    data["size_percent"] = int(round(
        _clamp_number(raw.get("size_percent"), 75, 200, 100) / 25
    ) * 25)
    data["pointer_tracking"] = bool(raw.get("pointer_tracking", True))
    data["typing_reactions"] = bool(raw.get("typing_reactions", True))
    data["petting_reactions"] = bool(raw.get("petting_reactions", True))
    data["typing_hold_seconds"] = round(
        _clamp_number(raw.get("typing_hold_seconds"), 0, 5, 2) * 2
    ) / 2
    data["paused"] = bool(raw.get("paused", False))
    data["launch_at_login"] = bool(raw.get("launch_at_login", False))
    pos = raw.get("position")
    if isinstance(pos, dict):
        try:
            x, y = float(pos["x"]), float(pos["y"])
            data["position"] = {
                "x": max(0.0, min(1.0, x)),
                "y": max(0.0, min(1.0, y)),
            }
        except (KeyError, TypeError, ValueError):
            pass
    return data


class SettingsStore:
    def __init__(self, path=None):
        self.path = path or settings_path()
        self.first_run = not os.path.exists(self.path)
        self.data = self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as handle:
                return normalize(json.load(handle))
        except (OSError, ValueError):
            return deepcopy(DEFAULTS)

    def get(self, key):
        return self.data[key]

    def update(self, key, value):
        previous = deepcopy(self.data)
        candidate = dict(self.data)
        candidate[key] = value
        self.data = normalize(candidate)
        try:
            self.save()
        except Exception:
            self.data = previous
            raise
        return self.data[key]

    def prepare(self, key, value):
        candidate = dict(self.data)
        candidate[key] = value
        return normalize(candidate)

    def adopt(self, snapshot):
        self.data = normalize(snapshot)

    def reset(self):
        previous = deepcopy(self.data)
        self.data = deepcopy(DEFAULTS)
        try:
            self.save()
        except Exception:
            self.data = previous
            raise

    def save(self):
        self.persist_snapshot(self.data)
        self.first_run = False

    def persist_snapshot(self, snapshot):
        snapshot = normalize(snapshot)
        directory = os.path.dirname(self.path)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="settings-", suffix=".json", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(snapshot, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise


def _desktop_exec(path):
    escaped = os.path.abspath(path).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}" --background'


def set_launch_at_login(enabled, launcher_path):
    path = autostart_path()
    if not enabled:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        return

    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    content = "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Name=Pixel Pet",
        "Comment=Start the Pixel Pet desktop companion",
        f"Exec={_desktop_exec(launcher_path)}",
        "Terminal=false",
        "X-GNOME-Autostart-enabled=true",
        "",
    ])
    fd, temporary = tempfile.mkstemp(prefix="pixel-pet-", suffix=".desktop", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
