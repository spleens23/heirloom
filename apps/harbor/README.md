# Heirloom tablet mode

Fold the screen back and Heirloom becomes a locked-down, iPad-like tablet. Open it
back up and it's a normal GNOME desktop.

## Using it

- **An app is always in front**, filling the screen. After starting up that's
  Screenroom; when you close the last app, Screenroom comes back.
- **The status bar** along the top shows the time on the left and Wi-Fi and battery
  on the right. **Pull down on the right** for the controls (Wi-Fi, Bluetooth,
  volume, brightness, Tablet Mode); **pull down on the left** for notifications and
  the calendar.
- **Swipe up from the bottom edge** (the little home bar) for the **app drawer**:
  search, your Favorites, and every app and folder in alphabetical order. Tap an
  app to open it; tap outside or pull the drawer down to close it. The Super key
  opens it too.
- **Swipe up and pause** for your **open apps**. Tap one to go back to it; flick a
  card up to close that app.
- **Tap and hold an app in the drawer** to add it to Favorites, or put it in a
  folder (**Add to Folder… → New Folder**). Tap a folder to open it and rename it;
  tap and hold an app inside to take it out.
- **Quick Settings → Tablet Mode** switches by hand: Automatic (follow the hinge),
  Always Tablet or Always Laptop.

## Lock screen and passcode

- The lock screen shows the time over your lock-screen picture. **Swipe up** for
  the **passcode keypad** (4 or 6 digits). The same keypad is on the login screen,
  and a keyboard's number keys work too. **Use Password** brings back the ordinary
  password box.
- The first time you log in, Heirloom asks you to choose your passcode. It becomes
  your account's password, so it also approves updates and settings changes.
- After **5 wrong tries in a row**, the account waits **5 minutes** before
  trying again.

## Tablet Settings

The **Tablet Settings** app (it used to be Harbor's home screen) sets the wallpaper,
the lock-screen picture (also used behind the login keypad) and your passcode.

## What's where

- `shell-extension/harbor-tablet@harbor.dev/` — tablet mode: status bar, drawer
  (`drawer.js`), open apps (`switcher.js`), and the look (`stylesheet.css`).
- `shell-extension/heirloom-keypad@heirloom.dev/` — the passcode keypad, on the
  login and lock screens.
- `harbor/` — Tablet Settings and choosing a passcode.
- `/usr/libexec/heirloom-lockscreen` — the small helper that sets the passcode and
  the login-screen picture (it checks your current password first).

Favorites and folders are saved in `~/.config/harbor/config.json`.
