# Screenroom and Parlor

Two built-in apps from [Screenroom](https://github.com/spleens23/screenroom):

- **Screenroom**: films and TV shows (`screenroom`, runs the app with `--edition=films`)
- **Parlor**: music (`parlor`, runs the app with `--edition=music`)

They are the same program started two ways, so the image carries one copy in `/usr/lib/screenroom`.
Each keeps its own profiles and settings (`~/.config/screenroom` and `~/.config/parlor`) and they
open in the **Heirloom** theme (glossy light blue); Settings → Theme can switch to 2020s or 1990s.

The image build takes the newest `linux-N` release of Screenroom, so the daily image (and the
Software Update app) brings new versions of both apps along with the system.

`data/` holds the launchers' desktop files and the icons.
