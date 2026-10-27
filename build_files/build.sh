#!/usr/bin/env bash
# Builds Heirloom on top of Fedora Silverblue. Runs inside the image build.
set -euxo pipefail

CTX=/ctx
LIB=/usr/lib/heirloom

# ---- 1. system packages ------------------------------------------------------
# mpv plays video inside Spectacle; ffmpeg merges downloads into one file.
# Fedora's default codecs cover VP9/AV1/Opus, which is what Spectacle prefers.
dnf5 install -y \
    mpv mpv-libs ffmpeg-free \
    python3-pip
dnf5 clean all

# ---- 2. Heirloom's apps ----------------------------------------------------------
mkdir -p "$LIB"
cp -r "$CTX/apps/spectacle/spectacle" "$LIB/"
cp -r "$CTX/apps/harbor/harbor" "$LIB/"
cp -r "$CTX/apps/updates/heirloom_updates" "$LIB/"

# Spectacle's helpers (yt-dlp and the mpv bindings) live in their own Python
# environment. The image is rebuilt daily, so yt-dlp stays current.
python3 -m venv --system-site-packages "$LIB/venv"
"$LIB/venv/bin/pip" install --no-cache-dir --upgrade yt-dlp mpv
# The venv must not depend on the build's /tmp or caches.
find "$LIB" -name '__pycache__' -prune -exec rm -rf {} +

install -Dm755 "$CTX/system_files/usr/bin/spectacle" /usr/bin/spectacle
install -Dm755 "$CTX/system_files/usr/bin/harbor" /usr/bin/harbor
install -Dm755 "$CTX/system_files/usr/bin/heirloom-updates" /usr/bin/heirloom-updates

# folder : app id : command
for app in spectacle:dev.spectacle.Spectacle:spectacle \
           harbor:dev.harbor.Harbor:harbor \
           updates:dev.heirloom.Updates:heirloom-updates; do
    IFS=: read -r dir id cmd <<< "$app"
    sed "s|@LAUNCHER@|/usr/bin/$cmd|" "$CTX/apps/$dir/data/$id.desktop" \
        > "/usr/share/applications/$id.desktop"
    install -Dm644 "$CTX/apps/$dir/data/$id.svg" "/usr/share/icons/hicolor/scalable/apps/$id.svg"
done

# Tablet Mode extension, installed for everyone.
cp -r "$CTX/apps/harbor/shell-extension/harbor-tablet@harbor.dev" \
    /usr/share/gnome-shell/extensions/

# ---- 3. look, defaults and branding ----------------------------------------------
cp -r "$CTX/system_files/etc/." /etc/
[ -d "$CTX/system_files/usr/share" ] && cp -r "$CTX/system_files/usr/share/." /usr/share/
install -Dm644 "$CTX/apps/harbor/harbor/wallpaper.svg" /usr/share/backgrounds/heirloom/sky.svg
dconf update

# Name the system Heirloom (keeping Fedora's ID so updates and tools still work).
sed -i \
    -e 's/^NAME=.*/NAME="Heirloom"/' \
    -e "s/^PRETTY_NAME=.*/PRETTY_NAME=\"Heirloom (Fedora ${FEDORA_VERSION})\"/" \
    -e 's/^VARIANT=.*/VARIANT="Heirloom"/' \
    -e 's/^VARIANT_ID=.*/VARIANT_ID=heirloom/' \
    /usr/lib/os-release
grep -q '^HOME_URL=' /usr/lib/os-release && \
    sed -i 's|^HOME_URL=.*|HOME_URL="https://github.com/spleens23/heirloom"|' /usr/lib/os-release

# ---- 4. first-boot jobs ---------------------------------------------------------------
install -Dm755 "$CTX/system_files/usr/libexec/heirloom-first-boot" /usr/libexec/heirloom-first-boot
install -Dm644 "$CTX/system_files/usr/lib/systemd/system/heirloom-first-boot.service" \
    /usr/lib/systemd/system/heirloom-first-boot.service
systemctl enable heirloom-first-boot.service

# ---- 5. updates --------------------------------------------------------------------
install -Dm755 "$CTX/system_files/usr/bin/heirloom-update" /usr/bin/heirloom-update
install -Dm644 "$CTX/system_files/usr/lib/systemd/system/heirloom-track-github.service" \
    /usr/lib/systemd/system/heirloom-track-github.service
systemctl enable heirloom-track-github.service

# Download updates quietly in the background; they take effect at the next
# restart, so nothing changes under you while you're working.
if [ -f /etc/rpm-ostreed.conf ] && grep -qE '^#?AutomaticUpdatePolicy=' /etc/rpm-ostreed.conf; then
    sed -i -E 's/^#?AutomaticUpdatePolicy=.*/AutomaticUpdatePolicy=stage/' /etc/rpm-ostreed.conf
elif [ -f /etc/rpm-ostreed.conf ]; then
    printf 'AutomaticUpdatePolicy=stage\n' >> /etc/rpm-ostreed.conf
else
    printf '[Daemon]\nAutomaticUpdatePolicy=stage\n' > /etc/rpm-ostreed.conf
fi
systemctl enable rpm-ostreed-automatic.timer || true

gtk-update-icon-cache -f -t /usr/share/icons/hicolor || true
update-desktop-database /usr/share/applications || true

# Anything left in /var during the build is discarded by bootc anyway.
rm -rf /var/lib/dnf /var/log/* || true
