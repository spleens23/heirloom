"""Reusable interface pieces: nav bar, tab bar, video cards, grids."""

from __future__ import annotations

from gi.repository import Adw, GLib, Graphene, Gtk, Pango

from . import images
from .models import Video, fmt_ago, fmt_count, fmt_duration


# ---- navigation ---------------------------------------------------------

class NavController(Gtk.Box):
    """A nav bar plus a stack of pages you can push and pop (with a slide)."""

    def __init__(self, root_title: str, root_page: Gtk.Widget, actions=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.add_css_class("spectacle-page")

        self.bar = Gtk.CenterBox()
        self.bar.add_css_class("navbar")
        self.title = Gtk.Label(label=root_title, ellipsize=Pango.EllipsizeMode.END, max_width_chars=28)
        self.title.add_css_class("navbar-title")
        self.bar.set_center_widget(self.title)

        self.back = Gtk.Button(label="‹  Back")
        self.back.add_css_class("bar-button")
        self.back.add_css_class("back")
        self.back.set_valign(Gtk.Align.CENTER)
        self.back.connect("clicked", lambda *_: self.pop())
        self.start_box = Gtk.Box(spacing=6)
        self.start_box.append(self.back)
        self.bar.set_start_widget(self.start_box)

        self.end_box = Gtk.Box(spacing=6)
        self.end_box.set_valign(Gtk.Align.CENTER)
        self.bar.set_end_widget(self.end_box)
        self.append(self.bar)

        self.stack = Gtk.Stack(vexpand=True, hexpand=True, transition_duration=260)
        self.append(self.stack)
        self._pages: list[tuple[Gtk.Widget, str, list]] = []
        self.push(root_page, root_title, actions or [], animate=False)

    def push(self, page: Gtk.Widget, title: str, actions=None, animate=True):
        self._pages.append((page, title, actions or []))
        self.stack.add_child(page)
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT if animate else Gtk.StackTransitionType.NONE)
        self.stack.set_visible_child(page)
        self._sync()

    def pop(self):
        if len(self._pages) < 2:
            return
        page, _, _ = self._pages.pop()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_RIGHT)
        self.stack.set_visible_child(self._pages[-1][0])
        GLib.timeout_add(320, lambda: (self.stack.remove(page), False)[1])
        self._sync()

    def pop_to_root(self):
        while len(self._pages) > 1:
            self.pop()

    def set_actions(self, page: Gtk.Widget, actions):
        for i, (p, t, _) in enumerate(self._pages):
            if p is page:
                self._pages[i] = (p, t, actions)
        self._sync()

    def _sync(self):
        _, title, actions = self._pages[-1]
        self.title.set_label(title)
        self.back.set_visible(len(self._pages) > 1)
        child = self.end_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.end_box.remove(child)
            child = nxt
        for a in actions:
            if a.get_parent():
                a.unparent()
            self.end_box.append(a)


def bar_button(label: str = "", icon: str | None = None, tooltip: str = "", on_click=None) -> Gtk.Button:
    b = Gtk.Button()
    if icon and label:
        box = Gtk.Box(spacing=6)
        box.append(Gtk.Image.new_from_icon_name(icon))
        box.append(Gtk.Label(label=label))
        b.set_child(box)
    elif icon:
        b.set_icon_name(icon)
    else:
        b.set_label(label)
    b.add_css_class("bar-button")
    b.set_valign(Gtk.Align.CENTER)
    if tooltip:
        b.set_tooltip_text(tooltip)
    if on_click:
        b.connect("clicked", lambda *_: on_click())
    return b


