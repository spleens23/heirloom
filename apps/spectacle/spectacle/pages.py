"""The five tabs and the channel page."""

from __future__ import annotations

import os
import shutil
import threading

from gi.repository import Gio, GLib, Gtk, Pango

from . import images
from .models import Channel, fmt_count, fmt_duration
from .paths import DOWNLOAD_DIR
from .widgets import (Thumb, VideoGrid, avatar, bar_button, empty_state, glossy_button,
                      loading_view, scroller, section_title)


def run_async(work, done, error=None):
    """Run work() on a thread; call done(result) or error(exc) on the main thread."""
    def target():
        try:
            result = work()
        except Exception as e:  # noqa: BLE001
            GLib.idle_add(lambda: ((error or (lambda _e: None))(e), False)[1])
            return
        GLib.idle_add(lambda: (done(result), False)[1])
    threading.Thread(target=target, daemon=True).start()


class Swappable(Gtk.Box):
    """A page body that switches between loading / content / empty views."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, vexpand=True)
        self.add_css_class("spectacle-page")

    def show(self, widget: Gtk.Widget):
        child = self.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.remove(child)
            child = nxt
        self.append(widget)


# ---- Subscriptions feed (home) ------------------------------------------

class HomePage(Swappable):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.grid = VideoGrid(app)
        self._loaded_for: tuple | None = None
        self.actions = [bar_button(icon="spectacle-refresh-symbolic", tooltip="Refresh", on_click=self.refresh)]
        app.library.connect(self._lib_changed)
        self.refresh()

    def _lib_changed(self, what):
        if what == "subscriptions":
            self.refresh(quiet=True)

    def refresh(self, quiet=False):
        subs = list(self.app.library.subscriptions)
        if not subs:
            self.show(empty_state(
                "spectacle-video-symbolic", "Welcome to Spectacle",
                "Subscribe to channels and their newest videos will gather here. "
                "Search for a channel, or bring your subscriptions over from Google Takeout.",
                [glossy_button("Find Channels", lambda: self.app.switch_tab("search")),
                 glossy_button("Import Subscriptions", self.app.import_takeout, "subscribed")]))
            return
        key = tuple(c.id for c in subs)
        if quiet and key == self._loaded_for:
            return
        if not self.grid.videos:
            self.show(loading_view("Gathering new videos…"))
        # Only the newest refresh gets to update the screen.
        self._token = getattr(self, "_token", 0) + 1
        token = self._token

        def done(result):
            if token != self._token:
                return
            videos, failed = result
            self._loaded_for = key
            if not videos:
                self.show(empty_state("spectacle-offline-symbolic", "Nothing to show",
                                      "Couldn't reach YouTube. Check your Wi-Fi and tap Refresh."))
                return
            self.grid = VideoGrid(self.app)
            self.grid.set_videos(videos[:150])
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            box.append(section_title(f"Latest from {len(subs)} channel{'s' if len(subs) != 1 else ''}"))
            box.append(self.grid)
            self.show(scroller(box))
            if failed:
                self.app.toast(f"Couldn't load {len(failed)} channel{'s' if len(failed) != 1 else ''}")

        def error(e):
            self.show(empty_state("spectacle-offline-symbolic", "Couldn't load your feed", str(e)))

        run_async(lambda: self.app.yt.subscription_feed(subs), done, error)


# ---- Search ---------------------------------------------------------------

class SearchPage(Gtk.Box):
    def __init__(self, app):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.add_css_class("spectacle-page")
        self.app = app
        self.actions = []

        strip = Gtk.Box()
        strip.add_css_class("search-strip")
        self.entry = Gtk.SearchEntry(hexpand=True, placeholder_text="Search videos and channels")
        self.entry.connect("activate", lambda *_: self.search())
        strip.append(self.entry)
        self.append(strip)

        self.body = Swappable()
        self.append(self.body)
        self.body.show(empty_state("spectacle-search-symbolic", "Search",
                                   "Find videos to watch, or channels to subscribe to."))
        self.grid = VideoGrid(app)
        self._token = 0

    def focus(self):
        self.entry.grab_focus()

    def search(self):
        q = self.entry.get_text().strip()
        if not q:
            return
        self._token += 1
        token = self._token
        self.body.show(loading_view(f"Searching for “{q}”…"))
        results = {}

        def finish():
            if token != self._token or len(results) < 2:
                return
            videos, channels = results["v"], results["c"]
            if isinstance(videos, Exception):
                self.body.show(empty_state("spectacle-warning-symbolic", "Search didn't work",
                                           "Check your connection. If it keeps happening, update yt-dlp "
                                           "(see the README)."))
                return
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            if channels and not isinstance(channels, Exception):
                box.append(section_title("Channels"))
                strip = Gtk.Box(spacing=12, margin_start=18, margin_end=18)
                for ch in channels:
                    strip.append(self._channel_chip(ch))
                sw = Gtk.ScrolledWindow(vscrollbar_policy=Gtk.PolicyType.NEVER, min_content_height=118)
                sw.set_child(strip)
                box.append(sw)
            box.append(section_title("Videos"))
            self.grid = VideoGrid(self.app)
            self.grid.set_videos(videos)
            box.append(self.grid)
            self.body.show(scroller(box))

        def got(kind):
            def cb(val):
                results[kind] = val
                finish()
            return cb

        run_async(lambda: self.app.yt.search(q), got("v"), got("v"))
        run_async(lambda: self.app.yt.search_channels(q), got("c"), got("c"))

    def _channel_chip(self, ch: Channel) -> Gtk.Button:
        btn = Gtk.Button()
        btn.add_css_class("card")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=4)
        box.append(avatar(ch.name, ch.avatar, 56))
        lbl = Gtk.Label(label=ch.name, ellipsize=Pango.EllipsizeMode.END, max_width_chars=12)
        lbl.add_css_class("card-meta")
        box.append(lbl)
        btn.set_child(box)
        btn.set_size_request(118, -1)
        btn.connect("clicked", lambda *_: self.app.open_channel(ch.id, ch.name))
        return btn


# ---- Channel page -----------------------------------------------------------

class ChannelPage(Swappable):
    def __init__(self, app, channel_id: str, name: str = ""):
        super().__init__()
        self.app = app
        self.channel_id = channel_id
        self.channel: Channel | None = None
        self.show(loading_view(f"Opening {name or 'channel'}…"))
        run_async(lambda: app.yt.channel_page(channel_id), self._loaded,
                  lambda e: self.show(empty_state("spectacle-warning-symbolic", "Couldn't open this channel", str(e))))

    def _loaded(self, ch: Channel):
        self.channel = ch
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        header = Gtk.Box(spacing=18)
        header.add_css_class("channel-header")
        header.append(avatar(ch.name, ch.avatar, 84))
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER, hexpand=True)
        name = Gtk.Label(label=ch.name, xalign=0, ellipsize=Pango.EllipsizeMode.END)
        name.add_css_class("channel-name")
        info.append(name)
        sub_line = fmt_count(ch.subscribers, "subscribers")
        if sub_line:
            s = Gtk.Label(label=sub_line, xalign=0)
            s.add_css_class("hint")
            info.append(s)
        if ch.description:
            d = Gtk.Label(label=ch.description, xalign=0, wrap=True, lines=2,
                          ellipsize=Pango.EllipsizeMode.END, max_width_chars=60)
            d.add_css_class("card-meta")
            info.append(d)
        header.append(info)
        self.sub_btn = glossy_button("", self._toggle_sub)
        self.sub_btn.set_valign(Gtk.Align.CENTER)
        self._sync_sub()
        header.append(self.sub_btn)
        box.append(header)

        box.append(section_title("Videos"))
        grid = VideoGrid(self.app, show_channel=False)
        grid.set_videos(ch.videos)
        box.append(grid)
        self.show(scroller(box))

    def _sync_sub(self):
        subbed = self.app.library.is_subscribed(self.channel_id)
        self.sub_btn.set_label("✓  Subscribed" if subbed else "Subscribe")
        (self.sub_btn.add_css_class if subbed else self.sub_btn.remove_css_class)("subscribed")

    def _toggle_sub(self):
        lib = self.app.library
        if lib.is_subscribed(self.channel_id):
            lib.unsubscribe(self.channel_id)
            self.app.toast(f"Unsubscribed from {self.channel.name}")
        else:
            lib.subscribe(self.channel)
            self.app.toast(f"Subscribed to {self.channel.name}")
        self._sync_sub()


# ---- Channels (manage subscriptions) ---------------------------------------

class ChannelsPage(Swappable):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.editing = False
        self.edit_btn = bar_button("Edit", on_click=self._toggle_edit)
        self.add_btn = bar_button(icon="spectacle-add-symbolic", tooltip="Add or import channels", on_click=self._add_menu)
        self.actions = [self.add_btn, self.edit_btn]
        app.library.connect(lambda what: what == "subscriptions" and self.rebuild())
        self.rebuild()

    def _toggle_edit(self):
        self.editing = not self.editing
        self.edit_btn.set_label("Done" if self.editing else "Edit")
        self.rebuild()

    def rebuild(self):
        subs = self.app.library.subscriptions
        if not subs:
            self.show(empty_state("spectacle-channels-symbolic", "No channels yet",
                                  "Channels you subscribe to are listed here.",
                                  [glossy_button("Add Channel", self._add_by_handle),
                                   glossy_button("Import Subscriptions", self.app.import_takeout, "subscribed")]))
            return
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(section_title(f"{len(subs)} subscription{'s' if len(subs) != 1 else ''}"))
        lst = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        lst.add_css_class("grouped")
        for ch in subs:
            row = Gtk.ListBoxRow(activatable=not self.editing)
            line = Gtk.Box(spacing=12)
            line.append(avatar(ch.name, ch.avatar, 40))
            t = Gtk.Label(label=ch.name, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
            t.add_css_class("row-title")
            line.append(t)
            if self.editing:
                rm = glossy_button("Unsubscribe", lambda c=ch: self.app.library.unsubscribe(c.id), "danger")
                rm.set_valign(Gtk.Align.CENTER)
                line.append(rm)
            else:
                line.append(Gtk.Image.new_from_icon_name("spectacle-chevron-symbolic"))
            row.set_child(line)
            row.channel = ch
            lst.append(row)
        lst.connect("row-activated", lambda _l, r: self.app.open_channel(r.channel.id, r.channel.name))
        box.append(lst)
        self.show(scroller(box))

    def _add_menu(self):
        dialog = _choice_dialog(self.app.window, "Add Channels", "How would you like to add channels?",
                                [("Add by @handle or link", self._add_by_handle),
                                 ("Import from Google Takeout", self.app.import_takeout)])
        dialog.present()

    def _add_by_handle(self):
        win = Gtk.Window(transient_for=self.app.window, modal=True, title="Add Channel", default_width=420)
        win.add_css_class("spectacle")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=18, margin_bottom=18,
                      margin_start=18, margin_end=18)
        lbl = Gtk.Label(label="Type a channel's @handle, or paste its link.", wrap=True, xalign=0)
        lbl.add_css_class("hint")
        box.append(lbl)
        entry = Gtk.Entry(placeholder_text="@channelname")
        entry.add_css_class("search-field")
        box.append(entry)
        status = Gtk.Label(xalign=0)
        status.add_css_class("hint")
        box.append(status)
        go = glossy_button("Add")
        box.append(go)
        win.set_child(box)

        def submit(*_):
            text = entry.get_text().strip()
            if not text:
                return
            status.set_label("Looking it up…")
            go.set_sensitive(False)

            def work():
                cid = self.app.yt.resolve_channel_id(text)
                if not cid:
                    raise ValueError("No channel found")
                return self.app.yt.channel_page(cid, limit=1)

            def done(ch):
                self.app.library.subscribe(ch)
                self.app.toast(f"Subscribed to {ch.name}")
                win.close()

            def error(_e):
                status.set_label("Couldn't find that channel. Check the spelling.")
                go.set_sensitive(True)

            run_async(work, done, error)

        go.connect("clicked", submit)
        entry.connect("activate", submit)
        win.present()


def _choice_dialog(parent, title, text, choices):
    win = Gtk.Window(transient_for=parent, modal=True, title=title, default_width=380)
    win.add_css_class("spectacle")
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=18, margin_bottom=18,
                  margin_start=18, margin_end=18)
    lbl = Gtk.Label(label=text, wrap=True)
    lbl.add_css_class("hint")
    box.append(lbl)
    for label, fn in choices:
        def make(f=fn):
            return lambda: (win.close(), f())
        b = glossy_button(label, make())
        b.set_halign(Gtk.Align.FILL)
        box.append(b)
    cancel = glossy_button("Cancel", win.close, "subscribed")
    cancel.set_halign(Gtk.Align.FILL)
    box.append(cancel)
    win.set_child(box)
    return win


# ---- Watch Later ------------------------------------------------------------

class WatchLaterPage(Swappable):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.actions = []
        self.grid = VideoGrid(app)
        app.library.connect(lambda what: what == "watch_later" and self.rebuild())
        self.rebuild()

    def rebuild(self):
        items = self.app.library.watch_later
        if not items:
            self.show(empty_state("spectacle-later-symbolic", "Nothing saved",
                                  "Tap the clock on any video to save it for later."))
            return
        self.grid = VideoGrid(self.app)
        self.grid.set_videos(items)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(section_title(f"{len(items)} saved video{'s' if len(items) != 1 else ''}"))
        box.append(self.grid)
        self.show(scroller(box))


# ---- Downloads --------------------------------------------------------------

class DownloadsPage(Swappable):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.actions = [bar_button(icon="spectacle-folder-symbolic", tooltip="Open the downloads folder",
                                   on_click=lambda: Gtk.FileLauncher.new(Gio.File.new_for_path(str(DOWNLOAD_DIR)))
                                   .launch(app.window, None, None))]
        self._rows: dict[str, tuple[Gtk.ProgressBar, Gtk.Label]] = {}
        app.library.connect(lambda what: what == "downloads" and self.rebuild())
        app.downloads.connect(self._job_changed)
        self.rebuild()

    def _job_changed(self, job):
        widgets = self._rows.get(job.video.id)
        if widgets and not job.done:
            bar, status = widgets
            bar.set_fraction(job.progress)
            status.set_label(job.status)
        else:
            self.rebuild()

    def rebuild(self):
        self._rows.clear()
        active = [j for j in self.app.downloads.jobs.values() if not j.done or j.failed]
        done = self.app.library.downloads
        if not active and not done:
            self.show(empty_state("spectacle-download-symbolic", "No downloads",
                                  "Tap the download arrow on any video to keep it for offline viewing."))
            return
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        if active:
            box.append(section_title("Downloading"))
            lst = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
            lst.add_css_class("grouped")
            for job in active:
                lst.append(self._job_row(job))
            box.append(lst)
        if done:
            box.append(section_title(f"On this device · {_disk_summary(done)}"))
            lst = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
            lst.add_css_class("grouped")
            for v in done:
                lst.append(self._done_row(v))
            lst.connect("row-activated", lambda _l, r: self.app.play(r.video, queue=list(done)))
            box.append(lst)
        self.show(scroller(box))

    def _thumb(self, video):
        frame = Gtk.Box()
        frame.add_css_class("thumb-frame")
        frame.set_overflow(Gtk.Overflow.HIDDEN)
        pic = Thumb(112, 63)
        frame.append(pic)
        images.load(video.thumb_url, pic.set_paintable)
        return frame

    def _job_row(self, job):
        row = Gtk.ListBoxRow(activatable=False)
        line = Gtk.Box(spacing=12)
        line.append(self._thumb(job.video))
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5, hexpand=True, valign=Gtk.Align.CENTER)
        t = Gtk.Label(label=job.video.title, xalign=0, ellipsize=Pango.EllipsizeMode.END)
        t.add_css_class("row-title")
        col.append(t)
        bar = Gtk.ProgressBar(fraction=job.progress)
        bar.add_css_class("download")
        col.append(bar)
        status = Gtk.Label(label=job.status, xalign=0)
        status.add_css_class("row-sub")
        col.append(status)
        line.append(col)
        if job.failed:
            retry = glossy_button("Retry", lambda: (self.app.downloads.jobs.pop(job.video.id, None),
                                                    self.app.download(job.video)))
            retry.set_valign(Gtk.Align.CENTER)
            line.append(retry)
        else:
            cancel = glossy_button("Cancel", lambda: self.app.downloads.cancel(job.video.id), "subscribed")
            cancel.set_valign(Gtk.Align.CENTER)
            line.append(cancel)
        row.set_child(line)
        self._rows[job.video.id] = (bar, status)
        return row

    def _done_row(self, video):
        row = Gtk.ListBoxRow()
        row.video = video
        line = Gtk.Box(spacing=12)
        line.append(self._thumb(video))
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, hexpand=True, valign=Gtk.Align.CENTER)
        t = Gtk.Label(label=video.title, xalign=0, ellipsize=Pango.EllipsizeMode.END)
        t.add_css_class("row-title")
        col.append(t)
        size = _size(video.local_path)
        sub = "  ·  ".join(b for b in (video.channel, fmt_duration(video.duration), size) if b)
        s = Gtk.Label(label=sub, xalign=0, ellipsize=Pango.EllipsizeMode.END)
        s.add_css_class("row-sub")
        col.append(s)
        line.append(col)
        rm = Gtk.Button(icon_name="spectacle-trash-symbolic", tooltip_text="Delete download", valign=Gtk.Align.CENTER)
        rm.add_css_class("pill")
        rm.connect("clicked", lambda *_: self._confirm_delete(video))
        line.append(rm)
        row.set_child(line)
        return row

    def _confirm_delete(self, video):
        _choice_dialog(self.app.window, "Delete Download", f"Delete “{video.title}” from this device?",
                       [("Delete", lambda: self.app.library.remove_download(video.id))]).present()


def _size(path):
    try:
        return f"{os.path.getsize(path) / 1e6:.0f} MB"
    except OSError:
        return ""


def _disk_summary(videos):
    total = sum(os.path.getsize(v.local_path) for v in videos if os.path.exists(v.local_path))
    free = shutil.disk_usage(DOWNLOAD_DIR).free
    return f"{total / 1e9:.1f} GB used, {free / 1e9:.0f} GB free"
