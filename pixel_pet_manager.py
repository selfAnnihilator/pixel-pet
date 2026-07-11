#!/usr/bin/env python3
"""Installed Pixel Pet lifecycle commands."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import urllib.request
import sys


APP_DIR = Path(__file__).resolve().parent
VERSION_FILE = APP_DIR / "VERSION"
RELEASE_API = os.environ.get(
    "PIXEL_PET_RELEASE_API",
    "https://api.github.com/repos/selfAnnihilator/pixel-pet/releases/latest",
)

HELP_TEXT = """Usage: pixel-pet [COMMAND] [OPTIONS]

Commands:
  pixel-pet                       Open Pixel Pet
  pixel-pet --background          Start without opening the controller
  pixel-pet version               Show the installed version
  pixel-pet update --check        Check for a stable update
  pixel-pet update                Install the latest stable update
  pixel-pet uninstall             Remove the app and preserve settings
  pixel-pet uninstall --purge     Remove the app and settings
  pixel-pet --help                Show this help
"""


@dataclass(frozen=True)
class Release:
    version: str
    tarball_url: str


def installed_version() -> str:
    return VERSION_FILE.read_text(encoding="utf-8").strip()


def version_key(version: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", version.strip())
    if match is None:
        raise ValueError(f"invalid stable version: {version}")
    return tuple(map(int, match.groups()))


def latest_release() -> Release:
    request = urllib.request.Request(
        RELEASE_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "pixel-pet"},
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.load(response)
    version = str(payload["tag_name"]).removeprefix("v")
    version_key(version)
    return Release(version=version, tarball_url=str(payload["tarball_url"]))


def install_release(release: Release) -> None:
    with tempfile.TemporaryDirectory(prefix="pixel-pet-update-") as temporary:
        temporary_path = Path(temporary)
        archive_path = temporary_path / "release.tar.gz"
        request = urllib.request.Request(
            release.tarball_url,
            headers={"User-Agent": "pixel-pet"},
        )
        with (
            urllib.request.urlopen(request, timeout=60) as response,
            archive_path.open("wb") as destination,
        ):
            while chunk := response.read(1024 * 1024):
                destination.write(chunk)
        with tarfile.open(archive_path, "r:gz") as archive:
            archive.extractall(temporary_path / "source", filter="data")
        installers = list((temporary_path / "source").glob("*/scripts/install.sh"))
        if len(installers) != 1:
            raise RuntimeError("release archive does not contain one Pixel Pet installer")
        source_root = installers[0].parents[1]
        archive_version = (source_root / "VERSION").read_text(encoding="utf-8").strip()
        if version_key(archive_version) != version_key(release.version):
            raise RuntimeError("release tag and archive VERSION do not match")
        subprocess.run([installers[0]], cwd=source_root, check=True)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments and arguments[0] in {"help", "--help", "-h"}:
        print(HELP_TEXT, end="")
        return 0

    parser = argparse.ArgumentParser(prog="pixel-pet")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("version")
    update = subcommands.add_parser("update")
    update.add_argument("--check", action="store_true")
    args = parser.parse_args(arguments)
    if args.command == "version":
        print(f"Pixel Pet {installed_version()}")
    elif args.command == "update":
        release = latest_release()
        current = installed_version()
        if version_key(release.version) > version_key(current):
            print(f"Pixel Pet {release.version} is available (installed: {current}).")
            if not args.check:
                install_release(release)
                print(
                    f"Updated Pixel Pet to {release.version}. "
                    "Quit and relaunch Pixel Pet to use it."
                )
        else:
            print(f"Pixel Pet {current} is up to date.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"pixel-pet: lifecycle command failed: {error}", file=sys.stderr)
        raise SystemExit(1)
