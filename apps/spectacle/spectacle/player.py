"""Full-screen video player.

Video is drawn by libmpv straight into a GTK GLArea, so it plays inside the
app with hardware decoding. mpv fetches YouTube streams itself through
yt-dlp. If embedding isn't possible on some system, Spectacle falls back to
opening the video in a separate full-screen mpv window.
"""

from __future__ import annotations

import ctypes
import locale
import os
import shutil
import subprocess
import sys

from gi.repository import GLib, Gtk, Pango

from .models import Video, fmt_duration

# 720p is the sweet spot for the Latitude 3120's 1366×768 screen. VP9 is
# preferred because the Intel chip decodes it in hardware; AV1 would have
# to be decoded in software and can stutter on a low-power CPU.
STREAM_FORMAT = ("bv*[height<=720][vcodec^=vp9]+ba/bv*[height<=720][vcodec!^=av01]+ba/"
                 "bv*[height<=720]+ba/b[height<=720]/b")

GL_DRAW_FRAMEBUFFER_BINDING = 0x8CA6


def _yt_dlp_path() -> str | None:
    # On Heirloom, 'spectacle update' puts a newer yt-dlp in your home folder.
    override = os.environ.get("SPECTACLE_YTDLP")
    if override and os.path.exists(override):
        return override
    here = os.path.join(os.path.dirname(sys.executable), "yt-dlp")
    return here if os.path.exists(here) else shutil.which("yt-dlp")


def _load_gl():
    for name in ("libOpenGL.so.0", "libGL.so.1"):
        try:
            lib = ctypes.CDLL(name)
            lib.glGetIntegerv.argtypes = [ctypes.c_uint, ctypes.POINTER(ctypes.c_int)]
            return lib
        except OSError:
            continue
    return None


def _proc_address_fn():
    """Return a callable(name: bytes) -> address for the current GL context."""
    for libname, sym in (("libEGL.so.1", "eglGetProcAddress"), ("libGL.so.1", "glXGetProcAddressARB")):
        try:
            lib = ctypes.CDLL(libname)
            fn = getattr(lib, sym)
            fn.restype = ctypes.c_void_p
            fn.argtypes = [ctypes.c_char_p]
            return fn
        except (OSError, AttributeError):
            continue
    return None


