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
    """Apply your saved order; anything new lands at the end, alphabetically."""
    by_id = {a.get_id(): a for a in apps if a.get_id() not in hidden}
    out = [by_id.pop(i) for i in order if i in by_id]
    out += sorted(by_id.values(), key=lambda a: a.get_display_name().casefold())
    return out


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
