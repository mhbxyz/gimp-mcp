#!/usr/bin/env bash
# Installs GIMP from gimp.org's DMG on a macOS runner: pinned version, SHA-256 verified (ADR 0008).
set -euo pipefail
VERSION=3.2.6
ARCH=$(uname -m)  # arm64 or x86_64
case "$ARCH" in
  arm64) SHA256=854573aec2be6a185aa021109c3c0ca94f210379204b704231bdd191b4060294 ;;
  x86_64) SHA256=ebe633642445d4d6fc6b68e7be7ca581c0b28c18dc9de7747849528c982e5677 ;;
  *) echo "unsupported architecture $ARCH" >&2; exit 1 ;;
esac
dmg="$(mktemp -d)/gimp.dmg"
curl -fsSL -o "$dmg" "https://download.gimp.org/gimp/v3.2/macos/gimp-$VERSION-$ARCH.dmg"
echo "$SHA256  $dmg" | shasum -a 256 -c
mount=$(mktemp -d)
hdiutil attach "$dmg" -nobrowse -readonly -mountpoint "$mount" >/dev/null
cp -R "$mount/GIMP.app" /Applications/
hdiutil detach "$mount" >/dev/null
/Applications/GIMP.app/Contents/MacOS/gimp-console-3.2 --version
