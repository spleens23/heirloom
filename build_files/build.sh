#!/usr/bin/env bash
# Builds Heirloom on top of Fedora Silverblue. Runs inside the image build.
set -euxo pipefail

CTX=/ctx
LIB=/usr/lib/heirloom

# ---- 1. system packages ------------------------------------------------------
# mpv plays video inside Spectacle and Screenroom; ffmpeg merges downloads into one file.
# Fedora's own ffmpeg leaves out H.264, HEVC, AC-3 and DTS, which most films use, so the full
# ffmpeg comes from RPM Fusion (plus the Intel/AMD video drivers that decode those in hardware).
FEDORA_RELEASE="$(rpm -E %fedora)"
dnf5 install -y \
    "https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-${FEDORA_RELEASE}.noarch.rpm" \
    "https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-${FEDORA_RELEASE}.noarch.rpm"
dnf5 swap -y --allowerasing ffmpeg-free ffmpeg || dnf5 install -y --allowerasing ffmpeg
dnf5 install -y --allowerasing \
    mpv mpv-libs ffmpeg \
    python3-pip
dnf5 install -y --allowerasing --skip-unavailable \
    mesa-va-drivers-freeworld intel-media-driver
# Screenroom/Parlor are Electron apps: the libraries Chromium needs, and the helpers its
# subtitle tools use (reading DVD subtitles needs OCR).
dnf5 install -y --skip-unavailable \
    nss atk at-spi2-atk cups-libs libdrm mesa-libgbm alsa-lib libxkbcommon libXScrnSaver libXtst \
    tesseract tesseract-langpack-eng python3-av python3-numpy python3-pillow
dnf5 clean all

# ---- 2. Heirloom's apps ----------------------------------------------------------
mkdir -p "$LIB"
cp -r "$CTX/apps/spectacle/spectacle" "$LIB/"
cp -r "$CTX/apps/harbor/harbor" "$LIB/"
cp -r "$CTX/apps/updates/heirloom_updates" "$LIB/"
cp -r "$CTX/apps/weather/heirloom_weather" "$LIB/"

# Spectacle's helpers (yt-dlp and the mpv bindings) live in their own Python
# environment. The image is rebuilt daily, so yt-dlp stays current.
python3 -m venv --system-site-packages "$LIB/venv"
"$LIB/venv/bin/pip" install --no-cache-dir --upgrade yt-dlp mpv
# The venv must not depend on the build's /tmp or caches.
find "$LIB" -name '__pycache__' -prune -exec rm -rf {} +

install -Dm755 "$CTX/system_files/usr/bin/spectacle" /usr/bin/spectacle
install -Dm755 "$CTX/system_files/usr/bin/harbor" /usr/bin/harbor
install -Dm755 "$CTX/system_files/usr/bin/heirloom-updates" /usr/bin/heirloom-updates
install -Dm755 "$CTX/system_files/usr/bin/heirloom-weather" /usr/bin/heirloom-weather

# folder : app id : command
for app in spectacle:dev.spectacle.Spectacle:spectacle \
           harbor:dev.harbor.Harbor:harbor \
           updates:dev.heirloom.Updates:heirloom-updates \
           weather:dev.heirloom.Weather:heirloom-weather; do
    IFS=: read -r dir id cmd <<< "$app"
    sed "s|@LAUNCHER@|/usr/bin/$cmd|" "$CTX/apps/$dir/data/$id.desktop" \
        > "/usr/share/applications/$id.desktop"
    install -Dm644 "$CTX/apps/$dir/data/$id.svg" "/usr/share/icons/hicolor/scalable/apps/$id.svg"
done

# Screenroom (films and TV) and Parlor (music), from the newest Screenroom release.
bash "$CTX/build_files/screenroom.sh"

# Tablet Mode extension, installed for everyone.
cp -r "$CTX/apps/harbor/shell-extension/harbor-tablet@harbor.dev" \
    /usr/share/gnome-shell/extensions/
# The passcode keypad: in your session, on the lock screen and on the login screen.
cp -r "$CTX/apps/harbor/shell-extension/heirloom-keypad@heirloom.dev" \
    /usr/share/gnome-shell/extensions/
install -Dm755 "$CTX/system_files/usr/libexec/heirloom-lockscreen" /usr/libexec/heirloom-lockscreen
install -d -m 0755 /usr/lib/tmpfiles.d
printf 'd /var/lib/heirloom 0755 root root -\nd /var/lib/heirloom/passcode 0755 root root -\n' \
    > /usr/lib/tmpfiles.d/heirloom.conf

# Wrong passcodes: after 5 in a row, wait 5 minutes (so a short passcode can't be guessed).
if command -v authselect >/dev/null; then
    authselect enable-feature with-faillock || echo "authselect: couldn't turn on the lockout" >&2
fi
mkdir -p /etc/security
cat > /etc/security/faillock.conf <<'EOF'
# Heirloom: lock an account for 5 minutes after 5 wrong passwords or passcodes in a row.
deny = 5
unlock_time = 300
fail_interval = 900
EOF

# ---- 3. look, defaults and branding ----------------------------------------------
cp -r "$CTX/system_files/etc/." /etc/
[ -d "$CTX/system_files/usr/share" ] && cp -r "$CTX/system_files/usr/share/." /usr/share/
install -Dm644 "$CTX/apps/harbor/harbor/wallpaper.svg" /usr/share/backgrounds/heirloom/sky.svg
# Harbor's wallpapers also show in GNOME Settings → Appearance.
mkdir -p /usr/share/gnome-background-properties
{
    echo '<?xml version="1.0" encoding="UTF-8"?>'
    echo '<!DOCTYPE wallpapers SYSTEM "gnome-wp-list.dtd">'
    echo '<wallpapers>'
    for w in "$CTX"/apps/harbor/harbor/wallpapers/*.svg; do
        n="$(basename "$w" .svg)"
        install -Dm644 "$w" "/usr/share/backgrounds/heirloom/$n.svg"
        printf '  <wallpaper deleted="false"><name>Heirloom %s</name><filename>/usr/share/backgrounds/heirloom/%s.svg</filename><options>zoom</options><shade_type>solid</shade_type></wallpaper>\n' "${n^}" "$n"
    done
    echo '</wallpapers>'
} > /usr/share/gnome-background-properties/heirloom.xml
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

# Start without flashing the boot menu (hold Esc while starting to see it).
install -Dm755 "$CTX/system_files/usr/libexec/heirloom-tidy" /usr/libexec/heirloom-tidy
install -Dm644 "$CTX/system_files/usr/lib/systemd/system/heirloom-tidy.service" \
    /usr/lib/systemd/system/heirloom-tidy.service
systemctl enable heirloom-tidy.service
# New installs get it from the start, as part of the boot menu's own settings.
if [ -d /usr/lib/bootupd/grub2-static/configs.d ]; then
    install -Dm644 "$CTX/system_files/usr/share/heirloom/grub-quiet.cfg" \
        /usr/lib/bootupd/grub2-static/configs.d/12_heirloom_quiet.cfg
fi

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
