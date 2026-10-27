"""Talking to YouTube.

* Subscription feeds use YouTube's public RSS feeds: fast, and they include
  upload dates so the home feed can be sorted newest-first.
* Search and channel pages use yt-dlp's "flat" extraction, which reads the
  listing without resolving every single video.

Everything here is blocking; the interface calls it from worker threads.
"""

from __future__ import annotations

import re
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from .models import Channel, Video

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0"
_NS = {
    "a": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}


class YouTubeError(Exception):
    pass


def _ydl(extra: dict | None = None):
    try:
        import yt_dlp
    except ImportError as e:  # pragma: no cover
        raise YouTubeError("yt-dlp is not installed. Run the Spectacle installer again.") from e
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "noplaylist": False,
        "ignoreerrors": True,
    }
    opts.update(extra or {})
    return yt_dlp.YoutubeDL(opts)


def _best_thumb(thumbs) -> str:
    if not thumbs:
        return ""
    # Prefer a medium-large one: sharp on the Latitude's screen but quick to load.
    scored = [t for t in thumbs if t.get("url")]
    scored.sort(key=lambda t: abs((t.get("width") or 480) - 480))
    return scored[0]["url"] if scored else ""


def _video_from_entry(e: dict, channel: str = "", channel_id: str = "") -> Video | None:
    if not e or not e.get("id"):
        return None
    vid = e["id"]
    if len(vid) != 11:  # skip playlists, shorts shelves, channels, etc.
        return None
    ts = e.get("timestamp") or e.get("release_timestamp")
    return Video(
        id=vid,
        title=e.get("title") or "Untitled",
        channel=e.get("channel") or e.get("uploader") or channel,
        channel_id=e.get("channel_id") or channel_id,
        duration=int(e["duration"]) if e.get("duration") else None,
        views=e.get("view_count"),
        published=float(ts) if ts else None,
        thumbnail=f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
    )


# ---- search -------------------------------------------------------------

def search(query: str, limit: int = 30) -> list[Video]:
    with _ydl() as ydl:
        info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
    if not info:
        raise YouTubeError("Search failed. Check your connection, or update yt-dlp.")
    return [v for v in (_video_from_entry(e) for e in info.get("entries") or []) if v]


def search_channels(query: str, limit: int = 6) -> list[Channel]:
    """Find channels for a query (used for the 'Channels' strip in search)."""
    url = ("https://www.youtube.com/results?search_query="
           + urllib.request.quote(query) + "&sp=EgIQAg%253D%253D")
    with _ydl({"playlistend": limit}) as ydl:
        info = ydl.extract_info(url, download=False)
    out = []
    for e in (info or {}).get("entries") or []:
        cid = e.get("channel_id") or e.get("id") or ""
        if cid.startswith("UC"):
            out.append(Channel(cid, e.get("channel") or e.get("title") or "", _best_thumb(e.get("thumbnails"))))
    return out


# ---- channels -----------------------------------------------------------

def resolve_channel_id(text: str) -> str | None:
    """Accepts a channel ID, a /channel/ URL, an @handle or a handle URL."""
    text = text.strip()
    m = re.search(r"(UC[\w-]{22})", text)
    if m:
        return m.group(1)
    handle = text if text.startswith("http") else f"https://www.youtube.com/{text if text.startswith('@') else '@' + text}"
    with _ydl({"playlistend": 1}) as ydl:
        info = ydl.extract_info(handle, download=False)
    return (info or {}).get("channel_id")


def channel_page(channel_id: str, limit: int = 40) -> Channel:
    url = f"https://www.youtube.com/channel/{channel_id}/videos"
    with _ydl({"playlistend": limit}) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        raise YouTubeError("Couldn't load this channel.")
    name = info.get("channel") or info.get("uploader") or info.get("title", "").removesuffix(" - Videos")
    thumbs = info.get("thumbnails") or []
    # Channel art comes as banners (wide) and avatars (square); pick the avatar.
    avatars = [t for t in thumbs if t.get("width") and t.get("width") == t.get("height")]
    avatar = (max(avatars, key=lambda t: t["width"])["url"] if avatars else "")
    ch = Channel(
        id=channel_id,
        name=name,
        avatar=avatar,
        subscribers=info.get("channel_follower_count"),
        description=(info.get("description") or "").strip(),
    )
    ch.videos = [v for v in (_video_from_entry(e, name, channel_id) for e in info.get("entries") or []) if v]
    # Flat listings lack dates; borrow them from the RSS feed where they overlap.
    try:
        dated = {v.id: v.published for v in _rss(channel_id)}
        for v in ch.videos:
            v.published = v.published or dated.get(v.id)
    except Exception:
        pass
    return ch


# ---- subscription feed (RSS) ---------------------------------------------

def _rss(channel_id: str) -> list[Video]:
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15) as r:
        root = ET.fromstring(r.read())
    author = root.findtext("a:author/a:name", default="", namespaces=_NS)
    out = []
    for entry in root.findall("a:entry", _NS):
        vid = entry.findtext("yt:videoId", namespaces=_NS)
        link = entry.find("a:link", _NS)
        # Shorts show up in the feed too; leave them out of a tablet video feed.
        if not vid or (link is not None and "/shorts/" in link.get("href", "")):
            continue
        published = entry.findtext("a:published", namespaces=_NS)
        stats = entry.find("media:group/media:community/media:statistics", _NS)
        out.append(Video(
            id=vid,
            title=entry.findtext("a:title", default="Untitled", namespaces=_NS),
            channel=author,
            channel_id=channel_id,
            views=int(stats.get("views")) if stats is not None and stats.get("views") else None,
            published=datetime.fromisoformat(published).timestamp() if published else None,
            thumbnail=f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
        ))
    return out


def subscription_feed(channels: list[Channel], per_channel: int = 8) -> tuple[list[Video], list[str]]:
    """Newest videos across all subscriptions. Returns (videos, failed channel names)."""
    videos: list[Video] = []
    failed: list[str] = []

    def fetch(ch: Channel):
        try:
            return ch, _rss(ch.id)[:per_channel]
        except Exception:
            return ch, None

    with ThreadPoolExecutor(max_workers=8) as pool:
        for ch, vids in pool.map(fetch, channels):
            if vids is None:
                failed.append(ch.name)
            else:
                videos.extend(vids)
    videos.sort(key=lambda v: v.published or 0, reverse=True)
    return videos, failed
