#!/usr/bin/env bash
# Removes Spectacle. Your downloaded videos in ~/Videos/Spectacle are kept.
set -euo pipefail
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
read -rp "Also delete your subscriptions and Watch Later list? [y/N] " wipe
rm -rf "$DATA/spectacle/app" "$DATA/spectacle/venv"
[[ "$wipe" == [yY]* ]] && rm -rf "$DATA/spectacle"
rm -f "$HOME/.local/bin/spectacle" \
      "$DATA/applications/dev.spectacle.Spectacle.desktop" \
      "$DATA/icons/hicolor/scalable/apps/dev.spectacle.Spectacle.svg"
rm -rf "${XDG_CACHE_HOME:-$HOME/.cache}/spectacle"
echo "Spectacle removed."
