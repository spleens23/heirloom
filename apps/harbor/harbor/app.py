"""Harbor's application, window, search, long-press menu and settings."""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from . import APP_ID, APP_NAME  # noqa: E402
from . import apps as appsmod  # noqa: E402
from .config import DEFAULT_DOCK, Config  # noqa: E402
from .home import AppIcon, Dock, Pages, StatusBar  # noqa: E402

HERE = Path(__file__).resolve().parent
MAX_DOCK = 6


class HarborApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        GLib.set_application_name(APP_NAME)
        self.window = None

    def do_startup(self):
        Adw.Application.do_startup(self)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        display = Gdk.Display.get_default()
        css = Gtk.CssProvider()
        css.load_from_path(str(HERE / "style.css"))
        Gtk.StyleContext.add_provider_for_display(display, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        Gtk.IconTheme.get_for_display(display).add_search_path(str(HERE / "icons"))

    def do_activate(self):
        # Launching Harbor again (e.g. from a keyboard shortcut) brings Home back.
        if not self.window:
            self.window = HomeWindow(self)
        else:
            self.window.go_home()
        self.window.present()


class HomeWindow(Adw.ApplicationWindow):
    def __init__(self, app: HarborApp):
        super().__init__(application=app, title=APP_NAME, default_width=1280, default_height=800)
        self.add_css_class("harbor")
        # Start at the screen's size, so the layout is right even before
        # the window goes full screen.
        monitors = Gdk.Display.get_default().get_monitors()
        if monitors.get_n_items():
            geo = monitors.get_item(0).get_geometry()
            self.set_default_size(geo.width, geo.height)
        self.config = Config()
        self._all_apps: list[Gio.DesktopAppInfo] = []
        self._wall_css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), self._wall_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 2)

        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)
        self.overlay = Gtk.Overlay()
        self.toasts.set_child(self.overlay)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.status = StatusBar(self)
        root.append(self.status)
        self.pages = Pages(self)
        self.pages.set_margin_top(12)
        root.append(self.pages)
        self.dock = Dock(self)
        root.append(self.dock)
        self.overlay.set_child(root)

        self.search_sheet = self._build_search()
        self.overlay.add_overlay(self.search_sheet)

        self._apply_wallpaper()
        self.reload_apps()
        self._monitor = appsmod.watch(self.reload_apps)
        self._tick()
        GLib.timeout_add_seconds(1, self._tick)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)
        self.fullscreen()

    # ---- data -------------------------------------------------------------
    def reload_apps(self):
        self._all_apps = appsmod.installed_apps()
        ids = {a.get_id() for a in self._all_apps}
        if self.config.dock is None:  # first run: pick a sensible dock
            dock = []
            for d in DEFAULT_DOCK:
                if d in ids and len(dock) < 4 and not (d == "firefox.desktop" and "org.mozilla.firefox.desktop" in dock):
                    dock.append(d)
            self.config.dock = dock
            self.config.save()
        self.pages.rebuild()
        self.dock.rebuild()

    def _by_id(self):
        return {a.get_id(): a for a in self._all_apps}

    def grid_apps(self):
        dock = set(self.config.dock or [])
        apps = [a for a in self._all_apps if a.get_id() not in dock]
        return appsmod.ordered(apps, self.config.order, self.config.hidden)

    def dock_apps(self):
        by_id = self._by_id()
        return [by_id[i] for i in (self.config.dock or []) if i in by_id]

    def _tick(self):
        now = datetime.now()
        self.status.tick(now)
        self.pages.clock.tick(now)
        return True

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text, timeout=2))

    def go_home(self):
        self.close_search()
        self.pages.go_first()

    def _key(self, _c, keyval, _code, state):
        if self.search_sheet.get_visible():
            if keyval == Gdk.KEY_Escape:
                self.close_search()
                return True
            return False
        # Typing anywhere on Home starts a search.
        ch = chr(Gdk.keyval_to_unicode(keyval) or 0)
        if ch.isprintable() and ch.strip() and not state & Gdk.ModifierType.CONTROL_MASK:
            self.open_search(ch)
            return True
        return False

    # ---- wallpaper --------------------------------------------------------
    def _apply_wallpaper(self):
        path = self.config.wallpaper
        if not path or not Path(path).exists():
            path = str(HERE / "wallpaper.svg")
        uri = Gio.File.new_for_path(path).get_uri()
        self._wall_css.load_from_string(f'window.harbor {{ background-image: url("{uri}"); }}')

    # ---- long-press menu ----------------------------------------------------
    def show_menu(self, icon: AppIcon, in_dock: bool):
        aid = icon.info.get_id()
        pop = Gtk.Popover(has_arrow=True, position=Gtk.PositionType.TOP)
        pop.add_css_class("app-menu")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        items = []
        if in_dock:
            items.append(("Remove from Dock", lambda: self._dock_remove(aid)))
            items.append(("Move Left", lambda: self._dock_move(aid, -1)))
            items.append(("Move Right", lambda: self._dock_move(aid, 1)))
        else:
            items.append(("Add to Dock", lambda: self._dock_add(aid)))
            items.append(("Move Earlier", lambda: self._grid_move(aid, -1)))
            items.append(("Move Later", lambda: self._grid_move(aid, 1)))
            items.append(("Hide from Home", lambda: self._hide(aid)))
        for label, fn in items:
            b = Gtk.Button(label=label)
            b.add_css_class("menu-item")
            b.get_child().set_xalign(0)
            b.connect("clicked", lambda *_, f=fn: (pop.popdown(), f()))
            box.append(b)
        pop.set_child(box)
        pop.set_parent(icon)
        pop.connect("closed", lambda p: GLib.idle_add(lambda: (p.unparent(), False)[1]))
        pop.popup()

    def _save_and_rebuild(self):
        self.config.save()
        self.pages.rebuild()
        self.dock.rebuild()

    def _dock_add(self, aid):
        if len(self.config.dock) >= MAX_DOCK:
            self.toast(f"The dock holds {MAX_DOCK} apps. Remove one first.")
            return
        self.config.dock.append(aid)
        self._save_and_rebuild()

    def _dock_remove(self, aid):
        self.config.dock = [d for d in self.config.dock if d != aid]
        self._save_and_rebuild()

    def _dock_move(self, aid, step):
        d = self.config.dock
        i = d.index(aid)
        j = max(0, min(len(d) - 1, i + step))
        d[i], d[j] = d[j], d[i]
        self._save_and_rebuild()

    def _grid_move(self, aid, step):
        order = [a.get_id() for a in self.grid_apps()]
        i = order.index(aid)
        j = max(0, min(len(order) - 1, i + step))
        order[i], order[j] = order[j], order[i]
        self.config.order = order
        self._save_and_rebuild()

    def _hide(self, aid):
        self.config.hidden.append(aid)
        self._save_and_rebuild()
        self.toast("Hidden — bring it back in Harbor settings")

    # ---- search -------------------------------------------------------------
    def _build_search(self):
        sheet = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, visible=False)
        sheet.add_css_class("search-sheet")
        top = Gtk.Box(spacing=10, margin_top=24, margin_start=40, margin_end=40)
        self.search_entry = Gtk.SearchEntry(hexpand=True, placeholder_text="Search apps")
        self.search_entry.add_css_class("home-search")
        self.search_entry.connect("search-changed", lambda *_: self._filter())
        self.search_entry.connect("activate", lambda *_: self._open_first())
        self.search_entry.connect("stop-search", lambda *_: self.close_search())
        top.append(self.search_entry)
        cancel = Gtk.Button(label="Cancel", valign=Gtk.Align.CENTER)
        cancel.add_css_class("glossy")
        cancel.add_css_class("plain")
        cancel.connect("clicked", lambda *_: self.close_search())
        top.append(cancel)
        sheet.append(top)
        self.search_hint = Gtk.Label(label="")
        self.search_hint.add_css_class("hint-light")
        sheet.append(self.search_hint)
        self.results = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                                   max_children_per_line=10, valign=Gtk.Align.START,
                                   margin_start=30, margin_end=30)
        sw = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        sw.set_child(self.results)
        sheet.append(sw)
        # Tapping the empty dark area closes search.
        tap = Gtk.GestureClick()
        tap.connect("released", lambda g, n, x, y: self._sheet_tap(sw, y))
        sheet.add_controller(tap)
        return sheet

    def _sheet_tap(self, sw, y):
        if not self.results.get_first_child():
            self.close_search()

    def open_search(self, initial: str = ""):
        self.search_sheet.set_visible(True)
        self.search_entry.set_text(initial)
        self.search_entry.grab_focus()
        self.search_entry.set_position(-1)
        self._filter()

    def close_search(self):
        self.search_sheet.set_visible(False)
        self.search_entry.set_text("")

    def _matches(self):
        q = self.search_entry.get_text().strip().casefold()
        if not q:
            return []
        hits = []
        for a in self._all_apps:
            name = a.get_display_name().casefold()
            hay = " ".join(filter(None, [name, (a.get_description() or "").casefold(),
                                         " ".join(a.get_keywords() or []).casefold()]))
            if q in hay:
                hits.append((0 if name.startswith(q) else 1 if q in name else 2, name, a))
        return [a for *_, a in sorted(hits, key=lambda h: (h[0], h[1]))]

    def _filter(self):
        self.results.remove_all()
        matches = self._matches()
        q = self.search_entry.get_text().strip()
        self.search_hint.set_label("" if not q else (f"No apps match “{q}”" if not matches else ""))
        for a in matches[:40]:
            icon = AppIcon(self, a)
            icon.connect("clicked", lambda *_: self.close_search())
            self.results.append(icon)

    def _open_first(self):
        matches = self._matches()
        if matches:
            appsmod.launch(matches[0])
            self.close_search()

    # ---- settings ---------------------------------------------------------------
    def open_settings(self):
        SettingsWindow(self).present()


