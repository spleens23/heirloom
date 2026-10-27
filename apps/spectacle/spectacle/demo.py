"""Offline stand-in for youtube.py, used to preview the design.

Run with:  SPECTACLE_DEMO=1 spectacle
Thumbnails are plain colored placeholders generated on first run.
"""

from __future__ import annotations

import random
import time

from .models import Channel, Video
from .paths import CACHE_DIR

_DEMO = CACHE_DIR / "demo"
_COLORS = ["#5fa6de", "#e2594f", "#6cbf6a", "#f0b24a", "#9a7fd1", "#4fb7b0", "#d97aa8", "#7c8a99"]
_CHANNELS = [
    ("UCdemo0000000000000000a", "Linux Tinkerers"),
    ("UCdemo0000000000000000b", "Kitchen Science"),
    ("UCdemo0000000000000000c", "Retro Hardware Lab"),
    ("UCdemo0000000000000000d", "Slow Travel"),
]
_TITLES = [
    "Turning an old laptop into a tablet",
    "The perfect weeknight noodles in 15 minutes",
    "Restoring a 2011-era tablet — will it boot?",
    "A quiet morning walk through Kyoto",
    "Why every Linux desktop feels different",
    "How baking soda actually works",
    "Building a custom launcher from scratch",
    "Night train across the Alps",
    "Repairing a sticky keyboard the right way",
    "Ten minutes of rain on a tin roof",
    "Designing glossy buttons with just CSS",
    "Fermentation basics for beginners",
]


def _thumb(i: int) -> str:
    _DEMO.mkdir(parents=True, exist_ok=True)
    path = _DEMO / f"thumb{i % len(_COLORS)}.png"
    if not path.exists():
        try:
            from gi.repository import GdkPixbuf
            color = _COLORS[i % len(_COLORS)].lstrip("#")
            pb = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 480, 270)
            pb.fill(int(color + "ff", 16))
            pb.savev(str(path), "png", [], [])
        except Exception:
            return ""
    return str(path)


def _videos(n: int, channel=None) -> list[Video]:
    rnd = random.Random(42 if channel is None else hash(channel))
    now = time.time()
    out = []
    for i in range(n):
        cid, cname = channel or _CHANNELS[i % len(_CHANNELS)]
        out.append(Video(
            id=f"demo{i:07d}",
            title=_TITLES[i % len(_TITLES)],
            channel=cname, channel_id=cid,
            duration=rnd.randint(90, 3600),
            views=rnd.randint(800, 4_000_000),
            published=now - rnd.randint(3600, 3600 * 24 * 40),
            thumbnail=_thumb(i),
        ))
    return out


def search(query, limit=30):
    time.sleep(0.4)
    return _videos(12)


def search_channels(query, limit=6):
    return [Channel(c, n) for c, n in _CHANNELS]


def resolve_channel_id(text):
    return _CHANNELS[0][0]


def channel_page(channel_id, limit=40):
    time.sleep(0.3)
    name = dict(_CHANNELS).get(channel_id, "Demo Channel")
    ch = Channel(channel_id, name, subscribers=184_000,
                 description="A demo channel used to preview Spectacle's design without a connection.")
    ch.videos = _videos(9, (channel_id, name))
    return ch


def subscription_feed(channels, per_channel=8):
    time.sleep(0.4)
    vids = _videos(15)
    vids.sort(key=lambda v: v.published or 0, reverse=True)
    return vids, []
