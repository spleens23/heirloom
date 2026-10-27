# Harbor

A glossy, light-blue home screen for your Linux tablet: pages of your apps,
a clock, a glass dock and quick search. It matches Spectacle's look.

## Install (Fedora)

1. Unzip the folder anywhere.
2. Open **Terminal**, type `cd ` (with a space), drag the `harbor` folder into
   the window, and press Enter.
3. Run `bash install.sh`.

## Tablet Mode

The installer also adds a small GNOME extension. After you log out and back in:

- **Fold the screen back** and Harbor comes forward as your home screen. The
  Super key and a **swipe up from the bottom edge** take you Home, a small home
  bar sits along the bottom, and apps open full size.
- **Open it back into a laptop** for a normal GNOME desktop. Harbor tucks
  itself away and the Super key opens Activities again.
- **Quick Settings** (top-right corner) has a **Tablet Mode** switch: tap it to
  flip modes by hand, or open its menu to pick Automatic, Always Tablet or
  Always Laptop.

## Make it your home screen

1. Open Harbor, tap the **gear** at the top left, and turn on
   **Open Harbor when I log in**.
2. Add a **Home button**: open GNOME **Settings → Keyboard → View and Customize
   Shortcuts → Custom Shortcuts → +**. Name it `Home`, set the command to
   `harbor`, and pick a shortcut (for example Super+H). Pressing it brings
   Harbor back to the front from any app.

To leave Harbor, use **Quit Harbor** in its settings.

## Using it

- **Tap** an app to open it. **Swipe** left and right between pages.
- **Tap and hold** (or right-click) an app for options: add to or remove from
  the dock, move it earlier or later, or hide it.
- **Search:** tap the magnifying glass, or just start typing on Home. Press
  Enter to open the top result.
- **Settings** (gear): choose your own wallpaper, turn the clock off, and
  bring back hidden apps.
- The layout re-flows automatically when you rotate the screen.

## Making it yours

- `harbor/style.css` — colors, gloss, the dock's glass, icon tiles, the clock.
- `harbor/wallpaper.svg` — the built-in sky wallpaper.
- `harbor/home.py` — `CELL_W` and `CELL_H` set how much room each icon gets.

Run `bash install.sh` again after editing. Your settings are saved in
`~/.config/harbor/config.json`. To remove Harbor, run `bash uninstall.sh`.
