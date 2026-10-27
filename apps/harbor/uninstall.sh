#!/usr/bin/env bash
# Removes Harbor and its settings.
set -euo pipefail
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}"
rm -rf "$DATA/harbor" "$CONF/harbor"
rm -f "$HOME/.local/bin/harbor" \
      "$DATA/applications/dev.harbor.Harbor.desktop" \
      "$DATA/icons/hicolor/scalable/apps/dev.harbor.Harbor.svg" \
      "$CONF/autostart/dev.harbor.Harbor.desktop"
rm -rf "$DATA/gnome-shell/extensions/harbor-tablet@harbor.dev"
gnome-extensions disable harbor-tablet@harbor.dev >/dev/null 2>&1 || true
echo "Harbor removed. Log out and back in to finish."
