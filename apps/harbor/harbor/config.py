"""Harbor's settings, saved in ~/.config/harbor/config.json."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "harbor"
CONFIG_FILE = CONFIG_DIR / "config.json"
AUTOSTART_FILE = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart" / "dev.harbor.Harbor.desktop"

# Shown in the dock the first time, if they're installed.
DEFAULT_DOCK = [
    "dev.spectacle.Spectacle.desktop",
    "dev.screenroom.Screenroom.desktop",
    "dev.screenroom.Parlor.desktop",
    "org.mozilla.firefox.desktop", "firefox.desktop",
    "org.gnome.Nautilus.desktop",
    "org.gnome.Settings.desktop",
    "org.gnome.Ptyxis.desktop", "org.gnome.Console.desktop",
]


class Config:
    def __init__(self):
        self.dock: list[str] | None = None  # None = not set up yet
        self.hidden: list[str] = []
        self.order: list[str] = []  # your own app order (ids); new apps go at the end
        self.wallpaper: str = ""     # empty = Harbor's built-in wallpaper
        self.show_clock: bool = True
        # folders on Home: {"folder:1": {"name": "Games", "apps": ["a.desktop", ...]}}
        self.folders: dict[str, dict] = {}
        self.load()

    def load(self):
        try:
            data = json.loads(CONFIG_FILE.read_text())
        except (OSError, ValueError):
            return
        self.dock = data.get("dock")
        self.hidden = list(data.get("hidden", []))
        self.order = list(data.get("order", []))
        self.wallpaper = data.get("wallpaper", "")
        self.show_clock = bool(data.get("show_clock", True))
        self.folders = {k: {"name": str(v.get("name") or "Folder"), "apps": list(v.get("apps", []))}
                        for k, v in (data.get("folders") or {}).items() if k.startswith("folder:")}

    def save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = {"dock": self.dock, "hidden": self.hidden, "order": self.order,
                "wallpaper": self.wallpaper, "show_clock": self.show_clock, "folders": self.folders}
        fd, tmp = tempfile.mkstemp(dir=CONFIG_DIR, suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, CONFIG_FILE)

    # ---- folders ---------------------------------------------------------
    def folder_of(self, aid: str) -> str | None:
        return next((fid for fid, f in self.folders.items() if aid in f["apps"]), None)

    def new_folder(self, name: str, first_app: str) -> str:
        n = 1
        while f"folder:{n}" in self.folders:
            n += 1
        fid = f"folder:{n}"
        self.take_out(first_app)
        self.folders[fid] = {"name": name, "apps": [first_app]}
        # The folder takes the app's place on Home.
        if first_app in self.order:
            self.order[self.order.index(first_app)] = fid
        return fid

    def put_in(self, fid: str, aid: str):
        self.take_out(aid)
        self.folders[fid]["apps"].append(aid)
        self.order = [o for o in self.order if o != aid]

    def take_out(self, aid: str):
        for fid, f in list(self.folders.items()):
            if aid in f["apps"]:
                f["apps"].remove(aid)
                if not f["apps"]:
                    self.remove_folder(fid)

    def remove_folder(self, fid: str):
        apps = self.folders.pop(fid, {"apps": []})["apps"]
        if fid in self.order:
            i = self.order.index(fid)
            self.order[i:i + 1] = apps

    # ---- start at login -------------------------------------------------
    @staticmethod
    def starts_at_login() -> bool:
        return AUTOSTART_FILE.exists()

    @staticmethod
    def set_start_at_login(on: bool, command: str):
        if on:
            AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
            AUTOSTART_FILE.write_text(
                "[Desktop Entry]\nType=Application\nName=Harbor\n"
                f"Exec={command}\nIcon=dev.harbor.Harbor\n"
                "X-GNOME-Autostart-enabled=true\nNoDisplay=true\n")
        elif AUTOSTART_FILE.exists():
            AUTOSTART_FILE.unlink()
