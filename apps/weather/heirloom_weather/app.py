"""Heirloom Weather's window: today's weather, the next hours, the week, and finding cities."""

from __future__ import annotations

import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from . import APP_ID  # noqa: E402
from . import forecast as fc  # noqa: E402

HERE = Path(__file__).resolve().parent
REFRESH_MINUTES = 30
MOODS = ("sunny", "cloudy", "rain", "snow", "storm", "night")


def run_in_thread(work, done):
    """Run work() away from the screen, then done(result, error) back on it."""
    def go():
        try:
            res, err = work(), None
        except Exception as e:  # network trouble, bad answers
            res, err = None, e
        GLib.idle_add(lambda: (done(res, err), False)[1])
    threading.Thread(target=go, daemon=True).start()


def label(text="", css=None, **kw):
    lbl = Gtk.Label(label=text, **kw)
    for c in (css or "").split():
        lbl.add_css_class(c)
    return lbl


class WeatherApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        GLib.set_application_name("Weather")

    def do_startup(self):
        Adw.Application.do_startup(self)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        css = Gtk.CssProvider()
        css.load_from_path(str(HERE / "style.css"))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)

    def do_activate(self):
        win = self.props.active_window or WeatherWindow(self)
        win.present()
        win.refresh(only_if_stale=True)


class WeatherWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Weather", default_width=900, default_height=680)
        self.add_css_class("weather")
        self.settings = fc.Settings()
        self.data: dict | None = None
        self._search_id = 0
        self._search_gen = 0

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.append(self._navbar())
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vexpand=True)
        self.stack.add_named(self._weather_page(), "weather")
        self.stack.add_named(self._search_page(), "search")
        self.stack.add_named(self._cities_page(), "cities")
        root.append(self.stack)
        self.toasts = Adw.ToastOverlay(child=root)
        self.set_content(self.toasts)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)
        GLib.timeout_add_seconds(REFRESH_MINUTES * 60, lambda: (self.refresh(), True)[1])

        if self.settings.places:
            self.show_place()
        else:
            self.open_search()

    # ---- the bar along the top -------------------------------------------------
    def _navbar(self):
        bar = Gtk.CenterBox()
        bar.add_css_class("navbar")
        self.cities_btn = Gtk.Button(label="Cities", valign=Gtk.Align.CENTER)
        self.cities_btn.add_css_class("bar-button")
        self.cities_btn.connect("clicked", lambda *_: self.toggle_cities())
        bar.set_start_widget(self.cities_btn)
        self.title = label("Weather", "navbar-title", ellipsize=Pango.EllipsizeMode.END)
        bar.set_center_widget(self.title)
        right = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
        self.search_btn = Gtk.Button(label="Find a City", valign=Gtk.Align.CENTER)
        self.search_btn.add_css_class("bar-button")
        self.search_btn.connect("clicked", lambda *_: self.open_search())
        right.append(self.search_btn)
        bar.set_end_widget(right)
        return bar

    # ---- today, the next hours, the week -----------------------------------------
    def _weather_page(self):
        sw = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.sky = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.sky.add_css_class("sky")
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=26, margin_bottom=30,
                      margin_start=24, margin_end=24, halign=Gtk.Align.CENTER)
        col.set_size_request(min(760, 700), -1)

        # now
        now = Gtk.Box(spacing=28, halign=Gtk.Align.CENTER)
        self.now_icon = Gtk.Image(pixel_size=128)
        self.now_icon.add_css_class("now-icon")
        now.append(self.now_icon)
        txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        self.now_place = label("", "now-place", xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.now_temp = label("", "now-temp", xalign=0)
        self.now_words = label("", "now-words", xalign=0)
        self.now_more = label("", "now-more", xalign=0, wrap=True)
        for w in (self.now_place, self.now_temp, self.now_words, self.now_more):
            txt.append(w)
        now.append(txt)
        col.append(now)

        # next 24 hours
        hours_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        hours_card.add_css_class("glass")
        hours_card.append(label("Next 24 Hours", "card-title", xalign=0))
        hs = Gtk.ScrolledWindow(vscrollbar_policy=Gtk.PolicyType.NEVER, hscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        hs.set_min_content_height(118)
        self.hours = Gtk.Box(spacing=4)
        hs.set_child(self.hours)
        hours_card.append(hs)
        col.append(hours_card)

        # the week
        week_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        week_card.add_css_class("glass")
        week_card.append(label("This Week", "card-title", xalign=0))
        self.days = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        week_card.append(self.days)
        col.append(week_card)

        self.updated = label("", "updated")
        col.append(self.updated)
        credit = label("Weather data by Open-Meteo.com · places from GeoNames", "credit")
        col.append(credit)

        self.sky.append(col)
        sw.set_child(self.sky)
        return sw

    # ---- finding a city ------------------------------------------------------------
    def _search_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=24,
                       margin_start=24, margin_end=24, margin_bottom=20)
        page.add_css_class("paper")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER)
        box.set_size_request(560, -1)
        box.append(label("Find a City", "page-title", xalign=0))
        self.search_entry = Gtk.SearchEntry(placeholder_text="City or town, like “Portland” or “Portland, Maine”",
                                            hexpand=True)
        self.search_entry.add_css_class("city-search")
        self.search_entry.connect("search-changed", lambda *_: self._queue_search())
        self.search_entry.connect("activate", lambda *_: self._pick_first())
        self.search_entry.connect("stop-search", lambda *_: self.close_search())
        box.append(self.search_entry)
        self.search_hint = label("Type at least two letters.", "dim", xalign=0, wrap=True)
        box.append(self.search_hint)
        self.results = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.results.add_css_class("grouped")
        self.results.connect("row-activated", lambda _l, row: self._pick(row.place))
        self.results.set_visible(False)
        self.results.set_valign(Gtk.Align.START)
        rs = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        rs.set_child(self.results)
        box.append(rs)
        self.search_cancel = Gtk.Button(label="Cancel", halign=Gtk.Align.START)
        self.search_cancel.add_css_class("glossy")
        self.search_cancel.add_css_class("plain")
        self.search_cancel.connect("clicked", lambda *_: self.close_search())
        box.append(self.search_cancel)
        page.append(box)
        return page

    def open_search(self):
        self.stack.set_visible_child_name("search")
        self.title.set_label("Find a City")
        self.search_cancel.set_visible(bool(self.settings.places))
        self.search_entry.set_text("")
        self.results.remove_all()
        self.results.set_visible(False)
        self.search_hint.set_label("Type at least two letters." if self.settings.places
                                   else "Welcome! Which city's weather would you like to see?")
        GLib.idle_add(lambda: (self.search_entry.grab_focus(), False)[1])

    def close_search(self):
        if self.settings.places:
            self.show_place()

    def _queue_search(self):
        if self._search_id:
            GLib.source_remove(self._search_id)
        self._search_id = GLib.timeout_add(350, self._run_search)

    def _run_search(self):
        self._search_id = 0
        q = self.search_entry.get_text().strip()
        self._search_gen += 1
        gen = self._search_gen
        if len(q) < 2:
            self.results.remove_all()
            self.results.set_visible(False)
            self.search_hint.set_label("Type at least two letters.")
            return False
        self.search_hint.set_label("Searching…")

        def done(places, err):
            if gen != self._search_gen:
                return  # an older search finished after a newer one started
            self.results.remove_all()
            if err:
                self.search_hint.set_label("Couldn't search right now. Check that you're connected to the internet.")
                self.results.set_visible(False)
                return
            if not places:
                self.search_hint.set_label(f"No places called “{q}”. Check the spelling, or add the state or country after a comma.")
                self.results.set_visible(False)
                return
            self.search_hint.set_label("Tap a place to add it.")
            for p in places:
                row = Gtk.ListBoxRow(activatable=True)
                row.place = p
                b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
                b.append(label(p["name"], "row-title", xalign=0))
                b.append(label(", ".join(x for x in (p["region"], p["country"]) if x), "row-sub", xalign=0))
                row.set_child(b)
                self.results.append(row)
            self.results.set_visible(True)

        run_in_thread(lambda: fc.search(q), done)
        return False

    def _pick_first(self):
        row = self.results.get_row_at_index(0)
        if row is not None:
            self._pick(row.place)

    def _pick(self, place):
        self.settings.add(place)
        self.rebuild_cities()
        self.show_place()

    # ---- your cities -------------------------------------------------------------------
    def _cities_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=24,
                       margin_start=24, margin_end=24, margin_bottom=20)
        page.add_css_class("paper")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, halign=Gtk.Align.CENTER)
        box.set_size_request(560, -1)
        box.append(label("Your Cities", "page-title", xalign=0))
        self.city_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.city_list.add_css_class("grouped")
        self.city_list.connect("row-activated", lambda _l, row: self._choose_city(row.index))
        box.append(self.city_list)
        add = Gtk.Button(label="Add a City…", halign=Gtk.Align.START)
        add.add_css_class("glossy")
        add.connect("clicked", lambda *_: self.open_search())
        box.append(add)

        box.append(label("Temperature", "section-title", xalign=0))
        units = Gtk.Box(spacing=0, halign=Gtk.Align.START)
        units.add_css_class("linked")
        self.f_btn = Gtk.ToggleButton(label="°F  Fahrenheit")
        self.c_btn = Gtk.ToggleButton(label="°C  Celsius", group=self.f_btn)
        for b in (self.f_btn, self.c_btn):
            b.add_css_class("unit")
            units.append(b)
        (self.f_btn if self.settings.fahrenheit else self.c_btn).set_active(True)
        self.f_btn.connect("toggled", lambda b: self._set_units(b.get_active()))
        box.append(units)
        page.append(box)
        self.rebuild_cities()
        return page

    def rebuild_cities(self):
        self.city_list.remove_all()
        for i, p in enumerate(self.settings.places):
            row = Gtk.ListBoxRow(activatable=True)
            row.index = i
            r = Gtk.Box(spacing=12)
            t = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
            t.append(label(p["name"], "row-title", xalign=0))
            t.append(label(", ".join(x for x in (p.get("region"), p.get("country")) if x), "row-sub", xalign=0))
            r.append(t)
            data = fc.cached(p)
            if data and data.get("current"):
                cur = data["current"]
                img = Gtk.Image(icon_name=fc.describe(cur.get("weather_code"), bool(cur.get("is_day", 1)))[1],
                                pixel_size=24)
                img.add_css_class("row-icon")
                r.append(img)
                r.append(label(f"{round(cur['temperature_2m'])}°", "row-temp"))
            rm = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER, tooltip_text="Remove")
            rm.add_css_class("flat")
            rm.connect("clicked", lambda *_, n=i: self._remove_city(n))
            r.append(rm)
            if i == self.settings.current:
                row.add_css_class("current")
            row.set_child(r)
            self.city_list.append(row)

    def toggle_cities(self):
        if self.stack.get_visible_child_name() == "cities" and self.settings.places:
            self.show_place()
        else:
            self.rebuild_cities()
            self.stack.set_visible_child_name("cities")
            self.title.set_label("Your Cities")
            self.cities_btn.set_label("Done")

    def _choose_city(self, i):
        self.settings.current = i
        self.settings.save()
        self.show_place()

    def _remove_city(self, i):
        self.settings.remove(i)
        self.rebuild_cities()
        if not self.settings.places:
            self.open_search()

    def _set_units(self, fahrenheit):
        if fahrenheit == self.settings.fahrenheit:
            return
        self.settings.fahrenheit = fahrenheit
        self.settings.save()
        self.refresh()

    # ---- showing a city's weather -------------------------------------------------
    def place(self):
        if not self.settings.places:
            return None
        return self.settings.places[self.settings.current]

    def show_place(self):
        p = self.place()
        if not p:
            self.open_search()
            return
        self.stack.set_visible_child_name("weather")
        self.title.set_label(p["name"])
        self.cities_btn.set_label("Cities")
        data = fc.cached(p)
        if data and data.get("_fahrenheit") == self.settings.fahrenheit:
            self.draw(data)
        else:
            self.data = None
            self.now_place.set_label(fc.place_label(p))
            self.now_temp.set_label("…")
            self.now_words.set_label("Getting the forecast")
            self.now_more.set_label("")
        self.refresh(only_if_stale=bool(data))

    def refresh(self, only_if_stale=False):
        p = self.place()
        if not p:
            return
        data = fc.cached(p)
        fresh = data and time.time() - data.get("_fetched", 0) < REFRESH_MINUTES * 60 \
            and data.get("_fahrenheit") == self.settings.fahrenheit
        if only_if_stale and fresh:
            return
        f = self.settings.fahrenheit

        def done(res, err):
            if self.place() is not p:
                return  # switched cities meanwhile
            if err:
                if not self.data:
                    self.now_words.set_label("No forecast right now")
                    self.now_more.set_label("Check that you're connected to the internet.")
                else:
                    self.toasts.add_toast(Adw.Toast(title="Couldn't update the forecast", timeout=3))
                return
            self.draw(res)

        run_in_thread(lambda: fc.forecast(p, f), done)

    def draw(self, data):
        self.data = data
        p = self.place()
        cur = data.get("current") or {}
        day = bool(cur.get("is_day", 1))
        code = cur.get("weather_code", 0)
        words, icon = fc.describe(code, day)
        for m in MOODS:
            self.sky.remove_css_class(m)
        self.sky.add_css_class(fc.mood(code, day))

        unit = "°"
        wind_unit = "mph" if data.get("_fahrenheit") else "km/h"
        daily = data.get("daily") or {}
        hi = (daily.get("temperature_2m_max") or [None])[0]
        lo = (daily.get("temperature_2m_min") or [None])[0]
        self.now_icon.set_from_icon_name(icon)
        self.now_place.set_label(fc.place_label(p))
        self.now_temp.set_label(f"{round(cur.get('temperature_2m', 0))}{unit}")
        self.now_words.set_label(words)
        bits = []
        if hi is not None and lo is not None:
            bits.append(f"High {round(hi)}°  ·  Low {round(lo)}°")
        if "apparent_temperature" in cur:
            bits.append(f"Feels like {round(cur['apparent_temperature'])}°")
        if "wind_speed_10m" in cur:
            bits.append(f"Wind {round(cur['wind_speed_10m'])} {wind_unit}")
        if "relative_humidity_2m" in cur:
            bits.append(f"Humidity {round(cur['relative_humidity_2m'])}%")
        self.now_more.set_label("   ".join(bits))

        self._draw_hours(data)
        self._draw_days(data)
        fetched = datetime.fromtimestamp(data.get("_fetched", time.time()))
        self.updated.set_label(f"Updated {fetched.strftime('%-I:%M %p')}")

    def _draw_hours(self, data):
        child = self.hours.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.hours.remove(child)
            child = nxt
        h = data.get("hourly") or {}
        times = h.get("time") or []
        now_local = (data.get("current") or {}).get("time", "")[:13]  # "2026-10-27T12"
        start = next((i for i, t in enumerate(times) if t[:13] >= now_local), 0)
        for i in range(start, min(start + 24, len(times))):
            t = datetime.fromisoformat(times[i])
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            col.add_css_class("hour")
            col.append(label("Now" if i == start else t.strftime("%-I %p"), "hour-time"))
            day = bool((h.get("is_day") or [1] * len(times))[i])
            img = Gtk.Image(icon_name=fc.describe((h.get("weather_code") or [0])[i], day)[1], pixel_size=28)
            img.add_css_class("hour-icon")
            col.append(img)
            col.append(label(f"{round((h.get('temperature_2m') or [0])[i])}°", "hour-temp"))
            rain = (h.get("precipitation_probability") or [None] * len(times))[i]
            col.append(label(f"{rain}%" if rain else " ", "hour-rain"))
            self.hours.append(col)

    def _draw_days(self, data):
        child = self.days.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.days.remove(child)
            child = nxt
        d = data.get("daily") or {}
        times = d.get("time") or []
        highs, lows = d.get("temperature_2m_max") or [], d.get("temperature_2m_min") or []
        if not times or not highs:
            return
        week_lo, week_hi = min(lows), max(highs)
        span = max(1.0, week_hi - week_lo)
        for i, day in enumerate(times):
            row = Gtk.Box(spacing=14)
            row.add_css_class("day")
            name = "Today" if i == 0 else datetime.fromisoformat(day).strftime("%A")
            row.append(label(name, "day-name", xalign=0, width_chars=10))
            img = Gtk.Image(icon_name=fc.describe((d.get("weather_code") or [0])[i], True)[1], pixel_size=26)
            img.add_css_class("day-icon")
            row.append(img)
            rain = (d.get("precipitation_probability_max") or [None] * len(times))[i]
            row.append(label(f"{rain}%" if rain else "", "day-rain", width_chars=4, xalign=0))
            row.append(label(f"{round(lows[i])}°", "day-lo", width_chars=4, xalign=1))
            bar = Gtk.Box(hexpand=True, valign=Gtk.Align.CENTER)
            bar.add_css_class("range")
            left = Gtk.Box()
            left.set_hexpand(False)
            fill = Gtk.Box()
            fill.add_css_class("range-fill")
            # Lay the day's low–high out on the week's scale.
            lw = int(200 * (lows[i] - week_lo) / span)
            fw = max(8, int(200 * (highs[i] - lows[i]) / span))
            left.set_size_request(lw, 6)
            fill.set_size_request(fw, 6)
            bar.append(left)
            bar.append(fill)
            bar.set_size_request(200, 6)
            row.append(bar)
            row.append(label(f"{round(highs[i])}°", "day-hi", width_chars=4, xalign=0))
            self.days.append(row)

    def _key(self, _c, keyval, _code, state):
        if keyval == Gdk.KEY_Escape and self.stack.get_visible_child_name() != "weather":
            self.close_search()
            return True
        if keyval == Gdk.KEY_f and state & Gdk.ModifierType.CONTROL_MASK:
            self.open_search()
            return True
        if keyval == Gdk.KEY_F5:
            self.refresh()
            return True
        return False


def main():
    return WeatherApp().run(sys.argv)