class TabBar(Gtk.Box):
    def __init__(self, on_switch):
        super().__init__(homogeneous=True)
        self.add_css_class("tabbar")
        self._buttons: dict[str, Gtk.ToggleButton] = {}
        self._group = None
        self._on_switch = on_switch

    def add_tab(self, name: str, label: str, icon: str):
        btn = Gtk.ToggleButton()
        btn.add_css_class("tab")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        box.append(Gtk.Image.new_from_icon_name(icon))
        box.append(Gtk.Label(label=label))
        btn.set_child(box)
        if self._group:
            btn.set_group(self._group)
        else:
            self._group = btn
        btn.connect("toggled", self._toggled, name)
        self._buttons[name] = btn
        self.append(btn)

    def _toggled(self, btn, name):
        if btn.get_active():
            self._on_switch(name)

    def select(self, name: str):
        self._buttons[name].set_active(True)

    def tapped_again(self, name: str, fn):
        """Tapping the current tab again (pops to the top, like a tablet)."""
        click = Gtk.GestureClick()
        click.connect("released", lambda *_: self._buttons[name].get_active() and fn())
        self._buttons[name].add_controller(click)


# ---- video cards & grids --------------------------------------------------

THUMB_W, THUMB_H = 248, 140


class Thumb(Gtk.Widget):
    """An image that fills a fixed 16:9 box (cropped to fit).

    Unlike Gtk.Picture, it doesn't ask for the image's full size, so grids
    can fit more columns on a small screen.
    """

    def __init__(self, width: int, height: int):
        super().__init__()
        self._w, self._h = width, height
        self.paintable = None
        self.set_overflow(Gtk.Overflow.HIDDEN)

    def set_paintable(self, paintable):
        self.paintable = paintable
        self.queue_draw()

    def do_measure(self, orientation, for_size):
        if orientation == Gtk.Orientation.HORIZONTAL:
            return self._w, self._w, -1, -1
        width = for_size if for_size > 0 else self._w
        h = round(width * self._h / self._w)
        return h, h, -1, -1

    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def do_snapshot(self, snapshot):
        if not self.paintable:
            return
        w, h = self.get_width(), self.get_height()
        pw = self.paintable.get_intrinsic_width() or w
        ph = self.paintable.get_intrinsic_height() or h
        scale = max(w / pw, h / ph)
        sw, sh = pw * scale, ph * scale
        snapshot.push_clip(Graphene.Rect().init(0, 0, w, h))
        snapshot.save()
        pt = Graphene.Point()
        pt.x, pt.y = (w - sw) / 2, (h - sh) / 2
        snapshot.translate(pt)
        self.paintable.snapshot(snapshot, sw, sh)
        snapshot.restore()
        snapshot.pop()


class VideoCard(Gtk.Box):
    def __init__(self, app, video: Video, show_channel: bool = True):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.app = app
        self.video = video
        self.add_css_class("card")
        

        # Thumbnail with duration badge and resume bar
        frame = Gtk.Overlay()
        frame.add_css_class("thumb-frame")
        frame.set_overflow(Gtk.Overflow.HIDDEN)
        self.picture = Thumb(THUMB_W, THUMB_H)
        frame.set_child(self.picture)
        if video.duration:
            badge = Gtk.Label(label=fmt_duration(video.duration), halign=Gtk.Align.END, valign=Gtk.Align.END)
            badge.add_css_class("duration-badge")
            frame.add_overlay(badge)
        pos = app.library.positions.get(video.id)
        if pos and video.duration:
            bar = Gtk.ProgressBar(fraction=min(pos / video.duration, 1), valign=Gtk.Align.END)
            bar.add_css_class("resume-bar")
            frame.add_overlay(bar)
        self.append(frame)
        images.load(video.thumb_url, self.picture.set_paintable)

        title = Gtk.Label(label=video.title, xalign=0, wrap=True, lines=2,
                          ellipsize=Pango.EllipsizeMode.END, max_width_chars=1, hexpand=True)
        title.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        title.add_css_class("card-title")
        self.append(title)

        bottom = Gtk.Box(spacing=6, margin_top=4)
        meta_bits = []
        if show_channel and video.channel:
            meta_bits.append(video.channel)
        if video.local_path:
            meta_bits.append("Downloaded")
        else:
            meta_bits += [b for b in (fmt_count(video.views), fmt_ago(video.published)) if b]
        meta = Gtk.Label(label="  ·  ".join(meta_bits), xalign=0, hexpand=True,
                         ellipsize=Pango.EllipsizeMode.END, max_width_chars=1)
        meta.add_css_class("card-meta")
        bottom.append(meta)

        if video.channel_id and show_channel:
            ch_btn = Gtk.Button(icon_name="spectacle-person-symbolic", tooltip_text="Go to channel")
            ch_btn.add_css_class("pill")
            ch_btn.connect("clicked", lambda *_: app.open_channel(video.channel_id, video.channel))
            bottom.append(ch_btn)

        self.later = Gtk.ToggleButton(icon_name="spectacle-later-symbolic", tooltip_text="Watch Later")
        self.later.add_css_class("pill")
        self.later.set_active(app.library.in_watch_later(video.id))
        self.later.connect("toggled", self._toggle_later)
        bottom.append(self.later)

        if not video.local_path:
            self.dl = Gtk.Button(icon_name="spectacle-download-symbolic", tooltip_text="Download")
            self.dl.add_css_class("pill")
            if app.library.downloaded(video.id):
                self.dl.add_css_class("on")
            self.dl.connect("clicked", lambda *_: app.download(video))
            bottom.append(self.dl)
        self.append(bottom)

    def _toggle_later(self, btn):
        if btn.get_active() != self.app.library.in_watch_later(self.video.id):
            saved = self.app.library.toggle_watch_later(self.video)
            self.app.toast("Saved to Watch Later" if saved else "Removed from Watch Later")


