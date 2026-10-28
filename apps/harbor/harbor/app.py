"""Tablet Settings: wallpaper, the lock screen and its passcode.

(This used to be Harbor's home screen; in tablet mode the home screen is now the app
drawer, built into the shell. The drawer keeps using ~/.config/harbor/config.json.)

  harbor                    the settings window
  harbor --setup-passcode   choose a passcode, full screen (the first time you log in)
  harbor --setup-if-needed  the same, only if you don't have a passcode yet
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango  # noqa: E402

from . import APP_ID  # noqa: E402
from . import apps as appsmod  # noqa: E402
from .config import AUTOSTART_FILE, Config  # noqa: E402

HERE = Path(__file__).resolve().parent
WALLPAPERS = [("sky", "Sky"), ("dusk", "Dusk"), ("sea", "Sea"), ("meadow", "Meadow"), ("night", "Night")]
HELPER = os.environ.get("HEIRLOOM_LOCKSCREEN_HELPER", "/usr/libexec/heirloom-lockscreen")
PASSCODE_DIR = Path(os.environ.get("HEIRLOOM_PASSCODE_DIR", "/var/lib/heirloom/passcode"))
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "heirloom"


def wallpaper_path(name: str) -> Path:
    p = HERE / "wallpapers" / f"{name}.svg"
    return p if p.exists() else HERE / "wallpaper.svg"


def current_user() -> str:
    return GLib.get_user_name()


def passcode_length() -> int:
    try:
        n = int((PASSCODE_DIR / current_user()).read_text().strip())
        return n if n in (4, 6) else 0
    except (OSError, ValueError):
        return 0


def _settings(schema):
    source = Gio.SettingsSchemaSource.get_default()
    if source and source.lookup(schema, True):
        return Gio.Settings.new(schema)
    return None


def set_desktop_background(path: str):
    uri = Gio.File.new_for_path(path).get_uri()
    s = _settings("org.gnome.desktop.background")
    if s:
        s.set_string("picture-uri", uri)
        s.set_string("picture-uri-dark", uri)


def render_png(src: str, dest: Path, width=1920, height=1200) -> Path:
    """Any picture (SVG too) as a PNG filling width×height, for the lock screen."""
    pix = GdkPixbuf.Pixbuf.new_from_file(src)
    scale = max(width / pix.get_width(), height / pix.get_height())
    w, h = max(1, round(pix.get_width() * scale)), max(1, round(pix.get_height() * scale))
    if src.endswith(".svg"):
        pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(src, w, h, False)
    else:
        pix = pix.scale_simple(w, h, GdkPixbuf.InterpType.BILINEAR)
    x, y = max(0, (pix.get_width() - width) // 2), max(0, (pix.get_height() - height) // 2)
    pix = pix.new_subpixbuf(x, y, min(width, pix.get_width() - x), min(height, pix.get_height() - y))
    dest.parent.mkdir(parents=True, exist_ok=True)
    pix.savev(str(dest), "png", [], [])
    return dest


def run_helper(args, stdin_text=None):
    """Run the root helper through pkexec. Returns (ok, message)."""
    cmd = [HELPER, *args] if os.environ.get("HEIRLOOM_LOCKSCREEN_DIRECT") else ["pkexec", HELPER, *args]  # (direct: tests)
    try:
        r = subprocess.run(cmd, input=stdin_text, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    if r.returncode == 0:
        return True, ""
    if r.returncode == 3 or "WRONG_PASSWORD" in r.stderr:
        return False, "WRONG_PASSWORD"
    if r.returncode in (126, 127):
        return False, "Not allowed."
    return False, (r.stderr.strip() or "Something went wrong.").splitlines()[-1]


def change_keyring_password(old: str, new: str) -> bool:
    """Keep the login keyring (saved Wi-Fi and website passwords) opening with the new passcode."""
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        res = bus.call_sync("org.freedesktop.secrets", "/org/freedesktop/secrets",
                            "org.freedesktop.Secret.Service", "OpenSession",
                            GLib.Variant("(sv)", ("plain", GLib.Variant("s", ""))),
                            GLib.VariantType("(vo)"), Gio.DBusCallFlags.NONE, 5000, None)
        session = res.unpack()[1]

        def secret(text):
            return (session, b"", text.encode("utf-8"), "text/plain")

        bus.call_sync("org.freedesktop.secrets", "/org/freedesktop/secrets",
                      "org.gnome.keyring.InternalUnsupportedGuiltRiddenInterface", "ChangeWithMasterPassword",
                      GLib.Variant("(o(oayays)(oayays))",
                                   ("/org/freedesktop/secrets/collection/login", secret(old), secret(new))),
                      None, Gio.DBusCallFlags.NONE, 10000, None)
        return True
    except GLib.Error as e:
        print(f"Tablet Settings: couldn't update the keyring: {e.message}", file=sys.stderr)
        return False


# ---- a keypad, the same as on the lock screen ---------------------------------------

class Keypad(Gtk.Box):
    LETTERS = ["", "ABC", "DEF", "GHI", "JKL", "MNO", "PQRS", "TUV", "WXYZ"]

    def __init__(self, on_complete):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=18, halign=Gtk.Align.CENTER)
        self.add_css_class("keypad")
        self.length = 6
        self.code = ""
        self.on_complete = on_complete
        self.dots = Gtk.Box(spacing=18, halign=Gtk.Align.CENTER)
        self.append(self.dots)
        grid = Gtk.Grid(row_spacing=16, column_spacing=28, halign=Gtk.Align.CENTER)
        for n in range(1, 10):
            grid.attach(self._key(str(n), self.LETTERS[n - 1]), (n - 1) % 3, (n - 1) // 3, 1, 1)
        grid.attach(self._key("0", ""), 1, 3, 1, 1)
        delete = Gtk.Button(label="Delete", valign=Gtk.Align.CENTER)
        delete.add_css_class("keypad-text")
        delete.connect("clicked", lambda *_: self.erase())
        grid.attach(delete, 2, 3, 1, 1)
        self.append(grid)
        self.draw()

    def _key(self, digit, letters):
        b = Gtk.Button()
        b.add_css_class("keypad-key")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        d = Gtk.Label(label=digit)
        d.add_css_class("keypad-digit")
        box.append(d)
        letters_label = Gtk.Label(label=letters)
        letters_label.add_css_class("keypad-letters")
        box.append(letters_label)
        b.set_child(box)
        b.connect("clicked", lambda *_: self.type(digit))
        return b

    def set_length(self, n):
        self.length = n
        self.clear()

    def clear(self):
        self.code = ""
        self.draw()

    def type(self, digit):
        if len(self.code) >= self.length:
            return
        self.code += digit
        self.draw()
        if len(self.code) == self.length:
            code = self.code
            GLib.timeout_add(180, lambda: (self.on_complete(code), False)[1])

    def erase(self):
        self.code = self.code[:-1]
        self.draw()

    def draw(self):
        child = self.dots.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.dots.remove(child)
            child = nxt
        for i in range(self.length):
            dot = Gtk.Box()
            dot.add_css_class("keypad-dot")
            if i < len(self.code):
                dot.add_css_class("on")
            self.dots.append(dot)

    def shake(self):
        self.add_css_class("shake")
        GLib.timeout_add(400, lambda: (self.remove_css_class("shake"), False)[1])

    def key_pressed(self, keyval):
        ch = chr(Gdk.keyval_to_unicode(keyval) or 0)
        if ch.isdigit():
            self.type(ch)
            return True
        if keyval == Gdk.KEY_BackSpace:
            self.erase()
            return True
        return False


# ---- choosing a passcode ------------------------------------------------------------

class PasscodeWindow(Adw.ApplicationWindow):
    """Current password (or passcode) → new passcode → the same again → done."""

    def __init__(self, app, first_time=False):
        super().__init__(application=app, title="Passcode", default_width=900, default_height=760)
        self.add_css_class("passcode-window")
        self.first_time = first_time
        self.old = ""
        self.new = ""
        self.had_passcode = passcode_length()

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT, vexpand=True)
        self.set_content(self.stack)

        # 1. who you are
        self.stack.add_named(self._old_page(), "old")
        # 2 and 3. the new passcode, twice
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, valign=Gtk.Align.CENTER)
        self.title = Gtk.Label(label="Choose a Passcode")
        self.title.add_css_class("passcode-title")
        page.append(self.title)
        self.hint = Gtk.Label(label="")
        self.hint.add_css_class("passcode-hint")
        page.append(self.hint)
        length = Gtk.Box(halign=Gtk.Align.CENTER)
        length.add_css_class("linked")
        self.six = Gtk.ToggleButton(label="6 digits", active=True)
        self.four = Gtk.ToggleButton(label="4 digits", group=self.six)
        for b in (self.six, self.four):
            b.add_css_class("length")
            length.append(b)
        self.six.connect("toggled", lambda b: self.keypad.set_length(6 if b.get_active() else 4))
        self.length_row = length
        page.append(length)
        self.keypad = Keypad(self._entered)
        page.append(self.keypad)
        self.back_btn = Gtk.Button(label="Start Over", halign=Gtk.Align.CENTER)
        self.back_btn.add_css_class("keypad-text")
        self.back_btn.connect("clicked", lambda *_: self._restart())
        page.append(self.back_btn)
        self.stack.add_named(page, "new")
        # 4. done
        self.stack.add_named(self._done_page(), "done")

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)
        if first_time:
            self.fullscreen()

    def _old_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        page.set_size_request(460, -1)
        t = Gtk.Label(label="Set Up Your Passcode" if not self.had_passcode else "Change Passcode")
        t.add_css_class("passcode-title")
        page.append(t)
        msg = ("Heirloom unlocks with a 4- or 6-digit passcode. First, type the password you chose when you installed Heirloom."
               if not self.had_passcode else "Type your current passcode.")
        m = Gtk.Label(label=msg, wrap=True, justify=Gtk.Justification.CENTER, max_width_chars=44)
        m.add_css_class("passcode-hint")
        page.append(m)
        self.old_entry = Gtk.PasswordEntry(show_peek_icon=True, hexpand=True)
        self.old_entry.add_css_class("passcode-entry")
        self.old_entry.connect("activate", lambda *_: self._old_done())
        page.append(self.old_entry)
        self.old_error = Gtk.Label(label="")
        self.old_error.add_css_class("passcode-error")
        page.append(self.old_error)
        row = Gtk.Box(halign=Gtk.Align.CENTER, spacing=12)
        later = Gtk.Button(label="Not Now" if self.first_time else "Cancel")
        later.add_css_class("glossy")
        later.add_css_class("plain")
        later.connect("clicked", lambda *_: self.close())
        row.append(later)
        nxt = Gtk.Button(label="Next")
        nxt.add_css_class("glossy")
        nxt.connect("clicked", lambda *_: self._old_done())
        row.append(nxt)
        page.append(row)
        return page

    def _done_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
        t = Gtk.Label(label="Your Passcode Is Set")
        t.add_css_class("passcode-title")
        page.append(t)
        self.done_msg = Gtk.Label(label="", wrap=True, justify=Gtk.Justification.CENTER, max_width_chars=48)
        self.done_msg.add_css_class("passcode-hint")
        page.append(self.done_msg)
        ok = Gtk.Button(label="Done", halign=Gtk.Align.CENTER)
        ok.add_css_class("glossy")
        ok.connect("clicked", lambda *_: self.close())
        page.append(ok)
        return page

    def _key(self, _c, keyval, _code, _state):
        if self.stack.get_visible_child_name() == "new":
            return self.keypad.key_pressed(keyval)
        return False

    def _old_done(self):
        self.old = self.old_entry.get_text()
        if not self.old:
            self.old_error.set_label("Type your password first.")
            return
        self.old_error.set_label("")
        self._restart()
        self.stack.set_visible_child_name("new")

    def _restart(self):
        self.new = ""
        self.title.set_label("Choose a Passcode")
        self.hint.set_label("Pick 4 or 6 digits you'll remember.")
        self.length_row.set_visible(True)
        self.keypad.set_length(6 if self.six.get_active() else 4)

    def _entered(self, code):
        if not self.new:
            self.new = code
            self.title.set_label("Type It Again")
            self.hint.set_label("To make sure.")
            self.length_row.set_visible(False)
            self.keypad.clear()
            return
        if code != self.new:
            self.keypad.shake()
            self._restart()
            self.title.set_label("Those Didn't Match")
            self.hint.set_label("Choose a passcode again.")
            return
        self.title.set_label("Saving…")
        self.set_sensitive(False)
        old, new = self.old, code

        def work():
            ok, msg = run_helper(["passcode"], json.dumps({"old": old, "new": new}))
            keyring = change_keyring_password(old, new) if ok else False
            GLib.idle_add(lambda: (self._saved(ok, msg, keyring), False)[1])

        threading.Thread(target=work, daemon=True).start()

    def _saved(self, ok, msg, keyring):
        self.set_sensitive(True)
        if not ok:
            if msg == "WRONG_PASSWORD":
                self.old_error.set_label("That isn't right. Try again.")
                self.old_entry.set_text("")
                self.stack.set_visible_child_name("old")
                self.old_entry.grab_focus()
            else:
                self._restart()
                self.title.set_label("Couldn't Save the Passcode")
                self.hint.set_label(msg)
            return
        extra = "" if keyring else (" Your saved passwords (Wi-Fi, websites) may ask for your old password once, "
                                    "the next time you log in.")
        self.done_msg.set_label("Use it to unlock Heirloom, log in, and approve updates and changes." + extra)
        self.stack.set_visible_child_name("done")


# ---- the settings window -----------------------------------------------------------

class SettingsWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Tablet Settings", default_width=720, default_height=760)
        self.add_css_class("harbor-settings")
        self.config = Config()
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        bar = Gtk.CenterBox()
        bar.add_css_class("navbar")
        t = Gtk.Label(label="Tablet Settings")
        t.add_css_class("navbar-title")
        bar.set_center_widget(t)
        root.append(bar)
        outer = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=24,
                           margin_start=24, margin_end=24, halign=Gtk.Align.CENTER)
        self.box.set_size_request(600, -1)
        outer.set_child(self.box)
        root.append(outer)
        self.toasts = Adw.ToastOverlay(child=root)
        self.set_content(self.toasts)
        self.build()

    def toast(self, text):
        self.toasts.add_toast(Adw.Toast(title=text, timeout=3))

    def _title(self, text):
        lbl = Gtk.Label(label=text, xalign=0)
        lbl.add_css_class("settings-title")
        return lbl

    def _note(self, text):
        lbl = Gtk.Label(label=text, xalign=0, wrap=True)
        lbl.add_css_class("dim-label")
        return lbl

    def _gallery(self, current, on_pick):
        gallery = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                              min_children_per_line=3, max_children_per_line=5, column_spacing=8, row_spacing=8)
        swatches = {}
        for name, label in WALLPAPERS:
            b = Gtk.Button(tooltip_text=label)
            b.add_css_class("wallpaper-swatch")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            pic = Gtk.Picture.new_for_filename(str(wallpaper_path(name)))
            pic.set_content_fit(Gtk.ContentFit.COVER)
            pic.set_size_request(120, 76)
            inner.append(pic)
            inner.append(Gtk.Label(label=label))
            b.set_child(inner)
            b.connect("clicked", lambda *_, n=name: on_pick(n))
            gallery.append(b)
            swatches[name] = b

        def mark(cur):
            for n, b in swatches.items():
                (b.add_css_class if n == cur else b.remove_css_class)("chosen")
        mark(current)
        return gallery, mark

    def build(self):
        box = self.box

        # Wallpaper (behind the open-apps view, and the laptop desktop)
        box.append(self._title("Wallpaper"))
        box.append(self._note("Behind your open apps, and on the desktop in laptop mode."))
        gallery, self._mark_wall = self._gallery(self.config.wallpaper or "sky", self._set_wallpaper)
        box.append(gallery)
        pick = Gtk.Button(label="Choose Picture…", halign=Gtk.Align.START)
        pick.add_css_class("glossy")
        pick.connect("clicked", lambda *_: self._choose_picture(self._set_wallpaper))
        box.append(pick)

        # Lock screen
        box.append(self._title("Lock Screen"))
        box.append(self._note("The picture on the lock screen, and behind the passcode keypad when you log in."))
        gallery, self._mark_lock = self._gallery(self._lock_choice(), self._set_lock_wallpaper)
        box.append(gallery)
        pick2 = Gtk.Button(label="Choose Picture…", halign=Gtk.Align.START)
        pick2.add_css_class("glossy")
        pick2.connect("clicked", lambda *_: self._choose_picture(self._set_lock_wallpaper))
        box.append(pick2)

        # Passcode
        box.append(self._title("Passcode"))
        n = passcode_length()
        box.append(self._note(f"You unlock Heirloom with a {n}-digit passcode." if n else
                              "You don't have a passcode yet: Heirloom still asks for your password."))
        change = Gtk.Button(label="Change Passcode…" if n else "Set Up Passcode…", halign=Gtk.Align.START)
        change.add_css_class("glossy")
        change.connect("clicked", lambda *_: PasscodeWindow(self.get_application()).present())
        box.append(change)

        # The app drawer
        box.append(self._title("App Drawer"))
        box.append(self._note("Swipe up from the bottom edge for your apps. Tap and hold an app there to add it to "
                              "Favorites or put it in a folder."))
        hidden = [a for a in appsmod.installed_apps() if a.get_id() in self.config.hidden]
        if hidden:
            box.append(self._note("Hidden apps:"))
            hl = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
            hl.add_css_class("grouped")
            for a in hidden:
                r = Gtk.Box(spacing=10)
                img = Gtk.Image(pixel_size=32)
                if a.get_icon():
                    img.set_from_gicon(a.get_icon())
                r.append(img)
                r.append(Gtk.Label(label=a.get_display_name(), xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END))
                show = Gtk.Button(label="Show", valign=Gtk.Align.CENTER)
                show.add_css_class("glossy")
                show.connect("clicked", lambda b, aid=a.get_id(), rr=r: self._unhide(aid, rr))
                r.append(show)
                hl.append(r)
            box.append(hl)

        # System
        try:
            updates = Gio.DesktopAppInfo.new("dev.heirloom.Updates.desktop")
        except TypeError:
            updates = None
        if updates:
            box.append(self._title("System"))
            upd = Gtk.Button(label="Software Update…", halign=Gtk.Align.START)
            upd.add_css_class("glossy")
            upd.connect("clicked", lambda *_: updates.launch([], None))
            box.append(upd)

    # ---- pictures ----
    def _choose_picture(self, then):
        dialog = Gtk.FileDialog(title="Choose a Picture")
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
            then(file.get_path())

        dialog.open(self, None, done)

    def _set_wallpaper(self, name_or_path):
        self.config.load()
        self.config.wallpaper = name_or_path
        self.config.save()
        path = name_or_path if name_or_path.startswith("/") else str(wallpaper_path(name_or_path))
        set_desktop_background(path)
        self._mark_wall(name_or_path)

    def _lock_choice(self):
        try:
            return (DATA_DIR / "lock-wallpaper.choice").read_text().strip() or "sky"
        except OSError:
            return "sky"

    def _set_lock_wallpaper(self, name_or_path):
        path = name_or_path if name_or_path.startswith("/") else str(wallpaper_path(name_or_path))
        try:
            png = render_png(path, DATA_DIR / "lock-wallpaper.png")
        except GLib.Error as e:
            self.toast(f"Couldn't use that picture: {e.message}")
            return
        s = _settings("org.gnome.desktop.screensaver")
        if s:
            s.set_string("picture-uri", Gio.File.new_for_path(str(png)).get_uri())
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        (DATA_DIR / "lock-wallpaper.choice").write_text(name_or_path)
        self._mark_lock(name_or_path)

        def work():
            ok, _msg = run_helper(["wallpaper", str(png)])
            GLib.idle_add(lambda: (self.toast("Lock screen picture set." if ok else
                                              "Set for the lock screen (the login screen couldn't be changed)."), False)[1])

        threading.Thread(target=work, daemon=True).start()

    def _unhide(self, aid, row_child):
        self.config.load()
        self.config.hidden = [h for h in self.config.hidden if h != aid]
        self.config.save()
        row = row_child.get_parent()
        row.get_parent().remove(row)


class SettingsApp(Adw.Application):
    def __init__(self, mode):
        super().__init__(application_id=APP_ID if mode == "settings" else f"{APP_ID}.Setup",
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.mode = mode
        GLib.set_application_name("Tablet Settings")

    def do_startup(self):
        Adw.Application.do_startup(self)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        css = Gtk.CssProvider()
        css.load_from_path(str(HERE / "style.css"))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = PasscodeWindow(self, first_time=True) if self.mode == "setup" else SettingsWindow(self)
        win.present()


def main():
    args = sys.argv[1:]
    # Harbor could start itself at login; it's not a home screen any more, so stop that.
    if os.environ.get("DESKTOP_AUTOSTART_ID") and AUTOSTART_FILE.exists() and not args:
        try:
            AUTOSTART_FILE.unlink()
        except OSError:
            pass
        return 0
    if "--setup-if-needed" in args:
        if passcode_length():
            return 0
        return SettingsApp("setup").run([sys.argv[0]])
    if "--setup-passcode" in args:
        return SettingsApp("setup").run([sys.argv[0]])
    return SettingsApp("settings").run([sys.argv[0]])
