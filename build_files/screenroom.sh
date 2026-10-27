#!/usr/bin/env bash
# Puts Screenroom (films and TV) and Parlor (music) into the image. Both are the same app
# (github.com/spleens23/screenroom) started in a different edition, so one copy serves both.
#
# The build workflow downloads the newest Screenroom release into apps/screenroom/dist first.
# Building by hand without it, this script fetches the newest release itself.
set -euxo pipefail
CTX=/ctx
DEST=/usr/lib/screenroom
TARBALL="$CTX/apps/screenroom/dist/screenroom-linux-x64.tar.gz"
TMP="$(mktemp -d)"

if [ ! -f "$TARBALL" ]; then
    url="$(curl -fsSL 'https://api.github.com/repos/spleens23/screenroom/releases?per_page=40' \
        | python3 -c 'import json,sys
for r in json.load(sys.stdin):
    if r["tag_name"].startswith("linux-") and not r["draft"]:
        for a in r["assets"]:
            if a["name"] == "screenroom-linux-x64.tar.gz":
                print(a["browser_download_url"]); raise SystemExit')"
    [ -n "$url" ] || { echo "No Screenroom release with screenroom-linux-x64.tar.gz found" >&2; exit 1; }
    curl -fsSL -o "$TMP/screenroom.tar.gz" "$url"
    TARBALL="$TMP/screenroom.tar.gz"
fi

rm -rf "$DEST"
mkdir -p "$DEST"
tar -xzf "$TARBALL" -C "$DEST" --strip-components=1
test -x "$DEST/screenroom"
# Chromium's sandbox helper must be owned by root and setuid.
chown root:root "$DEST/chrome-sandbox"
chmod 4755 "$DEST/chrome-sandbox"
rm -rf "$TMP"

install -Dm755 "$CTX/system_files/usr/bin/screenroom" /usr/bin/screenroom
install -Dm755 "$CTX/system_files/usr/bin/parlor" /usr/bin/parlor
for id in dev.screenroom.Screenroom:screenroom dev.screenroom.Parlor:parlor; do
    IFS=: read -r app cmd <<< "$id"
    sed "s|@LAUNCHER@|/usr/bin/$cmd|" "$CTX/apps/screenroom/data/$app.desktop" > "/usr/share/applications/$app.desktop"
    install -Dm644 "$CTX/apps/screenroom/data/$app.svg" "/usr/share/icons/hicolor/scalable/apps/$app.svg"
done