class MpvArea(Gtk.GLArea):
    """A GLArea that libmpv renders into."""

    def __init__(self, on_event):
        super().__init__(hexpand=True, vexpand=True, auto_render=False, has_depth_buffer=False)
        self.on_event = on_event  # called on the main thread: (name, value)
        self.mpv = None
        self.ctx = None
        self.failed: str | None = None
        self._gl = _load_gl()
        self._gpa = None
        self._pending: tuple | None = None
        self.connect("realize", self._realize)
        self.connect("unrealize", self._unrealize)
        self.connect("render", self._render)

    # -- setup / teardown ---------------------------------------------------
    def _realize(self, *_):
        self.make_current()
        if self.get_error() is not None:
            self.failed = "OpenGL isn't available"
            return
        try:
            import mpv
        except Exception as e:  # libmpv missing
            self.failed = f"libmpv couldn't load ({e})"
            return
        proc = _proc_address_fn()
        if proc is None or self._gl is None:
            self.failed = "OpenGL libraries not found"
            return
        # mpv refuses to start unless numbers are formatted the C way.
        locale.setlocale(locale.LC_NUMERIC, "C")
        try:
            opts = dict(vo="libmpv", hwdec="auto-safe", keep_open="yes", ytdl=True,
                        ytdl_format=STREAM_FORMAT, input_default_bindings=False,
                        osc=False, cache="yes", demuxer_max_bytes="150MiB")
            ytdlp = _yt_dlp_path()
            if ytdlp:
                opts["script_opts"] = f"ytdl_hook-ytdl_path={ytdlp}"
            self.mpv = mpv.MPV(**opts)
            self._gpa = mpv.MpvGlGetProcAddressFn(lambda _ctx, name: proc(name))
            self.ctx = mpv.MpvRenderContext(self.mpv, "opengl",
                                            opengl_init_params={"get_proc_address": self._gpa})
            self.ctx.update_cb = lambda: GLib.idle_add(self._queue)
        except Exception as e:  # noqa: BLE001
            self.failed = f"Player setup failed ({e})"
            self.mpv = self.ctx = None
            return

        for prop in ("time-pos", "duration", "pause", "eof-reached", "paused-for-cache", "core-idle"):
            self.mpv.observe_property(prop, self._observer(prop))

        @self.mpv.event_callback("end-file")
        def _end(ev):
            reason = getattr(getattr(ev, "data", None), "reason", None)
            if str(reason).lower().endswith("error") or reason == 4:
                GLib.idle_add(lambda: (self.on_event("error", None), False)[1])

        if self._pending:
            self.load(*self._pending)

    def _observer(self, prop):
        def cb(_name, value):
            GLib.idle_add(lambda: (self.on_event(prop, value), False)[1])
        return cb

    def _queue(self):
        self.queue_render()
        return False

    def _unrealize(self, *_):
        if self.ctx:
            self.make_current()
            self.ctx.free()
            self.ctx = None
        if self.mpv:
            self.mpv.terminate()
            self.mpv = None

    def _render(self, area, _context):
        if not self.ctx:
            return False
        fbo = ctypes.c_int(0)
        self._gl.glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, ctypes.byref(fbo))
        scale = self.get_scale_factor()
        w, h = self.get_width() * scale, self.get_height() * scale
        self.ctx.render(flip_y=True, opengl_fbo={"w": w, "h": h, "fbo": fbo.value})
        return True

    # -- control ------------------------------------------------------------
    def load(self, target: str, start: float = 0):
        if not self.mpv:
            self._pending = (target, start)
            return
        self._pending = None
        if start:
            self.mpv.command("loadfile", target, "replace", -1, f"start={start}")
        else:
            self.mpv.command("loadfile", target, "replace")
        self.mpv.pause = False

    def stop(self):
        if self.mpv:
            self.mpv.command("stop")

    def toggle_pause(self):
        if self.mpv:
            self.mpv.pause = not self.mpv.pause

    def seek(self, seconds: float, relative=False):
        if self.mpv:
            self.mpv.seek(seconds, "relative" if relative else "absolute+exact")

    @property
    def position(self) -> float:
        try:
            return float(self.mpv.time_pos or 0) if self.mpv else 0
        except Exception:
            return 0