class VideoGrid(Gtk.FlowBox):
    def __init__(self, app, show_channel: bool = True):
        super().__init__(
            homogeneous=True,
            selection_mode=Gtk.SelectionMode.NONE,
            activate_on_single_click=True,
            min_children_per_line=1,
            max_children_per_line=5,
            valign=Gtk.Align.START,
        )
        self.add_css_class("video-grid")
        self.app = app
        self.show_channel = show_channel
        self.videos: list[Video] = []
        self.connect("child-activated", self._activated)

    def set_videos(self, videos: list[Video]):
        self.remove_all()
        self.videos = list(videos)
        for v in self.videos:
            self.append(VideoCard(self.app, v, self.show_channel))

    def _activated(self, _box, child):
        self.app.play(self.videos[child.get_index()], queue=self.videos)


def scroller(child: Gtk.Widget) -> Gtk.ScrolledWindow:
    sw = Gtk.ScrolledWindow(vexpand=True, hexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
    sw.set_child(child)
    sw.set_kinetic_scrolling(True)
    return sw


def section_title(text: str) -> Gtk.Label:
    lbl = Gtk.Label(label=text, xalign=0)
    lbl.add_css_class("section-title")
    return lbl


def empty_state(icon: str, title: str, text: str, buttons=()) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                  valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER, vexpand=True, margin_top=40, margin_bottom=40)
    img = Gtk.Image.new_from_icon_name(icon)
    img.set_pixel_size(96)
    img.add_css_class("empty-icon")
    box.append(img)
    t = Gtk.Label(label=title)
    t.add_css_class("empty-title")
    box.append(t)
    s = Gtk.Label(label=text, wrap=True, justify=Gtk.Justification.CENTER, max_width_chars=44)
    s.add_css_class("hint")
    box.append(s)
    if buttons:
        row = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER, margin_top=8)
        for b in buttons:
            row.append(b)
        box.append(row)
    return box


def glossy_button(label: str, on_click=None, *classes) -> Gtk.Button:
    b = Gtk.Button(label=label, halign=Gtk.Align.CENTER)
    b.add_css_class("glossy")
    for c in classes:
        b.add_css_class(c)
    if on_click:
        b.connect("clicked", lambda *_: on_click())
    return b


def loading_view(text: str = "Loading…") -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                  valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER, vexpand=True)
    sp = Gtk.Spinner(spinning=True)
    sp.set_size_request(36, 36)
    box.append(sp)
    lbl = Gtk.Label(label=text)
    lbl.add_css_class("hint")
    box.append(lbl)
    return box


def avatar(name: str, url: str = "", size: int = 44) -> Adw.Avatar:
    a = Adw.Avatar(size=size, text=name, show_initials=True)
    if url:
        images.load(url, a.set_custom_image)
    return a
