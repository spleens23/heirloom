#!/usr/bin/env bash
# Harbor installer for Fedora (GNOME).   Run from this folder:  bash install.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
PREFIX="$DATA/harbor"
BIN="$HOME/.local/bin"
APP_ID="dev.harbor.Harbor"

say() { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }

say "Checking system packages (you may be asked for your password)"
if command -v dnf >/dev/null 2>&1; then
  sudo dnf install -y python3 python3-gobject gtk4 libadwaita
else
  echo "This script expects Fedora. Make sure python3, PyGObject, GTK 4 and libadwaita are installed."
fi

say "Copying Harbor"
mkdir -p "$PREFIX" "$BIN"
rm -rf "$PREFIX/app"
mkdir -p "$PREFIX/app"
cp -r "$HERE/harbor" "$PREFIX/app/"
find "$PREFIX/app" -name '__pycache__' -prune -exec rm -rf {} +

say "Creating the 'harbor' command"
cat > "$BIN/harbor" <<EOF
#!/usr/bin/env bash
# Opens Harbor, or brings it back to the front if it's already running.
export PYTHONPATH="$PREFIX/app\${PYTHONPATH:+:\$PYTHONPATH}"
exec python3 -m harbor "\$@"
EOF
chmod +x "$BIN/harbor"

say "Adding Harbor to your app grid"
mkdir -p "$DATA/applications" "$DATA/icons/hicolor/scalable/apps"
sed "s|@LAUNCHER@|$BIN/harbor|" "$HERE/data/$APP_ID.desktop" > "$DATA/applications/$APP_ID.desktop"
cp "$HERE/data/$APP_ID.svg" "$DATA/icons/hicolor/scalable/apps/$APP_ID.svg"
gtk-update-icon-cache -f -t "$DATA/icons/hicolor" >/dev/null 2>&1 || true
update-desktop-database "$DATA/applications" >/dev/null 2>&1 || true

say "Installing the Tablet Mode extension for GNOME"
EXT_UUID="harbor-tablet@harbor.dev"
EXT_DIR="$DATA/gnome-shell/extensions/$EXT_UUID"
rm -rf "$EXT_DIR"
mkdir -p "$(dirname "$EXT_DIR")"
cp -r "$HERE/shell-extension/$EXT_UUID" "$EXT_DIR"
# Turn it on (it takes effect the next time you log in).
if command -v gsettings >/dev/null 2>&1; then
  current="$(gsettings get org.gnome.shell enabled-extensions 2>/dev/null || echo '@as []')"
  if [[ "$current" != *"$EXT_UUID"* ]]; then
    updated="$(python3 -c 'import ast,sys; s=sys.argv[1].replace("@as ",""); l=ast.literal_eval(s) if s.strip() else []; l.append(sys.argv[2]); print(l)' "$current" "$EXT_UUID")"
    gsettings set org.gnome.shell enabled-extensions "$updated" || true
  fi
  gsettings set org.gnome.shell disable-user-extensions false || true
fi

say "Done! Log out and back in to turn on Tablet Mode."
echo "   Fold the screen back and Harbor becomes your home screen. Tablet Mode also"
echo "   has a switch in Quick Settings (top-right corner) to force it on or off."