class PlayerView(Gtk.Overlay):
    """The player page: video plus auto-hiding glossy control bars."""

    def __init__(self, app):
        super().__init__()
        self.add_css_class("player")
        self.app = app
        self.video: Video | None = None
        self.queue: list[Video] = []
        self.duration = 0.0
        self.paused = False
        self._seeking = False
        self._hide_id = 0
        self._save_id = 0

        self.area = MpvArea(self._event)
        self.set_child(self.area)

        # Centered status text (loading / errors)
        self.message = Gtk.Label(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, wrap=True,
                                 justify=Gtk.Justification.CENTER, max_width_chars=50)
        self.message.add_css_class("player-message")
        self.add_overlay(self.message)
        self.spinner = Gtk.Spinner(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, margin_top=80)
        self.spinner.set_size_request(40, 40)
        self.add_overlay(self.spinner)

        # Top bar: Done · title · Watch Later · Download
        top = Gtk.Box(spacing=10, valign=Gtk.Align.START)
        top.add_css_class("player-bar")
        done = Gtk.Button(label="Done")
        done.add_css_class("player-button")
        done.add_css_class("done")
        done.connect("clicked", lambda *_: self.close())
        top.append(done)
        self.title = Gtk.Label(hexpand=True, ellipsize=Pango.EllipsizeMode.END)
        self.title.add_css_class("player-title")
        top.append(self.title)
        self.later = Gtk.ToggleButton(icon_name="spectacle-later-symbolic", tooltip_text="Watch Later")
        self.later.add_css_class("player-button")
        self.later.connect("toggled", self._toggle_later)
        top.append(self.later)
        self.dl = Gtk.Button(icon_name="spectacle-download-symbolic", tooltip_text="Download")
        self.dl.add_css_class("player-button")
        self.dl.connect("clicked", lambda *_: self.video and self.app.download(self.video))
        top.append(self.dl)
        self.channel_btn = Gtk.Button(icon_name="spectacle-person-symbolic", tooltip_text="Go to channel")
        self.channel_btn.add_css_class("player-button")
        self.channel_btn.connect("clicked", self._go_channel)
        top.append(self.channel_btn)

        # Bottom bar: back 10 · play/pause · forward 10 · time · seek · time · next
        bottom = Gtk.Box(spacing=10, valign=Gtk.Align.END)
        bottom.add_css_class("player-bar")
        bottom.add_css_class("bottom")
        back = self._pbtn("spectacle-back-symbolic", lambda: self.area.seek(-10, True), "Back 10 seconds")
        self.play_btn = self._pbtn("spectacle-pause-symbolic", self._toggle_pause, "Play/Pause")
        self.play_btn.add_css_class("big")
        fwd = self._pbtn("spectacle-forward-symbolic", lambda: self.area.seek(10, True), "Forward 10 seconds")
        self.cur = Gtk.Label(label="0:00")
        self.cur.add_css_class("player-time")
        self.seek = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, hexpand=True, draw_value=False)
        self.seek.add_css_class("seek")
        self.seek.set_range(0, 1)
        self.seek.connect("change-value", self._seek_changed)
        self.total = Gtk.Label(label="0:00")
        self.total.add_css_class("player-time")
        self.next_btn = self._pbtn("spectacle-skip-symbolic", self.play_next, "Next video")
        for w in (back, self.play_btn, fwd, self.cur, self.seek, self.total, self.next_btn):
            w.set_valign(Gtk.Align.CENTER)
            bottom.append(w)

        self.bars = []
        for bar in (top, bottom):
            rev = Gtk.Revealer(child=bar, reveal_child=True, transition_duration=220,
                               transition_type=Gtk.RevealerTransitionType.CROSSFADE,
                               valign=bar.get_valign())
            self.add_overlay(rev)
            self.bars.append(rev)

        # Tap the video to show/hide controls; double-tap toggles full screen.
        tap = Gtk.GestureClick()
        tap.connect("released", self._tapped)
        self.area.add_controller(tap)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", lambda *_: self._show_controls())
        self.add_controller(motion)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._key)
        self.add_controller(keys)
        self.set_focusable(True)

    def _pbtn(self, icon, fn, tip):
        b = Gtk.Button(icon_name=icon, tooltip_text=tip)
        b.add_css_class("player-button")
        b.connect("clicked", lambda *_: (fn(), self._show_controls()))
        return b

    # -- opening & closing --------------------------------------------------
    def open(self, video: Video, queue: list[Video] | None = None):
        self.video = video
        self.queue = queue or []
        self.duration = float(video.duration or 0)
        self.title.set_label(video.title)
        self.later.set_active(self.app.library.in_watch_later(video.id))
        local = self.app.library.downloaded(video.id)
        self.dl.set_visible(not local and not video.local_path)
        self.channel_btn.set_visible(bool(video.channel_id))
        self.next_btn.set_sensitive(self._next_video() is not None)
        self.seek.set_value(0)
        self.cur.set_label("0:00")
        self.total.set_label(fmt_duration(self.duration) or "0:00")
        self._busy("Loading…")
        target = (local.local_path if local else None) or video.local_path or video.url
        start = self.app.library.positions.get(video.id, 0)
        self.app.library.record_watch(video)
        self._show_controls()
        self.grab_focus()

        if self.area.failed:
            self._external(target, start)
            return
        self.area.load(target, start)
        # If the embedded player never started, fall back after a moment.
        GLib.timeout_add(1500, self._check_embedded, target, start)
        if not self._save_id:
            self._save_id = GLib.timeout_add_seconds(5, self._save_position)

    def _check_embedded(self, target, start):
        if self.area.failed and self.video and self.app.player_visible():
            self._external(target, start)
        return False

    def _external(self, target, start):
        mpv_bin = shutil.which("mpv")
        if not mpv_bin:
            self._busy(None, f"The built-in player couldn't start: {self.area.failed}.\n"
                             "Install mpv (sudo dnf install mpv) and try again.")
            return
        args = [mpv_bin, "--fs", f"--ytdl-format={STREAM_FORMAT}", f"--start={int(start)}", target]
        ytdlp = _yt_dlp_path()
        if ytdlp:
            args.insert(1, f"--script-opts=ytdl_hook-ytdl_path={ytdlp}")
        subprocess.Popen(args, start_new_session=True)
        self._busy(None, "Playing in a separate window.")

    def close(self):
        self._save_position()
        if self._save_id:
            GLib.source_remove(self._save_id)
            self._save_id = 0
        self.area.stop()
        self.video = None
        self.app.close_player()

    # -- events from mpv ----------------------------------------------------
    def _event(self, name, value):
        if name == "time-pos" and value is not None:
            if not self._seeking:
                self.cur.set_label(fmt_duration(value) or "0:00")
                if self.duration:
                    self.seek.set_value(value / self.duration)
            if self.spinner.get_spinning() and value > 0:
                self._busy(None)
        elif name == "duration" and value:
            self.duration = float(value)
            self.total.set_label(fmt_duration(value))
        elif name == "pause":
            self.paused = bool(value)
            self.play_btn.set_icon_name("spectacle-play-symbolic" if value else "spectacle-pause-symbolic")
            if value:
                self._show_controls(stay=True)
        elif name == "paused-for-cache":
            if value:
                self._busy("Buffering…")
            else:
                self._busy(None)
        elif name == "eof-reached" and value:
            if self.video:
                self.app.library.positions.pop(self.video.id, None)
            nxt = self._next_video()
            if nxt and self.app.autoplay:
                self.open(nxt, self.queue)
            else:
                self._show_controls(stay=True)
        elif name == "error":
            self._busy(None, "This video couldn't be played.\nIt may be private or region-locked, "
                             "or yt-dlp may need an update.")

    def _busy(self, text: str | None, message: str | None = None):
        if text:
            self.spinner.set_spinning(True)
            self.spinner.set_visible(True)
            self.message.set_label(text)
        else:
            self.spinner.set_spinning(False)
            self.spinner.set_visible(False)
            self.message.set_label(message or "")

    # -- controls -----------------------------------------------------------
    def _toggle_pause(self):
        self.area.toggle_pause()

    def _seek_changed(self, _scale, _scroll, value):
        if self.duration:
            self._seeking = True
            self.cur.set_label(fmt_duration(value * self.duration) or "0:00")
            self.area.seek(max(0.0, min(1.0, value)) * self.duration)
            GLib.timeout_add(250, lambda: setattr(self, "_seeking", False) or False)
        self._show_controls()
        return False

    def _toggle_later(self, btn):
        if self.video and btn.get_active() != self.app.library.in_watch_later(self.video.id):
            saved = self.app.library.toggle_watch_later(self.video)
            self.app.toast("Saved to Watch Later" if saved else "Removed from Watch Later")

    def _go_channel(self, *_):
        if self.video and self.video.channel_id:
            cid, name = self.video.channel_id, self.video.channel
            self.close()
            self.app.open_channel(cid, name)

    def _next_video(self):
        if not self.video or not self.queue:
            return None
        ids = [v.id for v in self.queue]
        if self.video.id in ids:
            i = ids.index(self.video.id)
            return self.queue[i + 1] if i + 1 < len(self.queue) else None
        return None

    def play_next(self):
        nxt = self._next_video()
        if nxt:
            self._save_position()
            self.open(nxt, self.queue)

    def _save_position(self):
        if self.video:
            self.app.library.set_position(self.video.id, self.area.position, self.duration or None)
        return True

    def _tapped(self, gesture, n_press, _x, _y):
        if n_press == 2:
            self.app.toggle_fullscreen()
            return
        if self.bars[0].get_reveal_child():
            self._hide_controls()
        else:
            self._show_controls()

    def _show_controls(self, stay=False):
        for b in self.bars:
            b.set_reveal_child(True)
        if self._hide_id:
            GLib.source_remove(self._hide_id)
            self._hide_id = 0
        if not stay and not self.paused:
            self._hide_id = GLib.timeout_add_seconds(3, self._auto_hide)

    def _auto_hide(self):
        self._hide_id = 0
        if not self.paused:
            self._hide_controls()
        return False

    def _hide_controls(self):
        for b in self.bars:
            b.set_reveal_child(False)

    def _key(self, _ctl, keyval, _code, _state):
        from gi.repository import Gdk
        if keyval in (Gdk.KEY_space, Gdk.KEY_k):
            self._toggle_pause()
        elif keyval in (Gdk.KEY_Left, Gdk.KEY_j):
            self.area.seek(-10, True)
        elif keyval in (Gdk.KEY_Right, Gdk.KEY_l):
            self.area.seek(10, True)
        elif keyval == Gdk.KEY_f:
            self.app.toggle_fullscreen()
        elif keyval == Gdk.KEY_Escape:
            self.close()
        else:
            return False
        self._show_controls()
        return True
