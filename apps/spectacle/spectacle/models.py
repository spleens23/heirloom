"""Plain data objects shared by the backend and the interface."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


@dataclass
class Video:
    id: str
    title: str
    channel: str = ""
    channel_id: str = ""
    duration: int | None = None  # seconds
    views: int | None = None
    published: float | None = None  # unix timestamp
    thumbnail: str = ""
    local_path: str = ""  # set for downloaded videos

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.id}"

    @property
    def thumb_url(self) -> str:
        return self.thumbnail or f"https://i.ytimg.com/vi/{self.id}/hqdefault.jpg"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Video":
        known = {k: d.get(k) for k in cls.__dataclass_fields__ if k in d}
        return cls(**known)


@dataclass
class Channel:
    id: str
    name: str
    avatar: str = ""
    subscribers: int | None = None
    description: str = ""
    videos: list[Video] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/channel/{self.id}"

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "avatar": self.avatar}

    @classmethod
    def from_dict(cls, d: dict) -> "Channel":
        return cls(id=d["id"], name=d.get("name", ""), avatar=d.get("avatar", ""))


# ---- formatting helpers -------------------------------------------------

def fmt_duration(seconds: int | float | None) -> str:
    if not seconds:
        return ""
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_count(n: int | None, noun: str = "views") -> str:
    if n is None:
        return ""
    for div, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if n >= div:
            val = n / div
            txt = f"{val:.1f}".rstrip("0").rstrip(".") if val < 10 else f"{val:.0f}"
            return f"{txt}{suffix} {noun}"
    return f"{n} {noun}"


def fmt_ago(ts: float | None) -> str:
    if not ts:
        return ""
    delta = datetime.now(timezone.utc).timestamp() - ts
    for secs, unit in ((31536000, "year"), (2592000, "month"), (604800, "week"),
                       (86400, "day"), (3600, "hour"), (60, "minute")):
        if delta >= secs:
            n = int(delta // secs)
            return f"{n} {unit}{'s' if n != 1 else ''} ago"
    return "just now"
