# Heirloom

A glossy, light-blue, touch-first Linux for 2-in-1 laptops. Fold the screen
back and it's a tablet with a home screen; open it up and it's a normal
desktop. Built on Fedora Silverblue, so the system updates as a whole image
and a bad update can be undone from the boot menu.

**What's inside**

- **Harbor**, the home screen: pages of apps, a clock, a glass dock and search
- **Tablet Mode**: folding the screen back brings Harbor forward, and the
  Super key or a swipe up from the bottom edge goes Home
- **Spectacle**, a video app with subscriptions, Watch Later and downloads
- On first boot (with Wi-Fi): Steam, LibreOffice, Calculator, Calendar, Clocks,
  Text Editor, Photos, PDFs, Weather, Celluloid and Foliate from Flathub
- Fedora's GNOME underneath: Files, Terminal, Firefox, Settings, Software

## Getting the installer

1. Open the **Actions** tab of this repository.
2. Wait for **Build Heirloom** to show a green check (it runs on every change
   and once a day).
3. Click **Build installer ISO** → **Run workflow**. It takes about 20–40
   minutes.
4. Open the finished run and download **heirloom-installer** under
   **Artifacts**. Unzip it to get the `.iso`.

## Installing

1. Write the ISO to a USB stick (8 GB or larger) with **Fedora Media Writer**
   (choose "Select .iso file") or balenaEtcher.
2. Plug it into the Latitude, power on while tapping **F12**, and pick the USB
   stick.
3. Follow the installer: language, disk (**this erases the disk**), then your
   name and password.
4. After the first boot, connect to Wi-Fi. Heirloom quietly installs the extra
   apps in the background; they appear in Harbor over the next few minutes.

## Updates

New images are built daily. GNOME Software offers them like any update, or run
`sudo bootc upgrade` and restart. To undo the last update, pick the previous
entry in the boot menu, or run `sudo bootc rollback`.

## Changing Heirloom

Everything that makes up the system is in this repository:

| Where | What |
|---|---|
| `Containerfile` | The recipe. `FEDORA_VERSION` picks the Fedora release. |
| `build_files/build.sh` | Packages and setup steps run during the build |
| `system_files/etc/dconf/db/local.d/00-heirloom` | Default settings: wallpaper, accent color, dock favorites |
| `system_files/usr/libexec/heirloom-first-boot` | First-boot jobs, including the Flathub app list |
| `apps/harbor`, `apps/spectacle` | The apps themselves |

Commit a change and GitHub rebuilds the image; your installed machine picks it
up with the next update.
