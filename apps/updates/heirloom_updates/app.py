"""Software Update window.

All the real work is done by the `heirloom-update` command; this app runs it,
shows its progress, and asks for your password through the system prompt when
a step needs it.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from . import APP_ID  # noqa: E402

HERE = Path(__file__).resolve().parent


def update_cmd() -> str:
    return (os.environ.get("HEIRLOOM_UPDATE_CMD") or shutil.which("heirloom-update")
            or "/usr/bin/heirloom-update")


class UpdatesApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        GLib.set_application_name("Software Update")

    def do_startup(self):
        Adw.Application.do_startup(self)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        display = Gdk.Display.get_default()
        css = Gtk.CssProvider()
        css.load_from_path(str(HERE / "style.css"))
        Gtk.StyleContext.add_provider_for_display(display, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        Gtk.IconTheme.get_for_display(display).add_search_path(str(HERE / "icons"))

    def do_activate(self):
        win = self.props.active_window or UpdatesWindow(self)
        win.present()


class UpdatesWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Software Update", default_width=600, default_height=660)
        self.add_css_class("updates")
        self.busy = False
        self.status: dict = {}
        self._primary_action = None

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(root)

        # Glossy title bar with a Done button (works in tablet mode too).
        bar = Gtk.CenterBox()
        bar.add_css_class("navbar")
        done = Gtk.Button(label="Done", valign=Gtk.Align.CENTER)
        done.add_css_class("bar-button")
        done.connect("clicked", lambda *_: self.close())
        bar.set_start_widget(done)
        title = Gtk.Label(label="Software Update")
        title.add_css_class("navbar-title")
        bar.set_center_widget(title)
        handle = Gtk.WindowHandle(child=bar)
        root.append(handle)

        scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        root.append(scroll)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                       margin_top=16, margin_bottom=20, margin_start=20, margin_end=20)
        scroll.set_child(body)

        # ---- the main card -------------------------------------------------
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        card.add_css_class("card")
        top = Gtk.Box(spacing=16)
        icon = Gtk.Image(icon_name=APP_ID, pixel_size=84)
        top.append(icon)
        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, valign=Gtk.Align.CENTER, hexpand=True)
        name = Gtk.Label(label="Heirloom", xalign=0)
        name.add_css_class("product-name")
        info.append(name)
        self.version = Gtk.Label(label="", xalign=0)
        self.version.add_css_class("dim")
        info.append(self.version)
        top.append(info)
        card.append(top)

        self.message = Gtk.Label(label="", xalign=0, wrap=True)
        self.message.add_css_class("message")
        card.append(self.message)

        row = Gtk.Box(spacing=12)
        self.primary = Gtk.Button(label="Check for Updates")
        self.primary.add_css_class("glossy")
        self.primary.connect("clicked", lambda *_: self._primary_action and self._primary_action())
        row.append(self.primary)
        self.spinner = Gtk.Spinner(valign=Gtk.Align.CENTER)
        row.append(self.spinner)
        self.progress = Gtk.Label(label="", xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
        self.progress.add_css_class("dim")
        row.append(self.progress)
        card.append(row)
        body.append(card)

        # ---- other ways --------------------------------------------------------
        body.append(self._section("Other Ways to Update"))
        lst = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        lst.add_css_class("grouped")
        self.usb_btn = self._row(lst, "Update from a USB Stick",
                                 "Use an update file downloaded on another computer. Handy without Wi-Fi.",
                                 "Choose File…", self._choose_usb)
        self.undo_btn = self._row(lst, "Undo Last Update",
                                  "Go back to the version you had before. Your files stay as they are.",
                                  "Undo…", self._confirm_undo, plain=True)
        body.append(lst)

        # ---- details -------------------------------------------------------------
        body.append(self._section("Details"))
        self.log = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                                wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=8, bottom_margin=8,
                                left_margin=10, right_margin=10)
        self.log.add_css_class("log")
        log_scroll = Gtk.ScrolledWindow(min_content_height=130, child=self.log)
        log_scroll.add_css_class("log-frame")
        exp = Gtk.Expander(label="Show what's happening", child=log_scroll)
        exp.add_css_class("details")
        body.append(exp)

        note = Gtk.Label(wrap=True, xalign=0, margin_top=10, label=(
            "Updates never touch your files or apps. A new version starts the next time "
            "you restart, and the version before it stays on the startup menu just in case."))
        note.add_css_class("dim")
        body.append(note)

        self.refresh(then_check=True)

    # ---- small builders ------------------------------------------------------------
    def _section(self, text):
        lbl = Gtk.Label(label=text, xalign=0)
        lbl.add_css_class("section-title")
        return lbl

    def _row(self, lst, title, sub, button, fn, plain=False):
        line = Gtk.Box(spacing=12)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True, valign=Gtk.Align.CENTER)
        t = Gtk.Label(label=title, xalign=0)
        t.add_css_class("row-title")
        col.append(t)
        s = Gtk.Label(label=sub, xalign=0, wrap=True)
        s.add_css_class("row-sub")
        col.append(s)
        line.append(col)
        b = Gtk.Button(label=button, valign=Gtk.Align.CENTER)
        b.add_css_class("glossy")
        if plain:
            b.add_css_class("plain")
        b.connect("clicked", lambda *_: fn())
        line.append(b)
        lst.append(line)
        return b

    # ---- running heirloom-update ---------------------------------------------------
    def run(self, args, on_done, busy_text="", log=True):
        """Run heirloom-update with args; on_done(ok, output_lines)."""
        self._set_busy(True, busy_text)
        lines: list[str] = []
        try:
            proc = Gio.Subprocess.new([update_cmd(), *args],
                                      Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE)
        except GLib.Error as e:
            self._set_busy(False)
            self._append(f"Couldn't start heirloom-update: {e.message}")
            on_done(False, [])
            return
        stream = Gio.DataInputStream.new(proc.get_stdout_pipe())

        def read_line(*_):
            stream.read_line_async(GLib.PRIORITY_DEFAULT, None, got_line)

        def got_line(s, res):
            try:
                line, _len = s.read_line_finish_utf8(res)
            except GLib.Error:
                line = None
            if line is None:
                proc.wait_async(None, finished)
                return
            lines.append(line)
            if log:
                self._append(line)
            if not line.lstrip().startswith("{"):
                self.progress.set_label(line.strip())
            read_line()

        def finished(p, res):
            try:
                p.wait_finish(res)
            except GLib.Error:
                pass
            self._set_busy(False)
            ok = p.get_if_exited() and p.get_exit_status() == 0
            if p.get_if_exited() and p.get_exit_status() in (126, 127) and args[0] in ("apply", "usb", "rollback"):
                self.progress.set_label("Cancelled.")
            on_done(ok, lines)

        read_line()

    def _append(self, line):
        buf = self.log.get_buffer()
        buf.insert(buf.get_end_iter(), line + "\n")

    def _set_busy(self, busy, text=""):
        self.busy = busy
        self.spinner.set_spinning(busy)
        for b in (self.primary, self.usb_btn, self.undo_btn):
            b.set_sensitive(not busy)
        if busy:
            self.progress.set_label(text)
        else:
            self.undo_btn.set_sensitive(bool(self.status.get("rollback")))

    @staticmethod
    def _json(lines):
        for line in reversed(lines):
            if line.lstrip().startswith("{"):
                try:
                    return json.loads(line)
                except ValueError:
                    pass
        return None

    # ---- states --------------------------------------------------------------------
    def _set_primary(self, label, action):
        self.primary.set_label(label)
        self._primary_action = action

    def refresh(self, then_check=False):
        def done(ok, lines):
            st = self._json(lines) if ok else None
            self.status = st or {}
            self.progress.set_label("")
            self.undo_btn.set_sensitive(bool(self.status.get("rollback")))
            booted = self.status.get("booted") or {}
            self.version.set_label(_describe(booted) or "Version unknown")
            if self.status.get("pending"):
                self._show_ready()
            elif then_check:
                self.check()
            else:
                self.message.set_label("")
                self._set_primary("Check for Updates", self.check)
        self.run(["status", "--json"], done, "Looking at this computer…", log=False)

    def check(self):
        def done(ok, lines):
            res = self._json(lines) or {"state": "offline"}
            state = res.get("state")
            self.progress.set_label("")
            if state == "available":
                self.message.set_label("A new version of Heirloom is available.")
                self._set_primary("Download and Install", self.apply)
            elif state == "ready":
                self._show_ready()
            elif state == "current":
                self.message.set_label("Heirloom is up to date.")
                self._set_primary("Check Again", self.check)
            else:
                self.message.set_label("Couldn't reach the update server. Check your Wi-Fi, "
                                       "or update from a USB stick below.")
                self._set_primary("Try Again", self.check)
        self.run(["check", "--json"], done, "Checking for updates…", log=False)

    def apply(self):
        def done(ok, lines):
            if ok:
                self.refresh()
            else:
                self.message.set_label("The update didn't finish. Nothing has changed; you can try again.")
                self._set_primary("Try Again", self.apply)
        self.message.set_label("Downloading the new version. You can keep using your computer.")
        self.run(["apply"], done, "Downloading…")

    def _show_ready(self):
        pending = self.status.get("pending") or {}
        what = _describe(pending)
        self.message.set_label("Ready to finish: restart to start using the new version."
                               + (f"\n{what}" if what else ""))
        self._set_primary("Restart Now", self.restart)

    def restart(self):
        self.run(["restart"], lambda ok, lines: None, "Restarting…")

    # ---- USB ----------------------------------------------------------------------------
    def _choose_usb(self):
        dialog = Gtk.FileDialog(title="Choose the Heirloom update file")
        f = Gtk.FileFilter()
        f.set_name("Heirloom update files")
        f.add_pattern("*.ociarchive")
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(f)
        dialog.set_filters(store)
        media = Path("/run/media") / (os.environ.get("USER") or "")
        if media.is_dir():
            dialog.set_initial_folder(Gio.File.new_for_path(str(media)))

        def chosen(dlg, res):
            try:
                file = dlg.open_finish(res)
            except GLib.Error:
                return
            self.install_usb(file.get_path())

        dialog.open(self, None, chosen)

    def install_usb(self, path):
        def done(ok, lines):
            if ok:
                self.refresh()
            else:
                last = next((ln for ln in reversed(lines) if ln.startswith("Error:")), "")
                self.message.set_label(last.removeprefix("Error: ") or
                                       "Installing from the USB stick didn't work.")
                self._set_primary("Check for Updates", self.check)
        self.message.set_label("Installing the update from your USB stick. Leave it plugged in.")
        self.run(["usb", path], done, "Reading the USB stick…")

    # ---- undo ---------------------------------------------------------------------------
    def _confirm_undo(self):
        dlg = Adw.AlertDialog(heading="Undo the last update?",
                              body="Your previous version of Heirloom starts the next time you restart. "
                                   "Your files and apps stay as they are.")
        dlg.add_response("cancel", "Cancel")
        dlg.add_response("undo", "Undo Update")
        dlg.set_response_appearance("undo", Adw.ResponseAppearance.DESTRUCTIVE)
        dlg.connect("response", lambda _d, r: r == "undo" and self.undo())
        dlg.present(self)

    def undo(self):
        def done(ok, lines):
            if ok:
                self.refresh()
            else:
                self.message.set_label("There's no earlier version to go back to.")
        self.run(["rollback"], done, "Going back…")


def _describe(d: dict) -> str:
    if not d:
        return ""
    bits = []
    if d.get("version"):
        bits.append(f"Version {d['version']}")
    ts = d.get("timestamp")
    if ts:
        when = datetime.fromtimestamp(int(ts))
        bits.append(f"built {when:%B} {when.day}, {when:%Y}")
    return " · ".join(bits)


def main():
    return UpdatesApp().run(sys.argv)
