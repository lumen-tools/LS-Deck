#!/bin/sh
# Builds release/LS-Deck.zip, the file to install with Decky ("Install plugin from ZIP").
# Needs everything scripts/build-engine.sh needs, plus Node.js and pnpm.
set -eu
here="$(cd "$(dirname "$0")/.." && pwd)"
cd "$here"

./scripts/build-engine.sh
pnpm install --frozen-lockfile
pnpm run build

out="$here/release"
stage="$(mktemp -d)"
mkdir -p "$stage/LS-Deck/dist" "$out"
cp dist/index.js "$stage/LS-Deck/dist/"
cp -r bin main.py plugin.json package.json LICENSE README.md THIRD_PARTY.md "$stage/LS-Deck/"
rm -f "$out/LS-Deck.zip"
(cd "$stage" && zip -qr "$out/LS-Deck.zip" LS-Deck)
rm -rf "$stage"
echo "release: $out/LS-Deck.zip"
