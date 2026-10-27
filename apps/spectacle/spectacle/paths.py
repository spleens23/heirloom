"""Where Spectacle keeps its files (XDG locations)."""

import os
from pathlib import Path


def _xdg(var: str, fallback: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / fallback)


DATA_DIR = _xdg("XDG_DATA_HOME", ".local/share") / "spectacle"
CACHE_DIR = _xdg("XDG_CACHE_HOME", ".cache") / "spectacle"
THUMB_DIR = CACHE_DIR / "thumbnails"
LIBRARY_FILE = DATA_DIR / "library.json"
# Downloads go somewhere you can find them in the Files app.
DOWNLOAD_DIR = Path(
    os.environ.get("SPECTACLE_DOWNLOAD_DIR")
    or (_xdg("XDG_VIDEOS_DIR", "Videos") / "Spectacle")
)

for d in (DATA_DIR, CACHE_DIR, THUMB_DIR, DOWNLOAD_DIR):
    d.mkdir(parents=True, exist_ok=True)