class SettingsWindow(Gtk.Window):
    def __init__(self, home: HomeWindow):
        super().__init__(transient_for=home, modal=True, title="Harbor Settings",
                         default_width=460, default_height=560)
        self.add_css_class("harbor-settings")
        self.home = home
        cfg = home.config
        outer = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10,
                      margin_bottom=20, margin_start=18, margin_end=18)
        outer.set_child(box)
        self.set_child(outer)

        # Wallpaper
        box.append(self._title("Wallpaper"))
        row = Gtk.Box(spacing=10)
        pick = Gtk.Button(label="Choose Picture…")
        pick.add_css_class("glossy")
        pick.connect("clicked", lambda *_: self._choose_wallpaper())
        row.append(pick)
        reset = Gtk.Button(label="Use Harbor's Sky")
        reset.add_css_class("glossy")
        reset.add_css_class("plain")
        reset.connect("clicked", lambda *_: self._set_wallpaper(""))
        row.append(reset)
        box.append(row)

        # Options
        box.append(self._title("Home Screen"))
        lst = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        lst.add_css_class("grouped")
        lst.append(self._switch_row("Show the clock", cfg.show_clock, self._toggle_clock))
        lst.append(self._switch_row("Open Harbor when I log in", Config.starts_at_login(), self._toggle_login))
        box.append(lst)

        # Hidden apps
        box.append(self._title("Hidden Apps"))
        hidden = [a for a in home._all_apps if a.get_id() in cfg.hidden]
        if hidden:
            hl = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
            hl.add_css_class("grouped")
            for a in hidden:
                r = Gtk.Box(spacing=10)
                img = Gtk.Image(pixel_size=32)
                if a.get_icon():
                    img.set_from_gicon(a.get_icon())
                r.append(img)
                lbl = Gtk.Label(label=a.get_display_name(), xalign=0, hexpand=True,
                                ellipsize=Pango.EllipsizeMode.END)
                r.append(lbl)
                show = Gtk.Button(label="Show", valign=Gtk.Align.CENTER)
                show.add_css_class("glossy")
                show.connect("clicked", lambda b, aid=a.get_id(), rr=r: self._unhide(aid, rr))
                r.append(show)
                hl.append(r)
            box.append(hl)
        else:
            none = Gtk.Label(label="No hidden apps. Long-press an app on Home to hide it.", xalign=0, wrap=True)
            none.add_css_class("dim-label")
            box.append(none)

        # Heirloom's Software Update app, when it's installed.
        updates = Gio.DesktopAppInfo.new("dev.heirloom.Updates.desktop")
        if updates:
            box.append(self._title("System"))
            upd = Gtk.Button(label="Software Update…")
            upd.add_css_class("glossy")
            upd.connect("clicked", lambda *_: (updates.launch([], None), self.close()))
            box.append(upd)

        # Leave
        box.append(self._title("Harbor"))
        quit_btn = Gtk.Button(label="Quit Harbor")
        quit_btn.add_css_class("glossy")
        quit_btn.add_css_class("plain")
        quit_btn.connect("clicked", lambda *_: home.get_application().quit())
        box.append(quit_btn)
        tip = Gtk.Label(wrap=True, xalign=0, label=(
            "Tip: tapping and holding an app gives you options like Add to Dock. "
            "Type anywhere on Home to search."))
        tip.add_css_class("dim-label")
        tip.set_margin_top(8)
        box.append(tip)

    def _title(self, text):
        lbl = Gtk.Label(label=text, xalign=0)
        lbl.add_css_class("settings-title")
        return lbl

    def _switch_row(self, text, active, fn):
        r = Gtk.Box(spacing=10)
        lbl = Gtk.Label(label=text, xalign=0, hexpand=True)
        r.append(lbl)
        sw = Gtk.Switch(active=active, valign=Gtk.Align.CENTER)
        sw.connect("notify::active", lambda s, _p: fn(s.get_active()))
        r.append(sw)
        return r

    def _toggle_clock(self, on):
        self.home.config.show_clock = on
        self.home._save_and_rebuild()

    def _toggle_login(self, on):
        cmd = shutil.which("harbor") or f"{sys.executable} -m harbor"
        Config.set_start_at_login(on, cmd)

    def _unhide(self, aid, row_child):
        self.home.config.hidden = [h for h in self.home.config.hidden if h != aid]
        self.home._save_and_rebuild()
        row = row_child.get_parent()
        row.get_parent().remove(row)

    def _choose_wallpaper(self):
        dialog = Gtk.FileDialog(title="Choose a Wallpaper")
        f = Gtk.FileFilter()
        f.set_name("Pictures")
        f.add_mime_type("image/*")
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(f)
        dialog.set_filters(store)

        def done(dlg, res):
            try:
                file = dlg.open_finish(res)
            except GLib.Error:
                return
            self._set_wallpaper(file.get_path())

        dialog.open(self, None, done)

    def _set_wallpaper(self, path):
        self.home.config.wallpaper = path or ""
        self.home.config.save()
        self.home._apply_wallpaper()


def main():
    return HarborApp().run(sys.argv)
