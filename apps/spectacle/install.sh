#!/usr/bin/env bash
# Spectacle installer for Fedora (Workstation / GNOME).
# Run from inside the Spectacle folder:   bash install.sh
# Safe to run again any time — it also updates yt-dlp.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
PREFIX="$DATA/spectacle"
VENV="$PREFIX/venv"
BIN="$HOME/.local/bin"
APP_ID="dev.spectacle.Spectacle"

say() { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }

say "Installing system packages (you'll be asked for your password)"
if command -v dnf >/dev/null 2>&1; then
  sudo dnf install -y python3 python3-gobject gtk4 libadwaita mpv mpv-libs ffmpeg-free
else
  echo "This script expects Fedora. On another distro, install: python3, PyGObject,"
  echo "GTK 4, libadwaita, mpv (with libmpv) and ffmpeg — then run this again."
  read -rp "Continue anyway? [y/N] " ok; [[ "$ok" == [yY]* ]] || exit 1
fi

say "Setting up Spectacle's private Python environment"
mkdir -p "$PREFIX" "$BIN"
# --system-site-packages lets the environment use Fedora's GTK bindings.
[ -x "$VENV/bin/python" ] || python3 -m venv --system-site-packages "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet --upgrade yt-dlp mpv

say "Copying the app"
rm -rf "$PREFIX/app"
mkdir -p "$PREFIX/app"
cp -r "$HERE/spectacle" "$PREFIX/app/"
find "$PREFIX/app" -name '__pycache__' -prune -exec rm -rf {} +

say "Creating the 'spectacle' command"
cat > "$BIN/spectacle" <<EOF
#!/usr/bin/env bash
# Launch Spectacle.  'spectacle update' refreshes yt-dlp when YouTube changes.
if [ "\${1:-}" = "update" ]; then
  exec "$VENV/bin/pip" install --upgrade yt-dlp
fi
export PYTHONPATH="$PREFIX/app\${PYTHONPATH:+:\$PYTHONPATH}"
exec "$VENV/bin/python" -m spectacle "\$@"
EOF
chmod +x "$BIN/spectacle"

say "Adding Spectacle to your app grid"
mkdir -p "$DATA/applications" "$DATA/icons/hicolor/scalable/apps"
sed "s|@LAUNCHER@|$BIN/spectacle|" "$HERE/data/$APP_ID.desktop" > "$DATA/applications/$APP_ID.desktop"
cp "$HERE/data/$APP_ID.svg" "$DATA/icons/hicolor/scalable/apps/$APP_ID.svg"
gtk-update-icon-cache -f -t "$DATA/icons/hicolor" >/dev/null 2>&1 || true
update-desktop-database "$DATA/applications" >/dev/null 2>&1 || true

say "Done! Open Spectacle from your app grid, or type: spectacle"
echo "   Preview the design offline with:  SPECTACLE_DEMO=1 spectacle"
echo "   If videos stop loading someday:   spectacle update"
