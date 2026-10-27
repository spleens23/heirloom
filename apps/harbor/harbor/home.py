"""The home screen: status bar, clock, swipeable pages of apps, and the dock."""

from __future__ import annotations


from datetime import datetime

from gi.repository import Adw, Gio, GLib, Gtk, Pango

from . import apps as appsmod

CELL_W, CELL_H = 112, 122   # one app icon plus its label
CLOCK_ROWS = 2              # rows the clock takes on the first page


# ---- one app icon ---------------------------------------------------------

class AppIcon(Gtk.Button):
    def __init__(self, home, info: Gio.DesktopAppInfo, in_dock=False, folder: str | None = None):
        super().__init__()
        self.home = home
        self.info = info
        self.folder = folder
        self.add_css_class("app")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, halign=Gtk.Align.CENTER)
        tile = Gtk.Overlay(halign=Gtk.Align.CENTER)
        bg = Gtk.Box()
        bg.add_css_class("tile")
        bg.set_size_request(72, 72)
        tile.set_child(bg)
        img = Gtk.Image(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, pixel_size=52)
        icon = info.get_icon()
        if icon:
            img.set_from_gicon(icon)
        else:
            img.set_from_icon_name("application-x-executable")
        tile.add_overlay(img)
        # A glassy highlight over the top half, like light on a glazed tile.
        gloss = Gtk.Box(valign=Gtk.Align.START, margin_start=1, margin_end=1, margin_top=1)
        gloss.add_css_class("gloss")
        gloss.set_can_target(False)
        tile.add_overlay(gloss)
        box.append(tile)

        name = info.get_display_name()
        label = Gtk.Label(label=name, ellipsize=Pango.EllipsizeMode.END, max_width_chars=11,
                          justify=Gtk.Justification.CENTER)
        label.add_css_class("app-label")
        box.append(label)
        self.set_child(box)

        self.connect("clicked", self._launch)
        hold = Gtk.GestureLongPress()
        hold.connect("pressed", lambda *_: home.show_menu(self, in_dock))
        self.add_controller(hold)
        right = Gtk.GestureClick(button=3)
        right.connect("pressed", lambda *_: home.show_menu(self, in_dock))
        self.add_controller(right)

    def _launch(self, *_):
        self.add_css_class("launching")
        GLib.timeout_add(180, lambda: (self.remove_css_class("launching"), False)[1])
        err = appsmod.launch(self.info, self)
        if err:
            self.home.toast(f"Couldn't open {self.info.get_display_name()}")


# ---- a folder icon: a glass tile with tiny icons of what's inside -----------

