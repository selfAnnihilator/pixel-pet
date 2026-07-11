#!/bin/sh
set -eu

RELEASE_API=${PIXEL_PET_RELEASE_API:-https://api.github.com/repos/selfAnnihilator/pixel-pet/releases/latest}

for command in curl python3 tar; do
    if ! command -v "$command" >/dev/null 2>&1; then
        printf 'Pixel Pet installer requires %s.\n' "$command" >&2
        exit 1
    fi
done

TEMPORARY=$(mktemp -d -t pixel-pet-install-XXXXXX)
trap 'rm -rf "$TEMPORARY"' EXIT HUP INT TERM

curl -fsSL -H 'Accept: application/vnd.github+json' \
    -H 'User-Agent: pixel-pet-installer' \
    "$RELEASE_API" >"$TEMPORARY/release.json"
TARBALL_URL=$(python3 -c \
    'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["tarball_url"])' \
    "$TEMPORARY/release.json")
curl -fsSL -H 'User-Agent: pixel-pet-installer' \
    "$TARBALL_URL" >"$TEMPORARY/release.tar.gz"
mkdir "$TEMPORARY/source"
tar -xzf "$TEMPORARY/release.tar.gz" -C "$TEMPORARY/source"

set -- "$TEMPORARY"/source/*
if [ "$#" -ne 1 ] || [ ! -x "$1/scripts/install.sh" ]; then
    printf 'Downloaded release does not contain the Pixel Pet installer.\n' >&2
    exit 1
fi
exec "$1/scripts/install.sh"
