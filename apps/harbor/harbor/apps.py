"""Finding installed apps, and launching them."""

from __future__ import annotations

from gi.repository import Gdk, Gio, GLib

from . import APP_ID


def installed_apps() -> list[Gio.DesktopAppInfo]:
    """Every app that would normally show in the app grid, minus Harbor itself."""
    apps = []
    seen = set()
    for info in Gio.AppInfo.get_all():
        if not isinstance(info, Gio.DesktopAppInfo) or not info.should_show():
            continue
        aid = info.get_id()
        if not aid or aid in seen or aid == f"{APP_ID}.desktop":
            continue
        seen.add(aid)
        apps.append(info)
    apps.sort(key=lambda a: a.get_display_name().casefold())
    return apps


def ordered(apps, order: list[str], hidden: list[str]):
    """Apply your saved order; anything new lands at the end, alphabetically.
    Works for apps and folders alike (anything with get_id and get_display_name)."""
    by_id = {a.get_id(): a for a in apps if a.get_id() not in hidden}
    out = [by_id.pop(i) for i in order if i in by_id]
    out += sorted(by_id.values(), key=lambda a: a.get_display_name().casefold())
    return out


class Folder:
    """A folder on Home: a name and the apps in it."""

    def __init__(self, fid: str, name: str, apps: list):
        self.fid, self.name, self.apps = fid, name, apps

    def get_id(self):
        return self.fid

    def get_display_name(self):
        return self.name


# A first name for a new folder, from what kind of app went in first.
_CATEGORY_NAMES = [
    ("Game", "Games"), ("Education", "School"), ("Office", "Office"),
    ("AudioVideo", "Watch & Listen"), ("Audio", "Watch & Listen"), ("Video", "Watch & Listen"),
    ("Graphics", "Photos"), ("Network", "Internet"), ("Development", "Developer"),
    ("Settings", "System"), ("System", "System"), ("Utility", "Utilities"),
]


def folder_name_for(info) -> str:
    cats = (info.get_categories() or "").split(";") if info else []
    for cat, name in _CATEGORY_NAMES:
        if cat in cats:
            return name
    return "Folder"


def launch(info: Gio.DesktopAppInfo, widget=None) -> str | None:
    """Start an app. Returns an error message, or None if it worked."""
    try:
        display = Gdk.Display.get_default()
        ctx = display.get_app_launch_context() if display else None
        info.launch([], ctx)
        return None
    except GLib.Error as e:
        return e.message


def watch(callback):
    """Call callback() whenever apps are installed or removed."""
    monitor = Gio.AppInfoMonitor.get()
    pending = {"id": 0}

    def changed(*_):
        # Package installs touch many files at once; wait for things to settle.
        if pending["id"]:
            GLib.source_remove(pending["id"])
        pending["id"] = GLib.timeout_add(800, lambda: (pending.update(id=0), callback(), False)[2])

    monitor.connect("changed", changed)
    return monitor