class FolderIcon(Gtk.Button):
    def __init__(self, home, folder):
        super().__init__()
        self.home = home
        self.folder = folder
        self.info = None
        self.add_css_class("app")
        self.add_css_class("folder")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, halign=Gtk.Align.CENTER)
        tile = Gtk.Overlay(halign=Gtk.Align.CENTER)
        bg = Gtk.Box()
        bg.add_css_class("tile")
        bg.add_css_class("folder-tile")
        bg.set_size_request(72, 72)
        tile.set_child(bg)
        minis = Gtk.Grid(row_spacing=3, column_spacing=3, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        for n, info in enumerate(folder.apps[:9]):
            img = Gtk.Image(pixel_size=16)
            icon = info.get_icon()
            if icon:
                img.set_from_gicon(icon)
            else:
                img.set_from_icon_name("application-x-executable")
            minis.attach(img, n % 3, n // 3, 1, 1)
        minis.set_can_target(False)
        tile.add_overlay(minis)
        gloss = Gtk.Box(valign=Gtk.Align.START, margin_start=1, margin_end=1, margin_top=1)
        gloss.add_css_class("gloss")
        gloss.set_can_target(False)
        tile.add_overlay(gloss)
        box.append(tile)
        label = Gtk.Label(label=folder.name, ellipsize=Pango.EllipsizeMode.END, max_width_chars=11,
                          justify=Gtk.Justification.CENTER)
        label.add_css_class("app-label")
        box.append(label)
        self.set_child(box)

        self.connect("clicked", lambda *_: home.open_folder(folder.fid))
        hold = Gtk.GestureLongPress()
        hold.connect("pressed", lambda *_: home.show_folder_menu(self))
        self.add_controller(hold)
        right = Gtk.GestureClick(button=3)
        right.connect("pressed", lambda *_: home.show_folder_menu(self))
        self.add_controller(right)


def icon_for(home, item):
    return FolderIcon(home, item) if isinstance(item, appsmod.Folder) else AppIcon(home, item)


# ---- status bar -------------------------------------------------------------

class StatusBar(Gtk.CenterBox):
    def __init__(self, home):
        super().__init__()
        self.add_css_class("statusbar")
        left = Gtk.Box(spacing=2)
        for icon, tip, fn in (("harbor-settings-symbolic", "Harbor settings", home.open_settings),
                              ("harbor-search-symbolic", "Search apps", home.open_search)):
            b = Gtk.Button(icon_name=icon, tooltip_text=tip, valign=Gtk.Align.CENTER)
            b.add_css_class("status-button")
            b.connect("clicked", lambda *_, f=fn: f())
            left.append(b)
        self.set_start_widget(left)

        self.time = Gtk.Label()
        self.set_center_widget(self.time)

        right = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        self.pct = Gtk.Label()
        right.append(self.pct)
        batt = Gtk.Box(valign=Gtk.Align.CENTER)
        self.level = Gtk.LevelBar(min_value=0, max_value=1, valign=Gtk.Align.CENTER)
        self.level.add_css_class("battery")
        # Remove the default color offsets; our CSS draws the colors.
        for name in ("low", "high", "full"):
            self.level.remove_offset_value(name)
        batt.append(self.level)
        nub = Gtk.Box(valign=Gtk.Align.CENTER)
        nub.add_css_class("battery-nub")
        batt.append(nub)
        right.append(batt)
        self.bolt = Gtk.Label(label="⚡")
        right.append(self.bolt)
        self.batt_box = right
        self.set_end_widget(right)
        self._upower = None
        self._connect_battery()

    def tick(self, now: datetime):
        self.time.set_label(now.strftime("%-I:%M %p"))

    def _connect_battery(self):
        try:
            self._upower = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SYSTEM, Gio.DBusProxyFlags.NONE, None,
                "org.freedesktop.UPower", "/org/freedesktop/UPower/devices/DisplayDevice",
                "org.freedesktop.UPower.Device", None)
            self._upower.connect("g-properties-changed", lambda *_: self._update_battery())
        except GLib.Error:
            self._upower = None
        self._update_battery()

    def _update_battery(self):
        p = self._upower
        present = p and p.get_cached_property("IsPresent")
        if not present or not present.unpack():
            self.batt_box.set_visible(False)
            return
        pct = p.get_cached_property("Percentage").unpack()
        state = p.get_cached_property("State").unpack()  # 1 charging, 2 discharging, 4 full
        self.batt_box.set_visible(True)
        self.pct.set_label(f"{pct:.0f}%")
        self.level.set_value(pct / 100)
        (self.level.add_css_class if pct <= 20 and state != 1 else self.level.remove_css_class)("low")
        self.bolt.set_visible(state in (1, 4))


# ---- clock -------------------------------------------------------------------

class Clock(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.CENTER,
                         valign=Gtk.Align.CENTER)
        self.add_css_class("clock-panel")
        self.time = Gtk.Label()
        self.time.add_css_class("clock-time")
        self.date = Gtk.Label()
        self.date.add_css_class("clock-date")
        self.append(self.time)
        self.append(self.date)

    def tick(self, now: datetime):
        self.time.set_label(now.strftime("%-I:%M"))
        self.date.set_label(now.strftime("%A, %B %-d"))


# ---- the pages ---------------------------------------------------------------

class Pages(Gtk.Widget):
    """A swipeable set of app pages that re-flows when the screen rotates.

    It's a bare Gtk.Widget (not a Box) so GTK tells it its exact size, which
    is how it knows how many rows and columns of icons fit.
    """

    def __init__(self, home):
        super().__init__(vexpand=True, hexpand=True)
        self.home = home
        self.inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.inner.set_parent(self)
        self.carousel = Adw.Carousel(vexpand=True, hexpand=True, allow_scroll_wheel=True,
                                     allow_long_swipes=False, spacing=24)
        self.inner.append(self.carousel)
        self.dots = Adw.CarouselIndicatorDots(carousel=self.carousel)
        self.inner.append(self.dots)
        self._grid = (0, 0)
        self.clock = Clock()
        # Tap and hold an empty spot on Home: wallpaper and settings.
        hold = Gtk.GestureLongPress()
        hold.connect("pressed", self._hold_empty)
        self.add_controller(hold)
        right = Gtk.GestureClick(button=3)
        right.connect("pressed", lambda g, n, x, y: self._hold_empty(g, x, y))
        self.add_controller(right)

    def _hold_empty(self, _g, x, y):
        w = self.pick(x, y, Gtk.PickFlags.DEFAULT)
        while w is not None and w is not self:
            if isinstance(w, (AppIcon, FolderIcon)):
                return  # the icon shows its own menu
            w = w.get_parent()
        self.home.show_home_menu(self, x, y)

    def do_measure(self, orientation, for_size):
        _min, nat, _mb, _nb = self.inner.measure(orientation, for_size)
        return 0, nat, -1, -1  # can shrink: pages re-flow to fit

    def do_dispose(self):
        if self.inner.get_parent() is self:
            self.inner.unparent()

    def do_size_allocate(self, width, height, baseline):
        self.inner.allocate(width, height, baseline, None)
        dots_h = 28
        cols = max(3, min(8, width // CELL_W))
        rows = max(2, (height - dots_h) // CELL_H)
        if (cols, rows) != self._grid:
            self._grid = (cols, rows)
            # Can't change children mid-layout; rebuild right after.
            GLib.idle_add(lambda: (self.rebuild(), False)[1])

    def rebuild(self):
        cols, rows = self._grid
        if not cols:
            return
        current = round(self.carousel.get_position())
        while self.carousel.get_n_pages():
            page = self.carousel.get_nth_page(0)
            if page is self.clock.get_parent():
                page.remove(self.clock)  # keep the clock widget alive
            self.carousel.remove(page)

        apps = self.home.grid_apps()
        clock_on = self.home.config.show_clock and rows > CLOCK_ROWS + 1
        first_cap = cols * (rows - (CLOCK_ROWS if clock_on else 0))
        per_page = cols * rows
        chunks = [apps[:first_cap]]
        rest = apps[first_cap:]
        while rest:
            chunks.append(rest[:per_page])
            rest = rest[per_page:]

        for i, chunk in enumerate(chunks):
            page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, vexpand=True)
            if i == 0 and clock_on:
                holder = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
                holder.set_size_request(-1, CLOCK_ROWS * CELL_H)
                holder.append(self.clock)
                page.append(holder)
            grid = Gtk.Grid(column_homogeneous=True, halign=Gtk.Align.FILL, hexpand=True,
                            valign=Gtk.Align.START)
            for n, info in enumerate(chunk):
                cell = icon_for(self.home, info)
                cell.set_size_request(CELL_W, CELL_H)
                grid.attach(cell, n % cols, n // cols, 1, 1)
            # Fill short rows so icons stay aligned to the same columns.
            for c in range(len(chunk), cols):
                spacer = Gtk.Box()
                spacer.set_size_request(CELL_W, 1)
                grid.attach(spacer, c, 0, 1, 1)
            page.append(grid)
            self.carousel.append(page)
        self.dots.set_visible(len(chunks) > 1)
        n = self.carousel.get_n_pages()
        if n:
            self.carousel.scroll_to(self.carousel.get_nth_page(min(current, n - 1)), False)

    def go_first(self):
        if self.carousel.get_n_pages():
            self.carousel.scroll_to(self.carousel.get_nth_page(0), True)


# ---- the dock -----------------------------------------------------------------

class Dock(Gtk.Box):
    def __init__(self, home):
        super().__init__(halign=Gtk.Align.CENTER, spacing=10)
        self.add_css_class("dock")
        self.home = home

    def rebuild(self):
        child = self.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.remove(child)
            child = nxt
        dock = self.home.dock_apps()
        for info in dock:
            self.append(AppIcon(self.home, info, in_dock=True))
        self.set_visible(bool(dock))


