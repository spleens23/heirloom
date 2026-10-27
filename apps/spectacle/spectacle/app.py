"""Spectacle's application and main window."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, APP_NAME, VERSION  # noqa: E402
from .downloads import DownloadManager  # noqa: E402
from .library import Library  # noqa: E402
from .pages import (ChannelPage, ChannelsPage, DownloadsPage, HomePage,  # noqa: E402
                    SearchPage, WatchLaterPage)
from .player import PlayerView  # noqa: E402
from .widgets import NavController, TabBar  # noqa: E402

HERE = Path(__file__).resolve().parent


class SpectacleApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        GLib.set_application_name(APP_NAME)
        self.window = None
        self.autoplay = True
        if os.environ.get("SPECTACLE_DEMO"):
            from . import demo as yt
        else:
            from . import youtube as yt
        self.yt = yt

    def do_startup(self):
        Adw.Application.do_startup(self)
        # Light theme always: the look is designed around it.
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        css = Gtk.CssProvider()
        css.load_from_path(str(HERE / "style.css"))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        # Spectacle ships its own icon set so it looks the same everywhere.
        Gtk.IconTheme.get_for_display(Gdk.Display.get_default()).add_search_path(str(HERE / "icons"))
        self.library = Library()
        self.downloads = DownloadManager(self.library)
        for name, keys, fn in (("quit", ["<Ctrl>q"], lambda *_: self.quit()),
                               ("search", ["<Ctrl>f", "<Ctrl>l"], lambda *_: self.switch_tab("search")),
                               ("fullscreen", ["F11"], lambda *_: self.toggle_fullscreen())):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", fn)
            self.add_action(act)
            self.set_accels_for_action(f"app.{name}", keys)

    def do_activate(self):
        if not self.window:
            self.window = MainWindow(self)
        self.window.present()

    # ---- helpers used across the app ------------------------------------
    def toast(self, text: str):
        if self.window:
            self.window.toasts.add_toast(Adw.Toast(title=text, timeout=2))

    def switch_tab(self, name: str):
        self.window.tabbar.select(name)
        if name == "search":
            GLib.idle_add(lambda: (self.window.search_page.focus(), False)[1])

    def current_nav(self) -> NavController:
        return self.window.navs[self.window.current_tab]

    def open_channel(self, channel_id: str, name: str = ""):
        if self.player_visible():
            self.close_player()
        self.current_nav().push(ChannelPage(self, channel_id, name), name or "Channel")

    def play(self, video, queue=None):
        self.window.show_player(video, queue)

    def player_visible(self) -> bool:
        return self.window.root.get_visible_child_name() == "player"

    def close_player(self):
        self.window.hide_player()

    def toggle_fullscreen(self):
        w = self.window
        w.unfullscreen() if w.is_fullscreen() else w.fullscreen()

    def download(self, video):
        if self.library.downloaded(video.id):
            self.toast("Already downloaded")
            return
        job = self.downloads.start(video)
        if job:
            self.toast("Downloading — see the Downloads tab")

    def import_takeout(self):
        dialog = Gtk.FileDialog(title="Choose subscriptions.csv from your Google Takeout")
        f = Gtk.FileFilter()
        f.set_name("Takeout subscriptions (CSV)")
        f.add_pattern("*.csv")
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(f)
        dialog.set_filters(store)

        def chosen(dlg, res):
            try:
                file = dlg.open_finish(res)
            except GLib.Error:
                return
            try:
                n = self.library.import_takeout_csv(file.get_path())
                self.toast(f"Imported {n} channel{'s' if n != 1 else ''}")
            except Exception:  # noqa: BLE001
                self.toast("That file doesn't look like a Takeout subscriptions list")

        dialog.open(self.window, None, chosen)


class MainWindow(Adw.ApplicationWindow):
    TABS = [
        ("home", "Subscriptions", "spectacle-home-symbolic"),
        ("search", "Search", "spectacle-search-symbolic"),
        ("channels", "Channels", "spectacle-channels-symbolic"),
        ("later", "Watch Later", "spectacle-later-symbolic"),
        ("downloads", "Downloads", "spectacle-download-symbolic"),
    ]

    def __init__(self, app: SpectacleApp):
        super().__init__(application=app, title=APP_NAME, default_width=1100, default_height=720)
        self.add_css_class("spectacle")
        self.app = app

        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)
        self.root = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=220)
        self.toasts.set_child(self.root)

        # Tabs
        shell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.tab_stack = Gtk.Stack(vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE,
                                   transition_duration=150)
        shell.append(self.tab_stack)
        self.tabbar = TabBar(self._switch)
        shell.append(self.tabbar)
        self.root.add_named(shell, "tabs")

        self.search_page = SearchPage(app)
        pages = {
            "home": HomePage(app),
            "search": self.search_page,
            "channels": ChannelsPage(app),
            "later": WatchLaterPage(app),
            "downloads": DownloadsPage(app),
        }
        self.navs: dict[str, NavController] = {}
        for name, label, icon in self.TABS:
            page = pages[name]
            nav = NavController(label, page, getattr(page, "actions", []))
            self.navs[name] = nav
            self.tab_stack.add_named(nav, name)
            self.tabbar.add_tab(name, label, icon)
            self.tabbar.tapped_again(name, nav.pop_to_root)
        self.current_tab = "home"
        self.tabbar.select("home")

        # Player
        self.player = PlayerView(app)
        self.root.add_named(self.player, "player")
        self._was_fullscreen = False

        self.connect("close-request", self._closing)

    def _switch(self, name: str):
        self.current_tab = name
        self.tab_stack.set_visible_child_name(name)

    def show_player(self, video, queue):
        self._was_fullscreen = self.is_fullscreen()
        self.root.set_visible_child_name("player")
        self.fullscreen()
        self.player.open(video, queue)

    def hide_player(self):
        self.root.set_visible_child_name("tabs")
        if not self._was_fullscreen:
            self.unfullscreen()

    def _closing(self, *_):
        if self.player.video:
            self.player._save_position()
        return False


def main():
    app = SpectacleApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
